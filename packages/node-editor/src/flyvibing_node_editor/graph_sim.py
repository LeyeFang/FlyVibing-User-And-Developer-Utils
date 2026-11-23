"""节点图 fake-time 模拟 + 探针（graph-sim/v1）。

第一版语义：**整图执行，按 group/nodes 过滤观测**。这样 TimeTrigger、trial 相位、
变量读写都走引擎真实 evaluator，不伪造子图边界；`--group` 只是把 trace/summary
收窄到该组，并报告组的边界端口（entry/done、data_in/data_out）作为“模拟输入输出”视图。

时间基显式化：默认 fake-time 240 fps（dt=1/240），结果里带 `timebase`；不再隐含 1/60。
`--seconds` / `--frames` / `--fps` / `--dt` 都可控；低帧率会给出 aliasing 警告。
`mode="realtime"` 走 wall-clock 步进，报告实际 fps 与 dt 分位数，用于暴露调度抖动；
`uncapped=True` 进一步取消帧率上限（跑多快算多快），用实际 elapsed_time 和布尔信号
上升沿周期实测频率。所有模式都会在结果里声明 `modes` 与 `hint`，避免把 fake 结论当实测。

边界注入：`set_props` 覆盖节点 props（常量、TimeTrigger 时间等），`stub_pins`
按 output pin 强制注入数据节点输出；变量/计时器仍由 `set_vars` / `set_timers` 覆盖。

输出：
  - summary: 事件计数、每个被观测信号的 transitions / median interval / measured Hz / duty
  - trace: 记录变化帧与有事件的帧（变量/计时器/可见性/引脚/事件）；CLI 默认只回摘要
  - `--out trace.jsonl`: 完整 trace 落盘；`--max-trace N` 可把前 N 条放进 stdout
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import os
import re
import statistics
import time

from flyvibing_node_editor.graph_query import GraphIR, GraphQueryError

SCHEMA = "graph-sim/v1"
DEFAULT_FPS = 240.0
DEFAULT_SECONDS = 3.0
MAX_TRACE = 200
MAX_REALTIME_SECONDS = 10.0
MAX_UNPACED_FRAMES = 2_000_000


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    eid = getattr(value, "eid", None)
    if eid is not None:
        return {"entity_ref": int(eid)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _pin_spec(text: str):
    raw = str(text or "").strip()
    if ":" in raw:
        node, pin = raw.rsplit(":", 1)
    elif "." in raw:
        node, pin = raw.rsplit(".", 1)
    else:
        raise GraphQueryError(f"pin must be @node.pin or @node:pin, got {text!r}")
    node, pin = node.strip(), pin.strip()
    if not node or not pin:
        raise GraphQueryError(f"pin must be @node.pin or @node:pin, got {text!r}")
    return node, pin


def _resolve_scope(ir: GraphIR, group: str | None, nodes: list[str] | None):
    if group:
        kind, gid = ir.resolve(group)
        if kind != "group":
            raise GraphQueryError(f"{group!r} is a node, not a group")
        return set(ir.group_all.get(gid) or set()), {
            "kind": "group",
            "ref": ir.group_ref(gid),
            "group": ir.group_item(gid, with_ports=True),
        }
    if nodes:
        ids = set()
        refs = []
        for raw in nodes:
            kind, ident = ir.resolve(raw)
            refs.append(ir.group_ref(ident) if kind == "group" else ir.node_ref(ident))
            ids.update(ir.group_all.get(ident) or set() if kind == "group" else {ident})
        return ids, {"kind": "nodes", "refs": refs}
    return set(ir.nodes), {"kind": "full", "refs": [f"{len(ir.nodes)} nodes"]}


def _signal_stats(kind: str, name: str, values: list, times: list, dt: float) -> dict:
    changes = []
    prev = object()
    for t, v in zip(times, values):
        if v is None:
            continue
        if v != prev:
            changes.append((t, v))
            prev = v
    intervals = [b[0] - a[0] for a, b in zip(changes, changes[1:]) if b[0] > a[0]]
    median = statistics.median(intervals) if intervals else None
    booleanish = all(v in (0, 1, 0.0, 1.0, True, False) for _, v in changes)
    out = {
        "kind": kind,
        "name": name,
        "samples": len(values),
        "transitions": max(0, len(changes) - 1),
        "first": round(changes[0][0], 6) if changes else None,
        "last": round(changes[-1][0], 6) if changes else None,
        "median_interval": round(median, 6) if median is not None else None,
    }
    # 布尔信号用上升沿间隔测周期：比 1/(2*median_half_period) 更抗抖动/占空比偏差。
    rising = []
    prev_truth = None
    for t, v in changes:
        truth = bool(v)
        if prev_truth is not None and truth and not prev_truth:
            rising.append(t)
        prev_truth = truth
    periods = [b - a for a, b in zip(rising, rising[1:]) if b > a]
    if booleanish and len(periods) >= 2:
        period = statistics.median(periods)
        out["period_ms"] = round(period * 1000.0, 3)
        out["measured_hz"] = round(1.0 / period, 3)
        out["measured_hz_source"] = "rising_edges"
        out["period_min_ms"] = round(min(periods) * 1000.0, 3)
        out["period_max_ms"] = round(max(periods) * 1000.0, 3)
        out["period_jitter_ms"] = round((max(periods) - min(periods)) * 1000.0, 3)
    if median and median > 0:
        out["events_per_sec"] = round(1.0 / median, 3)
        if booleanish and out["transitions"] >= 2 and "measured_hz" not in out:
            out["measured_hz"] = round(1.0 / (2.0 * median), 3)
            out["measured_hz_source"] = "half_period"
    usable = [v for v in values if v is not None]
    if booleanish and usable:
        out["duty"] = round(sum(1 for v in usable if v) / len(usable), 3)
        active_changes = changes
        if changes and changes[0][0] <= 1e-9:
            active_changes = changes[1:]
        if len(active_changes) >= 2 and active_changes[-1][0] > active_changes[0][0]:
            lo, hi = active_changes[0][0], active_changes[-1][0]
            active = [v for t, v in zip(times, values)
                      if v is not None and lo <= t <= hi]
            if active:
                out["duty_active"] = round(sum(1 for v in active if v) / len(active), 3)
    if values:
        numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numeric:
            out["min"] = round(min(numeric), 6)
            out["max"] = round(max(numeric), 6)
            out["last_value"] = _jsonable(values[-1])
        else:
            out["last_value"] = _jsonable(values[-1])
    return out


def _timebase_hint(mode: str, step: float, uncapped: bool = False) -> str:
    fps = (1.0 / step) if step else 0.0
    if uncapped:
        return ("wall-clock 自由运行（不设帧率上限，含调度抖动，不含 GPU/渲染抖动）；"
                "确定性基线用 --mode fake")
    if mode == "realtime":
        return (f"wall-clock 实速（目标 {fps:.1f} fps，含调度抖动，不含 GPU/渲染抖动）；"
                "确定性基线用 --mode fake")
    return (f"fake-time 确定性步进 @ {fps:.1f} fps（不含任何抖动）；"
            "帧抖动/调度边界请用 --mode realtime 或 PIE 复测")


def simulate(
    scene_data: dict,
    *,
    seconds: float = DEFAULT_SECONDS,
    frames: int | None = None,
    fps: float = DEFAULT_FPS,
    dt: float | None = None,
    mode: str = "fake",
    uncapped: bool = False,
    group: str | None = None,
    nodes: list[str] | None = None,
    watch_vars: list[str] | None = None,
    watch_timers: list[str] | None = None,
    watch_pins: list[str] | None = None,
    set_vars: dict | None = None,
    set_timers: dict | None = None,
    set_props: dict | None = None,
    stub_pins: dict | None = None,
    allow_long: bool = False,
    max_trace: int = MAX_TRACE,
    seed: int = 0,
    trace_out: str | None = None,
) -> dict:
    from flyvibing_node_editor.engine_path import ensure_engine_importable
    ensure_engine_importable()
    from Application.Core.NodeGraph.canvas import NodeCanvas
    from Application.Core.NodeGraph.evaluator_engine import ExecutionContext, GraphEvaluator
    from Application.Core.NodeGraph.node_types import _TYPES
    from Application.Core.NodeGraph.validation.dry_run import (
        _DryScene, _cleanup_dry_sessions, _extract_entities, _seed_rng,
    )

    ir = GraphIR(scene_data)
    observed, scope = _resolve_scope(ir, group, nodes)

    mode = str(mode or "fake").lower()
    if uncapped:
        mode = "realtime"
    if mode not in ("fake", "realtime"):
        raise GraphQueryError("mode must be 'fake' or 'realtime'")
    if mode == "realtime" and float(fps or 0.0) <= 0.0:
        uncapped = True
    if uncapped:
        if float(seconds) <= 0:
            raise GraphQueryError("uncapped realtime 需要 --seconds > 0")
        if float(seconds) > MAX_REALTIME_SECONDS and not allow_long:
            raise GraphQueryError(
                f"uncapped realtime 时长 {float(seconds):.1f} s；"
                f"超过 {MAX_REALTIME_SECONDS:.0f} s 请显式 --allow-long"
            )
        step = float(dt) if dt and float(dt) > 0 else 0.0
        frames = max(0, int(frames)) if frames else 0
    else:
        step = float(dt) if dt and float(dt) > 0 else 1.0 / max(1.0, float(fps))
        if frames is None:
            frames = max(1, int(math.ceil(max(0.0, float(seconds)) / step)))
        frames = max(1, int(frames))
        if mode == "realtime" and frames * step > MAX_REALTIME_SECONDS and not allow_long:
            raise GraphQueryError(
                f"realtime 模式约 {frames * step:.1f} s；"
                f"超过 {MAX_REALTIME_SECONDS:.0f} s 请显式 --allow-long"
            )

    pin_watch = []
    for raw in watch_pins or []:
        node_ref, pin_name = _pin_spec(raw)
        kind, ident = ir.resolve(node_ref)
        if kind != "node":
            raise GraphQueryError(f"pin watch must target a node, got {node_ref!r}")
        pid = (ir.node_pins.get(ident) or {}).get(pin_name)
        if pid is None:
            raise GraphQueryError(f"unknown pin {pin_name!r} on {ir.node_ref(ident)}")
        pin_watch.append({"node": ident, "ref": ir.node_ref(ident), "pin": pin_name,
                          "pid": int(pid), "value": None})

    graph = copy.deepcopy(ir.graph)
    prop_overrides = {}
    for ref, props in (set_props or {}).items():
        kind, ident = ir.resolve(str(ref))
        if kind != "node":
            raise GraphQueryError(f"set-prop target must be a node, got {ref!r}")
        node = (graph.get("nodes") or {}).get(str(ident))
        if not isinstance(node, dict):
            raise GraphQueryError(f"unknown node {ref!r}")
        if not isinstance(props, dict):
            raise GraphQueryError(f"set-prop {ref!r} must be a mapping")
        node.setdefault("props", {}).update(props)
        prop_overrides[ir.node_ref(ident)] = dict(props)

    observed_vars = set()
    observed_timers = set()
    for nid in observed:
        nd = (graph.get("nodes") or {}).get(str(nid)) or {}
        node_type = nd.get("node_type")
        props = nd.get("props") or {}
        if node_type in ("VarGet", "VarSet") and props.get("var_name"):
            observed_vars.add(str(props["var_name"]))
        if node_type in ("TimeTrigger", "SetTimer", "NewTimer", "TimeGetElapsed"):
            timer = props.get("timer") or props.get("timer_name")
            if timer:
                observed_timers.add(str(timer))
    try:
        canvas = NodeCanvas.from_dict(graph)
    except Exception as e:  # noqa: BLE001
        return {"schema": SCHEMA, "ok": False, "errors": [f"canvas: {e}"],
                "timebase": {"mode": mode, "uncapped": uncapped,
                             "fps": round(1.0 / step, 3) if step else 0.0,
                             "dt": step, "frames": frames,
                             "duration": round(frames * step, 6),
                             "modes": ["fake", "realtime"],
                             "hint": _timebase_hint(mode, step, uncapped)}}

    evaluator = GraphEvaluator(canvas, _TYPES)
    stub_by_pid = {}
    inject_by_pid = {}
    stub_items = []
    for raw, value in (stub_pins or {}).items():
        node_ref, pin_name = _pin_spec(str(raw))
        kind, ident = ir.resolve(node_ref)
        if kind != "node":
            raise GraphQueryError(f"stub target must be a node, got {node_ref!r}")
        pid = (ir.node_pins.get(ident) or {}).get(pin_name)
        if pid is None:
            raise GraphQueryError(f"unknown pin {pin_name!r} on {ir.node_ref(ident)}")
        inst = canvas.nodes.get(ident)
        nd = _TYPES.get(inst.node_type) if inst is not None else None
        spec = next((p for p in (getattr(nd, "pins", []) or []) if p.name == pin_name), None)
        if spec is None:
            raise GraphQueryError(f"unknown pin {pin_name!r} on {ir.node_ref(ident)}")
        direction = str(getattr(spec, "direction", "") or "")
        if direction == "output":
            stub_by_pid[int(pid)] = value
        elif direction == "input" and str(getattr(spec, "kind", "") or "") == "data":
            inject_by_pid[int(pid)] = value
        else:
            raise GraphQueryError(
                f"stub target {raw!r} must be a data pin (input or output); exec pins are not injectable"
            )
        stub_items.append({"ref": f"{ir.node_ref(ident)}.{pin_name}",
                           "direction": direction, "value": _jsonable(value)})

    if stub_by_pid:
        original_ensure = evaluator._ensure_pin_evaluated

        def _ensure_with_stub(output_pin_id, exec_ctx):
            if output_pin_id in stub_by_pid:
                exec_ctx.set_pin(output_pin_id, stub_by_pid[output_pin_id])
                return
            original_ensure(output_pin_id, exec_ctx)

        evaluator._ensure_pin_evaluated = _ensure_with_stub

    if inject_by_pid:
        original_read = evaluator._read_input

        def _read_with_stub(input_pin_id, exec_ctx):
            if input_pin_id in inject_by_pid:
                return inject_by_pid[input_pin_id]
            return original_read(input_pin_id, exec_ctx)

        evaluator._read_input = _read_with_stub

    ctx = ExecutionContext()
    ctx.dry_run = True
    ctx.scene = _DryScene(_extract_entities(scene_data))
    entries: list[dict] = []
    frame_holder = {"frame": 0}

    def log(node_id, node_type, action, detail=""):
        entries.append({"frame": frame_holder["frame"], "t": round(ctx.elapsed_time, 6),
                        "node": int(node_id),
                        "node_type": str(node_type), "action": str(action),
                        "detail": str(detail)})

    ctx.log = log
    _seed_rng(seed)

    errors: list[str] = []
    variables: dict[str, list] = {}
    timers: dict[str, list] = {}
    visible: dict[int, list] = {}
    pin_values: dict[tuple, list] = {p["pid"]: [] for p in pin_watch}
    times: list[float] = []

    # eid → 场景里的名字（可见性用）
    entity_names = {}
    visible_state = {}
    scene = scene_data.get("scene") if isinstance(scene_data.get("scene"), dict) else scene_data
    for eid_raw, ent in ((scene or {}).get("entities") or {}).items():
        try:
            eid = int(eid_raw)
            entity_names[eid] = str((ent or {}).get("name") or f"#{eid_raw}")
            mr = ((ent or {}).get("components") or {}).get("MeshRenderer") or {}
            visible_state[eid] = bool(mr.get("visible", True))
        except (TypeError, ValueError):
            continue
    processed_events = 0

    def sync_visible():
        nonlocal processed_events
        for e in entries[processed_events:]:
            if e.get("action") != "set_visible":
                continue
            m = re.search(r"eid=(-?\d+), visible=(True|False)", e.get("detail") or "")
            if m:
                visible_state[int(m.group(1))] = (m.group(2) == "True")
        processed_events = len(entries)

    def frame_t(frame: int) -> float:
        if frame <= 0:
            return 0.0
        if frame - 1 < len(times):
            return float(times[frame - 1])
        return float(frame) * step

    def snapshot(frame: int, initial: bool = False):
        nonlocal variables, timers
        changed = {}
        if frame == 0:
            for key in (watch_vars if watch_vars is not None else list(ctx._variables)):
                variables.setdefault(key, [])
                v = _jsonable(ctx.get_var(key))
                variables[key].append(v)
                changed.setdefault("vars", {})[key] = v
            for key in (watch_timers if watch_timers is not None else list(ctx._timers)):
                timers.setdefault(key, [])
                v = ctx.get_timer(key)
                timers[key].append(v)
                changed.setdefault("timers", {})[key] = v
        else:
            watch_v = watch_vars if watch_vars is not None else list(ctx._variables)
            for key in watch_v:
                variables.setdefault(key, [])
                if len(variables[key]) < frame:
                    variables[key].extend([None] * (frame - len(variables[key])))
                v = _jsonable(ctx.get_var(key))
                variables[key].append(v)
                if variables[key][-2:-1] and variables[key][-2] != v:
                    changed.setdefault("vars", {})[key] = v
            watch_t = watch_timers if watch_timers is not None else list(ctx._timers)
            for key in watch_t:
                timers.setdefault(key, [])
                if len(timers[key]) < frame:
                    timers[key].extend([None] * (frame - len(timers[key])))
                v = ctx.get_timer(key)
                timers[key].append(v)
                if key not in timers or len(timers[key]) == 1:
                    changed.setdefault("timers", {})[key] = v
        for eid, val in visible_state.items():
            visible.setdefault(int(eid), [])
            if len(visible[int(eid)]) < frame:
                visible[int(eid)].extend([None] * (frame - len(visible[int(eid)])))
            visible[int(eid)].append(bool(val))
            if len(visible[int(eid)]) > 1 and visible[int(eid)][-2] != visible[int(eid)][-1]:
                changed.setdefault("visible", {})[entity_names.get(int(eid), f"#{eid}")] = bool(val)
        for item in pin_watch:
            val = _jsonable(ctx.get_pin(item["pid"]))
            pin_values[item["pid"]].append(val)
            if len(pin_values[item["pid"]]) > 1 and pin_values[item["pid"]][-2] != val:
                changed.setdefault("pins", {})[f"{item['ref']}.{item['pin']}"] = val
        new_entries = [e for e in entries
                       if e["frame"] == frame and e["node"] in observed]
        if changed or new_entries:
            changed = {"frame": frame, "t": round(frame_t(frame), 6), **changed}
            if new_entries:
                changed["events"] = new_entries
            return changed
        return None

    trace: list[dict] = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ctx.elapsed_time = 0.0
            ctx.delta_time = 0.0
            try:
                evaluator.trigger("OnGameStart", ctx)
            except Exception as e:  # noqa: BLE001
                errors.append(f"OnGameStart: {type(e).__name__}: {e}")
            sync_visible()
            for key, value in (set_vars or {}).items():
                ctx.set_var(str(key), value)
            for key, value in (set_timers or {}).items():
                if not ctx.has_timer(str(key)):
                    ctx.create_timer(str(key))
                try:
                    ctx.set_timer(str(key), float(value))
                except (TypeError, ValueError):
                    errors.append(f"set-timer {key!r}: value must be numeric")
            initial = snapshot(0, initial=True)
            if initial:
                trace.append(initial)

            completed = 0
            realtime = mode == "realtime"
            clock = time.perf_counter
            wall_start = clock()
            next_deadline = wall_start
            prev_tick = wall_start
            dt_samples: list[float] = []
            overruns = 0
            frame = 0
            while True:
                frame += 1
                if uncapped:
                    if frames and frame > frames:
                        break
                    if (clock() - wall_start) >= float(seconds):
                        break
                    if frame > MAX_UNPACED_FRAMES:
                        errors.append(
                            f"uncapped 达到安全上限 {MAX_UNPACED_FRAMES} 帧；请缩短 --seconds"
                        )
                        break
                elif frame > frames:
                    break
                frame_holder["frame"] = frame
                if uncapped:
                    now = clock()
                    actual_dt = max(0.0, now - prev_tick)
                    prev_tick = now
                    dt_samples.append(actual_dt)
                    ctx.elapsed_time = now - wall_start
                    ctx.delta_time = actual_dt
                elif realtime:
                    next_deadline += step
                    delay = next_deadline - clock()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        overruns += 1
                        next_deadline = clock()
                    now = clock()
                    actual_dt = max(0.0, now - prev_tick)
                    prev_tick = now
                    dt_samples.append(actual_dt)
                    ctx.elapsed_time = now - wall_start
                    ctx.delta_time = actual_dt
                else:
                    ctx.elapsed_time += step
                    ctx.delta_time = step
                times.append(round(ctx.elapsed_time, 6))
                try:
                    evaluator.trigger("OnFrameUpdate", ctx)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"frame {frame}: {type(e).__name__}: {e}")
                    break
                sync_visible()
                entry = snapshot(frame)
                if entry:
                    trace.append(entry)
                completed = frame
            loop_end = clock()
            try:
                evaluator.trigger("OnGameStop", ctx)
            except Exception as e:  # noqa: BLE001
                errors.append(f"OnGameStop: {type(e).__name__}: {e}")
    finally:
        _cleanup_dry_sessions()

    total_events = len(entries)
    observed_events = [e for e in entries if e["node"] in observed]
    by_node = {}
    for e in observed_events:
        key = (e["node"], e["node_type"])
        by_node.setdefault(key, []).append(e)
    event_stats = []
    for (nid, ntype), items in sorted(by_node.items()):
        stamps = [float(i.get("t", i["frame"] * step)) for i in items]
        intervals = [b - a for a, b in zip(stamps, stamps[1:]) if b > a]
        med = statistics.median(intervals) if intervals else None
        record = {
            "node": nid, "ref": ir.node_ref(nid), "type": ntype,
            "fires": len(items),
            "median_interval": round(med, 6) if med is not None else None,
            "events_per_sec": round(1.0 / med, 3) if med else None,
        }
        if med and ntype in ("TimeTrigger", "EntitySetRenderVisible",
                             "EntityGroupSetVisible", "EntityListSetVisible"):
            record["measured_hz"] = round(1.0 / (2.0 * med), 3)
        event_stats.append(record)

    observed_eids = set()
    for e in observed_events:
        if e.get("action") == "set_visible":
            m = re.search(r"eid=(-?\d+)", e.get("detail") or "")
            if m:
                observed_eids.add(int(m.group(1)))

    signals = {"visible": [], "vars": [], "timers": [], "pins": []}
    for eid, vals in visible.items():
        if scope.get("kind") != "full" and (not observed_eids or eid not in observed_eids):
            continue
        if len(set(vals)) > 1:
            signals["visible"].append(_signal_stats("visible", entity_names.get(eid, f"#{eid}"),
                                                    vals, [0.0] + times, step))
    for key, vals in variables.items():
        if scope.get("kind") != "full" and watch_vars is None and key not in observed_vars:
            continue
        if len(set(map(str, vals))) > 1:
            signals["vars"].append(_signal_stats("var", key, vals, [0.0] + times, step))
    for key, vals in timers.items():
        if scope.get("kind") != "full" and watch_timers is None and key not in observed_timers:
            continue
        numeric = [v for v in vals if isinstance(v, (int, float))]
        if numeric:
            signals["timers"].append({
                "kind": "timer", "name": key, "samples": len(vals),
                "last_value": _jsonable(vals[-1]),
                "min": round(min(numeric), 6), "max": round(max(numeric), 6),
            })
    for item in pin_watch:
        vals = pin_values[item["pid"]]
        if len(set(map(str, vals))) > 1:
            signals["pins"].append(_signal_stats("pin", f"{item['ref']}.{item['pin']}",
                                                 vals, [0.0] + times, step))

    elapsed_total = ((loop_end - wall_start) if realtime and loop_end else completed * step)
    measured = None
    if realtime and dt_samples:
        ordered = sorted(dt_samples)
        def _pick(q: float) -> float:
            idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
            return ordered[idx]
        measured = {
            "fps": round(len(dt_samples) / max(1e-9, sum(dt_samples)), 3),
            "dt_ms": {
                "min": round(ordered[0] * 1000.0, 3),
                "p50": round(_pick(0.50) * 1000.0, 3),
                "p95": round(_pick(0.95) * 1000.0, 3),
                "max": round(ordered[-1] * 1000.0, 3),
            },
            "overruns": overruns,
        }

    warnings = []
    if not realtime and step > 1.0 / 120.0 + 1e-9:
        warnings.append(
            f"timebase {1.0/step:.1f} fps: 高频信号（如 9/11 Hz 闪烁）会被量化/混叠；"
            "请用 --fps 240 或 --dt 0.0041667 复测，并以实测 Hz 为准。"
        )
    if realtime:
        warnings.append(
            "realtime 模式只包含进程调度抖动，不含 GPU/渲染抖动；"
            "渲染级时序问题仍需 PIE + probe 复测。"
        )
        if uncapped:
            warnings.append(
                "uncapped 不设帧率上限；不同机器/负载下帧数与实测频率会变化，"
                "适合频率标定，不适合作为可复现 CI 基线。"
            )
        elif measured and step > 0 and measured["dt_ms"]["p95"] > step * 1500.0:
            warnings.append(
                f"realtime 未达到目标步长：p95 {measured['dt_ms']['p95']} ms "
                f"> {step * 1000.0:.1f} ms × 1.5；结论按 measured 值解读。"
            )

    trace_truncated = False
    full_trace = trace
    if trace_out:
        out_path = os.path.abspath(trace_out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for item in trace:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        trace = []
    else:
        if len(trace) > max_trace:
            trace = trace[:max_trace]
            trace_truncated = True

    return {
        "schema": SCHEMA,
        "ok": not errors,
        "errors": errors,
        "timebase": {
            "mode": mode,
            "uncapped": uncapped,
            "fps": round(1.0 / step, 3) if step > 0 else 0.0,
            "dt": step,
            "frames": completed,
            "duration": round(elapsed_total, 6),
            "seed": seed,
            "modes": ["fake", "realtime"],
            "hint": _timebase_hint(mode, step, uncapped),
            **({"measured": measured} if measured else {}),
        },
        "scope": scope,
        "inputs": {"vars": set_vars or {}, "timers": set_timers or {},
                   "props": prop_overrides, "stubs": stub_items,
                   "uncapped": uncapped},
        "counts": {"events_total": total_events, "events_observed": len(observed_events)},
        "events": event_stats,
        "signals": signals,
        "trace": trace,
        "trace_truncated": trace_truncated,
        "trace_saved": out_path if trace_out else None,
        "trace_entries": len(full_trace),
        "warnings": warnings,
    }


def render_summary(result: dict) -> str:
    tb = result.get("timebase") or {}
    scope = result.get("scope") or {}
    if scope.get("kind") == "group":
        g = scope.get("group") or {}
        ports = g.get("ports") or {}
        scope_text = (f"{g.get('ref')} [{g.get('type')}] members={g.get('member_count')} "
                      f"ports=" + ",".join(f"{k}:{len(v)}" for k, v in ports.items()))
    elif scope.get("kind") == "nodes":
        scope_text = ", ".join(scope.get("refs") or [])
    else:
        scope_text = "full graph"
    if tb.get("uncapped"):
        measured = tb.get("measured") or {}
        dt_ms = measured.get("dt_ms") or {}
        tb_text = (f"realtime uncapped → measured {measured.get('fps', '-')} fps "
                   f"(p50 {dt_ms.get('p50', '-')} ms / p95 {dt_ms.get('p95', '-')} ms / "
                   f"max {dt_ms.get('max', '-')} ms)")
    elif tb.get("mode") == "realtime":
        measured = tb.get("measured") or {}
        dt_ms = measured.get("dt_ms") or {}
        tb_text = (f"realtime target {tb.get('fps', 0)} fps → measured "
                   f"{measured.get('fps', '-')} fps (p50 {dt_ms.get('p50', '-')} ms / "
                   f"p95 {dt_ms.get('p95', '-')} ms / max {dt_ms.get('max', '-')} ms)")
    else:
        tb_text = f"fake @ {tb.get('fps', 0)} fps (dt={tb.get('dt', '-')} s, deterministic)"
    lines = [
        f"simulate {'ok' if result.get('ok') else 'FAILED'}: "
        f"{tb.get('frames', 0)} frames ({tb.get('duration', 0):.3f} s)",
        f"timebase: {tb_text}",
        f"timebase hint: {tb.get('hint', '')}",
        f"scope: {scope_text}",
        f"events: {result.get('counts', {}).get('events_observed', 0)} observed / "
        f"{result.get('counts', {}).get('events_total', 0)} total",
    ]
    for s in (result.get("signals") or {}).get("visible", []):
        lines.append(
            f"  visible {s['name']}: transitions={s['transitions']} "
            f"measured_hz={s.get('measured_hz', '-')} "
            f"period_ms={s.get('period_ms', '-')} "
            f"jitter_ms={s.get('period_jitter_ms', '-')} "
            f"duty={s.get('duty', '-')} active_duty={s.get('duty_active', '-')}"
        )
    for s in (result.get("signals") or {}).get("vars", []):
        lines.append(f"  var {s['name']}: transitions={s['transitions']} "
                     f"last={s.get('last_value')}")
    for s in (result.get("signals") or {}).get("timers", []):
        lines.append(f"  timer {s['name']}: last={s.get('last_value')} "
                     f"min={s.get('min')} max={s.get('max')}")
    for e in result.get("events") or []:
        lines.append(f"  event {e['ref']} [{e['type']}]: fires={e['fires']} "
                     f"events_per_sec={e.get('events_per_sec', '-')} "
                     f"measured_hz={e.get('measured_hz', '-')}")
    inputs = result.get("inputs") or {}
    input_parts = []
    if inputs.get("vars"):
        input_parts.append("vars=" + json.dumps(inputs["vars"], ensure_ascii=False))
    if inputs.get("timers"):
        input_parts.append("timers=" + json.dumps(inputs["timers"], ensure_ascii=False))
    if inputs.get("props"):
        input_parts.append("props=" + json.dumps(inputs["props"], ensure_ascii=False))
    if inputs.get("stubs"):
        input_parts.append("stubs=" + json.dumps(inputs["stubs"], ensure_ascii=False))
    if input_parts:
        lines.append("inputs: " + "; ".join(input_parts))
    if result.get("trace_saved"):
        lines.append(f"trace: {result['trace_saved']} ({result.get('trace_entries')} entries)")
    elif result.get("trace_truncated"):
        if result.get("trace"):
            lines.append(f"trace: {len(result.get('trace') or [])} entries (truncated)")
        else:
            lines.append(f"trace: omitted ({result.get('trace_entries', 0)} entries; use --out or --max-trace)")
    for w in result.get("warnings") or []:
        lines.append(f"! {w}")
    for e in result.get("errors") or []:
        lines.append(f"x {e}")
    return "\n".join(lines)

"""静态执行流分析（V1）— 不执行、不连引擎，回答"这么连会发生什么顺序"。

定位:
    与 `node_graph_validator` 的 L1/L2 互补 —— 校验回答"对不对"，本模块回答"怎么跑"。
    纯链路遍历 + 节点元数据，无副作用、无 timer 依赖、无随机性。

用法:
    python -m flyvibing_node_editor.cli flow --scene X [--event OnFrameUpdate]
    python -m flyvibing_node_editor.cli flow --scene X --from 229 --data
    python -m flyvibing_node_editor.cli flow --scene X --event OnFrameUpdate --json

输出契约（行格式稳定，供 `--expect` 与 diff 复用）:
    #148 OnFrameUpdate
      #228 Sequence
        <out_0> #229 TimeTrigger thr=0 timer=trial_phase [GATE]
          #224 VarSet trial=1
    - 缩进 2 空格/层
    - `<pin>` 前缀表示经由哪个 exec 输出进入
    - `[GATE]` = 运行时可能阻塞（TimeTrigger 未到阈值 / 一次性训练节点）
    - `[TERMINAL]` = 执行到此结束
    - `[RE-ENTRY]` = 同一 tick 内该节点已执行过（引擎 `_exec_visited` 会跳过）

与引擎语义对齐（`evaluator_engine._walk_exec`）:
    - 默认按节点类型定义中 exec output 引脚顺序遍历；
    - `Branch` 只走 True/False 一路（本模块两边都展示，并标出条件来源）；
    - 任何节点被标记 `_blocked` 时不再向下遍历（本模块显示为 GATE）。
"""

from __future__ import annotations

from flyvibing_node_editor.engine_path import ensure_engine_importable
from flyvibing_node_editor.node_graph_validator import extract_graph_data

# 运行时会阻塞的节点类型（静态分析只标注，不判定实际是否放行）
GATE_TYPES = {
    "TimeTrigger": "thr",
    "TrainFBCSP": "one-shot",
}

_EVENT_TYPES = {"OnGameStart", "OnFrameUpdate", "OnGameStop"}

TERMINAL_TYPES = {"ExitGame", "Return", "Break"}

# 只对这些"结构分叉/事件入口"报告未连接的死端（链尾叶子节点不报，避免噪声）
_DEAD_END_WORTHY = {"OnGameStart", "OnFrameUpdate", "OnGameStop", "Sequence", "Branch"}

# 节点行尾部提示：{type: 从 props 提取哪些键}
_PROP_HINTS = {
    "TimeTrigger": ("time", "timer"),
    "VarSet": ("var_name", "value"),
    "VarGet": ("var_name",),
    "Constant": ("value",),
    "EntitySpawn": ("template",),
    "EntityGet": ("entity_name", "name"),
    "EntitySetRenderVisible": ("visible",),
    "ParallelSend": ("address",),
    "SerialSend": ("port",),
    "SetTimer": ("operate", "timer_name", "value"),
    "NewTimer": ("timer_name",),
    "Random": ("distribution", "min", "max"),
    "Compare": ("operation",),
    "ScalarMath": ("operation",),
    "Sequence": (),
}


def _fmt_value(value) -> str:
    if isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)
    if len(text) > 60:
        text = text[:57] + "..."
    return text


def _node_hint(node_type: str, props: dict) -> str:
    if node_type == "EntitySetRenderVisible":
        # 该节点的可见性通常来自 pin；props 兜底
        pass
    keys = _PROP_HINTS.get(node_type)
    if not keys:
        return ""
    parts = []
    for key in keys:
        if key in props:
            parts.append(f"{key}={_fmt_value(props[key])}")
    return " ".join(parts)


def _exec_outputs(type_def, inst_pins: dict) -> list[tuple[str, int]]:
    """[(pin_name, instance_pin_id)] — 按类型定义顺序。"""
    out = []
    for pin in type_def.pins:
        if pin.kind == "exec" and pin.direction == "output":
            pid = inst_pins.get(pin.name)
            if pid is not None:
                out.append((pin.name, pid))
    return out


def _input_source(pin_owner: dict[int, tuple[int, str]], links: dict,
                  inst_pins: dict, pin_name: str):
    """返回某个输入 pin 的上游 (node_id, pin_name)；无连线返回 None。"""
    inst_pid = inst_pins.get(pin_name)
    if inst_pid is None:
        return None
    for link in links.values():
        try:
            if int(link.get("to_pin", -1)) != int(inst_pid):
                continue
            owner = pin_owner.get(int(link.get("from_pin", -1)))
        except (KeyError, TypeError, ValueError):
            continue
        if owner:
            return owner
    return None


def analyze_flow(
    scene_data: dict,
    *,
    event: str = "OnFrameUpdate",
    start: int | None = None,
    max_depth: int = 24,
    max_lines: int = 120,
    include_data: bool = False,
    data_depth: int = 1,
) -> dict:
    """静态执行流分析。

    Args:
        scene_data: .scene JSON / 裸 graph / 旧格式（extract_graph_data 兼容）。
        event:      起始事件节点类型（start 为空时生效）。
        start:      显式起始节点 id（优先于 event）。
        max_depth:  最大展开深度。
        max_lines:  输出行预算（超出截断并标记 truncated）。
        include_data: 是否附带数据输入的上游来源。

    Returns:
        {ok, start, summary, lines, warnings}
    """
    ensure_engine_importable()
    from Application.Core.NodeGraph.node_types import _TYPES

    graph = extract_graph_data(scene_data)
    nodes: dict = graph.get("nodes") or {}
    links: dict = graph.get("links") or {}

    lines: list[str] = []
    warnings: list[str] = []
    summary = {"nodes": 0, "steps": 0, "gates": 0, "terminals": 0,
               "re_entries": 0, "cycles": 0, "truncated": False}

    if not nodes:
        return {"ok": False, "start": None, "summary": summary,
                "lines": [], "warnings": ["no nodes in graph"]}

    # pin_id → (node_id, pin_name)
    pin_owner: dict[int, tuple[int, str]] = {}
    for nid_str, nd in nodes.items():
        nid = int(nid_str)
        for pin_name, pid in (nd.get("pin_ids") or {}).items():
            pin_owner[int(pid)] = (nid, str(pin_name))

    # 组槽位 → 内部节点；flow 行标注单进单出边界
    group_slots: dict[int, str] = {}
    for gid, grp in (graph.get("node_groups") or {}).items():
        alias = str(grp.get("alias") or gid)
        for slot_name in ("entry", "done"):
            pin = (grp.get("slots") or {}).get(slot_name)
            if pin is None:
                continue
            owner = pin_owner.get(int(pin))
            if owner:
                tag = "IN" if slot_name == "entry" else "OUT"
                group_slots[owner[0]] = f"@{alias} {tag}"

    # 下游索引: from_pin_id → [(to_node_id, to_pin_name)]
    downstream: dict[int, list[tuple[int, str]]] = {}
    for link in links.values():
        try:
            from_pin = int(link["from_pin"])
            to_pin = int(link["to_pin"])
        except (KeyError, TypeError, ValueError):
            continue
        owner = pin_owner.get(to_pin)
        if owner:
            downstream.setdefault(from_pin, []).append(owner)

    # 起始节点
    start_id: int | None = None
    if start is not None:
        start_id = int(start) if str(start) in nodes else None
    else:
        for nid_str, nd in nodes.items():
            if nd.get("node_type") == event:
                start_id = int(nid_str)
                break
    if start_id is None:
        return {"ok": False, "start": None, "summary": summary, "lines": [],
                "warnings": [f"start node not found (event={event!r}, start={start!r})"]}

    visited: set[int] = set()
    on_path: list[int] = []
    budget_exceeded = False

    created_timers = {
        str((nd.get("props") or {}).get("timer_name", ""))
        for nd in nodes.values()
        if nd.get("node_type") == "NewTimer"
    }

    def _emit(depth: int, text: str) -> bool:
        nonlocal budget_exceeded
        if len(lines) >= max_lines:
            budget_exceeded = True
            return False
        lines.append("  " * depth + text)
        return True

    def _label(nid: int) -> str:
        nd = nodes[str(nid)]
        node_type = nd.get("node_type", "?")
        props = nd.get("props") or {}
        hint = _node_hint(node_type, props)
        alias = nd.get("alias")
        name = f"#{nid}@{alias}" if alias else f"#{nid}"
        tag = ""
        if node_type in GATE_TYPES:
            tag = " [GATE]"
            summary["gates"] += 1
        elif node_type in TERMINAL_TYPES:
            tag = " [TERMINAL]"
            summary["terminals"] += 1
        group_tag = group_slots.get(nid)
        if group_tag:
            tag += f" [group {group_tag}]"
        if node_type == "TimeTrigger":
            timer = str(props.get("timer") or props.get("timer_name") or "")
            if timer and timer not in created_timers:
                tag += " [NO TIMER]"
                warnings.append(
                    f"#{nid} {node_type}: timer {timer!r} is never created (NewTimer missing)")
        elif node_type == "SetTimer":
            # SetTimer 默认 create_if_missing=true: 首次写入时自动创建 timer,
            # 只有显式关闭惰性创建时才需要 NewTimer。
            timer = str(props.get("timer") or props.get("timer_name") or "")
            lazy = props.get("create_if_missing", True) is not False
            if timer and not lazy and timer not in created_timers:
                tag += " [NO TIMER]"
                warnings.append(
                    f"#{nid} {node_type}: timer {timer!r} is never created "
                    f"(create_if_missing=false and NewTimer missing)")
        suffix = f" {hint}" if hint else ""
        return f"{name} {node_type}{suffix}{tag}"

    def _emit_data(nid: int, indent: int, level: int, seen: set[int]) -> None:
        """递归展开数据输入（`--data`）：显示上游节点及其属性值。"""
        if level >= data_depth:
            return
        nd = nodes.get(str(nid))
        if not nd:
            return
        td = _TYPES.get(nd.get("node_type", ""))
        if not td:
            return
        pins = nd.get("pin_ids") or {}
        for pin in td.pins:
            if pin.kind != "data" or pin.direction != "input":
                continue
            src = _input_source(pin_owner, links, pins, pin.name)
            if not src:
                continue
            src_nid, src_pin = src
            src_nd = nodes.get(str(src_nid)) or {}
            src_type = src_nd.get("node_type", "?")
            hint = _node_hint(src_type, src_nd.get("props") or {})
            line = "  " * indent + f"~ {pin.name} <- #{src_nid} {src_type}.{src_pin}"
            if hint:
                line += f" {hint}"
            if not _emit(0, line):
                return
            if src_nid in seen:
                continue
            seen.add(src_nid)
            _emit_data(src_nid, indent + 1, level + 1, seen)

    def _walk(nid: int, depth: int, via: str = "", cond: str = "") -> None:
        nonlocal budget_exceeded
        if budget_exceeded:
            return
        nd = nodes.get(str(nid))
        if nd is None:
            return
        node_type = nd.get("node_type", "")

        prefix = f"<{via}> " if via else ""
        if cond:
            prefix += f"({cond}) "
        if nid in on_path:
            if _emit(depth, f"{prefix}#{nid} {node_type} [CYCLE -> stop]"):
                summary["cycles"] += 1
            return
        if nid in visited:
            if _emit(depth, f"{prefix}#{nid} {node_type} [RE-ENTRY -> skipped this tick]"):
                summary["re_entries"] += 1
            return
        visited.add(nid)
        summary["nodes"] += 1
        summary["steps"] += 1
        if not _emit(depth, prefix + _label(nid)):
            return
        if depth >= max_depth:
            _emit(depth + 1, f"... (depth limit {max_depth} — raise with --depth)")
            return

        type_def = _TYPES.get(node_type)
        if type_def is None:
            _emit(depth + 1, f"? unknown node type {node_type!r}")
            return

        inst_pins = nd.get("pin_ids") or {}

        # 数据输入来源（可选；递归展开纯数据节点）
        if include_data:
            _emit_data(nid, depth + 1, 0, {nid})

        on_path.append(nid)
        try:
            # Branch: 只走 True/False 两路，标注条件来源
            if node_type == "Branch":
                src = _input_source(pin_owner, links, inst_pins, "Condition")
                cond_text = ""
                if src:
                    src_type = (nodes.get(str(src[0])) or {}).get("node_type", "?")
                    cond_text = f"cond <- #{src[0]} {src_type}.{src[1]}"
                for branch_name in ("True", "False"):
                    branch_pid = inst_pins.get(branch_name)
                    if branch_pid is None:
                        continue
                    targets = downstream.get(int(branch_pid), [])
                    if not targets:
                        _emit(depth + 1, f"<{branch_name}> (unconnected)")
                        continue
                    for to_nid, to_pin in targets:
                        _walk(to_nid, depth + 1, via=branch_name, cond=cond_text)
                return

            exec_outs = _exec_outputs(type_def, inst_pins)
            if not exec_outs:
                return
            connected = [(name, pid) for name, pid in exec_outs if downstream.get(int(pid))]
            any_target = False
            for pin_name, pin_id in connected:
                any_target = True
                for to_nid, to_pin in downstream.get(int(pin_id), []):
                    via = pin_name if len(connected) > 1 else ""
                    _walk(to_nid, depth + 1, via=via)
            if not any_target and node_type in _DEAD_END_WORTHY:
                warnings.append(f"#{nid} {node_type}: exec output(s) unconnected "
                                f"({', '.join(n for n, _ in exec_outs)})")
        finally:
            on_path.pop()

    _walk(start_id, 0)

    # ── 孤立 exec 节点（从**任意事件**都走不到）──
    def _has_exec_pin(nd: dict) -> bool:
        td = _TYPES.get(nd.get("node_type", ""))
        return bool(td) and any(p.kind == "exec" for p in td.pins)

    reachable: set[int] = set()
    stack = [int(nid) for nid, nd in nodes.items()
             if nd.get("node_type") in _EVENT_TYPES and str(nid).isdigit()]
    while stack:
        nid = stack.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        nd = nodes.get(str(nid))
        td = _TYPES.get((nd or {}).get("node_type", ""))
        if not nd or not td:
            continue
        for pin in td.pins:
            if pin.kind == "exec" and pin.direction == "output":
                pid = (nd.get("pin_ids") or {}).get(pin.name)
                if pid is not None:
                    stack.extend(to_nid for to_nid, _ in downstream.get(int(pid), []))

    orphans = sorted(
        (int(nid_str) for nid_str, nd in nodes.items()
         if int(nid_str) not in reachable
         and nd.get("node_type") not in _EVENT_TYPES
         and _has_exec_pin(nd)),
    )
    if orphans:
        summary["orphans"] = len(orphans)
        if len(lines) < max_lines:
            def _orphan_text(n: int) -> str:
                nd = nodes[str(n)]
                hint = _node_hint(nd.get("node_type", ""), nd.get("props") or {})
                alias = nd.get("alias")
                name = f"#{n}@{alias}" if alias else f"#{n}"
                return f"{name} {nd.get('node_type')}" + (f" {hint}" if hint else "")

            lines.append("-- orphan exec nodes (no event reaches them): %s" % (
                ", ".join(_orphan_text(n) for n in orphans),
            ))

    if budget_exceeded:
        summary["truncated"] = True
        lines.append(f"... (truncated at {max_lines} lines — narrow with --from/--depth)")

    return {
        "ok": True,
        "start": {"node": start_id, "type": nodes[str(start_id)].get("node_type")},
        "summary": summary,
        "lines": lines,
        "warnings": warnings,
    }

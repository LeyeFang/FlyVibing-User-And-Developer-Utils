"""
Node Graph Validator — 节点图校验的**单一实现**（离线 CLI 与在线编辑器共用）。

层级:
  L1 静态: check_graph(scene_data) -> [{"level", "code", "message", "node_id"}]
           validate_static(scene_data) -> [message, ...]        （兼容旧调用, 仅 error）
  L2 干跑: dry_run_simulation(...) → 委托引擎
           Application.Core.NodeGraph.validation.dry_run.run_dry_run（单一实现）

消费方（同源）:
  离线: python -m flyvibing_node_editor.node_graph_validator <scene> [--frames N]
        flyvibing_node_editor.cli / GraphBuilder.validate / apply_graph --validate
  在线: Application/Core/NodeGraph/validation/checks.static_check_graph（薄适配器）
        ← graph.validate.*（LiveCommandServer）/ Node Editor Validate 按钮 / PlayerEntry --dry-run

规则随节点类型与图约束演进 —— **修改规则只改本文件**，引擎侧不再保留副本。
依赖 Application.Core.NodeGraph（节点类型注册表 / 图约束 / 干跑求值器），
因此需在引擎仓库环境中运行（或引擎源码在 PYTHONPATH 上）。

L1 规则:
  1. 未知节点类型 / 缺失引脚（optional 版本兼容 pin 除外）/ Pin ID 冲突
  2. 连线端点存在性 / 方向（output→input）/ 重复连线
  3. 孤立节点（warning — 可能是刻意保留的模板/常量节点）
  4. 必连引脚（Branch.Condition）
  5. SigGen Init/Kill 强制配对（graph_constraints 同一规则）
  6. 设备池: Create/Kill 配对 + Add/设备引用池校验
  7. 设备池: AddToDevicePool.device pin 连线检查（未连 / 来源 / 单池成员制）
  8. Epoch 数据集: Count/Clear/Save 引用校验
  9. Epoch 数据集: EpochAppend 必需数据引脚（Data / Label）
  10. BCI 算法: Init/Train/Test 模型与数据集引用校验 + TestCCA 频率组 ≥2
  11. 媒体: ShowMedia — Entity 引脚必需连线 + exec_in 警示
  12. 设备别名: props 中 @name 引用必须在本机已绑定（跨机器迁移提示）
"""

from __future__ import annotations

import json
import os
import re
import sys

_EVENT_TYPES = {"OnGameStart", "OnFrameUpdate", "OnGameStop"}

# 必连输入引脚: {node_type: [pin_name, ...]}
_REQUIRED_CONNECTIONS = {
    "Branch": ["Condition"],
}

_NODE_ID_RE = re.compile(r"^Node (\d+)<")


def _entry(level: str, code: str, message: str, node_id: int | None = None) -> dict:
    return {"level": level, "code": code, "message": message, "node_id": node_id}


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_graph_data(scene_data: dict) -> dict:
    """从 scene JSON / 裸 graph / 旧格式 graph 中提取节点图数据。

    支持三种格式:
      1. { "scene": { "node_graph": {...} } }   ← 标准 .scene 文件
      2. { "nodes": ..., "links": ... }          ← 裸 graph JSON（NodeCanvas.to_dict）
      3. { "graph": { "nodes": ..., "links": ... } }  ← 旧格式
    """
    if not isinstance(scene_data, dict):
        return {}
    scene = scene_data.get("scene", {})
    if isinstance(scene, dict):
        ng = scene.get("node_graph")
        if isinstance(ng, dict) and "nodes" in ng:
            return ng
    graph = scene_data.get("graph")
    if isinstance(graph, dict) and "nodes" in graph:
        return graph
    if "nodes" in scene_data:
        return scene_data
    return {}


# 兼容旧名（历史调用方使用私有名）
_extract_graph_data = extract_graph_data


# ═══════════════════════════════════════════════════════════════
# L1: 静态检查（结构化）
# ═══════════════════════════════════════════════════════════════

def check_graph(scene_data: dict) -> list[dict]:
    """L1: 静态结构校验 — 返回结构化条目列表（level: "error" | "warning"）。"""
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    ensure_engine_importable()
    from Application.Core.NodeGraph.node_types import _TYPES

    entries: list[dict] = []
    graph = extract_graph_data(scene_data)
    nodes: dict = graph.get("nodes", {}) or {}
    links: dict = graph.get("links", {}) or {}

    if not nodes:
        entries.append(_entry("error", "empty_graph", "No nodes found in graph data"))
        return entries

    # ── 收集所有 pin_id → (nid_str, pin_name, direction) 映射 ──
    pin_map: dict[int, tuple[str, str, str]] = {}
    all_pin_ids: set[int] = set()

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type not in _TYPES:
            entries.append(_entry(
                "error", "unknown_type",
                f"Node {nid_str}: unknown type '{node_type}'",
                _safe_int(nid_str),
            ))
            continue

        type_def = _TYPES[node_type]
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}

        # 1. 检查模板引脚是否齐全 (optional 标记的版本兼容 pin 缺失不报错)
        for pin_def in type_def.pins:
            if pin_def.name not in node_pin_ids:
                if getattr(pin_def, "optional", False):
                    continue
                entries.append(_entry(
                    "error", "missing_pin",
                    f"Node {nid_str}<{node_type}>: missing pin '{pin_def.name}' "
                    f"({pin_def.direction}, {pin_def.kind})",
                    _safe_int(nid_str),
                ))

        # 2. 收集 pin 映射 + 冲突检测
        for pin_name, pin_id in node_pin_ids.items():
            pid = int(pin_id)
            if pid in all_pin_ids:
                prev = pin_map.get(pid)
                prev_desc = f"Node {prev[0]}.{prev[1]}" if prev else "(unknown)"
                entries.append(_entry(
                    "error", "pin_collision",
                    f"Pin ID collision: {pid} used by "
                    f"Node {nid_str}.{pin_name} and {prev_desc}",
                    _safe_int(nid_str),
                ))
            all_pin_ids.add(pid)
            direction = "unknown"
            known = False
            for pin_def in type_def.pins:
                if pin_def.name == pin_name:
                    direction = pin_def.direction
                    known = True
                    break
            if not known:
                entries.append(_entry(
                    "warning", "stale_pin",
                    f"Node {nid_str}<{node_type}>: pin '{pin_name}' is not in the current "
                    f"type definition (legacy pin; links on it never execute)",
                    _safe_int(nid_str),
                ))
            pin_map[pid] = (nid_str, pin_name, direction)

    # 3. 连线检查
    link_set: set[tuple[int, int]] = set()
    for lid_str, ld in links.items():
        try:
            from_pin = int(ld["from_pin"])
            to_pin = int(ld["to_pin"])
        except (KeyError, TypeError, ValueError):
            entries.append(_entry("error", "malformed_link", f"Link {lid_str}: malformed (missing from_pin/to_pin)"))
            continue

        if from_pin not in pin_map:
            entries.append(_entry("error", "link_endpoint", f"Link {lid_str}: from_pin={from_pin} not found in any node"))
        if to_pin not in pin_map:
            entries.append(_entry("error", "link_endpoint", f"Link {lid_str}: to_pin={to_pin} not found in any node"))

        if from_pin in pin_map and to_pin in pin_map:
            _, _, from_dir = pin_map[from_pin]
            _, _, to_dir = pin_map[to_pin]
            if from_dir == "input":
                entries.append(_entry("error", "link_direction", f"Link {lid_str}: from_pin={from_pin} is input (should be output)"))
            if to_dir == "output":
                entries.append(_entry("error", "link_direction", f"Link {lid_str}: to_pin={to_pin} is output (should be input)"))

        pair = (from_pin, to_pin)
        if pair in link_set:
            entries.append(_entry("error", "duplicate_link", f"Link {lid_str}: duplicate connection {from_pin}→{to_pin}"))
        link_set.add(pair)

    # 4. 孤立节点（warning — 可能是刻意保留）
    connected_pins: set[int] = set()
    for ld in links.values():
        try:
            connected_pins.add(int(ld["from_pin"]))
            connected_pins.add(int(ld["to_pin"]))
        except (KeyError, TypeError, ValueError):
            continue

    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        if node_type in _EVENT_TYPES:
            continue
        if node_type not in _TYPES:
            continue  # 未知类型已报错, 跳过
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}
        is_isolated = True
        for pin_id in node_pin_ids.values():
            if int(pin_id) in connected_pins:
                is_isolated = False
                break
        if is_isolated:
            entries.append(_entry(
                "warning", "isolated_node",
                f"Node {nid_str}<{node_type}>: isolated (no connections) — "
                f"may be dead code or missing links",
                _safe_int(nid_str),
            ))

    # 5. 必连引脚检查
    for nid_str, nd in nodes.items():
        node_type = nd.get("node_type", "")
        required = _REQUIRED_CONNECTIONS.get(node_type, [])
        if not required:
            continue
        node_pin_ids: dict = nd.get("pin_ids", {}) or {}
        for rpin in required:
            rpid = node_pin_ids.get(rpin)
            if rpid is None:
                continue
            if int(rpid) not in connected_pins:
                entries.append(_entry(
                    "error", "required_pin_unconnected",
                    f"Node {nid_str}<{node_type}>: required pin '{rpin}' is not connected",
                    _safe_int(nid_str),
                ))

    # 6. SigGen Init/Kill 强制配对（设备族同一规则）
    try:
        from Application.Core.NodeGraph.graph_constraints import siggen_pairing_errors

        for msg in siggen_pairing_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "siggen_pairing", msg, node_id))
    except Exception as e:  # noqa: BLE001 — 约束模块失败不应让整个检查崩溃
        entries.append(_entry("error", "siggen_pairing", f"siggen pairing check failed: {e}"))

    # 7. 设备池: Create/Kill 配对 + Add/设备引用池校验
    try:
        from Application.Core.NodeGraph.graph_constraints import pool_pairing_errors, pool_reference_errors

        for msg in pool_pairing_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "pool_pairing", msg, node_id))
        for msg in pool_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "pool_reference", msg, node_id))
    except Exception as e:  # noqa: BLE001 — 约束模块失败不应让整个检查崩溃
        entries.append(_entry("error", "pool_pairing", f"pool check failed: {e}"))

    # 8. 设备池: AddToDevicePool.device pin 连线检查 (需 links)
    try:
        from Application.Core.NodeGraph.graph_constraints import DEVICE_INIT_PREFIX as _INIT_TYPES
        from Application.Core.NodeGraph.graph_constraints import POOL_ADD as _POOL_ADD

        to_src: dict[int, int] = {}
        for ld in links.values():
            try:
                to_src[int(ld["to_pin"])] = int(ld["from_pin"])
            except (KeyError, TypeError, ValueError):
                continue

        reported_srcs: set[int] = set()
        for nid_str, nd in nodes.items():
            if nd.get("node_type") != _POOL_ADD:
                continue
            node_pin_ids = nd.get("pin_ids", {}) or {}
            dp = node_pin_ids.get("device")
            if dp is None:
                continue  # optional pin 尚未补齐 — 加载时自动 heal, 静态检查跳过
            src = to_src.get(int(dp))
            if src is None:
                entries.append(_entry(
                    "error", "device_pin_unconnected",
                    f"Node {nid_str}<AddToDevicePool>: 'device' pin is not connected "
                    f"(link Init*Device.device → AddToDevicePool.device)",
                    _safe_int(nid_str),
                ))
                continue
            src_info = pin_map.get(src)
            if src_info is None:
                continue  # 端点问题已由连线检查报告
            src_nid_str, src_pin_name, src_dir = src_info
            src_type = (nodes.get(src_nid_str) or {}).get("node_type", "")
            if src_dir != "output" or src_pin_name != "device" or src_type not in _INIT_TYPES:
                entries.append(_entry(
                    "error", "device_pin_source",
                    f"Node {nid_str}<AddToDevicePool>: 'device' pin must come from an "
                    f"Init*Device 'device' output (got {src_type}.{src_pin_name})",
                    _safe_int(nid_str),
                ))
                continue
            # 单池成员制: 同一 device pin 不能被多个 Add 消费
            add_consumers = 0
            for ld in links.values():
                try:
                    if int(ld["from_pin"]) != src:
                        continue
                    cinfo = pin_map.get(int(ld["to_pin"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if cinfo and (nodes.get(cinfo[0]) or {}).get("node_type") == _POOL_ADD:
                    add_consumers += 1
            if add_consumers > 1 and src not in reported_srcs:
                reported_srcs.add(src)
                entries.append(_entry(
                    "error", "device_multi_pool",
                    f"Node {src_nid_str}<{src_type}>: device pin feeds {add_consumers} "
                    f"AddToDevicePool nodes — a device belongs to ONE pool (exclusive)",
                    _safe_int(src_nid_str),
                ))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "device_pin", f"device pin check failed: {e}"))

    # 9. Epoch 数据集: 引用校验 + EpochAppend 必需数据引脚 (Data / Label)
    try:
        from Application.Core.NodeGraph.graph_constraints import EPOCH_APPEND as _EPOCH_APPEND
        from Application.Core.NodeGraph.graph_constraints import epoch_reference_errors

        for msg in epoch_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "epoch_reference", msg, node_id))

        for nid_str, nd in nodes.items():
            if nd.get("node_type") != _EPOCH_APPEND:
                continue
            node_pin_ids = nd.get("pin_ids", {}) or {}
            for rpin in ("Data", "Label"):
                rpid = node_pin_ids.get(rpin)
                if rpid is not None and int(rpid) not in connected_pins:
                    entries.append(_entry(
                        "error", "epoch_pin_unconnected",
                        f"Node {nid_str}<EpochAppend>: '{rpin}' pin is not "
                        f"connected (link Get*Data.{rpin} / a label source)",
                        _safe_int(nid_str),
                    ))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "epoch_reference",
                              f"epoch check failed: {e}"))

    # 10. BCI 算法: 模型/数据集引用 + TestCCA 频率组
    try:
        from Application.Core.NodeGraph.graph_constraints import bci_reference_errors

        for msg in bci_reference_errors(nodes):
            node_id = None
            m = _NODE_ID_RE.match(msg)
            if m:
                node_id = int(m.group(1))
            entries.append(_entry("error", "bci_reference", msg, node_id))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "bci_reference",
                              f"bci check failed: {e}"))

    # 11. 媒体: ShowMedia — Entity 引脚必需连线; exec_in 未连降为 warning
    try:
        from Application.Core.NodeGraph.graph_constraints import SHOW_MEDIA as _SHOW_MEDIA

        for nid_str, nd in nodes.items():
            if nd.get("node_type") != _SHOW_MEDIA:
                continue
            node_pin_ids = nd.get("pin_ids", {}) or {}
            ep = node_pin_ids.get("Entity")
            if ep is not None and int(ep) not in connected_pins:
                entries.append(_entry(
                    "error", "media_pin_unconnected",
                    f"Node {nid_str}<ShowMedia>: 'Entity' pin is not connected "
                    f"(link Get Entity.Entity → ShowMedia.Entity)",
                    _safe_int(nid_str),
                ))
            xp = node_pin_ids.get("exec_in")
            if xp is not None and int(xp) not in connected_pins:
                entries.append(_entry(
                    "warning", "media_exec_unconnected",
                    f"Node {nid_str}<ShowMedia>: 'exec_in' not connected — "
                    f"node will never run (wire under OnFrameUpdate)",
                    _safe_int(nid_str),
                ))
    except Exception as e:  # noqa: BLE001
        entries.append(_entry("error", "media_reference",
                              f"media check failed: {e}"))

    # 12. 设备别名: props 中以 "@" 开头的引用必须在**本机**已绑定
    #     （跨机器迁移的第一道提示 —— 换电脑后 PIE 之前就能看见, 协议 device_io_protocol §12）
    entries.extend(_check_device_aliases(nodes))

    return entries


def _check_device_aliases(nodes: dict) -> list[dict]:
    """扫节点 props 中的 `@device` 引用 → 本机未绑定则 warning（带可操作提示）。"""
    out: list[dict] = []
    refs: list[tuple[str, str, object]] = []          # (nid_str, prop_name, value)
    for nid_str, nd in nodes.items():
        props = nd.get("props")
        if not isinstance(props, dict):
            continue
        for key, value in props.items():
            if isinstance(value, str) and value.startswith("@") and len(value) > 1:
                refs.append((str(nid_str), str(key), value))
    if not refs:
        return out
    try:
        from Application.Core.DeviceRegistry import describe, get, parse_ref
    except Exception as e:  # noqa: BLE001 — 无注册表环境不阻塞校验
        return [_entry("warning", "device_alias_check_unavailable",
                       f"device alias check skipped: {e}")]
    for nid_str, key, value in refs:
        name = parse_ref(value)
        if get(name) is None:
            out.append(_entry(
                "warning", "device_alias_unresolved",
                f"Node {nid_str}: {key}='{value}' is not bound on this machine "
                f"({describe(name)}) — bind it in the Serial/Parallel panel or via "
                f"ext.device.bind_alias name={name} port=COMx",
                _safe_int(nid_str),
            ))
    return out


def validate_static(scene_data: dict) -> list[str]:
    """L1 兼容入口：返回 error 级消息列表（空列表 = 通过）。

    与在线校验同语义：孤立节点等仅作 warning，不阻断。
    """
    return [e["message"] for e in check_graph(scene_data) if e["level"] == "error"]


# ═══════════════════════════════════════════════════════════════
# L2: 干跑模拟（委托引擎单一实现）
# ═══════════════════════════════════════════════════════════════

def dry_run_simulation(
    scene_data: dict,
    max_frames: int = 360,
    verbose: bool = False,
    real_time: bool = False,
    target_fps: float = 0.0,
) -> dict:
    """L2: 干跑模拟 — 委托引擎 `validation.dry_run.run_dry_run`（单一实现）。

    保留旧返回结构以兼容 GraphBuilder / apply_graph:
        {frames_simulated, total_events, events_by_type, errors, perf}

    `real_time` / `target_fps` 仅为旧签名兼容而保留，已无效果 — 校验一致性
    要求确定性 fake-time；性能测量请用引擎侧校验报告的 timing 字段。
    """
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    ensure_engine_importable()
    from Application.Core.NodeGraph.validation.dry_run import run_dry_run

    dr = run_dry_run(scene_data, frames=int(max_frames))
    events = list(dr.get("log") or [])
    if verbose:
        for e in events:
            print(f"  [TRACE] #{e['node_id']}<{e['node_type']}> {e['action']} | {e['detail']}")
    return {
        "frames_simulated": int(dr.get("frames_simulated", 0)),
        "total_events": int(dr.get("total_events", 0)),
        "events_by_type": dict(dr.get("events_by_type") or {}),
        "errors": list(dr.get("errors") or []),
        "perf": None,
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Node Graph Validator — L1 静态 + L2 干跑（与在线编辑器同源）"
    )
    parser.add_argument("scene_path", help="Path to .scene JSON (or bare graph JSON)")
    parser.add_argument("--frames", "-n", type=int, default=0,
                        help="Dry-run N frames (0 = static only)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-node dry-run traces")
    parser.add_argument("--static-only", "-s", action="store_true",
                        help="Static check only (skip dry-run even if --frames is set)")
    parser.add_argument("--real-time", "-r", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--fps", type=float, default=0.0,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    scene_path = args.scene_path
    if not os.path.isabs(scene_path):
        scene_path = os.path.abspath(scene_path)
    if not os.path.exists(scene_path):
        print(f"ERROR: File not found: {scene_path}")
        return 2

    with open(scene_path, "r", encoding="utf-8") as f:
        scene_data = json.load(f)

    print(f"\n{'=' * 60}")
    print(f"  L1: Static Validation — {os.path.basename(scene_path)}")
    print(f"{'=' * 60}")

    entries = check_graph(scene_data)
    static_errors = [e for e in entries if e["level"] == "error"]
    static_warnings = [e for e in entries if e["level"] == "warning"]
    if static_errors:
        print(f"\n  FAILED — {len(static_errors)} error(s):\n")
        for err in static_errors:
            print(f"    x {err['message']}")
    else:
        print("\n  PASSED — no static errors")
    for warn in static_warnings:
        print(f"    ! {warn['message']}")

    dry_run_errors: list[str] = []
    if args.frames > 0 and not args.static_only:
        result = dry_run_simulation(
            scene_data, max_frames=args.frames, verbose=args.verbose)
        dry_run_errors = result.get("errors", [])
        if dry_run_errors:
            print(f"\n  Dry-run errors ({len(dry_run_errors)}):")
            for err in dry_run_errors:
                print(f"    x {err}")
        else:
            print(f"\n  Dry-run completed — {result['frames_simulated']} frames, "
                  f"{result['total_events']} side-effect events")

    total_errors = len(static_errors) + len(dry_run_errors)
    print(f"\n{'=' * 60}")
    if total_errors:
        print(f"  RESULT: {total_errors} issue(s) total — FIX BEFORE PIE")
    else:
        print("  RESULT: All checks passed")
    print(f"{'=' * 60}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

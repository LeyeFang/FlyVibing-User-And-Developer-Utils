"""NodeEditor CLI — 终端通道（与 MCP 同一实现; 零常驻上下文成本）。

用法:
  python -m flyvibing_node_editor.cli rules [section] [--all] [--out FILE]
  python -m flyvibing_node_editor.cli entities <scene.scene>
  python -m flyvibing_node_editor.cli build --spec spec.json [--out graph.json]
  python -m flyvibing_node_editor.cli apply --scene scene.scene --graph graph.json   # --graph - = stdin
  python -m flyvibing_node_editor.cli flow  --scene scene.scene [--event OnFrameUpdate] [--from ID] [--data]
  python -m flyvibing_node_editor.cli pins  [TypeName]
  python -m flyvibing_node_editor.cli find  --scene scene.scene [--type T] [--alias NAME] [--prop K=V ...]
  python -m flyvibing_node_editor.cli groups [--scene scene.scene]
  python -m flyvibing_node_editor.cli apply-ops --scene scene.scene --ops ops.json [--write]

- `rules` 无 section → 目录（outline）; 有 section → 单节文本; `--all` → 全文;
  `--out` 落盘时只回摘要 JSON（不把全文/大图塞进上下文）。
- `build` 无 `--out` → 打印完整结果（含内联 graph）; 有 `--out` → 写入 graph JSON 只回摘要。
- 图校验请用引擎内服务（engine-editor MCP / CLI validate; 见 rules.md 的 Validation 节）。

退出码: 0 成功 / 1 运行时错误 / 2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flyvibing_node_editor import rule_sections  # noqa: E402


def _resolve(path: str) -> str:
    """相对路径解析优先级: cwd → 引擎仓库根（供 `Test/...` 这类仓库内路径）。"""
    if os.path.isabs(path):
        return path
    cwd_path = os.path.abspath(path)
    if os.path.exists(cwd_path):
        return cwd_path
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    root = ensure_engine_importable()
    if root:
        engine_path = os.path.join(root, path)
        if os.path.exists(engine_path):
            return engine_path
    return cwd_path


def _out(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _fail(message: str, code: int = 1) -> int:
    sys.stderr.write(message.rstrip() + "\n")
    return code


def _read_json_arg(raw: str):
    if raw == "-":
        # PowerShell 管道可能带 BOM；统一按 utf-8-sig 解
        return json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    with open(_resolve(raw), "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def cmd_rules(ns) -> int:
    if ns.all:
        text = rule_sections.load_rules()
    elif ns.section:
        text = rule_sections.section(ns.section)
        if text is None:
            titles = ", ".join(f'"{t}"' for t in rule_sections.section_titles())
            return _fail(f"unknown section: {ns.section!r} — 可用: {titles}", 2)
    else:
        text = rule_sections.outline()
    if ns.out:
        out_path = os.path.abspath(_resolve(ns.out))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        _out({"saved": out_path, "chars": len(text)})
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def cmd_entities(ns) -> int:
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    with open(scene_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    scene = data.get("scene", data)
    entities = []
    for eid_str, ed in (scene.get("entities") or {}).items():
        entities.append({
            "id": int(eid_str),
            "name": ed.get("name", ""),
            "components": list((ed.get("components") or {}).keys()),
            "parent_id": ed.get("parent_id"),
        })
    _out({"entities": entities, "total": len(entities)})
    return 0


def cmd_build(ns) -> int:
    try:
        spec = _read_json_arg(ns.spec)
    except (OSError, ValueError) as e:
        return _fail(f"spec 读取失败: {e}", 2)
    from flyvibing_node_editor.spec_builder import build_experiment_graph

    result = build_experiment_graph(spec)
    if ns.out:
        out_path = os.path.abspath(_resolve(ns.out))
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result["graph"], fh, indent=2, ensure_ascii=False)
        _out({"saved": out_path, "node_count": result["node_count"], "link_count": result["link_count"]})
    else:
        _out(result)
    return 0


def cmd_apply(ns) -> int:
    try:
        graph = _read_json_arg(ns.graph)
    except (OSError, ValueError) as e:
        return _fail(f"graph 读取失败: {e}", 2)
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["scene"]["node_graph"] = graph
        with open(scene_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except (OSError, KeyError, ValueError) as e:
        return _fail(f"apply 失败: {e}", 1)
    _out({
        "success": True,
        "path": scene_path,
        "node_count": len(graph.get("nodes", {})),
        "link_count": len(graph.get("links", {})),
    })
    return 0


def cmd_apply_ops(ns) -> int:
    """对已有节点图做增量修改（默认 dry-run；--write 才落盘）。"""
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    ensure_engine_importable()
    try:
        payload = _read_json_arg(ns.ops)
    except (OSError, ValueError) as e:
        return _fail(f"ops 读取失败: {e}", 2)
    ops = payload.get("ops") if isinstance(payload, dict) else payload
    if not isinstance(ops, list):
        return _fail("ops 必须是数组，或 {\"ops\": [...]}", 2)

    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return _fail(f"scene 读取失败: {e}", 1)

    from flyvibing_node_editor.node_graph_validator import check_graph
    from flyvibing_node_editor.ops import apply_ops

    result = apply_ops(data, ops)
    entries = check_graph(result["scene"])
    val_errors = [e for e in entries if e["level"] == "error"]
    ok = bool(result["ok"]) and not val_errors

    if ns.write and result["ok"]:
        with open(scene_path, "w", encoding="utf-8") as fh:
            json.dump(result["scene"], fh, indent=2, ensure_ascii=False)

    _out({
        "ok": ok,
        "op_errors": result["errors"],
        "validation_errors": [e["message"] for e in val_errors[:5]],
        "applied": len(ops),
        "created": result.get("symbols") or {},
        "written": bool(ns.write and result["ok"]),
        "path": scene_path,
    })
    return 0 if ok else 1


def cmd_pins(ns) -> int:
    """打印节点类型的 pin 契约（名称/方向/类型），供构图前确认写法。"""
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    ensure_engine_importable()
    from Application.Core.NodeGraph.node_types import _TYPES

    if not ns.type:
        groups: dict[str, list[str]] = {}
        for name, td in _TYPES.items():
            groups.setdefault(td.category, []).append(name)
        _out({"types": {k: sorted(v) for k, v in sorted(groups.items())},
              "total": len(_TYPES)})
        return 0

    wanted = ns.type
    td = _TYPES.get(wanted)
    if td is None:
        for name, cand in _TYPES.items():
            if name.lower() == wanted.lower():
                td, wanted = cand, name
                break
    if td is None:
        return _fail(f"unknown node type: {ns.type!r}", 2)

    def _pin(p):
        item = {"name": p.name, "kind": p.kind}
        if p.kind == "data":
            item["data_type"] = p.data_type
        if p.optional:
            item["optional"] = True
        return item

    _out({
        "type": wanted,
        "label": td.label,
        "category": td.category,
        "inputs": [_pin(p) for p in td.pins if p.direction == "input"],
        "outputs": [_pin(p) for p in td.pins if p.direction == "output"],
        "props_text": td.props_text,
    })
    return 0


def _prop_match(actual, expected: str) -> bool:
    if actual is None:
        return False
    try:
        return float(actual) == float(expected)
    except (TypeError, ValueError):
        return str(actual).strip().lower() == expected.strip().lower()


def cmd_find(ns) -> int:
    """按类型 / 属性 / 文本搜节点（把“定位”从模型推理变成工具调用）。"""
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return _fail(f"scene 读取失败: {e}", 1)

    filters: list[tuple[str, str]] = []
    for raw in ns.prop or []:
        if "=" not in raw:
            return _fail(f"--prop 需要 K=V 形式: {raw!r}", 2)
        key, val = raw.split("=", 1)
        filters.append((key.strip(), val.strip()))

    graph = data.get("scene", data).get("node_graph") or {}
    nodes = graph.get("nodes") or {}
    matches = []
    for nid, nd in nodes.items():
        ntype = nd.get("node_type", "")
        if ns.type and ntype.lower() != ns.type.lower():
            continue
        alias = nd.get("alias") or ""
        description = nd.get("description") or ""
        if ns.alias and ns.alias.lstrip("@").lower() != alias.lower():
            continue
        props = nd.get("props") or {}
        if any(not _prop_match(props.get(k), v) for k, v in filters):
            continue
        if ns.text:
            hay = (ntype + " " + alias + " " + description + " "
                   + json.dumps(props, ensure_ascii=False)).lower()
            if ns.text.lower() not in hay:
                continue
        matches.append({"id": int(nid), "type": ntype,
                        "alias": alias, "description": description,
                        "props": props})
        if len(matches) >= max(1, int(ns.limit)):
            break

    _out({"matches": matches, "count": len(matches), "scanned": len(nodes)})
    return 0


def cmd_groups(ns) -> int:
    """无 scene：列出内置组模板；有 scene：列出组实例。"""
    from flyvibing_node_editor.node_groups import list_groups

    if not ns.scene:
        _out({"templates": list_groups()})
        return 0
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return _fail(f"scene 读取失败: {e}", 1)

    graph = data.get("scene", data).get("node_graph") or {}
    groups = graph.get("node_groups") or {}
    out = {}
    for gid, g in groups.items():
        slots = g.get("slots") or {}
        out[gid] = {
            "type": g.get("type"),
            "alias": g.get("alias", ""),
            "version": g.get("version", 1),
            "entry": slots.get("entry"),
            "done": slots.get("done"),
            "parent": g.get("parent"),
            "children": list(g.get("children") or []),
            "arms": [a.get("id") for a in (g.get("params", {}).get("arms") or [])],
            "members": len(g.get("members") or []),
        }
    _out({"groups": out, "count": len(out)})
    return 0


def cmd_flow(ns) -> int:
    """静态执行流分析（V1）— 不执行引擎。"""
    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        return _fail(f"scene not found: {scene_path}", 1)
    try:
        with open(scene_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return _fail(f"scene 读取失败: {e}", 1)

    from flyvibing_node_editor.graph_flow import analyze_flow

    result = analyze_flow(
        data,
        event=ns.event,
        start=ns.start,
        max_depth=max(1, int(ns.depth)),
        max_lines=max(10, int(ns.max_lines)),
        include_data=bool(ns.data),
        data_depth=max(1, int(ns.data_depth)),
    )
    if ns.json:
        _out(result)
        return 0 if result["ok"] else 1
    if not result["ok"]:
        return _fail("; ".join(result["warnings"]), 1)
    for line in result["lines"]:
        print(line)
    s = result["summary"]
    print(f"-- nodes={s['nodes']} steps={s['steps']} gates={s['gates']} "
          f"terminals={s['terminals']} re_entries={s['re_entries']} "
          f"cycles={s['cycles']}" + (" TRUNCATED" if s["truncated"] else ""))
    for w in result["warnings"]:
        print(f"! {w}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m flyvibing_node_editor.cli",
        description="NodeEditor 终端通道（rules 分节 / build spec / apply 到 scene）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("rules", help="参考文档: 无参=目录; section=单节; --all=全文")
    p.add_argument("section", nargs="?", default="", help='节标题（如 "SigGen" / "build_graph Spec"）')
    p.add_argument("--all", action="store_true", help="输出全文（谨慎: 约 1 万字符）")
    p.add_argument("--out", help="写入文件（只回摘要 JSON）")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("entities", help="读取 .scene 实体列表")
    p.add_argument("scene")
    p.set_defaults(func=cmd_entities)

    p = sub.add_parser("build", help="实验 spec → 节点图 JSON")
    p.add_argument("--spec", required=True, help="spec JSON 文件路径（- = stdin）")
    p.add_argument("--out", help="写入 graph JSON（只回摘要; 供 apply 复用）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("apply", help="将节点图 JSON 注入 .scene 文件")
    p.add_argument("--scene", required=True)
    p.add_argument("--graph", required=True, help="graph JSON 文件路径（- = stdin）")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("flow", help="静态执行流分析（不执行引擎）")
    p.add_argument("--scene", required=True)
    p.add_argument("--event", default="OnFrameUpdate",
                   help="起始事件节点（默认 OnFrameUpdate）")
    p.add_argument("--from", dest="start", type=int, default=None,
                   help="显式起始节点 id（优先于 --event）")
    p.add_argument("--depth", type=int, default=24, help="最大展开深度")
    p.add_argument("--max-lines", type=int, default=120, help="输出行预算")
    p.add_argument("--data", action="store_true", help="附带数据输入的上游来源")
    p.add_argument("--data-depth", type=int, default=1, help="数据依赖展开层数（配合 --data）")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")
    p.set_defaults(func=cmd_flow)

    p = sub.add_parser("pins", help="节点类型的 pin 契约（无参=列类型）")
    p.add_argument("type", nargs="?", default="", help="节点类型名（如 TimeTrigger）")
    p.set_defaults(func=cmd_pins)

    p = sub.add_parser("find", help="按类型/属性/文本搜索节点")
    p.add_argument("--scene", required=True)
    p.add_argument("--type", default="", help="节点类型（大小写不敏感）")
    p.add_argument("--alias", default="", help="节点别名（@ 可省略）")
    p.add_argument("--prop", action="append", default=[], metavar="K=V",
                   help="属性过滤，可重复（如 --prop value=60）")
    p.add_argument("--text", default="", help="在类型+props 里做子串匹配")
    p.add_argument("--limit", type=int, default=20, help="最多返回条数")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("groups", help="组模板 / 场景内的组实例")
    p.add_argument("--scene", default="", help="省略则列出内置组模板")
    p.set_defaults(func=cmd_groups)

    p = sub.add_parser("apply-ops", help="对已有节点图做增量修改（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--ops", required=True, help='ops JSON 文件（- = stdin）')
    p.add_argument("--write", action="store_true", help="校验通过后写回 scene")
    p.set_defaults(func=cmd_apply_ops)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ns = build_parser().parse_args(argv)
    try:
        return int(ns.func(ns) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

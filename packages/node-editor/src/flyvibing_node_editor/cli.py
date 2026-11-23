"""NodeEditor CLI — 终端通道（与 MCP 同一实现; 零常驻上下文成本）。

用法:
  python -m flyvibing_node_editor.cli rules [section] [--all] [--out FILE]
  python -m flyvibing_node_editor.cli entities <scene.scene>
  python -m flyvibing_node_editor.cli build --spec spec.json [--out graph.json]
  python -m flyvibing_node_editor.cli apply --scene scene.scene --graph graph.json   # --graph - = stdin
  python -m flyvibing_node_editor.cli flow  --scene scene.scene [--event OnFrameUpdate] [--from ID] [--data]
  python -m flyvibing_node_editor.cli pins  [TypeName]
  python -m flyvibing_node_editor.cli find  --scene scene.scene [--type T] [--alias NAME] [--prop K=V ...]
  python -m flyvibing_node_editor.cli query --scene scene.scene --from @node [--direction down|up|both] [--groups opaque|expand]
  python -m flyvibing_node_editor.cli expand --scene scene.scene --group @group [--nested opaque|expand]
  python -m flyvibing_node_editor.cli patch --scene scene.scene --patch ops.json [--write] [--expect-hash SHA]
  python -m flyvibing_node_editor.cli link --scene scene.scene --from @a.Value --to @b.In_0 [--write]
  python -m flyvibing_node_editor.cli unlink --scene scene.scene --from @a.Value --to @b.In_0 [--write]
  python -m flyvibing_node_editor.cli simulate --scene scene.scene --group @g --seconds 3 --fps 240
  python -m flyvibing_node_editor.cli simulate --scene scene.scene --mode realtime --seconds 3
  python -m flyvibing_node_editor.cli simulate --scene scene.scene --mode realtime --uncapped --seconds 7
  python -m flyvibing_node_editor.cli groups [--scene scene.scene]
  python -m flyvibing_node_editor.cli group-merge --scene scene.scene --nodes 2,3 [--alias NAME] [--write]
  python -m flyvibing_node_editor.cli group-ungroup --scene scene.scene --group g1 [--write]
  python -m flyvibing_node_editor.cli group-delete --scene scene.scene --group g1 [--no-recursive] [--write]
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


def _fail(message: str, code: int = 1, error: str = "cli_error") -> int:
    payload = {"schema": "node-cli/error/v1", "ok": False,
               "error": error, "detail": message.strip()}
    print(json.dumps(payload, ensure_ascii=False))
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


def _run_group_op(ns, op: dict) -> int:
    """执行单个组 op（dry-run 默认；--write 才写回 scene）。"""
    from flyvibing_node_editor.engine_path import ensure_engine_importable

    ensure_engine_importable()
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

    result = apply_ops(data, [op])
    entries = check_graph(result["scene"]) if result["ok"] else []
    val_errors = [e for e in entries if e["level"] == "error"]
    ok = bool(result["ok"]) and not val_errors
    if ns.write and result["ok"]:
        with open(scene_path, "w", encoding="utf-8") as fh:
            json.dump(result["scene"], fh, indent=2, ensure_ascii=False)
    _out({
        "ok": ok,
        "op": op.get("op"),
        "errors": result["errors"],
        "validation_errors": [e["message"] for e in val_errors[:5]],
        "written": bool(ns.write and result["ok"]),
        "path": scene_path,
    })
    return 0 if ok else 1


def cmd_group_merge(ns) -> int:
    nodes = [p for p in str(ns.nodes).replace(" ", ",").split(",") if p]
    op = {"op": "merge_group", "nodes": nodes}
    if ns.alias:
        op["alias"] = ns.alias
    return _run_group_op(ns, op)


def cmd_group_ungroup(ns) -> int:
    return _run_group_op(ns, {"op": "ungroup_group", "group": ns.group})


def cmd_group_delete(ns) -> int:
    return _run_group_op(ns, {
        "op": "delete_group",
        "group": ns.group,
        "recursive": not bool(ns.no_recursive),
    })


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
            "title": g.get("title", ""),
            "description": g.get("description", ""),
            "entry": slots.get("entry"),
            "done": slots.get("done"),
            "parent": g.get("parent"),
            "children": list(g.get("children") or []),
            "arms": [a.get("id") for a in (g.get("params", {}).get("arms") or [])],
            "members": len(g.get("members") or []),
        }
    _out({"groups": out, "count": len(out)})
    return 0


def _load_graph_input(ns) -> dict:
    """--scene / --graph 二选一；--graph 支持裸 graph JSON 与 -。"""
    raw = ns.graph if getattr(ns, "graph", "") else ns.scene
    if raw == "-":
        return _read_json_arg("-")
    path = _resolve(raw)
    if not os.path.exists(path):
        raise FileNotFoundError(f"input not found: {path}")
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def cmd_query(ns) -> int:
    """组感知的上下游链路查询（组默认黑盒，带边界端口）。"""
    from flyvibing_node_editor.graph_query import GraphIR, GraphQueryError, render_query_text
    try:
        data = _load_graph_input(ns)
        ir = GraphIR(data)
        result = ir.query(
            ns.start,
            direction=ns.direction,
            depth=ns.depth,
            groups=ns.groups,
            edges=ns.edges,
            data_direction=ns.data_direction,
            max_nodes=ns.max_nodes,
            with_props=ns.with_props,
        )
    except (OSError, ValueError, GraphQueryError) as e:
        return _fail(f"query: {e}", 2)
    if ns.format == "text":
        print(render_query_text(result))
        return 0
    _out(result)
    return 0


def cmd_expand(ns) -> int:
    """展开一个组的内部链路；子组默认继续黑盒。"""
    from flyvibing_node_editor.graph_query import GraphIR, GraphQueryError, render_expand_text
    try:
        data = _load_graph_input(ns)
        ir = GraphIR(data)
        result = ir.expand(
            ns.group,
            nested=ns.nested,
            edges=ns.edges,
            max_nodes=ns.max_nodes,
            with_props=ns.with_props,
        )
    except (OSError, ValueError, GraphQueryError) as e:
        return _fail(f"expand: {e}", 2)
    if ns.format == "text":
        print(render_expand_text(result))
        return 0
    _out(result)
    return 0


def _read_patch_ops(raw: str) -> list:
    payload = _read_json_arg(raw)
    ops = payload.get("ops") if isinstance(payload, dict) else payload
    if not isinstance(ops, list):
        raise ValueError('patch must be a list or {"ops": [...]}')
    return ops


def _write_scene_file(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _patch_result_text(result: dict) -> str:
    c = (result.get("diff") or {}).get("counts") or {}
    n, l, g = c.get("nodes") or {}, c.get("links") or {}, c.get("groups") or {}
    return (f"patch {'ok' if result.get('ok') else 'FAILED'} "
            f"nodes +{n.get('added', 0)} ~{n.get('changed', 0)} -{n.get('removed', 0)}; "
            f"links +{l.get('added', 0)} -{l.get('removed', 0)}; "
            f"groups +{g.get('added', 0)} ~{g.get('changed', 0)} -{g.get('removed', 0)}; "
            f"written={result.get('written', False)}; "
            f"hash={result.get('hash_after') or '-'}")


def _run_patch(ns, ops: list) -> dict:
    from flyvibing_node_editor.graph_patch import apply_patch

    scene_path = _resolve(ns.scene)
    if not os.path.exists(scene_path):
        raise FileNotFoundError(f"scene not found: {scene_path}")
    with open(scene_path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    result = apply_patch(data, ops, expect_hash=getattr(ns, "expect_hash", None),
                         validate=not getattr(ns, "no_validate", False))
    written = False
    if result.get("ok") and getattr(ns, "write", False):
        _write_scene_file(scene_path, result["scene"])
        written = True
    result.pop("scene", None)
    result["written"] = written
    result["path"] = scene_path
    return result


def _endpoint(text: str) -> dict:
    raw = str(text or "").strip()
    if ":" in raw:
        node, pin = raw.rsplit(":", 1)
    elif "." in raw:
        node, pin = raw.rsplit(".", 1)
    else:
        raise ValueError(f"endpoint must be @node.pin or @node:pin, got {text!r}")
    node, pin = node.strip(), pin.strip()
    if not node or not pin:
        raise ValueError(f"endpoint must be @node.pin or @node:pin, got {text!r}")
    return [node, pin]


def _sim_json(raw: str):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _sim_split_ref_key(text: str):
    raw = str(text or "").strip()
    for sep in (".", ":"):
        if sep in raw:
            node, key = raw.rsplit(sep, 1)
            if node.strip() and key.strip():
                return node.strip(), key.strip()
    raise ValueError(f"expected @node.key, got {text!r}")


def _sim_props(items) -> dict:
    out = {}
    for raw in items or []:
        lhs, sep, value = str(raw).partition("=")
        if not sep:
            raise ValueError(f"expected @node.key=value, got {raw!r}")
        node, key = _sim_split_ref_key(lhs)
        out.setdefault(node, {})[key] = _sim_json(value)
    return out


def _sim_stubs(items) -> dict:
    out = {}
    for raw in items or []:
        lhs, sep, value = str(raw).partition("=")
        if not sep:
            raise ValueError(f"expected @node.pin=value, got {raw!r}")
        node, pin = _sim_split_ref_key(lhs)
        out[f"{node}.{pin}"] = _sim_json(value)
    return out


def _sim_kv(items) -> dict:
    out = {}
    for raw in items or []:
        key, sep, value = str(raw).partition("=")
        if not sep or not key.strip():
            raise ValueError(f"expected name=value, got {raw!r}")
        out[key.strip()] = _sim_json(value)
    return out


def cmd_simulate(ns) -> int:
    try:
        data = _load_graph_input(ns)
        from flyvibing_node_editor.graph_sim import render_summary, simulate

        nodes = [x.strip() for x in (ns.nodes or "").split(",") if x.strip()] or None
        result = simulate(
            data,
            seconds=ns.seconds,
            frames=(ns.frames if ns.frames and ns.frames > 0 else None),
            fps=ns.fps,
            dt=(ns.dt if ns.dt and ns.dt > 0 else None),
            mode=ns.mode,
            uncapped=bool(ns.uncapped),
            group=(ns.group or None),
            nodes=nodes,
            watch_vars=(ns.var or None),
            watch_timers=(ns.timer or None),
            watch_pins=(ns.pin or None),
            set_vars=_sim_kv(ns.set_var),
            set_timers=_sim_kv(ns.set_timer),
            set_props=_sim_props(ns.set_prop),
            stub_pins=_sim_stubs(ns.stub),
            allow_long=bool(ns.allow_long),
            max_trace=ns.max_trace,
            seed=ns.seed,
            trace_out=(os.path.abspath(ns.out) if ns.out else None),
        )
    except (OSError, ValueError) as e:
        return _fail(f"simulate: {e}", 2)
    if ns.format == "text":
        print(render_summary(result))
    else:
        _out(result)
    return 0 if result.get("ok") else 1


def cmd_patch(ns) -> int:
    try:
        ops = _read_patch_ops(ns.patch)
        result = _run_patch(ns, ops)
    except (OSError, ValueError) as e:
        return _fail(f"patch: {e}", 2)
    if ns.format == "text":
        print(_patch_result_text(result))
    else:
        _out(result)
    return 0 if result.get("ok") else 1


def cmd_link(ns, *, unlink: bool = False) -> int:
    try:
        op = {"op": "unlink" if unlink else "link",
              "from": _endpoint(ns.from_endpoint),
              "to": _endpoint(ns.to_endpoint)}
        result = _run_patch(ns, [op])
    except (OSError, ValueError) as e:
        return _fail(f"{'unlink' if unlink else 'link'}: {e}", 2)
    if ns.format == "text":
        print(_patch_result_text(result))
    else:
        _out(result)
    return 0 if result.get("ok") else 1


def cmd_unlink(ns) -> int:
    return cmd_link(ns, unlink=True)


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


def _json_scalar(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_scalar(v) for v in value]
    return None


def _arg_manifest(action) -> dict:
    if isinstance(action, argparse._HelpAction) or action.dest in ("func",):
        return {}
    choices = sorted(str(c) for c in action.choices) if action.choices else None
    type_name = None
    if action.type is not None:
        type_name = getattr(action.type, "__name__", "custom")
    return {
        "dest": action.dest,
        "flags": list(action.option_strings),
        "required": bool(getattr(action, "required", False)),
        "default": _json_scalar(action.default),
        "choices": choices,
        "type": type_name,
        "nargs": action.nargs if isinstance(action.nargs, (str, int, type(None))) else None,
        "help": getattr(action, "help", "") or "",
    }


def _command_manifest(parser: argparse.ArgumentParser) -> list[dict]:
    sub = next((a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction)), None)
    if sub is None:
        return []
    help_map = {a.dest: (a.help or "") for a in sub._choices_actions}
    by_parser: dict[int, dict] = {}
    order: list[dict] = []
    for name, child in sub.choices.items():
        key = id(child)
        if key not in by_parser:
            args = [a for a in (_arg_manifest(x) for x in child._actions) if a]
            item = {"name": name, "aliases": [], "summary": help_map.get(name, ""),
                    "args": args}
            by_parser[key] = item
            order.append(item)
        elif name != by_parser[key]["name"]:
            by_parser[key]["aliases"].append(name)
    return order


def _package_version() -> str:
    try:
        from importlib.metadata import version
        return version("flyvibing-node-editor")
    except Exception:  # noqa: BLE001
        return "unknown"


def build_manifest() -> dict:
    """flyvibing-node-editor/manifest/v1 — CLI 的机器可读单一事实源。"""
    return {
        "schema": "flyvibing-node-editor/manifest/v1",
        "entrypoint": "flyvibing-node-editor",
        "version": _package_version(),
        "invocation": "flyvibing-node-editor <command> [args]",
        "exit_codes": {"0": "success", "1": "runtime error", "2": "usage error"},
        "error": {
            "stream": "stdout",
            "schema": "node-cli/error/v1",
            "fields": ["schema", "ok", "error", "detail"],
        },
        "graph_schemas": {
            "query": "graph-query/v1",
            "patch": "graph-patch/v1",
            "simulate": "graph-sim/v1",
        },
        "commands": _command_manifest(build_parser()),
    }


def cmd_schema(ns) -> int:
    manifest = build_manifest()
    if getattr(ns, "format", "json") == "text":
        lines = [f"{manifest['entrypoint']} {manifest['version']} — command manifest",
                 f"schema: {manifest['schema']}",
                 f"exit: {manifest['exit_codes']}"]
        for cmd in manifest["commands"]:
            flags = " ".join(a["flags"][0] for a in cmd["args"] if a["flags"])
            lines.append(f"  {cmd['name']:<14} {cmd['summary']}")
            if flags:
                lines.append(f"      {flags}")
        print("\n".join(lines))
    else:
        print(json.dumps(manifest, ensure_ascii=False))
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

    p = sub.add_parser("query", help="组感知的上下游链路查询（组默认黑盒）")
    _src = p.add_mutually_exclusive_group(required=True)
    _src.add_argument("--scene", default="", help=".scene 文件")
    _src.add_argument("--graph", default="", help="裸 graph JSON 文件（- = stdin）")
    p.add_argument("--from", dest="start", required=True,
                   help="起点：@alias、#节点id、gN 或组 alias")
    p.add_argument("--direction", choices=["down", "up", "both"], default="down")
    p.add_argument("--depth", type=int, default=3, help="最多经过的边数")
    p.add_argument("--groups", choices=["auto", "opaque", "expand"], default="auto",
                   help="auto=起点组透明、其余组黑盒（默认）；opaque=全黑盒；expand=展开到节点")
    p.add_argument("--edges", choices=["exec", "data", "all"], default="all")
    p.add_argument("--data-direction", choices=["inputs", "outputs", "both"], default="inputs",
                   help="数据边遍历方向：inputs=回溯生产者（默认）；outputs=找消费者；both")
    p.add_argument("--max-nodes", type=int, default=80)
    p.add_argument("--with-props", action="store_true", help="附带完整 props（默认只回摘要字段）")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("expand", help="展开组内链路（子组默认继续黑盒）")
    _src = p.add_mutually_exclusive_group(required=True)
    _src.add_argument("--scene", default="", help=".scene 文件")
    _src.add_argument("--graph", default="", help="裸 graph JSON 文件（- = stdin）")
    p.add_argument("--group", required=True, help="组 gid 或 alias")
    p.add_argument("--nested", choices=["opaque", "expand"], default="opaque",
                   help="opaque=子组黑盒（默认）；expand=递归到节点")
    p.add_argument("--edges", choices=["exec", "data", "all"], default="all")
    p.add_argument("--max-nodes", type=int, default=80)
    p.add_argument("--with-props", action="store_true", help="附带完整 props")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_expand)

    p = sub.add_parser("simulate", help="fake-time 模拟 + 探针（整图执行，按组/节点过滤）")
    _src = p.add_mutually_exclusive_group(required=True)
    _src.add_argument("--scene", default="", help=".scene 文件")
    _src.add_argument("--graph", default="", help="裸 graph JSON 文件（- = stdin）")
    p.add_argument("--seconds", type=float, default=3.0, help="模拟时长（默认 3 s）")
    p.add_argument("--frames", type=int, default=0, help="帧数（>0 时覆盖 --seconds）")
    p.add_argument("--fps", type=float, default=240.0,
                   help="时间基（默认 240 fps；realtime 下 0=不设帧率上限）")
    p.add_argument("--dt", type=float, default=0.0, help="显式步长；>0 时覆盖 --fps")
    p.add_argument("--mode", choices=["fake", "realtime"], default="fake",
                   help="fake=确定性 fake-time（默认）；realtime=wall-clock 实速，统计抖动")
    p.add_argument("--uncapped", action="store_true",
                   help="realtime 不设帧率上限（自由运行；用 --seconds 控时长）")
    p.add_argument("--allow-long", action="store_true",
                   help="允许 realtime 超过 10 s（默认拒绝，防止误跑长时间）")
    p.add_argument("--group", default="", help="只观测该组（整图仍执行）")
    p.add_argument("--nodes", default="", help="只观测这些节点（逗号分隔；整图仍执行）")
    p.add_argument("--var", action="append", default=[], help="观测变量（可重复）")
    p.add_argument("--timer", action="append", default=[], help="观测计时器（可重复）")
    p.add_argument("--pin", action="append", default=[], help="观测引脚 @node.pin（可重复）")
    p.add_argument("--set-var", action="append", default=[], help="覆盖变量初值 name=value（可重复）")
    p.add_argument("--set-timer", action="append", default=[], help="覆盖计时器初值 name=value（可重复）")
    p.add_argument("--set-prop", action="append", default=[],
                   help="覆盖节点 props：@node.key=value（可重复；常量/时间参数等）")
    p.add_argument("--stub", "--inject", dest="stub", action="append", default=[],
                   help="注入数据引脚：@node.pin=value（output=强制输出，input=覆盖边界输入）")
    p.add_argument("--max-trace", type=int, default=0, help="stdout trace 条数上限（默认 0=只回摘要；--out 可落盘完整 trace）")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="", help="完整 trace 写 JSONL（只回摘要）")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("patch", help="事务式增量写入（graph-patch/v1；默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--patch", required=True, help='patch JSON 文件（- = stdin；数组或 {"ops": [...]}）')
    p.add_argument("--write", action="store_true", help="校验通过后原子写回 scene")
    p.add_argument("--expect-hash", default="", help="乐观并发校验（query 输出的 graph_hash）")
    p.add_argument("--no-validate", action="store_true", help="跳过 L1 校验（不推荐）")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("link", help="连接两个引脚（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--from", dest="from_endpoint", required=True, help="@node.pin 或 @node:pin")
    p.add_argument("--to", dest="to_endpoint", required=True, help="@node.pin 或 @node:pin")
    p.add_argument("--write", action="store_true", help="校验通过后原子写回 scene")
    p.add_argument("--expect-hash", default="")
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("unlink", help="断开两个引脚（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--from", dest="from_endpoint", required=True, help="@node.pin 或 @node:pin")
    p.add_argument("--to", dest="to_endpoint", required=True, help="@node.pin 或 @node:pin")
    p.add_argument("--write", action="store_true", help="校验通过后原子写回 scene")
    p.add_argument("--expect-hash", default="")
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_unlink)

    p = sub.add_parser("group-merge", help="把选中节点合并为组（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--nodes", required=True, help="节点 id/alias，逗号分隔（如 2,3,@print_a）")
    p.add_argument("--alias", default="", help="组别名（省略自动 group_N）")
    p.add_argument("--write", action="store_true", help="校验通过后写回 scene")
    p.set_defaults(func=cmd_group_merge)

    p = sub.add_parser("group-ungroup", help="拆分组框，保留成员节点与子组（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--group", required=True, help="组 gid 或 alias")
    p.add_argument("--write", action="store_true", help="校验通过后写回 scene")
    p.set_defaults(func=cmd_group_ungroup)

    p = sub.add_parser("group-delete", help="删除组框，保留成员节点（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--group", required=True, help="组 gid 或 alias")
    p.add_argument("--no-recursive", action="store_true",
                   help="只删当前组框；默认连同子组")
    p.add_argument("--write", action="store_true", help="校验通过后写回 scene")
    p.set_defaults(func=cmd_group_delete)

    p = sub.add_parser("apply-ops", help="对已有节点图做增量修改（默认 dry-run）")
    p.add_argument("--scene", required=True)
    p.add_argument("--ops", required=True, help='ops JSON 文件（- = stdin）')
    p.add_argument("--write", action="store_true", help="校验通过后写回 scene")
    p.set_defaults(func=cmd_apply_ops)

    p = sub.add_parser("schema", help="机器可读命令清单（flyvibing-node-editor/manifest/v1）")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_schema)

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

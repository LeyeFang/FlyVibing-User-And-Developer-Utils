"""图谱编辑 ops — 在已有节点图上做增量修改（link / unlink / set_props / add_node / remove_node /
set_alias / set_description / add_group / set_group / merge_group / ungroup_group / delete_group）。

与 bench 的 patch DSL 同一语义；供 CLI `apply-ops` 与 agent 的 stepwise 编辑使用。
纯内存操作：返回新的 scene dict，不写文件。
"""

from __future__ import annotations

import copy
import re

_OPS = ("link", "unlink", "set_props", "add_node", "remove_node",
        "set_alias", "set_description", "add_group", "set_group",
        "merge_group", "ungroup_group", "delete_group")

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_GENERIC_EXEC = {"exec", "exec_out", "out_0", "in", "exec_in", "in_0"}


def _graph(scene: dict) -> dict:
    return scene.get("scene", {}).get("node_graph", scene)


def _max_int(values) -> int:
    best = 0
    for v in values:
        try:
            best = max(best, int(v))
        except (TypeError, ValueError):
            continue
    return best


def _next_node_id(scene: dict) -> int:
    return _max_int(_graph(scene).get("nodes", {}).keys()) + 1


def _next_pin_id(scene: dict) -> int:
    ids = []
    for nd in _graph(scene).get("nodes", {}).values():
        ids.extend((nd.get("pin_ids") or {}).values())
    return _max_int(ids) + 1


def _next_link_id(scene: dict) -> int:
    return _max_int(_graph(scene).get("links", {}).keys()) + 1


def _types():
    from Application.Core.NodeGraph.node_types import _TYPES
    return _TYPES


def _alias_map(scene: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for nid, nd in _graph(scene).get("nodes", {}).items():
        alias = nd.get("alias")
        if isinstance(alias, str) and alias:
            out[alias.lower()] = int(nid)
    return out


def valid_alias(alias: str) -> bool:
    return bool(_ALIAS_RE.match(alias or ""))


def _resolve_node(scene: dict, ref, symbols: dict) -> int | None:
    nodes = _graph(scene).get("nodes", {})
    if isinstance(ref, str):
        name = ref.strip()
        if name in symbols:
            return symbols[name]
        if name.startswith("@"):
            name = name[1:]
        aliases = _alias_map(scene)
        if name.lower() in aliases:
            return aliases[name.lower()]
        if name.startswith("#"):
            name = name[1:]
        if name.isdigit():
            nid = int(name)
            return nid if str(nid) in nodes else None
        matches = [int(nid) for nid, nd in nodes.items()
                   if nd.get("node_type") == name]
        return matches[0] if len(matches) == 1 else None
    try:
        nid = int(ref)
    except (TypeError, ValueError):
        return None
    return nid if str(nid) in nodes else None


def _pin_id(scene: dict, nid: int, pin_name: str, direction: str | None = None) -> int | None:
    nd = _graph(scene).get("nodes", {}).get(str(nid))
    if not nd:
        return None
    pins = nd.get("pin_ids") or {}
    td = _types().get(nd.get("node_type", ""))
    known = {p.name for p in td.pins} if td else None

    # 只接受当前类型定义里的 pin；实例上的遗留 pin（如 TimeTrigger.exec_out）一律不用，
    # 否则会写出“看起来连上了但永远不会执行”的死链。
    if pin_name in pins and (known is None or pin_name in known):
        return pins[pin_name]
    lower = {str(k).lower(): v for k, v in pins.items()
             if known is None or k in known}
    if str(pin_name).lower() in lower:
        return lower[str(pin_name).lower()]

    if not td:
        return None
    if str(pin_name).lower() in _GENERIC_EXEC:
        for want in ([direction] if direction else ["output", "input"]):
            if not want:
                continue
            outs = [p.name for p in td.pins
                    if p.kind == "exec" and p.direction == want and p.name in pins]
            if len(outs) == 1:
                return pins[outs[0]]
    return None


def pin_names(scene: dict, nid: int) -> str:
    nd = _graph(scene).get("nodes", {}).get(str(nid)) or {}
    pins = nd.get("pin_ids") or {}
    if not pins:
        return "(none)"
    td = _types().get(nd.get("node_type", ""))
    dirs = {p.name: p.direction for p in td.pins} if td else {}
    parts = []
    for name in sorted(pins):
        d = dirs.get(name)
        if d:
            parts.append(f"{name}({'in' if d == 'input' else 'out'})")
        else:
            parts.append(f"{name}(stale)")
    return ", ".join(parts)


def apply_ops(scene: dict, ops) -> dict:
    """应用 ops，返回 {"ok", "errors", "scene", "symbols"}。"""
    scene = copy.deepcopy(scene)
    errors: list[str] = []
    symbols: dict[str, int] = {}
    if not isinstance(ops, list):
        return {"ok": False, "errors": ["ops must be a list"], "scene": scene,
                "symbols": symbols}

    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            errors.append(f"op[{i}] is not an object")
            continue
        kind = str(op.get("op", ""))

        if kind == "add_node":
            type_name = str(op.get("type", ""))
            td = _types().get(type_name)
            if td is None:
                errors.append(f"op[{i}] add_node: unknown type {type_name!r}")
                continue
            nid = _next_node_id(scene)
            pid = _next_pin_id(scene)
            pin_ids = {}
            for pin in td.pins:
                pin_ids[pin.name] = pid
                pid += 1
            props = dict(op.get("props") or {})
            alias = op.get("as")
            if not alias:
                alias = props.pop("as", None)
            else:
                props.pop("as", None)
            persistent = op.get("alias")
            if persistent is not None:
                if not isinstance(persistent, str) or not valid_alias(persistent):
                    errors.append(f"op[{i}] add_node: invalid alias {persistent!r}")
                    continue
                if persistent.lower() in _alias_map(scene):
                    errors.append(f"op[{i}] add_node: duplicate alias {persistent!r}")
                    continue
            nd = {
                "node_type": type_name,
                "pos": [0.0, 0.0],
                "props": props,
                "pin_ids": pin_ids,
            }
            if isinstance(persistent, str) and persistent:
                nd["alias"] = persistent
            description = op.get("description")
            if description not in (None, ""):
                nd["description"] = str(description)
            _graph(scene)["nodes"][str(nid)] = nd
            if isinstance(alias, str) and alias:
                symbols[alias] = nid
            if isinstance(persistent, str) and persistent:
                symbols[persistent] = nid
            continue

        if kind == "set_alias":
            nid = _resolve_node(scene, op.get("node"), symbols)
            if nid is None:
                errors.append(f"op[{i}] set_alias: unknown node {op.get('node')!r}")
                continue
            new_alias = op.get("alias")
            nd = _graph(scene)["nodes"][str(nid)]
            if new_alias in (None, ""):
                nd.pop("alias", None)
                continue
            if not isinstance(new_alias, str) or not valid_alias(new_alias):
                errors.append(f"op[{i}] set_alias: invalid alias {new_alias!r}")
                continue
            owners = _alias_map(scene)
            owner = owners.get(new_alias.lower())
            if owner is not None and owner != nid:
                errors.append(f"op[{i}] set_alias: duplicate alias {new_alias!r} (node #{owner})")
                continue
            nd["alias"] = new_alias
            continue

        if kind == "set_description":
            nid = _resolve_node(scene, op.get("node"), symbols)
            if nid is None:
                errors.append(f"op[{i}] set_description: unknown node {op.get('node')!r}")
                continue
            nd = _graph(scene)["nodes"][str(nid)]
            description = op.get("description")
            if description in (None, ""):
                nd.pop("description", None)
            else:
                nd["description"] = str(description)
            continue

        if kind == "set_props":
            nid = _resolve_node(scene, op.get("node"), symbols)
            if nid is None:
                errors.append(f"op[{i}] set_props: unknown node {op.get('node')!r}")
                continue
            nd = _graph(scene)["nodes"][str(nid)]
            nd["props"] = {**(nd.get("props") or {}), **dict(op.get("props") or {})}
            continue

        if kind == "remove_node":
            nid = _resolve_node(scene, op.get("node"), symbols)
            if nid is None:
                errors.append(f"op[{i}] remove_node: unknown node {op.get('node')!r}")
                continue
            nd = _graph(scene)["nodes"].pop(str(nid), None)
            pids = set((nd.get("pin_ids") or {}).values()) if nd else set()
            links = _graph(scene).get("links", {})
            for lid in [lid for lid, ld in links.items()
                        if int(ld.get("from_pin", -1)) in pids
                        or int(ld.get("to_pin", -1)) in pids]:
                links.pop(lid, None)
            continue

        if kind in ("link", "unlink"):
            src = op.get("from") or []
            dst = op.get("to") or []
            if not (isinstance(src, list) and len(src) == 2
                    and isinstance(dst, list) and len(dst) == 2):
                errors.append(f"op[{i}] {kind}: from/to must be [node, pin]")
                continue
            from_nid = _resolve_node(scene, src[0], symbols)
            to_nid = _resolve_node(scene, dst[0], symbols)
            from_pid = None
            slot_pid = None
            # 组入口/出口都是「虚拟端口」：入口指向内部 pin，出口指向内部 exec_out。
            if (from_nid is None and isinstance(src[0], str)
                    and src[0].strip().startswith("@")):
                from flyvibing_node_editor.node_groups import _resolve_group
                _gid, _group = _resolve_group(scene, src[0])
                if _group is not None:
                    from_pid = (_group.get("slots") or {}).get(
                        str(src[1] or "done"))
                    if from_pid is None:
                        errors.append(
                            f"op[{i}] {kind}: group {src[0]!r} has no slot [{src[1]!r}]")
                        continue
            if (to_nid is None and isinstance(dst[0], str)
                    and dst[0].strip().startswith("@")):
                from flyvibing_node_editor.node_groups import _resolve_group
                _gid, _group = _resolve_group(scene, dst[0])
                if _group is not None:
                    slot_pid = (_group.get("slots") or {}).get(str(dst[1] or "entry"))
                    if slot_pid is None:
                        errors.append(
                            f"op[{i}] {kind}: group {dst[0]!r} has no slot [{dst[1]!r}]")
                        continue
            if from_nid is not None:
                from_pid = _pin_id(scene, from_nid, str(src[1]), direction="output")
            if from_nid is None and from_pid is None:
                errors.append(f"op[{i}] {kind}: unknown node {src[0]!r} -> {dst[0]!r}")
                continue
            if to_nid is None and slot_pid is None:
                errors.append(f"op[{i}] {kind}: unknown node {src[0]!r} -> {dst[0]!r}")
                continue
            if slot_pid is not None:
                to_pid = int(slot_pid)
            else:
                to_pid = _pin_id(scene, to_nid, str(dst[1]), direction="input")
            if from_pid is None or to_pid is None:
                errors.append(
                    f"op[{i}] {kind}: unknown pin {src[1]!r}@#{from_nid} -> {dst[1]!r}@#{to_nid}; "
                    f"pins@#{from_nid}=[{pin_names(scene, from_nid)}], "
                    f"pins@#{to_nid}=[{pin_names(scene, to_nid)}]")
                continue
            links = _graph(scene).setdefault("links", {})
            existing = [lid for lid, ld in links.items()
                        if int(ld.get("from_pin", -1)) == int(from_pid)
                        and int(ld.get("to_pin", -1)) == int(to_pid)]
            if kind == "unlink":
                if not existing:
                    errors.append(f"op[{i}] unlink: link not found")
                for lid in existing:
                    links.pop(lid, None)
                continue
            if existing:
                errors.append(f"op[{i}] link: duplicate")
                continue
            links[str(_next_link_id(scene))] = {"from_pin": int(from_pid),
                                               "to_pin": int(to_pid)}
            continue

        if kind == "add_group":
            from flyvibing_node_editor.node_groups import add_group
            res = add_group(scene, op)
            if not res["ok"]:
                errors.extend(f"op[{i}] add_group: {e}" for e in res["errors"])
            else:
                scene = res["scene"]
                symbols.update(res.get("symbols") or {})
            continue

        if kind == "set_group":
            from flyvibing_node_editor.node_groups import update_group
            res = update_group(scene, op)
            if not res["ok"]:
                errors.extend(f"op[{i}] set_group: {e}" for e in res["errors"])
            else:
                scene = res["scene"]
                symbols.update(res.get("symbols") or {})
            continue

        if kind in ("merge_group", "ungroup_group", "delete_group"):
            from flyvibing_node_editor import node_groups as ng
            fn = {
                "merge_group": ng.merge_group,
                "ungroup_group": ng.ungroup_group,
                "delete_group": ng.delete_group,
            }[kind]
            res = fn(scene, {**op, "symbols": symbols} if kind == "merge_group" else op)
            if not res["ok"]:
                errors.extend(f"op[{i}] {kind}: {e}" for e in res["errors"])
            else:
                scene = res["scene"]
                symbols.update(res.get("symbols") or {})
            continue

        errors.append(f"op[{i}] unknown op {kind!r}")

    if not errors:
        graph = _graph(scene)
        max_id = 0
        for nid_s, nd in (graph.get("nodes") or {}).items():
            max_id = max(max_id, int(nid_s))
            for pid in (nd.get("pin_ids") or {}).values():
                max_id = max(max_id, int(pid))
        for ld in (graph.get("links") or {}).values():
            max_id = max(max_id, int(ld.get("id", 0)),
                         int(ld.get("from_pin", 0)), int(ld.get("to_pin", 0)))
        graph["next_id"] = max_id + 1
    return {"ok": not errors, "errors": errors, "scene": scene, "symbols": symbols}

"""事务式节点图补丁（graph-patch/v1）。

- 输入 `.scene` 或裸 graph；ops 与 `apply-ops` 同一套语义，额外支持：
  `add_node.pos` / `set_pos` / `set_group_meta` / `merge_group.description|title`。
- `expect_hash`: 用 `graph-query/v1` 的 `graph_hash` 做乐观并发校验；不匹配直接拒绝。
- 先算 diff，再跑 L1 校验；只有 `ok=true` 时调用方才应落盘。
- 返回结构化 diff（节点/连线/组），不返回整张图。
"""

from __future__ import annotations

import copy

from flyvibing_node_editor.graph_query import GraphIR
from flyvibing_node_editor.node_graph_validator import check_graph, extract_graph_data
from flyvibing_node_editor.ops import apply_ops

SCHEMA = "graph-patch/v1"
_MAX_DIFF = 200


def _nodes(graph):
    return {int(k): v for k, v in (graph.get("nodes") or {}).items()}


def _pin_index(graph):
    idx = {}
    for nid, nd in _nodes(graph).items():
        for name, pid in (nd.get("pin_ids") or {}).items():
            try:
                idx[int(pid)] = (nid, str(name))
            except (TypeError, ValueError):
                continue
    return idx


def _edges(graph):
    idx = _pin_index(graph)
    out = []
    for link in (graph.get("links") or {}).values():
        try:
            fp = int(link.get("from_pin"))
            tp = int(link.get("to_pin"))
        except (TypeError, ValueError):
            continue
        a, b = idx.get(fp), idx.get(tp)
        if a and b:
            out.append({"from": a, "to": b})
    return out


def _node_ref(nd, nid):
    alias = str((nd or {}).get("alias") or "")
    return f"@{alias}" if alias else f"#{nid}"


def _link_key(edge):
    return (edge["from"][0], edge["from"][1], edge["to"][0], edge["to"][1])


def _link_item(edge, nodes):
    return {
        "from": {"node": edge["from"][0], "ref": _node_ref(nodes.get(edge["from"][0]), edge["from"][0]),
                 "pin": edge["from"][1]},
        "to": {"node": edge["to"][0], "ref": _node_ref(nodes.get(edge["to"][0]), edge["to"][0]),
               "pin": edge["to"][1]},
    }


def _group_ref(graph, gid):
    g = (graph.get("node_groups") or {}).get(gid) or {}
    alias = str(g.get("alias") or "")
    return f"@{alias}" if alias else str(gid)


def diff_graphs(before_data, after_data) -> dict:
    """节点/连线/组的增量摘要；列表按 200 条截断。"""
    before = extract_graph_data(before_data)
    after = extract_graph_data(after_data)
    bn, an = _nodes(before), _nodes(after)
    bg, ag = before.get("node_groups") or {}, after.get("node_groups") or {}

    added_nodes = [{"id": nid, "ref": _node_ref(an[nid], nid), "type": an[nid].get("node_type"),
                    "pos": an[nid].get("pos") or [0, 0]}
                   for nid in sorted(set(an) - set(bn))]
    removed_nodes = [{"id": nid, "ref": _node_ref(bn[nid], nid), "type": bn[nid].get("node_type")}
                     for nid in sorted(set(bn) - set(an))]
    changed_nodes = []
    for nid in sorted(set(bn) & set(an)):
        b, a = bn[nid], an[nid]
        fields = [key for key in ("node_type", "alias", "description", "pos", "props")
                  if b.get(key) != a.get(key)]
        if fields:
            changed_nodes.append({
                "id": nid, "ref": _node_ref(a, nid), "type": a.get("node_type"),
                "fields": fields,
                "props_changed": sorted(
                    {k for k in (set((b.get("props") or {})) | set((a.get("props") or {})))
                     if (b.get("props") or {}).get(k) != (a.get("props") or {}).get(k)}
                ) if "props" in fields else [],
            })

    be, ae = _edges(before), _edges(after)
    bkeys, akeys = {_link_key(e): e for e in be}, {_link_key(e): e for e in ae}
    added_links = [_link_item(akeys[k], an) for k in sorted(set(akeys) - set(bkeys))]
    removed_links = [_link_item(bkeys[k], bn) for k in sorted(set(bkeys) - set(akeys))]

    added_groups = [{"id": gid, "ref": _group_ref(after, gid),
                     "type": (ag[gid] or {}).get("type"), "alias": (ag[gid] or {}).get("alias")}
                    for gid in sorted(set(ag) - set(bg))]
    removed_groups = [{"id": gid, "ref": _group_ref(before, gid),
                       "type": (bg[gid] or {}).get("type"), "alias": (bg[gid] or {}).get("alias")}
                      for gid in sorted(set(bg) - set(ag))]
    changed_groups = []
    for gid in sorted(set(bg) & set(ag)):
        b, a = bg[gid] or {}, ag[gid] or {}
        fields = [key for key in ("type", "alias", "title", "description", "params",
                                  "members", "children", "slots")
                  if b.get(key) != a.get(key)]
        if fields:
            changed_groups.append({
                "id": gid, "ref": _group_ref(after, gid),
                "alias": a.get("alias"), "fields": fields,
            })

    def cap(items):
        return items[:_MAX_DIFF]

    diffs = {
        "nodes": {"added": added_nodes, "removed": removed_nodes, "changed": changed_nodes},
        "links": {"added": added_links, "removed": removed_links},
        "groups": {"added": added_groups, "removed": removed_groups, "changed": changed_groups},
    }
    truncated = any(len(v) > _MAX_DIFF for section in (
        added_nodes, removed_nodes, changed_nodes, added_links, removed_links,
        added_groups, removed_groups, changed_groups) for v in [section])
    for section in diffs.values():
        for key in list(section):
            section[key] = cap(section[key])
    counts = {
        "nodes": {"added": len(added_nodes), "removed": len(removed_nodes),
                  "changed": len(changed_nodes)},
        "links": {"added": len(added_links), "removed": len(removed_links)},
        "groups": {"added": len(added_groups), "removed": len(removed_groups),
                   "changed": len(changed_groups)},
        "truncated": bool(truncated),
    }
    return {"changes": diffs, "counts": counts}


def apply_patch(scene_data: dict, ops: list, *, expect_hash: str | None = None,
                validate: bool = True) -> dict:
    """应用补丁并返回 {ok, hash_before, hash_after, diff, validation, scene}。

    不写文件；调用方只在 `ok` 为真时落盘。`scene` 是完整输入结构（便于测试/写入）。
    """
    if not isinstance(ops, list):
        return {"ok": False, "schema": SCHEMA, "stage": "input",
                "errors": ["ops must be a list"], "hash_before": None,
                "hash_after": None, "diff": None, "validation": None}
    try:
        before_hash = GraphIR(scene_data).graph_hash()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "schema": SCHEMA, "stage": "input",
                "errors": [f"cannot read graph: {e}"], "hash_before": None,
                "hash_after": None, "diff": None, "validation": None}

    if expect_hash and str(expect_hash) != before_hash:
        return {
            "ok": False, "schema": SCHEMA, "stage": "hash",
            "errors": [f"graph hash mismatch: expected {expect_hash}, actual {before_hash}"],
            "hash_before": before_hash, "hash_after": None, "diff": None,
            "validation": None,
        }

    result = apply_ops(copy.deepcopy(scene_data), ops)
    after_scene = result["scene"]
    if not result["ok"]:
        return {
            "ok": False, "schema": SCHEMA, "stage": "ops",
            "errors": list(result["errors"]), "hash_before": before_hash,
            "hash_after": None, "diff": None, "validation": None,
            "scene": after_scene,
        }

    validation = {"skipped": True, "errors": [], "warnings": []}
    if validate:
        try:
            entries = check_graph(after_scene)
            errors = [e for e in entries if e.get("level") == "error"]
            warnings = [e for e in entries if e.get("level") == "warning"]
            validation = {
                "skipped": False,
                "errors": [{"code": e.get("code"), "message": e.get("message"),
                            "node_id": e.get("node_id")} for e in errors],
                "warnings": [{"code": e.get("code"), "message": e.get("message"),
                              "node_id": e.get("node_id")} for e in warnings[:40]],
                "errors_total": len(errors),
                "warnings_total": len(warnings),
            }
        except Exception as e:  # noqa: BLE001
            validation = {"skipped": True, "errors": [], "warnings": [],
                          "error": f"validation unavailable: {e}"}

    diff = diff_graphs(scene_data, after_scene)
    try:
        after_hash = GraphIR(after_scene).graph_hash()
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "schema": SCHEMA, "stage": "hash",
            "errors": [f"cannot hash result: {e}"], "hash_before": before_hash,
            "hash_after": None, "diff": diff, "validation": validation,
            "scene": after_scene,
        }

    validation_error = validation.get("error")
    ok = not validation.get("errors") and not validation_error
    errors = [f"{e.get('code')}: {e.get('message')}" for e in validation.get("errors", [])]
    if validation_error:
        errors.append(validation_error)
    return {
        "ok": ok,
        "schema": SCHEMA,
        "stage": "done" if ok else "validation",
        "errors": errors if not ok else [],
        "hash_before": before_hash,
        "hash_after": after_hash,
        "diff": diff,
        "validation": validation,
        "scene": after_scene,
    }

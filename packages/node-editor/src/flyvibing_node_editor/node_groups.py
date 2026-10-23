"""节点组（NodeGroup）— 模板注册、扁平展开、差异重展开。

设计：组是“宏”，插入时展开成普通 nodes/links；`node_groups` 只是元数据，
运行时/校验不求值，但引擎画布会**不透明保留**（场景保存 / graph.export 随图带回）。
模板通过 params 参数化，分支用 arms 数组表达。

内置组:
  - cue_n_way: 随机 N 选 1 → 每个 arm 显示实体 + ParallelSend 码值
  - cue_window: 每帧可见窗口（单进单出；TimeGetElapsed → Compare → EntitySetRenderVisible）
"""

from __future__ import annotations

import copy
import re

_GROUP_ID_RE = re.compile(r"^g(\d+)$")


def _graph(scene: dict) -> dict:
    return scene.get("scene", {}).get("node_graph", scene)


def _next_node_id(scene: dict) -> int:
    ids = [int(k) for k in _graph(scene).get("nodes", {}) if str(k).isdigit()]
    return max(ids, default=0) + 1


def _max_group_id(scene: dict) -> int:
    best = 0
    for gid in (_graph(scene).get("node_groups") or {}):
        m = _GROUP_ID_RE.match(str(gid))
        if m:
            best = max(best, int(m.group(1)))
    return best


def _group_map(scene: dict) -> dict:
    return _graph(scene).setdefault("node_groups", {})


def _next_link_id(scene: dict) -> int:
    ids = [int(k) for k in _graph(scene).get("links", {}) if str(k).isdigit()]
    return max(ids, default=0) + 1


def _delete_nodes(scene: dict, node_ids) -> None:
    nodes = _graph(scene).get("nodes", {})
    links = _graph(scene).get("links", {})
    pids = set()
    for nid in node_ids:
        nd = nodes.pop(str(nid), None)
        if nd:
            pids.update(int(v) for v in (nd.get("pin_ids") or {}).values())
    for lid in [lid for lid, ld in links.items()
                if int(ld.get("from_pin", -1)) in pids
                or int(ld.get("to_pin", -1)) in pids]:
        links.pop(lid, None)


def _member_node_ids(member: dict) -> list[int]:
    """arm_members 条目 → 节点 id 列表（兼容旧版 get 为单 int）。"""
    out: list[int] = []
    for key in ("get", "pack", "merge"):
        value = member.get(key)
        if isinstance(value, int):
            out.append(int(value))
        elif isinstance(value, (list, tuple)):
            out.extend(int(v) for v in value)
    for key in ("set", "send", "code"):
        value = member.get(key)
        if value is not None:
            out.append(int(value))
    return out


def _alias_of(g: dict) -> str:
    return str(g.get("alias") or "")


def list_groups() -> dict:
    return {
        "cue_n_way": {
            "title": "随机 N 选 1 → 显示实体组 + 发码（分支宏；无 done）",
            "params": {
                "addr": "int (default 16376)",
                "arms": "list[{id?, entity | entities: [name...], code}]，2–8 个 arm；每个 arm 1–8 个实体",
            },
            "slots": {"entry": "exec_in", "done": None},
        },
        "cue_window": {
            "title": "按命名时钟的可见窗口（每帧求值，单进单出）",
            "params": {
                "clock": "str，Timer 名；空串 = 全局 elapsed",
                "start": "float，窗口起点（秒）",
                "end": "float，窗口终点（秒）；必须 >= start",
                "entity": "str，运行时实体名（EntityGet 查找）",
                "visible": "bool (default true)，窗口内设置 Visible=true/false",
                "include_end": "bool (default false)，true 时窗口为 [start,end]",
            },
            "slots": {
                "entry": "exec_in（每次父链执行时进入）",
                "done": "exec_out（本次求值结束，继续父链）",
            },
        },
        "hide_group": {
            "title": "按实体树批量显隐（线性组，单进单出）",
            "params": {
                "entities": "list[str]，运行时实体根名；树内子孙一起处理",
                "visible": "bool (default false)",
            },
            "slots": {
                "entry": "exec_in",
                "done": "exec_out",
            },
        },
        "container": {
            "title": "容器组（嵌套已有子组，不生成节点）",
            "params": {
                "children": "list[str]，子组 alias 或 gid",
                "entry": "[node_ref, pin] 可选；省略 = 第一个子组 entry",
                "done": "[node_ref, pin] 可选；省略 = 最后一个子组 done",
                "members": "list[node_ref] 可选，额外纳入组框的节点",
            },
            "slots": {
                "entry": "exec_in",
                "done": "exec_out",
            },
        },
        "mi_select": {
            "title": "0s 选择 MI 条件并显示对应 cue（线性组）",
            "params": {
                "mi_var": "str (default mi_code)",
                "arms": "list[{id, code 1..3, entity | entities:[...]}]",
            },
            "slots": {"entry": "exec_in", "done": "exec_out"},
        },
        "phase0_trigger": {
            "title": "Phase 0 条件 trigger（MI*32 + SSSEP，单次发送）",
            "params": {
                "mi_var": "str (default mi_code)",
                "sss_var": "str (default sss_code)",
                "trigger_var": "str (default trigger_val)",
                "mi_scale": "int (default 32)",
                "address": "int (default 16376)",
            },
            "slots": {"entry": "exec_in", "done": "exec_out"},
        },
        "sss_pulse": {
            "title": "一次 20 Hz SSSEP 脉冲（并口 + 串口，线性组）",
            "params": {
                "value_var": "str (default sss_code)",
                "count_var": "str (default pulse_count)",
                "timer": "str (default pulse)",
                "interval": "float (default -0.05)",
                "address": "int (default 16376)",
                "serial_port": "str (default @SSSEP-Stimulator)",
                "serial_baud": "int (default 9600)",
            },
            "slots": {"entry": "exec_in", "done": "exec_out"},
        },
    }


def _arm_entities(arm: dict) -> list[str]:
    """arm 实体列表: entities（新）优先，否则 entity（旧）单实体。"""
    raw = arm.get("entities")
    if raw is None:
        single = str(arm.get("entity") or "").strip()
        return [single] if single else []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _validate_arms(params: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    raw = params.get("arms")
    if not isinstance(raw, list) or len(raw) < 2:
        return [], ["params.arms must be a list with >= 2 arms"]
    if len(raw) > 8:
        errors.append("params.arms supports at most 8 arms")
    arms: list[dict] = []
    seen: set[str] = set()
    for i, arm in enumerate(raw, start=1):
        if not isinstance(arm, dict):
            errors.append(f"arms[{i}] must be an object")
            continue
        entities = _arm_entities(arm)
        if not entities:
            errors.append(f"arms[{i}] needs entity or entities")
        if len(entities) > 8:
            errors.append(f"arms[{i}] supports at most 8 entities")
        arm_id = str(arm.get("id") or f"arm{i}")
        if arm_id in seen:
            errors.append(f"duplicate arm id {arm_id!r}")
        seen.add(arm_id)
        try:
            code = int(arm.get("code", 0))
        except (TypeError, ValueError):
            code = 0
        if not 1 <= code <= 255:
            errors.append(f"arms[{i}] code must be 1..255 (got {arm.get('code')!r})")
        arm_out = {"id": arm_id, "entities": entities, "code": code}
        if len(entities) == 1:
            arm_out["entity"] = entities[0]
        arms.append(arm_out)
    return arms, errors


# ── cue_window: 每帧求值的可见窗口 ───────────────────────────

def _window_params(params: dict) -> tuple[dict, list[str]]:
    """校验并规范化 cue_window 参数（纯函数）。"""
    errors: list[str] = []
    clock = str(params.get("clock", "") or "").strip()
    entity = str(params.get("entity") or params.get("target")
                 or params.get("entity_name") or "").strip()
    if not entity:
        errors.append("params.entity is required (runtime entity name)")
    try:
        start = float(params.get("start", 0.0))
    except (TypeError, ValueError):
        errors.append("params.start must be a number")
        start = 0.0
    try:
        end = float(params.get("end", 0.0))
    except (TypeError, ValueError):
        errors.append("params.end must be a number")
        end = 0.0
    if end < start:
        errors.append("params.end must be >= params.start")
    out = {
        "clock": clock,
        "start": start,
        "end": end,
        "entity": entity,
        "visible": bool(params.get("visible", True)),
        "include_end": bool(params.get("include_end", False)),
    }
    return out, errors


def _window_ops(prefix: str, cfg: dict) -> list[dict]:
    """线性窗口组：TimeGetElapsed → 区间比较 → EntityGet → SetRenderVisible。

    entry = TimeGetElapsed.exec_in；done = EntitySetRenderVisible.exec_out。
    每次 entry 执行都会重新求值并写一次 Visible，因此组自己负责 enter/exit。
    """
    ge = f"{prefix}_ge"
    lt = f"{prefix}_lt"
    active = f"{prefix}_active"
    out = [
        {"op": "add_node", "type": "TimeGetElapsed",
         "props": {"timer": cfg["clock"]}, "as": f"{prefix}_clock",
         "description": f"Window clock {cfg['clock']!r} (empty = global time)."},
        {"op": "add_node", "type": "Constant", "props": {"value": cfg["start"]},
         "as": f"{prefix}_start",
         "description": f"Window start {cfg['start']:g}s."},
        {"op": "add_node", "type": "Constant", "props": {"value": cfg["end"]},
         "as": f"{prefix}_end",
         "description": f"Window end {cfg['end']:g}s."},
        {"op": "add_node", "type": "Compare", "props": {"operation": "gte"},
         "as": ge, "description": "elapsed >= start"},
        {"op": "add_node", "type": "Compare",
         "props": {"operation": "lte" if cfg["include_end"] else "lt"},
         "as": lt, "description": "elapsed <= end" if cfg["include_end"]
                                    else "elapsed < end"},
        {"op": "add_node", "type": "Compare", "props": {"operation": "and"},
         "as": active, "description": "Window active (start <= elapsed < end)."},
        {"op": "add_node", "type": "EntityGet",
         "props": {"entity_name": cfg["entity"]}, "as": f"{prefix}_get",
         "description": f"Resolve runtime entity {cfg['entity']!r}."},
        {"op": "add_node", "type": "EntitySetRenderVisible", "props": {},
         "as": f"{prefix}_set",
         "description": "Write visibility every frame (group owns enter/exit)."},
    ]

    def _add(alias: str, pin: str, to_alias: str, to_pin: str) -> None:
        out.append({"op": "link", "from": [alias, pin],
                    "to": [to_alias, to_pin]})

    _add(f"{prefix}_clock", "exec_out", f"{prefix}_get", "exec_in")
    _add(f"{prefix}_clock", "Elapsed", ge, "A")
    _add(f"{prefix}_clock", "Elapsed", lt, "A")
    _add(f"{prefix}_start", "Result", ge, "B")
    _add(f"{prefix}_end", "Result", lt, "B")
    _add(ge, "Result", active, "A")
    _add(lt, "Result", active, "B")
    _add(f"{prefix}_get", "exec_out", f"{prefix}_set", "exec_in")
    _add(f"{prefix}_get", "Entity", f"{prefix}_set", "EntityID")

    if cfg["visible"]:
        _add(active, "Result", f"{prefix}_set", "Visible")
    else:
        out.append({"op": "add_node", "type": "Compare",
                    "props": {"operation": "not"}, "as": f"{prefix}_not",
                    "description": "Invert the window state (visible=false)."})
        _add(active, "Result", f"{prefix}_not", "A")
        _add(f"{prefix}_not", "Result", f"{prefix}_set", "Visible")
    return out


def _window_member_aliases(prefix: str, include_not: bool) -> list[str]:
    names = [f"{prefix}_clock", f"{prefix}_start", f"{prefix}_end",
             f"{prefix}_ge", f"{prefix}_lt", f"{prefix}_active",
             f"{prefix}_get", f"{prefix}_set"]
    if include_not:
        names.append(f"{prefix}_not")
    return names


def _refresh_parent_members(scene: dict, gid: str) -> None:
    """Recompute a container parent's members after a child group changes."""
    from flyvibing_node_editor.ops import _resolve_node

    groups = _group_map(scene)
    child = groups.get(gid) or {}
    parent_gid = child.get("parent")
    parent = groups.get(parent_gid) if parent_gid else None
    if parent is None or parent.get("type") != "container":
        return
    members: list[int] = []
    for cgid in parent.get("children") or []:
        for mid in (groups.get(cgid) or {}).get("members") or []:
            if int(mid) not in members:
                members.append(int(mid))
    for ref in (parent.get("params") or {}).get("members") or []:
        nid = _resolve_node(scene, ref, {})
        if nid is not None and int(nid) not in members:
            members.append(int(nid))
    parent["members"] = members


def _refresh_parent_slots(scene: dict, gid: str) -> str | None:
    """Propagate rebuilt child slots through container ancestors.

    A container's entry/done defaults to its first/last child group's slots.
    When that child is rebuilt its pin ids change, so every ancestor container
    must update its metadata and retarget links that were attached to the old
    container boundary.
    """
    groups = _group_map(scene)
    links = _graph(scene).setdefault("links", {})
    current = gid
    seen: set[str] = set()
    while True:
        child = groups.get(current) or {}
        parent_gid = child.get("parent")
        if not parent_gid or parent_gid in seen:
            return None
        seen.add(parent_gid)
        parent = groups.get(parent_gid)
        if parent is None or parent.get("type") != "container":
            return None
        _refresh_parent_members(scene, current)

        children = parent.get("children") or []
        if not children:
            return None
        first = groups.get(children[0]) or {}
        last = groups.get(children[-1]) or {}
        params = parent.get("params") or {}
        new_entry, err = _container_slot(
            scene, params.get("entry"), want="input",
            default=(first.get("slots") or {}).get("entry"))
        if err:
            return err
        new_done, err = _container_slot(
            scene, params.get("done"), want="output",
            default=(last.get("slots") or {}).get("done"))
        if err:
            return err

        slots = parent.setdefault("slots", {})
        old_entry = int(slots.get("entry") or 0)
        old_done = int(slots.get("done") or 0)
        new_entry = int(new_entry) if new_entry is not None else None
        new_done = int(new_done) if new_done is not None else None
        if old_entry and new_entry and old_entry != new_entry:
            for link in links.values():
                if int(link.get("to_pin", -1)) == old_entry:
                    link["to_pin"] = new_entry
        if old_done and new_done and old_done != new_done:
            for link in links.values():
                if int(link.get("from_pin", -1)) == old_done:
                    link["from_pin"] = new_done
        slots["entry"] = new_entry
        slots["done"] = new_done
        current = parent_gid


def _attach_parent(scene: dict, gid: str, parent_ref) -> str | None:
    """把 gid 挂到父组的 children 列表（仅元数据；执行关系仍由 slots 连线表达）。"""
    if parent_ref in (None, ""):
        return None
    pgid, parent = _resolve_group(scene, parent_ref)
    if parent is None:
        return f"unknown parent group {parent_ref!r}"
    if pgid == gid:
        return "a group cannot be its own parent"
    group = _group_map(scene).get(gid) or {}
    group["parent"] = pgid
    children = parent.setdefault("children", [])
    if gid not in children:
        children.append(gid)
    _refresh_parent_members(scene, gid)
    return _refresh_parent_slots(scene, gid)


def _add_window_group(scene: dict, op: dict) -> dict:
    """Add a cue_window instance (per-frame linear group)."""
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    params = dict(op.get("params") or {})
    cfg, errors = _window_params(params)
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}

    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}

    gid = f"g{_max_group_id(scene) + 1}"
    prefix = gid
    res = apply_ops(scene, _window_ops(prefix, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _window_member_aliases(prefix, not cfg["visible"])]
    _layout(scene, members)

    clock_node = _graph(scene)["nodes"][str(symbols[f"{prefix}_clock"])]
    set_node = _graph(scene)["nodes"][str(symbols[f"{prefix}_set"])]
    group = {
        "type": "cue_window",
        "version": 1,
        "alias": alias or "",
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": clock_node["pin_ids"]["exec_in"],
                  "done": set_node["pin_ids"]["exec_out"]},
    }
    _group_map(scene)[gid] = group
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _update_window_group(scene: dict, op: dict, gid: str, group: dict) -> dict:
    """Re-expand a cue_window in place; external entry/done links are remapped."""
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    params = dict(group.get("params") or {})
    params.update(op.get("params") or {})
    cfg, errors = _window_params(params)
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}

    alias = str(group.get("alias") or "")
    if op.get("alias") is not None:
        new_alias = str(op.get("alias") or "")
        if new_alias and not valid_alias(new_alias):
            return {"ok": False, "errors": [f"invalid group alias {new_alias!r}"],
                    "scene": scene, "symbols": {}}
        for other_gid, other in _group_map(scene).items():
            if other_gid != gid and new_alias and \
                    str(other.get("alias", "")).lower() == new_alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {new_alias!r} ({other_gid})"],
                        "scene": scene, "symbols": {}}
        alias = new_alias

    slots = group.get("slots") or {}
    old_entry = int(slots.get("entry") or 0)
    old_done = int(slots.get("done") or 0)
    if not old_entry:
        return {"ok": False, "errors": [f"group {gid} has no entry slot"],
                "scene": scene, "symbols": {}}
    links = _graph(scene).get("links", {}) or {}
    inbound = [(lid, int(ld.get("from_pin", -1)))
               for lid, ld in links.items()
               if int(ld.get("to_pin", -1)) == old_entry]
    outbound = [(lid, int(ld.get("to_pin", -1)))
                for lid, ld in links.items()
                if old_done and int(ld.get("from_pin", -1)) == old_done]

    old_parent = group.get("parent")
    new_parent = op.get("parent", old_parent)
    if old_parent and old_parent != new_parent:
        parent = _group_map(scene).get(old_parent)
        if parent is not None:
            children = parent.get("children") or []
            if gid in children:
                children.remove(gid)

    _delete_nodes(scene, list(group.get("members") or []))
    res = apply_ops(scene, _window_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _window_member_aliases(gid, not cfg["visible"])]
    _layout(scene, members)

    clock_node = _graph(scene)["nodes"][str(symbols[f"{gid}_clock"])]
    set_node = _graph(scene)["nodes"][str(symbols[f"{gid}_set"])]
    new_group = {
        "type": "cue_window",
        "version": int(group.get("version", 1)) + 1,
        "alias": alias,
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": clock_node["pin_ids"]["exec_in"],
                  "done": set_node["pin_ids"]["exec_out"]},
    }
    if new_parent:
        new_group["parent"] = new_parent
    _group_map(scene)[gid] = new_group
    if new_parent:
        parent_error = _attach_parent(scene, gid, new_parent)
        if parent_error:
            return {"ok": False, "errors": [parent_error], "scene": scene,
                    "symbols": {}}

    links = _graph(scene).setdefault("links", {})
    entry_pin = int(new_group["slots"]["entry"])
    done_pin = int(new_group["slots"]["done"])
    valid_pins = {
        int(pid)
        for nd in _graph(scene).get("nodes", {}).values()
        for pid in (nd.get("pin_ids") or {}).values()
    }
    for _lid, from_pin in inbound:
        if int(from_pin) in valid_pins:
            links[str(_next_link_id(scene))] = {"from_pin": int(from_pin),
                                                "to_pin": entry_pin}
    if old_done:
        for _lid, to_pin in outbound:
            if int(to_pin) in valid_pins:
                links[str(_next_link_id(scene))] = {"from_pin": done_pin,
                                                    "to_pin": int(to_pin)}
    slot_error = _refresh_parent_slots(scene, gid)
    if slot_error:
        return {"ok": False, "errors": [slot_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _hide_params(params: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    raw = params.get("entities")
    if raw is None:
        single = params.get("entity")
        raw = [single] if single else []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        errors.append("params.entities must be a list of entity names")
        raw = []
    names: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        errors.append("params.entities needs at least one entity name")
    if len(names) > 16:
        errors.append("params.entities supports at most 16 roots")
    return {"entities": names, "visible": bool(params.get("visible", False))}, errors


def _hide_ops(prefix: str, cfg: dict) -> list[dict]:
    """EntityGet × N → EntityGetTree × N → EntityListMerge → EntityListSetVisible."""
    ops: list[dict] = []
    for i, name in enumerate(cfg["entities"]):
        ops.append({
            "op": "add_node", "type": "EntityGet",
            "props": {"entity_name": name}, "as": f"{prefix}_get{i}",
            "description": f"Resolve runtime entity {name!r}.",
        })
        ops.append({
            "op": "add_node", "type": "EntityGetTree", "props": {},
            "as": f"{prefix}_tree{i}",
            "description": f"Collect {name!r} and all descendants.",
        })
        ops.append({"op": "link", "from": [f"{prefix}_get{i}", "Entity"],
                    "to": [f"{prefix}_tree{i}", "Entity"]})
        if i > 0:
            ops.append({"op": "link", "from": [f"{prefix}_get{i-1}", "exec_out"],
                        "to": [f"{prefix}_get{i}", "exec_in"]})

    current = f"{prefix}_tree0"
    for i in range(1, len(cfg["entities"])):
        alias = f"{prefix}_merge{i}"
        ops.append({"op": "add_node", "type": "EntityListMerge", "props": {},
                    "as": alias,
                    "description": "Merge entity tree lists."})
        ops.append({"op": "link", "from": [current, "Entities"],
                    "to": [alias, "A"]})
        ops.append({"op": "link", "from": [f"{prefix}_tree{i}", "Entities"],
                    "to": [alias, "B"]})
        current = alias

    value = 1.0 if cfg["visible"] else 0.0
    ops += [
        {"op": "add_node", "type": "Constant", "props": {"value": value},
         "as": f"{prefix}_visible",
         "description": f"Visible={value:g} for this group."},
        {"op": "add_node", "type": "EntityListSetVisible", "props": {},
         "as": f"{prefix}_set",
         "description": "Apply visibility to the whole entity tree in one batch."},
        {"op": "link", "from": [f"{prefix}_get{len(cfg['entities'])-1}", "exec_out"],
         "to": [f"{prefix}_set", "exec_in"]},
        {"op": "link", "from": [current, "Entities"],
         "to": [f"{prefix}_set", "Entities"]},
        {"op": "link", "from": [f"{prefix}_visible", "Result"],
         "to": [f"{prefix}_set", "Visible"]},
    ]
    return ops


def _hide_member_aliases(prefix: str, count: int) -> list[str]:
    names = []
    for i in range(count):
        names += [f"{prefix}_get{i}", f"{prefix}_tree{i}"]
    names += [f"{prefix}_merge{i}" for i in range(1, count)]
    names += [f"{prefix}_visible", f"{prefix}_set"]
    return names


def _add_hide_group(scene: dict, op: dict) -> dict:
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    cfg, errors = _hide_params(dict(op.get("params") or {}))
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}

    gid = f"g{_max_group_id(scene) + 1}"
    res = apply_ops(scene, _hide_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _hide_member_aliases(gid, len(cfg["entities"]))]
    _layout(scene, members)
    first = _graph(scene)["nodes"][str(symbols[f"{gid}_get0"])]
    last = _graph(scene)["nodes"][str(symbols[f"{gid}_set"])]
    _group_map(scene)[gid] = {
        "type": "hide_group",
        "version": 1,
        "alias": alias or "",
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _update_hide_group(scene: dict, op: dict, gid: str, group: dict) -> dict:
    """Re-expand a hide_group in place; external entry/done links are remapped."""
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    params = dict(group.get("params") or {})
    params.update(op.get("params") or {})
    cfg, errors = _hide_params(params)
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = str(group.get("alias") or "")
    if op.get("alias") is not None:
        new_alias = str(op.get("alias") or "")
        if new_alias and not valid_alias(new_alias):
            return {"ok": False, "errors": [f"invalid group alias {new_alias!r}"],
                    "scene": scene, "symbols": {}}
        for other_gid, other in _group_map(scene).items():
            if other_gid != gid and new_alias and \
                    str(other.get("alias", "")).lower() == new_alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {new_alias!r} ({other_gid})"],
                        "scene": scene, "symbols": {}}
        alias = new_alias

    slots = group.get("slots") or {}
    old_entry = int(slots.get("entry") or 0)
    old_done = int(slots.get("done") or 0)
    if not old_entry:
        return {"ok": False, "errors": [f"group {gid} has no entry slot"],
                "scene": scene, "symbols": {}}
    links = _graph(scene).get("links", {}) or {}
    inbound = [(lid, int(ld.get("from_pin", -1)))
               for lid, ld in links.items()
               if int(ld.get("to_pin", -1)) == old_entry]
    outbound = [(lid, int(ld.get("to_pin", -1)))
                for lid, ld in links.items()
                if old_done and int(ld.get("from_pin", -1)) == old_done]

    old_parent = group.get("parent")
    new_parent = op.get("parent", old_parent)
    if old_parent and old_parent != new_parent:
        parent = _group_map(scene).get(old_parent)
        if parent is not None:
            children = parent.get("children") or []
            if gid in children:
                children.remove(gid)

    _delete_nodes(scene, list(group.get("members") or []))
    res = apply_ops(scene, _hide_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _hide_member_aliases(gid, len(cfg["entities"]))]
    _layout(scene, members)
    first = _graph(scene)["nodes"][str(symbols[f"{gid}_get0"])]
    last = _graph(scene)["nodes"][str(symbols[f"{gid}_set"])]
    new_group = {
        "type": "hide_group",
        "version": int(group.get("version", 1)) + 1,
        "alias": alias,
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    if new_parent:
        new_group["parent"] = new_parent
    _group_map(scene)[gid] = new_group
    if new_parent:
        parent_error = _attach_parent(scene, gid, new_parent)
        if parent_error:
            return {"ok": False, "errors": [parent_error], "scene": scene,
                    "symbols": {}}

    links = _graph(scene).setdefault("links", {})
    entry_pin = int(new_group["slots"]["entry"])
    done_pin = int(new_group["slots"]["done"])
    valid_pins = {
        int(pid)
        for nd in _graph(scene).get("nodes", {}).values()
        for pid in (nd.get("pin_ids") or {}).values()
    }
    for _lid, from_pin in inbound:
        if int(from_pin) in valid_pins:
            links[str(_next_link_id(scene))] = {"from_pin": int(from_pin),
                                                "to_pin": entry_pin}
    if old_done:
        for _lid, to_pin in outbound:
            if int(to_pin) in valid_pins:
                links[str(_next_link_id(scene))] = {"from_pin": done_pin,
                                                    "to_pin": int(to_pin)}
    slot_error = _refresh_parent_slots(scene, gid)
    if slot_error:
        return {"ok": False, "errors": [slot_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _container_slot(scene: dict, ref, *, default, want: str) -> tuple[int | None, str | None]:
    """Resolve [node, pin] / {@group, slot} / None into a pin id."""
    from flyvibing_node_editor.ops import _pin_id, _resolve_node

    if ref in (None, ""):
        return default, None
    node_ref = None
    pin_name = None
    if isinstance(ref, (list, tuple)) and len(ref) == 2:
        node_ref, pin_name = ref
    elif isinstance(ref, dict):
        node_ref, pin_name = ref.get("node"), ref.get("pin")
    else:
        return None, f"invalid slot ref {ref!r} (use [node, pin])"
    if node_ref is None or pin_name is None:
        return None, f"invalid slot ref {ref!r} (use [node, pin])"
    if isinstance(node_ref, str) and node_ref.strip().startswith("@"):
        _gid, group = _resolve_group(scene, node_ref)
        if group is None:
            return None, f"unknown slot group {node_ref!r}"
        pin = (group.get("slots") or {}).get(str(pin_name))
        return (int(pin), None) if pin is not None else (
            None, f"group {node_ref!r} has no slot {pin_name!r}")
    nid = _resolve_node(scene, node_ref, {})
    if nid is None:
        return None, f"unknown slot node {node_ref!r}"
    pin = _pin_id(scene, nid, str(pin_name), direction=want)
    if pin is None:
        return None, f"unknown {want} pin {pin_name!r}@#{nid}"
    return int(pin), None


def _add_container_group(scene: dict, op: dict) -> dict:
    """Wrap existing child groups without generating execution nodes."""
    from flyvibing_node_editor.ops import _resolve_node, valid_alias

    scene = copy.deepcopy(scene)
    params = dict(op.get("params") or {})
    raw_children = params.get("children") or []
    if isinstance(raw_children, str):
        raw_children = [raw_children]
    if not isinstance(raw_children, list):
        return {"ok": False, "errors": ["params.children must be a list"],
                "scene": scene, "symbols": {}}
    raw_members = params.get("members") or []
    if not raw_children and not raw_members:
        return {"ok": False,
                "errors": ["params.children or params.members needs >= 1 item"],
                "scene": scene, "symbols": {}}
    child_gids: list[str] = []
    child_groups: list[dict] = []
    for ref in raw_children:
        cgid, cgroup = _resolve_group(scene, ref)
        if cgroup is None:
            return {"ok": False, "errors": [f"unknown child group {ref!r}"],
                    "scene": scene, "symbols": {}}
        if cgid in child_gids:
            return {"ok": False, "errors": [f"duplicate child group {cgid}"],
                    "scene": scene, "symbols": {}}
        child_gids.append(cgid)
        child_groups.append(cgroup)

    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}

    entry, err = _container_slot(
        scene, params.get("entry"), want="input",
        default=((child_groups[0].get("slots") or {}).get("entry")
                 if child_groups else None))
    if err:
        return {"ok": False, "errors": [err], "scene": scene, "symbols": {}}
    done, err = _container_slot(
        scene, params.get("done"), want="output",
        default=((child_groups[-1].get("slots") or {}).get("done")
                 if child_groups else None))
    if err:
        return {"ok": False, "errors": [err], "scene": scene, "symbols": {}}
    if entry is None:
        return {"ok": False, "errors": ["container has no entry pin"],
                "scene": scene, "symbols": {}}

    members: list[int] = []
    for child in child_groups:
        for mid in child.get("members") or []:
            if int(mid) not in members:
                members.append(int(mid))
    for ref in params.get("members") or []:
        nid = _resolve_node(scene, ref, {})
        if nid is None:
            return {"ok": False, "errors": [f"unknown extra member {ref!r}"],
                    "scene": scene, "symbols": {}}
        if int(nid) not in members:
            members.append(int(nid))

    gid = f"g{_max_group_id(scene) + 1}"
    _group_map(scene)[gid] = {
        "type": "container",
        "version": 1,
        "alias": alias or "",
        "params": {"children": child_gids,
                   "entry": params.get("entry"),
                   "done": params.get("done")},
        "members": members,
        "children": child_gids,
        "slots": {"entry": int(entry),
                  "done": int(done) if done is not None else None},
    }
    for cgid, child in zip(child_gids, child_groups):
        old_parent = child.get("parent")
        if old_parent and old_parent != gid:
            parent = _group_map(scene).get(old_parent)
            if parent is not None:
                siblings = parent.get("children") or []
                if cgid in siblings:
                    siblings.remove(cgid)
        child["parent"] = gid
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    _layout(scene, members)
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _update_container_group(scene: dict, op: dict, gid: str, group: dict) -> dict:
    """Update children/aliases without touching execution nodes."""
    from flyvibing_node_editor.ops import _resolve_node, valid_alias

    params = dict(group.get("params") or {})
    params.update(op.get("params") or {})
    raw_children = params.get("children") or group.get("children") or []
    if isinstance(raw_children, str):
        raw_children = [raw_children]
    child_gids: list[str] = []
    child_groups: list[dict] = []
    for ref in raw_children:
        cgid, cgroup = _resolve_group(scene, ref)
        if cgroup is None:
            return {"ok": False, "errors": [f"unknown child group {ref!r}"],
                    "scene": scene, "symbols": {}}
        if cgid == gid:
            return {"ok": False, "errors": ["a container cannot contain itself"],
                    "scene": scene, "symbols": {}}
        if cgid not in child_gids:
            child_gids.append(cgid)
            child_groups.append(cgroup)
    if not child_gids and not (params.get("members") or []):
        return {"ok": False,
                "errors": ["params.children or params.members needs >= 1 item"],
                "scene": scene, "symbols": {}}

    alias = str(group.get("alias") or "")
    if op.get("alias") is not None:
        new_alias = str(op.get("alias") or "")
        if new_alias and not valid_alias(new_alias):
            return {"ok": False, "errors": [f"invalid group alias {new_alias!r}"],
                    "scene": scene, "symbols": {}}
        for other_gid, other in _group_map(scene).items():
            if other_gid != gid and new_alias and \
                    str(other.get("alias", "")).lower() == new_alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {new_alias!r} ({other_gid})"],
                        "scene": scene, "symbols": {}}
        alias = new_alias

    entry, err = _container_slot(
        scene, params.get("entry"), want="input",
        default=((child_groups[0].get("slots") or {}).get("entry")
                 if child_groups else None))
    if err:
        return {"ok": False, "errors": [err], "scene": scene, "symbols": {}}
    done, err = _container_slot(
        scene, params.get("done"), want="output",
        default=((child_groups[-1].get("slots") or {}).get("done")
                 if child_groups else None))
    if err:
        return {"ok": False, "errors": [err], "scene": scene, "symbols": {}}

    members: list[int] = []
    for child in child_groups:
        for mid in child.get("members") or []:
            if int(mid) not in members:
                members.append(int(mid))
    for ref in params.get("members") or []:
        nid = _resolve_node(scene, ref, {})
        if nid is None:
            return {"ok": False, "errors": [f"unknown extra member {ref!r}"],
                    "scene": scene, "symbols": {}}
        if int(nid) not in members:
            members.append(int(nid))

    old_children = list(group.get("children") or [])
    for cgid in old_children:
        child = _group_map(scene).get(cgid)
        if child is not None and child.get("parent") == gid and cgid not in child_gids:
            child.pop("parent", None)
    for cgid, child in zip(child_gids, child_groups):
        child["parent"] = gid
    group.update({
        "version": int(group.get("version", 1)) + 1,
        "alias": alias,
        "params": {"children": child_gids,
                   "entry": params.get("entry"),
                   "done": params.get("done")},
        "members": members,
        "children": child_gids,
        "slots": {"entry": int(entry) if entry is not None else None,
                  "done": int(done) if done is not None else None},
    })
    _layout(scene, members)
    if group.get("parent"):
        slot_error = _refresh_parent_slots(scene, gid)
        if slot_error:
            return {"ok": False, "errors": [slot_error], "scene": scene,
                    "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _mi_select_params(params: dict) -> tuple[dict, list[str]]:
    mi_var = str(params.get("mi_var", "mi_code") or "mi_code").strip() or "mi_code"
    arms, errors = _validate_arms(params)
    return {"mi_var": mi_var, "arms": arms}, errors


def _mi_select_member_aliases(prefix: str, arms: list[dict]) -> list[str]:
    names = [f"{prefix}_random", f"{prefix}_mi", f"{prefix}_mi_get"]
    for i, arm in enumerate(arms, start=1):
        names += [f"{prefix}_code{i}", f"{prefix}_cmp{i}"]
        for j in range(len(arm["entities"])):
            names += [f"{prefix}_get{i}_{j}", f"{prefix}_set{i}_{j}"]
    return names


def _mi_select_ops(prefix: str, cfg: dict) -> list[dict]:
    """Random MI -> mi_code -> per-cue Compare/SetVisible; one linear exec chain."""
    arms = cfg["arms"]
    ops: list[dict] = [
        {"op": "add_node", "type": "Random",
         "props": {"distribution": "discrete", "min": 1, "max": len(arms)},
         "as": f"{prefix}_random",
         "description": "Phase 0: choose one MI class."},
        {"op": "add_node", "type": "VarSet",
         "props": {"mode": "pin", "var_name": cfg["mi_var"]},
         "as": f"{prefix}_mi",
         "description": "Store the selected MI code for the trial."},
        {"op": "add_node", "type": "VarGet",
         "props": {"var_name": cfg["mi_var"]}, "as": f"{prefix}_mi_get",
         "description": "Read the selected MI code."},
        {"op": "link", "from": [f"{prefix}_random", "Result"],
         "to": [f"{prefix}_mi", "Value"]},
    ]
    prev_exec = f"{prefix}_mi"
    for i, arm in enumerate(arms, start=1):
        ops += [
            {"op": "add_node", "type": "Constant", "props": {"value": arm["code"]},
             "as": f"{prefix}_code{i}",
             "description": f"MI code {arm['code']} for arm {arm['id']!r}."},
            {"op": "add_node", "type": "Compare",
             "props": {"operation": "eq"}, "as": f"{prefix}_cmp{i}",
             "description": f"mi_code == {arm['code']}?"},
            {"op": "link", "from": [f"{prefix}_mi_get", "Value"],
             "to": [f"{prefix}_cmp{i}", "A"]},
            {"op": "link", "from": [f"{prefix}_code{i}", "Result"],
             "to": [f"{prefix}_cmp{i}", "B"]},
        ]
        for j, entity in enumerate(arm["entities"]):
            get = f"{prefix}_get{i}_{j}"
            set_ = f"{prefix}_set{i}_{j}"
            ops += [
                {"op": "add_node", "type": "EntityGet",
                 "props": {"entity_name": entity}, "as": get,
                 "description": f"Resolve cue part {entity!r}."},
                {"op": "add_node", "type": "EntitySetRenderVisible", "props": {},
                 "as": set_,
                 "description": f"Set {entity!r} visible when MI={arm['code']}."},
                {"op": "link", "from": [prev_exec, "exec_out"],
                 "to": [get, "exec_in"]},
                {"op": "link", "from": [get, "exec_out"], "to": [set_, "exec_in"]},
                {"op": "link", "from": [get, "Entity"], "to": [set_, "EntityID"]},
                {"op": "link", "from": [f"{prefix}_cmp{i}", "Result"],
                 "to": [set_, "Visible"]},
            ]
            prev_exec = set_
    return ops


def _add_mi_select(scene: dict, op: dict) -> dict:
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    cfg, errors = _mi_select_params(dict(op.get("params") or {}))
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}
    gid = f"g{_max_group_id(scene) + 1}"
    res = apply_ops(scene, _mi_select_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _mi_select_member_aliases(gid, cfg["arms"])]
    _layout(scene, members)
    first = _graph(scene)["nodes"][str(symbols[f"{gid}_mi"])]
    last = _graph(scene)["nodes"][str(members[-1])]
    _group_map(scene)[gid] = {
        "type": "mi_select",
        "version": 1,
        "alias": alias or "",
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _phase0_trigger_params(params: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        scale = int(params.get("mi_scale", 32))
    except (TypeError, ValueError):
        errors.append("params.mi_scale must be an integer")
        scale = 32
    try:
        address = int(params.get("address", 16376))
    except (TypeError, ValueError):
        errors.append("params.address must be an integer")
        address = 16376
    return {
        "mi_var": str(params.get("mi_var", "mi_code") or "mi_code"),
        "sss_var": str(params.get("sss_var", "sss_code") or "sss_code"),
        "trigger_var": str(params.get("trigger_var", "trigger_val") or "trigger_val"),
        "mi_scale": scale,
        "address": address,
    }, errors


def _phase0_trigger_member_aliases(prefix: str) -> list[str]:
    return [f"{prefix}_mi", f"{prefix}_sss", f"{prefix}_scale",
            f"{prefix}_mul", f"{prefix}_sum", f"{prefix}_trigger",
            f"{prefix}_trigger_get", f"{prefix}_send"]


def _phase0_trigger_ops(prefix: str, cfg: dict) -> list[dict]:
    return [
        {"op": "add_node", "type": "VarGet", "props": {"var_name": cfg["mi_var"]},
         "as": f"{prefix}_mi", "description": "Read selected MI code."},
        {"op": "add_node", "type": "VarGet", "props": {"var_name": cfg["sss_var"]},
         "as": f"{prefix}_sss", "description": "Read precomputed SSSEP code."},
        {"op": "add_node", "type": "Constant", "props": {"value": cfg["mi_scale"]},
         "as": f"{prefix}_scale", "description": "MI bit shift scale."},
        {"op": "add_node", "type": "ScalarMath",
         "props": {"operation": "multiply"}, "as": f"{prefix}_mul",
         "description": "mi_code * 32."},
        {"op": "add_node", "type": "ScalarMath",
         "props": {"operation": "sum"}, "as": f"{prefix}_sum",
         "description": "(mi_code * 32) + sss_code."},
        {"op": "add_node", "type": "VarSet",
         "props": {"mode": "pin", "var_name": cfg["trigger_var"]},
         "as": f"{prefix}_trigger", "description": "Store Phase 0 trigger."},
        {"op": "add_node", "type": "VarGet",
         "props": {"var_name": cfg["trigger_var"]},
         "as": f"{prefix}_trigger_get", "description": "Read Phase 0 trigger."},
        {"op": "add_node", "type": "ParallelSend",
         "props": {"mode": "pin", "address": cfg["address"]},
         "as": f"{prefix}_send",
         "description": "Send Phase 0 trigger once (cue onset)."},
        {"op": "link", "from": [f"{prefix}_mi", "Value"],
         "to": [f"{prefix}_mul", "In_0"]},
        {"op": "link", "from": [f"{prefix}_scale", "Result"],
         "to": [f"{prefix}_mul", "In_1"]},
        {"op": "link", "from": [f"{prefix}_mul", "Result"],
         "to": [f"{prefix}_sum", "In_0"]},
        {"op": "link", "from": [f"{prefix}_sss", "Value"],
         "to": [f"{prefix}_sum", "In_1"]},
        {"op": "link", "from": [f"{prefix}_sum", "Result"],
         "to": [f"{prefix}_trigger", "Value"]},
        {"op": "link", "from": [f"{prefix}_trigger", "exec_out"],
         "to": [f"{prefix}_send", "exec_in"]},
        {"op": "link", "from": [f"{prefix}_trigger_get", "Value"],
         "to": [f"{prefix}_send", "Value"]},
    ]


def _add_phase0_trigger(scene: dict, op: dict) -> dict:
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    cfg, errors = _phase0_trigger_params(dict(op.get("params") or {}))
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}
    gid = f"g{_max_group_id(scene) + 1}"
    res = apply_ops(scene, _phase0_trigger_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _phase0_trigger_member_aliases(gid)]
    _layout(scene, members)
    first = _graph(scene)["nodes"][str(symbols[f"{gid}_trigger"])]
    last = _graph(scene)["nodes"][str(symbols[f"{gid}_send"])]
    _group_map(scene)[gid] = {
        "type": "phase0_trigger",
        "version": 1,
        "alias": alias or "",
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _sss_pulse_params(params: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        interval = float(params.get("interval", -0.0499))
    except (TypeError, ValueError):
        errors.append("params.interval must be a number")
        interval = -0.0499
    try:
        address = int(params.get("address", 16376))
    except (TypeError, ValueError):
        errors.append("params.address must be an integer")
        address = 16376
    try:
        baud = int(params.get("serial_baud", 9600))
    except (TypeError, ValueError):
        errors.append("params.serial_baud must be an integer")
        baud = 9600
    return {
        "value_var": str(params.get("value_var", "sss_code") or "sss_code"),
        "count_var": str(params.get("count_var", "pulse_count") or "pulse_count"),
        "timer": str(params.get("timer", "pulse") or "pulse"),
        "interval": interval,
        "address": address,
        "serial_port": str(params.get("serial_port", "@SSSEP-Stimulator")
                           or "@SSSEP-Stimulator"),
        "serial_baud": baud,
    }, errors


def _sss_pulse_member_aliases(prefix: str) -> list[str]:
    return [f"{prefix}_value", f"{prefix}_parallel", f"{prefix}_serial",
            f"{prefix}_count", f"{prefix}_one", f"{prefix}_sum",
            f"{prefix}_count_set", f"{prefix}_timer"]


def _sss_pulse_ops(prefix: str, cfg: dict) -> list[dict]:
    return [
        {"op": "add_node", "type": "VarGet", "props": {"var_name": cfg["value_var"]},
         "as": f"{prefix}_value", "description": "Read SSSEP code."},
        {"op": "add_node", "type": "ParallelSend",
         "props": {"mode": "pin", "address": cfg["address"]},
         "as": f"{prefix}_parallel",
         "description": "20 Hz pulse: parallel SSSEP code."},
        {"op": "add_node", "type": "SerialSend",
         "props": {"mode": "pin", "format": "string",
                   "port": cfg["serial_port"], "baud_rate": cfg["serial_baud"]},
         "as": f"{prefix}_serial",
         "description": "20 Hz pulse: serial SSSEP code."},
        {"op": "add_node", "type": "VarGet",
         "props": {"var_name": cfg["count_var"]},
         "as": f"{prefix}_count", "description": "Read pulse count."},
        {"op": "add_node", "type": "Constant", "props": {"value": 1},
         "as": f"{prefix}_one", "description": "Pulse count increment."},
        {"op": "add_node", "type": "ScalarMath",
         "props": {"operation": "sum"}, "as": f"{prefix}_sum",
         "description": "pulse_count + 1."},
        {"op": "add_node", "type": "VarSet",
         "props": {"mode": "pin", "var_name": cfg["count_var"]},
         "as": f"{prefix}_count_set", "description": "Store incremented count."},
        {"op": "add_node", "type": "SetTimer",
         "props": {"operate": "set_time", "mode": "manual",
                   "timer_name": cfg["timer"], "value": cfg["interval"]},
         "as": f"{prefix}_timer", "description": "Re-arm the 20 Hz pulse timer."},
        {"op": "link", "from": [f"{prefix}_value", "Value"],
         "to": [f"{prefix}_parallel", "Value"]},
        {"op": "link", "from": [f"{prefix}_value", "Value"],
         "to": [f"{prefix}_serial", "Value"]},
        {"op": "link", "from": [f"{prefix}_parallel", "exec_out"],
         "to": [f"{prefix}_serial", "exec_in"]},
        {"op": "link", "from": [f"{prefix}_serial", "exec_out"],
         "to": [f"{prefix}_count_set", "exec_in"]},
        {"op": "link", "from": [f"{prefix}_count", "Value"],
         "to": [f"{prefix}_sum", "In_0"]},
        {"op": "link", "from": [f"{prefix}_one", "Result"],
         "to": [f"{prefix}_sum", "In_1"]},
        {"op": "link", "from": [f"{prefix}_sum", "Result"],
         "to": [f"{prefix}_count_set", "Value"]},
        {"op": "link", "from": [f"{prefix}_count_set", "exec_out"],
         "to": [f"{prefix}_timer", "exec_in"]},
    ]


def _add_sss_pulse(scene: dict, op: dict) -> dict:
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    cfg, errors = _sss_pulse_params(dict(op.get("params") or {}))
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}
    gid = f"g{_max_group_id(scene) + 1}"
    res = apply_ops(scene, _sss_pulse_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    members = [symbols[n] for n in _sss_pulse_member_aliases(gid)]
    _layout(scene, members)
    first = _graph(scene)["nodes"][str(symbols[f"{gid}_parallel"])]
    last = _graph(scene)["nodes"][str(symbols[f"{gid}_timer"])]
    _group_map(scene)[gid] = {
        "type": "sss_pulse",
        "version": 1,
        "alias": alias or "",
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _update_linear_group(scene: dict, op: dict, gid: str, group: dict,
                         parse, build_ops, member_aliases,
                         entry_suffix: str = "", done_suffix: str = "") -> dict:
    """Re-expand a generated linear group in place and remap external slots."""
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    params = dict(group.get("params") or {})
    params.update(op.get("params") or {})
    cfg, errors = parse(params)
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}
    alias = str(group.get("alias") or "")
    if op.get("alias") is not None:
        new_alias = str(op.get("alias") or "")
        if new_alias and not valid_alias(new_alias):
            return {"ok": False, "errors": [f"invalid group alias {new_alias!r}"],
                    "scene": scene, "symbols": {}}
        for other_gid, other in _group_map(scene).items():
            if other_gid != gid and new_alias and \
                    str(other.get("alias", "")).lower() == new_alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {new_alias!r} ({other_gid})"],
                        "scene": scene, "symbols": {}}
        alias = new_alias

    slots = group.get("slots") or {}
    old_entry = int(slots.get("entry") or 0)
    old_done = int(slots.get("done") or 0)
    if not old_entry:
        return {"ok": False, "errors": [f"group {gid} has no entry slot"],
                "scene": scene, "symbols": {}}
    links = _graph(scene).get("links", {}) or {}
    inbound = [(lid, int(ld.get("from_pin", -1)))
               for lid, ld in links.items()
               if int(ld.get("to_pin", -1)) == old_entry]
    outbound = [(lid, int(ld.get("to_pin", -1)))
                for lid, ld in links.items()
                if old_done and int(ld.get("from_pin", -1)) == old_done]

    old_parent = group.get("parent")
    new_parent = op.get("parent", old_parent)
    if old_parent and old_parent != new_parent:
        parent = _group_map(scene).get(old_parent)
        if parent is not None:
            children = parent.get("children") or []
            if gid in children:
                children.remove(gid)

    _delete_nodes(scene, list(group.get("members") or []))
    res = apply_ops(scene, build_ops(gid, cfg))
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]
    names = member_aliases(gid, cfg)
    members = [symbols[n] for n in names]
    _layout(scene, members)
    first_alias = f"{gid}_{entry_suffix}" if entry_suffix else names[0]
    last_alias = f"{gid}_{done_suffix}" if done_suffix else names[-1]
    first = _graph(scene)["nodes"][str(symbols[first_alias])]
    last = _graph(scene)["nodes"][str(symbols[last_alias])]
    new_group = {
        "type": group.get("type"),
        "version": int(group.get("version", 1)) + 1,
        "alias": alias,
        "params": cfg,
        "members": members,
        "chain_members": list(members),
        "slots": {"entry": first["pin_ids"]["exec_in"],
                  "done": last["pin_ids"]["exec_out"]},
    }
    if new_parent:
        new_group["parent"] = new_parent
    _group_map(scene)[gid] = new_group
    if new_parent:
        parent_error = _attach_parent(scene, gid, new_parent)
        if parent_error:
            return {"ok": False, "errors": [parent_error], "scene": scene,
                    "symbols": {}}

    links = _graph(scene).setdefault("links", {})
    entry_pin = int(new_group["slots"]["entry"])
    done_pin = int(new_group["slots"]["done"])
    valid_pins = {
        int(pid)
        for nd in _graph(scene).get("nodes", {}).values()
        for pid in (nd.get("pin_ids") or {}).values()
    }
    for _lid, from_pin in inbound:
        if int(from_pin) in valid_pins:
            links[str(_next_link_id(scene))] = {"from_pin": int(from_pin),
                                                "to_pin": entry_pin}
    if old_done:
        for _lid, to_pin in outbound:
            if int(to_pin) in valid_pins:
                links[str(_next_link_id(scene))] = {"from_pin": done_pin,
                                                    "to_pin": int(to_pin)}
    slot_error = _refresh_parent_slots(scene, gid)
    if slot_error:
        return {"ok": False, "errors": [slot_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _arm_symbols(prefix: str, arm: dict) -> dict:
    """一个 arm 的节点别名（与 _arm_ops 的 `as` 一致）。"""
    p = f"{prefix}_{arm['id']}"
    n = len(arm["entities"])
    out = {
        "get": [f"{p}_get{i}" for i in range(n)],
        "set": f"{p}_set",
        "send": f"{p}_send",
        "code": f"{p}_code",
        "pack": [],
        "merge": [],
    }
    if n > 1:
        for i in range((n + 3) // 4):
            out["pack"].append(f"{p}_pack{i}")
            if i > 0:
                out["merge"].append(f"{p}_merge{i}")
    return out


def _arm_ops(prefix: str, arm: dict, addr: int) -> list[dict]:
    """一个 arm 的动作子图。

    单实体: EntityGet → EntitySetRenderVisible → ParallelSend（兼容旧图）
    多实体: EntityGet×N → EntityPack/Merge → EntityListSetVisible → ParallelSend
            （单批命令，复合 cue 同帧显隐）
    返回值 = 要执行的 ops；exec 链入口由调用方连到第一个 `_get0`。
    """
    p = f"{prefix}_{arm['id']}"
    sym = _arm_symbols(prefix, arm)
    entities = arm["entities"]
    ops: list[dict] = []

    for i, name in enumerate(entities):
        ops.append({"op": "add_node", "type": "EntityGet",
                    "props": {"entity_name": name}, "as": f"{p}_get{i}",
                    "description": f"Resolve runtime entity {name!r} "
                                   f"(spawned from its scene template)."})
        if i > 0:
            ops.append({"op": "link", "from": [f"{p}_get{i-1}", "exec_out"],
                        "to": [f"{p}_get{i}", "exec_in"]})

    ops += [
        {"op": "add_node", "type": "ParallelSend",
         "props": {"mode": "pin", "address": addr}, "as": f"{p}_send",
         "description": f"Send cue code {arm['code']} to parallel address {addr}."},
        {"op": "add_node", "type": "Constant",
         "props": {"value": arm["code"]}, "as": f"{p}_code",
         "description": f"Cue code {arm['code']} for arm {arm['id']!r}."},
        {"op": "link", "from": [f"{p}_code", "Result"], "to": [f"{p}_send", "Value"]},
    ]

    if len(entities) == 1:
        ops += [
            {"op": "add_node", "type": "EntitySetRenderVisible", "props": {},
             "as": f"{p}_set",
             "description": f"Show entity {entities[0]!r} (single-mesh arm)."},
            {"op": "link", "from": [f"{p}_get0", "exec_out"],
             "to": [f"{p}_set", "exec_in"]},
            {"op": "link", "from": [f"{p}_get0", "Entity"],
             "to": [f"{p}_set", "EntityID"]},
            {"op": "link", "from": [f"{p}_set", "exec_out"],
             "to": [f"{p}_send", "exec_in"]},
        ]
        return ops

    # 多实体: 每 4 个打包，再合并成一条 entity_list
    packs: list[str] = []
    for pack_idx in range(0, len(entities), 4):
        pack_name = f"{p}_pack{len(packs)}"
        packs.append(pack_name)
        ops.append({"op": "add_node", "type": "EntityPack", "props": {},
                    "as": pack_name,
                    "description": f"Pack arm {arm['id']!r} mesh entities into one list."})
        for slot, ent_idx in enumerate(range(pack_idx, min(pack_idx + 4, len(entities))), start=1):
            ops.append({"op": "link", "from": [f"{p}_get{ent_idx}", "Entity"],
                        "to": [pack_name, f"Entity{slot}"]})

    current = packs[0]
    for i, nxt in enumerate(packs[1:], start=1):
        merge_name = f"{p}_merge{i}"
        ops += [
            {"op": "add_node", "type": "EntityListMerge", "props": {},
             "as": merge_name,
             "description": "Merge packed entity lists for this arm."},
            {"op": "link", "from": [current, "Entities"], "to": [merge_name, "A"]},
            {"op": "link", "from": [nxt, "Entities"], "to": [merge_name, "B"]},
        ]
        current = merge_name

    ops += [
        {"op": "add_node", "type": "EntityListSetVisible", "props": {},
         "as": f"{p}_set",
         "description": f"Show all parts of arm {arm['id']!r} in one atomic batch."},
        {"op": "link", "from": [f"{p}_get{len(entities)-1}", "exec_out"],
         "to": [f"{p}_set", "exec_in"]},
        {"op": "link", "from": [current, "Entities"],
         "to": [f"{p}_set", "Entities"]},
        {"op": "link", "from": [f"{p}_set", "exec_out"],
         "to": [f"{p}_send", "exec_in"]},
    ]
    return ops


def _chain_ops(prefix: str, arms: list[dict]) -> list[dict]:
    """决策链：Random → (Compare/Branch) × N。"""
    n = len(arms)
    ops: list[dict] = [
        {"op": "add_node", "type": "Random",
         "props": {"distribution": "discrete", "min": 1, "max": n},
         "as": f"{prefix}_rand",
         "description": f"Group entry: pick one of {n} cue arms uniformly."},
    ]
    for i, arm in enumerate(arms, start=1):
        ops += [
            {"op": "add_node", "type": "Constant", "props": {"value": i},
             "as": f"{prefix}_k{i}",
             "description": f"Arm {arm['id']!r} selector value ({i})."},
            {"op": "add_node", "type": "Compare", "props": {"operation": "eq"},
             "as": f"{prefix}_cmp{i}",
             "description": f"Check whether the random draw equals arm {arm['id']!r}."},
            {"op": "add_node", "type": "Branch", "props": {},
             "as": f"{prefix}_br{i}",
             "description": f"If arm {arm['id']!r} was selected, run its cue actions."},
            {"op": "link", "from": [f"{prefix}_rand", "Result"],
             "to": [f"{prefix}_cmp{i}", "A"]},
            {"op": "link", "from": [f"{prefix}_k{i}", "Result"],
             "to": [f"{prefix}_cmp{i}", "B"]},
            {"op": "link", "from": [f"{prefix}_cmp{i}", "Result"],
             "to": [f"{prefix}_br{i}", "Condition"]},
        ]
        if i == 1:
            pass  # entry 由调用方指定
        else:
            ops.append({"op": "link", "from": [f"{prefix}_br{i-1}", "False"],
                        "to": [f"{prefix}_br{i}", "exec_in"]})
    return ops


def _layout(scene: dict, ids: list[int]) -> None:
    nodes = _graph(scene).get("nodes", {})
    for idx, nid in enumerate(ids):
        nd = nodes.get(str(nid))
        if nd is not None:
            nd["pos"] = [100.0 + 220.0 * (idx % 4), 100.0 + 180.0 * (idx // 4)]


def add_group(scene: dict, op: dict) -> dict:
    """展开一个组实例；返回 {"ok","errors","scene","symbols"}。"""
    from flyvibing_node_editor.ops import apply_ops, valid_alias

    scene = copy.deepcopy(scene)
    errors: list[str] = []
    gtype = str(op.get("group_type") or op.get("type") or "").strip()
    if gtype not in list_groups():
        return {"ok": False, "errors": [f"unknown group type {gtype!r}"],
                "scene": scene, "symbols": {}}
    if gtype == "cue_window":
        return _add_window_group(scene, op)
    if gtype == "hide_group":
        return _add_hide_group(scene, op)
    if gtype == "container":
        return _add_container_group(scene, op)
    if gtype == "mi_select":
        return _add_mi_select(scene, op)
    if gtype == "phase0_trigger":
        return _add_phase0_trigger(scene, op)
    if gtype == "sss_pulse":
        return _add_sss_pulse(scene, op)

    params = dict(op.get("params") or {})
    arms, arm_errors = _validate_arms(params)
    errors.extend(arm_errors)
    try:
        addr = int(params.get("addr", 16376))
    except (TypeError, ValueError):
        errors.append("params.addr must be an integer")
        addr = 16376
    if errors:
        return {"ok": False, "errors": errors, "scene": scene, "symbols": {}}

    alias = op.get("alias")
    if alias is not None:
        if not isinstance(alias, str) or not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
        for g in _group_map(scene).values():
            if str(g.get("alias", "")).lower() == alias.lower():
                return {"ok": False,
                        "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}

    gid = f"g{_max_group_id(scene) + 1}"
    prefix = gid

    ops: list[dict] = _chain_ops(prefix, arms)
    for arm in arms:
        ops += _arm_ops(prefix, arm, addr)
    # 链尾 True → arm 起点；第一条 Branch.exec_in 作为组入口（外部链接由调用方处理）
    for i, arm in enumerate(arms, start=1):
        ops.append({"op": "link", "from": [f"{prefix}_br{i}", "True"],
                    "to": [f"{prefix}_{arm['id']}_get0", "exec_in"]})

    res = apply_ops(scene, ops)
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]

    chain_ids = [symbols[f"{prefix}_rand"]]
    arm_members: dict[str, dict] = {}
    for i, arm in enumerate(arms, start=1):
        chain_ids += [symbols[f"{prefix}_k{i}"], symbols[f"{prefix}_cmp{i}"],
                      symbols[f"{prefix}_br{i}"]]
        sym = _arm_symbols(prefix, arm)
        arm_members[arm["id"]] = {
            "get": [symbols[n] for n in sym["get"]],
            "pack": [symbols[n] for n in sym["pack"]],
            "merge": [symbols[n] for n in sym["merge"]],
            "set": symbols[sym["set"]],
            "send": symbols[sym["send"]],
            "code": symbols[sym["code"]],
            "entities": list(arm["entities"]),
        }
    members = list(chain_ids)
    for m in arm_members.values():
        for key in ("get", "pack", "merge"):
            members.extend(m.get(key) or [])
        members.extend([m["set"], m["send"], m["code"]])
    _layout(scene, members)

    # 组入口 = 第一个 Branch 的 exec_in
    first_br = _graph(scene)["nodes"][str(symbols[f"{prefix}_br1"])]
    entry_pin = first_br["pin_ids"]["exec_in"]

    _group_map(scene)[gid] = {
        "type": gtype,
        "version": 1,
        "alias": alias or "",
        "params": {"addr": addr, "arms": arms},
        "members": members,
        "chain_members": chain_ids,
        "arm_members": arm_members,
        "slots": {"entry": entry_pin, "done": None},
    }
    parent_error = _attach_parent(scene, gid, op.get("parent"))
    if parent_error:
        return {"ok": False, "errors": [parent_error], "scene": scene,
                "symbols": {}}
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}


def _group_children(scene: dict, gid: str) -> list[str]:
    groups = _group_map(scene)
    grp = groups.get(gid) or {}
    out: list[str] = []
    for raw in grp.get("children") or []:
        cgid = str(raw)
        if cgid in groups and cgid != gid and cgid not in out:
            out.append(cgid)
    for cgid, child in groups.items():
        if cgid != gid and str((child or {}).get("parent") or "") == gid \
                and cgid not in out:
            out.append(cgid)
    return out


def _group_node_ids(scene: dict, gid: str, seen: set[str] | None = None) -> list[int]:
    if seen is None:
        seen = set()
    if gid in seen:
        return []
    seen.add(gid)
    groups = _group_map(scene)
    grp = groups.get(gid) or {}
    out: list[int] = []
    for raw in grp.get("members") or []:
        try:
            nid = int(raw)
        except (TypeError, ValueError):
            continue
        if nid not in out:
            out.append(nid)
    for cgid in _group_children(scene, gid):
        for nid in _group_node_ids(scene, cgid, seen):
            if nid not in out:
                out.append(nid)
    return out


def _group_ancestors(scene: dict, gid: str) -> list[str]:
    groups = _group_map(scene)
    out: list[str] = []
    seen: set[str] = set()
    cur = str((groups.get(gid) or {}).get("parent") or "")
    while cur and cur in groups and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = str((groups.get(cur) or {}).get("parent") or "")
    return out


def merge_group(scene: dict, op: dict) -> dict:
    """把已有节点合并为 container 组（不移动/删除节点）。"""
    from flyvibing_node_editor.ops import _resolve_node, valid_alias

    scene = copy.deepcopy(scene)
    graph = _graph(scene)
    nodes = graph.get("nodes") or {}
    raw = op.get("nodes") or op.get("node_ids") or []
    if isinstance(raw, str):
        raw = [part for part in raw.replace(" ", ",").split(",") if part]
    if not isinstance(raw, list):
        return {"ok": False, "errors": ["nodes must be a list"], "scene": scene,
                "symbols": {}}
    symbols = op.get("symbols") or {}
    selected: list[int] = []
    for ref in raw:
        nid = _resolve_node(scene, ref, symbols)
        if nid is None:
            return {"ok": False, "errors": [f"unknown node {ref!r}"],
                    "scene": scene, "symbols": {}}
        if nid not in selected:
            selected.append(int(nid))
    if len(selected) < 2:
        return {"ok": False, "errors": ["select at least two nodes to merge"],
                "scene": scene, "symbols": {}}

    groups = _group_map(scene)
    selected_set = set(selected)
    touched: dict[str, set[int]] = {}
    for gid in groups:
        members = set(_group_node_ids(scene, gid))
        hit = members & selected_set
        if hit:
            touched[gid] = hit
    partial = {gid: hit for gid, hit in touched.items()
               if hit and hit != set(_group_node_ids(scene, gid))}
    if partial:
        detail = ", ".join(f"{gid}({len(hit)}/{len(_group_node_ids(scene, gid))})"
                           for gid, hit in sorted(partial.items()))
        return {"ok": False,
                "errors": [f"selection partially covers existing group(s): {detail}"],
                "scene": scene, "symbols": {}}
    fully = {gid for gid, hit in touched.items()
             if hit and hit == set(_group_node_ids(scene, gid))}
    child_gids = [gid for gid in groups
                  if gid in fully
                  and not any(a in fully for a in _group_ancestors(scene, gid))]
    if len(child_gids) == 1 and not (
            selected_set - set(_group_node_ids(scene, child_gids[0]))):
        return {"ok": False, "errors": [f"selection is already group {child_gids[0]}"],
                "scene": scene, "symbols": {}}

    alias = op.get("alias")
    if alias is not None:
        alias = str(alias).strip()
        if alias and not valid_alias(alias):
            return {"ok": False, "errors": [f"invalid group alias {alias!r}"],
                    "scene": scene, "symbols": {}}
    gid = f"g{_max_group_id(scene) + 1}"
    if alias:
        for other in groups.values():
            if str(other.get("alias", "")).lower() == alias.lower():
                return {"ok": False, "errors": [f"duplicate group alias {alias!r}"],
                        "scene": scene, "symbols": {}}
    else:
        alias = f"group_{gid[1:]}"
        taken = {str(g.get("alias", "")).lower() for g in groups.values()}
        n = 2
        while alias.lower() in taken:
            alias = f"group_{gid[1:]}_{n}"
            n += 1

    for child_gid in child_gids:
        child = groups.get(child_gid) or {}
        old_parent = str(child.get("parent") or "")
        if old_parent and old_parent in groups and old_parent != gid:
            groups[old_parent]["children"] = [
                c for c in (groups[old_parent].get("children") or [])
                if str(c) != child_gid
            ]
        child["parent"] = gid

    groups[gid] = {
        "type": "container",
        "version": 1,
        "alias": alias,
        "params": {"children": list(child_gids), "entry": None, "done": None},
        "members": sorted(selected),
        "children": list(child_gids),
        "slots": {},
    }
    return {"ok": True, "errors": [], "scene": scene, "symbols": {},
            "gid": gid, "alias": alias, "nodes": len(selected)}


def ungroup_group(scene: dict, op: dict) -> dict:
    """拆掉一个组框；子组上移到父级，成员节点保留。"""
    scene = copy.deepcopy(scene)
    gid, group = _resolve_group(scene, op.get("group") or op.get("gid"))
    if group is None:
        return {"ok": False, "errors": [f"unknown group {op.get('group')!r}"],
                "scene": scene, "symbols": {}}
    groups = _group_map(scene)
    count = len(_group_node_ids(scene, gid))
    parent = str(group.get("parent") or "")
    parent_group = groups.get(parent) if parent else None
    child_gids = _group_children(scene, gid)
    groups.pop(gid, None)
    for child_gid in child_gids:
        child = groups.get(child_gid)
        if child is None:
            continue
        if parent_group is not None:
            child["parent"] = parent
            siblings = [str(c) for c in (parent_group.get("children") or [])]
            if child_gid not in siblings:
                parent_group["children"] = [*(parent_group.get("children") or []),
                                            child_gid]
        else:
            child.pop("parent", None)
    if parent_group is not None:
        parent_group["children"] = [
            c for c in (parent_group.get("children") or []) if str(c) != gid
        ]
    return {"ok": True, "errors": [], "scene": scene, "symbols": {},
            "gid": gid, "nodes": count, "children": child_gids}


def delete_group(scene: dict, op: dict) -> dict:
    """删除组框（默认递归子组）；只删元数据，成员节点保留。"""
    scene = copy.deepcopy(scene)
    gid, group = _resolve_group(scene, op.get("group") or op.get("gid"))
    if group is None:
        return {"ok": False, "errors": [f"unknown group {op.get('group')!r}"],
                "scene": scene, "symbols": {}}
    groups = _group_map(scene)
    recursive = op.get("recursive") is not False
    targets = [gid]
    if recursive:
        pending = [gid]
        seen: set[str] = set()
        while pending:
            cur = pending.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur != gid:
                targets.append(cur)
            pending.extend(_group_children(scene, cur))
    count = len(_group_node_ids(scene, gid))
    for target in reversed(targets):
        groups.pop(target, None)
    target_set = set(targets)
    for other in groups.values():
        children = [c for c in (other.get("children") or [])
                    if str(c) not in target_set]
        if children or "children" in other:
            other["children"] = children
        if str(other.get("parent") or "") in target_set:
            other.pop("parent", None)
    return {"ok": True, "errors": [], "scene": scene, "symbols": {},
            "gid": gid, "removed": targets, "nodes": count}


def _resolve_group(scene: dict, ref) -> tuple[str | None, dict | None]:
    groups = _graph(scene).get("node_groups") or {}
    name = str(ref or "").lstrip("@")
    if name in groups:
        return name, groups[name]
    for gid, g in groups.items():
        if str(g.get("alias", "")).lower() == name.lower():
            return gid, g
    return None, None


def _arm_pin(scene: dict, nid: int, pin: str) -> int | None:
    nd = _graph(scene).get("nodes", {}).get(str(nid))
    if not nd:
        return None
    return (nd.get("pin_ids") or {}).get(pin)


def update_group(scene: dict, op: dict) -> dict:
    """差异重展开：保留未变 arm 的动作节点，只重建决策链与变动 arm。"""
    from flyvibing_node_editor.ops import apply_ops

    scene = copy.deepcopy(scene)
    gid, group = _resolve_group(scene, op.get("group"))
    if group is None:
        return {"ok": False, "errors": [f"unknown group {op.get('group')!r}"],
                "scene": scene, "symbols": {}}
    if str(group.get("type")) == "cue_window":
        return _update_window_group(scene, op, gid, group)
    if str(group.get("type")) == "hide_group":
        return _update_hide_group(scene, op, gid, group)
    if str(group.get("type")) == "container":
        return _update_container_group(scene, op, gid, group)
    if str(group.get("type")) == "mi_select":
        return _update_linear_group(
            scene, op, gid, group, _mi_select_params, _mi_select_ops,
            lambda p, c: _mi_select_member_aliases(p, c["arms"]),
            entry_suffix="mi")
    if str(group.get("type")) == "phase0_trigger":
        return _update_linear_group(
            scene, op, gid, group, _phase0_trigger_params, _phase0_trigger_ops,
            lambda p, c: _phase0_trigger_member_aliases(p),
            entry_suffix="trigger", done_suffix="send")
    if str(group.get("type")) == "sss_pulse":
        return _update_linear_group(
            scene, op, gid, group, _sss_pulse_params, _sss_pulse_ops,
            lambda p, c: _sss_pulse_member_aliases(p),
            entry_suffix="parallel", done_suffix="timer")

    params = dict(group.get("params") or {})
    params.update(op.get("params") or {})
    arms, arm_errors = _validate_arms(params)
    if arm_errors:
        return {"ok": False, "errors": arm_errors, "scene": scene, "symbols": {}}
    try:
        addr = int(params.get("addr", 16376))
    except (TypeError, ValueError):
        return {"ok": False, "errors": ["params.addr must be an integer"],
                "scene": scene, "symbols": {}}

    old_entry = (group.get("slots") or {}).get("entry")
    if old_entry is None:
        return {"ok": False, "errors": [f"group {gid} has no entry slot"],
                "scene": scene, "symbols": {}}
    old_entry = int(old_entry)
    old_arms = group.get("arm_members") or {}
    old_arm_params = {str(a.get("id")): a
                      for a in (group.get("params", {}).get("arms") or [])}
    new_by_id = {a["id"]: a for a in arms}

    # ── 保留判定：arm id 存在且实体列表完全不变才保留（否则重建该 arm）──
    kept: dict[str, dict] = {}
    removed: dict[str, dict] = {}
    for aid, member in old_arms.items():
        old_cfg = old_arm_params.get(aid, {})
        old_entities = _arm_entities(old_cfg) or [
            str(x) for x in (member.get("entities") or [])
        ]
        new_arm = new_by_id.get(aid)
        if new_arm is not None and old_entities == new_arm["entities"]:
            member = dict(member)
            if isinstance(member.get("get"), int):
                member["get"] = [member["get"]]
            member.setdefault("pack", [])
            member.setdefault("merge", [])
            member["entities"] = list(new_arm["entities"])
            kept[aid] = member
        else:
            removed[aid] = member

    # 外部指向组入口的连线（重展开后 remap）
    inbound = [(lid, int(ld.get("from_pin", -1)))
               for lid, ld in _graph(scene).get("links", {}).items()
               if int(ld.get("to_pin", -1)) == old_entry]

    # 删除旧决策链与已移除/已变化的 arm
    _delete_nodes(scene, list(group.get("chain_members") or []))
    for m in removed.values():
        _delete_nodes(scene, _member_node_ids(m))

    prefix = gid
    ops: list[dict] = _chain_ops(prefix, arms)
    try:
        old_addr = int(group.get("params", {}).get("addr", 16376))
    except (TypeError, ValueError):
        old_addr = 16376
    for arm in arms:
        if arm["id"] not in kept:
            ops += _arm_ops(prefix, arm, addr)
            continue
        ids = kept[arm["id"]]
        old_cfg = old_arm_params.get(arm["id"], {})
        try:
            old_code = int(old_cfg.get("code", 0))
        except (TypeError, ValueError):
            old_code = 0
        if old_code != arm["code"]:
            ops.append({"op": "set_props", "node": f"#{ids['code']}",
                        "props": {"value": arm["code"]}})
        if old_addr != addr:
            ops.append({"op": "set_props", "node": f"#{ids['send']}",
                        "props": {"address": addr}})

    # 链尾 True → arm 起点（保留 arm 用旧节点）
    for i, arm in enumerate(arms, start=1):
        if arm["id"] in kept:
            first_get = kept[arm["id"]]["get"][0]
            ops.append({"op": "link", "from": [f"{prefix}_br{i}", "True"],
                        "to": [f"#{first_get}", "exec_in"]})
        else:
            ops.append({"op": "link", "from": [f"{prefix}_br{i}", "True"],
                        "to": [f"{prefix}_{arm['id']}_get0", "exec_in"]})

    res = apply_ops(scene, ops)
    if not res["ok"]:
        return {"ok": False, "errors": res["errors"], "scene": scene,
                "symbols": {}}
    scene = res["scene"]
    symbols = res["symbols"]

    chain_ids = [symbols[f"{prefix}_rand"]]
    arm_members: dict[str, dict] = {}
    for i, arm in enumerate(arms, start=1):
        chain_ids += [symbols[f"{prefix}_k{i}"], symbols[f"{prefix}_cmp{i}"],
                      symbols[f"{prefix}_br{i}"]]
        if arm["id"] in kept:
            arm_members[arm["id"]] = kept[arm["id"]]
        else:
            sym = _arm_symbols(prefix, arm)
            arm_members[arm["id"]] = {
                "get": [symbols[n] for n in sym["get"]],
                "pack": [symbols[n] for n in sym["pack"]],
                "merge": [symbols[n] for n in sym["merge"]],
                "set": symbols[sym["set"]],
                "send": symbols[sym["send"]],
                "code": symbols[sym["code"]],
                "entities": list(arm["entities"]),
            }
    members = list(chain_ids)
    for m in arm_members.values():
        members.extend(_member_node_ids(m))

    first_br = _graph(scene)["nodes"][str(symbols[f"{prefix}_br1"])]
    new_entry = first_br["pin_ids"]["exec_in"]
    # 被 _delete_nodes 一并清掉的外部入口连线 → 重新接到新入口
    links = _graph(scene).setdefault("links", {})
    existing_targets = {int(ld.get("from_pin", -1))
                        for ld in links.values()
                        if int(ld.get("to_pin", -1)) == int(new_entry)}
    for _lid, from_pin in inbound:
        if from_pin in existing_targets:
            continue
        links[str(_next_link_id(scene))] = {"from_pin": from_pin,
                                            "to_pin": int(new_entry)}

    _layout(scene, members)
    alias = group.get("alias", "")
    if op.get("alias") is not None:
        from flyvibing_node_editor.ops import valid_alias
        new_alias = str(op.get("alias") or "")
        if new_alias and not valid_alias(new_alias):
            return {"ok": False, "errors": [f"invalid group alias {new_alias!r}"],
                    "scene": scene, "symbols": {}}
        for other_gid, other in _group_map(scene).items():
            if other_gid != gid and str(other.get("alias", "")).lower() == new_alias.lower() and new_alias:
                return {"ok": False,
                        "errors": [f"duplicate group alias {new_alias!r} ({other_gid})"],
                        "scene": scene, "symbols": {}}
        alias = new_alias
    new_group = {
        "type": group.get("type"),
        "version": int(group.get("version", 1)) + 1,
        "alias": alias,
        "params": {"addr": addr, "arms": arms},
        "members": members,
        "chain_members": chain_ids,
        "arm_members": arm_members,
        "slots": {"entry": new_entry, "done": None},
    }
    if group.get("parent"):
        new_group["parent"] = group["parent"]
    if group.get("children"):
        new_group["children"] = list(group["children"])
    _group_map(scene)[gid] = new_group
    if new_group.get("parent"):
        _refresh_parent_members(scene, gid)
    return {"ok": True, "errors": [], "scene": scene, "symbols": {}}

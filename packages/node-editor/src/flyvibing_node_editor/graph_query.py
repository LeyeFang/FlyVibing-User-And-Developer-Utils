"""组感知的节点图链路查询（graph-query/v1）。

目标: 让 agent 用少量 CLI 调用就能理解局部链路，而不是把整张 `.scene` 读进上下文。

- `query`: 从节点/组出发，按 exec/data 边查上下游；经过组时默认只报告组（黑盒），
  组带边界端口（entry/done、data_in/data_out），需要时用 `expand` 展开内部。
- `expand`: 展开一个组内部的链路；子组默认继续黑盒，`nested=expand` 时递归到节点。
- 输入既可以是 `.scene`，也可以是裸 graph JSON（`{"nodes":..., "links":...}`）。

输出 schema: `graph-query/v1`。节点用 alias 优先的 `ref` 寻址；组用 `@alias` / `gN`。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque

from flyvibing_node_editor.node_graph_validator import extract_graph_data

SCHEMA = "graph-query/v1"

_EXEC_NAMES = {"exec", "exec_in", "exec_out", "true", "false", "done", "entry"}
_OUT_RE = re.compile(r"^out_\d+$")

# 默认只回这些 props（省上下文）；--with-props 才回全量
_SUMMARY_PROPS = {
    "TimeTrigger": ("mode", "time", "timer"),
    "SetTimer": ("operate", "mode", "timer_name", "value"),
    "NewTimer": ("mode", "timer_name"),
    "VarSet": ("mode", "var_name", "value"),
    "VarGet": ("var_name",),
    "Constant": ("value",),
    "EntitySpawn": ("template",),
    "EntityGet": ("entity_name", "name"),
    "EntitySetRenderVisible": ("visible",),
    "Compare": ("operation",),
    "ScalarMath": ("operation",),
    "TimeGetElapsed": ("timer",),
    "ParallelSend": ("address", "value"),
    "SerialSend": ("port", "baud_rate", "format"),
    "PrintString": ("message",),
    "Print": (),
}


class GraphQueryError(ValueError):
    """查询/展开的用法或寻址错误（CLI 退出码 2）。"""


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short(text, limit=240):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _kind_from_pin_name(name: str) -> str:
    name = str(name or "")
    return "exec" if name.lower() in _EXEC_NAMES or _OUT_RE.match(name) else "data"


def _link_dicts(raw_links):
    """兼容 dict / list 两种 links 存储。"""
    out = []
    if isinstance(raw_links, dict):
        items = raw_links.items()
    elif isinstance(raw_links, list):
        items = enumerate(raw_links)
    else:
        return out
    for lid, link in items:
        if not isinstance(link, dict):
            continue
        out.append((lid, link))
    return out


class GraphIR:
    """规范化后的图索引；只读，不修改 scene。"""

    def __init__(self, data: dict):
        self.graph = extract_graph_data(data)
        if not isinstance(self.graph, dict) or "nodes" not in self.graph:
            raise GraphQueryError("no node graph found (expected .scene or {'nodes': ...})")
        self.nodes = {}
        for nid, nd in (self.graph.get("nodes") or {}).items():
            nid_i = _safe_int(nid)
            if nid_i is not None and isinstance(nd, dict):
                self.nodes[nid_i] = nd
        self.groups = {
            str(gid): g for gid, g in (self.graph.get("node_groups") or {}).items()
            if isinstance(g, dict)
        }
        self.types = self._load_types()
        self.node_pins: dict[int, dict[str, int]] = {}
        self.pin_owner: dict[int, tuple[int, str]] = {}
        self.pin_meta: dict[int, dict] = {}
        self._build_pins()
        self.edges = self._build_edges()
        self._build_group_membership()
        self._collapsed_cache = {}

    # ── 基础索引 ─────────────────────────────────────────

    @staticmethod
    def _load_types():
        try:
            from flyvibing_node_editor.engine_path import ensure_engine_importable
            ensure_engine_importable()
            from Application.Core.NodeGraph.node_types import _TYPES
            return _TYPES
        except Exception:  # noqa: BLE001 — 无引擎时按 pin 名推断 exec/data
            return {}

    def _build_pins(self):
        for nid, nd in self.nodes.items():
            pins = {}
            for name, pid in (nd.get("pin_ids") or {}).items():
                pid_i = _safe_int(pid)
                if pid_i is None:
                    continue
                pins[str(name)] = pid_i
                self.pin_owner[pid_i] = (nid, str(name))
                td = self.types.get(nd.get("node_type", ""))
                kind = direction = data_type = None
                if td is not None:
                    for pin in getattr(td, "pins", []) or []:
                        if pin.name == name:
                            kind = getattr(pin, "kind", None)
                            direction = getattr(pin, "direction", None)
                            data_type = getattr(pin, "data_type", None)
                            break
                self.pin_meta[pid_i] = {
                    "node": nid,
                    "name": str(name),
                    "kind": kind or _kind_from_pin_name(name),
                    "direction": direction or ("output" if name in ("exec", "exec_out") or _OUT_RE.match(name) else "input"),
                    "data_type": data_type,
                }
            self.node_pins[nid] = pins

    def _build_edges(self):
        edges = []
        for lid, link in _link_dicts(self.graph.get("links")):
            from_pin = _safe_int(link.get("from_pin"))
            to_pin = _safe_int(link.get("to_pin"))
            owner_from = self.pin_owner.get(from_pin)
            owner_to = self.pin_owner.get(to_pin)
            if owner_from is None or owner_to is None:
                continue
            from_meta = self.pin_meta.get(from_pin) or {}
            to_meta = self.pin_meta.get(to_pin) or {}
            kind = from_meta.get("kind") or to_meta.get("kind") or "data"
            edges.append({
                "id": _safe_int(lid),
                "from_node": owner_from[0],
                "from_pin": owner_from[1],
                "from_pin_id": from_pin,
                "to_node": owner_to[0],
                "to_pin": owner_to[1],
                "to_pin_id": to_pin,
                "kind": "exec" if kind == "exec" else "data",
            })
        return edges

    def _build_group_membership(self):
        self.group_direct: dict[str, set[int]] = {}
        for gid, grp in self.groups.items():
            direct = set()
            for raw in grp.get("members") or []:
                nid = _safe_int(raw)
                if nid is not None:
                    direct.add(nid)
            self.group_direct[gid] = direct
        self.group_all: dict[str, set[int]] = {}
        for gid in self.groups:
            self.group_all[gid] = set(self._group_node_ids(gid))
        self.node_group_map: dict[int, list[str]] = defaultdict(list)
        for gid, members in self.group_all.items():
            for nid in members:
                self.node_group_map[nid].append(gid)
        self.node_immediate: dict[int, str | None] = {}
        for nid, gids in self.node_group_map.items():
            # 最深的组 = 直接成员组
            self.node_immediate[nid] = max(gids, key=self.group_depth)
        self.node_top: dict[int, str | None] = {
            nid: self._root_group(gid) if gid else None
            for nid, gid in self.node_immediate.items()
        }

    def _group_node_ids(self, gid: str, seen=None) -> list[int]:
        seen = seen or set()
        if gid in seen:
            return []
        seen.add(gid)
        grp = self.groups.get(gid) or {}
        out = []
        for raw in grp.get("members") or []:
            nid = _safe_int(raw)
            if nid is not None and nid in self.nodes and nid not in out:
                out.append(nid)
        for child in self.group_children(gid):
            for nid in self._group_node_ids(child, seen):
                if nid not in out:
                    out.append(nid)
        return out

    # ── 组层级 / 寻址 ───────────────────────────────────

    def group_parent(self, gid: str) -> str | None:
        parent = (self.groups.get(gid) or {}).get("parent")
        parent = str(parent) if parent else None
        return parent if parent in self.groups else None

    def group_children(self, gid: str) -> list[str]:
        grp = self.groups.get(gid) or {}
        out = []
        for raw in grp.get("children") or []:
            child = str(raw)
            if child in self.groups and child != gid and child not in out:
                out.append(child)
        for child, g in self.groups.items():
            if child != gid and str(g.get("parent") or "") == gid and child not in out:
                out.append(child)
        return out

    def group_depth(self, gid: str) -> int:
        depth = 0
        cur = self.group_parent(gid)
        seen = {gid}
        while cur and cur not in seen:
            seen.add(cur)
            depth += 1
            cur = self.group_parent(cur)
        return depth

    def _root_group(self, gid: str) -> str:
        cur = gid
        seen = {gid}
        while True:
            parent = self.group_parent(cur)
            if not parent or parent in seen:
                return cur
            seen.add(parent)
            cur = parent

    def group_ref(self, gid: str) -> str:
        alias = str((self.groups.get(gid) or {}).get("alias") or "")
        return f"@{alias}" if alias else gid

    def group_path(self, gid: str) -> str:
        parts = []
        cur = gid
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            parts.append(self.group_ref(cur))
            cur = self.group_parent(cur)
        return "/".join(reversed(parts))

    def node_ref(self, nid: int) -> str:
        alias = str((self.nodes.get(nid) or {}).get("alias") or "")
        return f"@{alias}" if alias else f"#{nid}"

    def resolve(self, ref: str) -> tuple[str, int | str]:
        """→ ("node", id) / ("group", gid)。"""
        raw = str(ref or "").strip()
        if not raw:
            raise GraphQueryError("empty ref")
        if raw.startswith("#"):
            nid = _safe_int(raw[1:])
            if nid in self.nodes:
                return "node", nid
            raise GraphQueryError(f"node {raw!r} not found")
        if raw.isdigit():
            nid = int(raw)
            if nid in self.nodes:
                return "node", nid
            if raw in self.groups:
                return "group", raw
            raise GraphQueryError(f"id {raw!r} not found")
        name = raw[1:] if raw.startswith("@") else raw
        if name in self.groups:
            return "group", name
        node_hits = [nid for nid, nd in self.nodes.items()
                     if str(nd.get("alias") or "").lower() == name.lower()]
        group_hits = [gid for gid, g in self.groups.items()
                      if str(g.get("alias") or "").lower() == name.lower()]
        if len(node_hits) + len(group_hits) > 1:
            raise GraphQueryError(
                f"ambiguous ref {raw!r}: nodes={node_hits or '-'} groups={group_hits or '-'}"
            )
        if node_hits:
            return "node", node_hits[0]
        if group_hits:
            return "group", group_hits[0]
        raise GraphQueryError(f"ref {raw!r} not found (node alias, group alias, #id, gN)")

    # ── 组边界端口 ───────────────────────────────────────

    def group_ports(self, gid: str) -> dict:
        inside = self.group_all.get(gid) or set()
        ports: dict[tuple, dict] = {}
        for edge in self.edges:
            fin = edge["from_node"] in inside
            tin = edge["to_node"] in inside
            if fin == tin:
                continue
            if tin:  # inbound
                key = (edge["to_node"], edge["to_pin"], "in")
                port = ports.setdefault(key, {
                    "node": edge["to_node"], "pin": edge["to_pin"],
                    "kind": edge["kind"], "direction": "in",
                    "external": [], "edges": 0, "slot": None,
                })
                ext = {"kind": "node", "id": edge["from_node"],
                       "ref": self.node_ref(edge["from_node"]), "pin": edge["from_pin"]}
            else:  # outbound
                key = (edge["from_node"], edge["from_pin"], "out")
                port = ports.setdefault(key, {
                    "node": edge["from_node"], "pin": edge["from_pin"],
                    "kind": edge["kind"], "direction": "out",
                    "external": [], "edges": 0, "slot": None,
                })
                ext = {"kind": "node", "id": edge["to_node"],
                       "ref": self.node_ref(edge["to_node"]), "pin": edge["to_pin"]}
            port["edges"] += 1
            if len(port["external"]) < 4 and ext not in port["external"]:
                port["external"].append(ext)

        slots = (self.groups.get(gid) or {}).get("slots") or {}
        for slot_name in ("entry", "done"):
            pid = _safe_int(slots.get(slot_name))
            owner = self.pin_owner.get(pid) if pid is not None else None
            if not owner:
                continue
            wanted = "in" if slot_name == "entry" else "out"
            for key, port in ports.items():
                if key[0] == owner[0] and key[1] == owner[1] and key[2] == wanted:
                    port["slot"] = slot_name
        # 没有显式槽位时，唯一 exec 入口/出口就是事实上的 entry/done
        if not slots:
            exec_in = [p for p in ports.values() if p["kind"] == "exec" and p["direction"] == "in"]
            exec_out = [p for p in ports.values() if p["kind"] == "exec" and p["direction"] == "out"]
            if len(exec_in) == 1:
                exec_in[0]["slot"] = "entry"
            if len(exec_out) == 1:
                exec_out[0]["slot"] = "done"

        buckets = {"exec_in": [], "exec_out": [], "data_in": [], "data_out": []}
        for port in ports.values():
            bucket = f"{port['kind']}_{'in' if port['direction'] == 'in' else 'out'}"
            buckets.setdefault(bucket, []).append({
                "node": port["node"],
                "ref": self.node_ref(port["node"]),
                "pin": port["pin"],
                "edges": port["edges"],
                "slot": port["slot"],
                "external": port["external"],
            })
        return {k: v for k, v in buckets.items() if v}

    def group_item(self, gid: str, *, with_ports=True) -> dict:
        grp = self.groups.get(gid) or {}
        item = {
            "kind": "group",
            "id": gid,
            "ref": self.group_ref(gid),
            "alias": str(grp.get("alias") or ""),
            "type": str(grp.get("type") or "container"),
            "path": self.group_path(gid),
            "parent": self.group_parent(gid),
            "title": str(grp.get("title") or ""),
            "description": _short(grp.get("description") or ""),
            "params": grp.get("params") or {},
            "member_count": len(self.group_all.get(gid) or set()),
        }
        if with_ports:
            item["ports"] = self.group_ports(gid)
        return item

    def node_item(self, nid: int, *, with_props=False) -> dict:
        nd = self.nodes.get(nid) or {}
        props = nd.get("props") or {}
        if with_props:
            picked = dict(props)
        else:
            picked = {k: props[k] for k in _SUMMARY_PROPS.get(nd.get("node_type", ""), ())
                      if k in props}
        group = self.node_immediate.get(nid)
        return {
            "kind": "node",
            "id": nid,
            "ref": self.node_ref(nid),
            "type": nd.get("node_type", ""),
            "alias": str(nd.get("alias") or ""),
            "group": group,
            "group_path": self.group_path(group) if group else "",
            "description": _short(nd.get("description") or ""),
            "props": picked,
        }

    # ── 折叠视图 ─────────────────────────────────────────

    def container_for(self, nid: int, scope: str | None = None,
                      focus: str | None = None):
        """节点在指定 scope 下的容器：scope 的子组 or 节点自身。

        scope=None → 顶层组（或节点自身）。scope=gid → 展开该组时，
        直接成员算节点，孙辈归到 scope 的直接子组。
        focus=gid → 该组内部透明（节点级），组外仍按顶层组折叠。
        """
        if focus and nid in (self.group_all.get(focus) or set()):
            return ("node", nid)
        if scope is None:
            top = self.node_top.get(nid)
            return ("group", top) if top else ("node", nid)
        group = self.node_immediate.get(nid)
        if not group or group == scope:
            return ("node", nid)
        cur = group
        seen = {cur}
        while True:
            parent = self.group_parent(cur)
            if not parent or parent in seen:
                return ("group", cur)
            if parent == scope:
                return ("group", cur)
            seen.add(parent)
            cur = parent

    def _container_ref(self, container) -> dict:
        kind, ident = container
        if kind == "group":
            return {"kind": "group", "id": ident, "ref": self.group_ref(ident)}
        return {"kind": "node", "id": ident, "ref": self.node_ref(ident)}

    def collapsed_edges(self, scope: str | None = None, focus: str | None = None):
        key = (scope if scope is not None else "__top__", focus or "")
        if key in self._collapsed_cache:
            return self._collapsed_cache[key]
        out = []
        for edge in self.edges:
            a = self.container_for(edge["from_node"], scope, focus)
            b = self.container_for(edge["to_node"], scope, focus)
            if a == b:
                continue
            from_ep = dict(self._container_ref(a))
            to_ep = dict(self._container_ref(b))
            if a[0] == "group":
                from_ep.update({"port": edge["from_pin"], "via_node": self.node_ref(edge["from_node"])})
            else:
                from_ep["pin"] = edge["from_pin"]
            if b[0] == "group":
                to_ep.update({"port": edge["to_pin"], "via_node": self.node_ref(edge["to_node"])})
            else:
                to_ep["pin"] = edge["to_pin"]
            out.append({
                "kind": edge["kind"],
                "from_container": a,
                "to_container": b,
                "from": from_ep,
                "to": to_ep,
                "edge": edge,
            })
        self._collapsed_cache[key] = out
        return out

    # ── 查询 / 展开 ──────────────────────────────────────

    def query(self, start: str, *, direction="down", depth=3, groups="auto",
              edges="all", data_direction="inputs", max_nodes=80,
              with_props=False) -> dict:
        if groups not in ("auto", "opaque", "expand"):
            raise GraphQueryError("groups must be 'auto', 'opaque' or 'expand'")
        if edges not in ("exec", "data", "all"):
            raise GraphQueryError("edges must be 'exec', 'data' or 'all'")
        if direction not in ("down", "up", "both"):
            raise GraphQueryError("direction must be 'down', 'up' or 'both'")
        if data_direction not in ("inputs", "outputs", "both"):
            raise GraphQueryError("data-direction must be 'inputs', 'outputs' or 'both'")
        kind, ident = self.resolve(start)
        start_node = None
        focus = None
        if kind == "group":
            if groups == "expand":
                raise GraphQueryError(
                    "query --groups expand 需要从节点出发；要展开组请用 expand --group"
                )
            scope = self.group_parent(ident)
            root_container = ("group", ident)
        else:
            scope = None
            if groups == "expand":
                root_container = ("node", ident)
            elif groups == "auto" and self.node_top.get(ident):
                # 节点视角：起点所在的组透明，其余组黑盒
                focus = self.node_top.get(ident)
                root_container = ("node", ident)
            else:
                root_container = self.container_for(ident, scope)
                start_node = ident if root_container[0] == "group" else None
        return self._traverse(
            root_container, direction=direction, depth=max(0, int(depth)),
            groups=groups, edges=edges, data_direction=data_direction,
            max_nodes=max(1, int(max_nodes)),
            scope=scope, focus=focus, start_node=start_node, with_props=with_props,
        )

    def _edge_allowed(self, edge, edges_mode):
        if edges_mode == "all":
            return True
        return edge["kind"] == edges_mode

    def _traverse(self, root_container, *, direction, depth, groups, edges,
                  data_direction, max_nodes, scope, focus=None,
                  start_node, with_props) -> dict:
        adjacency = defaultdict(list)
        hop_seen = set()

        def add_hop(src, dst, item):
            key = (src, dst, item["kind"],
                   item["from"].get("port") or item["from"].get("pin"),
                   item["to"].get("port") or item["to"].get("pin"))
            if key in hop_seen:
                return
            hop_seen.add(key)
            adjacency[src].append((dst, item))

        def add_edge_hops(a, b, item):
            if item["kind"] == "exec":
                if direction in ("down", "both"):
                    add_hop(a, b, item)
                if direction in ("up", "both"):
                    add_hop(b, a, item)
                return
            # 数据边 = 依赖边：默认只沿“消费者 → 生产者”回溯输入
            if data_direction in ("inputs", "both"):
                add_hop(b, a, item)
            if data_direction in ("outputs", "both"):
                add_hop(a, b, item)

        if groups in ("opaque", "auto"):
            edge_items = self.collapsed_edges(scope, focus)
            for item in edge_items:
                if not self._edge_allowed(item["edge"], edges):
                    continue
                add_edge_hops(item["from_container"], item["to_container"], item)
        else:
            edge_items = []
            for edge in self.edges:
                if not self._edge_allowed(edge, edges):
                    continue
                a = ("node", edge["from_node"])
                b = ("node", edge["to_node"])
                item = {"kind": edge["kind"], "from_container": a, "to_container": b,
                        "from": {**self._container_ref(a), "pin": edge["from_pin"]},
                        "to": {**self._container_ref(b), "pin": edge["to_pin"]},
                        "edge": edge}
                edge_items.append(item)
                add_edge_hops(a, b, item)

        visited = {root_container: 0}
        queue = deque([(root_container, 0)])
        truncated = False
        while queue:
            container, dist = queue.popleft()
            if dist >= depth:
                continue
            for nxt, item in adjacency.get(container, []):
                if nxt not in visited:
                    if len(visited) >= max_nodes:
                        truncated = True
                        continue
                    visited[nxt] = dist + 1
                    queue.append((nxt, dist + 1))

        node_items, group_items = [], []
        for container in visited:
            if container[0] == "group":
                group_items.append(self.group_item(container[1], with_ports=True))
            elif groups == "expand":
                node_items.append(self.node_item(container[1], with_props=with_props))
            else:
                node_items.append(self.node_item(container[1], with_props=with_props))

        out_edges = []
        seen_edges = set()
        for item in edge_items:
            if item["from_container"] not in visited or item["to_container"] not in visited:
                continue
            if direction == "down" and item["from_container"] == root_container and \
                    item["to_container"] not in visited:
                continue
            key = (item["from_container"], item["to_container"], item["kind"],
                   item["from"].get("port") or item["from"].get("pin"),
                   item["to"].get("port") or item["to"].get("pin"))
            if key in seen_edges:
                continue
            seen_edges.add(key)
            out_edges.append({
                "kind": item["kind"],
                "from": item["from"],
                "to": item["to"],
            })

        root = self._container_ref(root_container)
        root.update({"path": self.group_path(root_container[1]) if root_container[0] == "group" else ""})
        if focus:
            group_items = [g for g in group_items if g["id"] != focus]
        result = {
            "schema": SCHEMA,
            "mode": "query",
            "graph_hash": self.graph_hash(),
            "root": root,
            "direction": direction,
            "groups_mode": groups,
            "focus_group": self.group_item(focus, with_ports=True) if focus else None,
            "edges_mode": edges,
            "data_direction": data_direction,
            "depth": depth,
            "start_node": self.node_item(start_node, with_props=with_props) if start_node is not None else None,
            "groups_list": sorted(group_items, key=lambda x: (x["path"], x["id"])),
            "nodes": sorted(node_items, key=lambda x: x["id"]),
            "edges": out_edges,
            "truncated": truncated,
            "stats": {
                "containers": len(visited),
                "nodes": len(node_items),
                "groups": len(group_items),
                "edges": len(out_edges),
                "max_nodes": max_nodes,
            },
        }
        return result

    def expand(self, group: str, *, nested="opaque", edges="all",
               max_nodes=80, with_props=False) -> dict:
        if nested not in ("opaque", "expand"):
            raise GraphQueryError("nested must be 'opaque' or 'expand'")
        if edges not in ("exec", "data", "all"):
            raise GraphQueryError("edges must be 'exec', 'data' or 'all'")
        kind, gid = self.resolve(group)
        if kind != "group":
            raise GraphQueryError(f"{group!r} is a node, not a group")
        inside = self.group_all.get(gid) or set()
        if nested == "opaque":
            containers = {}
            for nid in inside:
                containers[nid] = self.container_for(nid, gid)
            item_edges = []
            for item in self.collapsed_edges(gid):
                if self._edge_allowed(item["edge"], edges):
                    item_edges.append(item)
        else:
            containers = {nid: ("node", nid) for nid in inside}
            item_edges = []
            for edge in self.edges:
                if not self._edge_allowed(edge, edges):
                    continue
                if edge["from_node"] in inside and edge["to_node"] in inside:
                    item_edges.append({
                        "kind": edge["kind"],
                        "from_container": ("node", edge["from_node"]),
                        "to_container": ("node", edge["to_node"]),
                        "from": {**self._container_ref(("node", edge["from_node"])),
                                 "pin": edge["from_pin"]},
                        "to": {**self._container_ref(("node", edge["to_node"])),
                               "pin": edge["to_pin"]},
                        "edge": edge,
                    })
        # 只保留展开框内部的容器
        allowed = set(containers.values())
        node_items, group_items = [], []
        for container in allowed:
            if container[0] == "group":
                group_items.append(self.group_item(container[1], with_ports=True))
            else:
                node_items.append(self.node_item(container[1], with_props=with_props))
        if len(node_items) > max_nodes:
            node_items = sorted(node_items, key=lambda x: x["id"])[:max_nodes]
            node_ids = {n["id"] for n in node_items}
            item_edges = [e for e in item_edges
                          if e["from_container"][1] in node_ids and e["to_container"][1] in node_ids]
            truncated = True
        else:
            node_items.sort(key=lambda x: x["id"])
            truncated = False
        out_edges = []
        seen = set()
        for item in item_edges:
            if item["from_container"] not in allowed or item["to_container"] not in allowed:
                continue
            key = (item["from_container"], item["to_container"], item["kind"],
                   item["from"].get("port") or item["from"].get("pin"),
                   item["to"].get("port") or item["to"].get("pin"))
            if key in seen:
                continue
            seen.add(key)
            out_edges.append({"kind": item["kind"], "from": item["from"], "to": item["to"]})

        # 边界边（组内外各一端），用于理解组如何接入父图
        boundary = []
        for edge in self.edges:
            if not self._edge_allowed(edge, edges):
                continue
            fin = edge["from_node"] in inside
            tin = edge["to_node"] in inside
            if fin == tin:
                continue
            boundary.append({
                "kind": edge["kind"],
                "from": {"kind": "node", "id": edge["from_node"],
                         "ref": self.node_ref(edge["from_node"]), "pin": edge["from_pin"],
                         "inside": fin},
                "to": {"kind": "node", "id": edge["to_node"],
                       "ref": self.node_ref(edge["to_node"]), "pin": edge["to_pin"],
                       "inside": tin},
            })
        result = {
            "schema": SCHEMA,
            "mode": "expand",
            "graph_hash": self.graph_hash(),
            "group": self.group_item(gid, with_ports=True),
            "nested": nested,
            "edges_mode": edges,
            "groups_list": sorted(group_items, key=lambda x: (x["path"], x["id"])),
            "nodes": node_items,
            "edges": out_edges,
            "boundary": boundary,
            "truncated": truncated,
            "stats": {
                "nodes": len(node_items),
                "groups": len(group_items),
                "edges": len(out_edges),
                "boundary": len(boundary),
                "max_nodes": max_nodes,
            },
        }
        return result

    def graph_hash(self) -> str:
        payload = {
            "nodes": [
                {"id": nid, "type": nd.get("node_type"), "alias": nd.get("alias"),
                 "pos": nd.get("pos"), "description": nd.get("description"),
                 "props": nd.get("props"), "pin_ids": nd.get("pin_ids")}
                for nid, nd in sorted(self.nodes.items())
            ],
            "links": sorted(
                ({"from": e["from_pin_id"], "to": e["to_pin_id"]} for e in self.edges),
                key=lambda x: (x["from"], x["to"]),
            ),
            "groups": [
                {"id": gid, "alias": g.get("alias"), "type": g.get("type"),
                 "title": g.get("title"), "description": g.get("description"),
                 "members": g.get("members"), "children": g.get("children"),
                 "slots": g.get("slots"), "params": g.get("params")}
                for gid, g in sorted(self.groups.items())
            ],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ── 文本渲染（省 token 的次要格式）──────────────────────────


def _ports_line(label: str, ports: list, limit=8) -> str:
    if not ports:
        return ""
    parts = []
    for port in ports[:limit]:
        text = f"{port['ref']}.{port['pin']}"
        if port.get("slot"):
            text += f"[{port['slot']}]"
        parts.append(text)
    suffix = " ..." if len(ports) > limit else ""
    return f"  {label}: " + ", ".join(parts) + suffix


def render_query_text(result: dict) -> str:
    lines = []
    root = result["root"]
    lines.append(f"{root['ref']} [{root['kind']}]")
    if result.get("focus_group"):
        g = result["focus_group"]
        lines.append(f"focus: {g['ref']} [{g['type']}] {g['description']}".rstrip())
    for g in result["groups_list"]:
        lines.append(f"group {g['ref']} [{g['type']}] {g['description']}".rstrip())
        for bucket in ("exec_in", "exec_out", "data_in", "data_out"):
            line = _ports_line(bucket, g.get("ports", {}).get(bucket) or [])
            if line:
                lines.append(line)
    for n in result["nodes"]:
        props = " ".join(f"{k}={v}" for k, v in (n.get("props") or {}).items())
        lines.append(f"node {n['ref']} [{n['type']}] {props}".rstrip())
    if result["start_node"]:
        n = result["start_node"]
        lines.append(f"start node: {n['ref']} [{n['type']}] {n['description']}".rstrip())
    lines.append("edges:")
    for edge in result["edges"]:
        a = edge["from"]
        b = edge["to"]
        pin_a = a.get("port") or a.get("pin") or ""
        pin_b = b.get("port") or b.get("pin") or ""
        arrow = "--exec-->" if edge["kind"] == "exec" else "--data-->"
        lines.append(f"  {a['ref']}.{pin_a} {arrow} {b['ref']}.{pin_b}")
    if result["truncated"]:
        lines.append("... TRUNCATED")
    return "\n".join(lines)


def render_expand_text(result: dict) -> str:
    g = result["group"]
    lines = [f"{g['ref']} [{g['type']}] {g['description']}".rstrip()]
    for bucket in ("exec_in", "exec_out", "data_in", "data_out"):
        line = _ports_line(bucket, g.get("ports", {}).get(bucket) or [])
        if line:
            lines.append(line)
    for child in result["groups_list"]:
        lines.append(f"child group {child['ref']} [{child['type']}] {child['description']}".rstrip())
    for n in result["nodes"]:
        props = " ".join(f"{k}={v}" for k, v in (n.get("props") or {}).items())
        lines.append(f"node {n['ref']} [{n['type']}] {props}".rstrip())
    lines.append("edges:")
    for edge in result["edges"]:
        a, b = edge["from"], edge["to"]
        pin_a = a.get("port") or a.get("pin") or ""
        pin_b = b.get("port") or b.get("pin") or ""
        arrow = "--exec-->" if edge["kind"] == "exec" else "--data-->"
        lines.append(f"  {a['ref']}.{pin_a} {arrow} {b['ref']}.{pin_b}")
    for edge in result["boundary"][:20]:
        a, b = edge["from"], edge["to"]
        lines.append(f"  boundary: {a['ref']}.{a['pin']} -> {b['ref']}.{b['pin']}")
    if result["truncated"]:
        lines.append("... TRUNCATED")
    return "\n".join(lines)

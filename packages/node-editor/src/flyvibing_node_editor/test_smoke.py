"""
GraphBuilder 冒烟测试 — 验证 API 可用性。

用法: python packages/node-editor/test_smoke.py
"""

import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flyvibing_node_editor.graph_builder import GraphBuilder

g = GraphBuilder()

# 基础节点
a = g.node("Constant", ["Result"], {"value": 42})
b = g.node("Print", ["exec_in", "exec_out", "Value"])
g.link(a, "Result", b, "Value")
print(f"  node: {a=}, {b=}, link OK")

# event nodes
GS, FU, GP = g.event_nodes()
print(f"  events: GS={GS}, FU={FU}, GP={GP}")

# chain
c = g.node("VarSet", ["exec_in", "exec_out", "Name", "Value"],
           {"mode": "manual", "var_name": "x", "value": 1})
g.chain(b, c)
print("  chain: OK")

# validate
r = g.validate(max_frames=0)
assert r.passed, f"Static failed: {r.static_errors}"
print(f"  validate: PASSED (static)")

# build
d = g.build()
assert len(d["nodes"]) >= 6, f"Expected >=6 nodes, got {len(d['nodes'])}"
assert len(d["links"]) >= 2, f"Expected >=2 links, got {len(d['links'])}"
print(f"  build: {len(d['nodes'])} nodes, {len(d['links'])} links")

# entity_list helpers (tree / pack+merge / list visible / list destroy)
g2 = GraphBuilder()
tree = g2.entity_get_tree("CueRoot")
tree_entry, tree_node = g2.entity_get_tree("CueRoot", with_entry=True)
packed = g2.entity_pack("A", "B", "C", "D", "E")
lv = g2.entity_list_set_visible((packed, "Entities"), 0.0)
ld = g2.entity_list_destroy((tree, "Entities"))
g2.annotate(tree_node, "cue_tree", "Fixation cross tree.")
node_data = g2.build()["nodes"][str(tree_node)]
assert node_data.get("alias") == "cue_tree"
assert node_data.get("description") == "Fixation cross tree."
types = [n["node_type"] for n in g2.build()["nodes"].values()]
assert types.count("EntityGet") == 7, types
assert types.count("EntityGetTree") == 2, types
assert types.count("EntityPack") == 2, types
assert types.count("EntityListMerge") == 1, types
assert types.count("EntityListSetVisible") == 1, types
assert types.count("EntityListDestroy") == 1, types
assert len(g2.build()["nodes"]) == 15, types
assert len(g2.build()["links"]) == 12
print("  entity_list helpers: 15 nodes, 12 links")

print("\n[OK] All GraphBuilder smoke tests passed")

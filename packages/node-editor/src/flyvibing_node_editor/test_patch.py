"""graph patch / link / unlink 自测。

用法:
    .venv-py314t\\Scripts\\python.exe packages/node-editor/src/flyvibing_node_editor/test_patch.py
"""

from __future__ import annotations

import json
import os
import sys

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _engine_root() -> str:
    env = os.environ.get("MGE_ROOT") or os.environ.get("FLYVIBING_ENGINE_ROOT")
    if env and os.path.isdir(os.path.join(env, "Application", "Core", "NodeGraph")):
        return env
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur:
        if os.path.isdir(os.path.join(cur, "Application", "Core", "NodeGraph")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


_ROOT = _engine_root()
if _ROOT and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flyvibing_node_editor.graph_builder import GraphBuilder       # noqa: E402
from flyvibing_node_editor.graph_patch import apply_patch         # noqa: E402
from flyvibing_node_editor.node_groups import merge_group         # noqa: E402


def _scene():
    g = GraphBuilder()
    gs, fu, _gp = g.event_nodes()
    seq = g.node("Sequence", ["exec_in", "out_0", "out_1", "out_2", "out_3", "out_4"])
    tt = g.node("TimeTrigger",
                ["exec_in", "Time", "Elapsed"] + [f"out_{i}" for i in range(8)],
                {"mode": "manual", "time": 0, "timer": "phase"})
    set1 = g.node("VarSet", ["exec_in", "Name", "Value", "exec_out"],
                  {"mode": "manual", "var_name": "a", "value": 0})
    set2 = g.node("VarSet", ["exec_in", "Name", "Value", "exec_out"],
                  {"mode": "manual", "var_name": "b", "value": 1})
    const = g.node("Constant", ["Result"], {"value": 1.0})
    g.link(fu, "exec", seq, "exec_in")
    g.link(seq, "out_0", tt, "exec_in")
    g.link(tt, "out_0", set1, "exec_in")
    g.link(set1, "exec_out", set2, "exec_in")
    g.link(const, "Result", set1, "Value")
    for nid, alias in ((tt, "tt"), (set1, "set1"), (set2, "set2"), (const, "one")):
        g.annotate(nid, alias)
    scene = {"scene": {"node_graph": g.build()}}
    res = merge_group(scene, {"nodes": [set1, set2], "alias": "trial",
                              "title": "Trial", "description": "Fixture group."})
    check("merge_group fixture", res["ok"], str(res.get("errors")))
    return res["scene"]


def test_add_and_meta():
    print("-- add_node pos / set_pos / group metadata --")
    scene = _scene()
    ops = [
        {"op": "add_node", "type": "Constant", "props": {"value": 42},
         "as": "probe", "alias": "probe", "pos": [100, 200]},
        {"op": "set_pos", "node": "@probe", "pos": [300, 400]},
        {"op": "set_group_meta", "group": "@trial", "title": "Trial (patched)",
         "description": "Patched.", "params": {"note": "x"}},
    ]
    r = apply_patch(scene, ops)
    check("patch ok", r["ok"], str(r["errors"]))
    check("stage done", r["stage"] == "done")
    node = [n for n in r["scene"]["scene"]["node_graph"]["nodes"].values()
            if n.get("alias") == "probe"][0]
    check("add_node pos then set_pos", node["pos"] == [300.0, 400.0], str(node["pos"]))
    group = r["scene"]["scene"]["node_graph"]["node_groups"]["g1"]
    check("group title", group.get("title") == "Trial (patched)", str(group.get("title")))
    check("group param merged", (group.get("params") or {}).get("note") == "x")
    counts = r["diff"]["counts"]
    check("diff node added", counts["nodes"]["added"] == 1, json.dumps(counts))
    check("diff group changed", counts["groups"]["changed"] == 1, json.dumps(counts))


def test_link_unlink():
    print("-- link / unlink diff --")
    scene = _scene()
    r = apply_patch(scene, [{"op": "link", "from": ["one", "Result"],
                             "to": ["tt", "Time"]}])
    check("link ok", r["ok"], str(r["errors"]))
    check("link diff added", r["diff"]["counts"]["links"]["added"] == 1,
          json.dumps(r["diff"]["counts"]))
    r2 = apply_patch(r["scene"], [{"op": "unlink", "from": ["one", "Result"],
                                    "to": ["tt", "Time"]}])
    check("unlink ok", r2["ok"], str(r2["errors"]))
    check("unlink diff removed", r2["diff"]["counts"]["links"]["removed"] == 1,
          json.dumps(r2["diff"]["counts"]))


def test_hash():
    print("-- expected_hash --")
    scene = _scene()
    r = apply_patch(scene, [{"op": "set_pos", "node": "@tt", "pos": [1, 2]}])
    check("first patch ok", r["ok"], str(r["errors"]))
    bad = apply_patch(scene, [{"op": "set_pos", "node": "@tt", "pos": [3, 4]}],
                      expect_hash="sha1:deadbeef")
    check("hash mismatch rejected", not bad["ok"] and bad["stage"] == "hash",
          str(bad.get("stage")))
    ok = apply_patch(r["scene"], [{"op": "set_pos", "node": "@tt", "pos": [3, 4]}],
                     expect_hash=r["hash_after"])
    check("hash chain accepted", ok["ok"], str(ok["errors"]))
    check("hash changes", r["hash_after"] != r["hash_before"])


def test_errors_transactional():
    print("-- op errors / validation --")
    scene = _scene()
    before = json.dumps(scene, sort_keys=True)
    r = apply_patch(scene, [{"op": "link", "from": ["tt", "NoPin"],
                             "to": ["set1", "exec_in"]}])
    check("bad pin rejected", not r["ok"] and r["stage"] == "ops", str(r.get("stage")))
    check("input scene untouched", json.dumps(scene, sort_keys=True) == before)
    bad_kind = apply_patch(scene, [{"op": "link", "from": ["one", "Result"],
                                    "to": ["tt", "exec_in"]}])
    check("L1 validation blocks write", not bad_kind["ok"] and bad_kind["stage"] == "validation",
          str(bad_kind.get("stage")))
    # 补丁对象内部可能部分修改，但 ok=False 时调用方不会写盘
    check("no write on error", r.get("written") is None and not r["ok"])


def main() -> int:
    test_add_and_meta()
    test_link_unlink()
    test_hash()
    test_errors_transactional()
    print(f"\nSUMMARY: {_RESULTS['pass']} pass / {_RESULTS['fail']} fail")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

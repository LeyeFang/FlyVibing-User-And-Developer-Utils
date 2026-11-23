"""graph query / expand 自测。

用法:
    .venv-py314t\\Scripts\\python.exe packages/node-editor/src/flyvibing_node_editor/test_query.py
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

from flyvibing_node_editor.graph_builder import GraphBuilder          # noqa: E402
from flyvibing_node_editor.graph_query import GraphIR, GraphQueryError  # noqa: E402
from flyvibing_node_editor.node_groups import merge_group              # noqa: E402


def _scene():
    g = GraphBuilder()
    gs, fu, _gp = g.event_nodes()
    seq = g.node("Sequence", ["exec_in", "out_0", "out_1", "out_2", "out_3", "out_4"])
    tt = g.node("TimeTrigger", ["exec_in", "Time", "Elapsed", "out_0"],
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
    g.annotate(gs, "start")
    g.annotate(fu, "frame")
    g.annotate(seq, "seq")
    g.annotate(tt, "tt")
    g.annotate(set1, "set1")
    g.annotate(set2, "set2")
    g.annotate(const, "one")
    scene = {"scene": {"node_graph": g.build()}}
    res = merge_group(scene, {"nodes": [set1, set2], "alias": "trial_start",
                              "description": "test group"})
    check("merge_group for fixture", res["ok"], str(res.get("errors")))
    return res["scene"]


def test_opaque():
    print("-- query: groups opaque --")
    ir = GraphIR(_scene())
    r = ir.query("@seq", direction="down", depth=2, groups="opaque", edges="exec")
    refs = {g["ref"] for g in r["groups_list"]}
    node_refs = {n["ref"] for n in r["nodes"]}
    check("group reported", "@trial_start" in refs, str(refs))
    check("group members hidden", "set1" not in node_refs and "set2" not in node_refs, str(node_refs))
    check("entry port inferred", any(p.get("slot") == "entry"
                                     for p in r["groups_list"][0]["ports"].get("exec_in", [])))
    edge = [e for e in r["edges"] if e["to"]["ref"] == "@trial_start"]
    check("crossing edge uses group port", bool(edge) and edge[0]["to"]["port"] == "exec_in",
          json.dumps(edge, ensure_ascii=False))


def test_auto_focus():
    print("-- query: groups auto (start node in group) --")
    ir = GraphIR(_scene())
    r = ir.query("@set1", direction="down", depth=1, groups="auto", edges="all")
    refs = {n["ref"] for n in r["nodes"]}
    check("focus group transparent", {"@set1", "@set2"} <= refs, str(refs))
    check("focus group excluded from groups_list",
          all(g["ref"] != "@trial_start" for g in r["groups_list"]))
    check("focus_group returned", r["focus_group"]["ref"] == "@trial_start")
    check("internal edge visible", any(e["from"]["ref"] == "@set1" and e["to"]["ref"] == "@set2"
                                       for e in r["edges"]))


def test_expand():
    print("-- expand --")
    ir = GraphIR(_scene())
    r = ir.expand("@trial_start", nested="opaque", edges="all")
    refs = {n["ref"] for n in r["nodes"]}
    check("members returned", {"@set1", "@set2"} <= refs, str(refs))
    check("internal edge", any(e["from"]["ref"] == "@set1" and e["to"]["ref"] == "@set2"
                               for e in r["edges"]))
    check("boundary edge", any(b["from"]["ref"] == "@tt" and b["to"]["ref"] == "@set1"
                               for b in r["boundary"]))
    entry = (r["group"]["ports"].get("exec_in") or [{}])[0]
    check("group ports", entry.get("slot") == "entry", json.dumps(entry, ensure_ascii=False))


def test_filters_and_raw_graph():
    print("-- filters / raw graph / truncation --")
    scene = _scene()
    ir = GraphIR(scene["scene"]["node_graph"])
    r = ir.query("@set1", direction="up", depth=1, groups="auto", edges="data")
    refs = {n["ref"] for n in r["nodes"]}
    check("data-only upstream", "@one" in refs and "@tt" not in refs, str(refs))
    r = ir.query("@one", direction="down", depth=1, groups="expand", edges="data",
                 data_direction="outputs")
    refs = {n["ref"] for n in r["nodes"]}
    check("data outputs find consumer", "@set1" in refs, str(refs))
    r = ir.query("@seq", direction="down", depth=3, groups="opaque", max_nodes=2)
    check("truncated flag", r["truncated"] is True)
    try:
        ir.resolve("@missing")
        check("missing ref rejected", False)
    except GraphQueryError:
        check("missing ref rejected", True)


def main() -> int:
    test_opaque()
    test_auto_focus()
    test_expand()
    test_filters_and_raw_graph()
    print(f"\nSUMMARY: {_RESULTS['pass']} pass / {_RESULTS['fail']} fail")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

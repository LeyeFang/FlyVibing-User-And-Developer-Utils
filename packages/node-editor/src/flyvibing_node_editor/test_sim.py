"""graph simulate / probe 自测。

用法:
    .venv-py314t\\Scripts\\python.exe packages/node-editor/src/flyvibing_node_editor/test_sim.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

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

from flyvibing_node_editor.graph_builder import GraphBuilder      # noqa: E402
from flyvibing_node_editor.graph_sim import simulate             # noqa: E402
from flyvibing_node_editor.node_groups import merge_group        # noqa: E402


def _counter_scene(entities=None):
    g = GraphBuilder()
    gs, fu, _gp = g.event_nodes()
    init = g.node("VarSet", ["exec_in", "Name", "Value", "exec_out"],
                  {"mode": "manual", "var_name": "a", "value": 0})
    read = g.node("VarGet", ["exec_in", "Name", "exec_out", "Value"],
                  {"var_name": "a"})
    one = g.node("Constant", ["Result"], {"value": 1.0})
    add = g.node("ScalarMath", ["In_0", "In_1", "In_2", "In_3", "In_4", "In_5",
                                "In_6", "In_7", "Result"], {"operation": "sum"})
    inc = g.node("VarSet", ["exec_in", "Name", "Value", "exec_out"],
                 {"mode": "pin", "var_name": "a"})
    g.link(gs, "exec", init, "exec_in")
    g.link(fu, "exec", inc, "exec_in")
    g.link(read, "Value", add, "In_0")
    g.link(one, "Result", add, "In_1")
    g.link(add, "Result", inc, "Value")
    for nid, alias in ((gs, "start"), (fu, "frame"), (init, "init"),
                       (read, "read"), (one, "one"), (add, "add"), (inc, "inc")):
        g.annotate(nid, alias)
    scene = {"scene": {"node_graph": g.build(),
                       "entities": entities or {}}}
    return scene, inc, read, one


def test_counter():
    print("-- variable counter --")
    scene, _inc, _read, _one = _counter_scene()
    r = simulate(scene, frames=10, fps=100, watch_vars=["a"])
    check("simulate ok", r["ok"], str(r["errors"]))
    check("10 frames", r["timebase"]["frames"] == 10, json.dumps(r["timebase"]))
    var = [s for s in r["signals"]["vars"] if s["name"] == "a"]
    check("var signal", bool(var), json.dumps(r["signals"], ensure_ascii=False))
    check("last value 10", var and var[0].get("last_value") == 10.0,
          json.dumps(var, ensure_ascii=False)[:200])
    check("transitions 10", var and var[0].get("transitions") == 10,
          json.dumps(var, ensure_ascii=False)[:200])
    r2 = simulate(scene, frames=1, fps=100, watch_vars=["a"], set_vars={"a": 10})
    var2 = [s for s in r2["signals"]["vars"] if s["name"] == "a"]
    check("set_vars override", var2 and var2[0].get("last_value") == 11.0,
          json.dumps(var2, ensure_ascii=False)[:200])


def test_group_scope():
    print("-- group scope --")
    scene, inc, read, one = _counter_scene()
    res = merge_group(scene, {"nodes": [inc, read, one], "alias": "inc_group"})
    check("merge fixture", res["ok"], str(res.get("errors")))
    scene = res["scene"]
    r = simulate(scene, frames=5, fps=100, group="@inc_group", watch_vars=["a"])
    check("scope group", (r.get("scope") or {}).get("kind") == "group",
          json.dumps(r.get("scope"), ensure_ascii=False)[:200])
    var = [s for s in r["signals"]["vars"] if s["name"] == "a"]
    check("whole graph executes", var and var[0].get("last_value") == 5.0,
          json.dumps(var, ensure_ascii=False)[:200])


def test_visibility_and_trace():
    print("-- visibility / trace out / low fps warning --")
    g = GraphBuilder()
    gs, fu, _gp = g.event_nodes()
    get0 = g.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                  {"entity_name": "Cue"})
    hide = g.node("EntitySetRenderVisible", ["exec_in", "EntityID", "Visible", "exec_out"])
    zero = g.node("Constant", ["Result"], {"value": 0.0})
    get1 = g.node("EntityGet", ["exec_in", "exec_out", "Name", "Entity"],
                  {"entity_name": "Cue"})
    show = g.node("EntitySetRenderVisible", ["exec_in", "EntityID", "Visible", "exec_out"])
    one = g.node("Constant", ["Result"], {"value": 1.0})
    g.link(gs, "exec", get0, "exec_in")
    g.chain(get0, hide)
    g.link(zero, "Result", hide, "Visible")
    g.link(get0, "Entity", hide, "EntityID")
    g.link(fu, "exec", get1, "exec_in")
    g.chain(get1, show)
    g.link(one, "Result", show, "Visible")
    g.link(get1, "Entity", show, "EntityID")
    for nid, alias in ((get0, "get0"), (hide, "hide"), (zero, "zero"),
                       (get1, "get1"), (show, "show"), (one, "one")):
        g.annotate(nid, alias)
    scene = {"scene": {
        "node_graph": g.build(),
        "entities": {"1": {"name": "Cue", "components": {
            "MeshRenderer": {"visible": True}}}},
    }}
    r = simulate(scene, frames=2, fps=100)
    vis = [s for s in r["signals"]["visible"] if s["name"] == "Cue"]
    check("visible signal", bool(vis), json.dumps(r["signals"]["visible"], ensure_ascii=False))
    check("visibility transition", vis and vis[0]["transitions"] >= 1,
          json.dumps(vis, ensure_ascii=False)[:200])
    out = os.path.join(tempfile.gettempdir(), "flyvibing_sim_trace.jsonl")
    r2 = simulate(scene, frames=3, fps=100, trace_out=out)
    check("trace saved", os.path.exists(out) and r2.get("trace_entries", 0) > 0)
    r3 = simulate(scene, frames=3, fps=60)
    check("low fps warning", bool(r3.get("warnings")), json.dumps(r3.get("warnings")))
    try:
        os.remove(out)
    except OSError:
        pass


def test_injection_and_timebase():
    print("-- injection / timebase modes --")
    scene, _inc, _read, _one = _counter_scene()
    r = simulate(scene, frames=10, fps=100, watch_vars=["a"],
                 set_props={"@one": {"value": 100.0}})
    var = [s for s in r["signals"]["vars"] if s["name"] == "a"]
    check("set_props override", var and var[0].get("last_value") == 1000.0,
          json.dumps(var, ensure_ascii=False)[:200])
    r2 = simulate(scene, frames=10, fps=100, watch_vars=["a"],
                  stub_pins={"@add.Result": 5})
    var2 = [s for s in r2["signals"]["vars"] if s["name"] == "a"]
    check("stub output pin", var2 and var2[0].get("last_value") == 5.0,
          json.dumps(var2, ensure_ascii=False)[:200])
    r2b = simulate(scene, frames=3, fps=100, watch_vars=["a"],
                   stub_pins={"@inc.Value": 7})
    var2b = [s for s in r2b["signals"]["vars"] if s["name"] == "a"]
    check("stub input pin", var2b and var2b[0].get("last_value") == 7.0,
          json.dumps(var2b, ensure_ascii=False)[:200])
    check("fake timebase advertises modes",
          r["timebase"].get("mode") == "fake" and
          r["timebase"].get("modes") == ["fake", "realtime"] and
          "realtime" in (r["timebase"].get("hint") or ""),
          json.dumps(r["timebase"], ensure_ascii=False)[:300])
    r3 = simulate(scene, frames=3, fps=100, mode="realtime", watch_vars=["a"])
    tb = r3["timebase"]
    check("realtime mode", tb.get("mode") == "realtime" and
          (tb.get("measured") or {}).get("fps", 0) > 0,
          json.dumps(tb, ensure_ascii=False)[:300])
    check("realtime warns render jitter", any("GPU" in w or "渲染" in w for w in r3["warnings"]),
          json.dumps(r3.get("warnings"), ensure_ascii=False)[:300])
    r4 = simulate(scene, seconds=0.05, mode="realtime", uncapped=True,
                  watch_vars=["a"])
    tb4 = r4["timebase"]
    check("uncapped realtime", tb4.get("uncapped") is True and
          (tb4.get("measured") or {}).get("fps", 0) > 0 and tb4.get("frames", 0) > 0,
          json.dumps(tb4, ensure_ascii=False)[:300])
    r5 = simulate(scene, seconds=0.05, mode="realtime", fps=0, watch_vars=["a"])
    check("fps=0 implies uncapped", r5["timebase"].get("uncapped") is True,
          json.dumps(r5["timebase"], ensure_ascii=False)[:300])
    try:
        simulate(scene, seconds=11, mode="realtime")
        check("realtime long guard", False)
    except Exception as e:  # noqa: BLE001
        check("realtime long guard", "allow-long" in str(e), str(e))


def test_unconnected_input_injection():
    print("-- unconnected boundary input --")
    g = GraphBuilder()
    _gs, fu, _gp = g.event_nodes()
    pr = g.node("Print", ["exec_in", "Value", "exec_out"], {})
    g.link(fu, "exec", pr, "exec_in")
    g.annotate(pr, "pr")
    scene = {"scene": {"node_graph": g.build(), "entities": {}}}
    r = simulate(scene, frames=1, fps=100, max_trace=10,
                 stub_pins={"@pr.Value": 42})
    events = [e for t in (r.get("trace") or [])
              for e in (t.get("events") or []) if e.get("node_type") == "Print"]
    check("unconnected input injected", bool(events) and "42" in (events[0].get("detail") or ""),
          json.dumps(events, ensure_ascii=False)[:300])


def main() -> int:
    test_counter()
    test_group_scope()
    test_visibility_and_trace()
    test_injection_and_timebase()
    test_unconnected_input_injection()
    print(f"\nSUMMARY: {_RESULTS['pass']} pass / {_RESULTS['fail']} fail")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

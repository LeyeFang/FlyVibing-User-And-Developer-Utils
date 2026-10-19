"""别名 + 节点组 自测。

用法:
    set MGE_ROOT=<engine repo>   # ops 需要引擎节点类型注册表
    .venv-py314t\\Scripts\\python.exe packages/node-editor/src/flyvibing_node_editor/test_aliases_groups.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

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
from flyvibing_node_editor.graph_flow import analyze_flow         # noqa: E402
from flyvibing_node_editor.node_graph_validator import check_graph  # noqa: E402
from flyvibing_node_editor.ops import apply_ops                   # noqa: E402
from Application.Core.NodeGraph import (                           # noqa: E402
    ExecutionContext, GraphEvaluator, NodeCanvas, _TYPES,
)


def _base():
    g = GraphBuilder()
    _gs, fu, _gp = g.event_nodes()
    return g, fu


def _errors(entries):
    return [e for e in entries if e["level"] == "error"]


def test_alias() -> None:
    print("-- node alias --")
    g, fu = _base()
    c = g.node("Constant", ["Result"], {"value": 1})
    scene = g.build()

    r = apply_ops(scene, [{"op": "set_alias", "node": c, "alias": "trial_end"}])
    check("set_alias ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    check("alias stored", scene["nodes"][str(c)].get("alias") == "trial_end")

    r = apply_ops(scene, [{"op": "set_props", "node": "@trial_end", "props": {"value": 7}}])
    check("resolve @alias", r["ok"], str(r["errors"]))
    check("set_props via alias", r["scene"]["nodes"][str(c)]["props"]["value"] == 7)

    r = apply_ops(scene, [{"op": "set_alias", "node": fu, "alias": "trial_end"}])
    check("duplicate alias rejected", not r["ok"])

    r = apply_ops(scene, [{"op": "add_node", "type": "Constant",
                           "props": {"value": 2}, "alias": "trial_end"}])
    check("duplicate at add_node rejected", not r["ok"])

    r = apply_ops(scene, [{"op": "add_node", "type": "Constant",
                           "props": {"value": 2}, "alias": "2bad"}])
    check("invalid alias rejected", not r["ok"])

    bad = json.loads(json.dumps(scene))
    bad["nodes"][str(fu)]["alias"] = "TRIAL_END"
    codes = {e["code"] for e in check_graph(bad)}
    check("validator duplicate_alias", "duplicate_alias" in codes, str(codes))

    r = apply_ops(scene, [{"op": "set_alias", "node": fu, "alias": "frame_tick"}])
    check("alias on event ok", r["ok"], str(r["errors"]))
    flow = analyze_flow(r["scene"], event="OnFrameUpdate")
    check("flow shows alias", any("@frame_tick" in line for line in flow["lines"]),
          "\n".join(flow["lines"][:6]))

    r = apply_ops(scene, [{"op": "set_description", "node": "@trial_end",
                           "description": "Trial counter used by the stop rule."}])
    check("set_description ok", r["ok"], str(r["errors"]))
    check("description stored",
          r["scene"]["nodes"][str(c)].get("description") ==
          "Trial counter used by the stop rule.")
    r = apply_ops(r["scene"], [{"op": "set_description", "node": c}])
    check("description cleared",
          "description" not in r["scene"]["nodes"][str(c)])
    r = apply_ops(scene, [{"op": "add_node", "type": "Constant",
                           "description": "inline description"}])
    check("add_node description",
          any(nd.get("description") == "inline description"
              for nd in r["scene"]["nodes"].values()))


def test_group_add() -> None:
    print("-- cue_n_way add --")
    g, fu = _base()
    scene = g.build()
    params = {"addr": 16376,
              "arms": [{"id": "left", "entity": "L_arrow", "code": 3},
                       {"id": "right", "entity": "R_arrow", "code": 4}]}
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "cue_n_way", "alias": "cue_rand",
         "params": params},
        # 组入口由外部事件驱动
    ])
    check("add_group ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    group = scene["node_groups"]["g1"]
    check("member count 15", len(group["members"]) == 15, str(len(group["members"])))
    check("arm members", set(group["arm_members"]) == {"left", "right"})

    r = apply_ops(scene, [{"op": "link", "from": [fu, "exec"],
                           "to": ["@cue_rand", "entry"]}])
    check("link into group entry", r["ok"], str(r["errors"]))
    scene = r["scene"]

    errs = _errors(check_graph(scene))
    check("validate add: no errors", not errs, str(errs[:3]))

    flow = analyze_flow(scene, event="OnFrameUpdate", include_data=True,
                        data_depth=2)
    text = "\n".join(flow["lines"])
    check("flow enters chain", "Random" in text and "Branch" in text, text[:400])
    check("flow reaches both arms", "L_arrow" in text and "R_arrow" in text, text[:600])
    check("flow reaches send", "ParallelSend" in text)


def test_group_update() -> None:
    print("-- cue_n_way diff update --")
    g, fu = _base()
    scene = g.build()
    arms2 = [{"id": "left", "entity": "L_arrow", "code": 3},
             {"id": "right", "entity": "R_arrow", "code": 4}]
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "cue_n_way", "alias": "cue_rand",
         "params": {"addr": 16376, "arms": arms2}},
        {"op": "link", "from": [fu, "exec"], "to": ["@cue_rand", "entry"]},
    ])
    check("setup ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    before = dict(scene["node_groups"]["g1"]["arm_members"])

    arms3 = arms2 + [{"id": "top", "entity": "T_arrow", "code": 5}]
    r = apply_ops(scene, [
        {"op": "set_group", "group": "@cue_rand",
         "params": {"addr": 16376, "arms": arms3}},
    ])
    check("set_group add arm ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    group = scene["node_groups"]["g1"]
    check("kept arm ids stable",
          group["arm_members"]["left"] == before["left"]
          and group["arm_members"]["right"] == before["right"])
    check("new arm present", "top" in group["arm_members"])
    check("member count 22", len(group["members"]) == 22, str(len(group["members"])))
    errs = _errors(check_graph(scene))
    check("validate add arm: no errors", not errs, str(errs[:3]))
    flow = analyze_flow(scene, event="OnFrameUpdate")
    check("flow has 3rd arm", "T_arrow" in "\n".join(flow["lines"]))

    # 删除中间 arm，并改码值
    arms2b = [{"id": "left", "entity": "L_arrow", "code": 9},
              {"id": "top", "entity": "T_arrow", "code": 5}]
    r = apply_ops(scene, [
        {"op": "set_group", "group": "g1",
         "params": {"addr": 16376, "arms": arms2b}},
    ])
    check("set_group remove arm ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    group = scene["node_groups"]["g1"]
    check("removed arm gone", "right" not in group["arm_members"])
    right_ids = {str(v) for v in before["right"].values()}
    check("removed nodes deleted", not (right_ids & set(scene["nodes"])))
    left_code = group["arm_members"]["left"]["code"]
    check("kept arm code synced",
          scene["nodes"][str(left_code)]["props"]["value"] == 9,
          str(scene["nodes"][str(left_code)]["props"]))
    check("entry remapped", int(group["slots"]["entry"]) in {
        int(ld["to_pin"]) for ld in scene["links"].values()})
    errs = _errors(check_graph(scene))
    check("validate remove arm: no errors", not errs, str(errs[:3]))
    flow = analyze_flow(scene, event="OnFrameUpdate")
    text = "\n".join(flow["lines"])
    check("flow no removed arm", "R_arrow" not in text)
    check("flow still reaches arms", "L_arrow" in text and "T_arrow" in text)

    # 别名改名
    r = apply_ops(scene, [{"op": "set_group", "group": "g1",
                           "params": {}, "alias": "cue_main"}])
    check("set_group rename ok", r["ok"], str(r["errors"]))
    check("alias renamed", r["scene"]["node_groups"]["g1"]["alias"] == "cue_main")


def test_group_multi_entity() -> None:
    print("-- cue_n_way multi-entity arms --")
    g, fu = _base()
    scene = g.build()
    arms = [
        {"id": "left", "entities": ["arrow_body", "arrow_head_copy"], "code": 3},
        {"id": "right", "entities": ["arrow_head", "arrow_body_copy"], "code": 4},
    ]
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "cue_n_way", "alias": "cue_rand",
         "params": {"addr": 16376, "arms": arms}},
        {"op": "link", "from": [fu, "exec"], "to": ["@cue_rand", "entry"]},
    ])
    check("multi add ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    group = scene["node_groups"]["g1"]
    check("member count 19 (2 arms x 2 entities)",
          len(group["members"]) == 19, str(len(group["members"])))
    types = Counter(scene["nodes"][str(n)]["node_type"] for n in group["members"])
    check("EntityGet x4", types["EntityGet"] == 4, str(types))
    check("EntityPack x2", types["EntityPack"] == 2, str(types))
    check("EntityListSetVisible x2", types["EntityListSetVisible"] == 2, str(types))
    check("ParallelSend x2", types["ParallelSend"] == 2, str(types))
    check("group members carry descriptions",
          all(scene["nodes"][str(n)].get("description") for n in group["members"]),
          str([n for n in group["members"]
               if not scene["nodes"][str(n)].get("description")]))
    errs = _errors(check_graph(scene))
    check("validate multi: no errors", not errs, str(errs[:3]))
    flow = analyze_flow(scene, event="OnFrameUpdate", include_data=True, data_depth=2)
    text = "\n".join(flow["lines"])
    check("flow reaches all 4 mesh entities",
          all(name in text for name in
              ("arrow_body", "arrow_head_copy", "arrow_head", "arrow_body_copy")),
          text[:800])
    check("flow shows list set", "EntityListSetVisible" in text)

    right_get = list(group["arm_members"]["right"]["get"])
    left_get = list(group["arm_members"]["left"]["get"])
    arms2 = [
        {"id": "left", "entities": ["arrow_body", "arrow_head_copy", "trace"], "code": 3},
        {"id": "right", "entities": ["arrow_head", "arrow_body_copy"], "code": 4},
    ]
    r = apply_ops(scene, [{"op": "set_group", "group": "@cue_rand",
                           "params": {"arms": arms2}}])
    check("multi set_group ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    group = scene["node_groups"]["g1"]
    check("unchanged arm ids stable",
          list(group["arm_members"]["right"]["get"]) == right_get)
    check("changed arm rebuilt",
          list(group["arm_members"]["left"]["get"]) != left_get)
    check("member count 20 after arm extension",
          len(group["members"]) == 20, str(len(group["members"])))
    errs = _errors(check_graph(scene))
    check("validate multi update: no errors", not errs, str(errs[:3]))


def test_group_window() -> None:
    print("-- cue_window per-frame + nested --")
    g, fu = _base()
    scene = g.build()
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "cue_window", "alias": "trial_window",
         "params": {"clock": "trial_phase", "start": 0, "end": 10,
                    "entity": "TaskCue"}},
        {"op": "add_group", "group_type": "cue_window", "alias": "phase_cue",
         "parent": "@trial_window",
         "params": {"clock": "trial_phase", "start": 0, "end": 2,
                    "entity": "ChildCue"}},
        {"op": "add_node", "type": "VarSet",
         "props": {"var_name": "cue_done"}, "as": "after_cue"},
        {"op": "link", "from": [fu, "exec"],
         "to": ["@trial_window", "entry"]},
        {"op": "link", "from": ["@trial_window", "done"],
         "to": ["@phase_cue", "entry"]},
        {"op": "link", "from": ["@phase_cue", "done"],
         "to": ["after_cue", "exec_in"]},
    ])
    check("window add ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    parent = scene["node_groups"]["g1"]
    child = scene["node_groups"]["g2"]
    check("window parent slots", parent["slots"]["entry"] and parent["slots"]["done"])
    check("window child nested", child.get("parent") == "g1")
    check("parent children", parent.get("children") == ["g2"], str(parent.get("children")))
    check("window members 8", len(child["members"]) == 8, str(len(child["members"])))

    types = Counter(scene["nodes"][str(n)]["node_type"] for n in child["members"])
    check("window uses TimeGetElapsed", types["TimeGetElapsed"] == 1, str(types))
    check("window uses Compare", types["Compare"] == 3, str(types))
    check("window uses EntityGet/SetVisible",
          types["EntityGet"] == 1 and types["EntitySetRenderVisible"] == 1, str(types))

    errs = _errors(check_graph(scene))
    check("validate window: no errors", not errs, str(errs[:3]))
    flow = analyze_flow(scene, event="OnFrameUpdate", include_data=True,
                        data_depth=2)
    text = "\n".join(flow["lines"])
    check("flow reaches both windows",
          "TaskCue" in text and "ChildCue" in text, text[:800])
    check("flow reaches after_cue", "VarSet" in text, text[:800])
    check("flow marks group boundaries",
          "@trial_window IN" in text and "@phase_cue OUT" in text, text[:800])

    old_members = set(child["members"])
    old_entry = int(child["slots"]["entry"])
    old_done = int(child["slots"]["done"])
    r = apply_ops(scene, [{"op": "set_group", "group": "@phase_cue",
                           "params": {"start": 1, "end": 3}}])
    check("window set_group ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    child2 = scene["node_groups"]["g2"]
    check("window member ids rebuilt", old_members.isdisjoint(child2["members"]))
    check("window version bumped", child2["version"] == 2, str(child2["version"]))
    check("window params updated",
          child2["params"]["start"] == 1 and child2["params"]["end"] == 3,
          str(child2["params"]))
    parent2 = scene["node_groups"]["g1"]
    check("nested parent kept", child2.get("parent") == "g1" and
          parent2.get("children") == ["g2"])
    check("window external links remapped",
          any(int(ld["from_pin"]) == int(parent2["slots"]["done"])
              and int(ld["to_pin"]) == int(child2["slots"]["entry"])
              for ld in scene["links"].values()),
          str(scene["links"]))
    check("window outbound link remapped",
          any(int(ld["from_pin"]) == int(child2["slots"]["done"])
              for ld in scene["links"].values()))
    check("old window pins gone", all(
        int(ld["from_pin"]) not in {old_entry, old_done}
        and int(ld["to_pin"]) not in {old_entry, old_done}
        for ld in scene["links"].values()))
    errs = _errors(check_graph(scene))
    check("validate window update: no errors", not errs, str(errs[:3]))

    # visible=false 走 Compare(not) 反转；非法区间拒绝
    g2, _fu2 = _base()
    scene2 = g2.build()
    r = apply_ops(scene2, [{"op": "add_group", "group_type": "cue_window",
                            "alias": "hidden_cue",
                            "params": {"clock": "", "start": 0, "end": 2,
                                       "entity": "TaskCue", "visible": False}}])
    check("window visible=false ok", r["ok"], str(r["errors"]))
    scene2 = r["scene"]
    hidden = scene2["node_groups"]["g1"]
    htypes = Counter(r["scene"]["nodes"][str(n)]["node_type"]
                     for n in hidden["members"])
    check("window visible=false adds NOT", htypes["Compare"] == 4, str(htypes))
    errs = _errors(check_graph(r["scene"]))
    check("validate window visible=false: no errors", not errs, str(errs[:3]))

    r = apply_ops(scene2, [{"op": "add_group", "group_type": "cue_window",
                            "alias": "bad_window",
                            "params": {"start": 2, "end": 1,
                                       "entity": "TaskCue"}}])
    check("window end<start rejected", not r["ok"], str(r["errors"]))
    bad = json.loads(json.dumps(scene2))
    bad["node_groups"]["g1"]["slots"]["done"] = 999999
    codes = {e["code"] for e in check_graph(bad)}
    check("validator group_done_missing", "group_done_missing" in codes, str(codes))

    # 引擎求值：同一图每帧进入，0–2 s true，之后 false
    g3, fu3 = _base()
    scene3 = g3.build()
    r = apply_ops(scene3, [
        {"op": "add_group", "group_type": "cue_window", "alias": "runtime_cue",
         "params": {"clock": "", "start": 0, "end": 2,
                    "entity": "RuntimeCue"}},
        {"op": "link", "from": [fu3, "exec"],
         "to": ["@runtime_cue", "entry"]},
    ])
    check("runtime window setup ok", r["ok"], str(r["errors"]))
    canvas = NodeCanvas.from_dict(r["scene"])
    evaluator = GraphEvaluator(canvas, _TYPES)
    ctx = ExecutionContext()
    ctx.dry_run = True
    logs = []
    ctx.log = lambda nid, ntype, action, detail: logs.append((action, detail))
    ctx.elapsed_time = 1.0
    evaluator.trigger("OnFrameUpdate", ctx)
    check("window active at t=1", any("visible=True" in detail for _a, detail in logs),
          str(logs))
    logs.clear()
    ctx.elapsed_time = 3.0
    evaluator.trigger("OnFrameUpdate", ctx)
    check("window inactive at t=3", any("visible=False" in detail for _a, detail in logs),
          str(logs))


def test_group_hide_container() -> None:
    print("-- hide_group + container --")
    g, fu = _base()
    scene = g.build()
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "cue_window", "alias": "class_window",
         "params": {"clock": "trial_phase", "start": 0, "end": 6,
                    "entity": "ClassCue"}},
        {"op": "add_group", "group_type": "cue_window", "alias": "task_window",
         "params": {"clock": "trial_phase", "start": 2, "end": 6,
                    "entity": "TaskCue"}},
        {"op": "add_group", "group_type": "hide_group", "alias": "rest_window",
         "params": {"entities": ["LeftCue", "RightCue", "TaskCue"],
                    "visible": False}},
        {"op": "add_group", "group_type": "container", "alias": "trial",
         "params": {"children": ["@class_window", "@task_window", "@rest_window"]}},
        {"op": "link", "from": [fu, "exec"],
         "to": ["@trial", "entry"]},
    ])
    check("hide/container add ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    rest = scene["node_groups"]["g3"]
    trial = scene["node_groups"]["g4"]
    check("hide group slots", rest["slots"]["entry"] and rest["slots"]["done"])
    check("hide group uses EntityGetTree",
          any(scene["nodes"][str(n)]["node_type"] == "EntityGetTree"
              for n in rest["members"]))
    check("container children", trial["children"] == ["g1", "g2", "g3"],
          str(trial.get("children")))
    check("container members aggregate",
          len(trial["members"]) == len(scene["node_groups"]["g1"]["members"]) +
          len(scene["node_groups"]["g2"]["members"]) + len(rest["members"]),
          str(len(trial["members"])))
    check("children parent set",
          all(scene["node_groups"][gid].get("parent") == "g4" for gid in ("g1", "g2", "g3")))
    check("container entry from first child",
          int(trial["slots"]["entry"]) ==
          int(scene["node_groups"]["g1"]["slots"]["entry"]))
    check("container done from last child",
          int(trial["slots"]["done"]) ==
          int(scene["node_groups"]["g3"]["slots"]["done"]))
    errs = _errors(check_graph(scene))
    check("validate hide/container: no errors", not errs, str(errs[:3]))

    r = apply_ops(scene, [{"op": "set_group", "group": "@rest_window",
                           "params": {"entities": ["LeftCue", "TaskCue"]}}])
    check("hide set_group ok", r["ok"], str(r["errors"]))
    if r["ok"]:
        scene2 = r["scene"]
        rest2 = scene2["node_groups"]["g3"]
        trial2 = scene2["node_groups"]["g4"]
        check("hide group rebuilt", len(rest2["members"]) == 7,
              str(len(rest2["members"])))
        check("hide group parent kept", rest2.get("parent") == "g4")
        check("container refreshed after hide update",
              len(trial2["members"]) == len(scene2["node_groups"]["g1"]["members"]) +
              len(scene2["node_groups"]["g2"]["members"]) + len(rest2["members"]))
        check("container done follows last child",
              int(trial2["slots"]["done"]) == int(rest2["slots"]["done"]),
              f"{trial2['slots']['done']} vs {rest2['slots']['done']}")
        errs = _errors(check_graph(scene2))
        check("validate hide update: no errors", not errs, str(errs[:3]))


def test_group_linear_templates() -> None:
    print("-- mi_select / phase0_trigger / sss_pulse --")
    g, fu = _base()
    scene = g.build()
    arms2 = [{"id": "left", "entities": ["L_arrow_body", "L_arrow_head"], "code": 1},
             {"id": "right", "entities": ["R_arrow_head", "R_arrow_body"], "code": 2}]
    r = apply_ops(scene, [
        {"op": "add_group", "group_type": "mi_select", "alias": "mi_select",
         "params": {"mi_var": "mi_code", "arms": arms2}},
        {"op": "add_group", "group_type": "phase0_trigger",
         "alias": "phase0_trigger", "params": {"mi_scale": 32}},
        {"op": "add_group", "group_type": "sss_pulse", "alias": "sss_pulse",
         "params": {"interval": -0.05}},
        {"op": "add_group", "group_type": "container", "alias": "trial",
         "params": {"children": ["@mi_select"]}},
        {"op": "link", "from": [fu, "exec"], "to": ["@mi_select", "entry"]},
        {"op": "link", "from": ["@mi_select", "done"],
         "to": ["@phase0_trigger", "entry"]},
        {"op": "link", "from": ["@phase0_trigger", "done"],
         "to": ["@sss_pulse", "entry"]},
    ])
    check("linear groups add ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    sel = scene["node_groups"]["g1"]
    trig = scene["node_groups"]["g2"]
    pulse = scene["node_groups"]["g3"]
    check("mi_select members 15", len(sel["members"]) == 15, str(len(sel["members"])))
    check("phase0_trigger members 8", len(trig["members"]) == 8,
          str(len(trig["members"])))
    check("sss_pulse members 8", len(pulse["members"]) == 8,
          str(len(pulse["members"])))
    check("mi_select entry chain starts with VarSet",
          scene["nodes"][str(sel["members"][1])]["node_type"] == "VarSet")
    check("linear group parent set", sel.get("parent") == "g4", str(sel.get("parent")))
    check("all linear members described",
          all(scene["nodes"][str(n)].get("description")
              for grp in (sel, trig, pulse) for n in grp["members"]))
    errs = _errors(check_graph(scene))
    check("validate linear groups: no errors", not errs, str(errs[:3]))

    r = apply_ops(scene, [
        {"op": "set_group", "group": "@mi_select",
         "params": {"arms": arms2 + [{"id": "none", "entities": ["part1", "part2"],
                                      "code": 3}]}},
        {"op": "set_group", "group": "@phase0_trigger",
         "params": {"mi_scale": 16}},
        {"op": "set_group", "group": "@sss_pulse",
         "params": {"interval": -0.1}},
    ])
    check("linear set_group ok", r["ok"], str(r["errors"]))
    scene = r["scene"]
    sel2 = scene["node_groups"]["g1"]
    trig2 = scene["node_groups"]["g2"]
    pulse2 = scene["node_groups"]["g3"]
    check("mi_select arm added", len(sel2["members"]) == 21,
          str(len(sel2["members"])))
    check("phase0 scale updated",
          any(scene["nodes"][str(n)]["node_type"] == "Constant"
              and scene["nodes"][str(n)]["props"].get("value") == 16
              for n in trig2["members"]))
    check("sss interval updated",
          any(scene["nodes"][str(n)]["node_type"] == "SetTimer"
              and scene["nodes"][str(n)]["props"].get("value") == -0.1
              for n in pulse2["members"]))
    check("mi_select entry still linked",
          int(sel2["slots"]["entry"]) in
          {int(link["to_pin"]) for link in scene["links"].values()})
    check("linear group parent kept", sel2.get("parent") == "g4")
    check("container child refreshed",
          scene["node_groups"]["g4"]["children"] == ["g1"],
          str(scene["node_groups"]["g4"].get("children")))
    errs = _errors(check_graph(scene))
    check("validate linear update: no errors", not errs, str(errs[:3]))


def main() -> int:
    test_alias()
    test_group_add()
    test_group_update()
    test_group_multi_entity()
    test_group_window()
    test_group_hide_container()
    test_group_linear_templates()
    print(f"\n{_RESULTS['pass']} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

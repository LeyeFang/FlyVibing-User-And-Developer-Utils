"""Graph Flow (V1) 自测 — 合成图 + 真实场景（可选）。

用法:
    .venv-py314t\\Scripts\\python.exe packages/node-editor/src/flyvibing_node_editor/test_flow.py

环境:
    MGE_ROOT      引擎仓库根（默认向上查找 Application/Core/NodeGraph）
    MGE_MI_SCENE  可选的 .scene 路径（存在则跑真实图断言）
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

from flyvibing_node_editor.graph_builder import GraphBuilder  # noqa: E402
from flyvibing_node_editor.graph_flow import analyze_flow        # noqa: E402


def _synthetic():
    """FU → Sequence(out_0 → TimeTrigger[GATE] → VarSet → 回到 Sequence; out_1 → Branch(True→Exit, False→Exit))。"""
    g = GraphBuilder()
    _gs, fu, _gp = g.event_nodes()

    seq = g.node("Sequence", ["exec_in", "out_0", "out_1"])
    g.link(fu, "exec", seq, "exec_in")

    tt = g.time_triggers("trial_phase", 2.0)[0]
    g.link(seq, "out_0", tt, "exec_in")

    v = g.var_set("trial", 1)
    g.link(tt, "out_0", v, "exec_in")
    g.link(v, "exec_out", seq, "exec_in")          # 故意制造环

    const = g.constant(1)
    br = g.branch_on((const, "Result"))
    g.link(seq, "out_1", br, "exec_in")
    ex1 = g.node("ExitGame", ["exec_in"])
    ex2 = g.node("ExitGame", ["exec_in"])
    g.link(br, "True", ex1, "exec_in")
    g.link(br, "False", ex2, "exec_in")
    return g.build()


def test_synthetic() -> None:
    print("-- synthetic graph --")
    r = analyze_flow(_synthetic(), event="OnFrameUpdate", max_depth=24, max_lines=80)
    text = "\n".join(r["lines"])
    check("ok", r["ok"] is True, str(r["warnings"]))
    check("起始节点是 OnFrameUpdate", r["start"]["type"] == "OnFrameUpdate", str(r["start"]))
    check("Sequence 展开", "#" in text and "Sequence" in text)
    check("TimeTrigger 标注 [GATE]", "TimeTrigger" in text and "[GATE]" in text)
    check("Branch 两路 + 条件来源", "<True>" in text and "<False>" in text and "cond <-" in text)
    check("ExitGame 标注 [TERMINAL]", "[TERMINAL]" in text)
    check("环检测 [CYCLE", "[CYCLE" in text, text)
    check("summary.gates >= 1", r["summary"]["gates"] >= 1, str(r["summary"]))
    check("summary.terminals >= 1", r["summary"]["terminals"] >= 1, str(r["summary"]))
    check("summary.cycles >= 1", r["summary"]["cycles"] >= 1, str(r["summary"]))

    r2 = analyze_flow(_synthetic(), event="OnFrameUpdate", max_lines=4)
    check("行预算截断", r2["summary"]["truncated"] is True, str(r2["summary"]))

    r3 = analyze_flow(_synthetic(), event="NoSuchEvent")
    check("未知事件 → ok=False", r3["ok"] is False)


def test_real_scene() -> None:
    scene = os.environ.get("MGE_MI_SCENE", "")
    if not scene or not os.path.isfile(scene):
        print("-- real scene: SKIPPED (set MGE_MI_SCENE) --")
        return
    print(f"-- real scene: {os.path.basename(scene)} --")
    with open(scene, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    r = analyze_flow(data, event="OnFrameUpdate", max_lines=200, max_depth=32)
    text = "\n".join(r["lines"])
    check("真实图 ok", r["ok"] is True, str(r["warnings"]))
    check("含 Sequence", "Sequence" in text)
    check("含 TimeTrigger GATE", "TimeTrigger" in text and "[GATE]" in text)
    check("含 Branch 条件来源", "cond <-" in text)
    check("节点数 > 5", r["summary"]["nodes"] > 5, str(r["summary"]))


def main() -> int:
    print("=" * 60)
    print("  graph_flow (V1) — static execution flow")
    print("=" * 60)
    if not _ROOT:
        print("  ! engine root not found — set MGE_ROOT")
    test_synthetic()
    test_real_scene()
    print("-" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

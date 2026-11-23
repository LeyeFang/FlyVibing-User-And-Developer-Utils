"""Phase 0/1 contract tests — CLI manifest + multi-target setup.

跑法（工具仓根目录，使用引擎 venv）:
    D:/MyWork/Project/FlyVibing-Engine/.venv-py314t/Scripts/python.exe \
      packages/editor-mcp/test_manifest_setup.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "editor-mcp" / "src"))
sys.path.insert(0, str(_REPO / "packages" / "node-editor" / "src"))

from engine_editor_mcp import cli as engine_cli  # noqa: E402
from flyvibing_node_editor import cli as node_cli  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _run(argv: list[str]):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = engine_cli.main(argv)
    return code, buf.getvalue()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_engine_manifest() -> None:
    print("-- engine manifest --")
    m = engine_cli.build_manifest()
    check("schema", m.get("schema") == "engine-cli/manifest/v1")
    check("ops non-empty", len(m.get("ops") or []) > 50, str(len(m.get("ops") or [])))
    check("commands include setup/ops", {"ops", "setup", "validate"} <=
          {c["name"] for c in m.get("commands") or []})
    validate = next(o for o in m["ops"] if o["name"] == "graph.validate.start")
    params = {p["name"] for p in validate["params"]}
    check("validate.start exposes dt/realtime", {"dt", "realtime", "allow_long"} <= params,
          str(sorted(params)))
    code, out = _run(["ops", "--json"])
    check("cli ops --json", code == 0 and json.loads(out)["schema"] == "engine-cli/manifest/v1")

    src = _REPO / "agent" / "targets.json"
    dst = _REPO / "packages" / "editor-mcp" / "src" / "engine_editor_mcp" / "agent_targets.json"
    check("packaged agent targets synced", src.read_bytes() == dst.read_bytes())


def test_node_manifest() -> None:
    print("-- node manifest / error --")
    m = node_cli.build_manifest()
    names = {c["name"] for c in m.get("commands") or []}
    check("schema", m.get("schema") == "flyvibing-node-editor/manifest/v1")
    check("commands include schema/query/simulate", {"schema", "query", "simulate"} <= names,
          str(sorted(names)))
    check("graph schemas declared", m.get("graph_schemas", {}).get("patch") == "graph-patch/v1")

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = node_cli.main(["query", "--scene", "missing.scene", "--from", "@x"])
    payload = json.loads(buf.getvalue())
    check("node error is JSON on stdout",
          code == 2 and payload.get("schema") == "node-cli/error/v1" and payload.get("ok") is False,
          buf.getvalue()[:200])


def test_generic_setup() -> None:
    print("-- setup generic / AGENTS.md --")
    tmp = Path(tempfile.mkdtemp(prefix="flyvibing-setup-"))
    try:
        agents = tmp / "AGENTS.md"
        agents.write_text("# User Notes\n\nKeep this line.\n", encoding="utf-8")
        code, out = _run(["setup", "--workspace", str(tmp), "--target", "generic", "--json"])
        data = json.loads(out)
        text = _read(agents)
        check("generic setup ok", code == 0 and data.get("written") is True)
        check("AGENTS block added", "flyvibing:begin" in text and "engine-editor-cli ops --json" in text)
        check("canonical onboarding used",
              "## 先看这里：CLI 优先" in text and "## 安装到工作区" in text)
        check("user content preserved", "Keep this line." in text)

        _run(["setup", "--workspace", str(tmp), "--target", "generic"])
        text2 = _read(agents)
        check("AGENTS idempotent", text2.count("flyvibing:begin") == 1,
              str(text2.count("flyvibing:begin")))
        check("user content still preserved", "Keep this line." in text2)

        _run(["setup", "--workspace", str(tmp), "--target", "generic", "--uninstall"])
        text3 = _read(agents)
        check("AGENTS block removed", "flyvibing:begin" not in text3 and "Keep this line." in text3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_platform_targets() -> None:
    print("-- setup targets --")
    tmp = Path(tempfile.mkdtemp(prefix="flyvibing-targets-"))
    try:
        code, out = _run(["setup", "--workspace", str(tmp), "--target", "vscode"])
        mcp = json.loads(_read(tmp / ".vscode" / "mcp.json"))
        entry = mcp["servers"]["engine-editor-live"]
        check("vscode servers key", code == 0 and mcp.get("servers") and entry.get("type") == "stdio")
        check("vscode skill copied", (tmp / ".github/skills/engine-editor/SKILL.md").is_file())

        code, _ = _run(["setup", "--workspace", str(tmp), "--target", "claude"])
        mcp = json.loads(_read(tmp / ".mcp.json"))
        entry = mcp["mcpServers"]["engine-editor-live"]
        check("claude mcpServers key", code == 0 and mcp.get("mcpServers") is not None)
        check("claude no type field", "type" not in entry)
        check("claude skill copied", (tmp / ".claude/skills/engine-editor/SKILL.md").is_file())

        code, _ = _run(["setup", "--workspace", str(tmp), "--target", "cursor"])
        mcp = json.loads(_read(tmp / ".cursor" / "mcp.json"))
        check("cursor mcpServers key", code == 0 and "engine-editor-live" in mcp["mcpServers"])

        print_dir = Path(tempfile.mkdtemp(prefix="flyvibing-print-"))
        try:
            code, out = _run(["setup", "--workspace", str(print_dir),
                              "--target", "vscode", "--print"])
            check("print does not write",
                  code == 0 and "[mcp]" in out
                  and not (print_dir / ".vscode" / "mcp.json").exists()
                  and not (print_dir / "AGENTS.md").exists())
        finally:
            shutil.rmtree(print_dir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_auto_detect_and_errors() -> None:
    print("-- auto detect / errors --")
    tmp = Path(tempfile.mkdtemp(prefix="flyvibing-auto-"))
    try:
        (tmp / ".vscode").mkdir()
        code, out = _run(["setup", "--workspace", str(tmp), "--target", "auto", "--json"])
        data = json.loads(out)
        check("auto detects vscode", code == 0 and "vscode" in data.get("targets", []),
              str(data.get("targets")))
        check("auto adds generic", "generic" in data.get("targets", []))
        check("auto writes vscode mcp", (tmp / ".vscode" / "mcp.json").is_file())
        check("auto writes AGENTS.md", (tmp / "AGENTS.md").is_file())

        code, out = _run(["setup", "--workspace", str(tmp), "--target", "unknown"])
        payload = json.loads(out)
        check("unknown target is usage error",
              code == 2 and payload.get("ok") is False and "unknown target" in payload.get("detail", ""),
              out[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_generated_agent_docs() -> None:
    print("-- generated agent docs --")
    onboarding_src = _REPO / "agent" / "onboarding.md"
    onboarding_dst = (_REPO / "packages" / "editor-mcp" / "src" / "engine_editor_mcp"
                      / "agent_onboarding.md")
    check("packaged onboarding synced", onboarding_src.read_bytes() == onboarding_dst.read_bytes())

    for skill, package in (
        ("engine-editor", _REPO / "packages" / "editor-mcp" / "src" / "engine_editor_mcp" / "skills"),
        ("node-graph", _REPO / "packages" / "node-editor" / "src" / "flyvibing_node_editor" / "skills"),
    ):
        src_file = _REPO / "skills" / skill / "SKILL.md"
        dst_file = package / skill / "SKILL.md"
        check(f"{skill} skill synced into package",
              dst_file.is_file() and src_file.read_bytes() == dst_file.read_bytes())

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "gen_agent_docs.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", env=env)
    check("gen_agent_docs --check", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-300:])

    agents = _read(_REPO / "AGENTS.md")
    check("root AGENTS uses canonical onboarding",
          "## 先看这里：CLI 优先" in agents and "## 上下文纪律" in agents)
    check("root AGENTS marker block", agents.count("flyvibing:begin") == 1
          and agents.count("flyvibing:end") == 1)

    engine_skill = _read(_REPO / "skills" / "engine-editor" / "SKILL.md")
    check("engine skill counts generated",
          "80 个核心 op" in engine_skill and "45 个旧 `editor_*` 工具" in engine_skill)
    node_skill = _read(_REPO / "skills" / "node-graph" / "SKILL.md")
    check("node skill counts generated", "19 个 CLI 命令" in node_skill)


def test_generated_mcp_tools() -> None:
    print("-- generated MCP tools --")
    from engine_editor_mcp import ops as op_registry
    from engine_editor_mcp import server

    tools = server._ALL_TOOL_OBJECTS
    expected = (set(server.LITE_TOOL_NAMES) | set(op_registry.ALIASES)
                | set(op_registry.LEGACY_SPECIAL_TOOLS))
    check("tool registry complete", set(tools) == expected,
          f"missing={sorted(expected - set(tools))} extra={sorted(set(tools) - expected)}")
    check("full legacy count matches",
          len(op_registry.legacy_tool_specs()) + len(op_registry.LEGACY_SPECIAL_TOOLS) == 45,
          str(len(op_registry.legacy_tool_specs())))

    server.apply_profile("lite")
    lite = set(server.mcp._tool_manager._tools)
    check("lite profile exact", lite == set(server.LITE_TOOL_NAMES), str(sorted(lite)))

    server.apply_profile("full")
    full = set(server.mcp._tool_manager._tools)
    expected_full = expected - set(server.LITE_TOOL_NAMES) | set(server._SHARED_TOOL_NAMES)
    check("full profile exact", full == expected_full,
          f"missing={sorted(expected_full - full)} extra={sorted(full - expected_full)}")
    check("all aliases exposed in full", set(op_registry.ALIASES) <= full)

    def params(name: str) -> dict:
        return tools[name].parameters.get("properties") or {}

    def required(name: str) -> set[str]:
        return set(tools[name].parameters.get("required") or [])

    check("entity_id renamed for entity ops",
          "entity_id" in params("editor_entity_get") and "id" not in params("editor_entity_get"))
    check("graph_link dotted params",
          {"from_node", "from_pin", "to_node", "to_pin"} <= set(params("editor_graph_link"))
          and required("editor_graph_link") == {"from_node", "from_pin", "to_node", "to_pin"})
    check("switch_2d takes no params", not params("editor_switch_2d"))
    camera_set = params("editor_camera_set")
    check("camera role default 3d",
          camera_set.get("role", {}).get("default") == "3d"
          and "role" not in required("editor_camera_set"))
    check("component fields typed object",
          params("editor_component_set").get("fields", {}).get("type") == "object")
    check("graph node type renamed",
          "node_type" in params("editor_graph_add") and "type" not in params("editor_graph_add"))


def main() -> int:
    test_engine_manifest()
    test_node_manifest()
    test_generated_agent_docs()
    test_generic_setup()
    test_platform_targets()
    test_auto_detect_and_errors()
    test_generated_mcp_tools()
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

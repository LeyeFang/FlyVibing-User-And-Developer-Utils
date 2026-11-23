#!/usr/bin/env python3
"""生成 agent 入口文档（canonical onboarding → 各视图）。

用法:
    python scripts/gen_agent_docs.py           # 写入 AGENTS.md / llms.txt / SKILL 生成块
    python scripts/gen_agent_docs.py --check   # 只校验（CI/测试用；不一致退出码 1）

事实源:
    agent/onboarding.md            — 入口说明（CLI 优先 / MCP 可选 / 纪律）
    packages/.../ops.py            — op 数 / full 档工具数
    flyvibing_node_editor.cli      — node CLI 命令数
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "editor-mcp" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "node-editor" / "src"))

from engine_editor_mcp import agent_docs, ops as op_registry  # noqa: E402
from flyvibing_node_editor import cli as node_cli  # noqa: E402

AGENTS_MD = ROOT / "AGENTS.md"
LLMS_TXT = ROOT / "llms.txt"
ENGINE_SKILL = ROOT / "skills" / "engine-editor" / "SKILL.md"
NODE_SKILL = ROOT / "skills" / "node-graph" / "SKILL.md"
ONBOARDING = ROOT / "agent" / "onboarding.md"


def render_agents_md() -> str:
    return "# Agent Notes\n\n" + agent_docs.render_agents_block(
        ["skills"], onboarding=ONBOARDING.read_text(encoding="utf-8")) + "\n"


def render_llms_txt() -> str:
    return "\n".join([
        "# FlyVibing Tools",
        "",
        "> CLI-first agent toolchain for MyGameEngine: 实时编辑器控制 + 离线节点图。",
        "> 命令清单是机器可读的；MCP 只是可选适配层。",
        "",
        "## Manifests",
        "- `engine-editor-cli ops --json` — engine-cli/manifest/v1",
        "- `flyvibing-node-editor schema` — flyvibing-node-editor/manifest/v1",
        "- `agent/targets.json` — flyvibing-agent-targets/v1（setup --target）",
        "",
        "## Skills",
        "- [engine-editor](skills/engine-editor/SKILL.md) — 实时编辑器 CLI/MCP",
        "- [node-graph](skills/node-graph/SKILL.md) — 离线节点图 spec→scene",
        "",
        "## Docs",
        "- [Agent onboarding](agent/onboarding.md)",
        "- [Tutorial](docs/TUTORIAL.md)",
        "- [README](README.md)",
        "- [Install](packaging/README-INSTALL.md)",
        "",
    ])


def render_engine_skill(text: str) -> str:
    body = agent_docs.render_engine_skill_block(
        ops_count=len(op_registry.op_names()),
        legacy_tools=len(op_registry.legacy_tool_specs()) + len(op_registry.LEGACY_SPECIAL_TOOLS),
    )
    return agent_docs.replace_block(text, body,
                                    agent_docs.SKILL_BEGIN, agent_docs.SKILL_END)


def render_node_skill(text: str) -> str:
    body = agent_docs.render_node_skill_block(
        command_count=len(node_cli.build_manifest()["commands"]),
    )
    return agent_docs.replace_block(text, body,
                                    agent_docs.SKILL_BEGIN, agent_docs.SKILL_END)


def _targets() -> dict[Path, str]:
    originals = {
        ENGINE_SKILL: ENGINE_SKILL.read_text(encoding="utf-8"),
        NODE_SKILL: NODE_SKILL.read_text(encoding="utf-8"),
    }
    return {
        AGENTS_MD: render_agents_md(),
        LLMS_TXT: render_llms_txt(),
        ENGINE_SKILL: render_engine_skill(originals[ENGINE_SKILL]),
        NODE_SKILL: render_node_skill(originals[NODE_SKILL]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/gen_agent_docs.py")
    ap.add_argument("--check", action="store_true", help="只校验，不写盘")
    args = ap.parse_args(argv)

    stale: list[Path] = []
    for path, content in _targets().items():
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        if existing == content:
            continue
        stale.append(path)
        if not args.check:
            path.write_text(content, encoding="utf-8")
            print(f"[gen] wrote {path.relative_to(ROOT)}")

    if args.check:
        for path in stale:
            print(f"[gen] OUT OF DATE: {path.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("[gen] run: python scripts/gen_agent_docs.py", file=sys.stderr)
            return 1
        print("[gen] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

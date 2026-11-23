"""Agent 入口文档渲染 — setup / scripts/gen_agent_docs.py 共用。

canonical 源: `agent/onboarding.md`
→ 打包副本 `agent_onboarding.md`（scripts/build_tools.py 同步）
→ `setup` 写入工作区的 AGENTS.md 标记块
→ `scripts/gen_agent_docs.py` 写入仓库根 AGENTS.md / llms.txt / SKILL 生成块
"""

from __future__ import annotations

from pathlib import Path

AGENTS_BEGIN = "<!-- flyvibing:begin -->"
AGENTS_END = "<!-- flyvibing:end -->"
SKILL_BEGIN = "<!-- flyvibing:onboarding:begin -->"
SKILL_END = "<!-- flyvibing:onboarding:end -->"

_FALLBACK_ONBOARDING = (
    "## FlyVibing 工具链\n"
    "\n"
    "- 实时编辑器: `engine-editor-cli ops --json` / `engine-editor-cli help <op>`。\n"
    "- 离线节点图: `flyvibing-node-editor schema` / `flyvibing-node-editor rules`。\n"
    "- CLI 优先（任意终端可用）；MCP 是可选工具通道。\n"
    "- stdout 始终是 JSON；退出码 0 成功 / 1 运行错误 / 2 用法错误。\n"
)


def onboarding_text(source: str | Path | None = None) -> str:
    path = Path(source) if source else Path(__file__).resolve().parent / "agent_onboarding.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return _FALLBACK_ONBOARDING.strip()


def render_agents_block(
    skill_dirs: list[str] | tuple[str, ...] = (),
    onboarding: str | None = None,
) -> str:
    lines = [AGENTS_BEGIN, (onboarding or onboarding_text()).strip(), ""]
    if skill_dirs:
        lines.append("## 本工作区已安装")
        for rel in skill_dirs:
            lines.append(f"- 实时编辑器 skill: `{rel}/engine-editor/SKILL.md`")
        lines.append("- 离线节点图 skill 随 `flyvibing-node-editor` 包分发"
                     "（`flyvibing-node-editor rules`）。")
        lines.append("")
    lines.append(AGENTS_END)
    return "\n".join(lines)


def render_engine_skill_block(ops_count: int, legacy_tools: int) -> str:
    return "\n".join([
        SKILL_BEGIN,
        "## 1. 通道与规模（由 `agent/onboarding.md` + 注册表生成 — 勿手改）",
        "",
        "- **CLI 优先**：`engine-editor-cli ops --json` / `help <op>`；任意终端型 agent 可用，"
        "未使用时常驻成本为 0。",
        f"- **MCP 可选**：lite 档 6 个元工具；full 档 {legacy_tools} 个旧 `editor_*` 工具 + "
        "`engine_launch`。",
        f"- **规模**：{ops_count} 个核心 op（不含内部 op）；完整参考 `references/ops.md`"
        "（docgen 生成）。",
        "- **纪律**：先索引后内容；大输出落盘再局部读；多步操作合并成 `batch` / `exec`。",
        SKILL_END,
    ])


def render_node_skill_block(command_count: int) -> str:
    return "\n".join([
        SKILL_BEGIN,
        "## 0. 通道与规模（由 `agent/onboarding.md` + 注册表生成 — 勿手改）",
        "",
        "- **CLI 优先**：`flyvibing-node-editor schema` / `rules <section>`；"
        "任意终端型 agent 可用，未使用时常驻成本为 0。",
        "- **MCP 可选**：`node-graph-editor`（4 工具）；无终端环境再用。",
        f"- **规模**：{command_count} 个 CLI 命令；图数据契约 `graph-query/v1` / "
        "`graph-patch/v1` / `graph-sim/v1`。",
        "- **纪律**：规则永远先看目录、按节取；图 JSON 落盘后局部读取。",
        SKILL_END,
    ])


def replace_block(text: str, body: str, begin: str, end: str) -> str:
    """替换标记块；标记缺失时追加（调用方负责首次插入位置）。"""
    if begin in text and end in text:
        before, rest = text.split(begin, 1)
        _, after = rest.split(end, 1)
        return before.rstrip() + "\n\n" + body + after
    return text.rstrip() + "\n\n" + body + "\n"

# engine-editor-mcp — 编辑器实时 MCP + CLI（独立发布包）

把 **MyGameEngine 编辑器**的实时控制能力带给任意三方工作区里的 AI agent。
引擎开着，agent 就能干活（编辑器未运行时工具返回明确错误，不会静默失败）。

## 三种消费形态（同一 wheel / 同一 op 注册表）

| 形态 | 未使用时常驻成本 | 适用 |
|---|---|---|
| **CLI** `engine-editor-cli`（终端） | **0** | 任意终端型 agent（Codex / Copilot / Claude Code / Cursor ...）；多步、批处理、脚本首选 |
| **MCP lite**（推荐档） | ~1k tokens（6 个工具） | IDE 内 agent；`engine_help` / `engine_call` / `engine_batch` / `engine_validate_graph` / `engine_capture` / `engine_launch` |
| **MCP full**（兼容档） | ~6k tokens（45 个旧工具 + `engine_launch`） | 旧提示词/旧工作流仍绑定 `editor_*` 工具名时（`--profile full`） |

> 另有 Skill（`engine-editor`）：渐进披露的用法文档（SKILL.md + references）——
> agent 只在相关任务时才加载。v0.5.0 新增 `engine_launch` 与 CLI `launch`/`engines`，
> 支持多引擎自动端口协商。

## 安装

```powershell
# 方式 1 — wheel（离线分发）
pip install engine_editor_mcp-0.5.0-py3-none-any.whl

# 方式 2 — 从源码安装（dev）
pip install -e packages/editor-mcp
```

依赖：`mcp==1.10.1`、`pydantic==2.13.4`、`pydantic-settings==2.14.2`（与引擎 wheelhouse 对齐）、`Pillow`、`numpy`。

工具链发行版 zip（`FlyVibing-Tools-0.5.0.zip`）内含三个 wheel 和一键安装脚本：
解压后双击 `install.cmd`，或执行 `sh install.sh`。

## 在三方工作区启用（任意 IDE）

```powershell
# 一条命令：拷贝 Skill（.github/skills/engine-editor/）+ 合并 .vscode/mcp.json（lite 档）
engine-editor-cli setup --workspace C:\path\to\your-experiment-project
```

- `--skills claude|agents|all|none` 选择 Skill 目标目录（默认 `.github/skills`）；
- `--profile full` 用旧 45 个 `editor_*` 工具 + `engine_launch`；`--python <exe>` 指定 MCP 启动解释器；
- `--port N` 固定该工作区的 MCP 端口（多 agent 时每个工作区不同）；`--engine-root DIR` 写入
  `MGE_ENGINE_ROOT`，方便在任意工作区调用 `engine_launch`；
- `--dry-run` 预览；`--uninstall` 卸载（移除 Skill + mcp.json 条目）。

不用 MCP 的平台也可以只用 CLI：终端里 `engine-editor-cli call sim.state`。

## 启动引擎（自动端口，多引擎友好）

```powershell
# 在引擎根目录（含 startup.bat）或传 --engine-root；自动选 8977..9076 空闲端口
engine-editor-cli launch --port auto --language zh --set ui.font_scale=1.15

# 后续命令指向返回的端口
engine-editor-cli --port 8977 call settings.get

# 发现本机运行中的编辑器
engine-editor-cli engines
```

MCP lite/full 都有 `engine_launch(engine_root=..., port="auto", language="zh", settings={...})`；
成功后该 MCP 进程后续调用自动使用新端口。多个 agent 各自 `launch --port auto` 即可互不串话；
也可以给 MCP 配 `--port N` 连接已有实例。

**English**: `launch --port auto` starts an editor on the first free port and waits for the
`sim.state` handshake. Each agent can own its own port; `engines` lists active instances.

## 使用前提

1. 启动引擎编辑器（仓库内 `startup.bat`；发行版为安装器快捷方式）；
2. 编辑器控制台出现 `[Live] Editor command server on 127.0.0.1:8977` 即就绪；
3. 端口可在 Settings ▸ Common ▸ Port 或 `--port N` / `--settings` 中设置（范围 1024..65535）。

## CLI 速览

```powershell
engine-editor-cli ops                      # op 目录（70 个核心 op）
engine-editor-cli call graph.group.merge nodes=[2,3]   # 选中节点合并为组
engine-editor-cli call graph.group.ungroup group=g1    # 拆分组框（保留节点）
engine-editor-cli help entity.transform    # 单 op 详情（参数 + 示例）
engine-editor-cli call entity.add name=MCP_Cue
engine-editor-cli call entity.transform id=5 position='[1,0,2]'   # 数组/对象加引号
engine-editor-cli batch ops.json           # 顺序批处理（- = stdin）
engine-editor-cli exec script.py           # 脚本模式（注入 engine 客户端, 可过滤输出 -> 省 token）
engine-editor-cli validate                 # 图干跑校验（默认 summary）
engine-editor-cli capture pie --out f.png  # 抓帧落盘（只回路径）
engine-editor-cli launch --port auto       # 启动引擎 + 自动端口握手
engine-editor-cli engines                  # 发现运行中的编辑器
```

值解析：先按 JSON（数字/true/false/数组/对象/带引号字符串），失败按纯字符串。
退出码：0 成功 / 1 引擎或运行时错误 / 2 用法错误。

## MCP 注册（手写 mcp.json 时）

```json
{ "servers": { "engine-editor-live": {
  "type": "stdio",
  "command": "engine-editor-mcp",
  "args": ["--profile", "lite"],
  "env": { "MGE_ENGINE_ROOT": "C:/path/to/MyGameEngine-Python" }
} } }
```

- 多 agent：给不同 MCP 进程加 `"args": ["--profile","lite","--port","8978"]`，或在工具里调用
  `engine_launch(port="auto")`；`engine_launch` 成功后本进程会自动切换端口。
- `MGE_ENGINE_ROOT` 只在需要从任意工作区 `engine_launch` 时设置；也可在 `engine_launch` 里显式传 `engine_root`。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `MGE_EDITOR_MCP_PORT` | 引擎命令端口（**两侧需一致**；优先于 Settings `server.port`） | `8977` |
| `MGE_ENGINE_ROOT` | `launch`/`engine_launch` 找不到 `startup.bat` 时的引擎根目录 | 当前目录向上查找 |
| `MGE_MCP_FRAMES_DIR` | 抓帧根目录（server 启动时清空） | `<临时目录>/engine_editor_mcp` |
| `MGE_MCP_PROFILE` | MCP 档位 `lite` / `full`（启动参数 `--profile` 优先） | `full`（仓库安装脚本默认写 `lite`） |

## 抓帧说明

- MCP `engine_capture` → PNG 落盘 + **图像直回**（agent 能直接看到画面）；
- CLI `capture` → 只落盘并回路径（不把图像塞进上下文 — 省 token）。

## 与引擎仓库的关系

- 本包源码位于引擎仓库 `packages/editor-mcp/`（开发入口、独立包源码、构建器与 Skill 源）；
- 协议细节见引擎仓库 `Doc/Dev/editor_live_protocol.md`；
- 新增 op 后：引擎侧注册 → `ops.py` 加条目 → `python -m engine_editor_mcp.docgen` 重生成
  `skills/engine-editor/references/ops.md`（离线测试 `test_editor_mcp_package.py` 会校验一致性）。


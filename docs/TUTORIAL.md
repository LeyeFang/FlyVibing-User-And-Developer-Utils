# 从零做一个实验：完整教学

> 目标读者：**实验设计者**（不写引擎代码）。你只需要：装好的 FlyVibingEngine + 一个 AI agent
> （VS Code Copilot / Codex / Claude Code / 任何能跑命令或 MCP 的客户端）+ 一个空工作区。
>
> 走完本教学，你的工作区里会得到和官方范式示例一致的两样东西：
> - `project/` —— **实验设计**（场景 + 节点图，可进版本库、可反复改）
> - `rst/` —— **成品**（含运行时，双击 `run_game.cmd` 就能被试跑）
>
> 官方示例可对照：`Paradigm/project/MI-SSSEP` 与 `Paradigm/rst/MI-SSSEP`。

---

## 0. 三个概念（先分清，后面就不迷路）

| 东西 | 是什么 | 谁需要 |
|---|---|---|
| **引擎（编辑器）** | 你看到的窗口：摆场景、连节点图、跑预览、导出 | 你要装（安装包）或开发者用源码启动 |
| **你的工作区** | 一个空文件夹，放**实验设计**与**成品**，以及给 agent 的说明 | 你自己建 |
| **工具链（本仓库）** | 让 agent 能"替你操作引擎"的桥：`editor-mcp`（实时）+ `node-editor`（离线）+ `extension-kit` | 装一次，工作区里用 |

**你不需要**：装 Python、装 uv、配虚拟环境 —— 引擎自带运行时；本仓库的安装走 pip/wheel。

---

## 1. 准备

1. **装引擎**：跑 `FlyVibingEngine-Setup-*.exe`（默认装到 `%ProgramFiles%\FlyVibingEngine`，开始菜单有快捷方式）。
2. **建工作区**：例如 `D:\Experiments\MyParadigm`，用 VS Code 打开它。
3. **确认引擎能启动**：开始菜单 → FlyVibingEngine，看到编辑器窗口（状态栏/控制台出现
   `Editor command server on 127.0.0.1:8977` 就是就绪）。

## 2. 把工具链接进你的工作区（三选一）

**A. 最省事：让 CLI 自己装配（推荐）**

```powershell
pip install flyvibing-editor-mcp     # 或从本仓库 wheel/ 安装
engine-editor-cli setup --workspace D:\Experiments\MyParadigm
```

`setup` 会把 agent 技能（skill）与 MCP 配置（`mcp.json`）写进你的工作区。

**B. 用 MCP 客户端手动加**（VS Code / Codex / Claude Code 等）

```json
{ "servers": { "engine-editor-live": { "type": "stdio",
  "command": "engine-editor-mcp", "args": ["--profile", "lite"] } } }
```

**C. 只用命令行的 agent**（不需要 MCP）：把仓库里的
`skills/engine-editor/SKILL.md` 放进工作区（例如 `.github/skills/` 或 `AGENTS.md` 引用它），
agent 会自动知道怎么用 `engine-editor-cli`。

> 三种方式可以叠加。核心是：**让 agent 知道"有一台在跑的编辑器可以被命令行/MCP 操作"**。

## 3. 给 agent 说需求

打开引擎（保持运行），在工作区里对 agent 这样说就够了 —— 例如：

> "我要做一个左右手运动想象的实验范式：左右两种提示随机出现各 30 次，每次提示显示 2 秒、
> 间隔 4 秒。请用引擎搭好场景与节点图，跑起来给我看，然后导出设计工程和成品到我这个工作区。"

agent 会自己完成：读规则 → 在编辑器里建实体/节点图 → 起 PIE 预览/截图 → 保存工程 → 导出。

## 4. 你会得到什么

```
D:\Experiments\MyParadigm\
├── micue/                     ← 导出 ①：实验设计（可选名字）
│   ├── MyParadigm.myproj
│   └── scenes\*.scene
└── rst/                        ← 导出 ②：成品（含 runtime）
    ├── MyParadigm.myproj
    ├── scenes\*.scene
    ├── run_game.cmd            ← 双击即被试跑
    └── output\                 ← 实验数据落这里
```

- **设计包**（`project/`）：小、可进 git、换机器只要重新导出；改实验就改它。
- **成品包**（`rst/`）：自带 Python 运行时与全部依赖，**目标是"拷到实验机双击就能跑"**，
  不需要对方装任何环境。

导出仍用同一个编辑器：**File ▸ Export**，或让 agent 调 `project.export`。

## 5. 一台机器换另一台（设备/端口）

实验常要接设备（串口、脑电）。设计里**不要写死 `COM3`**，写**逻辑设备名** `@mibox`：

1. 新机器上插好设备，打开引擎 → 扩展 **Device (Serial/Parallel)** 面板 → Device names 段 →
   选当前端口 → **Bind current port**（名字填 `mibox`）。
2. 场景里 `@mibox` 自动生效；没绑定时引擎会**明确报错并告诉你怎么绑**（不会静默发错端口）。

## 6. 常见问题

| 症状 | 原因 / 怎么办 |
|---|---|
| agent 说"编辑器未运行" | 先启动引擎；确认控制台有 `127.0.0.1:8977` |
| `engine-editor-cli` 找不到命令 | 没装 wheel：`pip install flyvibing-editor-mcp`（或把 `packages/editor-mcp` 的 wheel 装上） |
| agent 不认得这些命令 | skill 没进工作区：跑一次 `engine-editor-cli setup --workspace <你的工作区>` |
| 导出的成品在别的机器打不开设备 | 那台机器没绑定逻辑设备名（见 §5） |
| 端口 8977 被占 | 设 `FVE_EDITOR_MCP_PORT=<别的端口>`，重启引擎与客户端 |

## 7. 想改引擎/写扩展？

那是另一条路（源码开发）：需要 Python 环境与 uv，见引擎仓库的开发者快速开始与本仓库的
`packages/extension-kit/README.md`（扩展审查 + 无头测试）。**普通做实验不需要这一步。**

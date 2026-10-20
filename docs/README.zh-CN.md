# FlyVibing Utils

**语言：** [English](../README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)

FlyVibing Utils 是 [FlyVibingEngine](https://github.com/LeyeFang/MyGameEngine-Python) 的创作与自动化工具链。它提供一组独立 Python 包，用于控制正在运行的编辑器、离线设计节点图以及校验扩展，无需修改引擎源码。

> 初次使用？[端到端教学](TUTORIAL.md)覆盖从空工作区、引擎准备、节点图编排到导出的完整流程。

## 包

| 包 | 入口 | 用途 | 需要编辑器运行 |
|---|---|---|---|
| **`editor-mcp`** | `engine-editor-cli`、`engine-editor-mcp` | 通过 CLI 与 MCP 服务端实时控制编辑器。 | 是 |
| **`node-editor`** | `flyvibing-node-editor` | 离线完成节点图编排、校验与场景注入。 | 否 |
| **`extension-kit`** | `flyvibing-review` | 扩展静态审查与无头 ImGui 测试。 | 否 |

`skills/` 目录包含 `engine-editor` 与 `node-graph` 技能的源文件。构建时它们分别同步进 `editor-mcp` 与 `node-editor` 包。`engine-editor-cli setup` 安装 `engine-editor` 技能与 MCP 配置；`node-graph` 技能随 `node-editor` 包分发。

## 环境要求

- 全部工具需要 Python 3.10 或更新版本。
- 实时操作需要 FlyVibingEngine 编辑器正在运行。离线构图与扩展审查不要求引擎运行。
- 使用 `node-editor` 的校验能力时，引擎源码需位于 `PYTHONPATH` 上，因为校验复用引擎的节点注册表与图约束。详见 [`packages/node-editor/README.md`](../packages/node-editor/README.md)。

## 安装

在仓库根目录执行：

```powershell
pip install -e packages/editor-mcp
pip install -e packages/node-editor
pip install -e packages/extension-kit
```

也可以在本地构建 wheel：

```powershell
python scripts/build_tools.py
```

该命令会把 skills 同步进 `editor-mcp` 与 `node-editor`，构建三个 wheel，并把校验和写入 `dist/CHECKSUMS.sha256`。

## 快速开始

### 实时控制编辑器

启动编辑器，并确认命令服务器就绪（控制台输出 `[Live] Editor command server on 127.0.0.1:8977`）。

```powershell
engine-editor-cli ops
engine-editor-cli call sim.state
engine-editor-cli call entity.add name=Cue
engine-editor-cli validate
engine-editor-cli capture pie --out frame.png
```

在工作区中注册 MCP 服务与 skills：

```powershell
engine-editor-cli setup --workspace C:\path\to\project
```

手动配置 MCP：

```json
{
  "servers": {
    "engine-editor-live": {
      "type": "stdio",
      "command": "engine-editor-mcp",
      "args": ["--profile", "lite"]
    }
  }
}
```

lite 档暴露 5 个工具（`engine_help`、`engine_call`、`engine_batch`、`engine_validate_graph`、`engine_capture`）。full 档保留旧的 44 工具接口。

### 离线编排节点图

以下示例假设工程中存在 `scenes/main.scene`、`spec.json` 与 `ops.json`，请替换为实际文件。

```powershell
flyvibing-node-editor rules
flyvibing-node-editor entities scenes/main.scene
flyvibing-node-editor build --spec spec.json --out graph.json
flyvibing-node-editor apply --scene scenes/main.scene --graph graph.json
flyvibing-node-editor flow --scene scenes/main.scene --event OnFrameUpdate
flyvibing-node-editor pins TimeTrigger
```

校验与引擎使用同一实现：

```powershell
python -m flyvibing_node_editor.node_graph_validator scenes/main.scene --frames 360
```

增量编辑通过 `apply-ops` 完成：

```powershell
flyvibing-node-editor apply-ops --scene scenes/main.scene --ops ops.json          # 干跑
flyvibing-node-editor apply-ops --scene scenes/main.scene --ops ops.json --write  # 校验通过后写入
```

### 扩展审查

在引擎仓库根目录执行：

```powershell
flyvibing-review Application/Functions/SerialParallelDevice
flyvibing-review --all
```

退出码 0 表示无失败项；退出码 1 表示存在失败项，可直接用于 CI。

## 设计边界

节点图行为只有一套实现、一个规则来源：

| 关注点 | 离线 `node-editor` | 实时 `editor-mcp` |
|---|---|---|
| 建图 | spec → 图 JSON（可复现、可进版本库） | 导入图 JSON 并进行交互式微调 |
| 校验 | 无头调用引擎实现 | 编辑器内的 `graph.validate.*` 服务 |
| 场景写入 | 直接读写 `.scene` 文件（CI、批量、无 GUI） | 只修改活动场景，不直接写场景文件 |

- 设计期与批量任务使用离线工具；运行期与交互式任务使用实时工具。
- 直接写 `.scene` 仅允许出现在离线侧，避免与正在运行的编辑器并发写入。
- `rules.md` 是规则参考；校验逻辑与引擎共享，不在工具中重复实现。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `packages/editor-mcp/` | 实时编辑器控制的 CLI 与 MCP 服务端 |
| `packages/node-editor/` | 离线图构建、校验、执行流分析与 MCP 服务端 |
| `packages/extension-kit/` | 扩展审查器与无头 ImGui 工具 |
| `skills/` | `engine-editor` 与 `node-graph` 技能的源文件，构建时同步进打包副本 |
| `scripts/` | 构建与文档同步脚本 |
| `docs/` | 教学文档与本地化文档 |

## 开发

```powershell
python scripts/build_tools.py           # 同步 skills、构建 wheel、写入校验和
python scripts/build_tools.py --no-sync # 只构建
```

技能源文件位于 `skills/`；`packages/*/.../skills/` 下的副本由构建过程生成。

路线图：`sdk/` 将提供扩展类型存根（`ExtensionBase`/`ExtensionContext`）与模板。

`extension-kit` 与 `node-editor` 都不导入编辑器内部模块。`node-editor` 的校验复用引擎的 `Application.Core.NodeGraph`，以避免规则漂移；独立分发的处理方式见 [`packages/node-editor/README.md`](../packages/node-editor/README.md)。

## 相关仓库

| 仓库 | 范围 |
|---|---|
| [**MyGameEngine-Python**](https://github.com/LeyeFang/MyGameEngine-Python) | 引擎、编辑器、运行时、内置模块与引擎研发工具 |
| **FlyVibing-User-And-Developer-Utils**（本仓库） | 面向引擎工程的创作与自动化工具链 |

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/TUTORIAL.md`](TUTORIAL.md) | 端到端流程：从空工作区到设计工程与可运行成品 |
| [`packages/editor-mcp/README.md`](../packages/editor-mcp/README.md) | CLI/MCP 档位、操作、环境变量与抓帧行为 |
| [`packages/node-editor/README.md`](../packages/node-editor/README.md) | 离线图工作流、增量编辑、别名与节点组 |
| [`packages/extension-kit/README.md`](../packages/extension-kit/README.md) | 静态审查规则与无头 ImGui 测试 |
| 引擎仓库 `Doc/Dev/` | 实时协议、节点图协议与校验协议 |

## 贡献

欢迎提交 Issue 与 Pull Request。节点规则变更必须同步更新 `rules.md`、校验器与引擎侧适配器。

## 许可证

[MIT](../LICENSE) © 2026 Leye Fang

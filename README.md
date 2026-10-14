# FlyVibing User & Developer Utils

**引擎"使用侧"工具链** —— 给实验设计者（用户）、扩展开发者，以及**引擎团队自己**日常干活用。
引擎研发侧（环境/测试/打包/安装器）不在这里，那部分留在引擎仓库 `Utils/Dev`。

> 一句话分工：**引擎仓库 = 造引擎；本仓库 = 用引擎。**

## 内容

| 目录 | 是什么 | 前提 |
|---|---|---|
| `packages/editor-mcp/` | **编辑器实时控制**（MCP + CLI，回环 127.0.0.1:8977）。实体/组件/节点图/PIE/截图/导出… 所有操作与人工点击等价 | **编辑器在运行** |
| `packages/node-editor/` | **离线节点图工具**：实验 spec → 图 JSON → 注入 `.scene`；`rules.md` 分节规则参考（agent 省上下文） | **不需要引擎运行** |
| `packages/extension-kit/` | **扩展作者工具包**：`review_extension.py`（提交前静态审查）+ `imgui_headless.py`（无头 GUI 测试唯一入口，自带禁 ini） | 无 |
| `skills/` | agent 技能权威源（`engine-editor` / `node-graph`）—— 随 wheel 打包，`engine-editor-cli setup` 装配进任意工作区 | 无 |
| `sdk/` | `[计划]` 类型存根（`ExtensionBase`/`ExtensionContext`）+ 扩展模板 | 无 |

## 职责边界（防重复的硬规则）

**图（node graph）这件事，两个入口、一套实现：**

| 能力 | 实时侧 `editor-mcp` | 离线侧 `node-editor` |
|---|---|---|
| 建图 | 导入图 JSON + 交互微调（`graph.*`） | **spec → 图 JSON**（可复现、可进版本库） |
| 校验 | 引擎内服务 `graph.validate.*` | 无头调用**同一个**引擎实现 |
| 场景写入 | 只改"活场景" | 直接读写 `.scene` 文件（CI / 批量 / 无 GUI） |
| 规则参考 | — | `rules.md`（唯一权威，分节读取） |

1. **校验/规则实现永远只有一份**（引擎侧 `Application.Core.NodeGraph.validation` + 本仓 `rules.md`）；
   两个工具都只是"怎么调到它"。工具里**不许**出现第二套校验规则。
2. **建图分工**：设计期/离线/批量 → `node-editor`；运行期/交互/所见即所得 → `editor-mcp`。
3. **直接写 `.scene` 文件**只允许在离线侧（运行中的场景改动必须走实时通道，避免双写）。

一句话：**离线设计 → node-editor；运行交互 → editor-mcp；校验实现 → 引擎（唯一）。**

## 安装

```powershell
# 三个包（开发态用 -e；用户态用 wheel）
pip install -e packages/editor-mcp
pip install -e packages/node-editor
pip install -e packages/extension-kit
```

常用入口：

```powershell
engine-editor-cli call sim.state        # 实时通道（编辑器需在运行）
flyvibing-node-editor rules             # 离线：规则目录（按节读）
flyvibing-review <扩展目录> --all        # 扩展审查
python -m flyvibing_extension_kit.imgui_headless   # 无头 GUI 测试入口（库）
```

## 依赖与边界（重要）

- `node-editor` 的**校验**复用引擎实现（`Application.Core.NodeGraph`），因为"两套规则迟早漂移"。
  独立分发时按优先级：① 随包带上无头 NodeGraph；② 校验降级为"调用运行中的引擎"。
  这件事写在 `packages/node-editor/README.md` 的「依赖与边界」一节，改动前先读。
- `editor-mcp` 只经 TCP 回环与编辑器通信，**不 import 引擎内部**。
- `extension-kit` 纯静态 + imgui 库，**不 import 引擎内部**（reviewer 只做 AST 扫描）。

## 与引擎仓库的关系

- 引擎仓库 `Utils/Dev` = 引擎研发工具（环境/测试/打包/安装器）；`Utils/User` = 随成品分发的运行时辅助（`player.bat`）。
- 引擎侧 agent 用到的 skills 以**本仓 `skills/` 为权威源**，由 `scripts/build_tools.py` 同步/打包。
- 引擎的回归测试需要这些工具时，直接使用本仓（引擎 dev 环境按 `-e` 安装即"假装我们是用户"）。

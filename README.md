# FlyVibing Utils

给**引擎使用者**的工具箱 —— 不用改引擎源码，就能让 agent 替你搭实验、盯设备、发数据、审扩展。

引擎本身（渲染器、编辑器、运行时）在另一个仓库：[MyGameEngine-Python](https://github.com/LeyeFang/MyGameEngine-Python)；
本仓库只放"怎么把引擎用好"的东西。

## 三个工具

| 工具 | 解决什么 | 什么时候用 | 需要编辑器在跑吗 |
|---|---|---|---|
| **`editor-mcp`** | 让 agent **实时操作编辑器**：加实体/改组件/连节点图/启停 PIE/截图/导出工程。所有操作 = 人工点击 | 调实验、试运行、批量改场景 | ✅ 需要（回环 TCP） |
| **`node-editor`** | **离线**把"实验 spec"变成节点图并写进 `.scene`；附 `rules.md` 规则参考。可在 CI、无 GPU 机器、批量场景上用 | 设计期、版本库里的可复现实验设计 | ❌ 不需要 |
| **`extension-kit`** | 写扩展时自检：`review_extension.py` 静态审查（提交前必跑），`imgui_headless.py` 无头 GUI 测试入口（自带禁用 ini） | 开发/提交扩展 | ❌ 不需要 |

`skills/` 是 agent 技能（`engine-editor` / `node-graph`），随 wheel 打包，由 `engine-editor-cli setup` 装配到你的工作区。

## 安装

```powershell
pip install -e packages/editor-mcp
pip install -e packages/node-editor
pip install -e packages/extension-kit
```

## 三个常见任务

```powershell
# ① 让 agent 在运行中的编辑器里干活（CLI 零常驻上下文；也可用 MCP）
engine-editor-cli call sim.state
engine-editor-cli call entity.add name=Cue
engine-editor-cli setup --workspace C:\my-experiment      # 装配 skill + MCP 配置

# ② 离线设计一个实验范式，产出可进版本库的节点图
flyvibing-node-editor rules                  # 规则目录（按节读，省上下文）
flyvibing-node-editor build --spec spec.json --out graph.json
flyvibing-node-editor apply --scene scenes/main.scene --graph graph.json

# ③ 交扩展前自检（0 fail 才算过）
flyvibing-review Functions/MyExtension
```

## 边界：同一件事只做一遍

**图（node graph）有两个入口，一套实现**（校验规则永远只有引擎里那一份）：

| | 离线 `node-editor` | 实时 `editor-mcp` |
|---|---|---|
| 建图 | spec → 图 JSON（可复现、进版本库） | 导入图 JSON + 交互微调 |
| 校验 | 无头调用引擎同一实现 | 引擎内服务 `graph.validate.*` |
| 场景写入 | 直接读写 `.scene`（CI / 批量 / 无 GUI） | 只改"活场景"（不直接写文件） |

- 设计期/批量 → 离线工具；运行期/所见即所得 → 实时工具。
- 直接写 `.scene` 文件只允许出现在离线侧（运行中的场景改动必须走实时通道，避免双写）。
- 工具里不实现第二套节点规则：`rules.md` 是文档权威，校验实现来自引擎源码。

## 给维护者

```powershell
python scripts/build_tools.py      # 同步 skills/ 进各包 → 构建 3 个 wheel → 写 CHECKSUMS.sha256
python scripts/build_tools.py --no-sync    # 只构建
```

- `skills/` 是 agent 技能的唯一权威源；`packages/*/.../skills/**` 是构建期同步进去的负载（不要手改）。
- `extension-kit` 与 `node-editor` 都**不 import 引擎编辑器内部**；`node-editor` 的校验复用引擎
  `Application.Core.NodeGraph`（避免两套规则漂移），独立分发时的处理方式见
  `packages/node-editor/README.md` 的「依赖与边界」。
- 计划中：`sdk/`（`ExtensionBase`/`ExtensionContext` 类型存根 + 扩展模板）。

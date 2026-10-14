# NodeEditor — 离线节点图工具（不需要引擎运行）

实验设计者（或其 agent）用它把"实验 spec"变成引擎 `.scene` 里的节点图，并在注入前干跑校验。

## 用法

```powershell
# CLI（终端首选，零常驻上下文）
python -m flyvibing_node_editor.cli rules            # 规则目录（按节读，省上下文）
python -m flyvibing_node_editor.cli entities <scene> # 列场景实体
python -m flyvibing_node_editor.cli build  <spec.json> --out graph.json
python -m flyvibing_node_editor.cli apply  <scene> graph.json
```

同一能力经 MCP 暴露（`node-graph-editor`：`get_rules` / `get_scene_entities` / `build_graph` / `apply_graph`）；
装法见 `install_mcp.py`（或 `install_mcp.bat`）。

## 文件

| 文件 | 作用 |
|---|---|
| `cli.py` | 命令行入口（上述四个子命令） |
| `rule_sections.py` + `rules.md` | 节点图规则参考（**按节读取**，避免一次性灌满上下文） |
| `spec_builder.py` | 实验 spec → 节点图（trial 计时器/相位/分支/触发编码） |
| `graph_builder.py` | 节点图数据结构与连线 |
| `node_graph_validator.py` | 干跑校验（静态检查 + 固定时间步模拟）——依赖 `Application.Core.NodeGraph`（见下） |
| `apply_graph.py` | 把图注入 `.scene` |
| `mcp_server.py` | MCP 服务端（stdio） |
| `test_smoke.py` | 冒烟自测 |

## 依赖与边界

**图校验实现唯一**：本工具不实现规则，只调用引擎侧 `Application.Core.NodeGraph.validation`
（静态检查 + 固定时间步模拟）。原因：两套规则迟早漂移（历史上已经走过一次弯路）。
因此独立安装后，"校验"功能需要引擎源码在 `PYTHONPATH` 上；`build` / `apply` / `entities` / `rules`
四个能力**完全不依赖引擎**。

**独立分发前必须二选一**：① 随包带上无头 NodeGraph；② 校验降级为"调用运行中的引擎"。
（规划见引擎仓库 `Doc/Dev/ecosystem_plan.md`。）

**与实时工具的分工**（不要两边各做一遍）：

| | 本工具（离线） | `editor-mcp`（实时） |
|---|---|---|
| 前提 | 不需要引擎运行 | 编辑器在运行 |
| 建图 | **spec → 图 JSON**（可复现、进版本库） | 导入图 JSON + 交互微调 |
| 校验 | 无头调用同一实现 | 引擎内服务 `graph.validate.*` |
| 场景 | 直接读写 `.scene`（CI / 批量 / 无 GUI） | 只改活场景 |

- 规则参考权威 = 本包 `rules.md`（分节读取）；改造规则请连同引擎侧校验实现一起改。
- 直接写 `.scene` 文件**只允许出现在离线侧**（运行中的场景改动必须走实时通道，避免双写）。

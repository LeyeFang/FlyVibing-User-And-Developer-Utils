# NodeEditor — 离线节点图工具（不需要引擎运行）

实验设计者（或其 agent）用它把"实验 spec"变成引擎 `.scene` 里的节点图，并在注入前干跑校验。

## 用法

```powershell
# CLI（终端首选，零常驻上下文）
python -m flyvibing_node_editor.cli rules            # 规则目录（按节读，省上下文）
python -m flyvibing_node_editor.cli entities <scene> # 列场景实体
python -m flyvibing_node_editor.cli build  <spec.json> --out graph.json
python -m flyvibing_node_editor.cli apply  <scene> graph.json
python -m flyvibing_node_editor.cli flow   <scene> --event OnFrameUpdate   # 静态执行流（不跑引擎）
python -m flyvibing_node_editor.cli pins   TimeTrigger                     # 节点 pin 契约
python -m flyvibing_node_editor.cli find   --scene <scene> --type Constant --prop value=60  # 定位节点
python -m flyvibing_node_editor.cli apply-ops --scene <scene> --ops ops.json [--write]        # 增量改图（默认 dry-run）
```

同一能力经 MCP 暴露（`node-graph-editor`：`get_rules` / `get_scene_entities` / `build_graph` / `apply_graph`）；
装法见 `install_mcp.py`（或 `install_mcp.bat`）。

## 文件

| 文件 | 作用 |
|---|---|
| `cli.py` | 命令行入口（rules / entities / build / apply / flow / pins / find） |
| `rule_sections.py` + `rules.md` | 节点图规则参考（**按节读取**，避免一次性灌满上下文） |
| `spec_builder.py` | 实验 spec → 节点图（trial 计时器/相位/分支/触发编码） |
| `graph_builder.py` | 节点图数据结构与连线 |
| `node_graph_validator.py` | **校验唯一实现**：L1 规则（`check_graph`）+ 兼容入口 `validate_static`；L2 干跑委托引擎 `validation.dry_run` |
| `graph_flow.py` | **静态执行流（V1）**：不执行引擎，输出“从某事件出发的真实执行顺序”（含 Branch 分支、TimeTrigger 门控、环检测） |
| `apply_graph.py` | 把图注入 `.scene` |
| `ops.py` | **增量编辑**（link / unlink / set_props / add_node / remove_node），供 `apply-ops` 与分步 agent 使用 |
| `mcp_server.py` | MCP 服务端（stdio） |
| `test_smoke.py` | 冒烟自测 |

## 校验（离线，与在线同源）

```powershell
python -m flyvibing_node_editor.node_graph_validator <scene.scene>               # L1 静态
python -m flyvibing_node_editor.node_graph_validator <scene.scene> --frames 360  # + L2 干跑
```

## 执行流（静态，不跑引擎）

```powershell
python -m flyvibing_node_editor.cli flow --scene <scene.scene>                    # 默认从 OnFrameUpdate 出发
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --event OnGameStart --data
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --from 229 --max-lines 40  # 只看一条链
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --from 281 --data --data-depth 3  # 看参数来源
```

加 `--data` 时，数据输入会以 `~ <pin> <- #id Type.<pin> <值提示>` 递归展开（如
`~ B <- #280 Constant.Result value=60`）—— 要改参数就改那个来源节点。
构图前若不确定 pin 名，用 `pins <TypeName>` 查（含方向、数据类型、`optional` 标记）；
定位某类/某值的节点用 `find --scene ... [--type T] [--prop K=V]`。

## 增量改图（agent 分步）

```powershell
python -m flyvibing_node_editor.cli apply-ops --scene <scene> --ops ops.json          # dry-run + L1 校验
python -m flyvibing_node_editor.cli apply-ops --scene <scene> --ops ops.json --write  # 校验通过后落盘
```

ops 与 bench 的 patch DSL 同语义：

```json
{"ops": [
  {"op": "unlink",    "from": ["#232", "out_0"], "to": ["#273", "exec_in"]},
  {"op": "add_node",  "type": "PrintString", "props": {"message": "trial_end"}, "as": "ps"},
  {"op": "link",      "from": ["#232", "out_0"], "to": ["ps", "exec_in"]},
  {"op": "set_props", "node": "#280", "props": {"value": 30}},
  {"op": "remove_node", "node": "ps"}
]}
```

默认不写文件；`ok=false` 时返回 `op_errors` + `validation_errors`，可直接喂给下一轮模型。

回答“这么连会什么顺序”：`Branch` 两路标出条件来源、`TimeTrigger`/`TimeDelay` 标 `[GATE]`、
`ExitGame` 标 `[TERMINAL]`、环标 `[CYCLE]`；行输出有预算上限，保证不会一把塞满上下文。

## 依赖与边界

**图校验实现唯一 —— 就在本仓库**：`node_graph_validator.check_graph` 是 L1 规则唯一实现，
引擎侧 `Application/Core/NodeGraph/validation/checks.py` 只是薄适配器（在线 Validate 按钮 /
`graph.validate.*` / `PlayerEntry --dry-run` 都走它）。历史上两套规则漂移过一次，因此规则只留一份：
改规则改这里，离线与在线同时生效。

L2 干跑复用引擎求值器（`validation.dry_run.run_dry_run`），离线 `dry_run_simulation` 是它的
薄包装 —— 同样只有一份实现。

因此：`build` / `apply` / `entities` / `rules` **完全不依赖引擎**；校验的 L1 需要引擎的节点类型
注册表与图约束（`Application.Core.NodeGraph`），L2 还需要求值器 —— 即需要引擎源码在
`PYTHONPATH` 上（引擎仓库内直接可用；导出游戏包会随运行时镜像带上本包）。

**独立分发前**：① 随包带上无头 NodeGraph（类型注册表 + 图约束 + 求值器），或 ② 校验降级为
“调用运行中的引擎”。（规划见引擎仓库 `Doc/Dev/ecosystem_plan.md`。）

**与实时工具的分工**（不要两边各做一遍）：

| | 本工具（离线） | `editor-mcp`（实时） |
|---|---|---|
| 前提 | 不需要引擎运行 | 编辑器在运行 |
| 建图 | **spec → 图 JSON**（可复现、进版本库） | 导入图 JSON + 交互微调 |
| 校验 | 无头调用同一实现 | 引擎内服务 `graph.validate.*` |
| 场景 | 直接读写 `.scene`（CI / 批量 / 无 GUI） | 只改活场景 |

- 规则参考权威 = 本包 `rules.md`（分节读取）；改造规则请连同引擎侧校验实现一起改。
- 直接写 `.scene` 文件**只允许出现在离线侧**（运行中的场景改动必须走实时通道，避免双写）。

---
name: node-graph
description: "构建/修改 .scene 里的实验节点图（离线通道 — 不需要引擎运行）: 按节读规则、实验 spec→节点图（build_graph）、注入 .scene（apply）、离线校验（node_graph_validator，与在线同一实现）。★ 节点图是场景可运行的必要条件：编辑器实体只是模板，不建图则 PIE/成品内什么都不渲染。Use when the user asks to generate or edit experiment node graphs from a spec, wire trials/cues/triggers, or apply a graph JSON into a scene file. 实时编辑/截图请用 engine-editor skill。通道: python -m flyvibing_node_editor.cli（终端首选）或 node-graph-editor MCP（get_rules/get_scene_entities/build_graph/apply_graph）。"
---

# Node Graph 离线构建（MyGameEngine）

从**实验描述 spec** 生成节点图并写入 `.scene`；或按节查阅节点参考。与引擎运行状态无关。
（引擎运行时的实时编辑/校验/截图 → 用 `engine-editor` skill。）

> ★ **节点图是场景可运行的必要条件**（不是可选装饰）：编辑器里的实体只是模板，
> PIE / 导出成品只渲染与执行节点图生成的内容 —— 不建图 = 运行时（几乎）什么都看不到。
> 最低配: `OnGameStart → EntitySpawn(template=<实体名>)`。
> 完成建图后必须过引擎校验（见 §2 末尾），有实体但无图的情况 `sim.play` 会返回 warning 提醒。

## 0. 通道选择

| 通道 | 常驻成本 | 何时用 |
|---|---|---|
| `python -m flyvibing_node_editor.cli`（终端） | **0** | 默认首选（任意终端型 agent） |
| MCP `node-graph-editor`（4 工具） | ~1.5k 字符 schema | 无终端的环境 |

相对路径均基于**引擎仓库根**（部署副本里 = 项目根）。

## 1. 规则查询（渐进披露 — 别拉全文）

```powershell
python -m flyvibing_node_editor.cli rules                # 目录（各节标题+规模）— 先看这个
python -m flyvibing_node_editor.cli rules "Connection Rules"
python -m flyvibing_node_editor.cli rules "SigGen"       # 子标题可单独取
python -m flyvibing_node_editor.cli rules "build_graph Spec"
python -m flyvibing_node_editor.cli rules --all --out rules_full.md   # 只在真需要全文时（落盘+摘要）
```

MCP 等价: `get_rules()`（目录）/ `get_rules(section="SigGen")` / `get_rules(section="all")`。

## 2. spec → 图 → scene（一条龙）

```powershell
python -m flyvibing_node_editor.cli build --spec spec.json --out graph.json   # 只回摘要
python -m flyvibing_node_editor.cli apply --scene scenes/My.scene --graph graph.json
```

spec 字段/示例见 `rules "build_graph Spec"`。要点:

- `phases[]`: `cue_pick`（随机分支+显隐+并行口触发）/ `action|show` / `trial_end`；
- `pulse`（可选）: 50ms 发送循环（count/interval/parallel_addr/serial_port/encode）；
- `entities[]` 先 spawn 后统一隐藏；seed 链固定挂 OnGameStart。

**校验（必做）**: 先过离线 L1（不需引擎）——
`python -m flyvibing_node_editor.node_graph_validator <scene.scene>`（加 `--frames 360` 连干跑），
与在线 `graph.validate.*` 是**同一实现**。引擎已启动时也可用
`engine-editor-cli validate --source graph --graph @graph.json`（或 MCP `engine_validate_graph`），
零告警再交付；无头环境用 `PlayerEntry --dry-run`。

**看不懂图的执行顺序时**: `python -m flyvibing_node_editor.cli flow --scene <scene>` —— 纯静态、
不跑引擎，输出从事件节点出发的执行链（Branch 标条件来源、TimeTrigger 标 `[GATE]`、环标 `[CYCLE]`）。
用 `--from <节点id>` 只看关心的那条链；加 `--data` 显示数据输入来源
（`~ B <- #280 Constant.Result value=60`，改参数就改这个来源），`--data-depth 2` 可再展开一层。

**改现有图（增量，不必重生成）**:

```powershell
python -m flyvibing_node_editor.cli find --scene <scene> --type Constant --prop value=60  # 定位
python -m flyvibing_node_editor.cli pins TimeTrigger                                   # 查 pin 名
python -m flyvibing_node_editor.cli apply-ops --scene <scene> --ops ops.json           # dry-run + L1
python -m flyvibing_node_editor.cli apply-ops --scene <scene> --ops ops.json --write   # 落盘
```

ops: `link` / `unlink` / `set_props` / `add_node` / `remove_node`；节点可写 `#id`、唯一类型名或 `add_node` 的 `as` 别名。
改参数前先用 `flow --data` 确认来源节点，别改下游。

## 3. 场景实体查询

```powershell
python -m flyvibing_node_editor.cli entities scenes/My.scene
```

MCP: `get_scene_entities(scene_path)`。

## 4. Token 纪律

- 规则文档**永远先看目录**、按节取；不要把 `--all` 全文或整图 JSON 打印进上下文。
- `build --out` / `rules --out` 落盘 + 摘要回读；需要检查内容时只读关心的片段。
- 多步（build→apply→validate）在同一条命令链里完成，避免多次往返。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| `unknown section` | 先跑无参 `rules` 看准确标题（支持子标题模糊匹配） |
| spec 构建报 KeyError | 对照 `rules "build_graph Spec"` 的字段表检查拼写 |
| apply 后图没生效 | 确认写入的是当前工程加载的 .scene（引擎需重新加载/打开） |
| 校验报错 | 用引擎内 validate 的 summary 定位 node_id → `rules` 查该节点类型规则 |

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
python -m flyvibing_node_editor.cli find   --scene <scene> --alias trial_end                # 按别名定位
python -m flyvibing_node_editor.cli groups                                # 内置组模板
python -m flyvibing_node_editor.cli groups --scene <scene>                # 场景内组实例
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
| `ops.py` | **增量编辑**（link / unlink / set_props / add_node / remove_node / set_alias / set_description / add_group / set_group），供 `apply-ops` 与分步 agent 使用 |
| `node_groups.py` | **节点组**：模板注册（`cue_n_way` / `cue_window` / `hide_group` / `container` / `mi_select` / `phase0_trigger` / `sss_pulse`）、扁平展开、按 arm 差分重展开 |
| `mcp_server.py` | MCP 服务端（stdio） |
| `test_smoke.py` | 冒烟自测 |
| `test_aliases_groups.py` | 别名 + 节点组（cue_n_way / cue_window / hide_group / container / mi_select / phase0_trigger / sss_pulse）自测 |

## 校验（离线，与在线同源）

```powershell
python -m flyvibing_node_editor.node_graph_validator <scene.scene>               # L1 静态
python -m flyvibing_node_editor.node_graph_validator <scene.scene> --frames 360  # + L2 干跑 (默认 dt=1/60)
python -m flyvibing_node_editor.node_graph_validator <scene.scene> --seconds 32 --dt 0.004166667  # 绝对时长 @240Hz
```

`--seconds` 只是把绝对时长换算成 `ceil(seconds/dt)` 帧；L2 本身是确定性 fake-time，
不会等待真实时间。要验证 240 Hz 逻辑线程下的 20 Hz 脉冲，必须显式传
`--dt 0.0041666667`（或 `--frames 帧数`），否则默认按 60 Hz 模拟。
干跑的日志按 `frame` 记录，绝对时间 = `frame * dt`；需要“跑满一个 trial / 两个 trial”
时应按 `trial_phase` 的 0/2/6/10 s 设计断言，而不是只看固定帧数。

## 执行流（静态，不跑引擎）

```powershell
python -m flyvibing_node_editor.cli flow --scene <scene.scene>                    # 默认从 OnFrameUpdate 出发
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --event OnGameStart --data
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --from 229 --max-lines 40  # 只看一条链
python -m flyvibing_node_editor.cli flow --scene <scene.scene> --from 281 --data --data-depth 3  # 看参数来源
```

加 `--data` 时，数据输入会以 `~ <pin> <- #id Type.<pin> <值提示>` 递归展开（如
`~ B <- #280 Constant.Result value=60`）—— 要改参数就改那个来源节点。
组边界会标 `[group @alias IN]` / `[group @alias OUT]`（`cue_window` 的单进单出）。
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

## 节点别名

`nodes[nid].alias` 是节点的人可读名字（类似变量名 vs 地址）：不影响运行时，只影响 flow、搜索与 ops 引用。

```json
{"ops": [
  {"op": "set_alias", "node": "#232", "alias": "trial_end"},
  {"op": "add_node", "type": "Constant", "props": {"value": 30}, "alias": "cue_dur"},
  {"op": "set_props", "node": "@trial_end", "props": {"time": 12}}
]}
```

- 格式 `[A-Za-z_][A-Za-z0-9_]*`；大小写无关唯一（`duplicate_alias`）。
- `add_node` 的 `as` 仍是**批次内**临时符号；`alias` 才是写进场景的持久名。
- flow 输出 `#232@trial_end TimeTrigger ...`。

## 节点描述

`nodes[nid].description` 是可自由书写的人/agent 说明（意图、输入输出、范式含义）：
不影响运行时；编辑器节点卡可展开/收起并直接编辑，MCP/CLI 可读写。

```json
{"ops": [
  {"op": "add_node", "type": "Constant", "props": {"value": 30},
   "alias": "cue_dur", "description": "Cue duration in seconds."},
  {"op": "set_description", "node": "@cue_dur",
   "description": "Cue is visible from 0 s to this duration."}
]}
```

- 空串或省略 `description` = 清除；`find` / `graph.list` 会返回描述字段。
- 节点组展开时自动为决策/取实体/显隐/发送节点写入描述，便于阅读。

## 节点组（宏）

组是“宏”：插入时展开成普通 nodes/links，`node_groups` 只是元数据（引擎不透明保留、不求值，
`graph.export` / 场景保存会原样带回）。

```json
{"ops": [
  {"op": "add_group", "group_type": "cue_n_way", "alias": "cue_rand",
   "params": {"addr": 16376, "arms": [
     {"id": "left",  "entities": ["LeftCue", "arrow_body", "arrow_head_copy"], "code": 3},
     {"id": "right", "entity": "RightCue", "code": 4}]}},
  {"op": "link", "from": ["#229", "out_0"], "to": ["@cue_rand", "entry"]}
]}
```

`cue_n_way` 展开：`Random(discrete 1..N)` → N×( `Constant(i)→Compare(eq)→Branch` )；
每个 arm 的 `Branch.True` → `EntityGet`（1 个或多个）→（多实体时 `EntityPack`/`EntityListMerge`
→ `EntityListSetVisible`；单实体时 `EntitySetRenderVisible`）→
`ParallelSend(mode=pin, address=addr, Value←Constant(code))`。
`entity` 与 `entities` 二选一；实体都按名字在运行时查找（不存编辑器 id）。

**条件随范式增减分支**：不改图、只改参数 —— arm 的 `id` 是稳定键：

```json
{"ops": [
  {"op": "set_group", "group": "@cue_rand",
   "params": {"arms": [
     {"id": "left",  "entities": ["LeftCue", "arrow_body", "arrow_head_copy"], "code": 3},
     {"id": "right", "entity": "RightCue", "code": 4},
     {"id": "top",   "entity": "TopCue", "code": 5}]}}
]}
```

未变 arm 的动作节点 ID 保持不变；增/删只重建决策链与变动 arm，外部接在 `@cue_rand` 入口的连线
自动 remap 到新入口。`groups --scene` 可查组实例、arm 列表与入口 pin。

### cue_window（每帧可见窗口）

`cue_window` 是**每帧求值**的线性组，适合“0–2 s 显示 class cue”这类状态窗口：

```json
{"ops": [
  {"op": "add_group", "group_type": "cue_window", "alias": "class_cue",
   "params": {"clock": "trial_phase", "start": 0, "end": 2, "entity": "TaskCue"}},
  {"op": "link", "from": ["#163", "exec"], "to": ["@class_cue", "entry"]}
]}
```

展开为 `TimeGetElapsed(clock)` → `Compare(gte,start)` + `Compare(lt,end)` →
`Compare(and)` → `EntityGet(entity)` → `EntitySetRenderVisible(Visible=active)`；
每次 `entry` 执行都会写一次可见性，所以窗口外自动写 `false`，组自己完成 enter/exit。
`entry` / `done` 是唯一两个 exec 边界；`done` 是**每帧继续**的普通出口，不是退出事件。
需要“2 s 到点只触发一次”时用独立 `TimeTrigger(timer="trial_phase", time=2)`。
`include_end=true` 改为闭区间；`visible=false` 表示窗口内隐藏。

嵌套组在 `add_group` 加 `"parent": "@外层组"`（只记 `parent/children` 元数据），
执行关系仍用显式连线：

```json
[
  {"op": "link", "from": ["@trial_window", "done"],
   "to": ["@phase_cue", "entry"]}
]
```

`cue_n_way` 与 `cue_window` 都遵循同一规则：同一实体/属性只允许一个组写，重叠窗口必须
在单个组内先算 phase，或显式优先级，不能依赖执行顺序。`set_group` 修改 `cue_window`
参数时会重建组内节点，并自动把外部 `entry` / `done` 连线 remap 到新槽位。

### hide_group

按实体树批量显隐的线性组：

```json
{"op": "add_group", "group_type": "hide_group", "alias": "rest_cue",
 "params": {"entities": ["LeftCue", "RightCue", "NullCue", "TaskCue"],
            "visible": false}}
```

每个根实体走 `EntityGet → EntityGetTree`，多个根经 `EntityListMerge` 合批，最后
`EntityListSetVisible`。通常用 `TimeTrigger` 在 6 s 触发一次。

### mi_select（MI 类别 → 可见 cue 的线性选择组）

```json
{"op": "add_group", "group_type": "mi_select", "alias": "mi_select",
 "params": {"mi_var": "mi_code", "arms": [
   {"id": "left",  "entities": ["L_arrow_body", "L_arrow_head"], "code": 1},
   {"id": "right", "entities": ["R_arrow_head", "R_arrow_body"], "code": 2},
   {"id": "none",  "entities": ["part1", "part2"], "code": 3}]}}
```

展开为 `Random(discrete 1..N) → VarSet(mi_var)`，然后一条**线性 exec 链**：每个 arm
依次 `Constant(code) → Compare(eq)`，再对本 arm 的每个实体 `EntityGet → EntitySetRenderVisible(Visible=Compare)`。
入口是 `VarSet` 的 `exec_in`，出口是最后一个 `EntitySetRenderVisible` 的 `exec_out`；
组内没有 Branch、没有 ExecSelect，只有单写者。**每次 entry 会重新抽一次 Random**，因此应在
phase0 起点调用一次（例如 `TimeTrigger(trial_phase, 0)`），不要接每帧 Update 链。
`arms` 的 `id` 是稳定键；`set_group` 增删 arm 时只重建相关链，外部入口/出口自动 remap。

### phase0_trigger（Phase 0 cue 触发组）

```json
{"op": "add_group", "group_type": "phase0_trigger", "alias": "phase0_trigger",
 "params": {"mi_scale": 32, "address": 16376}}
```

展开为 `VarGet(mi_code) → * mi_scale → + sss_code → VarSet(trigger_val) → ParallelSend`。
入口是 `VarSet(trigger_val).exec_in`，出口是 `ParallelSend.exec_out`；每次 entry 发送一次。
适合放在 cue 稳定后的 OneShot/phase0 逻辑中，不要每帧无条件调用。

### sss_pulse（20 Hz SSSEP 脉冲组）

```json
{"op": "add_group", "group_type": "sss_pulse", "alias": "sss_pulse",
 "params": {"interval": -0.0499, "address": 16376,
            "serial_port": "@SSSEP-Stimulator", "serial_baud": 9600}}
```

每次 entry 做一次脉冲：`VarGet(sss_code)` 同时送 `ParallelSend` 与 `SerialSend`，
然后 `pulse_count += 1`，最后 `SetTimer(pulse, interval)` 重装定时器。
入口是 `ParallelSend.exec_in`，出口是 `SetTimer.exec_out`；组本身不判断 20 Hz 窗口与脉冲上限，
这些前置条件由外层 `pulse_gate`（`count<80` 且 `trial_phase<6`）负责。

**`interval` 是 timer 重装值（负值），不是正的周期。** 240 Hz 逻辑线程下 `-0.0499`
对应 12 帧 = 50 ms；若用 `-0.05`，浮点边界会落成 13 帧（约 18.5 Hz），4 s 窗口内
实际只会发出约 76 个脉冲，而不是 80 个。换逻辑帧率时需重新校准该值。

### container（外层嵌套）

```json
{"op": "add_group", "group_type": "container", "alias": "trial",
 "params": {"children": ["@class_cue", "@task_cue", "@rest_cue"],
            "entry": ["phase", "exec_in"],
            "done": ["next_trial", "exec_out"],
            "members": ["phase", "tt_rest", "tt_next"]}}
```

容器不生成节点，只记录 `children` / `parent` 与 `slots`；`entry`/`done` 省略时取
首/末子组槽位。子组 `set_group` 重展开后，外层容器成员自动刷新。执行关系仍由
`@父组.done -> @子组.entry` 等显式连线决定。

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

- 规则参考位于本包 `rules.md`（分节读取）；修改规则时请同步调整引擎侧校验实现。
- 直接写 `.scene` 文件**只允许出现在离线侧**（运行中的场景改动必须走实时通道，避免双写）。

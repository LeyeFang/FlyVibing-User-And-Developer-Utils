# 节点编辑器业务逻辑开发协议

> 适用：节点类型定义、求值器（evaluator）、图约束、执行引擎、图文档（agent 消费）、
> 程序化构图（GraphBuilder）、agent 通道（CLI + MCP, FlyVibing-User-And-Developer-Utils/packages/node-editor）。
> UI 表现层协议见 `ui_protocol.md`；设备/IO 后端协议见 `device_io_protocol.md`。
>
> **位置约定（2026-09 迁移）**：运行时本体位于 `Application/Core/NodeGraph/**`
> （与编辑器/imgui 零耦合，边界由 `Test/Application/Core/test_node_graph_boundary.py` 守卫）；
> 编辑器交互层位于 `Application/Editor/UI/panels/node_editor/**`。

---

## 1. 域地图

| 层 | 文件 | 说明 |
|---|---|---|
| 数据模型 | `Application/Core/NodeGraph/data_model.py` | `PinDef` / `NodeTypeDef` / `NodeInstance` / `LinkInstance`（无 imgui 依赖） |
| 类型注册表 | `Application/Core/NodeGraph/node_types/*.py` | 每文件一类；`_reg()` 注册进 `_TYPES`；颜色常量在 `node_types/__init__.py` |
| 执行引擎 | `Application/Core/NodeGraph/evaluator_engine.py` | `ExecutionContext`（pin/var/timer/dry_run/**宿主注入**）、`GraphEvaluator`（exec 遍历 + 懒求值）、`_EVALUATORS` 注册表 |
| 求值器 | `Application/Core/NodeGraph/evaluators/*.py` | 每文件一域；`register_evaluator()`；导入触发在 `Application/Core/NodeGraph/__init__.py` |
| 画布 | `Application/Core/NodeGraph/canvas.py` | `NodeCanvas`：节点/连线 CRUD、`pin_ids` 实例化、序列化（**存档契约**） |
| 图约束 | `Application/Core/NodeGraph/graph_constraints.py` | 跨节点联动（删除级联 + 静态校验函数）；纯数据、无 imgui |
| 场景内嵌文档 | `Application/Core/NodeGraph/graph_rules.py` | `_NODE_GRAPH_RULES`，每次导出 scene 时附带（外部 agent 读） |
| 编辑器交互层 | `Application/Editor/UI/panels/node_editor/**` | 画布渲染 / Add 菜单 / 内联控件 / 级联删除交互 / 自动布局（imgui） |
| Agent 参考文档 | `FlyVibing-User-And-Developer-Utils/packages/node-editor/rules.md` | 构图 agent 参考（**按节读取**: get_rules(section=...) / CLI rules; 无参=目录）；含 build_graph Spec 节 |
| Agent 通道 | `FlyVibing-User-And-Developer-Utils/packages/node-editor/mcp_server.py` + `cli.py` | MCP 4 工具（get_rules(分节) / get_scene_entities / build_graph / apply_graph；`validate_graph` 已移除）; CLI: `python -m flyvibing_node_editor.cli {rules,entities,build,apply}` |
| 校验器（唯一实现） | `FlyVibing-User-And-Developer-Utils/packages/node-editor/node_graph_validator.py` | L1 规则唯一实现（`check_graph` / `validate_static`）+ L2 干跑委托 `validation.dry_run`；引擎侧 `validation/checks.py` 是薄适配器（`graph_validation_protocol.md`） |
| 构图器 | `FlyVibing-User-And-Developer-Utils/packages/node-editor/graph_builder.py` | 程序化构图 + `validate()`；节点 helper（siggen_* / pool_* / epoch_* / fbscp_* / cca_* / show_media / entity_list_* / annotate） |

> 旧路径 `Application/Editor/UI/controllers/node_editor/` 仅保留包级 re-export shim（弃用）；
> 新代码一律使用上表路径。

---

## 2. 画布存档契约（alias / description / node_groups）

`NodeCanvas.to_dict()` / `from_dict()` 是**唯一存档契约**（场景 `node_graph` 字段直接用它）：

- `NodeInstance.alias: str` — 人可读别名（工具链/flow/搜索用，运行时忽略）。
  空字符串 = 未命名；`to_dict()` **省略空 alias**，旧场景文件保持干净。
- `NodeInstance.description: str` — 人和 agent 可读的意图/输入输出说明（运行时忽略）。
  `to_dict()` 省略空描述；GUI 节点卡 **Description** 可展开/收起并直接编辑；
  `graph.list` 返回、`graph.set_description` 读写（省略参数=读，空串=清除）；
  离线工具 `set_description` / `add_node.description` 同样支持。
- `NodeCanvas.node_groups: dict` — 节点组元数据（tools 层宏的记账：`type/alias/params/
  members/chain_members/arm_members/slots/parent/children`；规范见工具仓 `node_groups.py` + `rules.md`）。
  引擎**只做不透明保留**，不参与求值；空 dict 不写入 JSON。
- `clear()` 同时清空组；`replace_from()` 整块复制（导入/切场景不丢组）。
- `graph.list` 快照：节点带 `alias` / `description`（非空时），顶层带 `node_groups` 摘要
  （`type/alias/version/arms/members/parent/children/slots`）；`graph.export` 走 `to_dict()`，元数据随图落盘。
- 编辑器表现层：节点卡标题显示 `@alias`；**Description** 区折叠时显示首行、展开后可直接编辑；
  `node_groups` 按成员位置画背景框（标题 `@组别名 [类型]`）；工具栏 **Fit** / `graph.fit` 视图适配全部节点。
- 守卫：`Test/Application/NodeGraph/test_canvas_metadata.py`（alias/description round-trip、空值省略 /
  clear / replace_from / Scene 存档 / export_graph）+ `Test/Application/Editor/test_live_command_server.py`
  （`graph.set_description` 读写/清除）+ `node_editor_smoke` 场景（alias + 组框绘制 + Fit）。

> 历史坑（2026-10-18）：`NodeInstance` 与 `NodeCanvas` 曾不保存这两个字段 →
> 引擎 `graph.export` / 场景保存会把 alias 与 `node_groups` 静默丢掉，
> 工具侧 `set_group` 随后报 unknown group。新增画布字段必须同步 `to_dict/from_dict`。

---

## 2.1 执行模型（写求值器前必须理解）

- 触发：`GraphEvaluator.trigger(event_type)` 遍历所有 `category == "Event"` 的同名事件节点，
  沿 exec 输出 DFS（`_walk_exec`），同一 trigger 内节点只执行一次。
- 数据节点（无 exec pin）**懒求值**：任一输出被 `_read_input` 读取时触发其 evaluator；
  环检测由 `_eval_guard` 保证（每次 trigger 重置）。
- 每次 trigger 会**清空** `ctx._pin_values`；pin 值作用域 = 单次 trigger。
- 变量 `ctx.set_var/get_var` 跨 trigger 持久；Timer 用 `ctx.create_timer/get_timer/set_timer`。
  `SetTimer` 默认 `create_if_missing=true`：timer 名不存在时自动创建（`operate=reset` 为 0，
  `set_time` 为指定值），不再强制先 `NewTimer`；显式关掉可恢复旧行为。
- `Compare`：数值 `gt/lt/eq/neq/gte/lte`；布尔 `and/or/not/xor`；成员 `in/not_in`（`out` 为 `not_in` 别名，A=item，B=list，EntityRef 按 eid）；
  区间 `between`（B ≤ A < C，`include_end=true` 时闭端）。`MakeList` 把已连接的 `Item_0..7`
  收集为列表（未连接项跳过），作为 `in/not_in` 的 B 源；实体列表也可直接用 `EntityPack`。
- 有状态节点用 `g.get_state(nid, key, default)` / `g.set_state(nid, key, value)`（如 Delay）。
- 阻塞语义：节点可设 `_blocked=True` 暂停 exec 链（Delay / TimeTrigger / Branch 手动走分支）。
- pin 约定：`exec_in` / `exec_out`；多路 exec 用 `out_0..out_N`；数据 pin 用语义名
  （`Value` / `Result` / `In_0..`）。`data_type` 决定连线颜色（`styling.LINK_COLORS`：
  exec/float/int/bool/vec3/string/entity_ref/variant；新类型需补色）。
- 类型转换：`_read_input` 返回原始值（可能 str/int/ndarray）；需要 float 时用 math.py 的
  `_read_data_input`，需要原始类型时参考 `evaluators/io.py._read_input_raw` 模式。
- 事件节点 pin 名为 **`exec`**（不是 exec_in/exec_out）；GraphBuilder 固定事件 ID 161/163/166，
  连线写法 `g.link(GS, "exec", node, "exec_in")`。

### 2.2 实体生命周期与可见性（MI / 复合 cue 必读）

- `EntitySpawn(template=X)`：从 `Scene.entities` 实例化模板 X，并沿 `parent_id` **递归生成全部子孙**；
  返回 Entity = 根实例。子实体保留模板名，可用 `EntityGet(子名)` 取。
- `EntitySetRenderVisible`：只写**目标实体自己**的 `MeshRenderer.visible`，**不递归**。
  只有 Transform 的容器（如 MI 的 `LeftCue`）没有视觉效果。
- `EntityGroupSetVisible`：对 Entity1-4 各写一次（单批同帧），同样**不递归**；
  复合 cue 必须把每个带网格的子实体都接进来。
- `EntityGetTree` / `EntityPack` / `EntityListMerge` 产生 `entity_list`（纯数据）；
  `EntityListSetVisible` 单批显隐；`EntityListDestroy` 按子树删除。列表只能装运行时
  `EntityRef`，不能存编辑器场景 id（PIE 会重新分配）。
- `entity.visible` / `entity.delete` op 统一支持 `scope=one|tree|list`：
  `one` = 目标本身；`tree` = 目标 + 全部子孙；`list` = `ids` 给定的精确集合。
  `entity.visible editor` 默认 `tree`，`render` 默认 `one`；多实体 render 走单批命令。
  `entity.delete scope=one` 默认把子实体重挂到父级（`reparent_children=true`），不产生孤儿。
- 因此 `cue_n_way` 的 arm 支持 `entity`（单实体兼容）或 `entities: [names...]`
  （多实体 → 多个 `EntityGet` + `EntityPack/Merge` + `EntityListSetVisible` +
  `ParallelSend`）；MI 的“箭把+箭头”复合 cue 用后者。

### 2.3 节点组（tools 层宏）

`node_graph.node_groups` 是工具层宏记账，引擎不透明保留、不求值。组在插入时已展开为普通
`nodes/links`；`slots.entry` / `slots.done` 是内部 pin 的引用，外部用
`["@alias", "entry"]` / `["@alias", "done"]` 连接。

`cue_window` 是**每帧线性组**：`entry` 每次父链执行都会进入，`done` 是本次求值继续（**每帧**，不是退出事件）；组内用 `TimeGetElapsed(clock)` + `Compare(gte/lt or lte)` + `Compare(and)` 算 active，
再 `EntityGet(entity)` → `EntitySetRenderVisible(Visible=active)`。窗口外也写 `false`，
所以组自己负责 enter/exit，不需要外部隐藏；一次性到点事件仍用独立 `TimeTrigger`。参数：`clock`、`start`、`end`、`entity`、
`visible`、`include_end`。`set_group` 修改参数时重建组内节点，并 remap 外部 entry/done 连线。
嵌套用 `"parent": "@外层组"` 记录 `parent/children` 元数据；执行关系仍由显式
`@外层组.done -> @内层组.entry` 连线表达。同一属性只允许一个组写（单写者）。

`hide_group` 是线性组：每个根实体 `EntityGet → EntityGetTree`，多根经
`EntityListMerge` → `EntityListSetVisible`；参数 `entities`（根名）与 `visible`。
`mi_select` 是**一次性**线性组：`Random(1..N) → VarSet(mi_var)`，再对每个 arm
`Compare(mi_code==code)` + 每个实体 `EntityGet → EntitySetRenderVisible`；没有 Branch。
`entry` 必须接 phase0 起点的一次性事件（如 `TimeTrigger(trial_phase, 0)`），**不能每帧调用**，
否则 Random 会重抽。注意这里的 `phase` 是 **trial 时间阶段**（0/2/6/10 s），不是 SSSEP
刺激相位差；刺激相位差由下位机刺激器解释 `sss_code` 后设置，节点图不计算它。
`phase0_trigger` 线性组计算 `mi_code*mi_scale + sss_code` 并
`ParallelSend` 一次；`sss_pulse` 线性组每次 entry 发送并行/串行 SSSEP 码、`pulse_count++`、
重装 `SetTimer`，20 Hz 窗口与 `count<80` 由外层 gate 负责。`sss_pulse` 的 `interval`
默认是 `-0.0499`（负的重装值）：240 Hz 逻辑线程下正好 12 帧 = 50 ms；`-0.05` 会因浮点边界
变成 13 帧，4 s 窗口内只能发出约 76 次而不是 80 次。
`container` 不生成执行节点，只包已有子组：参数 `children`、可选 `entry`/`done`
（节点 pin 引用）与 `members`；子组 `set_group` 重展开后容器成员自动刷新。

---

## 3. 新增节点完整清单（10 步，缺一不可）

1. `node_types/<域>.py`：`_reg(NodeTypeDef(type_name, label, category, COLOR, pins, props_text))`；
   `category` 只对 Event 特殊（触发匹配用）。
2. `node_types/__init__.py`：新域文件 `from . import xxx` + 颜色常量。
3. 菜单：`panels/node_editor/styling.py` `MENU_SECTIONS` 对应分组加 `(label, type_name)`；
   **label 必须等于 NodeTypeDef.label**。
4. 控件：`panels/node_editor/widgets/`（包；注册表在 `core.py`，按家族分子模块）`@register("TypeName")`；默认值幂等初始化；控件 ID 带 `_{nid}`。UI 侧调校验函数（`epoch_source_keys` 等）一律经 `graph_constraints.nodes_as_dicts(canvas)` 转换。
5. 自动布局：`panels/node_editor/panel.py` `_WIDGET_NODES` 加入该类型（有内联控件必须加）。
6. 引脚可见性（可选）：`panels/node_editor/visible_pins.py` `@rule("TypeName")`。
7. 求值器：`evaluators/<域>.py` 实现 + `register_evaluator()`；
   并在 `Application/Core/NodeGraph/__init__.py` 的 `from .evaluators import (...)` 中加模块名。
8. 删除联动/校验（如涉及跨节点规则）：`graph_constraints.py` 增加纯函数；
   `panel._handle_deletion` 与 `node_graph_validator.validate_static` 各自接入。
9. 文档：`graph_rules.py`（场景内嵌）+ `FlyVibing-User-And-Developer-Utils/packages/node-editor/rules.md`（MCP agent）+
   `FlyVibing-User-And-Developer-Utils/packages/node-editor/graph_builder.py` helper（推荐）。
10. 测试：无头单元测试或干跑断言（见 §6）；引擎内校验必须通过（`engine_validate_graph` / `PlayerEntry --dry-run` / `test_graph_validation.py`）。

> 兼容保留的旧节点：**保留注册但菜单不出现**，在定义文件注释说明替代关系
> （例：`math.py` 的 MathAdd 系列、`entity.py` 的 EntityAddMesh/EntityAddCamera）。

---

## 4. Dry-Run（MCP 空跑）契约 — CRITICAL

干跑校验（引擎内服务；无头经 `PlayerEntry --dry-run`）会以 `ctx.dry_run=True` 模拟执行整图。求值器必须：

```python
if ctx.dry_run:
    ctx.emit_log(node_id, "TypeName", "action", "参数与真实路径一致")
    return
# 真实副作用（写文件 / 开设备 / 发串口 / 改场景）
```

- `ctx.emit_log(node_id, node_type, action, detail)`：干跑校验器的日志通道
  （`validate_graph` 汇总 `events_by_type` / `by action`，测试可断言）。
- **禁止**在干跑中：开线程、开设备、写文件、改真实场景、导入重依赖。
- 真实模式失败要**记录并继续**（`emit_log(..., "error", ...)` + print），不得向上抛异常
  （否则整帧执行中断）。参考 `evaluators/siggen.py` + `Application/Functions/VirtualDevice` 空跑后端的写法。
- 纯数据节点（如 GetSigGenData）干跑中只有在输出**被读取**时才会求值 —— 测试/校验图要保证
  至少有一条数据连线消费它的输出，否则不会出现在干跑事件里。

---

## 5. 图约束（graph_constraints.py 模式）

- 业务规则示例：`InitSigGenDevice ⇄ KillSigGenDevice` 强制成对（设备族）；设备池 `CreateDevicePool ⇄
  KillDevicePool` 同样成对（外加 `device` pin 连线校验与单池成员制，见 `validation/checks.py` §8/§9）。
- 两部分配套实现：
  - `*_cascade_deletes(canvas, ids)`：编辑器删除时扩展为级联删除集合（UI 调用；
    `device_cascade_deletes` = SigGen ∥ Pool 并集）。
  - `*_pairing_errors(nodes_dict)`：静态校验错误列表（`node_graph_validator.validate_static` 调用；
    另有 `pool_reference_errors` 校验池引用）。
- 键规则单点化：`device_session_key` / `pool_key` 由评估器 / 校验器 / UI 三处共用，禁止另写变体。
- 绑定规则写进模块 docstring，并与 `rules.md` 同步（agent 依据它构图）。
- 规则函数必须**纯数据、无 imgui**，便于被 UI / 校验器 / 测试三处复用。

---

## 6. 测试模式

- **干跑全链路**（零硬件零 UI）：`GraphBuilder` 构图 → `validate_static()` → `g.validate(max_frames=N)`
  → 断言 `report.passed` 且 `dry_run["events_by_type"]` 含预期节点。
  范例：`Test/Application/Functions/test_siggen_device.py::test_graph_dry_run`。
- 约束测试：纯 dict 调 `siggen_pairing_errors`；`NodeCanvas` + `device_cascade_deletes` 测级联。
- 边界守卫（改动节点图包后必跑）：`python Test/Application/Core/test_node_graph_boundary.py` —
  源码扫描禁止 `Application.Editor` / `imgui_bundle` 导入，且阻断导入时运行时链路必须仍可导入。
- 迭代开发时可直接用 Pylance 代码片段工具跑无头断言（无需落盘测试文件）。

---

## 7. 已知坑（实战教训，按代价排序）

1. **菜单漂移**：曾出现节点已注册但菜单不可达（Event 页整体缺失、`EntitySetRenderVisible`
   不在菜单）→ 新增节点后必须核对"注册表 ↔ 菜单"。
2. **标签不一致**：`Constant` 卡片标题曾是 `"Scale"`（历史误名）→ 菜单/文档/卡片三处对齐；
   改名要注意 `graph_rules.py` 中给 agent 的说明同步。
3. **pin_ids 是实例级**：JSON 连线引用 `inst.pin_ids`（画布/导入导出/MCP 均如此），
   手写图时给每 pin 分配全局唯一数值；重复会导致连线错乱。
4. **事件节点 pin 名是 `exec`**：`chain()` 对事件节点不适用，直接 `link(GS, "exec", ...)`。
5. **重依赖 import 副作用**：设备 SDK/串口驱动 import 可能连带原生依赖；设备后端必须懒导入，
   否则 MCP 干跑在无设备机器上直接崩。
6. **自由线程（-Xgil=0）下的数据竞争**：跨线程共享结构必须加锁（见 device_io_protocol §4）；
   实机采集中"图线程读缓冲 / 采集线程写缓冲"是典型场景。
7. **文档三处不同步**：`rules.md`（MCP agent）、`graph_rules.py`（导出场景内嵌）、
   `Doc/Dev`（本目录）—— 改节点后三处一起改，避免 agent 依据旧文档构图。
8. **legacy 节点误入菜单**：兼容节点应在代码注释标明"菜单不出现"，避免后人误加。

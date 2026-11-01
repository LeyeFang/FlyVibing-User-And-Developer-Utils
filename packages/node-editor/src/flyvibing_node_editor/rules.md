# Node Graph Reference for AI Agents

> 本文档供 AI agent 编写节点图 JSON 时参考（节点类型表、连线规则、执行模型、常见模式）。
> **按节读取（省 token）**: MCP `get_rules(section="<标题>")` / CLI `python -m flyvibing_node_editor.cli rules "<标题>"`;
> 无参只回目录（各节标题与规模）; 仅确需全文时才 `section="all"` / `--all`。

---

## JSON Structure

```json
{
  "version": "0.1.0",
  "nodes": { "<node_id>": { ... }, ... },
  "links": { "<link_id>": { ... }, ... },
  "next_id": <int>
}
```

- **nodes**: key 为 node ID 字符串, value 为 NodeInstance
- **links**: key 为 link ID 字符串, value 为 LinkInstance
- **next_id**: 1 + max(所有 node/link/pin ID), 确保无碰撞

### NodeInstance

```json
{
  "id": <int>,
  "node_type": "<type_name>",
  "pos": [<x>, <y>],
  "props": { <key>: <value>, ... },
  "pin_ids": { "<pin_name>": <int>, ... },
  "alias": "<optional_name>",
  "description": "<optional_free_text>"
}
```

- `pin_ids`: 实例级唯一定义的 pin ID。所有连线引用这些 ID,而非类型模板的 PinDef ID。
- `alias`: 可选的人可读别名（类似变量名 vs 地址）。`[A-Za-z_][A-Za-z0-9_]*`，图内大小写无关唯一；
  不影响运行时，只影响工具/flow/搜索。编辑 ops 里可用 `@alias` 或裸 alias 引用节点。
- `description`: 可选的人/agent 可读说明（意图、输入输出、范式含义）。不影响运行时；
  写/改/清用 `set_description`，`add_node` 也可直接带 `description`；`graph.list` 会返回。
- 事件节点 (OnGameStart/OnFrameUpdate/OnGameStop) 固定 ID: 161/163/166

### LinkInstance

```json
{
  "id": <int>,
  "from_pin": <int>,
  "to_pin": <int>
}
```

- `from_pin`: 必须是 output pin 的 ID
- `to_pin`: 必须是 input pin 的 ID

---

## Node Groups (tools-level macro)

`node_graph.node_groups` 是 **可选** 元数据（引擎**不透明保留**、不参与求值；
`graph.export` / 场景保存会原样带回）。组插入时已展开成普通
nodes/links，组只是一层可重展开的记账：

```json
"node_groups": {
  "g1": {
    "type": "cue_n_way",
    "version": 1,
    "alias": "cue_rand",
    "params": {"addr": 16376, "arms": [{"id": "left", "entity": "L", "code": 3}]},
    "members": [<node ids>],
    "chain_members": [<decision chain ids>],
    "arm_members": {"left": {"get": 1, "set": 2, "send": 3, "code": 4}},
    "slots": {"entry": <pin id>, "done": null},
    "parent": "g2",
    "children": ["g3"]
  }
}
```

外部只能用 `"to": ["@cue_rand", "entry"]` 接进组；`set_group` 按 arm `id` 差分重展开，
未变 arm 的动作节点 ID 保持不变。模板与参数说明见 `README.md`。

### cue_window（每帧窗口组）

`cue_window` 是**每帧求值**的线性组，边界只有 `entry` / `done` 两个 exec 槽：

- `entry`：父链每次执行到这里就进入（不是一次性开始事件）。
- `done`：本次求值结束，继续父链（不是退出事件）。
  `done` 是**每帧都会走**的普通 exec 出口；需要“2 s 到点只触发一次”时用独立的
  `TimeTrigger(timer=..., time=2)`，不要把它接到 `done`。
- 组内每帧重新计算 `start <= elapsed < end`，并写一次 `EntitySetRenderVisible`：
  窗口内 `Visible=true`（`visible=false` 时取反），窗口外 `Visible=false`。
  因此**组自己负责 enter/exit**，外部不需要再写隐藏。

```json
{"op": "add_group", "group_type": "cue_window", "alias": "class_cue",
 "params": {"clock": "trial_phase", "start": 0, "end": 2, "entity": "TaskCue"}}
```

展开为：`TimeGetElapsed(clock)` → `Compare(gte,start)` + `Compare(lt/end)` →
`Compare(and)` → `EntityGet(entity)` → `EntitySetRenderVisible(Visible=active)`。
`include_end=true` 时区间为 `[start,end]`；`visible=false` 时窗口内写 `false`。
`entry` 接 `OnFrameUpdate` 即可；`done` 可接后续节点或用 `"from": ["@class_cue", "done"]`
继续。嵌套组加 `"parent": "@外层组"`，父组 `children` 记录子组；执行关系仍由
`@父组.done -> @子组.entry` 这类显式连线表达。

**单写者**：同一实体/属性只允许一个窗口组写；多个窗口重叠时，改成单个组内先算 phase
（`Compare`/`and` 组合）再写一次，或显式经过优先级节点，不依赖链顺序。

### hide_group（按实体树批量显隐）

线性组，`entry` / `done` 各一个 exec 槽。对每个根实体做 `EntityGet → EntityGetTree`，
再 `EntityListMerge`（多个根）→ `EntityListSetVisible`：

```json
{"op": "add_group", "group_type": "hide_group", "alias": "rest_cue",
 "params": {"entities": ["LeftCue", "RightCue", "NullCue", "TaskCue"],
            "visible": false}}
```

`entities` 是运行时实体名（通常传容器根，树内网格一起处理）；`visible=false` 为隐藏。
适合在 6 s 用 `TimeTrigger` 触发一次，而不是每帧执行。

### mi_select（MI 类别 → 可见 cue）

```json
{"op": "add_group", "group_type": "mi_select", "alias": "mi_select",
 "params": {"mi_var": "mi_code", "arms": [
   {"id": "left",  "entities": ["L_arrow_body", "L_arrow_head"], "code": 1},
   {"id": "right", "entities": ["R_arrow_head", "R_arrow_body"], "code": 2},
   {"id": "none",  "entities": ["part1", "part2"], "code": 3}]}}
```

线性组：`Random(1..N) → VarSet(mi_var)`，再对每个 arm 做 `Compare(mi_code==code)`，并对该 arm
的每个实体 `EntityGet → EntitySetRenderVisible`。没有 Branch；`entry` 是 `VarSet.exec_in`，
`done` 是最后一个 `EntitySetRenderVisible.exec_out`。**每次 entry 会重新抽 Random**，应在
phase0 起点用 `TimeTrigger` 调用一次，不能接每帧 Update。

### phase0_trigger（cue onset 触发）

线性组：`VarGet(mi_code) * mi_scale + VarGet(sss_code) → VarSet(trigger_val) → ParallelSend`。
`entry` 在 `VarSet(trigger_val).exec_in`，`done` 在 `ParallelSend.exec_out`；每次 entry 发送一次，
适合接在 cue 稳定后的 OneShot 逻辑中。参数 `mi_scale` 默认 32，`address` 默认 16376。

### sss_pulse（20 Hz 脉冲）

线性组：`VarGet(sss_code)` 同时送 `ParallelSend` 与 `SerialSend`，随后 `pulse_count += 1`，
最后 `SetTimer(pulse, interval)` 重装定时器。`entry` 在 `ParallelSend.exec_in`，`done` 在
`SetTimer.exec_out`。组本身不判断 20 Hz 窗口和上限；前置条件（如 `count<80` 且 `trial_phase<6`）
由外层 gate 负责，避免在 rest 段继续发脉冲。

`interval` 是负的 timer 重装值：240 Hz 逻辑线程下默认 `-0.0499` 才能稳定落在
12 帧（50 ms）；`-0.05` 会在浮点边界变成 13 帧，实际约 18.5 Hz，80 次脉冲窗口会漏发。

### container（外层嵌套组）

`container` 不生成执行节点，只把已有子组包成外层组（用于组框/嵌套/单入口单出口）：

```json
{"op": "add_group", "group_type": "container", "alias": "trial",
 "params": {
   "children": ["@class_cue", "@task_cue", "@rest_cue"],
   "entry": ["phase", "exec_in"],
   "done": ["next_trial", "exec_out"],
   "members": ["phase", "tt_rest", "tt_next"]
 }}
```

- `children` 的子组自动写 `parent`，外层组写 `children`。
- `entry`/`done` 可省略：默认取第一个子组 entry / 最后一个子组 done。
- `members` 可追加 gate 节点，让组框覆盖整个试次；实际执行仍由图中显式连线决定。
- 子组 `set_group` 重展开后，外层容器的 `members` 会自动刷新。

### 交互式合并 / 拆分 / 删除

编辑器侧：`Shift+click` 多选，框选只命中节点；右键多选节点或背景 → `Merge into Group`，
右键组框 → `Ungroup` / `Delete Group`；`Groups` 窗口也有后两个动作。删除只删组框元数据，
成员节点保留。选择必须完整覆盖已有组，部分覆盖会被拒绝。

编辑器会持久化 `node_groups[gid]` 的可选几何字段（画布坐标）：

```json
"box":     {"x": 48.0, "y": 38.0, "w": 300.0, "h": 220.0},
"min_box": {"w": 220.0, "h": 160.0},
"params":  {"entry": 271, "done": 277, "entry_node": 270, "done_node": 274}
```

`box`/`min_box` 由 GUI 组框拖动/缩放维护；离线工具应原样保留，不要按 members 重新推导。
`Groups` 窗口的 `Group name` 输入会更新 `alias`。

离线 CLI（默认 dry-run，`--write` 才落盘）：

```powershell
python -m flyvibing_node_editor.cli group-merge --scene scene.scene --nodes 2,3 --write
python -m flyvibing_node_editor.cli group-ungroup --scene scene.scene --group g1 --write
python -m flyvibing_node_editor.cli group-delete --scene scene.scene --group g1 --write
```

对应的 `apply-ops` kind：`merge_group` / `ungroup_group` / `delete_group`。

---

## Connection Rules

1. **exec → exec**, **data → data**, **never cross**
2. One output pin can fan out to **multiple** input pins
3. One input pin can only receive from **one** output pin
4. Event nodes have **no** input exec pins (they are graph roots)
5. Input event nodes: `OnKeyPressed` / `OnKeyReleased` / `OnMouseClicked` also have no input exec pins

---

## Execution Model

- **OnGameStart**: fires ONCE. Use for init.
- **OnFrameUpdate**: fires EVERY FRAME. Use for TimeTrigger, polling.
- **OnGameStop**: fires ONCE. Use for cleanup.
- **OnKeyPressed / OnKeyReleased / OnMouseClicked**: fire once per matching input event. `OnMouseClicked` fires on release only when the press moved <= 6 px (drag is not a click). Props: key (`"Space"`/`"A"`/`"Escape"`/code), mods (`any`/`none`/`Shift`/`Ctrl+Shift`), button (`Left`/`Right`/`Middle`/`Any`), repeat (OnKeyPressed only).
- **Exec chain**: depth-first traversal following exec output→input links.
- **Pure data nodes** (Constant, Compare, ScalarMath, Random, IsKeyDown, IsMouseButtonDown, GetMousePosition, etc.): NO exec pins. Evaluated LAZILY when their output pin is read via a data link.
- **TimeTrigger**: fires on the rising edge of `current >= threshold` (once per crossing).
  Re-arm by raising the threshold above current (variable/pin pulse pattern) or by resetting the timer.
  (The engine removed `TimeDelay` — it only advanced when the whole exec chain re-entered
  every frame, and its duration prop was ignored. Use `TimeTrigger(mode=manual, time=N)`
  on an `OnFrameUpdate` chain instead.)
- **Branch**: walks True or False based on Condition data pin.
- **Variables** persist across frames. VarSet writes, VarGet reads.

---

## Node Type Reference

### Event (graph roots)
| type_name | output pins | notes |
|-----------|------------|-------|
| OnGameStart | exec | once at start |
| OnFrameUpdate | exec, delta(float) | every frame |
| OnGameStop | exec | once at stop |
| OnKeyPressed | exec, Key(int), Mods(int) | props: key, mods, repeat |
| OnKeyReleased | exec, Key(int), Mods(int) | props: key, mods |
| OnMouseClicked | exec, Button/Mods/X/Y(int) | props: button, mods |

### Input data (pure data, no exec)
| type_name | output | props |
|-----------|--------|-------|
| IsKeyDown | Down(int 0/1) | key |
| IsMouseButtonDown | Down(int 0/1) | button |
| GetMousePosition | X(int), Y(int) | — |

### Flow
| type_name | input | output | props |
|-----------|-------|--------|-------|
| Sequence | exec_in | out_0..out_4 (exec) | — |
| Branch | exec_in, Condition(bool) | True, False (exec) | — |

### Math (pure data, no exec)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ScalarMath | In_0..In_7 (float) | Result | operation: sum/subtract/multiply/divide (short aliases add/sub/mul/div accepted) |
| Compare | A,B (variant), C (float, 可选) | Result(bool) | operation: gt/lt/eq/neq/gte/lte/and/or/not/xor/in/not_in(out)/between; between 半开区间 B<=A<C, include_end=true 时闭区间 |
| MakeList | Item_0..Item_7 (variant, 可选) | List(variant) | — (纯数据: 跳过未连接槽位, 常用来给 in/not_in 提供候选集合) |
| Constant | — | Result(float) | value: float |
| RandomSetSeed | exec_in, exec_out, Seed(int) | (exec_out) | source: hardware/manual/pin |
| Random | Min,Max,Mean,StdDev | Result(float) | distribution: uniform/gaussian/discrete, mode: manual/pin |

`Compare` 的 `and`/`or`/`not`/`xor` 是布尔组合（A/B 取真值，`not` 只用 A）；`in`/`not_in` 支持列表、字符串与 EntityRef：`A` 是要测试的值，`B` 是列表
（可由 `MakeList` 或 `EntityPack`/`EntityGetTree` 提供）；`not_in` 也可写 `out`。
`between` 用 `B <= A < C`（半开），`include_end=true` 改为 `B <= A <= C`；`C` 未连接
时区间上界为 0。旧的 `gt/lt/eq/neq/gte/lte` 仍按数值比较。

### Time (✅ has timer support)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| TimeGetElapsed | exec_in | exec_out, Elapsed(float) | timer: "" (global) or name |
| TimeTrigger | exec_in, Time(float) | Elapsed, out_0..out_7 (exec×8) | mode: manual/pin, time: float, **timer**: "" or name |
| TimeGetDate | — | DateString(string) | year/month/day/hour/minute: bool, format: str |
| NewTimer | exec_in, Name(string) | exec_out | mode: manual/pin, timer_name: str |
| SetTimer | exec_in, Value(float) | exec_out | operate: reset/set_time, mode: manual/pin, timer_name: str, value: float, create_if_missing: bool (默认 true) |

`SetTimer` 默认 `create_if_missing=true`：`timer_name` 不存在时，第一次执行即创建并从该次
写入的 `value` 开始计时（`operate=reset` 即 0；`operate=set_time` 即 value 秒）。
`NewTimer` 变成可选（需要显式清零/固定创建位置时再用）。把 `create_if_missing=false`
可恢复旧行为：timer 不存在时静默跳过。`TimeTrigger`/`TimeGetElapsed` 只读取，不创建。

### Variable
| type_name | input | output | props |
|-----------|-------|--------|-------|
| VarSet | exec_in, Name(string), Value(var) | exec_out | mode: manual/pin, var_name, value |
| VarGet | exec_in, Name(string) | exec_out, Value(var) | var_name |

### Entity
| type_name | input | output | props |
|-----------|-------|--------|-------|
| EntitySpawn | exec_in | exec_out, Entity(ref) | template: string |
| EntityGet | exec_in, Name(string) | exec_out, Entity(ref) | entity_name: string |
| EntitySetRenderVisible | exec_in, EntityID(int), Visible(bool) | exec_out | — |
| EntityGroupSetVisible | exec_in, Entity1-4(ref, 可选), Visible(bool) | exec_out | — |
| EntityGetTree | Entity(ref) | Entities(entity_list), Count(int) | — (纯数据: 先序包含根 + 全部子孙) |
| EntityPack | Entity1-4(ref, 可选) | Entities(entity_list), Count(int) | — (纯数据) |
| EntityListMerge | A,B(entity_list) | Entities(entity_list), Count(int) | — (纯数据: 去重保序) |
| EntityListSetVisible | exec_in, Entities(entity_list), Visible(bool) | exec_out | — (单批原子显隐) |
| EntityListDestroy | exec_in, Entities(entity_list) | exec_out | — (按子树删除) |
| SetText | exec_in, Entity(ref), Text(string) | exec_out | — |

多部件 cue（箭把+箭头等）显隐 MUST 用 `EntityGroupSetVisible` 或 `EntityListSetVisible`：
同一批命令下发，组内实体**同帧生效**（渲染帧边界不会把一组切成两半）；`EntitySetRenderVisible`
保留给单实体。

★ 实体层级与可见性语义（写 MI/复合 cue 图必读）：
- `EntitySpawn(template=X)`：从 `Scene.entities` 实例化模板 X，并按 `parent_id` **递归生成全部子孙**；
  返回的 Entity 是根实例。子实体保留模板名称，`EntityGet(子名)` 可找到。
- `EntitySetRenderVisible`：只写**目标实体自己**的 `MeshRenderer.visible`，**不递归**。
  容器实体（只有 Transform、无 MeshRenderer，如 MI 的 `LeftCue`）对它操作**没有任何视觉效果**。
- `EntityGroupSetVisible` / `EntityListSetVisible`：只对列表里的实体逐一生效（单批同帧），
  同样**不递归**；复合 cue 必须把每个带网格的子实体都接进来。
- `EntityGetTree` 负责把“根 + 子孙”变成 `entity_list`；`EntityPack` / `EntityListMerge`
  负责把多个实体或列表合成任意长度列表（运行时只接受 EntityRef，不接受编辑器场景 id）。
- 编辑器眼图标（`entity.visible editor=...`）是**编辑器视口**可见性，会递归到全部子孙；
  与运行时渲染可见性（`MeshRenderer.visible`）是两套语义。

`SetText`：设置目标实体 `TextDisplay.text` 并立即重新光栅化（PIE）；目标实体需有
`TextDisplay` 组件（字号/颜色/粗斜体等样式在组件上，编辑器/MCP 可改）。

### IO
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ParallelSend | exec_in, Address(int), Value(var) | exec_out | mode: manual/pin, address: int (0x3FF8 LPT1) |
| SerialSend | exec_in, Value(var) | exec_out | format: string/bytes, port, baud_rate |
| PathVar | — | Path(string) | browse_mode: directory/file, path |
| TextFileWrite | exec_in, FilePath, FileName, Value | exec_out | mode: pin, write_mode: w/a, delimiter |
| SaveData | exec_in, Data(var), FilePath, FileName | exec_out, Path, MetaPath, Rows, Cols, Samples, Written, Ok | mode, format: npz/npy/csv/json, file_path, file_name, unique, tag, key, compress, save_meta, csv_delimiter, csv_header, csv_mode, json_indent, value |

`SaveData` is the algorithm-facing data path; `TextFileWrite` remains for human-readable `.txt` logs. `Data` accepts arrays/lists/scalars/dicts; dict → NPZ arrays or CSV columns. `unique=true` appends timestamp/tag; dry-run only plans path/counts.

### SigGen (虚拟信号发生器 — IO ▸ SigGen)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| InitSigGenDevice | exec_in | exec_out | device_name, channels: 1..256, sampling_rate: 1..38400, frequency (Hz, ≤0=未填→10), freq_step (Hz/ch, ≥0), amplitude_uv (≥0), noise_uv (0=纯正弦), seed, export_format: npz/csv, save_dir ("." = cwd), buffer_seconds |
| StartSigGenRecord | exec_in | exec_out | device_name |
| StopSigGenRecord | exec_in | exec_out | device_name, save_scope: session/buffer |
| KillSigGenDevice | exec_in | exec_out | device_name |
| GetSigGenData | — (pure data node) | Data(variant ndarray channels×samples), Channels(int), Samples(int), Fs(float) | device_name |

SigGen 规则 (MUST):
1. **InitSigGenDevice 与 KillSigGenDevice 强制成对出现** — 设备族统一配对规则
   (引擎校验静态检查 + 编辑器删除级联; Kill 的 device_name 为空且仅 1 个 Init 时自动绑定)。
2. 纯软件正弦源: 通道 i 频率 = frequency + i·freq_step Hz, 幅度 µV float32,
   noise_uv>0 时按 seed 叠加确定性高斯噪声 — 任意机器可跑, 无硬件依赖。
3. 窗口缓冲 / GetSigGenData / Stop 保存语义 = 设备族统一实现:
   buffer_seconds × sampling_rate → (channels, N) float32 环形缓冲, 旧数据被新数据覆盖;
   Get 每次求值返回非销毁副本 (Channels / Samples 有效样本数 / Fs 辅出);
   Stop: save_scope=session → 本次 Start 以来全部数据, buffer → 仅当前窗口;
   目录与格式来自 Init (默认 "." 当前目录), npz/csv + 同名 .json 元数据。
   区别: 真实模式 (非干跑) 真正写盘; 干跑不落盘。
4. 所有设备族共用同一设备会话注册表 — device_name 跨族必须唯一;
   为空 = 注册表仅一个会话时自动绑定, 多会话必须显式指定。
5. 无硬件 / MCP 干跑 (validate_graph 设 max_frames>0): 全部节点走确定性空跑后端 —
   不触硬件、不落盘、不起线程, 干跑可复现。

### Game
| type_name | input | output | notes |
|-----------|-------|--------|-------|
| ExitGame | exec_in | — | terminal, no output |

### Media (动态媒体 — GIF/图像)
| type_name | input | output | props |
|-----------|-------|--------|-------|
| ShowMedia | exec_in, Entity(entity_ref) | exec_out | — |

ShowMedia 规则 (MUST):
1. **编辑器侧编辑只是模板**（实体上 MediaPlayer 组件声明 source 等参数, 编辑器不播放）;
   播放必须由本节点在图中正确接线才生效（PIE / 独立运行）。
2. 目标实体: `Get Entity`(Name) → `Entity` ref → `ShowMedia.Entity`
   （Entity 引脚未连 → 引擎校验报 media_pin_unconnected）。
3. 驱动频率 = 接线频率: 挂 `OnFrameUpdate` 链 → 逐帧播放（推荐）;
   挂 OnGameStart → 只推首帧。exec_in 未连仅警告（media_exec_unconnected）。
4. 同一实体被多个 ShowMedia 驱动 → 引擎帧内自动去重（每帧只推进一次, 不加速）。
5. 媒体播放状态（帧号/时钟）不序列化; 场景只存 MediaPlayer.source 等模板参数。

### Debug
| type_name | input | output | props |
|-----------|-------|--------|-------|
| Print | exec_in, Value(var) | exec_out | — |
| PrintString | exec_in | exec_out | message: string |

---

## ID Allocation Convention

- Event nodes: **161, 163, 166** (fixed)
- User nodes: start from **200**
- Pin IDs: start from **10000**
- Link IDs: start from **500**

---

## build_graph Spec

`build_graph`（MCP）/ `build`（CLI）从**实验描述 spec** 自动生成整张图（OnGameStart
初始化链 + OnFrameUpdate 计时/分支链）:

```json
{
  "seed_dir": "Test/.../seed",
  "seed_prefix": "MI-Seed",
  "init_delay": 5.0,
  "trials": 60,
  "timer": "trial_phase",
  "phases": [
    {"time": 0, "type": "cue_pick",
     "random": {"min": 1, "max": 2},
     "branches": [
       {"value": 1, "show": ["L_arrow_body", "L_arrow_head"], "parallel": 11},
       {"value": 2, "show": ["R_arrow_head", "R_arrow_body"], "parallel": 12}
     ]},
    {"time": 2, "show": ["TaskCue"]},
    {"time": 6, "hide": ["L_arrow_body", "L_arrow_head", "R_arrow_head", "R_arrow_body", "TaskCue"]},
    {"time": 10, "type": "trial_end"}
  ],
  "entities": ["Cross", "LeftCue", "RightCue", "TaskCue"],
  "pulse": null
}
```

- `phases[].type`: `cue_pick`（随机分支 + show + 并行口触发） / `action|show` / `trial_end`（trial 计数 + 复位 timer）;
- `pulse`（可选）: `{count, interval, timer, parallel_addr, serial_port, encode}` — 50ms 发送循环;
- `entities[]` 先 spawn 后统一隐藏，由 phases 显隐控制；seed 链固定串在 OnGameStart 上;
- CLI 等价: `python -m flyvibing_node_editor.cli build --spec spec.json --out graph.json`（--out 落盘只回摘要）。

---

## Common Patterns

### 1. Timer-driven trial experiment
```
OnGameStart → seed → spawn → hide → VarSet(trial) → NewTimer("phase") → SetTimer(-delay)
OnFrameUpdate → Sequence → TimeTrigger×4 (timer="phase", time=0,2,6,10)
  TT0 → cue pick + show + send
  TT2 → show TaskCue
  TT6 → hide all
  TT10 → trial++ → Branch(trial>60) → ExitGame / SetTimer(reset)
```

### 2. 50ms pulse loop
```
OnFrameUpdate → Sequence → TTPulse (timer="pulse", time=0)
  → VarGet("count") → Compare(lt, 80) → Branch
    True  → send → inc count → SetTimer("pulse", -0.05)
    False → (stop)
Start: VarSet("count", 0) → SetTimer("pulse", -0.05)
```

### 3. Cue visibility toggle
```
EntityGet("entity_name") → EntitySetRenderVisible
  Entity.Get → EntitySet.EntityID
  Constant(0 or 1) → EntitySet.Visible
```

### 4. Binary random pick
```
Random(min=1, max=2, discrete) → Compare(eq, 1) → Branch
  True → (chain A)
  False → (chain B)
```

### 5. MI×SSSEP encoding (trigger = MI<<6 | SSSEP)
```
Constant(MI<<6) → ScalarMath(sum, In_0)
VarGet("sss_code") → ScalarMath(sum, In_1)
ScalarMath.Result → VarSet("trigger_val", mode=pin)
```

---

## Validation

- **引擎运行中（推荐）**: 引擎内校验服务 — Node Editor ▸ Validate 按钮 /
  `engine_validate_graph`（editor MCP, lite 档）/ `engine-editor-cli validate`（终端;
  `--source graph` 可先验 agent 生成的图，不用先导入画布）。
- **无头 / CI**: `PlayerEntry --dry-run` 或 `Test/Application/NodeGraph/test_graph_validation.py`。
- 旧离线路径说明（2026-10-05）: 本 MCP 的 `validate_graph` 工具已移除；
  `node_graph_validator.py` / `GraphBuilder.validate()` 仅供旧脚本与单元测试复用，不再是推荐入口 —
  校验的单一事实源是引擎内服务（`Doc/Dev/graph_validation_protocol.md`）。

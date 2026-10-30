# Example 开发指南（从场景到可运行成品）

> 读者：实验设计者 / 扩展作者 / agent。目标：构建一个 **Example**（场景 + 节点图 + README +
> 可复现验证 + 可导出成品），使用工具仓现有接口，不修改引擎核心。
>
> 当前官方示例：`Examples/MI`（MI 左右手范式）与 `Examples/RestingState`（睁眼/闭眼静息态）。
> 本文是面向工具使用者的构建流程；引擎内部的 Examples 进度板见
> `Doc/Dev/examples_plan.md`。

## 1. Example 的交付物

每个 Example 至少包含：

```text
Examples/<Name>/
  <Name>.myproj              # 工程入口（scenes 列表 + startup_scene + resources）
  scenes/<Name>.scene        # 模板实体 + 节点图
  README.md                  # 范式、时间线、别名、码值/设备名、如何改名/改参数
```

如果要交付给实验员，再导出一份成品：

```text
rst/<Name>/
  <Name>.myproj
  scenes/*.scene
  game.json
  run_game.cmd               # 双击启动（自带 runtime）
  output/                    # 实验数据
```

设计工程和成品分开；改实验改 `project/Examples`，不要手改成品的 `Application/`。

## 1.1 社区 Example 注入（不污染主线）

社区作者**不要**把示例复制进仓库 `Examples/`，也不要改官方 `.myproj`/场景；把示例放到用户目录：

```text
%APPDATA%/FlyVibingEngine/examples/<Name>/
  <Name>.myproj
  scenes/*.scene
  README.md
```

- 测试/便携部署可用 `FVE_EXAMPLES_DIR`（旧 `MGE_EXAMPLES_DIR`）指向任意目录。
- `.myproj` 顶层写提供者签名：

```json
{
  "name": "MyTask",
  "provider": "@ACME",
  "startup_scene": "scenes/MyTask.scene"
}
```

- `File ▸ Open Example` 会扫描官方 `Examples/`、测试夹具和用户目录；
  项目名后显示灰色 `@ACME`。未写 `provider` 的用户示例默认显示 `@Community`，
  不会冒充官方。
- 也可直接打开：`engine-editor-cli call project.open path="%APPDATA%/FlyVibingEngine/examples/MyTask/MyTask.myproj"`。
- 社区示例只属于本机/当前用户；不要把它登记进
  `Application/Functions/official_extensions.json`，也不要指望安装包分发。
  要给别人用，走 `project.export` 的用户态游戏包，并让使用到的扩展显式声明
  `signature`/`export`。
- 不要把社区扩展放进 `Application/Functions/`；安装包只按 mainline allowlist 分发。

## 2. 推荐构建顺序

### ① 建工程与场景

用编辑器打开/新建工程，或者复制一个最小示例骨架：

```powershell
engine-editor-cli call project.open path=C:\path\to\<Name>.myproj
engine-editor-cli call scene.list
engine-editor-cli call scene.create name=<Name>
engine-editor-cli call scene.switch name=<Name>
```

场景里只需要放 **EntitySpawn 模板实体**、相机/光照等模板；运行时由节点图生成实际实体。
不要假设编辑器里的实体在 PIE/成品中直接可见（没有节点图就是空画面）。

### ② 用离线工具搭节点图

```powershell
flyvibing-node-editor rules
flyvibing-node-editor entities scenes/<Name>.scene
flyvibing-node-editor build --spec spec.json --out graph.json
flyvibing-node-editor apply --scene scenes/<Name>.scene --graph graph.json
```

复杂范式优先用节点组（macro），不要复制几十个节点：

```powershell
# 查看组模板/参数
flyvibing-node-editor groups --scene scenes/<Name>.scene

# 示例：把一组 cue 分支写成参数（具体参数以 rules / README 为准）
flyvibing-node-editor apply-ops --scene scenes/<Name>.scene --ops ops.json --write
```

组参数修改后，必须确认它确实更新了成员节点的 `props`；组参数本身不是运行时数据。
尤其串口 `baud_rate`、并行口地址这类值，运行时读的是节点 props。

### ③ 可读性：alias / description / group

- 关键节点加 `@alias`；用 `set_alias` 或 `add_node.alias`。
- 每个组加 `description`（节点卡/组框可展开阅读）。
- 组要有真实 `GroupStart` / `GroupEnd`，不要只画视觉框。
- 用 `graph.fit` 或 `flyvibing-node-editor` 的布局工具整理视图。

### ④ 校验

```powershell
# 静态 + 假时间干跑（L1/L2）
engine-editor-cli validate
# 或离线
python -m flyvibing_node_editor.node_graph_validator scenes/<Name>.scene --frames 360

# 成品入口干跑（无窗口）
.venv-py314t\Scripts\python.exe Application\PlayerEntry.py <Name>.myproj --dry-run --frames 360
```

验收：L1 `0 error`，L2 `0 error`；side-effect 节点在干跑中只写 `ctx.emit_log`，不碰硬件。

### ⑤ PIE 实机验证

```powershell
engine-editor-cli call sim.play
engine-editor-cli call sim.state          # 应返回 Running
engine-editor-cli capture pie --out pie.png
engine-editor-cli call sim.stop
```

至少截取关键时间点（例如 MI 的 0–2 s class cue、2–6 s 重叠、6–10 s rest），确认：

- 可见 cue 与时间线一致；
- 并行/串口码值符合 README；
- 停止后没有残留实体、设备会话或错误日志。

### ⑥ 导出并验证成品

```powershell
engine-editor-cli call project.export target_parent=C:\path\to\out include_player=true
```

导出后进入成品目录，双击 `run_game.cmd`（或命令行启动）验证：

- 窗口正常显示（远程/无物理显示器环境先看渲染呈现层问题，不要误判为场景问题）；
- 场景/节点图从 `scenes/*.scene` 加载；
- `output/` 数据写入正确；
- 成品不包含 `extension.json` 声明 `"export": false` 的本地插件 fixture。

## 3. README 模板

每个 Example 的 README 至少写：

```markdown
# <Name>

## 范式
一句话说明实验任务与目标。

## 时间线
| 时间 | 事件 | 可见实体 | 码值/设备 |
|---|---|---|---|
| 0 s | ... | ... | ... |

## 节点图
- 入口事件：OnGameStart / OnFrameUpdate
- 关键组：@trial / @class_cue / ...
- 关键 alias 与参数：...

## 运行
- 打开方式：File -> Open Example -> <Name>
- 导出：project.export ...
- 设备：@device 逻辑名（不要写死 COMx）

## 修改
- 改臂数/码值/串口参数的具体位置
- 重新校验/导出的命令
```

## 4. 验收清单

- [ ] 场景有模板实体、相机、正确 `game_type`；
- [ ] 节点图有 `OnGameStart` 入口，场景运行后有内容；
- [ ] 关键节点/组有 alias + description；
- [ ] L1 静态校验 0 error；L2 干跑 0 error；
- [ ] PIE 关键帧截图与时间线一致；
- [ ] 成品 `run_game.cmd` 可启动，`output/` 可写；
- [ ] README 包含范式、时间线、码值/设备名、修改入口；
- [ ] 本地插件 fixture 不进入成品（`export:false` 契约）。

## 5. 常见坑

| 现象 | 处理 |
|---|---|
| PIE 空画面 | 没有节点图/没有 EntitySpawn；编辑器实体只是模板 |
| 改了串口/组参数但运行值没变 | 组参数 ≠ 节点 props；改 `SerialSend.props.baud_rate` 或重新展开组 |
| 成品窗口白屏但 PIE 内部抓帧正常 | 远程/无物理显示器呈现层问题，见 `Doc/Dev/remote_display_white_screen.md` |
| 设备换了机器打不开 | 用 `@device` 逻辑名绑定，不要写死 `COM3` |
| 导出后多出插件目录 | 游戏包只按场景节点按需带扩展；本地插件检查 `export:false`，安装包检查 `official_extensions.json` allowlist |

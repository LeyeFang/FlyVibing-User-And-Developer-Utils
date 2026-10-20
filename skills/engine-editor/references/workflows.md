# Engine 工作流配方（按需阅读）

> 主技能见 `SKILL.md`；op 参数细节见 `ops.md`。以下示例默认 PowerShell（数组/对象加单引号）。

## 1. 提示场景（cue）搭建与截图对比

目标：摆一个中心注视点 + 左右提示方块，截图给用户确认。

```powershell
engine-editor-cli call entity.add name=Cross
engine-editor-cli call entity.add name=L_Cue
engine-editor-cli call entity.add name=R_Cue
engine-editor-cli call component.add type=MeshRenderer id=Cross
engine-editor-cli call component.add type=MeshRenderer id=L_Cue
engine-editor-cli call component.add type=MeshRenderer id=R_Cue
engine-editor-cli call component.set id=L_Cue type=MeshRenderer fields='{"color":[0.2,0.7,1,1],"material_name":"Cue_Cyan"}'
engine-editor-cli call component.set id=R_Cue type=MeshRenderer fields='{"color":[1,0.6,0.1,1],"material_name":"Cue_Orange"}'
engine-editor-cli call entity.transform id=L_Cue position='[-2,0,0]' scale=2
engine-editor-cli call entity.transform id=R_Cue position='[2,0,0]' scale=2
engine-editor-cli call selection.set id=L_Cue          # 高亮 + gizmo（截图更直观）
engine-editor-cli capture editor --out cues.png
```

显隐对比（实验里常用）：

```powershell
engine-editor-cli call entity.visible id=L_Cue editor=false render=false
engine-editor-cli capture editor --out cue_hidden.png
```

相对调整（等同拖拽 gizmo）：`entity.transform id=5 position='[1,0,0]' relative=true`。

### ★ 让场景“可运行”（必须 — 否则 Play 后空画面）

编辑器实体只是**模板**；PIE 只显示节点图生成的内容。最低配 = `EntitySpawn` 生成实体：

```powershell
engine-editor-cli call graph.list                                  # 拿 OnGameStart 节点的 id
engine-editor-cli call graph.add type=EntitySpawn props='{"template":"Cross"}'
engine-editor-cli call graph.link from='{"node":<OnGameStart id>,"pin":"exec"}' to='{"node":<新节点 id>,"pin":"exec_in"}'
engine-editor-cli call sim.play                                    # 等 sim.state = Running
engine-editor-cli capture pie --out run.png                        # 看图确认不是空画面
engine-editor-cli call sim.stop
```

> 没有 EntitySpawn 的场景：`sim.play` 返回 `warning`（引擎兑底），Play 画面为空属预期语义。
> 复杂时序（trial / cue 显隐 / 触发脉冲）→ 用 node-graph skill 的 build_graph spec 通道生成。

## 2. 从零批建节点图（batch JSON — 让场景可运行的必要路径）

`ops.json`：

```json
[
  {"op": "graph.add", "args": {"type": "OnGameStart", "position": [60, 60]}},
  {"op": "graph.add", "args": {"type": "EntitySpawn", "props": {"template": "DefaultCube"}, "position": [260, 60]}},
  {"op": "graph.link", "args": {"from": {"node": 1, "pin": "exec"}, "to": {"node": 2, "pin": "exec_in"}}}
]
```

> 节点 id 按添加顺序递增（从当前 `next_id` 开始）；不确定时先 `graph.list` 看最新 id。
> 引脚名规则（exec 链、数据引脚 kind/data_type、可选引脚）见引擎仓库 `packages/node-editor/rules.md`
> 与 `Doc/Dev/node_editor_protocol.md`；不确定引脚名时 `graph.list` 某个节点会带 `pins` 表。

```powershell
engine-editor-cli batch ops.json
engine-editor-cli validate                    # 干跑校验（默认 summary）
```

## 3. 图导出 / 导入（落盘往返）

```powershell
# 导出：带 path → 自动 inline=false（只回 counts + saved_path，不把整图打进上下文）
engine-editor-cli call graph.export path=packages/editor-mcp/tmp/mi_graph.json include_rules=false
# 导入：validate_first 默认开（静态有 error 会拒绝；强制用 validate_first=false）
engine-editor-cli call graph.import path=packages/editor-mcp/tmp/mi_graph.json
```

- 需要检查文件内容时：只读你关心的片段（用编辑器/工具打开），不要整文件回贴。
- `include_rules=true` 会把规则文档 `_rules` 写进 JSON（供离线消费）；agent 一般传 `false`。

## 4. 打开工程 → 切场景 → 校验 → 运行 → 截图

```powershell
engine-editor-cli call project.open path=../MI-SSSEP/Experiment/Paradigm/project/MI-SSSEP/MI-SSSEP.myproj
engine-editor-cli call scene.list
engine-editor-cli call scene.switch name=MI-SSSEP
engine-editor-cli validate --save packages/editor-mcp/tmp/validation_mi_sssep.json
engine-editor-cli call sim.play               # 等 sim.state 变 Running（PIE 帧末起）
engine-editor-cli capture pie --out run.png
engine-editor-cli call sim.stop
```

## 5. 干跑校验（dry-run）语义与排错

- 校验在**引擎内服务**执行：静态规则 + fake-time 模拟（默认 360 帧 @60fps，seed=0 确定性）。
- `source=canvas`（默认，当前画布）/ `source=graph`（先验 agent 生成的图，不用先导进画布）：
  `engine-editor-cli validate --source graph --graph @proposed.json`
- 报告结构：`report.ok` / `counts` / `static.errors/warnings` / `runtime.errors` / `log`；
  `static` 与 `runtime` 条目带 `node_id` → 用 `selection.set id=<node_id>` 在画布定位，`graph.set_props` 修正后重校验。
- **副作用隔离**：设备走 stub、实体生成/显隐等副作用只记日志（dryrun# 命名空间，结束自动清理）。
- 注意：`EntityGet` 类节点在干跑中查不到真实实体（提示 `[EntityGet] 'x' not found`，不计 error）——防御写法不受影响。
- 完整日志：`--detail full` 或 `--save report.txt`（文本更易读）。

## 6. MCP lite 等价调用（无终端时的通道）

```
engine_help()                                  # op 目录
engine_help("entity.transform")                # 单 op 详情
engine_call(op="entity.add", args={"name": "MCP_Cue"})
engine_batch(calls=[{"op": "entity.add", "args": {"name": "A"}}, {"op": "sim.play"}])
engine_validate_graph(source="canvas", detail="summary")
engine_capture(target="pie")                   # 图像直回（需要看画面时）
engine_launch(engine_root="C:/path/to/MyGameEngine-Python", port="auto", language="zh",
              settings={"ui.font_scale": 1.15})  # 启动 + 自动端口；后续调用自动使用该端口
```

旧工具名兼容：`engine_call(op="editor_run_pie")` ≡ `sim.play`（别名表见 ops.py）。

### 6.2 扩展节点与“节点池”（不连线）

```powershell
engine-editor-cli call graph.types owner=device          # 看扩展 node_pack 的 type/pins/fields
engine-editor-cli call graph.types category=Algorithm    # 看 BCI 节点
engine-editor-cli call graph.add --json @args.json       # {"type":"SerialSend","props":{...}}
engine-editor-cli call graph.list                        # 未连线节点也在画布/节点池中
```

`graph.add` 只创建节点，不要求 `graph.link`；适合外部 agent 先批量摆节点、再逐步接线。
扩展节点必须由已发现的 `node_pack.py` 注册；未安装 pack 时该类型不可添加（会提示 `graph.types`）。

### 6.1 多引擎 / 多 agent（端口互不串话）

```powershell
# agent A
engine-editor-cli launch --port auto --language zh --set ui.font_scale=1.15
# -> {"ok": true, "port": 8977, ...}
engine-editor-cli --port 8977 call sim.state

# agent B（同时运行；自动拿到 8978）
engine-editor-cli launch --port auto --language en
engine-editor-cli --port 8978 call sim.state

engine-editor-cli engines   # 核对所有活动实例
```

- 每个 agent 必须记住自己的 `port`；CLI 用全局 `--port N`，MCP 用 `engine_launch` 的返回值（进程内自动记住）。
- 不要复用默认 8977 同时操作两个实例；否则会出现“另一个窗口在动”的串话。
- Settings 面板的 Port 只决定**手动启动**的默认端口；`--port` / `MGE_EDITOR_MCP_PORT` 优先。

## 7. 脚本模式模板（扫描 + 过滤输出）

```python
# filter_report.py — 只输出有问题的节点，避免全量日志进上下文
r = engine.ok("graph.validate.start", source="canvas", frames=120)
tid = r["task_id"]
while engine.ok("graph.validate.state", task_id=tid).get("state") == "running":
    time.sleep(0.1)
rep = engine.ok("graph.validate.report", task_id=tid)["report"]
print("ok:", rep["ok"], "counts:", rep["counts"])
for e in rep["static"]["errors"] + rep["runtime"]["errors"]:
    print("ERR", e.get("code"), "node", e.get("node_id"), e.get("message"))
```

```powershell
engine-editor-cli exec filter_report.py
```

## 8. 编辑器未就绪时的行为约定

- 所有命令在编辑器未运行时**立刻返回** `编辑器未运行（127.0.0.1:<port> 无监听）— 请先启动 startup.bat。`（exit code 1）。
- 不要自动反复重试；提醒用户启动编辑器后继续。

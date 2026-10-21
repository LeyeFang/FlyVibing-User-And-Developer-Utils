# 设备 IO 层开发协议（Application/Functions）

> 适用：`SerialParallelDevice`（串口/并口）、`VirtualDevice`（EEG 设备模块：服务进程 + 虚拟信号发生器等）等硬件集成。
> 节点求值器如何调用设备见 `node_editor_protocol.md`；UI 控件见 `ui_protocol.md`。

---

## 1. 域地图与两种既有架构

| 模块 | 架构 | 要点 |
|---|---|---|
| `Application/Functions/SerialParallelDevice/` | 全局单例 + I/O 线程 + 队列 | `api.py`（start/stop/send/write_parallel）、`io_thread.py`、`state.py`、`test_hooks.py`；无驱动优雅降级；5ms 自动复位 |
| `Application/Functions/VirtualDevice/` | 设备模块（会话注册表 + 后端协议 + 环形缓冲 + 服务进程 + 面板扩展） | `Device.py`（后端无关：配置/缓冲/会话/注册表/落盘）、`ServiceProtocol/ServiceHost/ServiceClient.py`（服务进程通信，见 §7）、`SigGen.py`（虚拟信号发生器后端）、`service.py`（服务入口）、`extension.py`（面板）、`__init__.py`（门面路由; 2026-10-16 EEGDevice 并迁） |

共同约束：
- **不得反向依赖 Engine / Editor**；被求值器（核心 `Application/Core/NodeGraph/evaluators/*` 或扩展目录 `Application/Functions/VirtualDevice/evaluator_*.py`）调用。
- 门面 API 返回 `(ok, detail)` / `(result, detail)`，**不向上抛异常**（求值器把它转为 error 日志）。
- 真实不可用（驱动缺失/设备未连）→ 明确报错 + 优雅降级，**绝不静默伪造数据**。

---

## 2. 真实 / 空跑双后端契约（本层核心，MCP 空跑依赖）

- 后端接口：`DeviceBackend`（`configure / start / stop / close / pump / info`）。
- 空跑后端（设备族 stub）规则：
  - 不触硬件、不落盘、不起线程（`pump` 同步补齐数据）；
  - **确定性**：同一时间轴 → 同一数组（干跑可复现）；
  - 合成总量封顶为窗口容量（避免长时间干跑占内存）；
  - 通过 `on_block` 走**与真实后端相同的数据通路**（环形缓冲/全量录制逻辑一并被验证）。
- 选择方式：门面 `_make_backend` 路由 —— 干跑（`ctx.dry_run=True`）走进程内确定性 stub 后端（无进程、零副作用）；真实模式默认走**品牌服务进程**（独立进程 + 协议通信，见 §7）；逃生门 `MGE_EEG_TRANSPORT=inproc` 退回进程内真实后端。
  **真实模式绝不回退 stub**（防实验数据污染），干跑才走 stub。
- 新增设备时同步实现两套后端 + 在 `Doc/Dev/README.md` §3 的验收命令下跑通。
  **纯软件设备例外**（如 `SigGen` — 虚拟信号发生器）：单一后端 + 构造参数 `dry_run` 控制
  `is_stub`/落盘（干跑不落盘、真实落盘），同样走会话/缓冲/导出全通路。

---

## 3. 数据与落盘约定

- 单位/类型：设备数据统一为 **float32、µV**（SDK/驱动已定标）。
- **窗口缓冲**：形状 `(channels, capacity)`，`capacity = buffer_seconds × fs`（上限
  `MAX_BUFFER_SAMPLES = 4e6`/通道）；环形写入、旧数据覆盖；快照按时间序，未填区 = 0，
  有效样本数单独给出（`samples`）。
- **导出文件**：形状 `(samples, channels)`（便于 np.load/MNE 复用）。
  - `npz`：keys = `data / fs / channel_names / serial / duration_s`（压缩）；
  - `csv`：首行 `sample,<ch names...>`，行 = 采样点；
  - 两种格式都附同名 `.json` 元数据（设备信息、滤波器索引、起止时间、模式 stub/device、文件清单）。
  - 文件名：`<安全化设备名>_<YYYYmmdd_HHMMSS>.<ext>`；目录来自 Init 节点 `save_dir`
    （默认 `.` = 当前目录）。
- **附加通道（触发合成列, 2026-10-16）**：硬件块可带 +1 列（16 线触发合并）——显示/节点只消费
  EEG 主通道，录制保留原列（`channel_names` 末列 `TRIG`）；事件通路 = `get_trigger_events`
  （沿变检出 `[{sample, t_s, code}]`，增量游标）+ 落盘元数据 `trigger_events`；无硬件回归用
  合成触发源 `SigGenConfig.trigger_every_s`。
- Stop 语义：`save_scope=session` 保存 Start 以来全部数据（内存拼接，受
  `MAX_RECORD_BYTES = 2 GiB` 保护，超限仅窗口继续更新）；`save_scope=buffer` 只保存当前窗口。
- `close_all()`：Runtime 停止安全网（**不保存**，丢弃数据）；由 `GameRuntime.start/stop` 调用。

---

## 4. 线程模型与自由线程引擎（重要）

- 引擎以 `-Xgil=0`（Python 3.14 自由线程）运行：**没有 GIL 保护**，跨线程共享结构必须加锁。
- 现有实现：`RingBuffer` 自带锁；`RecordingSession._on_block` 会话锁 + 录制内存保护；
  `_REGISTRY` 注册表锁。
- 真实采集：worker 线程跑 `d.GetData(user_block, more)`；`stop()` 置 flag → `more` 返回 False
  → GetData 内部 StopStreaming/StopAcquisition 收尾 → join。
- 空跑：`pump(elapsed_s)` 由**图线程**同步调用（无并发）。
- 时序坑（已修复，勿回退）：`RecordingSession.start()` 必须**先** `backend.start()`
  **再** `backend.pump(elapsed_s)` —— 空跑后端在 pump 中锚定仿真起点；顺序反了会得到空数据。

---

## 5. Runtime 集成

- `GameRuntime.start()`：清理上次残留 EEG 会话（异常退出保护）；`stop()` 末尾再次
  `close_all()`（图内 `OnGameStop` 链（含设备 Stop/Kill 节点）已执行完，此处兜底）。
- PIE 重复运行：同名设备 Init 会**替换**旧会话（门面内先 kill 再注册）。
- 图内生命周期（Init→Start→Get…→Stop→Kill）与 Runtime 安全网是两层保障，缺一不可。

---

## 6. 设备池 (Device Pool)

设备池 = 设备的分组 / 生命周期 / (未来) 进程组与同步域锚点（模块级注册表, `Device.py`）。

- 门面 API：`create_pool / destroy_pool / add_to_pool / pool_of / pool_members / list_pools / reset_pools`；
  隐式 `global` 池始终存在（未入显式池的设备），不可创建/销毁。
- **排他成员制**：一个设备同一时刻只属一个池；`add_to_pool` 到新池 = 移动（日志记录）；
  `kill_device` 自动脱池；`destroy_pool` 成员回落 `global`；`close_all` 连池一并清空。
- 池作用域绑定：`resolve_session(name, pool)` —— `name` 非空按名称解析；空名 + `pool=None`
  保持旧语义（全注册表唯一会话自动绑定）；空名 + 池 → 池内唯一设备自动绑定（多设备报歧义）。
- 节点侧（IO ▸ Pool）：`CreateDevicePool ⇄ KillDevicePool` 强制配对（校验 + 编辑器级联，
  与设备族同一套规则）；`AddToDevicePool` 读 Init `device` pin 的会话键入池 —— **必须与对应
  Init 排在同一条 exec 链、紧跟其后执行**（pin 值仅一个 trigger 内有效）。
- 键规则单点定义在 `graph_constraints`（`device_session_key` / `pool_key`），
  评估器 / 校验器 / UI 下拉三处共用，禁止另写变体。
- 干跑隔离：池与会话共用 `dryrun#` 命名空间，任务结束由 `validation/dry_run.py` 一并清理。
- **设备模块布局（2026-10-16 终态, 取代品牌目录制）**：设备族 = 单目录自包含模块
  （`Application/Functions/VirtualDevice/`：面板 + 后端 `SigGen.py` + 服务 `service.py` + 会话核心 `Device.py`/`Service*.py`）;
  外部品牌 = 独立目录 + 自有环境经服务协议接入（见 §7）。导出**按需包含**：项目未引用某设备时，
  其目录（含未来成品环境）不随导出。设备池 = 进程组管理单元（池条目 `meta` 预留进程句柄/启动参数）。
  延伸规则：`Application/Functions/` 下未来一律按**终端可安装的可选拓展**演进（仅备忘，暂不施工）。
- **面板参考实现**：`Application/Functions/VirtualDevice/`（波形监视面板 — watch/record + 示波器 +
  显示滤波 + `ext.virtual.*` 九件套; 见 `Doc/ExtDev/extension_dev_protocol.md` §7）。

---

## 7. 品牌服务进程（独立进程 + 协议通信）

品牌目录 = 独立进程文件应用：后端实现 + `service.py` 入口 +（未来）随目录携带的环境。
引擎与品牌之间只经一条协议通信，节点图侧零改动。

| 组件 | 位置 | 职责 |
|---|---|---|
| `ServiceProtocol.py` | 共享 | 帧格式 `[4B 大端长度][pickle(protocol=4)]`；3.9+ 兼容（服务可能跑在低版本环境） |
| `ServiceHost.py` | 服务侧 | 命令循环 hello/init/start/pump/stop/kill/info/**impedance**/shutdown；push 模式采集线程加锁写 socket |
| `ServiceClient.py` | 引擎侧 | `ServiceBackend`（DeviceBackend 实现）；pump/push 双模式；rid 路由 + 单读者线程 |

- **数据模式**：`pump`（合成后端——块随响应同步返回，与进程内逐位一致，确定性来源）；
  `push`（真实硬件——start 后采集线程持续推送，引擎接收线程写会话环形缓冲）。
- **保存仍在引擎侧**：服务只提供数据；npz/csv/元数据落盘逻辑与进程内完全一致。
- **生命周期**：VirtualDevice 引擎自动拉起（`sys.executable`，引擎环境，动态端口，日志在系统 temp）；
  外部品牌服务**三级路由（2026-10-15 模式）**: 显式端点（`MGE_EEG_SERVICE=host:port`）连接 →
  设备配置 `service_python` + `service_module`（自有环境 python + 品牌服务模块；或 env
  `MGE_EEG_SERVICE_PYTHON` / `MGE_EEG_SERVICE_MODULE`）**自动拉起**（动态端口，断开回收子进程）→
  否则直连默认端口（**3s 快速失败** + 启动指引）；
  客户端断开 → 服务退出（引擎崩溃自动清理）；`kill/close` 发 shutdown 并回收子进程。
- **连通失败诊断**：报错含启动提示 + 服务日志尾部（自动拉起场景）；
  两阶段失败点显式区分（2026-10-15 实战教训）——`cannot connect ...` = 服务没起（A: 自动拉起 / B: 手动启动），
  `init failed ...` = 服务已起但设备被占用（如厂商软件独占），两者文案各不相同。
- **服务探针（模式）**：品牌服务应提供秒级只读连通探测（无副作用），供面板/agent 排障（新品牌落地时随服务实现）。
- 待办：PIE start/stop 的 `close_all` 与会话联动政策、品牌目录随环境打包（规划见 §6）。
  （服务协议无头回环已重建 — 2026-10-16: stub 品牌服务 `Test/Application/Functions/_brand_stub_service.py`
  + `test_siggen_device.py` §6 — 自动拉起 / hello / 数据往返；真实品牌随新服务落地再验。）

---

## 8. 测试

```powershell
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_siggen_device.py      # 设备族（虚拟信号发生器: 配置/会话/落盘/干跑/配对）
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_serial_parallel_device.py
.venv-py314t\Scripts\python.exe Test/Application/Functions/test_device_alias.py       # 逻辑设备名（@alias 跨机器）
```

- 干跑用例必须断言：静态校验零错误、`events_by_type` 覆盖全链路节点、干跑后注册表为空。
- 测试模式遵循 `Test/_path_setup.py` 引导；参考 SPD 测试的 `check()` 累加式写法。

---

## 9. 已知坑（实战教训）

1. 空跑 pump 时序（§4）—— 顺序错误的症状是"数据全 0 / valid=0"。
2. 真实模式不得伪造数据（§2）—— 采集失败要显式报错，宁缺毋假。
3. 内存保护：缓冲区（`MAX_BUFFER_SAMPLES`）与全量录制（`MAX_RECORD_BYTES`）都有上限，
   超限行为已定义（截断 / 仅窗口更新），新增设备沿用同一策略。
4. 自由线程下忘加锁 → 概率性数据错乱，且很难复现；所有跨线程结构一律加锁。
5. 设备释放要幂等：`close_all` / `kill` 允许重复调用（异常保护包裹）。
6. 不要在 import 期做设备探测（`probe_environment` 只做只读探测且吞异常，供日志用）。
7. 服务命令顺序：`shutdown` 必须在任意状态可用（未 init 也允许）——否则 init 失败的收尾路径卡死；
   `kill` 无会话时宽容返回（幂等）。服务进程客户端断开即退出（不驻留）。
8. 控制台编码：GBK 环境**管道输出**（如 `| Select-Object`）遇非 GBK 字符（`↔` 等）会 UnicodeEncodeError
   —— 测试脚本打印只用 GBK 覆盖的符号（`──` `×` `→` 可用，箭头互指用 `<->`）。

---

## 10. 两级设备身份与跨机器迁移（`@alias` — 2026-10-12 新增）

**问题**: 场景节点里写死 `COM3`，换机器 / 换 USB 口后设备"找不到"，实验设计被物理拓扑绑死。

**方案 = 两级身份**（设计真相在场景，物理真相在机器）:

| 层 | 写在哪 | 内容 | 谁负责 |
|---|---|---|---|
| L1 逻辑设备名 | 场景节点 `props.port = "@mibox"` | 与机器无关的**实验设计** | 场景作者（写一次，跨机器不变） |
| L2 物理端点 | `%APPDATA%/MyGameEngine/devices.json`（`MGE_DEVICES_FILE` 可覆盖 — 测试沙箱） | 本机上 `@mibox` **当前**是哪个 `COMx@baud` | 每台机器绑一次（面板 / agent） |

- 注册表实现: `Application/Core/DeviceRegistry.py` —— 原子写（tmp+replace）、线程锁、损坏文件
  容错为空表；名称 `^[A-Za-z][A-Za-z0-9_.-]{0,31}$`；字段 `transport/port/baud/updated/hint`。
- **单一解析点**: `SerialParallelDevice.serial_manager.resolve_port(text)` —— `""` → `ValueError`；
  `@name` → 注册表 → 物理端口；其它 → 原样直通（裸 `COMx` 仍可用，兼容旧场景）。`send` /
  `start_watch` 在**入队前**解析；扩展面板与节点走同一条路径。
- **未绑定 = 显式报错，绝不静默回退**: `DeviceUnresolved` 消息含"绑在哪、怎么绑"
  （面板 Device names 段 / `ext.device.bind_alias name=… port=…`）与注册表路径。
- **静态校验（提前发现）**: 校验规则 13 扫描节点 props 中任意 `@` 前缀值 → 本机未绑定则 warning
  `device_alias_unresolved`（打开场景即提示，不必等运行）；已绑定不报；裸端口不参与。
- **求值器不再猜端口**: `SerialSend.port` 默认值由 `"COM1"` 改为 `""`（**兼容性变更**）——
  未配置端口时显式 `emit_log(..., "error", ...)` 并跳过，不再往 COM1 盲写。
- **日常动线（迁移一台机器）**: 插设备 → 面板 Device names 段 → [Bind current port]
  （或 agent `ext.device.bind_alias name=mibox`）→ 需要时 [Migrate N node(s) -> @mibox] 把场景里
  裸 `COMx` 的节点批量换成 `@mibox`（= `ext.device.bind_nodes`，`dry_run` 可先预演）。
- **官方示范（面板 → 场景 同步）**: 面板按钮与 agent 调用**同一个**操作实现（动作单点），
  经 `ctx.graph`（`capabilities` 含 `"graph"` 才注入；只读 `nodes/find` + 受控 `set_props`）
  读写当前图，扩展不 import 编辑器层。`ext.device.status` 一并返回别名视图。
- 测试: `Test/Application/Functions/test_device_alias.py`（31 checks — 注册表 / 解析 / 发送链路 /
  求值器 / 校验 / 扩展 ops；注册表用 `MGE_DEVICES_FILE` 沙箱，不污染真实机器配置）。
- 规划（未做）: 自动重绑 —— `hint` 已预留 `usb_serial` / `vid_pid`，用于同型号设备换口自动认出。


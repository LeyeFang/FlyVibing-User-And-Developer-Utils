# 扩展开发规范协议（Extension Development Protocol）

> 配套任务指南：[UI 开发](ui_development.md) · [节点开发](node_development.md) · [Example 开发](example_development.md)。
>
> 读者: **外部/无上下文的开发者与 agent**（模拟社区生态 — 只有本文件 + 仓库即可开工）。
> 架构背景: `extension_protocol.md`（三层高度模型 / 三档侵入 / 兼容机制）。
> 状态: **M0 已实装 + M1 部分实装**（`ctx.ui.register_window` 2026-10-11；
> 官方示例 = `Application/Functions/SerialParallelDevice`（设备 IO + 事件流面板）与 `Application/Functions/VirtualDevice`（虚拟设备 + 波形监视面板））；
> M1+ 剩余能力在本文件中以 `[M1 待]` 标注（当前为设计约束, 实装后按其验收）。

---

## 1. 适用范围与阅读顺序

1. 本文件（开发规范, **必读**）→ 2. `extension_protocol.md` §1/§3/§4（架构与侵入纪律）→
3. 相关领域协议（`node_editor_protocol.md` / `threading_protocol.md` / `device_io_protocol.md`）。

**扩展（Extension）** = 编辑器应用层的功能模块。当前规划的默认扩展（状态档案在各自目录 `TODO.md`）：

| id | 目录 | 状态 |
|---|---|---|
| `sigproc` | `Application/Functions/SignalProcess/` | skeleton（可装载样例） |
| `bci` | `Application/Functions/BCIAlgorithm/` | partial（内核算已实现, 待迁移） |
| `device` | `Application/Functions/SerialParallelDevice/` | v0.2.0（设备 IO + 事件流监视面板, 见 §7） |
| `virtual` | `Application/Functions/VirtualDevice/` | v0.1.0（**波形监视面板范例**: watch/record + 显示滤波 + `ext.virtual.*` 九件套, 见 §7） |

## 2. 快速上手（最小扩展）

```
Application/Functions/MyThing/  # 内置扩展（随仓库分发）
  extension.json              # ① 清单
  extension.py                # ② 入口（headless 安全 — 禁止顶层创建 imgui context/窗口/GL;
                              #    纯模块导入 imgui 允许, 见 §12.3）
  TODO.md                     # ③ 状态档案（计划/进行中的扩展必须有）
```

`extension.json`:

```json
{
  "id": "mything",
  "name": "My Thing",
  "version": "0.1.0",
  "api_version": "1",
  "maturity": "skeleton",
  "description": "一句话说明",
  "entry": "extension.py:create_extension",
  "capabilities": ["ops"],
  "requires": []
}
```

`extension.py`:

```python
from Application.Core.Extension.ExtensionBase import ExtensionBase

class MyThingExtension(ExtensionBase):
    id = "mything"
    name = "My Thing"
    version = "0.1.0"

    def on_load(self, ctx):
        self.ctx = ctx
        ctx.ops.register("info", self._op_info, summary="状态查询")
        ctx.log("loaded")

    def _op_info(self, args: dict) -> dict:
        return {"hello": "world"}

def create_extension() -> MyThingExtension:
    return MyThingExtension()
```

启用与验证（编辑器运行中）：

```
engine-editor-cli call extension.enable id=mything     # 或 Settings ▸ Extensions 勾选（§3.3）
engine-editor-cli call extension.list                  # 应出现 mything + ext.mything.info
engine-editor-cli call ext.mything.info                # 扩展 op 直接可调（ext.* 透传）
```

> 开发期挂在 `Application/Functions/` 的扩展默认是 `local`（**opt-in**，需勾一次，见 §3.3）；
> 只有 allowlist 内的 `builtin` 才恒激活，`extension.enable` 对它只是兜底。
> 没有面板的扩展不会出现在主菜单栏 —— 管理在 Settings ▸ Extensions。

## 3. 目录与命名规范

- 目录名建议 = id; manifest 的 `id` 是唯一权威（`^[a-z][a-z0-9_]*$`）。
- 所有对外贡献**强制命名空间**: ops = `ext.<id>.<name>`; 未来节点 = `ext.<id>.<TypeName>`。
- 私有实现文件不限; 资源放扩展目录内（只读）; 可写数据一律用 `ctx.data_dir`。
- **同目录私有模块**: 加载器会把扩展目录加入 `sys.path` → 可直接裸 `import <module>`
  （扩展目录内的私有子模块即此模式）; **不要**用包相对导入（扩展不是包）;
  机制标注 M0, 打包期可能收窄, 以本节为准。
- **可导入的引擎面**（白名单, 与审查器 **C6** 同源 — 以审查器为准）:
  `Application.Core.Extension` / `Application.Functions`（设备门面等）/
  `Application.Core.Events` / `Application.Core.ThreadRegistry`。
  其余 `Application.*` → 审查器 WARN（人工复核）; 禁止修改 `Application/**`（见 §5 侵入纪律）。
- 不要把扩展内部文件丢到仓库其它区; 不得修改 `Application/**`（见 §5 侵入纪律）。

### 3.1 开发态 vs 发布态：扩展到底从哪加载（2026-11-01 补）

两种形态的**扫描根不同**，混用是"扩展明明装了却没生效"的最常见原因：

| 形态 | 扩展扫描根 | 典型做法 |
|---|---|---|
| 开发仓（dev） | `<EngineRoot>/Application/Functions/<YourPack>/` | 开发时把目录（或 junction）挂到这里，重启编辑器即被发现 |
| 发布包 / 导出成品（release） | `<InstallRoot>/Application/Functions/<YourPack>/`（随安装包/wheel 一起分发） | 由 `official_extensions.json` allowlist 决定是否打进安装包 |

实操纪律：

1. **开发期用 junction 挂载**，不要复制粘贴 —— 复制会产生两份分叉：
   ```powershell
   New-Item -ItemType Junction -Path "C:\WorkSpace\FLY\FlyVibing-Engine\Application\Functions\missssep" `
            -Target  "C:\WorkSpace\FLY\Phase-Encoded-SSSEP-MI-FlyVibing-Extension\missssep"
   ```
2. **迁移到发布形态**时把目录实体拷进 `Application/Functions/`，并在
   `official_extensions.json` 中登记（不登记 = 不进安装包；`export:false` 只影响**游戏导出**，
   不影响安装包）。
3. 场景里留了 `ext.<id>.*` 节点但扩展没启用 → 节点保留但**不求值**：
   `graph.validate` 报 `unknown_type`，`sim.play` 直接拒绝启动（见 `dev/scene_format` §1）。
   这是特意的硬拦截 —— 别把它当成"图没生效的玄学"。
   `extension.enable` 之后画布会**就地补全**这些节点（不需要重载场景），
   `sim.play auto_fix=true` 可以一键 enable 后直接跑。
4. `extension.list` 是运行期的唯一事实源（`enabled` / `disabled` / `broken`）；`broken`
   的 `error` 字段会给出 manifest / import 的具体原因。

### 3.2 面板关闭语义：`close_policy` 别乱用 `disable`（2026-11-03 补）

`ctx.ui.register_window(..., close_policy=...)` 有三档，默认 `"hide"`：

| 值 | 用户点窗口 X 之后 | 适用 |
|---|---|---|
| `"hide"`（默认） | 只隐藏窗口；扩展继续运行，可从菜单/`extension.enable` 重新打开 | **设备类 / 后台服务类扩展**（图上的节点依赖它，用户只是"不想看了"） |
| `"disable"` | 请求停用整个扩展（持久化到下次启动，其 `ext.<id>.*` 节点立刻变成未注册） | 极少数"面板就是功能本体"的扩展 |
| `"custom"` | 只回调 `on_ui_event`，由扩展自己决定 | 自定义生命周期 |

⚠️ 对**设备/数据采集类**扩展用 `disable` 是反直觉的：用户的意图通常是"收起面板"，
结果却让整张图在下次 PIE 时被预检拒绝。宿主的边界提示：`extension.disable`
（含面板 X 触发的停用）在画布上还有该扩展节点时会返回
`unresolved_nodes` + 警告，并在控制台点名。

### 3.3 激活策略与入口分工（2026-11-10 起，改变了默认行为）

**内置由 allowlist 定义，不由目录定义；面板决定菜单。**

| 扩展位置 | `scope` | 激活 | 谁管启停 |
|---|---|---|---|
| `<EngineRoot>/Application/Functions/**` **且** ∈ `official_extensions.json` allowlist（= `.gitignore` 白名单） | `builtin` | **恒激活**（`always_on=true`，不可停用） | 无人管 —— 装好即用 |
| `<EngineRoot>/Application/Functions/**` **但不在** allowlist（本地/社区夹具，如 Gtec、mi-sssep） | `local` | 状态文件 opt-in（默认停用） | **Settings ▸ Extensions** 页勾选 |
| `<APPDATA>/FlyVibingEngine/extensions/**`（用户装） | `user` | 状态文件 opt-in（默认停用） | **Settings ▸ Extensions** 页勾选 |

> **为什么不是「在 Functions 里就算内置」**：`Application/Functions/` 整个目录在 `.gitignore` 里，
> 只有放行行 `!Application/Functions/<Dir>/` 覆盖到的目录才随仓库/安装包分发。本地夹具
> （社区插件的开发副本）也常驻该目录，它们不进安装包、也不该被锁成不可停用。
> 判定唯一实现：`ExtensionManager.scope_of()`；两处白名单的镜像关系由
> `Test/Application/Extensions/test_extension_builtin_scope.py` 守卫（漂移即红）。

安全模式：`FVE_EXTENSIONS_BUNDLED=off`（旧 `MGE_` 前缀同样生效）→ builtin 也回到 opt-in，
用于排查"某个内置扩展把编辑器搞崩了"。此时 `extension.list` 每个 builtin 项 `always_on=false`。

**两个入口各管一半，别再混着找：**

| 入口 | 显示什么 | 用途 |
|---|---|---|
| 主菜单栏 **Extensions** | **只有 `has_ui` 的扩展**（`capabilities` 含 `ui`，或确实注册了面板） | **面板开关**：勾选 = 该扩展至少一个窗口可见（点击 = 显示/隐藏，不改变启停） |
| **Settings ▸ Extensions**（`order=20`） | **全部扩展**（含无面板的后台扩展、broken、planned） | 唯一的管理面：启停、**面板显隐**、诊断（目录/scope/capabilities/解释器/示例根/已注册 op/错误原因） |

> 无面板扩展（`ops` / `nodes` / `examples` / `device` 类）**不会**出现在主菜单栏 —— 这是有意的，
> 否则菜单会被一堆"点了没反应"的条目填满。它们的开关在设置页。

`has_ui` 的两条判据（任一成立）：manifest `capabilities` 声明 `ui`（**意图** — 未启用时菜单也能
留下入口）；或当前确实注册了 `ExtensionPanel` 窗口（**事实** — 兜住"没声明但用了 `ctx.ui`"）。
`extension.list` 每项都回 `scope` / `always_on` / `has_ui`，agent 用这三个字段判断该去哪儿找。

**对作者的影响（必读）**

1. 开发期把扩展挂在 `Application/Functions/` → 它是 `local`：**默认停用**，在
   Settings ▸ Extensions 勾一下即可（`extension.enable id=<你的 id>` 等价，会持久化）。
   只有 allowlist 内的才 `always_on`、`extension.disable` 会报错。
2. **示例（`Examples/`）跟着扩展的启用状态走**：`local` / `user` 扩展停用时，它的示例
   不会出现在 `File ▸ Open Example`。为避免"注入了却没出现"的误判，菜单在底部会显示
   灰字 `"<扩展> — N 个示例（扩展未启用）"`，点一下就地启用。
3. 菜单里"看不到我的扩展"现在有明确答案：**没面板就不在菜单里**，去 Settings ▸ Extensions 找。
4. `extension.enable id=<builtin>` 仍然可用，但语义变成"确保已装载 + 显示它的面板"，不写状态文件。
5. **菜单勾选 ≠ 扩展启用**（2026-11-13 起）：勾选只表示面板可见。以前两者共用同一个勾选框，
   于是出现"菜单勾着、界面上却看不到面板"的假象（扩展是启用的，只是窗口被隐藏了）。
   现在的关系是单向的：启用 → 可以显示面板；隐藏面板 → 仍然启用。

## 4. manifest 参考（extension.json）

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 唯一标识; 命名空间前缀; 全局不可重复（重复 → 后加载者 broken） |
| `name` / `version` | ✅ | 显示名 / semver |
| `api_version` | ✅ | 当前仅支持 `"1"`（或 `1.x`）; 不匹配 → broken（菜单灰显原因） |
| `maturity` | ✅ | `planned` / `skeleton` / `partial` / `stable` — 设置页与 `extension.list` 展示 |
| `entry` | 有代码则必填 | `"extension.py:create_extension"` 形式; **文件缺失 → broken**; 省略 = 仅计划（不可启用） |
| `description` | 建议 | 设置页 / 菜单 tooltip / 文档 |
| `provider` | 可选 | 扩展自带的 Example/节点默认签名（`@ACME`）；缺省 `@<id>`。单个 `.myproj` / 节点仍可用自身 `provider`/`signature` 覆盖 |
| `capabilities` | 建议 | 声明所需能力。**合法值集**（与审查器 M5 同源）: `ops` / `ui` / `nodes` / `threads` / `jobs` / `settings` / `device` / `graph` / `examples`。语义见 §6 能力表；`requires` 暂仅解析展示（依赖拓扑 M3） |
| `export` | 可选 | 默认 `true`。仅控制 **游戏导出**：`false` = 该扩展目录不进入 `File ▸ Export` 游戏层（即使场景用到其节点也会告警并排除）；**不影响安装包**——安装包按 `Application/Functions/official_extensions.json` mainline allowlist 分发。导出清单 `export_excluded` 会记录路径 |
| `python` | 可选 | 解释器协议（§11.1）：`"engine"` 简写，或 `{mode, path, requirements, probe}`。缺省 = 引擎解释器；依赖冲突时声明 `venv` / `path`。产物侧另需 `python.runtime`（§11.2，**导出强制**） |
| `device_aliases` | 可选 | 声明本扩展提供**逻辑设备名**（`@alias`）能力：`{"module": "device_registry", "dir": "."}`。核心 `Application.Core.DeviceAliases` **只读这个键**惰性发现提供者 —— 于是离线校验器、以及用户停用本扩展时的编辑器都能读到机器侧台账（迁移前由核心直接读文件，能力等价）。模块导入时应调用 `DeviceAliases.register(<id>, <module>)`。审查器 M9 校验模块文件存在 |

**状态语义**（`extension.list` / 设置页）: `planned`（无 entry）· `disabled`（可装载未启用）·
`enabled`（已装载）· `broken`（manifest/加载错误 — 原因在 `error` 字段）。
另有三个入口相关字段：`scope`（`builtin` / `local` / `user`）、`always_on`（仅 builtin 恒激活，§3.3）、
`has_ui`（决定是否出现在主菜单栏 Extensions）。

视图字段（2026-11-13 起）：`panel_visible`（bool — 该扩展当前是否至少有一个窗口可见，即菜单勾选态）
与 `panel_state`（`{<窗口名>: {visible, intent}}` — 逐窗口事实 + 已持久化的意图，`intent=null`
表示从未记录）。想诊断"勾着但看不见"、或确认用户上次是不是自己关掉的，看这两个字段。

## 5. 生命周期契约

```
enable:  构造实例 → on_load(ctx) → on_enable()
disable: on_disable() → on_unload() → 自动注销该扩展全部 ext.<id>.* ops
rescan:  已装载者全部 unload 后重新扫描（Settings ▸ Extensions ▸ Rescan）
关闭:    ExtensionManager.unload_all()（不改变持久化启用状态）
```

> `builtin` 扩展（allowlist 内，随引擎/安装包分发）没有 `disable` 这一支 —— `disable` 直接抛错（§3.3）。
> `local`（Functions 下的非白名单夹具）与 `user` 扩展可以正常停用。

约定：
1. `on_load` 只做**注册类**工作（ops/窗口/节点）; 重初始化放 `on_enable`。
2. 任何一步抛异常 → 该扩展 `broken`（引擎不受影响）; 修复后 `Rescan` 重试。
3. **禁止 monkey-patch 引擎/编辑器类**（运行时 `setattr` 核心类）; 需要在既有行为上挂钩时,
   走架构 Hook 点（`extension_protocol.md` §3.1）并向引擎侧提需求 — 缝外侵入=违规。
4. 卸载必须无残留: 自建线程/句柄在 `on_disable`/`on_unload` 里停干净（M2 起 `ctx.threads` 代管）。

## 6. ctx 能力总表（M0 实装 vs 规划）

| 能力 | 状态 | 说明 |
|---|---|---|
| `ctx.id / name / version / manifest` | ✅ M0 | 元数据 |
| `ctx.extension_dir` / `ctx.data_dir` / `ctx.engine_root` | ✅ M0 | 只读资产目录 / 可写数据目录 / 引擎根 || `ctx.output_dir` | ✅ 2026-11-11 | **运行数据落在哪里**（绝对路径）：编辑器 `<引擎>/output`、PIE `<工程>/output`、成品 `<成品>/output` || `ctx.log(msg)` | ✅ M0 | `[ext:<id>]` 前缀日志（Console 通道 M1） |
| `ctx.ops.register(name, fn, summary="")` | ✅ M0 | **扩展 op**（§9 生态核心） |
| `ctx.ui.register_window(name, draw_fn, visible=False, flags=None, close_policy="hide", show_on_enable=True, first_pos=None, first_size=None)` | ✅ M1 (2026-10-11; 参数扩展 2026-10-30) | 注册独立窗口（唯一入口 `ExtensionUI`；重名冲突/异常隔离/purge/窗口生命周期完备性 见 §7；默认不抢焦点）。`show_on_enable=False` = **按需窗口**（enable 时 `show_all` 不弹它，用 `ctx.ui.show_window(name)` 或 View 菜单打开）；`first_pos`/`first_size` = 首次出现位置/尺寸（`Cond_.first_use_ever`，附属窗口用它错开主面板） |
| `ctx.ui.show_window(name)` | ✅ M1 (2026-10-30) | 把本扩展的某个窗口置为可见（主面板里的“打开 XXX”按钮同路径）；非本扩展/不存在 → `False` |
| `ctx.ui.register_command / post / kit` | `[M1 待]` | 命令 / 帧安全点 / 控件包（设计见 `extension_protocol.md` §5.1） |
| `ctx.nodes.register_pack(...)` | ✅ M1 (2026-10-20) | 节点包（声明 + evaluator + 控件字段；§8） |
| `ctx.settings(schema)` | `[M1]` | schema 化设置（自动 UI + 持久化）；落地后**页面注册进 Settings 面板**（与 `Common`/`Export` 同级 — 宿主侧已就绪: `SettingsPanel.register_page` / `unregister_pages_by_owner`，见 `Doc/Dev/ui_protocol.md` §13） |
| `ctx.threads / ctx.jobs / ctx.bus` | `[M2]` | 受管线程 / 后台任务 / 数据总线 |
| `ctx.ui.post(fn)` | `[M1]` | 后台线程 → 渲染线程帧安全点 |
| `device`（能力键, **非** ctx 对象） | ✅ M0 | 语义 = **允许导入设备门面** `Application.Functions.VirtualDevice`（在 C6 白名单内）；**不提供 `ctx.device`**（不扩大 API 面）; 三模式（sim/device/virtual）与无硬件验收通道见 `Doc/Dev/device_io_protocol.md` §7 |
| `ctx.python` | ✅ 2026-11-09 | **解释器协议** — `.executable` / `.env(extra)` / `.probe(module)` / `.spawn(module, args, ...)` / `.explain()` / `.install_hint()`。总是注入（默认引擎解释器）；manifest `python` 声明自有 venv/exe；`spawn` 拉起的子进程由宿主在 disable/unload 时统一回收（§11.1） |
| `ctx.graph`（能力键 `graph`） | ✅ M1 (2026-10-29 扩展) | **受限图访问** — `nodes()` / `owned_nodes()` / `find(...)` / `find_type(...)` 读取；`add_node` / `update_node` / `set_props` / `replace_props` / `remove_node` / `add_link` / `remove_link` 写入；`request_redraw()` 触发编辑器重绘。默认只允许创建/改写/删除本扩展 owner 的节点，连线至少一端属于本扩展。**不 import 编辑器层**（`ExtensionGraph` 转发到编辑器单一入口）。未声明 `graph` 时 `ctx.graph is None` |
| `ctx.examples`（能力键 `examples`） | ✅ M1 (2026-10-30) | **扩展示例根目录** — `register(root, provider=None)` / `unregister(root)` / `roots()`。扩展自带 `<extension_dir>/Examples/` 在 enable 时由宿主自动登记（无需 capability）；声明 `examples` 后才注入 `ctx.examples`，用于追加额外根目录。宿主只读、不复制；disable/unload 时自动移除本扩展全部根目录。未声明 `examples` 时 `ctx.examples is None`；`.myproj.provider` 优先于 manifest `provider`，缺省 `@<id>` |
> 能力键 `device` 与其它行的区别: 前几行是"宿主注入的 ctx 能力对象", `device` 是**导入许可声明**
> （2026-10-12 裁决）。

未实装能力对应的 ctx 属性为 `None` — 扩展必须做能力检测（`if ctx.ui is None: ...`）。

### 6.1 `ctx.graph` 写入示例（仅操作自己拥有的节点）

```python
# 创建自己的节点（owner 必须等于扩展 manifest id）
n = ctx.graph.add_node("ext.acme.Init", position=(320, 120),
                       props={"gain": 2.0}, alias="acme_init")
# 检索自己的节点（type_prefix / owned_only）
nodes = ctx.graph.find_type(prefix="ext.acme.", owned_only=True)
# 覆写属性 / alias / description
ctx.graph.update_node(n["id"], props={"gain": 4.0}, description="updated")
ctx.graph.set_props(n["id"], {"mode": "device"})       # 合并
ctx.graph.replace_props(n["id"], {"mode": "device"})   # 整体覆写
# 连线（至少一端属于本扩展）
ctx.graph.add_link(n["id"], "exec_out", other["id"], "exec_in")
# GUI 刷新（标记 revision + 请求下一帧重绘）
ctx.graph.request_redraw()
```

`add_node/update_node/remove_node/set_props` 默认只接受本扩展 owner 的节点；
跨扩展/core 节点会抛 `PermissionError`。读取接口默认返回全图快照，可用
`owned_only=True` 或 `type_prefix="ext.acme."` 缩小范围。所有写入都在主线程
（扩展 `on_load` / ops / UI 回调）执行，不要从后台线程改图。

### 6.2 `ctx.examples` 示例（只读示例根目录）

扩展自带示例放在 `<extension_dir>/Examples/<Name>/` 时，enable 后自动出现在
`File ▸ Open Example`，不需要声明能力，也不需要复制到用户目录。若还要登记额外
根目录，在 manifest 声明能力并在 `on_load` 中调用：

```python
# extension.json: "capabilities": ["examples"]
def on_load(self, ctx):
    ctx.examples.register(os.path.join(ctx.extension_dir, "shared_examples"),
                          provider="@ACME")
```

- `register(root)` 的根目录必须已存在；引擎只读，不会修改扩展目录。
- 单个 `.myproj` 的 `provider` / `signature` / `author` 优先；否则用 manifest
  `provider`，再缺省 `@<id>`。同名示例若提供者不同，菜单用灰色签名区分。
- 禁用/卸载扩展会移除其全部示例根目录；不要自行复制到
  `%APPDATA%/FlyVibingEngine/examples`。旧式 `.injected.json` 副本在源根目录仍
  注册时会被菜单忽略。

## 7. UI 规范（`ctx.ui` — `register_window` 已实装 2026-10-11）

**实装状态**: `ctx.ui.register_window(...)` ✅（`ExtensionUI` / `ExtensionPanel` 桥）;
`register_command / post / kit` 仍 `[M1 待]`。

**行为契约（宿主保证 — 扩展可依赖）**:

1. **渲染线程纪律**: `draw_fn` 在 `UIManager.draw_all` 帧内被调用（`imgui.begin/end` 已由宿主包裹）;
   禁止在 draw_fn 内自建 imgui context / 自行 render / 跨帧持有 imgui 对象。
2. **窗口命名红线**: 与内建面板或其它扩展重名 → `register_window` 抛 `ValueError`（不静默改写）。
3. **异常遏制**: `draw_fn` 异常 → 本帧跳过 + 计数; 连续 120 帧异常 → 自动隐藏（quarantine）;
   扩展不必在 draw 顶层 try/except（可依赖宿主）, 但业务错误建议自查并展示。
4. **启停对称**: disable / 卸载 → 宿主自动注销该扩展全部窗口与 ops（保险丝）;
   enable 重走 on_load（新实例）→ 推荐扩展实现**幂等 `_install(ctx)`**（on_load/on_enable 共用,
   窗口重名 `ValueError` 静默跳过）— 完整模式见官方示例。
   **多窗口（2026-10-30）**: enable 时 `show_all` 只打开 `show_on_enable=True` 的主窗口;
   附属/管理窗口注册时设 `show_on_enable=False` + `first_pos`/`first_size` 错开主面板,
   由主面板按钮调用 `ctx.ui.show_window(name)` 或用户在 View 菜单打开。
5. **线程 → UI 通道**: 快照式读取（业务模块线程安全快照, 如 device 示例每帧 `monitor_snapshot()`）;
   `ctx.ui.post(fn)` 帧安全点 `[M1 待]`; 后台线程不得直接触碰 UI 状态。
6. **视觉**: 强制 UIManager 主题; 窗口默认浮动（用户可手动 dock; 布局 API `[M1 待]`）;
   图标用 FontAwesome 白名单。
7. **imgui 窗口栈配对纪律**（与主应用同规则 — `Doc/Dev/ui_protocol.md` §2.13）:
   `begin_child/end_child` **无条件配对**（宿主最小化 → 0×0 全裁剪时 `BeginChild` 返回 False
   也须 `EndChild`; 用 `try/finally` 兜底）—— 否则窗口栈失衡、`end_panel` 断言杀渲染循环;
   `begin_combo` / `begin_tab_item` 相反 — 仅返回 True 时 end。
   **静态拦截（2026-10-12）**: 审查器 **C8**（`begin_child` 被条件门控 → FAIL）、
   **C9**（`end_combo`/`end_tab_item` 疑似无条件 → WARN）、**C10**（顶层创建 imgui
   上下文/窗口/GL → FAIL; 纯导入允许, 见 §2/§12）、**C11**（触碰宿主全局 imgui 状态
   → FAIL: `create/destroy_context`、`set_ini_filename`（含 `imgui.get_io().set_ini_filename(…)`
   链式写法与 `io = imgui.get_io(); io.x = …` 别名写法, 2026-10-12 加固）、`io/style` 赋值;
   只读查 `io.display_size` 与窗口内 `push_style_*` 允许）; 主应用与扩展示例同源守卫
   `Test/Application/Editor/test_imgui_stack_pairing.py`（含规则自检 + 早退补偿计数）。
   运行期回归: 扩展侧自测（裸 imgui 0×0/1×1 绘制帧不崩）。
   崩溃定位指引与上游材料: `Doc/Dev/upstream_imgui_beginchild_fullclip.md`。

**文本安全（imgui 字面量 — 2026-10-11, "?" 现象根治）**:

`draw_fn` 的 imgui 文本与主应用共用同一字体图集（**ASCII + Latin-1 + General Punctuation
子集 + FontAwesome 私有区** — `hello_imgui` 默认字形范围）→ 图集外字符渲染为 `?`:

- **禁**: CJK 中文（→ "???"）、箭头 `← →`、几何 `▶ ■ ●`、Dingbats `✓ ✗ ★`;
- **图标用 FA 常量**: `from imgui_bundle import icons_fontawesome_6 as fa` +
  `getattr(fa, "ICON_FA_PLAY", "")`（device 示例示范: Start/Stop/Send 按钮与错误行
  `ICON_FA_TRIANGLE_EXCLAMATION`）; 安全标点 `— – · × …` 可直接用;
- **审查器 C7 自动检查**（`review_extension.py` — imgui 字面量图集外字符 → FAIL）;
- 完整安全集与 GBK print 约束（`▸ ✗ ▶` 不在 GBK, 管道输出会崩）见
  `Doc/Dev/ui_protocol.md` §12（**两边同源** — 改规则需同步两处 + 两侧守卫）。
- 参照: device 示例本批修复 `(watch/send 时自动启动)` → `(auto-start on watch/send)` 等 4 处。

**扩展语言包（[M1]）**: 宿主 i18n 已目录化 —— 扩展可 `I18n.register_catalog("ext.<id>", lang, {...})`
自带语言包（键命名空间 `ext.<id>.*`；卸载经 `unregister_catalogs("ext.<id>")` 对称清理）。
协议与 Runbook: `Doc/Dev/i18n_protocol.md` §11；审查器 **C8**（UI 字面量未走 `t()` → FAIL）与
**M7**（`locale/*.json` 键集对齐 en → FAIL）为下一轮落地。

**宿主适配点**（扩展体系向主应用支付的**一次性**接入面 — 新扩展不再需要触碰）:

| 适配点 | 内容 | 日期 |
|---|---|---|
| `UIManager.unregister()` | 面板注销基础能力（原先只有 register） | 2026-10-11 |
| View 菜单动态枚举 | 由硬编码 5 面板改为遍历 `_panels`（扩展窗口自动纳入菜单） | 2026-10-11 |
| `ExtensionUI` 桥 | ctx.ui → UIManager 唯一入口 + owner 追踪 + purge 保险丝 | 2026-10-11 |
| `SettingsPanel.register_page` | 设置页注册表（扩展页与 `Common`/`Export` 同级 + `unregister_pages_by_owner` 清理） | 2026-10-12 |

> 主菜单栏实际渲染 = `UIManager._draw_menu_bar()`（`UI/panels/MenuBarPanel.py` 为未注册保留文件, 不要改错地方）;
> `Extensions` 菜单 = `ExtensionMenu.draw_extensions_menu()`。

**设置页贡献（与 `Common` / `Export` 同级 — 宿主侧已就绪 2026-10-12）**:

Settings 面板（**Edit ▸ Preferences…**）采用**页面注册表** — 扩展页与 core 页同级展示
（宿主协议 `Doc/Dev/ui_protocol.md` §13）:

```python
from Application.Editor.UI.panels.SettingsPanel import SettingsPage, SettingsPanel

def _draw_demo_settings() -> None:
    ...  # imgui 控件; 变更即写 ctx.data_dir 下的自有设置文件

SettingsPanel.register_page(SettingsPage(
    id="ext_demo", title_key="ext.demo.settings", draw_fn=_draw_demo_settings,
    order=50, owner=ctx.id))
# 卸载/停用时: SettingsPanel.unregister_pages_by_owner(ctx.id)
```

- `title_key` 是 I18n 键（宿主无词条时回退显示键原文 — 扩展可直接用自有文案作键）;
- `owner=ctx.id` → 与 `purge_ui` / `_purge_ops` 对称的生命周期保险丝（**卸载必清**）;
- `ctx.settings(schema)` `[M1 待]` 落地前, 扩展自行持久化到 **`ctx.data_dir`**
  （不要写主应用 `Application/Editor/Config/settings.json`）;
- 该接入面属上表"宿主适配点" — 一次性支付, 后续扩展不再需要改主应用代码。

**窗口生命周期完备性（2026-10-11 — 面板开关同步闭环）**:

背景: 面板自身关闭（X）与其它状态（设置页勾选）曾出现不同步 —— 根因是
**“启用状态”与“窗口可见性”是两条正交的线, 无人负责其联动**。职责划分: 联动策略由
**扩展作者**决定（宿主不可能预知每个扩展的面板语义）, 宿主提供机制, 三重保障 =
本文档 + 静态审查器 + Python 语言层强制。

| 状态 | 语义 | 责任 |
|---|---|---|
| 注册 | `register_window` 成功（装配期） | 扩展（经 ctx.ui） |
| 可见/隐藏 | 窗口 X / View 菜单 / 程序化设置 | **扩展必须声明联动策略（close_policy）** |
| 注销 | disable/卸载 → 宿主 purge | 宿主（保险丝） |

**close_policy（注册时声明, 三选一）**:

| 策略 | 窗口 X 的语义 | 适用场景 |
|---|---|---|
| `"hide"`（默认） | 仅隐藏; 扩展继续运行（**隐藏会被记住, 下次启动仍隐藏**） | 可选视图侧窗 |
| `"disable"` | **关闭 = 请求停用扩展 → 整个条目从 Extensions 菜单消失, 设置页勾选同步取消（闭环）** | 单主面板扩展（面板即扩展界面本体） |
| `"custom"` | 仅派发事件, 由扩展全权决策 | 复杂多窗联动 |

**面板可见性的持久化（2026-11-13 — 单一咽喉）**:

`ExtensionPanel.visible` 的 setter 是宿主唯一的落盘点：菜单点击、View 菜单、`ui.panel` op、
用户点 X、dock 分离 —— 无论哪条路径，写入都经过它，并同步写
`%APPDATA%/FlyVibingEngine/editor_state/extensions.json` 的 `panels` 段（**按窗口名**，
不是扩展 id —— 一个扩展可以有多个窗口，各自独立恢复）：

```json
{ "version": 2,
  "enabled": { "gtec": true },
  "python":  {},
  "panels":  { "Gtec Monitor": true, "Device Manager": false } }
```

恢复规则（`scan()` 激活后按窗口逐个执行）：

| `panels[<窗口名>]` | 结果 |
|---|---|
| `true` | 打开 |
| `false` | 保持隐藏（**用户关过就是关的**，重启也不会自己弹回来） |
| 缺省（从未记录） | 非 builtin 且注册时 `show_on_enable=True` → 自动打开一次并记录；否则保持隐藏 |

> 为什么 builtin 不参与"首次自动打开"：builtin 恒激活，"第一次扫到"与"用户半年前关掉了"
> 在状态文件里长得一样；自动弹窗还会挤掉 e2e 的默认布局。用户想开就点一次菜单。
>
> 老状态文件没有 `panels` 段 = 全部按"从未记录"处理，向后兼容。
> 文件按 `utf-8-sig` 读 —— 记事本存盘会加 BOM，用纯 `utf-8` 读会整份解析失败并**静默回落默认值
> （= 扩展开关全丢）**，这是 2026-11-13 实测踩到的坑。

> builtin 扩展（allowlist 内）不可停用，`close_policy="disable"` 对它退化为
> `"hide"`（窗口 X 只隐藏）；需要「关掉就不再见」的语义请把扩展装到用户目录。

**on_ui_event(event, name) 事件契约**:

- `"closed"` — 用户关闭窗口（宿主在 visible True→False 时派发, 渲染线程帧内）;
  推荐在其中做**即时收尾**（例: device 示例在面板关闭时停止监视、释放端口）。
- `"disable"` 策略的执行走**挂起队列**（`ExtensionManager.request_disable` → 主线程
  pump 每帧 `consume_pending_disables`）— 生命周期方法始终在主线程, 扩展无需关心线程。

**语言层强制（三重保障之三）** — `capabilities` 含 `"ui"` 的扩展**必须**:

1. entry 类继承 `UIExtensionBase`（`Application.Core.Extension.ExtensionBase`）— 其
   `on_ui_event` 为 `abstractmethod`, **未实现则无法实例化**
   （`TypeError: Can't instantiate abstract class` → 加载失败隔离为 broken）;
2. 未继承而声明 ui → ExtensionManager 加载时拒载（capabilities↔基类一致性校验, 同为 broken）。

**静态审查（三重保障之二）**: 提交前运行
`python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>` —
C1/C2 检查基类与实现、C3 检查 close_policy 声明（检查项全表见工具头部）。

**官方示例**: `Application/Functions/SerialParallelDevice/extension.py`（监视面板 — 上述全部契约的活参考:
枚举/文本混合端口选择、设置持久化、快照式事件流、`ext.device.*` **八件套** ops、
`close_policy="disable"` + `on_ui_event` 收尾示范; **面板 ↔ 场景 同步示范**（2026-10-12）:
`bind_alias` / `bind_nodes` 两个 op + 面板 “Device names (@alias)” 段 — 面板按钮与 agent
调用**同一个**操作实现（动作单点）, 经 `ctx.graph` 读/写当前图节点 props, 见
`Doc/Dev/device_io_protocol.md` §12）。
> **接手维护该扩展的 agent 入口**: `Application/Functions/SerialParallelDevice/HANDOFF.md`（交接书: 边界/裁决/坑/下一步/验收）
> + `HANDOFF_PROMPT.md`（可直接粘给新会话的启动提示词）。

**第二个官方示例（设备族面板模板）**: `Application/Functions/VirtualDevice/`（虚拟信号发生器波形监视面板 —
watch / record 分离、实时示波器（min/max 包络 + 悬停读数）、显示滤波（陷波/频带, 2/4 阶因果 IIR）、
采集落盘、`ext.virtual.*` **九件套** ops、设置持久化与 `close_policy="disable"` 收尾;
**厂商复制指南**见其 README — 设备族面板扩展的起手模板）。

## 8. 节点包规范（✅ M1 实装 2026-10-20）

扩展在 `node_pack.py` 返回声明 dict（或用 `ctx.nodes.register_pack(pack)` 运行期注册）。
内置 `Application/Functions/**/node_pack.py` 由 NodeGraph **自动发现**，不需要扩展 enable；
type 名作为图的持久身份，官方迁移保留旧名（如 `SerialSend`），新扩展建议 `ext.<id>.<Type>`。

```python
def register() -> dict:
    return {
        "id": "myext", "owner": "myext", "name": "My Extension",
        "signature": "@ACME",   # 节点卡标题下灰色提供者签名
        "nodes": [{
            "type": "ext.myext.MyNode", "label": "My Node", "category": "MyExt",
            "color": (0.5, 0.7, 0.9),
            "pins": [{"name": "exec_in", "kind": "exec", "direction": "input"}],
            "fields": [{"key": "gain", "label": "Gain", "kind": "float", "default": 1.0}],
            "evaluator": my_eval,       # 可选；纯函数 (node_id, ctx, graph)
        }],
        "menu": [("My Extension", [("My Node", "ext.myext.MyNode")])],
    }
```

规则：
- 不得覆盖其他 owner 的 type（`NodePackError`）；同 owner 重复注册幂等；
- `fields` 由 Node Editor 通用控件渲染（text/int/float/bool/enum/serial_port），
  扩展无需 import Editor / imgui；
- evaluator 必须是确定性纯函数（干跑也走它）；未安装 pack 的图应显示 missing extension（M3）；
- **提供者签名**: pack 可写 `signature`（如 `@Official` / `@ACME`）；缺省扩展节点为
  `@Community`，核心节点默认 `@Official`。签名显示在节点标题下一行（灰色），不写进
  `props_text`/description，也不从本地路径自动推断。
- **Agent 发现**: `graph.types`（含 type/label/category/owner/signature/pins），`extension.list` 也返回
  `extensions[].nodes`；`graph.add` 可直接添加未连线节点（节点池）并返回 pins。
- 内置 pack 在扩展 disable 后仍保留（节点类型属于图可加载性）；运行期 `ctx.nodes` 注册的 pack
  在 unload 时反注册。

## 9. MCP/CLI 服务规范（增量扫描生态 — 本协议的生态核心）

**目标**: 扩展可以携带自己的 op 服务; 主应用 **不重启、不重打包** 即可增量发现并提供
（引擎注册宿主**强制加**前缀 `ext.<id>.`; 扩展注册名**不得自带** `ext.` 前缀
      （自带 → 加载期 ValueError, 扩展 broken）—— 与审查器 C4 同一事实, 两种说法以本条为准。

### 9.1 引擎侧（已实装 M0）

```
扩展 on_load:  ctx.ops.register("open_device", fn, summary="打开设备")
             → LiveCommandServer.register_extension_ops("<id>", {"ext.<id>.open_device": fn}, ...)
约束:  op 名强制前缀 ext.<id>.（违反 → 加载期 ValueError, 扩展 broken）
隔离:  disable/unload → unregister_extension_ops(id) 全量注销
不变式: 扩展 op 不进入核心注册表（_ops）; 核心计数守卫（见 §12）不受扩展影响
```

### 9.2 agent 侧（发现与调用）

| 动作 | 通道 |
|---|---|
| 发现 | `extension.list`（==菜单列表）→ `extensions[].ops` + `extensions[].nodes` + `extension_ops{}`（owner/summary） |
| 节点类型 | `graph.types`（含扩展 pack）→ type/label/category/owner/pins/fields |
| 启停 | `extension.enable / extension.disable`（等同 Settings ▸ Extensions 勾选; 持久化；builtin 不可停用） |
| 调用 | 任意通道直接发 `ext.<id>.<op>`: CLI `call`（ext.* 透传, 无需静态注册）/ `engine_call` / exec `engine.ok` |
| 文档 | 扩展 op 的 summary 在 `extension.list` 中; 富有文档的扩展建议带 README 路径 |

### 9.3 边界与版本

- 扩展 op 的**参数契约属于扩展自身**（核心注册表的 `Param` 元数据不覆盖 ext.* — 保持核心表纯净）。
- CLI `ops` 静态目录只列核心 op; 扩展 op 以 `extension.list` 为权威（避免静态/动态双源冲突）。
- 长任务的超时放宽: 核心 `call_timeout` 对 ext.* 默认 15s; 扩展如需长超时, 在 README 声明并在
  CLI 调用时显式 `--timeout`（未来可支持扩展在 manifest 里声明 `op_timeouts`）。
- 安全边界: ext.* op 与核心 op **同权限**（进程内执行）; 需要硬隔离的走 T2 进程扩展（设备类）。

### 9.4 迁移指引（从核心抽出）

把现有核心 op 迁移到扩展时的步骤（例: 未来的 `ext.device.*`）：
1. 在扩展内实现 handler（纯函数; 返回值 JSON 可序列化）;
2. `ctx.ops.register` 注册新名; 核心侧旧名保留一版转发或标记 deprecated;
3. 更新 `ui_protocol.md` §10（该表只管核心 op; 扩展 op 由 `extension.list` 呈现）;
4. 核心注册表删除旧 op → 五处同步（`editor_live_protocol.md` §6 检查单）+ 计数守卫更新。

## 10. 线程规范（现状纪律 + `[M2]` 受管模型）

- **M0 阶段**: 扩展如必须用线程, 照 `threading_protocol.md` 手工执行（ThreadRegistry 注册,
  命名 `ext:<id>:<用途>`, 心跳, 关闭清理）; 但推荐等到 M2 的 `ctx.threads` 统一代管。
- `[M2]` 目标模型: `ctx.threads.spawn(name, fn, expect_hz)`（自动注册/心跳/统一 join）;
  `ctx.jobs.submit(fn) → Future`（结果回调经主线程）; `ctx.bus.ringbuffer/queue`（唯一推荐共享媒介）。
- 永久禁止: 渲染/主线程阻塞等待; 无锁共享可变结构（引擎为 free-threaded Python, 无 GIL 保护）。

## 11. 设置与数据目录

- 可写状态一律 `ctx.data_dir`（默认 `%APPDATA%/FlyVibingEngine/extensions_data/<id>/`，随启用状态独立；测试/部署可用 `FVE_EXTENSIONS_DATA` 或旧 `MGE_EXTENSIONS_DATA` 覆盖）。
- **运行数据（录制/日志/表格）一律落在 `ctx.output_dir`**，不要用 `os.getcwd()` 拼相对路径：
  成品里 CWD 就是成品安装目录 —— 写进去会污染安装目录，装到只读位置还会直接失败。
  如需相对基准，用 `Application/Core/FileSystem/DataPaths.py` 的
  `resolve_write_path(raw, relative_to="output"|"project"|"cwd")`；节点侧的
  `relative_to` 默认就是 `output`。
  **不要**把本机绝对路径存进节点 prop（录制目录、模型目录）—— 导出器会把它写进
  `export_manifest.json` 的 `absolute_paths` 并告警，因为它换机器就断。
  推荐三态：空（= `ctx.output_dir/<ext>/`）/ 相对路径 / 绝对路径（显式覆盖）。
- `[M1]` `ctx.settings(schema)` 落地后: schema 自动生成设置 UI + 持久化, 禁止自建配置文件到其它位置。

### 11.1 Python 解释器与依赖（2026-11-09 — `ctx.python`）

**先说结论**：扩展的第三方依赖**不要装进引擎 venv**，也不要在代码里写死
`C:\...\venv\Scripts\python.exe`。在 manifest 声明，宿主负责解析、托管、回收。

```json
"python": {
  "mode": "engine",
  "path": "%EXT_DATA%/venv",
  "requirements": "requirements.txt",
  "probe": ["serial", "numpy"]
}
```

| mode | 什么时候用 | 行为 |
|---|---|---|
| `engine`（默认） | 纯 Python / 与引擎同版本的依赖（pyserial、numpy…） | 用编辑器自己的解释器；零配置 |
| `venv` | 依赖与引擎冲突，或需要编译轮子（设备 SDK） | `path` 指向扩展自己的 venv **目录**（也接受 exe）；推荐 `%EXT_DATA%/venv` |
| `path` | 系统 Python / conda / 用户指定 | `path` 直接指向 exe |

`path` 支持 `%EXT_DIR%` / `%EXT_DATA%` / `%ENGINE_ROOT%` 变量，**禁止写死机器路径**。

**解析优先级**（`ctx.python.explain()` 会说明实际来源）：

```
FVE_EXT_PYTHON_<ID>（旧 MGE_EXT_PYTHON_<ID>）→ manifest python.path → 引擎解释器
```

**运行期覆盖（不用重启）**

```powershell
engine-editor-cli call extension.python id=device          # 只读：mode/source/executable/probe/problems
engine-editor-cli call extension.python id=device path="C:/envs/eeg/Scripts/python.exe"
engine-editor-cli call extension.python id=device path=""   # 清除，回落 env → manifest → 引擎
```

覆盖写进 `%APPDATA%/FlyVibingEngine/editor_state/extensions.json`（`version: 2`，`python` 段）；
已装载的扩展立即生效（之后的 `probe`/`spawn` 用新解释器，已拉起的子进程仍由 `close()` 回收）。

**`ctx.python` 门面**

| 成员 | 用途 |
|---|---|
| `.executable` / `.source` | 解析结果 / 来源（`engine` / `manifest` / `env`） |
| `.env(extra=None)` | 子进程环境（`PYTHONPATH` = 扩展目录 + 引擎根；`PYTHONNOUSERSITE=1`） |
| `.probe("serial")` | 子进程 `import` 自检 → `(ok, detail)`；结果缓存 |
| `.spawn(module="pkg.service", args=["--port", "0"])` | 拉起子进程 → `{pid, cmd, log}`；**disable/unload 时宿主统一 terminate/kill** |
| `.explain()` | `{mode, source, executable, exists, probe, problems, children}` — 直接贴进错误信息 |
| `.install_hint()` | 缺依赖时的可复制命令（`"<exe>" -m pip install -r "<requirements>"`；不自动执行） |

**开发者视角：你原来会怎么做，现在该怎么做**

| 你原本的打算 | 会发生什么 | 现在 |
|---|---|---|
| `pip install` 到引擎 venv | 本机能跑，重装/升级/换机即失效，且可能与引擎依赖打架 | 声明 `venv` + `%EXT_DATA%/venv`；或 `engine` 模式 + `probe` 声明 |
| 自己 `subprocess.Popen(sys.executable, ...)` | 拿到的是编辑器环境；缺依赖时才在子进程日志里炸；退出不回收 | `ctx.python.spawn(module=..., args=[...])`：统一日志目录、卸载回收、环境一致 |
| 写死 `C:\Users\me\venv\Scripts\python.exe` | 换机器/换盘符就断，报错不可读 | manifest `path` 用变量；用户可用 `FVE_EXT_PYTHON_<ID>` 临时覆盖 |
| 让用户先手动起服务 | 每次实验前要记得起，忘了就是"设备打不开" | 仍支持手动端点；自动拉起用 `spawn`，失败信息带 `explain()` 与启动命令 |
| 缺依赖时 `except Exception: return []` | 用户只看到"没有设备/没有波形" | `probe()` + 一条带安装命令的日志（设备类扩展的 `ext.<id>.status` 也回传 `python` 块） |

**检查清单**

1. manifest 声明了 `python`（至少 `{"mode": "engine", "probe": [...]}`）；
2. 不在模块顶层 spawn / 不自己 `Popen`；
3. 依赖缺失走 `probe` → 日志/状态里给出 `install_hint()`；
4. 卸载不需要自己杀子进程（宿主回收；扩展自己 Popen 的仍需自己管）；
5. `extension.list` 的 `python` 块能看到解析结果（`executable` / `source` / `problems`）。

### 11.2 产物侧依赖（`python.runtime`，2026-11-14 — **导出强制**）

§11.1 描述的是"**编辑器里**扩展代码跑哪个解释器"。它**不描述成品**：成品用的是
`Resource/runtime` 这份独立镜像（按手写清单烘焙），扩展的包从来不在里面。

> 事故：Gtec 落盘改 HDF5（需 `h5py`）→ PIE 正常、**导出成品在落盘那一刻**才报
> `h5py is not installed`。能开、能录、实验跑完才炸。

所以 manifest 多了一条**产物轴**，且**导出时强制校验**（不合法 = 导出失败）：

```json
"python": {
  "mode": "engine",
  "runtime": {
    "mode": "engine",
    "requires": ["h5py>=3.16"],
    "probe": ["h5py"],
    "optional": false,
    "note": "g.tec g.Recorder layout export needs h5py"
  }
}
```

| `runtime.mode` | 落地 | 谁用 |
|---|---|---|
| `engine` | `<产物>/runtime/Lib/site-packages` | **节点代码**（进程内 `import`） |
| `bundle` | `<产物>/extensions/<id>/env/` | **只有子进程**（进程内节点只有一个解释器） |
| `none` | — | 无三方依赖（**也必须显式写**） |

- 未知键 = 错误（拼错 `requires` 不会被静默忽略）；
- `bundle` 用于"三方包版本/ABI 与引擎冲突"——代价是产物 +几百 MB，**只在必需时用**；
- `engine` 的包按 `<扩展>/wheels/` → `Resource/wheels/` → 引擎 venv 的顺序解析，全部离线；
- 成品启动即 probe，缺包打 `[Player] ERROR:`（不再等到第一次落盘）。

**完整语言、强制点、自检工具、清单字段**：见 **`extension_dependencies.md`**。

提交前必跑：

```powershell
python Utils/Dev/check_extension_python.py --all
```

## 12. 测试规范（扩展必带自测）

1. 每个扩展自带 `test_<id>_extension.py`（放 `Test/Application/Extensions/` 或扩展目录的
   `tests/`—M3 定稿; 现阶段建议前者）, 遵守 `test_protocol.md` 输出契约（`RESULT: OK (n/m)`）。
2. 至少覆盖: manifest 校验 / on_lo —— **禁止顶层创建** imgui context / 窗口 / GL
   （`create_context` / `glfw_init*` / `opengl3_init` / `new_frame` 等）; **纯模块导入**
   `imgui_bundle` 允许（编辑器环境必有; 实测无显示环境下导入无副作用 —— 与两个官方示例
   一致, 2026-10-12 口径修正）。GUI 代码放窗口回调内。审查器 **C10** 机械检查该约束 无残留 / 异常遏制。
3. 无头约束: 扩展入口必须 headless 可加载（顶层不得 import imgui; GUI 代码放窗口回调内）。
4. **不变式守卫**（引擎侧已有, 扩展不得破坏）:
   - `test_action_contract` 三方一致（核心 ops ↔ 文档表 ↔ 引擎注册表）— 扩展 op 在核心表外;
   - `test_editor_mcp_package` 核心计数 — 扩展不改变核心计数;
   - `test_imgui_stack_pairing` 窗口栈配对（主应用 + 扩展示例同源扫描）;
   - 扩展 op 出现/消失只影响 `extension.list`。
5. **实机自动化**: 用 `extension.enable` / `extension.disable` op 驱动启停（等同设置页勾选语义）——
   菜单/设置页没有程序化点击入口, 不必为此写鼠标脚本（`extension.list` 每项的
   `enabled` / `status` 就是断言点）。
6. **无头 GUI 测试的唯一入口**（2026-10-12 — 实测踩坑）: 需要裸 imgui 上下文时**必须**用
   `flyvibing_extension_kit.imgui_headless.headless_imgui()`（自动禁用布局持久化）:
   ```python
   from flyvibing_extension_kit.imgui_headless import headless_imgui
   with headless_imgui() as h:
       h.frames([(1280, 720), (0, 0), (1, 1), (1280, 720)], draw=my_panel_draw)
   ```
   裸 `imgui.create_context()` 会在 `destroy_context()` 时把 **`imgui.ini` 写进当前工作目录**
   （扩展自测最常踩 → 仓库/app 根多出垃圾文件）; **`set_ini_filename(None)` 会让进程原生
   崩溃**（exit 0xC0000005, 可复现）—— 禁用一律用空串, 且优先用上面的 helper。
   主应用侧同名守卫: `Test/Application/Editor/test_imgui_hygiene.py`。

## 13. 实装地图（M0 → M3）

| 项 | 状态 |
|---|---|
| 发现/校验/启停/持久化/隔离 · ops 增量扫描 · `extension.*` ops | ✅ M0 (2026-10-11) |
| **激活策略 + 入口分工**（builtin = allowlist 恒激活；Functions 下非白名单 = `local` 仍 opt-in；主菜单栏只列 `has_ui`；管理面收敛到 Settings ▸ Extensions；`FVE_EXTENSIONS_BUNDLED=off` 安全模式） | ✅ M1 (2026-11-10) |
| `ctx.ui.register_window` + ExtensionUI 桥 + **官方示例扩展**（device 监视面板 — 含真实串口闭环与侵入风险审查） | ✅ M1 部分 (2026-10-11) |
| **窗口生命周期完备性**（close_policy / on_ui_event / `UIExtensionBase` 语言层强制 / 挂起停用队列）+ ExtensionKit 审查器 v0 | ✅ M1 (2026-10-11) |
| **VirtualDevice 波形监视面板范例**（Gtec 设计语言干净重写: watch/record + 示波器 + 显示滤波 + `ext.virtual.*` 九件套 + 厂商复制指南） | ✅ M1 (2026-10-16) |
| UI 剩余（command/kit/post）· 节点包 · 设置（schema 化） | `[M1 待]` |
| 线程/任务/总线受管模型 · ThreadRegistry 集成 | `[M2]` |
| 外部目录安装（.mgext）· 脚手架 `ext-init` · 示例扩展 · 贡献审计 · 边界测试全套 | `[M3]` |
| 依赖拓扑 requires · 热重载（dev）· 扩展 op 超时声明 | `[M3+]` |

## 14. 提交检查单（无上下文 agent 开工前自查）

- [ ] 读了本文件 + `extension_protocol.md` §1/§3/§4 + 对应领域协议
- [ ] 目录/命名/id/ops 前缀合规（注册名不含 `ext.` 前缀 — §9.1）; manifest 字段完整（api_version="1"）;
      `capabilities` 取值在 §4 合法值集内
- [ ] 入口 headless 可加载（**无顶层 context/窗口/GL 创建** — 纯导入允许）; 生命周期无残留;
      未 monkey-patch 任何核心类; 仅 import §3 白名单内的 `Application.*`
- [ ] （UI 扩展）继承 `UIExtensionBase` + 声明 `close_policy` + 实现 `on_ui_event` 收尾;
      imgui 窗口栈配对纪律（`begin_child` 无条件配对 — §7 第 7 条）;
      `python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>` 无 FAIL
- [ ] （示例扩展）自带 `<extension_dir>/Examples/<Name>/` 可被 `File ▸ Open Example`
      发现；不要把示例复制到用户目录；需要额外根目录时声明 `capabilities:["examples"]`
      并用 `ctx.examples.register`，确认 disable/unload 后条目消失（§6.2）
- [ ] `extension.list` 四项入口字段符合预期：`scope`（builtin/local/user）、`always_on`
（仅 allowlist 内置应为 true）、`has_ui`（有无面板 —— 决定是否进主菜单栏，§3.3）、`enabled`
- [ ] `extension.enable` → `extension.list` 显示 enabled + ops 齐全 → 逐 op 实调通过
- [ ] 自带测试按 `test_protocol.md` 契约全绿; 未破坏核心计数守卫
- [ ] `TODO.md` 状态更新（maturity 与清单勾选）

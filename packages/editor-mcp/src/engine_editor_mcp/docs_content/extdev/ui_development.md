# UI 开发指南（扩展编辑器 UI）

> 读者：扩展作者 / agent。目标：用**引擎公开的 `ctx.ui` 接口**给编辑器增加面板，不修改
> `Application/Editor/UI/**`，不依赖跨进程 UI。
>
> 本文只讲**编辑器 UI**。游戏运行时内的用户 GUI（按钮、弹窗、实验参数面板）是另一条
> GameRuntime 工作流，见 `runtime_scene_ui_input_plan.md`（引擎研发文档）；不要在扩展里
> 假设 `imgui_bundle` 会随游戏成品分发。

## 1. 先决条件

1. 扩展目录有 `extension.json`，且 `capabilities` 含 `"ui"`。
2. 入口类继承 `UIExtensionBase`（不是只继承 `ExtensionBase`）。
3. 实现 `on_ui_event(self, event, name)`；`capabilities` 声明 `ui` 但未继承/未实现时，
   `ExtensionManager` 会把扩展隔离为 `broken`，不会拖垮编辑器。
4. 只使用公开接口：`ctx.ui.register_window` / `ctx.ops.register` / `ctx.data_dir`。
   不要把 ImGui 控件写进引擎 UI 文件，也不要 monkey-patch 引擎类。

## 2. 最小可运行面板

```python
from Application.Core.Extension.ExtensionBase import UIExtensionBase
from imgui_bundle import imgui


class MyPanelExtension(UIExtensionBase):
    id = "mypanel"
    name = "My Panel"
    version = "0.1.0"

    def on_load(self, ctx):
        self.ctx = ctx
        # visible=False：启动时只保留主工作区默认标签页；扩展启用时宿主会 show_all
        ctx.ui.register_window(
            "My Panel",
            self._draw,
            visible=False,
            close_policy="hide",
        )

    def _draw(self):
        imgui.text("Hello from my extension")
        if imgui.button("Ping"):
            self.ctx.log("ping")

    def on_ui_event(self, event: str, name: str):
        # 用户点击窗口 X 后（宿主在 visible True→False 时派发）
        if event == "closed":
            self.ctx.log(f"window closed: {name}")
```

对应的 `extension.json` 至少要包含：

```json
{
  "id": "mypanel",
  "name": "My Panel",
  "version": "0.1.0",
  "api_version": "1",
  "maturity": "skeleton",
  "entry": "extension.py:create_panel_extension",
  "capabilities": ["ui", "ops"]
}
```

`api_version` 是必填项（引擎当前支持 `1.x`）；缺少它会直接得到 `broken`，不会加载入口。

启用并验证（编辑器运行中）：

```powershell
engine-editor-cli call extension.enable id=mypanel
engine-editor-cli call extension.list
engine-editor-cli call ui.panels
engine-editor-cli call ui.panel name="My Panel" visible=true
```

## 3. 窗口契约

`ctx.ui.register_window(name, draw_fn, visible=False, flags=None, close_policy="hide")`

| 参数 | 说明 |
|---|---|
| `name` | 全局唯一；与内置面板/其他扩展重名会抛 `ValueError` |
| `draw_fn` | 无参函数；宿主已在窗口 `begin/end` 内调用，**只画内容**，不要自己 `begin` 同名窗口 |
| `visible` | 默认 `False`；扩展启用时宿主会把该扩展窗口重新置为可见 |
| `flags` | `imgui.WindowFlags`；`None` = 默认 |
| `close_policy` | 窗口 X 的语义，见下表 |

| `close_policy` | X 的语义 | 适用 |
|---|---|---|
| `"hide"`（默认） | 只隐藏，扩展继续运行 | 可选辅助视图 |
| `"disable"` | 请求停用扩展，Extensions 菜单勾选同步消失 | 面板就是扩展主界面 |
| `"custom"` | 只派发 `on_ui_event`，由扩展自行决策 | 多窗口联动 |

`on_ui_event` 当前事件：`"closed"`（用户关闭窗口）。`close_policy="disable"` 的停用请求走
挂起队列，生命周期方法仍在主线程执行；不要在 UI 回调里直接做重活。

## 4. 线程与数据

- `draw_fn` 在渲染线程的 ImGui 帧内执行；**禁止**自建 ImGui context、窗口或 GL 上下文。
- 禁止跨帧持有 ImGui 对象（`imgui` 的 UI 对象只在当前帧有效）。
- 后台线程不要直接操作 ImGui；用快照/队列把数据交给主线程。
  - 当前已实装：快照读取、`ctx.ops` 调用、`ctx.data_dir` 持久化。
  - `ctx.ui.post` 尚未实装（M1 待办）；不要依赖它，先使用线程安全队列 + 帧内消费。
- 可写状态放 `ctx.data_dir`（默认 `%APPDATA%/FlyVibingEngine/extensions_data/<id>/`，
  可用 `FVE_EXTENSIONS_DATA` / 旧 `MGE_EXTENSIONS_DATA` 覆盖），不要写引擎目录或仓库根。
- 绘制异常会被 `ExtensionPanel` 遏制：连续异常达到阈值后窗口自动隐藏；不要用 try/except
  掩盖真实错误，修复后重新启用/Rescan。

## 5. 测试与审查

提交前运行：

```powershell
python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>
```

审查器会检查 `UIExtensionBase`、`on_ui_event`、`close_policy`、ops 前缀、ImGui 窗口栈配对、
顶层 context/GL 创建等。

无头测试需要裸 ImGui 上下文时，必须使用工具仓的唯一入口：

```python
from flyvibing_extension_kit.imgui_headless import headless_imgui

with headless_imgui() as h:
    h.frames([(1280, 720), (0, 0), (1, 1)], draw=my_panel_draw)
```

不要直接 `imgui.create_context()`：`destroy_context()` 会把 `imgui.ini` 写到当前工作目录；
`set_ini_filename(None)` 已知会导致原生崩溃。

## 6. 常见坑

| 现象 | 原因 / 处理 |
|---|---|
| `window name already registered` | 面板名与内置或其他扩展冲突；换唯一名称 |
| 扩展加载为 `broken` | 声明 `ui` 但未继承 `UIExtensionBase` / 未实现 `on_ui_event` |
| 点击 X 后菜单还勾选 | `close_policy` 不是 `"disable"`；或扩展未清理自己的停用请求 |
| 面板每帧报错后消失 | 绘制异常被隔离；看控制台 traceback，修复后 Rescan |
| 后台线程更新 UI 崩溃 | 改为快照/队列；不要从后台线程调 ImGui |
| 测试后仓库多出 `imgui.ini` | 裸上下文导致；改用 `headless_imgui()` |

## 7. 参考实现

| 示例 | 重点 |
|---|---|
| `Application/Functions/SerialParallelDevice/extension.py` | 端口枚举、设置持久化、快照式事件流、`close_policy="disable"` + 收尾 |
| `Application/Functions/VirtualDevice/extension.py` | 设备族面板、watch/record、实时波形、显示滤波 |

相关规范全文：`extension_dev_protocol.md` §6/§7；无头 UI 细节：引擎仓库
`Doc/Dev/ui_protocol.md`（内部协议，扩展作者不必通读）。

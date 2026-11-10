# ui_recipes.md — 扩展面板配方（复制就能用）

> 写给编辑器面板的扩展作者：9 个片段，每个对应一个真实需求 —— 参数行、设置持久化、
> 表格、日志、波形、确认框、禁用原因、后台线程、无头自测。
>
> 本文只讲**怎么组合控件**；单个控件的签名/返回值/坑查 `dev/imgui_api`（按用途归类）。
> 面板怎么挂到编辑器、窗口契约、隔离机制查 `extdev/ui_development`。

读法：

```powershell
engine-editor-cli doc outline extdev/ui_recipes
engine-editor-cli doc show extdev/ui_recipes#表格
```

每个配方都遵守同一条线程纪律：**`draw_fn` 在渲染线程的 ImGui 帧内执行**，
只读快照、只写自己的内存状态；重活与 IO 交给后台线程（见 §8）。

---

## 1. 参数行：标签 + 滑杆 + 单位 + 复位

**场景**：一个可调参数（频率、时长、阈值），要能拖、显示单位、改了能一键回到默认。

```python
from imgui_bundle import imgui


def param_row(label: str, value: float, lo: float, hi: float,
              default: float, unit: str = "", key: str = "") -> float:
    """一行参数，返回（可能被改过的）值。key 用于同面板多个同名参数的去重。"""
    uid = "##" + (key or label)

    imgui.push_item_width(150)
    speed = (hi - lo) / 200.0 or 0.01
    _changed, value = imgui.drag_float(label + uid, value, speed, lo, hi, "%.3f")
    imgui.pop_item_width()

    if unit:
        imgui.same_line()
        imgui.text_disabled(unit)

    if abs(value - default) > 1e-6:          # 只在偏离默认值时给复位
        imgui.same_line()
        if imgui.small_button("reset" + uid):
            value = default
    return value
```

调用：

```python
self.cfg["freq"] = param_row("频率", self.cfg["freq"], 1.0, 60.0, 10.0, "Hz", key="freq")
```

坑：

- `drag_float` 的 min/max 传 `0, 0` 表示**不限制**；这里给了真实范围，用户拖不出去。
- 复位按钮的 id 必须和滑杆不同（`reset##freq` vs `频率##freq`），否则 ImGui 认为是一个控件。
- 不要用 `imgui.slider_float` 做参数：滑杆按住时会持续被拖动，输入框输不进去；slider 适合 0–1 的连续量。

---

## 2. 设置面板 + 持久化

**场景**：面板上有几个设置，关掉编辑器再打开要还在。

```python
import json
import os

from imgui_bundle import imgui

from Application.Core.Extension.ExtensionBase import UIExtensionBase


class SettingsExtension(UIExtensionBase):
    id = "settings_demo"
    name = "Settings Demo"
    version = "0.1.0"

    def on_load(self, ctx):
        self.ctx = ctx
        self.cfg = {"freq": 10.0, "gain": 1.0, "show_hint": True}
        self._load()
        ctx.ui.register_window("Settings Demo", self._draw, visible=False)

    # ── 持久化：只写 ctx.data_dir ──
    def _path(self) -> str:
        return os.path.join(self.ctx.data_dir, "settings.json")

    def _load(self) -> None:
        try:
            with open(self._path(), encoding="utf-8") as fh:
                self.cfg.update(json.load(fh))
        except (OSError, ValueError):
            pass                                  # 首次运行/文件坏了 → 用默认值

    def _save(self) -> None:
        os.makedirs(self.ctx.data_dir, exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, ensure_ascii=False, indent=2)

    def _draw(self):
        changed = False
        if imgui.collapsing_header("刺激参数"):   # collapsing_header 不需要 tree_pop
            imgui.push_item_width(150)
            c, v = imgui.drag_float("频率##freq", self.cfg["freq"], 0.1, 1.0, 60.0, "%.1f Hz")
            if c:
                self.cfg["freq"], changed = v, True
            c, v = imgui.drag_float("增益##gain", self.cfg["gain"], 0.01, 0.0, 4.0, "%.2f")
            if c:
                self.cfg["gain"], changed = v, True
            imgui.pop_item_width()

        c, v = imgui.checkbox("显示提示##hint", self.cfg["show_hint"])
        if c:
            self.cfg["show_hint"], changed = v, True

        if changed:
            imgui.same_line()
            imgui.text_disabled("● 未保存")
            if imgui.button("保存"):
                self._save()
                self.ctx.log("settings saved")
```

坑：

- **每帧都不要写盘**。只在「保存」按钮或面板关闭时写（写盘会卡住渲染线程）。
- `ctx.data_dir` 是唯一可写位置；写引擎目录或仓库根会被审查器拒绝。
- `cfg` 结构一旦发布就不要删字段——用户机器上已经有旧 json，用 `update` + 默认值兜底。

---

## 3. 表格：设备 / trial 列表

**场景**：多行数据，能选中、能双击打开、右键有菜单。

```python
from imgui_bundle import imgui


def draw_rows(rows: list[dict], state) -> None:
    flags = (imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_inner_h
             | imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.resizable)
    if not imgui.begin_table("##rows", 3, flags):
        imgui.end_table()                       # 不可见也要收尾
        return

    imgui.table_setup_column("设备", init_width_or_weight=2.0)
    imgui.table_setup_column("状态", init_width_or_weight=1.0)
    imgui.table_setup_column("样本", init_width_or_weight=1.0)
    imgui.table_headers_row()

    for i, row in enumerate(rows):
        imgui.table_next_row()
        imgui.table_next_column()

        selected = (state.selected == i)
        pressed, _ = imgui.selectable(row["name"] + f"##row{i}", selected,
                                      imgui.SelectableFlags_.span_all_columns)
        if pressed:
            state.selected = i
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            state.open_row(i)

        imgui.table_next_column()
        imgui.text_disabled(row["state"])

        imgui.table_next_column()
        imgui.text(str(row["samples"]))

    imgui.end_table()
```

坑：

- **不要写 `from imgui_bundle.imgui import TableFlags_`** —— 那个模块不支持 from-import（会 `ImportError`）。
  统一用 `from imgui_bundle import imgui` 然后 `imgui.TableFlags_.xxx`；`ImVec2/ImVec4` 从 `imgui_bundle` 顶层拿。
- `begin_table` 返回 False 时**也要 `end_table()`**，否则整块 UI 错位。
- 整行可点靠 `SelectableFlags_.span_all_columns`，且 selectable 要在**第一列**画。
- 行内控件 id 必须唯一：`##row{i}`。忘了会出现「点第 3 行，第 1 行高亮」。
- 单元格里要放输入框时，先 `imgui.table_set_column_index(n)` 再画，不要依赖「按顺序画」。

---

## 4. 日志区：自动跟随最新，但用户上滑不打断

**场景**：设备输出/事件日志，新行自动滚到底；用户往上翻看历史时不要抢滚动条。

```python
def draw_log(lines: list[str], state) -> None:
    imgui.begin_child("##log", size=(0, 180), child_flags=imgui.ChildFlags_.borders)

    for line in lines[-800:]:                  # 只画最近 800 行，别让 ImGui 吐
        imgui.text_unformatted(line)

    at_bottom = (imgui.get_scroll_y() >= imgui.get_scroll_max_y()
                 - imgui.get_text_line_height())
    if at_bottom and state.follow:
        imgui.set_scroll_here_y(1.0)
    elif not at_bottom:
        state.follow = False                   # 用户上滑 → 暂停跟随

    imgui.end_child()

    if imgui.button("跟随最新" if not state.follow else "已跟随"):
        state.follow = not state.follow
```

坑：

- 用 `text_unformatted` 而不是 `text`：日志里的 `{}`、`%s` 不会被当成格式串。
- 必须在**画完内容之后**判断 `get_scroll_y`，否则拿到的是上一帧的位置。
- 行数要有上限（这里是切片），无限追加会让每帧耗时线性增长。

---

## 5. 实时波形：环形缓冲 + plot_lines

**场景**：设备数据实时波形（像 VirtualDevice 面板那样）。

```python
import numpy as np
from imgui_bundle import ImVec2, imgui


class Wave:
    def __init__(self, capacity: int = 600):
        self.buf = np.zeros(capacity, dtype=np.float32)
        self.n = 0

    def push(self, samples) -> None:           # 后台线程调用：只动 buffer
        arr = np.asarray(samples, dtype=np.float32).reshape(-1)
        if arr.size >= self.buf.size:
            self.buf[:] = arr[-self.buf.size:]
        else:
            self.buf = np.roll(self.buf, -arr.size)
            self.buf[-arr.size:] = arr

    def draw(self, height: float = 90.0, lo: float = -1.0, hi: float = 1.0) -> None:
        imgui.plot_lines("##wave", self.buf, overlay_text=f"{lo:+.1f} … {hi:+.1f}",
                         scale_min=lo, scale_max=hi, graph_size=ImVec2(0, height))


# 面板里：
self.wave.draw(height=90.0)
```

坑：

- `ImVec2` 从 `imgui_bundle` 顶层导入；`from imgui_bundle.imgui import ImVec2` 会 `ImportError`。
- `plot_lines` 要 `ndarray`（`float32` 最省事）；传 Python list 每帧会多一次转换。
- `graph_size` 宽度传 0 = 占满可用宽度；高度自己定。
- 后台线程**只写 buffer**，不要在里面调 imgui（见 §8）。
- 想要「暂停时冻结显示」：draw 时读一个快照副本，而不是直接读 `buf`。

---

## 6. 确认弹窗：危险操作二次确认

**场景**：删除数据 / 停止实验 / 覆盖文件前问一句。

```python
def draw_delete_button(state, do_delete) -> None:
    if imgui.button("删除全部"):
        imgui.open_popup("##confirm_delete")

    opened, _p_open = imgui.begin_popup_modal("确认删除", True)   # 返回 tuple！
    if not opened:
        return
    imgui.text("将删除当前会话的全部记录，此操作不可撤销。")
    imgui.spacing()
    if imgui.button("删除"):
        do_delete()
        imgui.close_current_popup()
    imgui.same_line()
    if imgui.button("取消"):
        imgui.close_current_popup()
    imgui.end_popup()
```

坑：

- `begin_popup_modal` 在 pybind 里返回 **`(visible, p_open)`**，必须解包；只写 `if imgui.begin_popup_modal(...)` 恒为真。
- `end_popup()` 必须在 `if` 外面？这里 `return` 提前退出了——所以**要么提前 return，要么把 end 放外面**，二选一但必须成对。上面这种写法（先 return）是安全的。
- 弹窗的 label 用 `"确认删除"` 而不是 `"##x"`：用户需要看到标题。
- 模态会挡住整个编辑器；不要在 `draw_fn` 里同步等待用户点击（阻塞渲染线程）。

---

## 7. 禁用与原因：为什么这个按钮不能点

**场景**：没连设备时「开始记录」是灰的，但用户要知道为什么。

```python
def action_buttons(state) -> None:
    can_start = state.device is not None

    imgui.begin_disabled(not can_start)
    clicked = imgui.button("开始记录")
    imgui.end_disabled()                      # 无条件调用！

    if clicked:
        state.start()

    if not can_start and imgui.is_item_hovered(
            imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip("先在上方选择设备")
```

坑：

- `end_disabled()` **必须无条件执行**；写成 `if can_start: begin/end` 会让禁用状态泄漏到后续控件。
- 禁用态默认不触发 hover；要显示原因必须加 `HoveredFlags_.allow_when_disabled`。
- 状态色用主题：`imgui.text_colored(imgui.get_style_color_vec4(imgui.Col_.text_disabled), "...")`；
  自定义红/绿用 `ImVec4`，别混用 `get_color_u32`。

---

## 8. 后台线程 → UI：快照队列

**场景**：采集线程每秒产出数据，面板要显示；直接调用 imgui 会崩。

```python
import queue


class Panel:
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self.samples = []                       # 只由 UI 线程写

    # ── 后台线程：只 put，绝不碰 imgui ──
    def worker_push(self, batch) -> None:
        try:
            self._q.put_nowait(batch)
        except queue.Full:
            pass                                # 丢帧好过阻塞采集

    # ── UI 线程：每帧排空（有上限，防止一帧排太多） ──
    def _drain(self) -> None:
        for _ in range(16):
            try:
                batch = self._q.get_nowait()
            except queue.Empty:
                return
            self.samples = (self.samples + list(batch))[-2000:]

    def _draw(self):
        self._drain()
        imgui.text(f"{len(self.samples)} samples")
```

坑：

- `ctx.ui.post` 目前**未实装**；用线程安全队列 + 帧内排空（上面就是）。
- 队列要有上限并允许丢数据；采集线程被 UI 拖慢比丢几帧严重得多。
- 不要在后台线程里读 `self.cfg` 之类「UI 线程正在改」的 dict；要传值就传不可变快照。

---

## 9. 无头自测 + 提交前检查

**场景**：不想开编辑器就能验证面板不崩、不撕窗口栈。

```python
from flyvibing_extension_kit.imgui_headless import headless_imgui


def test_panel_draws():
    ext = MyExtension()
    ext.on_load(fake_ctx)                   # fake_ctx 提供 ui/ops/data_dir
    with headless_imgui() as h:
        h.frames([(1280, 720), (0, 0), (1, 1)], draw=ext._draw)   # 含极端尺寸
```

提交前：

```powershell
python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>
```

审查器会检查 `UIExtensionBase`、`on_ui_event`、`close_policy`、ops 前缀、**ImGui 窗口栈配对**、
顶层 context/GL 创建等。窗口栈配对这条能抓出 §1/§4/§6 里说的大部分 `begin/end` 问题。

坑：

- 别直接 `imgui.create_context()`：`destroy_context()` 会把 `imgui.ini` 写到当前工作目录；
  `set_ini_filename(None)` 已知会让原生崩溃。用 `headless_imgui()`。
- `(0, 0)` 和 `(1, 1)` 的尺寸是故意的：能抓出除零、负宽度、`push_item_width(0)` 等问题。

---

## 附：这些配方与哪些控件对应

| 配方 | 主要控件 | 详查 |
|---|---|---|
| §1 参数行 | `drag_float` `push_item_width` `same_line` `small_button` | `dev/imgui_api#数值与文本输入` |
| §2 设置 | `collapsing_header` `checkbox` `button` | `dev/imgui_api#容器` |
| §3 表格 | `begin_table` `table_setup_column` `selectable` | `dev/imgui_api#表格` |
| §4 日志 | `begin_child` `text_unformatted` `get_scroll_y` | `dev/imgui_api#容器` |
| §5 波形 | `plot_lines` | `dev/imgui_api#样式` |
| §6 确认框 | `open_popup` `begin_popup_modal` | `dev/imgui_api#弹窗` |
| §7 禁用 | `begin_disabled` `is_item_hovered` `set_tooltip` | `dev/imgui_api#禁用态` |
| §8 线程 | 无（纯队列） | `extdev/ui_development#4` |
| §9 自测 | `headless_imgui` | `extdev/ui_development#5` |

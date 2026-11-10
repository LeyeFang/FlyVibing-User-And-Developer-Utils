# imgui_api.md — 编辑器面板控件目录（imgui-bundle）

> 为写编辑器面板的人（引擎内部 + 扩展作者）准备：按「我要做什么」归类 imgui-bundle 的接口 ——
> 每个按钮/表格/弹窗该调哪个函数、返回什么、有哪些坑；附录给全量索引。
> **本页由 `Utils/Dev/imgui_docgen.py` 生成，勿手改**；签名来自已安装的 `imgui_bundle`，
> 所以升级依赖后重新生成即可看到真实差异。

读法（CLI 按节取，省上下文）：

```powershell
engine-editor-cli doc outline dev/imgui_api              # 章节索引
engine-editor-cli doc show dev/imgui_api#表格            # 单节正文
engine-editor-cli doc search 折叠                        # 跨主题检索
```

配套（扩展作者从这两篇入门，再回这里查控件）：

- `extdev/ui_development.md` —— 面板怎么挂到编辑器（`ctx.ui.register_window`、窗口契约、隔离）
- `extdev/ui_recipes.md` —— 常见面板配方（参数行 / 表格 / 日志 / 波形 / 确认框）
- `dev/ui_protocol.md` —— 引擎内部 UI 层协议（线程、绘制 pass、主题）

---

## 1. 动手前必须知道的约定

下面三条是绝大多数面板 bug 的来源；先记住它们，再去查具体控件。

| 规则 | 说明 |
|---|---|
| **`##` 是 id 作用域** | `"保存##save"` 只显示「保存」，`save` 参与唯一性。循环里画同名控件必须加 `##` 后缀或 `push_id`。 |
| **返回值形状不统一** | `button()` 返回 `bool`；`checkbox/selectable/input_*/drag_*/combo` 返回 `(changed, value)`。**必须解包**，否则 `if imgui.checkbox(...)` 恒为真。 |
| **`begin_*` / `end_*` 与 `push_*` / `pop_*` 必须配对** | 且 `end/pop` 写在 `if` 外面。begin 之后 early `return` 会撕裂栈，下一帧直接崩或整块 UI 错位。 |

其余高频约定：

1. **宽度**：`push_item_width(w)` + `pop_item_width()` 管一段，`set_next_item_width(w)` 只管下一个。
2. **并排**：`same_line()` 接右边的控件；换行用 `new_line()` / `spacing()`。
3. **颜色两套类型**：给 `text_colored` 传 `ImVec4`（用 `get_style_color_vec4`）；
   给 `push_style_color` 传 u32（用 `get_color_u32`）。传错不报错，只是颜色不对。
4. **不要在 `draw_fn` 里开窗口/建 context** —— 宿主已经开好了；见 §16。
5. **导入只有一种写法**：`from imgui_bundle import imgui`（枚举用 `imgui.TableFlags_.xxx`），
   `ImVec2/ImVec4` 从 `imgui_bundle` 顶层拿。
   **`from imgui_bundle.imgui import ImVec2 / TableFlags_` 会 `ImportError`** —— 那个模块不支持 from-import。
6. **异常会被隔离**：绘制抛异常 → 本帧跳过；连续多帧 → 窗口自动隐藏（`ExtensionPanel` 的保险丝）。

---

## 2. flag 速查

值是运行时读出来的（`imgui.<Enum>.<成员>`），**用名字不要抄数字** —— 升级库时数字会变。组合写法：`TableFlags_.row_bg | TableFlags_.borders_inner_h`。

### TableFlags_

表格的形态全靠它。**最常用的一行**：`row_bg | borders_inner_h | sizing_stretch_prop`。

| 成员 | 值 | 用途 |
|---|---|---|
| `TableFlags_.row_bg` | `64` | 隔行底色（长表格必开，扫行不串） |
| `TableFlags_.borders_inner_h` | `128` | 行间横线 |
| `TableFlags_.borders_outer_h` | `256` | 外框横线 |
| `TableFlags_.resizable` | `1` | 列宽可拖 |
| `TableFlags_.sizing_stretch_prop` | `24576` | 按 `init_width_or_weight` 比例分配宽度（自适应首选） |
| `TableFlags_.no_saved_settings` | `16` | 不把列宽写进 imgui.ini（临时表格用） |
| `TableFlags_.scroll_y` | `33554432` | 竖向滚动 |
| `TableFlags_.context_menu_in_body` | `32` | 右键菜单覆盖整个表体 |

### WindowFlags_

主要影响**弹出的小窗口**；主面板窗口的 flag 由宿主决定。

| 成员 | 值 | 用途 |
|---|---|---|
| `WindowFlags_.no_title_bar` | `1` | 无标题栏（自绘标题/浮层） |
| `WindowFlags_.no_resize` | `2` | 禁止改大小（固定尺寸对话框） |
| `WindowFlags_.always_auto_resize` | `64` | 尺寸随内容变化（小提示框） |
| `WindowFlags_.no_saved_settings` | `256` | 不记忆位置尺寸 |
| `WindowFlags_.no_collapse` | `32` | 禁止折叠成标题条 |
| `WindowFlags_.menu_bar` | `1024` | 窗口带菜单栏（要在里面 `begin_menu_bar`） |
| `WindowFlags_.horizontal_scrollbar` | `2048` | 允许横向滚动（宽表格） |

### InputTextFlags_

文本框行为。回车提交、只读、数字字符集最常用。

| 成员 | 值 | 用途 |
|---|---|---|
| `InputTextFlags_.enter_returns_true` | `64` | 回车时返回 changed（「输入即提交」） |
| `InputTextFlags_.auto_select_all` | `4096` | 获得焦点时全选（改名场景） |
| `InputTextFlags_.chars_decimal` | `1` | 只允许数字字符 |
| `InputTextFlags_.read_only` | `512` | 只读但可选中复制 |
| `InputTextFlags_.allow_tab_input` | `32` | Tab 当输入而不是切焦点 |

### TreeNodeFlags_

树节点/折叠块的行为。

| 成员 | 值 | 用途 |
|---|---|---|
| `TreeNodeFlags_.default_open` | `32` | 默认展开 |
| `TreeNodeFlags_.open_on_arrow` | `128` | 只有点箭头才展开（点文字做别的操作用） |
| `TreeNodeFlags_.open_on_double_click` | `64` | 双击展开 |
| `TreeNodeFlags_.span_avail_width` | `2048` | 占满可用宽度（点击区域更大，行选中的常见做法） |
| `TreeNodeFlags_.leaf` | `256` | 标记叶子节点（不画展开箭头） |
| `TreeNodeFlags_.framed` | `2` | 带背景框 |

### SelectableFlags_

列表行的行为。

| 成员 | 值 | 用途 |
|---|---|---|
| `SelectableFlags_.allow_double_click` | `4` | 允许双击 |
| `SelectableFlags_.span_all_columns` | `2` | 跨满表格行（表格里做整行选中必备） |
| `SelectableFlags_.allow_overlap` | `16` | 允许与其它控件重叠 |
| `SelectableFlags_.disabled` | `8` | 禁用态 |

### ComboFlags_

下拉框尺寸档位。

| 成员 | 值 | 用途 |
|---|---|---|
| `ComboFlags_.height_small` | `2` | 小号（约 4 项高） |
| `ComboFlags_.height_regular` | `4` | 标准 |
| `ComboFlags_.height_large` | `8` | 大号（长列表） |

### HoveredFlags_

`is_item_hovered` 的补充条件。

| 成员 | 值 | 用途 |
|---|---|---|
| `HoveredFlags_.allow_when_disabled` | `1024` | 禁用态也算悬停（做「为什么不能点」提示时用） |
| `HoveredFlags_.delay_normal` | `65536` | 短暂延迟后才算悬停（防 tooltip 闪烁） |
| `HoveredFlags_.child_windows` | `1` | 连子窗口一起算 |

### Col_

主题色索引。**不要手写 ColorEdit 字面量**，从主题取（换主题才跟着变）。

| 成员 | 值 | 用途 |
|---|---|---|
| `Col_.text` | `0` | 正文 |
| `Col_.text_disabled` | `1` | 次要/禁用文本 |
| `Col_.button` | `21` | 按钮底色 |
| `Col_.button_hovered` | `22` | 按钮悬停 |
| `Col_.button_active` | `23` | 按钮按下 |
| `Col_.frame_bg` | `7` | 输入框底色 |
| `Col_.frame_bg_hovered` | `8` | 输入框悬停底色 |
| `Col_.popup_bg` | `4` | 弹层底色 |
| `Col_.child_bg` | `3` | 子窗口底色 |
| `Col_.table_header_bg` | `47` | 表头底色 |
| `Col_.check_mark` | `18` | 勾选标记 |
| `Col_.text_selected_bg` | `53` | 选中文本底色 |
| `Col_.separator` | `27` | 分隔线 |
| `Col_.border` | `5` | 边框 |

### StyleVar_

间距/圆角等尺寸变量。传值给 `push_style_var` 时**标量 float**（不要 ImVec2）。

| 成员 | 值 | 用途 |
|---|---|---|
| `StyleVar_.item_spacing` | `14` | 控件间距（最常见的「太挤了」调整项） |
| `StyleVar_.item_inner_spacing` | `15` | 控件内部间距 |
| `StyleVar_.frame_padding` | `11` | 输入框内边距 |
| `StyleVar_.window_padding` | `2` | 窗口内边距 |
| `StyleVar_.cell_padding` | `17` | 表格单元内边距（行高） |
| `StyleVar_.indent_spacing` | `16` | 缩进宽度 |

---

## 3. 文本、分隔与进度

面板里出现最多的一类。全部按「当前行」往后排，需要并排时用 `same_line()`（见 §6）。

- `text(fmt: str) -> None` — 静态文本。`fmt` 支持 printf 风格（`text(f"{n} 项")` 更直观）。
- `text_wrapped(fmt: str) -> None` — 自动折行的文本。面板说明文字用它，**不要自己算宽度**。
- `text_colored(col: ImVec4, fmt: str) -> None` — 带色文本。第一个参数是 `ImVec4`，主题色用 `get_style_color_vec4(Col_.text)`，不要手写字面量。
- `text_disabled(fmt: str) -> None` — 灰字/次要信息（快捷键提示、占位说明、引擎驱动值）。**不表示控件禁用**。
- `bullet_text(fmt: str) -> None` — 带项目符号的一行；适合列表说明。
- `separator() -> None` — 水平分隔线；分组之间用一条即可，不要连续两条。
- `spacing() -> None` — 竖直留白（等于一个 ItemSpacing）。比 `dummy` 语义更明确。
- `new_line() -> None` — 强制换行（`same_line` 的撤销）。
- `align_text_to_frame_padding() -> None` — 让文本基线与右侧输入框对齐；混排 label + 控件时少一行 `same_line`。
- `calc_text_size(text: str, text_end: str | None = None, hide_text_after_double_hash: bool = False, wrap_width: float = -1.0) -> ImVec2` — 量文本尺寸（`(w, h)`），用于自己算列宽或裁剪；结果受当前字体影响。
- `progress_bar(fraction: float, size_arg: ImVec2 | None = None, overlay: str | None = None) -> None` — 只读进度条；传 0.0–1.0。没有对应的「可拖」版本——要拖用 slider。

---

## 4. 按钮、勾选与选择

所有「点一下」的入口。注意 **返回值的形状不统一**：`button` 返回 `bool`，`checkbox`/`selectable` 返回 `(changed, value)`。

- `button(label: str, size: ImVec2 | None = None) -> bool` — 普通按钮，返回是否按下。需要定宽时传 `size=(w, 0)`。
- `small_button(label: str) -> bool` — 小号按钮，常用于行尾的 ✕ / ⚙ 图标。
- `invisible_button(str_id: str, size: ImVec2, flags: int = 0) -> bool` — 不可见但可交互的区域；自绘图表命中检测用。
- `checkbox(label: str, v: bool) -> tuple[bool, bool]` — 复选框，返回 `(changed, v)`。**必须解包成两个变量**，否则永远为真。
- `radio_button(label: str, active: bool) -> bool` — 单选按钮，`(label, active)`；同组自己保证互斥（写 id 后缀或用 `push_id`）。
- `selectable(label: str, p_selected: bool, flags: int = 0, size: ImVec2 | None = None) -> tuple[bool, bool]` — 列表行/下拉项。返回 `(pressed, selected)` —— 仓库里几乎都写 `[0]`。
- `combo(label: str, current_item: int, items: Sequence[str], popup_max_height_in_items: int = -1) -> tuple[bool, int]` — 一次性下拉（常数选项）。最短写法：`combo(label, idx, items)` 返回 `(changed, idx)`。
- `begin_combo(label: str, preview_value: str, flags: int = 0) -> bool` — 可定制下拉的开始（里面自己画 `selectable`）；必须 `end_combo()`。
- `end_combo() -> None` — 结束下拉。**必须在 `if begin_combo(...)` 外面调用**——否则没展开时栈就撕了。
- `begin_list_box(label: str, size: ImVec2 | None = None) -> bool` — 带边框的滚动列表容器（比 combo 更适合长列表/多选）。
- `end_list_box() -> None` — 结束列表容器。

---

## 5. 数值与文本输入

全部返回 `(changed, value)`。**不要原地改传进去的值**——把返回值写回你自己的状态。

- `input_float(label: str, v: float, step: float = 0.0, step_fast: float = 0.0, format: str = '%.3f', flags: int = 0) -> tuple[bool, float]` — 精确输入框（可打字）。适合需要精确值的参数。
- `input_int(label: str, v: int, step: int = 1, step_fast: int = 100, flags: int = 0) -> tuple[bool, int]` — 整数输入框。
- `drag_float(label: str, v: float, v_speed: float = 1.0, v_min: float = 0.0, v_max: float = 0.0, format: str = '%.3f', flags: int = 0) -> tuple[bool, float]` — 拖动滑杆。第 4/5 参数是 min/max：**传 0,0 表示不限制**（引擎里常这样用）。
- `drag_float2(label: str, v: Sequence[float], v_speed: float = 1.0, v_min: float = 0.0, v_max: float = 0.0, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]` — 二维拖动（xy）。
- `drag_float3(label: str, v: Sequence[float], v_speed: float = 1.0, v_min: float = 0.0, v_max: float = 0.0, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]` — 三维拖动（位置/缩放/颜色 RGB）。
- `drag_float4(label: str, v: Sequence[float], v_speed: float = 1.0, v_min: float = 0.0, v_max: float = 0.0, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]` — 四维拖动（颜色 RGBA 的兜底方案）。
- `drag_int(label: str, v: int, v_speed: float = 1.0, v_min: int = 0, v_max: int = 0, format: str = '%d', flags: int = 0) -> tuple[bool, int]` — 整数拖动；同样 `min=max=0` 表示不限制。
- `input_text(label: str, str: str, flags: int = 0, callback: Callable[[InputTextCallbackData], int] | None = None, user_data: types.CapsuleType | None = None) -> tuple[bool, str]` — 单行文本。`flags=InputTextFlags_.enter_returns_true` 可当「回车提交」。
- `input_text_multiline(label: str, str: str, size: ImVec2 | None = None, flags: int = 0, callback: Callable[[InputTextCallbackData], int] | None = None, user_data: types.CapsuleType | None = None) -> tuple[bool, str]` — 多行文本；`size` 给宽高。
- `input_text_with_hint(label: str, hint: str, str: str, flags: int = 0, callback: Callable[[InputTextCallbackData], int] | None = None, user_data: types.CapsuleType | None = None) -> tuple[bool, str]` — 带占位提示的文本框；空值时显示 hint。
- `color_edit4(label: str, col: Sequence[float], flags: int = 0) -> tuple[bool, list[float]]` — 颜色选择器，返回 `(changed, [r,g,b,a])`。想要 HSV 界面传 `ColorEditFlags_.display_hsv`。

---

## 6. 布局：宽度、间距与光标

ImGui 是**立即模式 + 单行流**：控件默认占满可用宽度，并排全靠 `same_line`，宽度全靠 `push_item_width` / `set_next_item_width`。

- `same_line(offset_from_start_x: float = 0.0, spacing: float = -1.0) -> None` — 把下一个控件接到当前行右侧（可给间距）。仓库里用得最多的布局函数。
- `dummy(size: ImVec2) -> None` — 占位盒（`dummy((w, h))`）。撑宽/撑高、占位对齐都靠它。
- `push_item_width(item_width: float) -> None` — 本段控件统一宽度。**必须和 `pop_item_width` 成对**。
- `pop_item_width() -> None` — 结束统一宽度。
- `set_next_item_width(item_width: float) -> None` — 只影响下一个控件宽度（比 push/pop 轻，适合单个例外）。
- `get_content_region_avail() -> ImVec2` — 当前可用区域 `(w, h)`；画满宽表格/子窗口前先问它。
- `get_cursor_pos_x() -> float` — 光标 x（窗口局部坐标）。
- `get_cursor_pos_y() -> float` — 光标 y（窗口局部坐标）。
- `set_cursor_pos_x(local_x: float) -> None` — 跳到指定 x（局部坐标）。
- `set_cursor_pos_y(local_y: float) -> None` — 跳到指定 y（局部坐标）——自己排版时用它换行。
- `get_cursor_screen_pos() -> ImVec2` — 光标屏幕坐标（绝对）；自绘/命中检测用。
- `set_cursor_screen_pos(pos: ImVec2) -> None` — 跳到屏幕绝对坐标（画浮层时用）。
- `get_item_rect_min() -> ImVec2` — 上一个控件左上角屏幕坐标；画包围框/锚点用。
- `get_item_rect_max() -> ImVec2` — 上一个控件右下角屏幕坐标。
- `get_text_line_height() -> float` — 一行文本的高度（做垂直居中的常量）。
- `get_frame_height() -> float` — 一个输入框/按钮的标准高度。

---

## 7. 容器：子窗口 / 标签页 / 折叠树

容器类全部是 `begin_*` + `end_*`。**规则：`end_*` 一定在 `if` 外面**，并且不要在 begin 和 end 之间 `return`。

- `begin_child(str_id: str, size: ImVec2 | None = None, child_flags: int = 0, window_flags: int = 0) -> bool` — 可滚动的子区域：日志、长列表、固定高度的波形槽。第一个参数是 id（可 `##`）。
- `end_child() -> None` — 结束子区域。
- `begin_tab_bar(str_id: str, flags: int = 0) -> bool` — 标签栏开始；里面放 `begin_tab_item`。
- `end_tab_bar() -> None` — 结束标签栏。
- `begin_tab_item(label: str, p_open: bool | None = None, flags: int = 0) -> tuple[bool, bool | None]` — 单个标签页，返回 `(visible, p_open)`；**内容只在 visible 时画**。
- `end_tab_item() -> None` — 结束标签页（在 if 外面调）。
- `collapsing_header(label: str, flags: int = 0) -> bool` — 可折叠分组标题（比 tree_node 更像「小节」）。
- `tree_node(label: str) -> bool` — 树节点 / 折叠块，返回是否展开；`##` 控制 id。
- `tree_node_ex(label: str, flags: int = 0) -> bool` — 带 flags 的树节点；常用 `default_open`、`open_on_arrow`、`leaf`、`span_avail_width`。
- `tree_pop() -> None` — 结束 tree/collapsing 层级（在 if 外面调）。
- `set_next_item_open(is_open: bool, cond: int = 0) -> None` — 强制下一个树节点展开/收起（默认展开、搜索命中自动展开）。
- `push_id(str_id: str) -> None` — 压入 id 作用域：让内部同名控件互不冲突（循环里画同类控件时必备）。
- `pop_id() -> None` — 结束 id 作用域。
- `get_id(str_id: str) -> int` — 字符串 → id（自绘/手动匹配时用）。

---

## 8. 表格

设备列表、参数矩阵、trial 表都用它。三步：`begin_table` → `table_setup_column` × N → 循环里 `table_next_row` / `table_next_column` → `end_table`。

- `begin_table(str_id: str, columns: int, flags: int = 0, outer_size: ImVec2 | None = None, inner_width: float = 0.0) -> bool` — 开始表格，返回是否可见（不可见时也要走完 setup + end_table）。
- `table_setup_column(label: str, flags: int = 0, init_width_or_weight: float = 0.0, user_id: int = 0) -> None` — 声明一列：`label` 是表头文本，`init_width_or_weight` 在 stretch 模式下是权重。
- `table_headers_row() -> None` — 画出表头行（调用一次，在 setup 之后）。
- `table_next_row(row_flags: int = 0, min_row_height: float = 0.0) -> None` — 换行；表头之后第一次调用会跳过表头行。
- `table_next_column() -> bool` — 换到下一列，返回是否还有列（超出会返回 False）。
- `table_set_column_index(column_n: int) -> bool` — 直接跳到第 n 列（画不规则行时用）。
- `table_setup_scroll_freeze(cols: int, rows: int) -> None` — 冻结前 N 列 / 前 N 行（长表格固定表头）。
- `end_table() -> None` — 结束表格（无论如何都要调到）。

---

## 9. 弹窗、菜单与提示

三类东西容易混：**popup**（点出来的浮层）、**modal**（挡住整个编辑器的对话框）、**tooltip**（悬停提示）。它们的 begin/end 规则都一样：`end` 在 `if` 外面。

- `open_popup(str_id: str, popup_flags: int = 0) -> None` — 打开一个 popup（配合 `begin_popup` 使用）。
- `begin_popup(str_id: str, flags: int = 0) -> bool` — popup 开始，返回是否打开；必须 `end_popup()`。
- `end_popup() -> None` — 结束 popup。
- `close_current_popup() -> None` — 关闭当前 popup（选中一项后调）。
- `begin_popup_modal(name: str, p_open: bool | None = None, flags: int = 0) -> tuple[bool, bool | None]` — 模态对话框，返回 `(open, p_open)`；必须 `end_popup()`。
- `begin_popup_context_item(str_id: str | None = None, popup_flags: int = 1) -> bool` — 右键菜单（针对上一个控件）。
- `begin_popup_context_window(str_id: str | None = None, popup_flags: int = 1) -> bool` — 右键菜单（针对窗口空白处）。
- `begin_menu(label: str, enabled: bool = True) -> bool` — 下拉菜单项的开始（放在菜单栏里）；返回是否展开。
- `end_menu() -> None` — 结束菜单。
- `menu_item(label: str, shortcut: str, p_selected: bool, enabled: bool = True) -> tuple[bool, bool]` — 菜单行，返回 `(pressed, selected)`；`shortcut` 只作展示，不会真的绑键。
- `begin_main_menu_bar() -> bool` — 窗口顶部菜单栏（宿主已有一层，扩展一般不用自己开）。
- `end_main_menu_bar() -> None` — 结束菜单栏。
- `set_tooltip(fmt: str) -> None` — 悬停提示（在 `is_item_hovered()` 分支里调，不要每帧无脑调）。
- `begin_tooltip() -> bool` — 自定义 tooltip 内容的开始。
- `end_tooltip() -> None` — 结束 tooltip。
- `begin_item_tooltip() -> bool` — 给上一个控件挂 tooltip 的简写（里面画内容，`end_tooltip` 收尾）。
- `set_item_tooltip(fmt: str) -> None` — 给上一个控件设纯文本 tooltip（最省事）。
- `set_next_window_focus() -> None` — 让下一个窗口/弹窗获得焦点（弹出确认框时用）。

---

## 10. 交互状态（点击 / 悬停 / 焦点）

都是查「上一个控件」的状态。**必须在画完控件之后、下一个控件之前**调用。

- `is_item_hovered(flags: int = 0) -> bool` — 上一个控件是否被悬停（tooltip、右键菜单的入口）。
- `is_item_clicked(mouse_button: int = 0) -> bool` — 上一个控件是否被点击（可指定鼠标键）。
- `is_item_active() -> bool` — 上一个控件是否处于激活态（按住/正在编辑）。
- `is_item_focused() -> bool` — 上一个控件是否有键盘焦点。
- `is_item_deactivated_after_edit() -> bool` — 输入类控件「编辑完成」的瞬间——提交值的好时机。
- `set_item_default_focus() -> None` — 让下一个控件默认获得焦点（combo/输入框弹出的首选行）。
- `set_keyboard_focus_here(offset: int = 0) -> None` — 把键盘焦点给下一个控件（打开面板后直接可打字）。

---

## 11. 禁用态（包住任意控件）

「现在不能点」的标准写法：把控件包在 `begin_disabled(True)` / `end_disabled()` 之间。**`end_disabled()` 必须在 `if` 外面**；`begin_disabled(False)` 也会压栈，所以不要用条件去跳过 begin。

- `begin_disabled(disabled: bool = True) -> None` — 开始禁用区（可传 False 作为「条件禁用」的写法，仍然要配对 end）。
- `end_disabled() -> None` — 结束禁用区。**无条件调用**，否则后续所有控件都会被连带禁用。

---

## 12. 拖放

源 + 目标成对使用；载荷类型用字符串区分（`"ENTITY"` / `"ASSET"`）。

- `begin_drag_drop_source(flags: int = 0) -> bool` — 拖放源开始，返回是否在拖。
- `end_drag_drop_source() -> None` — 结束源（在 if 外面）。
- `set_drag_drop_payload_py_id(type: str, data_id: int, cond: int = 0) -> bool` — 写入载荷（`py_id` 变体传整数 id，是 pybind 的安全版）。
- `begin_drag_drop_target() -> bool` — 拖放目标开始，返回是否有东西悬在上面。
- `end_drag_drop_target() -> None` — 结束目标（在 if 外面）。
- `accept_drag_drop_payload_py_id(type: str, flags: int = 0) -> Payload_PyId | None` — 接受并取回载荷整数 id。

---

## 13. 样式与颜色（含自绘）

颜色有两套表示：**`Col_` 索引 + u32**（`push_style_color` / `get_color_u32`）和 **`ImVec4`**（`text_colored` / `get_style_color_vec4`）。传错类型是静默错色。

- `push_style_color(idx: int, col: int) -> None` — 临时改颜色（`push_style_color(Col_.button, get_color_u32(Col_.button_hovered))`）。
- `pop_style_color(count: int = 1) -> None` — 恢复颜色；**参数是压入的层数**，默认 1。
- `push_style_var(idx: int, val: float) -> None` — 临时改尺寸/间距（`StyleVar_.item_spacing` 等），值传 float。
- `pop_style_var(count: int = 1) -> None` — 恢复；同样按层数弹。
- `get_style() -> Style` — 拿全局 Style（读 `item_spacing`、`frame_padding` 等实际值）。
- `get_color_u32(idx: int, alpha_mul: float = 1.0) -> int` — `Col_` → u32 颜色（给 `push_style_color` 用，可带 alpha 乘子）。
- `get_style_color_vec4(idx: int) -> ImVec4` — `Col_` → `ImVec4`（给 `text_colored` 用）。
- `get_window_draw_list() -> ImDrawList` — 当前窗口的 DrawList，自绘波形/连线/高亮的入口（不走控件布局）。
- `push_text_wrap_pos(wrap_local_pos_x: float = 0.0) -> None` — 临时设定折行宽度（配合 `text_wrapped`）。
- `pop_text_wrap_pos() -> None` — 恢复折行宽度。

---

## 14. 键盘鼠标原始输入

面板里**优先用控件返回值**；只有在自绘/拖拽/快捷键时才直接查输入。

- `is_mouse_down(button: int) -> bool` — 鼠标键是否按住（0=左 1=右 2=中）。
- `is_mouse_clicked(button: int, repeat: bool = False) -> bool` — 本帧是否按下。
- `is_mouse_double_clicked(button: int) -> bool` — 本帧是否双击。
- `is_mouse_released(button: int) -> bool` — 本帧是否松开。
- `is_key_down(key: Key) -> bool` — 键是否按住（`imgui.Key.space` 等）。
- `is_key_pressed(key: Key, repeat: bool = True) -> bool` — 本帧是否按下（可关掉 repeat）。
- `get_mouse_pos() -> ImVec2` — 鼠标位置（窗口坐标）。
- `get_io() -> IO` — IO 单例：`io.want_capture_mouse` / `want_text_input` 判「该不该响应」。

---

## 15. 窗口级接口（宿主负责，只在必要时用）

扩展的 `draw_fn` 跑在宿主已经开好的窗口里，**不要再 `begin`/`end`**。下面这些只在做弹窗、定位浮层时例外。

- `begin(name: str, p_open: bool | None = None, flags: int = 0) -> tuple[bool, bool | None]` — 开窗口。**扩展禁用**：宿主 `BasePanel` 已经开好了。
- `end() -> None` — 关窗口。**扩展禁用**，理由同上。
- `get_window_pos() -> ImVec2` — 当前窗口左上角（屏幕坐标）。
- `get_window_size() -> ImVec2` — 当前窗口尺寸。
- `set_next_window_pos(pos: ImVec2, cond: int = 0, pivot: ImVec2 | None = None) -> None` — 设定下一个窗口/弹窗位置（`cond=ImGuiCond_.appearing` 只首次生效）。
- `set_next_window_size(size: ImVec2, cond: int = 0) -> None` — 设定下一个窗口/弹窗尺寸。
- `set_window_size(size: ImVec2, cond: int = 0) -> None` — 改当前窗口尺寸。
- `get_main_viewport() -> Viewport` — 主视口（多显示器/DPI 时算绝对坐标）。
- `set_mouse_cursor(cursor_type: int) -> None` — 改鼠标指针形状（拖拽/缩放时反馈）。
- `set_clipboard_text(text: str) -> None` — 写系统剪贴板（「复制路径」这类操作）。
- `push_font(font: ImFont | None, font_size_base_unscaled: float) -> None` — 临时换字号：`push_font(font, size)`（1.92 起没有 `set_window_font_scale`）。
- `pop_font() -> None` — 恢复字号，与 `push_font` 成对。

---

## 16. 宿主侧 / 禁止调用

这些是**引擎渲染管线**在用（`EditorImguiLayer` 等）。扩展或普通面板调用会破坏帧循环，或者干脆崩。列在这里是为了「搜到也知道不能用」。

- `create_context(shared_font_atlas: ImFontAtlas | None = None) -> internal.Context` — 建 ImGui 上下文。**禁止**：宿主已建；测试用 `flyvibing_extension_kit.imgui_headless`。
- `destroy_context(ctx: internal.Context | None = None) -> None` — 销毁上下文。**禁止**，同上。
- `get_current_context() -> internal.Context` — 取当前上下文。**禁止**，除非在写宿主层。
- `new_frame() -> None` — 开新帧。**禁止**：帧由 `EditorImguiLayer` 驱动。
- `end_frame() -> None` — 结束帧。**禁止**。
- `render() -> None` — 提交绘制数据。**禁止**。
- `get_draw_data() -> ImDrawData` — 取绘制数据。**禁止**。
- `dock_space(dockspace_id: int, size: ImVec2 | None = None, flags: int = 0, window_class: WindowClass | None = None) -> int` — 建 DockSpace。**禁止**：停靠由宿主统一管理。
- `set_next_window_dock_id(dock_id: int, cond: int = 0) -> None` — 指定停靠目标。**禁止**：同上。

---

## 17. 附录：其余公开接口

下面是当前 `imgui_bundle` 里**不在上面分组中**的接口（函数 230 个 / 枚举 51 个 / 类型 95 个）。只列签名，不解释 —— 目的是「想到某个功能时能搜到名字」，真正要用之前先确认它不会破坏帧循环（§16）。

> 本节很长：**不要整节读**。用 `engine-editor-cli doc search <关键词>` 定位，或 `doc show dev/imgui_api#附录` 后按字母扫。真正推荐的用法都在 §3–§16。

### A. 函数（按字母）

- `IM_COL32(arg0: int, arg1: int, arg2: int, arg3: int, /) -> int`
- `arrow_button(str_id: str, dir: Dir) -> bool`
- `begin_group() -> None`
- `begin_horizontal(str_id: str, size: ImVec2 | None = None, align: float = -1.0) -> None`
- `begin_menu_bar() -> bool`
- `begin_multi_select(flags: int, selection_size: int = -1, items_count: int = -1) -> MultiSelectIO`
- `begin_popup_context_void(str_id: str | None = None, popup_flags: int = 1) -> bool`
- `begin_tab_item_simple(label: str, flags: int = 0) -> bool`
- `begin_vertical(str_id: str, size: ImVec2 | None = None, align: float = -1.0) -> None`
- `bullet() -> None`
- `calc_item_width() -> float`
- `checkbox_flags(label: str, flags: int, flags_value: int) -> tuple[bool, int]`
- `color_button(desc_id: str, col: ImVec4, flags: int = 0, size: ImVec2 | None = None) -> bool`
- `color_convert_float4_to_u32(in_: ImVec4) -> int`
- `color_convert_hsv_to_rgb(h: float, s: float, v: float, out_r: float, out_g: float, out_b: float) -> tuple[float, float, float]`
- `color_convert_rgb_to_hsv(r: float, g: float, b: float, out_h: float, out_s: float, out_v: float) -> tuple[float, float, float]`
- `color_convert_u32_to_float4(in_: int) -> ImVec4`
- `color_edit3(label: str, col: Sequence[float], flags: int = 0) -> tuple[bool, list[float]]`
- `color_picker3(label: str, col: Sequence[float], flags: int = 0) -> tuple[bool, list[float]]`
- `color_picker4(label: str, col: ImVec4, flags: int = 0, ref_col: ImVec4 | None = None) -> tuple[bool, ImVec4]`
- `columns(count: int = 1, id_: str | None = None, borders: bool = True) -> None`
- `debug_check_version_and_data_layout(version_str: str, sz_io: int, sz_style: int, sz_vec2: int, sz_vec4: int, sz_drawvert: int, sz_drawidx: int) -> bool`
- `debug_flash_style_color(idx: int) -> None`
- `debug_start_item_picker() -> None`
- `debug_text_encoding(text: str) -> None`
- `destroy_platform_windows() -> None`
- `dock_space_over_viewport(dockspace_id: int = 0, viewport: Viewport | None = None, flags: int = 0, window_class: WindowClass | None = None) -> int`
- `drag_float_range2(label: str, v_current_min: float, v_current_max: float, v_speed: float = 1.0, v_min: float = 0.0, v_max: float = 0.0, format: str = '%.3f', format_max: str | None = None, flags: int = 0) -> tuple[bool, float, float]`
- `drag_int2(label: str, v: Sequence[int], v_speed: float = 1.0, v_min: int = 0, v_max: int = 0, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `drag_int3(label: str, v: Sequence[int], v_speed: float = 1.0, v_min: int = 0, v_max: int = 0, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `drag_int4(label: str, v: Sequence[int], v_speed: float = 1.0, v_min: int = 0, v_max: int = 0, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `drag_int_range2(label: str, v_current_min: int, v_current_max: int, v_speed: float = 1.0, v_min: int = 0, v_max: int = 0, format: str = '%d', format_max: str | None = None, flags: int = 0) -> tuple[bool, int, int]`
- `drag_scalar(label: str, data_type: int, p_data: types.CapsuleType, v_speed: float = 1.0, p_min: types.CapsuleType | None = None, p_max: types.CapsuleType | None = None, format: str | None = None, flags: int = 0) -> bool`
- `drag_scalar_n(label: str, data_type: int, p_data: types.CapsuleType, components: int, v_speed: float = 1.0, p_min: types.CapsuleType | None = None, p_max: types.CapsuleType | None = None, format: str | None = None, flags: int = 0) -> bool`
- `end_group() -> None`
- `end_horizontal() -> None`
- `end_menu_bar() -> None`
- `end_multi_select() -> MultiSelectIO`
- `end_vertical() -> None`
- `find_viewport_by_id(id_: int) -> Viewport`
- `find_viewport_by_platform_handle(platform_handle: types.CapsuleType) -> Viewport`
- `get_background_draw_list(viewport: Viewport | None = None) -> ImDrawList`
- `get_clipboard_text() -> str`
- `get_column_index() -> int`
- `get_column_offset(column_index: int = -1) -> float`
- `get_column_width(column_index: int = -1) -> float`
- `get_columns_count() -> int`
- `get_cursor_pos() -> ImVec2`
- `get_cursor_start_pos() -> ImVec2`
- `get_drag_drop_payload_py_id() -> Payload_PyId | None`
- `get_draw_list_shared_data() -> internal.ImDrawListSharedData`
- `get_font() -> ImFont`
- `get_font_baked() -> ImFontBaked`
- `get_font_size() -> float`
- `get_font_tex_uv_white_pixel() -> ImVec2`
- `get_foreground_draw_list(viewport: Viewport | None = None) -> ImDrawList`
- `get_frame_count() -> int`
- `get_frame_height_with_spacing() -> float`
- `get_imgui_demo_marker_is_active() -> bool`
- `get_item_id() -> int`
- `get_item_rect_size() -> ImVec2`
- `get_key_name(key: Key) -> str`
- `get_key_pressed_amount(key: Key, repeat_delay: float, rate: float) -> int`
- `get_mouse_clicked_count(button: int) -> int`
- `get_mouse_cursor() -> int`
- `get_mouse_drag_delta(button: int = 0, lock_threshold: float = -1.0) -> ImVec2`
- `get_mouse_pos_on_opening_current_popup() -> ImVec2`
- `get_platform_io() -> PlatformIO`
- `get_scroll_max_x() -> float`
- `get_scroll_max_y() -> float`
- `get_scroll_x() -> float`
- `get_scroll_y() -> float`
- `get_state_storage() -> Storage`
- `get_style_color_name(idx: int) -> str`
- `get_text_line_height_with_spacing() -> float`
- `get_time() -> float`
- `get_tree_node_to_label_spacing() -> float`
- `get_version() -> str`
- `get_window_dock_id() -> int`
- `get_window_dpi_scale() -> float`
- `get_window_height() -> float`
- `get_window_viewport() -> Viewport`
- `get_window_width() -> float`
- `image(tex_ref: ImTextureRef, image_size: ImVec2, uv0: ImVec2 | None = None, uv1: ImVec2 | None = None) -> None`
- `image_button(str_id: str, tex_ref: ImTextureRef, image_size: ImVec2, uv0: ImVec2 | None = None, uv1: ImVec2 | None = None, bg_col: ImVec4 | None = None, tint_col: ImVec4 | None = None) -> bool`
- `image_with_bg(tex_ref: ImTextureRef, image_size: ImVec2, uv0: ImVec2 | None = None, uv1: ImVec2 | None = None, bg_col: ImVec4 | None = None, tint_col: ImVec4 | None = None) -> None`
- `indent(indent_w: float = 0.0) -> None`
- `input_double(label: str, v: float, step: float = 0.0, step_fast: float = 0.0, format: str = '%.6f', flags: int = 0) -> tuple[bool, float]`
- `input_float2(label: str, v: Sequence[float], format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `input_float3(label: str, v: Sequence[float], format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `input_float4(label: str, v: Sequence[float], format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `input_int2(label: str, v: Sequence[int], flags: int = 0) -> tuple[bool, list[int]]`
- `input_int3(label: str, v: Sequence[int], flags: int = 0) -> tuple[bool, list[int]]`
- `input_int4(label: str, v: Sequence[int], flags: int = 0) -> tuple[bool, list[int]]`
- `input_scalar(label: str, data_type: int, p_data: types.CapsuleType, p_step: types.CapsuleType | None = None, p_step_fast: types.CapsuleType | None = None, format: str | None = None, flags: int = 0) -> bool`
- `input_scalar_n(label: str, data_type: int, p_data: types.CapsuleType, components: int, p_step: types.CapsuleType | None = None, p_step_fast: types.CapsuleType | None = None, format: str | None = None, flags: int = 0) -> bool`
- `is_any_item_active() -> bool`
- `is_any_item_focused() -> bool`
- `is_any_item_hovered() -> bool`
- `is_any_mouse_down() -> bool`
- `is_item_activated() -> bool`
- `is_item_deactivated() -> bool`
- `is_item_edited() -> bool`
- `is_item_toggled_open() -> bool`
- `is_item_toggled_selection() -> bool`
- `is_item_visible() -> bool`
- `is_key_chord_pressed(key_chord: int) -> bool`
- `is_key_released(key: Key) -> bool`
- `is_mouse_dragging(button: int, lock_threshold: float = -1.0) -> bool`
- `is_mouse_hovering_rect(r_min: ImVec2, r_max: ImVec2, clip: bool = True) -> bool`
- `is_mouse_pos_valid(mouse_pos: ImVec2 | None = None) -> bool`
- `is_mouse_released_with_delay(button: int, delay: float) -> bool`
- `is_popup_open(str_id: str, flags: int = 0) -> bool`
- `is_rect_visible(size: ImVec2) -> bool`
- `is_window_appearing() -> bool`
- `is_window_collapsed() -> bool`
- `is_window_docked() -> bool`
- `is_window_focused(flags: int = 0) -> bool`
- `is_window_hovered(flags: int = 0) -> bool`
- `label_text(label: str, fmt: str) -> None`
- `list_box(label: str, current_item: int, items: Sequence[str], height_in_items: int = -1) -> tuple[bool, int]`
- `load_ini_settings_from_disk(ini_filename: str) -> None`
- `load_ini_settings_from_memory(ini_data: str, ini_size: int = 0) -> None`
- `log_buttons() -> None`
- `log_finish() -> None`
- `log_text(fmt: str) -> None`
- `log_to_clipboard(auto_open_depth: int = -1) -> None`
- `log_to_file(auto_open_depth: int = -1, filename: str | None = None) -> None`
- `log_to_tty(auto_open_depth: int = -1) -> None`
- `menu_item_simple(label: str, shortcut: str | None = None, selected: bool = False, enabled: bool = True) -> bool`
- `next_column() -> None`
- `open_popup_on_item_click(str_id: str | None = None, popup_flags: int = 1) -> None`
- `plot_histogram(label: str, values: ndarray[], values_offset: int = 0, overlay_text: str | None = None, scale_min: float = 3.4028234663852886e+38, scale_max: float = 3.4028234663852886e+38, graph_size: ImVec2 | None = None, stride: int = -1) -> None`
- `plot_lines(label: str, values: ndarray[], values_offset: int = 0, overlay_text: str | None = None, scale_min: float = 3.4028234663852886e+38, scale_max: float = 3.4028234663852886e+38, graph_size: ImVec2 | None = None, stride: int = -1) -> None`
- `pop_clip_rect() -> None`
- `pop_item_flag() -> None`
- `push_clip_rect(clip_rect_min: ImVec2, clip_rect_max: ImVec2, intersect_with_current_clip_rect: bool) -> None`
- `push_item_flag(option: int, enabled: bool) -> None`
- `push_style_var_x(idx: int, val_x: float) -> None`
- `push_style_var_y(idx: int, val_y: float) -> None`
- `render_platform_windows_default(platform_render_arg: types.CapsuleType | None = None, renderer_render_arg: types.CapsuleType | None = None) -> None`
- `reset_mouse_drag_delta(button: int = 0) -> None`
- `resume_layout() -> None`
- `save_ini_settings_to_disk(ini_filename: str) -> None`
- `save_ini_settings_to_memory() -> str`
- `separator_text(label: str) -> None`
- `set_color_edit_options(flags: int) -> None`
- `set_column_offset(column_index: int, offset_x: float) -> None`
- `set_column_width(column_index: int, width: float) -> None`
- `set_current_context(ctx: internal.Context) -> None`
- `set_cursor_pos(local_pos: ImVec2) -> None`
- `set_drag_drop_payload(type: str, data: types.CapsuleType, sz: int, cond: int = 0) -> bool`
- `set_imgui_demo_code_window_pos(arg0: ImVec2, arg1: ImVec2, arg2: int, /) -> None`
- `set_imgui_demo_marker_is_active(arg: bool, /) -> None`
- `set_imgui_demo_show_python_code(arg: bool, /) -> None`
- `set_imgui_demo_window_pos(arg0: ImVec2, arg1: ImVec2, arg2: int, /) -> None`
- `set_item_key_owner(key: Key) -> None`
- `set_nav_cursor_visible(visible: bool) -> None`
- `set_next_frame_want_capture_keyboard(want_capture_keyboard: bool) -> None`
- `set_next_frame_want_capture_mouse(want_capture_mouse: bool) -> None`
- `set_next_item_allow_overlap() -> None`
- `set_next_item_selection_user_data(selection_user_data: int) -> None`
- `set_next_item_shortcut(key_chord: int, flags: int = 0) -> None`
- `set_next_item_storage_id(storage_id: int) -> None`
- `set_next_window_bg_alpha(alpha: float) -> None`
- `set_next_window_class(window_class: WindowClass) -> None`
- `set_next_window_collapsed(collapsed: bool, cond: int = 0) -> None`
- `set_next_window_content_size(size: ImVec2) -> None`
- `set_next_window_scroll(scroll: ImVec2) -> None`
- `set_next_window_size_constraints(size_min: ImVec2, size_max: ImVec2, custom_callback: Callable[[SizeCallbackData], None] | None = None, custom_callback_data: types.CapsuleType | None = None) -> None`
- `set_next_window_viewport(viewport_id: int) -> None`
- `set_scroll_from_pos_x(local_x: float, center_x_ratio: float = 0.5) -> None`
- `set_scroll_from_pos_y(local_y: float, center_y_ratio: float = 0.5) -> None`
- `set_scroll_here_x(center_x_ratio: float = 0.5) -> None`
- `set_scroll_here_y(center_y_ratio: float = 0.5) -> None`
- `set_scroll_x(scroll_x: float) -> None`
- `set_scroll_y(scroll_y: float) -> None`
- `set_state_storage(storage: Storage) -> None`
- `set_tab_item_closed(tab_or_docked_window_label: str) -> None`
- `set_window_collapsed(collapsed: bool, cond: int = 0) -> None`
- `set_window_focus() -> None`
- `set_window_pos(pos: ImVec2, cond: int = 0) -> None`
- `shortcut(key_chord: int, flags: int = 0) -> bool`
- `show_about_window(p_open: bool | None = None) -> bool | None`
- `show_debug_log_window(p_open: bool | None = None) -> bool | None`
- `show_demo_window(p_open: bool | None = None) -> bool | None`
- `show_font_selector(label: str) -> None`
- `show_id_stack_tool_window(p_open: bool | None = None) -> bool | None`
- `show_metrics_window(p_open: bool | None = None) -> bool | None`
- `show_style_editor(ref: Style | None = None) -> None`
- `show_style_selector(label: str) -> bool`
- `show_user_guide() -> None`
- `slider_angle(label: str, v_rad: float, v_degrees_min: float = -360.0, v_degrees_max: float = 360.0, format: str = '%.0f deg', flags: int = 0) -> tuple[bool, float]`
- `slider_float(label: str, v: float, v_min: float, v_max: float, format: str = '%.3f', flags: int = 0) -> tuple[bool, float]`
- `slider_float2(label: str, v: Sequence[float], v_min: float, v_max: float, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `slider_float3(label: str, v: Sequence[float], v_min: float, v_max: float, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `slider_float4(label: str, v: Sequence[float], v_min: float, v_max: float, format: str = '%.3f', flags: int = 0) -> tuple[bool, list[float]]`
- `slider_int(label: str, v: int, v_min: int, v_max: int, format: str = '%d', flags: int = 0) -> tuple[bool, int]`
- `slider_int2(label: str, v: Sequence[int], v_min: int, v_max: int, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `slider_int3(label: str, v: Sequence[int], v_min: int, v_max: int, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `slider_int4(label: str, v: Sequence[int], v_min: int, v_max: int, format: str = '%d', flags: int = 0) -> tuple[bool, list[int]]`
- `slider_scalar(label: str, data_type: int, p_data: types.CapsuleType, p_min: types.CapsuleType, p_max: types.CapsuleType, format: str | None = None, flags: int = 0) -> bool`
- `slider_scalar_n(label: str, data_type: int, p_data: types.CapsuleType, components: int, p_min: types.CapsuleType, p_max: types.CapsuleType, format: str | None = None, flags: int = 0) -> bool`
- `spring(weight: float = 1.0, spacing: float = -1.0) -> None`
- `style_colors_classic(dst: Style | None = None) -> None`
- `style_colors_dark(dst: Style | None = None) -> None`
- `style_colors_light(dst: Style | None = None) -> None`
- `suspend_layout() -> None`
- `tab_item_button(label: str, flags: int = 0) -> bool`
- `table_angled_headers_row() -> None`
- `table_get_column_count() -> int`
- `table_get_column_flags(column_n: int = -1) -> int`
- `table_get_column_index() -> int`
- `table_get_column_name(column_n: int = -1) -> str`
- `table_get_hovered_column() -> int`
- `table_get_row_index() -> int`
- `table_get_sort_specs() -> TableSortSpecs`
- `table_header(label: str) -> None`
- `table_set_bg_color(target: int, color: int, column_n: int = -1) -> None`
- `table_set_column_enabled(column_n: int, v: bool) -> None`
- `text_link(label: str) -> bool`
- `text_link_open_url(label: str, url: str | None = None) -> bool`
- `text_unformatted(text: str, text_end: str | None = None) -> None`
- `tree_push(str_id: str) -> None`
- `unindent(indent_w: float = 0.0) -> None`
- `update_platform_windows() -> None`
- `v_slider_float(label: str, size: ImVec2, v: float, v_min: float, v_max: float, format: str = '%.3f', flags: int = 0) -> tuple[bool, float]`
- `v_slider_int(label: str, size: ImVec2, v: int, v_min: int, v_max: int, format: str = '%d', flags: int = 0) -> tuple[bool, int]`
- `v_slider_scalar(label: str, size: ImVec2, data_type: int, p_data: types.CapsuleType, p_min: types.CapsuleType, p_max: types.CapsuleType, format: str | None = None, flags: int = 0) -> bool`
- `value(prefix: str, b: bool) -> None`

### B. 枚举（可用作 flag / 颜色 / 样式索引）

| 枚举 | 成员数 | 例子 |
|---|---|---|
| `imgui.BackendFlags_` | 9 | `has_gamepad`, `has_mouse_cursors`, `has_mouse_hovered_viewport`, `has_set_mouse_pos` |
| `imgui.ButtonFlags_` | 6 | `enable_nav`, `mouse_button_left`, `mouse_button_mask_`, `mouse_button_middle` |
| `imgui.ChildFlags_` | 10 | `always_auto_resize`, `always_use_window_padding`, `auto_resize_x`, `auto_resize_y` |
| `imgui.Col_` | 61 | `border`, `border_shadow`, `button`, `button_active` |
| `imgui.ColorEditFlags_` | 31 | `alpha_bar`, `alpha_mask_`, `alpha_no_bg`, `alpha_opaque` |
| `imgui.ComboFlags_` | 10 | `height_large`, `height_largest`, `height_mask_`, `height_regular` |
| `imgui.Cond_` | 5 | `always`, `appearing`, `first_use_ever`, `none` |
| `imgui.ConfigFlags_` | 10 | `docking_enable`, `is_srgb`, `is_touch_screen`, `nav_enable_gamepad` |
| `imgui.DataType_` | 13 | `bool`, `count`, `double`, `float` |
| `imgui.Dir` | 6 | `count`, `down`, `left`, `none` |
| `imgui.Dir_` | 6 | `count`, `down`, `left`, `none` |
| `imgui.DockNodeFlags_` | 8 | `auto_hide_tab_bar`, `keep_alive_only`, `no_docking_over_central_node`, `no_docking_split` |
| `imgui.DragDropFlags_` | 13 | `accept_before_delivery`, `accept_no_draw_default_rect`, `accept_no_preview_tooltip`, `accept_peek_only` |
| `imgui.FocusedFlags_` | 7 | `any_window`, `child_windows`, `dock_hierarchy`, `no_popup_hierarchy` |
| `imgui.HoveredFlags_` | 21 | `allow_when_blocked_by_active_item`, `allow_when_blocked_by_popup`, `allow_when_disabled`, `allow_when_overlapped` |
| `imgui.INDEX_SIZE` | 4 | `denominator`, `imag`, `numerator`, `real` |
| `imgui.ImDrawFlags_` | 13 | `closed`, `none`, `round_corners_all`, `round_corners_bottom` |
| `imgui.ImDrawListFlags_` | 5 | `allow_vtx_offset`, `anti_aliased_fill`, `anti_aliased_lines`, `anti_aliased_lines_use_tex` |
| `imgui.ImFontAtlasFlags_` | 4 | `no_baked_lines`, `no_mouse_cursors`, `no_power_of_two_height`, `none` |
| `imgui.ImFontFlags_` | 4 | `lock_baked_sizes`, `no_load_error`, `no_load_glyphs`, `none` |
| `imgui.ImTextureFormat` | 2 | `alpha8`, `rgba32` |
| `imgui.ImTextureStatus` | 5 | `destroyed`, `ok`, `want_create`, `want_destroy` |
| `imgui.InputFlags_` | 11 | `none`, `repeat`, `route_active`, `route_always` |
| `imgui.InputTextFlags_` | 26 | `allow_tab_input`, `always_overwrite`, `auto_select_all`, `callback_always` |
| `imgui.ItemFlags_` | 7 | `allow_duplicate_id`, `auto_close_popups`, `button_repeat`, `no_nav` |
| `imgui.Key` | 153 | `a`, `apostrophe`, `app_back`, `app_forward` |
| `imgui.ListClipperFlags_` | 2 | `no_set_table_row_counters`, `none` |
| `imgui.MouseButton_` | 4 | `count`, `left`, `middle`, `right` |
| `imgui.MouseCursor_` | 13 | `arrow`, `count`, `hand`, `none` |
| `imgui.MouseSource` | 4 | `count`, `mouse`, `pen`, `touch_screen` |
| `imgui.MultiSelectFlags_` | 17 | `box_select1d`, `box_select2d`, `box_select_no_scroll`, `clear_on_click_void` |
| `imgui.PopupFlags_` | 10 | `any_popup`, `any_popup_id`, `any_popup_level`, `mouse_button_mask_` |
| `imgui.SelectableFlags_` | 8 | `allow_double_click`, `allow_overlap`, `disabled`, `highlight` |
| `imgui.SelectionRequestType` | 3 | `none`, `set_all`, `set_range` |
| `imgui.SliderFlags_` | 10 | `always_clamp`, `clamp_on_input`, `clamp_zero_range`, `invalid_mask_` |
| `imgui.SortDirection` | 3 | `ascending`, `descending`, `none` |
| `imgui.SortDirection_` | 3 | `ascending`, `descending`, `none` |
| `imgui.StyleVar_` | 42 | `alpha`, `button_text_align`, `cell_padding`, `child_border_size` |
| `imgui.TabBarFlags_` | 12 | `auto_select_new_tabs`, `draw_selected_overline`, `fitting_policy_mask_`, `fitting_policy_mixed` |
| `imgui.TabItemFlags_` | 10 | `leading`, `no_assumed_closure`, `no_close_with_middle_mouse_button`, `no_push_id` |
| `imgui.TableBgTarget_` | 4 | `cell_bg`, `none`, `row_bg0`, `row_bg1` |
| `imgui.TableColumnFlags_` | 28 | `angled_header`, `default_hide`, `default_sort`, `disabled` |
| `imgui.TableFlags_` | 37 | `borders`, `borders_h`, `borders_inner`, `borders_inner_h` |
| `imgui.TableRowFlags_` | 2 | `headers`, `none` |
| `imgui.TreeNodeFlags_` | 22 | `allow_overlap`, `bullet`, `collapsing_header`, `default_open` |
| `imgui.VERTEX_BUFFER_COL_OFFSET` | 4 | `denominator`, `imag`, `numerator`, `real` |
| `imgui.VERTEX_BUFFER_POS_OFFSET` | 4 | `denominator`, `imag`, `numerator`, `real` |
| `imgui.VERTEX_BUFFER_UV_OFFSET` | 4 | `denominator`, `imag`, `numerator`, `real` |
| `imgui.VERTEX_SIZE` | 4 | `denominator`, `imag`, `numerator`, `real` |
| `imgui.ViewportFlags_` | 15 | `can_host_other_windows`, `is_focused`, `is_minimized`, `is_platform_monitor` |
| `imgui.WindowFlags_` | 30 | `always_auto_resize`, `always_horizontal_scrollbar`, `always_vertical_scrollbar`, `child_menu` |

### C. 结构与对象

| 类型 | 成员数 |
|---|---|
| `imgui.FLT_MAX` | 8 |
| `imgui.FLT_MIN` | 8 |
| `imgui.IO` | 126 |
| `imgui.ImColor` | 5 |
| `imgui.ImDrawCmd` | 9 |
| `imgui.ImDrawCmdHeader` | 3 |
| `imgui.ImDrawData` | 14 |
| `imgui.ImDrawList` | 59 |
| `imgui.ImDrawListSplitter` | 5 |
| `imgui.ImDrawVert` | 3 |
| `imgui.ImFont` | 21 |
| `imgui.ImFontAtlas` | 40 |
| `imgui.ImFontAtlasRect` | 6 |
| `imgui.ImFontBaked` | 18 |
| `imgui.ImFontConfig` | 21 |
| `imgui.ImFontGlyph` | 13 |
| `imgui.ImFontGlyphRangesBuilder` | 7 |
| `imgui.ImTextureData` | 25 |
| `imgui.ImTextureRect` | 4 |
| `imgui.ImTextureRef` | 1 |
| `imgui.ImVec2` | 4 |
| `imgui.ImVec4` | 6 |
| `imgui.ImVector_ColorMod` | 8 |
| `imgui.ImVector_FocusScopeData` | 8 |
| `imgui.ImVector_GroupData` | 8 |
| `imgui.ImVector_ImDrawChannel` | 8 |
| `imgui.ImVector_ImDrawCmd` | 8 |
| `imgui.ImVector_ImDrawList_ptr` | 8 |
| `imgui.ImVector_ImDrawVert` | 8 |
| `imgui.ImVector_ImFontConfig` | 8 |
| `imgui.ImVector_ImFontConfig_ptr` | 8 |
| `imgui.ImVector_ImFontGlyph` | 8 |
| `imgui.ImVector_ImFont_ptr` | 8 |
| `imgui.ImVector_ImRect` | 8 |
| `imgui.ImVector_ImTextureData_ptr` | 8 |
| `imgui.ImVector_ImTextureRect` | 8 |
| `imgui.ImVector_ImTextureRef` | 8 |
| `imgui.ImVector_ImVec2` | 8 |
| `imgui.ImVector_ImVec4` | 8 |
| `imgui.ImVector_InputEvent` | 8 |
| `imgui.ImVector_KeyRoutingData` | 8 |
| `imgui.ImVector_ListClipperData` | 8 |
| `imgui.ImVector_ListClipperRange` | 8 |
| `imgui.ImVector_MultiSelectTempData` | 8 |
| `imgui.ImVector_OldColumnData` | 8 |
| `imgui.ImVector_OldColumns` | 8 |
| `imgui.ImVector_PlatformMonitor` | 8 |
| `imgui.ImVector_PopupData` | 8 |
| `imgui.ImVector_PtrOrIndex` | 8 |
| `imgui.ImVector_SelectionRequest` | 8 |
| `imgui.ImVector_SettingsHandler` | 8 |
| `imgui.ImVector_ShrinkWidthItem` | 8 |
| `imgui.ImVector_StackLevelInfo` | 8 |
| `imgui.ImVector_StyleMod` | 8 |
| `imgui.ImVector_TabItem` | 8 |
| `imgui.ImVector_TableColumnSortSpecs` | 8 |
| `imgui.ImVector_TableHeaderData` | 8 |
| `imgui.ImVector_TableInstanceData` | 8 |
| `imgui.ImVector_TableTempData` | 8 |
| `imgui.ImVector_TreeNodeStackData` | 8 |
| `imgui.ImVector_ViewportP_ptr` | 8 |
| `imgui.ImVector_Viewport_ptr` | 8 |
| `imgui.ImVector_WindowStackData` | 8 |
| `imgui.ImVector_Window_ptr` | 8 |
| `imgui.ImVector_char` | 8 |
| `imgui.ImVector_float` | 8 |
| `imgui.ImVector_int` | 8 |
| `imgui.ImVector_uchar` | 8 |
| `imgui.ImVector_uint` | 8 |
| `imgui.InputTextCallbackData` | 18 |
| `imgui.KeyData` | 4 |
| `imgui.ListClipper` | 15 |
| `imgui.MultiSelectIO` | 6 |
| `imgui.OnceUponAFrame` | 1 |
| `imgui.Payload` | 11 |
| `imgui.Payload_PyId` | 2 |
| `imgui.PlatformIO` | 13 |
| `imgui.PlatformImeData` | 5 |
| `imgui.PlatformMonitor` | 6 |
| `imgui.SelectionBasicStorage` | 9 |
| `imgui.SelectionExternalStorage` | 2 |
| `imgui.SelectionRequest` | 5 |
| `imgui.SizeCallbackData` | 4 |
| `imgui.Storage` | 14 |
| `imgui.StoragePair` | 1 |
| `imgui.Style` | 70 |
| `imgui.TableColumnSortSpecs` | 6 |
| `imgui.TableSortSpecs` | 4 |
| `imgui.TextBuffer` | 11 |
| `imgui.TextFilter` | 7 |
| `imgui.Viewport` | 20 |
| `imgui.WindowClass` | 9 |
| `imgui.backends` | 30 |
| `imgui.internal` | 664 |
| `imgui.test_engine` | 79 |

---

## 18. 维护：生成器与守卫

| 事 | 怎么做 |
|---|---|
| 重新生成 | `python Utils/Dev/imgui_docgen.py`（写到工具仓 `docs_content/dev/imgui_api.md`，路径由已安装的 `engine_editor_mcp` 包定位） |
| 只校验 | `python Utils/Dev/imgui_docgen.py --check`（与磁盘比对，不写文件） |
| 看覆盖率 | `python Utils/Dev/imgui_docgen.py --stats`（分类数 / 未归类 / 引擎未使用） |
| 升级 imgui_bundle 后 | 重新生成 → 看 diff：新函数落进「附录」，确认值得收编就加进上面的分组表 |
| CI 守卫 | `Test/Application/Editor/test_imgui_api_doc.py` |

守的是三件事：

1. **产物新鲜** —— 磁盘内容 == 现渲染内容（依赖版本变了会红）。
2. **分组名真实** —— 分组表里写的函数必须在当前 `imgui_bundle` 里存在（拼错/被删会红）。
3. **引擎用到的都被归类** —— 仓库里任何地方调过 `imgui.<name>`，而 `<name>` 不在分组表里 → 报未归类。
   加新控件用法的人会被这条提醒「去补一行文档」，而不是默默多出一个没人知道的接口。

<!-- generated by Utils/Dev/imgui_docgen.py | imgui_bundle 1.92.5 | python 3.14.6 -->

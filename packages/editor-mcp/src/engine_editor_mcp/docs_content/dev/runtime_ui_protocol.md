# 运行时 UI 协议（场景驱动 UI）

> 域：`Application/Core/UI/**`（core 侧纯数据/数学）· `Application/Core/Scene/UIComponents.py`（组件）
> · `Application/Runtime/RuntimeUILayer.py`（运行时层）· `Application/Core/Renderer/OpenGL/OpenGLUI.py`（绘制）
> · `Application/Core/NodeGraph/{node_types,evaluators}/ui.py`（UI 节点）· `Examples/UIShowcase/**`（长期测试工程）。
> 设计讨论与决策记录：`Doc/Dev/product_todo.md` §10。

## 1. 域地图

| 文件 | 职责 | 线程 |
|---|---|---|
| `Core/UI/layout.py` | `UIQuad` 绘制指令；`content_box`（参考分辨率→视口）；`resolve_rect`（9 宫格锚点/枢轴）；`rect_hit`；字体探测（CJK 用系统字体） | 纯函数 |
| `Core/UI/theme.py` | 主题 token 默认值（颜色/字号/间距）+ `parse_color`（token / `#hex` / tuple）+ 按钮变体色 | 纯函数 |
| `Core/UI/tree.py` | `UIElement` → `UIBuildResult`（quads + 命中矩形 + modal 标记）；`captures` | 渲染线程（只读快照） |
| `Core/UI/controls.py` | 控件绘制与数值数学（开关/滑条/三皮肤选择） | 纯函数 |
| `Core/UI/scene.py` | esper 场景 → `UIElement` 快照；`find_by_role` / `find_by_name` | **逻辑线程** |
| `Core/Scene/UIComponents.py` | 组件 + 数据契约注册 + 受控枚举值 | — |
| `Core/Renderer/OpenGL/OpenGLUI.py` | UI pass（关深度/开 alpha/关切面；按 key 缓存文字纹理） | 渲染线程 |
| `Runtime/RuntimeUILayer.py` | 场景 UI + 内置退出确认；ESC 策略；动作派发；overlay 捕获判定 | 见 §7 |
| `Editor/EditorLayer.py` | 编辑期预览（`OnUpdate` 取快照 → `OnRender` 编译） | 见 §7 |

**铁律**：UI 组件**不绑 `MeshRenderer`**（世界空间网格语义 vs 屏幕空间矩形语义，焊一起会互相污染）；
UI 渲染走独立 pass，永远画在场景与 overlay 之上。

## 2. 组件字段表

所有组件都是 `DataclassContract`（`.scene` 直接读写，无需额外工厂）。

### `UICanvas`（画布根）

| 字段 | 默认 | 说明 |
|---|---|---|
| `scale_mode` | `fit_height` | `fit_height` / `fit_width` / `contain`（宽高都贴合）/ `stretch` |
| `reference_w` / `reference_h` | 1920 / 1080 | 所有 `UIRect` 数值所在的参考空间 |
| `sort_order` | 0 | 多画布绘制顺序（小的先画） |
| `visible` | true | 整块画布显隐 |

### `UIRect`（布局）

| 字段 | 默认 | 说明 |
|---|---|---|
| `anchor` | `center` | 相对**父矩形**的 9 宫格锚点（无父 → 画布内容框） |
| `pivot` | 同 `anchor` | 矩形自身对齐点 |
| `pos_x` / `pos_y` | 0 | 锚点处偏移（参考分辨率像素） |
| `width` / `height` | 320 / 120 | 参考分辨率像素；**0 = 撑满父级该轴** |
| `visible` | true | 自身可见性（父不可见 → 子树不画不命中） |
| `order` | 0 | 同层绘制顺序（小的先画） |

### `UIPanel`

| 字段 | 默认 | 说明 |
|---|---|---|
| `bg_color` | `@color.surface` | token / `#hex` / RGBA；alpha=0 → 不画底 |
| `border_color` | `@color.border` | 描边色 |
| `border_width` | 1 | 0 = 无描边（M0 直角，无圆角） |
| `scrim_color` | `""` | 非空 → 整屏遮罩（对话框用 `@color.scrim`） |
| `modal` | false | 吃掉全部键鼠（节点图收不到）；点击面板外不穿透给下层 UI |
| `role` | `""` | 语义标记；`exit_confirm` = ESC 退出确认面板 |

### `UILabel`

| 字段 | 默认 | 说明 |
|---|---|---|
| `text` | `Label` | 字面量（多行用 `\n`；自动折行未实现） |
| `size` | 0 | 0 = 主题 `@font.size.body`；>0 = 参考分辨率像素 |
| `color` | `@color.text` | token / `#hex` / RGBA |
| `align` | `center` | `left` / `center` / `right`（垂直恒居中） |
| `bold` | false | 合成加粗 |

### `UIButton`（唯一产生点击的元素）

| 字段 | 默认 | 说明 |
|---|---|---|
| `text` | `Button` | 按钮文字画在按钮内（不要再挂 `UILabel` 子实体） |
| `variant` | `secondary` | `primary` / `secondary` / `danger` / `ghost`（语义色，颜色由主题决定） |
| `action` | `""` | 见 §5；空 = 仅视觉（不消费点击） |
| `enabled` | true | false → 禁用底色 + 不可点 |
| `size` | 0 | 0 = 主题 `@font.size.button` |

### 控件三件套（设置页）

| 组件 | 字段 | 交互 |
|---|---|---|
| `UIToggle` | `label` / `value` / `action` | 点击任意处翻转（轨道 + 方块旋钮；开=主色） |
| `UISlider` | `label` / `min_value` / `max_value` / `step` / `value` / `show_value` / `action` | 按下即跳、拖拽跟手、松开提交；`step>0` 启动吸附 |
| `UISelect` | `label` / `options` / `index` / `skin` / `action` | `segmented` 分段直选 / `stepper` `− 值 +` / `dropdown` 展开列表（靠近底边向上翻） |

共同约定：

- `label` 非空 → 左侧 38% 宽度画说明（`Core/UI/controls.row_areas`），右侧剩余是控件本体；
- 控件值是**运行期状态**（`RuntimeUILayer._values[eid]`），**不写回 `.scene`**（PIE 停止即丢弃，
  不会污染正在编辑的场景）；节点用 `GetUIValue` 读取；
- 每次交互（翻转 / 拖动结束 / 选中）都发一条 **UI 事件**，节点 `OnUIClick` 可接（见 §5.1）；
- 控件也接受 `action`（与 `UIButton` 同语法：`exit` / `close` / `show:` / `hide:` / `toggle:`）。

## 3. 布局规则

1. 画布 `scale_mode` 决定内容框与缩放（`content_box`）：`fit_height` 高度贴合（超宽屏两侧留边）、
   `contain` 取宽高较小比例（窄视口不裁切，示例工程用这个）、`stretch` 会变形。
2. 元素的父矩形 = **最近的带 `UIRect` 的祖先**的屏幕矩形；没有 → 画布内容框。
3. 子元素锚点是相对父矩形算的，因此 `anchor=top_left, pivot=top_left, pos=(20,20)` 就是"父内左上角内缩 20"。
4. `width/height = 0` 表示撑满父级该轴（被换算回参考单位后再缩放）。
5. UI 布局**不看 `Transform`**（`Transform` 只是为了让编辑器 Outliner / 其它系统能枚举到实体）。

## 4. 绘制顺序与命中

- 排序键：`(UICanvas.sort_order, 深度, UIRect.order, entity_id)`；父先于子。
- 命中取**反向绘制顺序的第一个可交互元素**（最上层优先）。
- 只有**可交互元素**产生命中矩形（`kind`：`button` / `toggle` / `slider` / `select` / `step` / `dropdown`）；
  面板/文字不抢点击 → overlay 模式下“没画按钮的地方”仍可穿透。
- `dropdown` 的展开列表画在所有元素之后（命中排最后 = 最上层），选中/点空白都会关闭。
- `modal` 面板可见时：`UIBuildResult.modal = True`，`captures()` 对整屏返回真；
  `hit_at()` 只认模态子树里的可点元素（面板外点击被吃掉但无动作）。

## 5. 按钮动作

| action | 行为 |
|---|---|
| `""` | 仅视觉：不消费点击、不产生动作 |
| `exit` / `quit` | 关闭全部 UI → `RuntimeNodeLayer.request_stop()`（与 `ExitGame` 节点同一条链；PIE → `SimulationController.stop`，成品 → `GameRuntime.run_state=False`） |
| `close` | 隐藏**所属面板**（最近一层带 `UIPanel` 的祖先；面板自身也可用） |
| `show:<实体名>` | 显示该实体（运行期覆盖，不改场景数据） |
| `hide:<实体名>` | 隐藏该实体 |
| `toggle:<实体名>` | 反转该实体可见性 |

显隐一律走 `RuntimeUILayer._overrides`（`eid → bool`），**不写回 `.scene`**；PIE 停止即丢弃。

### 5.1 UI 事件 → 节点图

每次交互（按钮、开关、滑条释放、选择）产生一条事件（`SimpleNamespace`，`kind="ui_event"`）：
`eid / name / action / control / value / index`。事件先入 `RuntimeUILayer._events`（有界 128），
再由 `RuntimeNodeLayer._dispatch_input_events` 在**逻辑线程**取走，逐条触发 `OnUIClick`：

| 节点 | 引脚 | 属性 | 语义 |
|---|---|---|---|
| `SetUIVisible` | `exec_in, Entity(entity_ref, 可选), Visible(bool, 可选), exec_out` | `target`（实体名）、`visible` | 写运行期显隐覆盖；`Entity` 连线优先，否则按名字找 |
| `SetUIText` | `exec_in, Entity(entity_ref, 可选), Text(string, 可选), exec_out` | `target`（实体名）、`text` | 写运行期文本覆盖；`Text` 连线优先，否则用 `props.text`；空串 = 清除覆盖，回落 `UILabel.text` |
| `OnUIClick` | `exec` / `Action, Name, Value, Index`（Event 类入口） | `action` / `name` 过滤（空 = 不过滤） | 每次交互触发一次（释放时），不是每帧 |
| `GetUIValue` | `Entity(entity_ref, 可选)` → `Value(float), Index(int)` | `target` | 读开关(0/1) / 滑条数值 / 选择下标 |

注意：`OnUIClick` 必须归入 **Event 分类**（`GraphEvaluator.trigger` 只遍历 `category=="Event"` 的节点）；
事件记录用对象（`.kind`）而不是 dict —— 与 `RuntimeInputFrame` 保持一致。

## 6. ESC 策略与内置兜底

1. 场景里有 `UIPanel(role="exit_confirm")` → ESC 打开/关闭**该面板**（推荐做法，控件可自由摆放）。
2. 场景没有该面板 → 退回**内置对话框**（`RuntimeUILayer._builtin_elements()` 生成同一套 `UIElement`，
   走同一个编译器；文案由宿主 i18n 注入 `pie.exit.*`）。
3. 关闭 Runtime 窗口（标题栏 X）同样走这条确认链（`EditorLayer` 拦截 `window_should_close`）。
4. `RuntimeUILayer.set_enabled(False)` → ESC 不再消费，退回引擎"关窗口"安全网。

## 7. 线程模型

| 阶段 | 线程 | 做什么 | 不做什么 |
|---|---|---|---|
| `OnUpdate` | 逻辑线程 | `collect_elements(engine.scene)` → 不可变 `UIElement` 元组；刷新 `_exit_panel_eid` | 不编译 quad |
| `OnRender` | 渲染线程 | `build_ui(...)` → `renderer.set_ui_quads(...)`；写 `_scene_result` | **不读 ECS** |
| `OnEvent` | 窗口事件线程 | hover/press/拖拽状态、ESC 策略、控件值、动作派发、事件入队、模态消费 | 不碰 ECS 组件 |

理由：free-threading 无 GIL，渲染线程读 esper 会与逻辑线程的 EntitySpawn/Delete 竞态。
`_scene_result` 是整体替换的不可变对象，事件线程读到的是"上一帧快照"，足够用。

## 8. Overlay 穿透联动

`glfwWindow._is_click_through_target` 在 overlay 模式下每帧判定是否加 `WS_EX_TRANSPARENT`：

1. `RuntimeUILayer.is_open()`（模态）→ 整窗捕获；
2. 否则 `RuntimeWindow._cursor_over_ui(ndc)`：NDC → framebuffer 像素 → `RuntimeUILayer.captures_at(px,py)`
   （按钮上 / 模态内 → 捕获；空白 → 继续走 GPU pick 判定）。

注意：UI quad 用 **framebuffer 像素**，NDC 换算必须用 `glfw.get_framebuffer_size`（高 DPI 下 ≠ window size）。

## 9. 编辑器预览

`EditorLayer.OnUpdate` 取快照、`EditorLayer.OnRender` 编译到编辑器渲染器的 UI pass —— 编辑场景即可看到 UI，
不必先 PIE。预览**不可交互**、不参与 pick（点 UI 仍会选中 3D 物体）。

已知偏差：编辑器没有单独的视口 FBO，`renderer.viewport_width/height` 是**窗口尺寸**，
因此预览按整窗布局（右侧被停靠面板遮住的部分只是被挡住，不是没画）。

## 10. 测试与验收

| 层级 | 用例 | 覆盖 |
|---|---|---|
| core | `Test/Application/Core/test_ui_tree.py`（44 checks） | 布局/可见性/面板/按钮状态/模态命中/对齐/顺序/收集器/颜色解析 |
| core | `Test/Application/Core/test_ui_controls.py`（55 checks） | 控件绘制/数值数学/图层交互/值读取/显隐与文本入口/UI 节点求值/「点击→OnUIClick→SetUIVisible→SetUIText」全链 |
| core | `Test/Application/Core/test_ui_showcase.py`（55 checks） | 示例工程结构、控件齐全（含三皮肤）、token 可解析、编译与缩放、对话框、节点图 |
| core | `Test/Application/Core/test_runtime_ui.py`（23 checks） | 内置对话框状态机、ESC、Yes/No、模态吞键 |
| live | 手工/CLI 验收 | `project.open Examples/UIShowcase` → `sim.play` → 截图（HUD）→ ESC（对话框）→ 点 Stay（Running）→ ESC → 点 Exit（Stopped） |

**新增控件必须同步 `Examples/UIShowcase`**（它是 UI 的验收清单）与 `test_ui_showcase.py`。

## 11. 未实现（后续里程碑）

- 控件：`UIProgress`、`UIScrollView`（裁剪栈 + 滚动）—— 按用户要求**暂缓**，先补实验链路
- 主题文件：`ui_theme.json` 加载（当前 token 在代码里）、多主题目录、热重载 —— 同上**暂缓**
- 文本：字体图集（现在每条文字一张纹理）、自动折行、图标/九宫格、圆角
- 交互：焦点链与键盘导航、hover 音效/动画、拖拽、文本输入与 IME
- 场景文本不参与 i18n（字面量）；世界空间 UI（血条挂在 3D 物体上）另立项

## 12. 已知限制

- 场景里的文字是**数据**（字面量），切换编辑器语言不会翻译它；内置退出确认才走 `pie.exit.*`。
- 编辑器预览按窗口尺寸布局（见 §9），且 UI 不参与编辑器 pick。
- 命中判定用矩形，不做裁剪（元素超出父面板仍可点 → 等 `UIScrollView` 的裁剪栈一起做）。

## 13. 交叉引用

- 设计讨论与决策（D1–D10、暂停/模态、风格交付三层）：`Doc/Dev/product_todo.md` §10
- 渲染 pass / 像素验证：`Doc/Dev/rendering_protocol.md`
- 文字光栅化（`TextSystem`）：`Doc/Dev/text_protocol.md`
- 场景文件格式：`Doc/Dev/scene_format.md`
- 编辑器 UI（ImGui，**与本协议是两套东西**）：`Doc/Dev/ui_protocol.md`

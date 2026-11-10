# shader_protocol.md — 着色器设计规范协议

> 改 `Resource/Shaders/**`、渲染器 uniform 注入（`OpenGLEntities._inject_lighting`）、
> 材质 uniform 系统（`Application/Resource/Material.py`）前必读。
> 配套：`rendering_protocol.md`（渲染体系 / 验证体系 / RT）· `media_protocol.md`（动态纹理）。
> 本协议由「P1 渲染能力」章建立（2026-10-06）；全部规则经 **core 测试 + GL 像素测试** 锁定，
> 关键数值见 §7.3 / §10。

---

## 1. 定位与三层职责

shader 已从「Basic + SSVEP 两个平面着色器」演进到 Lighting（法线 / 光照 / 多 uniform）
体系 —— 必须显式契约化，避免"改一个 shader 崩一场景"。

| 层 | 职责 | 代码域 |
|---|---|---|
| **shader（GLSL）** | 消费属性与 uniform；输出颜色/alpha | `Resource/Shaders/**` |
| **材质系统** | 逐实体 uniform 数据（`uniforms_data`）、按类型自动默认值、`.mat` 序列化 | `Application/Resource/Material.py` + `ResourceManager` |
| **渲染器** | 每帧注入帧级状态（矩阵 / 相机 / 光照）；属性布局一致性校验 | `Application/Core/Renderer/OpenGL/**` |

**核心规则：shader 里声明的每个 uniform 必须能回答"谁写入、什么频率"。**三类归属见 §5。

---

## 2. 文件布局与加载

### 2.1 布局

```
Resource/Shaders/Builtin/
  Basic.vert / Basic.frag          # 内置：id 与文件名顺序绑定
  SSVEP.vert / SSVEP.frag
  Lighting.vert / Lighting.frag
  Name.vert.spv / Name.frag.spv    # 可选（Vulkan 实验路径）
```

### 2.2 注册与解析链

1. **注册**：`ResourceManager.DEFAULT_SHADER_NAME` / `DEFAULT_SHADER_FILE`（zip 顺序 → `shader_id` 1..N）。
   新增内置 shader = 两个列表各加一项；**顺序即 id，插队会移位所有后续 id**。
2. **解析**：`Resource/_resource_utils.py: parse_shader_files()` — 正则提取 `uniform <type> <name>`
   （含数组/初始化式）→ `uniforms_name_type`（名 → GLSL 类型），**同时**读取声明旁的 `//!` 注解
   → `uniform_specs`（名 → `UniformSpec`，见 §6.1）。返回值是 6 元组，最后一项是 spec 表。
3. **保留 uniform 黑名单**（`_RESERVED_UNIFORMS`，同文件）：
   `uAmbient / uCameraPos / uLightCount / uLightPos / uLightDir / uLightColor /`
   `uPointCount / uPointPos / uPointColor / uPointRange`
   —— 由渲染管线**每帧统一注入**，解析时**直接剔除**，不进材质、UI 不可见、逐实体上传时跳过
   （`OpenGLEntities._MATERIAL_SKIP_UNIFORMS`）。新增帧级注入项时必须两处同步。
4. **归属来源**：除黑名单外，`//! owner=engine|runtime` 也能把 uniform 排除出材质
   （`time` 即走这条 —— 不进 `.mat`、GUI 只读、逐实体上传时二次跳过）。

### 2.3 材质系统支持的 uniform 类型

**默认值不再按类型硬编码** —— 以 shader 的 `//! default=` 为准（§6.1），没写注解时才回落下表
（= 2026-11 之前的行为，老 shader 一行不改也能跑）：

| GLSL 类型 | 无注解时的默认值 | UI 控件（无注解） |
|---|---|---|
| `mat4` | 全 0 | 只读文本 |
| `vec4` | (1,1,1,1) | drag_float4 |
| `vec3` | (1,1,1) | drag_float3 |
| `float` / `double` | 0 | drag_float |
| `int` | 0 | drag_int（注解 `ui: enum` 才是下拉） |
| `sampler2D` / 数组 | **不进材质**（采样器由 `texture_id_list` 管、数组只读展示） | — |

> 想让某个参数有正确的控件/范围/默认值，**写注解**（§6.1），不要扩充本表。

---

## 3. 顶点属性契约（STD_LAYOUT）

网格 VBO 交错布局由 `VertexLayout.STD_LAYOUT` 定义（唯一真理源）。常规实体的布局：

```
ENTITY_POS_UV_NORMAL  (stride 32B):  loc0 → vec3 aPos (12B)
                                     loc1 → vec2 aTexCoord (8B)
                                     loc2 → vec3 aNormal (12B)
```

规则（`check_shader_consistency` 在 `register_entity` 时逐 shader 告警）：

1. **shader 声明的 `in` 必须 ⊆ 所用 layout 的属性集**，位置编号必须与 layout 对齐
   （mesh 写 loc2，shader 就必须 `layout(location=2) in vec3 ...`）。
2. 布局有、shader 没声明 → 启动 `UserWarning: 数据被浪费`（Basic/SSVEP 当前各有 1 条 —
   快照锁定在 `test_vertex_layout.py`，新增 shader 会新增快照行，必须同步该表）。
3. 布局没有、shader 用了 → `使用但未定义` 告警（比浪费严重，通常 bug）。
4. 网格法线：`Square.obj` 正面为 `(0,1,0)`；`Cube` 各面外法线。三角形网格不保证。

---

## 4. 矩阵与坐标约定（实测锁定）

- 上传：numpy C 连续 + `GL_FALSE`（见 `OpenGLUtils.set_uniform_mat4`）→ **GLSL 中的
  `model/view/projection` 与引擎 row-vector 矩阵等价**：`(M * vec4) == 引擎世界坐标`。
- `view` / `projection`：每 program 每帧写一次（program 切换时）；`model`：逐实体。
- 法线：`mat3(model) * aNormal` 在**旋转 + 均匀缩放**下正确；非均匀缩放需
  inverse-transpose（现状不支持，记录为已知限制 — §9）。
- `uCameraPos` = 相机世界坐标（row-vector 视图矩阵求逆的平移行，`OpenGLEntities._collect_light_frame`）。

---

## 5. uniform 契约总表

| 类别 | 名称（固定） | 类型 | 写入方 | 频率 |
|---|---|---|---|---|
| 矩阵 | `model` / `view` / `projection` | mat4 | 渲染器 | 逐实体 / 每 program 每帧 |
| 采样 | `uTexture`（binding=0） | sampler2D | 渲染器（texture unit 0） | 逐实体 |
| 材质通用 | `uColor` 等 | vec4… | 材质 `uniforms_data` | 逐实体 |
| 材质光照（Lighting 专用） | `uShininess` · `uSpecularStrength` · `uDiffuseStrength` · `uAmbientStrength` (float) · `uSpecularModel` (int) | — | 材质 | 逐实体 |
| 材质自定义 | 任意（如 `uShininess`） | 见 §2.3 | 材质 | 逐实体 |
| **运行期注入** | 声明 `//! owner=runtime` 者（当前：SSVEP `time`） | float | `OpenGLEntities._inject_runtime`（值 = 引擎 elapsed 秒） | 每 program 每帧**一次** |
| **渲染器注入** | `uAmbient` (vec3) · `uCameraPos` (vec3) · `uLightCount` (int) · **`uLightPos[4]` (vec3)** · `uLightDir[4]` (vec3) · `uLightColor[4]` (vec3) · `uPointCount` (int) · `uPointPos[4]` (vec3) · `uPointColor[4]` (vec3) · `uPointRange[4]` (float) | — | `OpenGLEntities._inject_lighting` | 每 program 每帧**一次** |

规则：

1. 未声明某类 uniform 的 shader：注入调用全部 no-op（`glGetUniformLocation` 返回 -1），
   **Basic/SSVEP 不受光照体系影响**（SSVEP 刺激色精确性依赖此点）。
2. `uLightColor` = 颜色 × 强度（已合并）；`uLightDir` = 光线**传播**方向（世界空间单位向量）；
   `uLightPos` = 面光源**世界位置**（参与发光面半空间判定，见 §7.2）；
   点光组：`uPointPos` = 世界位置、`uPointColor` = 颜色 × 强度、`uPointRange` = 衰减半径。
3. 逐实体材质上传跳过黑名单（§2.2），材质若**历史遗留**同名键也不会覆盖注入值（双保险）。
   `owner=runtime` 的名字在这条链上有第二道拦截（材质里就算有 `time` 也不会覆盖帧值）。
4. 新增帧级注入：黑名单两处 + `_inject_lighting` + 本表 + GL 测试各一处，共五处同步。
5. **`time` 的语义**：全帧一致、单调递增的运行秒数（`engine.get_elapsed_time()`），
   每帧取一次写进所有声明 `owner=runtime` 的 uniform。SSVEP 的相位因此为
   `sin(2π·freq·time + phase)` —— `time` 不写 = 恒黑（2026-11 之前就是这个状态）。

---

## 6. 材质默认值系统与「切 shader 重置」语义

### 6.1 `//!` 注解 —— 参数的唯一描述来源

**动机**：同一份「这个 uniform 是什么」以前写在 4 个地方 —— GLSL 声明（类型）、`Material`
（按类型填白/0）、`ScenePanel`（`if shader_name == 'Basic'` 才给色盘）、`LiveCommandServer`
（按参数名手写 key）。结果每加一个参数要改四处，漏一处就静默不生效，agent 侧表现为"工具缺口"。

现在只有一处：**声明上一行（或同行 `;` 之后）的 `//!` 注释**。GUI 形态、范围、默认值、校验、
文档全部由它派生（`Application/Resource/UniformSpec.py`）。

语法（`//!` 前缀，机读；普通 `//` 注释保持自由，不影响语义）：

```
//! ui:<kind> | label=<i18n 键> | group=<分组> | range=<min>..<max> | step=<n>
//!   | default=<v[,v...]> | unit=<Hz|rad|deg> | choices=<v>:<标签键>[, ...]
//!   | owner=<content|engine|runtime> | readonly | doc=<一行说明>
```

| 字段 | 说明 |
|---|---|
| `ui:<kind>` | 控件形态：`float` `int` `bool` `color3` `color4` `vec2/3/4` `enum` `readonly` `array`。省略则按 GLSL 类型推断（`vec4` 仍是四条滑杆，**不会**自动变颜色） |
| `label` | i18n 键，回退 = uniform 名 |
| `group` | 面板分组（同组折叠），键 = `mat.group.<group 小写>` |
| `range` | 滑杆上下限，同时是**写入校验**边界 |
| `step` | 拖动步长 |
| `default` | **真正的默认值**（`.mat` 新建 / 复位用）。GLSL 的 `= 0.0` 只是语言要求，不再当哨兵 |
| `unit` / `doc` | 显示单位（`Hz`/`rad`/`deg`）、悬浮说明 |
| `choices` | `enum` 的取值与标签键 |
| `owner` | `content`（默认，进材质）/ `engine`（渲染器每帧注入）/ `runtime`（引擎运行期值，当前只有 `time`） |
| `readonly` | 强制只读（不进材质、GUI 灰显） |

内置 shader 现状（全部已注解）：

```glsl
// Basic.frag
//! ui: color4 | label=mat.color | group=Surface | default=1,1,1,1
uniform vec4 uColor = vec4(1.0);

// Lighting.frag —— 高光指数：真正的默认 32，范围 1..256
//! ui: float | label=mat.shininess | group=Specular | range=1..256 | step=1 | default=32
uniform float uShininess = 0.0;     // 0 = 旧材质的"用默认"哨兵（shader 里回落 32）

//! ui: enum | label=mat.specular_model | group=Specular | choices=0:mat.phong,1:mat.blinn | default=0
uniform int uSpecularModel = 0;

// SSVEP.frag —— 刺激参数（实验侧真正要调的三个）
//! ui: float | label=mat.freq | group=Stimulus | range=1..60 | step=0.1 | unit=Hz | default=10
uniform float freq;
//! ui: float | label=mat.phase | group=Stimulus | range=0..6.283 | step=0.01 | unit=rad | default=0
uniform float phase_shift;
//! ui: readonly | owner=runtime | label=mat.time | group=Stimulus
uniform float time;
```

**降级规则**（保证老 shader 不改也能跑）：无注解 → kind 按 GLSL 类型推断、`editable=True`、
无范围、默认值回落 §2.3 表 —— 与 2026-11 之前逐字段一致。注解写错（无法解析的 token）
静默忽略，绝不让引擎崩。

### 6.2 默认值与「哨兵约定」

- 新建材质：`build_default_uniforms()`（`UniformSpec.py`，**唯一**实现）优先 `spec.default`，
  否则回落类型默认。`ResourceManager` 里旧的 `uShininess = 32.0` 硬编码已删除。
- 复位：`ResourceManager.ResetMaterialUniform(s)` 把值写回注解默认（面板的 \(\circlearrowleft\) 按钮
  走 `SceneBrowserController.reset_material_uniform(s)`，会先 `_ensure_unique_material` 克隆，
  不动共享/内置材质）。
- **哨兵约定仍在**（旧 `.mat` 文件里 `uShininess` 存的是 0）：

  ```glsl
  float shininess = (uShininess > 0.0) ? uShininess : 32.0;   // 0 = 用默认 32
  ```

  所以注解里 `range` 下限写成 `0.001`/`1` —— 让面板不可能再产出 0 这个哨兵值。
  新 shader 若用哨兵模式，必须在 §10 表登记含义。
  > 后续（S2）：`.mat` 改稀疏存（只存改过的键）+ 加载时把 0 归一到注解默认，哨兵约定即可退役。

### 6.3 切 shader 会重建参数表

`SetEntityShader` → `material.set_new_shader()` 按**新 shader** 的 `uniforms_name_type` +
`uniform_specs` 重建 `uniforms_data`，旧参数（含 uColor）全部丢失重置为默认。
编辑器/MCP 路径要「先切 shader，后设颜色/uniform」（GL 测试与 live 演示双次踩中，教训入此）。

### 6.4 序列化与引用唯一性

- `.mat` JSON：`name / shader_id / shader_ref / blend / texture_ids / texture_refs / uniforms`。
- **`shader_ref` 是持久化身份**：`builtin://Basic` 或绝对路径。`shader_id` 是会话级自增，
  跨会话必然错位 —— 旧文件没有 `shader_ref` 时按 `shader_id` 回退（兼容），有新文件优先按 ref。
  解析顺序见 `ResourceManager.ResolveShaderRef`：`builtin://名称` 精确 → 路径精确 →
  文件名唯一（多命中视为歧义，返回 0 不猜）。
- **`texture_refs` 同理**：与 `texture_ids` 平行，`builtin://名称` / 绝对路径；
  程序化/媒体帧纹理没有落点 → 空串（保留 id 回退，这类纹理本来就不可跨会话复用）。
  `LoadMaterialFromFile` 解析不到 ref 时才用保存的 id。
- 缺 `blend` 回退 `"opaque"`；缺 `shader_ref` / `texture_refs` 回退 id —— 旧文件兼容。
- 与 `MaterialRef` / `ResolveMaterialRef` 同一条纪律：**资源 id 不能当跨会话身份**。
  三条链（shader / texture / material）现在都走「稳定引用 → 会话内 id」的同一套解析顺序。

---

## 7. 光照约定（Lighting shader）

### 7.1 输入

| 通道 | 来源 | 语义 |
|---|---|---|
| `NormalWorld` (loc1 out) | VS: `mat3(model) * aNormal` | 世界/引擎空间法线 |
| `PosWorld` (loc2 out) | VS: `(model * vec4(aPos,1)).xyz` | 世界/引擎空间位置 |
| `uLightPos[i]` / `uLightDir[i]` / `uLightColor[i]` / `uLightCount` | 渲染器注入（§5） | 至多 4 盏**面光源**（位置 + 传播方向） |
| `uPointPos[i]` / `uPointColor[i]` / `uPointRange[i]` / `uPointCount` | 渲染器注入（§5） | 至多 4 盏**点光源** |
| `uAmbient` | 渲染器注入（场景 `SceneManager.ambient_color`） | 环境光 |
| `uShininess` / `uSpecularStrength` / `uDiffuseStrength` / `uAmbientStrength` / `uSpecularModel` | 材质 `uniforms_data`（§6 哨兵：0 = 默认） | 冯氏材质参数 |

### 7.2 光照模型（参考实现 = `Lighting.frag`）

经典冯氏反射（`uSpecularModel=0`，默认）：

$$
\text{accum} = uAmbient \cdot k_a
+ \sum_i uLightColor_i \cdot \big(k_d\max(N \cdot L_i, 0) + k_s\, s_i\big)
+ \sum_j att_j \cdot uPointColor_j \cdot \big(k_d\max(N \cdot L_j, 0) + k_s\, s_j\big)
$$

$$
s = \max(R \cdot V,\ 0)^{sh} \cdot \mathrm{step}(\varepsilon, N \cdot L),\quad R = \mathrm{reflect}(-L, N)
$$

- **面光源**：$L_i = -\mathrm{normalize}(uLightDir_i)$（指向光源）。
  只有当表面点在**发光面正面**时才受照：
  $\mathrm{dot}(PosWorld - uLightPos_i,\; d_i) \ge -\varepsilon$（$d_i$ = 传播方向，
  $\varepsilon = 10^{-4}$ 用于消除共面抖动）。**发光面背后（射线负方向）没有直射光** ——
  这是 2026-11-04 修掉的缺陷：以前只用方向、位置被忽略，光源摆在物体背后也像无穷远面光。
- **点光源**：$L_j = \mathrm{normalize}(uPointPos_j - PosWorld)$，
  $att_j = (\max(1 - |uPointPos_j - PosWorld| / uPointRange_j, 0))^2$（超距整项跳过）。
- $V = \mathrm{normalize}(uCameraPos - PosWorld)$；`uSpecularModel=1` 时改用 Blinn（$H = \mathrm{normalize}(L+V)$）。
- 材质参数（0 = 默认）：$k_a$ = `uAmbientStrength`(1.0) · $k_d$ = `uDiffuseStrength`(1.0) ·
  $k_s$ = `uSpecularStrength`(0.25) · $sh$ = `uShininess`(32)。
- 最终 `FragColor.rgb = albedo × accum`；`FragColor.a` 见 §8。

### 7.3 光源数据来源（`Light` 组件 — 面光源 / 点光源）

- 组件：`Light`（`Application/Core/Scene/BasicComponents.py`）—— `light_type`
  （`"area"` 面光源 / `"point"` 点光源；旧值 `"directional"` 仍兼容，按面光源处理）
  + `color_r/g/b` + `intensity` + `range`（仅点光）。
  旧名 `DirectionalLight` 已改名：模块保留 `DirectionalLight = Light` 别名（旧 import 兼容），
  场景 / 预置体 / MCP 加载链自动迁移（见 Editor 协议与 `SceneSync._COMP_NAME_MIGRATIONS`）。
- **面光源**（`light_type="area"`，上限 4）：世界位置 = Transform 平移（`model[3,:3]`，
  **参与半空间判定**）；传播方向 = 实体 Transform **局部 -Z** 的世界变换（`-model[2,:3]`，自动归一化）；
  方向决定光照方向，位置决定“哪些表面在发光侧”。
- **点光源**（`light_type="point"`，上限 4）：世界位置 = Transform 平移；距离衰减
  $att = (1 - d/range)^2$（$d \ge range$ ⇒ 整项跳过）；投影/锥向不做（无聚光）。
- 收集：`OpenGLEntities._collect_light_frame` 按世界查询顺序各取前 4；无阴影（roadmap P2）。
- 默认场景含一盏 `Sun`（**面光源**，`Resource/Prefabs/Builtin/DefaultLight.prefab`，
  位置 (0, 5, 0)、GL rotation ≈ (-1.0, 0.6, 0) rad —— 自上而下照亮默认立方体）。
- 场景环境光：`SceneManager.ambient_color`（默认 **0.5 = 50% 全局光**；`SetAmbientColor` / Scene.ambient_color
  随工程序列化与 PIE 同步）。
- **坐标系提醒**：编辑器 UI / MCP / Inspector 的 position/rotation 均为**编辑器空间**（Z-up；
  权威换算 `Application/Core/Math/CoordinateSystem.py`：editor (x, 前, 上) ↔ GL (x, z, -y)），
  引擎内部存储与渲染统一 GL。调光时以面板角度为准：仰角 = 编辑器 rot.x、方位角 = 编辑器 rot.z。
- **无灯回退**（`SceneManager.lighting_fallback`，默认开；`SetLightingFallback` / `Scene.lighting_fallback`
  随工程序列化与 PIE 同步）：场景**无任何光源**（面光源 + 点光源计数均为 0）时，本帧 ambient 强制为 (1,1,1) ——
  "未配置光照 ≠ 全黑"。单点实现：`OpenGLEntities._collect_light_frame`（`count == 0 and pcount == 0` 判定）。

### 7.4 数值锁定（`Test/Application/Renderer/test_gl_lighting.py`，手算参照）

夹具：俯视相机（V=(0,1,0)）、Square 法线 +Y、uColor 0.8、ambient (0.2, 0.1, 0.05)；
fallback 钉死 OFF（回退用例单独开关）；面光源均摆在**发光面正面** （世界 +Y 侧）；
点光用例光源在正上方（L=(0,1,0), ndl=1, spec=0.25）：

| 场景 | 期望像素 | 说明 |
|---|---|---|
| 无灯 | (41, 20, 10) | = 0.8 × ambient，逐通道 |
| 面光源垂直向下 (Rx=+90°, 光源在上方) | ≥250 全通道 | ndl=1 + 镜面 0.25 → 饱和 |
| 面光源斜射 60° | (218, 198, 187) ±10 | ndl=0.866 + 经典冯氏 spec≈0.0025 |
| 面光源**背面**（同方向、光源在表面下方） | (41, 20, 10) | 半空间判定：表面在射线负方向 ⇒ 无直射光 |
| 面光源侧向 (Rx=0) / 背向 (Rx=-90°) | (41, 20, 10) | ndl≤0，`step` 拍死高光（背面不漏光） |
| 面光源 白×0.5 + 红×0.5 双灯 | (255, 148, 138) ±8 | 逐通道叠加 + 饱和 |
| 材质 `uSpecularModel=1` | (234, 214, 204) ±10 | Blinn 变体（旧观感） |
| 材质 `uShininess=1` | (255, 241, 231) ±10 | 高光铺开 |
| 材质 `uDiffuseStrength=0.5` | (130, 110, 100) ±10 | 漫反射减半 |
| 点光 d=5, range=10（att=0.25） | (105, 84, 74) ±10 | 0.8×(ambient + 1.25×0.25) |
| 点光 d=7.5, range=10（att=0.0625） | (57, 36, 26) ±8 | 衰减中间档 |
| 点光 d=15 > range=10（att=0） | (41, 20, 10) | 超距截断 → 仅环境光 |
| 无灯 + fallback=ON | (204, 204, 204) | ambient 强制 1.0 → 0.8×1.0 |

---

## 8. shader alpha 与混合（`Material.blend`）

- 混合是**材质属性**（`opaque/alpha`），不写进 shader；渲染器负责 GL 状态与排序（painter）。
- shader 的唯一责任：**输出正确的 `FragColor.a`** —— Basic 用 `uColor.a`；Lighting 用
  `texel.a * uColor.a`。不透明 shader 也建议输出有意义 alpha（防御未来切 blend）。
- alpha 通道的 GL 混合数学注意：`glBlendFunc(SRC_ALPHA, ONE_MINUS_SRC_ALPHA)` 同样作用于
  目标 alpha 通道（`a' = a_s² + a_d(1−a_s)`）——叠加多层后 alpha 不再等于 1，属正常现象。

---

## 9. 已知限制（有意保留）

| 限制 | 说明 | 解除条件 |
|---|---|---|
| 法线矩阵简化 | `mat3(model)` 不支持非均匀缩放 | 出现需求时换 inverse-transpose |
| 数组 uniform 不可编辑 | 数组只读展示（避免按 vec3 误上传）；单值 int 已支持 | 出现数组参数需求 |
| `.mat` 仍是全量存 | 每个参数抄一份默认值 → 改 shader 默认不跟随旧材质 | S2：稀疏存储 |
| 材质 0 哨兵 | 旧 `.mat` 的 `uShininess=0` 靠 GLSL 回落 | S2：加载时归一 |
| 光照无阴影 | 平面光/点光均不产 shadow map | roadmap P2/P3 |
| SPIR-V 旁路仅 Vulkan 实验 | GL 路径永远用 GLSL 源 | — |
| 运行期注入仅 GL 后端 | `_inject_runtime` 在 `OpenGLEntities`；Vulkan/ZenGL 实验后端未接 → 那边 SSVEP 仍静态 | 启用对应后端时补 |

---

## 10. 内置 shader 现状表

| shader | id | 用途 | 材质参数（注解声明） | 运行期注入 | 顶点属性 | 测试覆盖 |
|---|---|---|---|---|---|---|
| Basic | 1 | unlit 平面/刺激/媒体 | `uColor`（color4，默认白） | — | loc0/1（loc2 浪费） | gl_pixels 全节 |
| SSVEP | 2 | SSVEP 闪频刺激 | `freq`（Hz，1–60，默认 10）· `phase_shift`（rad，0–2π） | `time`（owner=runtime） | loc0/1 | vertex_layout 快照 · uniform_schema |
| Lighting | 3 | 受光 3D（默认 Cube；面光源 + 点光源） | `uColor` · `uShininess`(1–256，默认 32) · `uSpecularStrength`(0.001–1，默认 0.25) · `uDiffuseStrength`(0.001–4，默认 1) · `uAmbientStrength`(0.001–1，默认 1) · `uSpecularModel`(enum 0=Phong/1=Blinn) | — | loc0/1/2 全用 | gl_lighting 21 checks · uniform_schema |

> 面板呈现：参数按 `group` 折叠成组（`Surface` / `Specular` / `Stimulus`），带单位与"已改"标记，
> 单参数与整组复位按钮都在面板上。`time` 只读灰显、标注"引擎驱动"。

---

## 11. 新增/修改 shader 检查单（DoD）

1. **文件对**：`Name.vert` + `Name.frag` 入 `Resource/Shaders/Builtin/`。
2. **属性对照**：`in` 与目标 `STD_LAYOUT` 布局对齐（§3）；加了/删了属性 → 更新
   `test_vertex_layout.py` 快照表。
3. **uniform 注解**：每个「人可调」的参数写一行 `//!`（§6.1）—— 控件形态、范围、单位、默认值、
   分组。**这一步替代了以前「改面板代码」**；矩阵/时间这类注入项标 `owner=engine|runtime`。
4. **uniform 归属**：每个 uniform 填进 §5 表（矩阵/材质/运行期/注入）。
   帧级注入项 → 黑名单两处同步。
5. **注册**：`DEFAULT_SHADER_NAME/FILE`（内置）；需要默认材质就绪的话在
   `__load_default_material` 加（参照 DefaultLit 模式）。
6. **测试**：快照行（vertex_layout）+ 至少一个像素级用例（守卫本协议数值）+
   `test_uniform_schema.py`（注解解析/默认值/引用唯一性）→ runner 全绿。
7. **文档**：本文件 §10 表 + `rendering_protocol.md §6` 发现清单同步。

---

## 12. 交叉引用

- `rendering_protocol.md` — 架构 / 命令 / **§7 渲染目标(RT)** / **§8 光照体系**（运行链路）/ 验证体系
- `roadmap_next.md` 章 G — 能力差距与优先级
- `content_schema_plan.md` — S1–S5 迁移路线（本文 §6.1 是其 S1 落地）
- 测试：`test_vertex_layout.py`（布局快照）· `test_gl_pixels.py`（Basic 行为）·
  `test_gl_lighting.py`（光照数值）· `test_material_isolation.py`（材质隔离）·
  `test_uniform_schema.py`（注解/GUI 契约/引用唯一性/时间注入）

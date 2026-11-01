"""Op registry — 编辑器 Live op 的单一事实源（CLI / 精简 MCP / 文档生成共用）。

数据来源与责任:
  - 引擎侧实现: Application/Editor/Services/LiveCommandServer.py `_register_ops()`（75 ops）;
  - 本注册表是 agent 侧（CLI/MCP/Skill）的唯一元数据来源;
  - 新增 op 时: 引擎侧注册实现 → 本表加条目 → `python -m engine_editor_mcp.docgen` 重生成 ops.md;
  - 完整性由 Test/Application/Editor/test_editor_mcp_package.py 对照引擎源码守卫。

消费方:
  - cli.py     — 参数提示 / 帮助 / 别名解析;
  - server.py  — lite 档 MCP 工具 engine_help / engine_call / engine_batch;
  - docgen.py  — 生成 skills/engine-editor/references/ops.md。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Param:
    """op 参数元数据（kind 仅供帮助/文档; CLI 实际用 "JSON 或字符串" 统一规则解析）。"""

    name: str
    kind: str = "str"  # str|int|float|bool|json|enum
    required: bool = False
    summary: str = ""


@dataclass(frozen=True)
class OpSpec:
    name: str
    category: str
    summary: str
    params: tuple[Param, ...] = ()
    internal: bool = False  # true → 不出现在 ops 列表/Skill 文档（frame.* 由 capture 封装）
    detail: str = ""
    # 可复制粘贴的真实调用示例（不带 `engine-editor-cli call` 前缀也行）。
    # 不填时由 example_args() 从 params 推一个“能看懂但不一定能跑”的占位示例。
    example: str = ""


CATEGORY_ORDER = [
    ("sim", "运行控制"),
    ("device", "设备会话"),
    ("view", "视图 / 摄像机"),
    ("ui", "界面面板"),
    ("renderer", "渲染器诊断"),
    ("entity", "实体"),
    ("selection", "选中"),
    ("component", "组件"),
    ("scene", "场景"),
    ("resource", "资源"),
    ("graph", "节点图"),
    ("project", "工程"),
    ("extension", "扩展体系"),
    ("settings", "设置"),
    ("frame", "抓帧（内部）"),
    ("threads", "线程诊断"),
    ("editor", "编辑器"),
]

_E = (Param("id", "int", False, "实体 id（id / name 二选一）"),
      Param("name", "str", False, "实体名（id / name 二选一；重名取首个）"))

OPS: dict[str, OpSpec] = {o.name: o for o in [
    # ── sim ──
    OpSpec("sim.play", "sim", "启动 PIE（等同 Run 按钮；启动前硬预检，force=true 跳过）",
           (Param("force", "bool", False, "true=跳过未知节点类型等预检硬拦（默认 false）"),),
           detail="预检只看“必然不生效”的状态（如未注册节点类型 → 图不会求值）。"
                  "被拦时返回 {\"error\": \"preflight_failed\", \"problems\": [...]}，"
                  "原因同时写入 sim.state 的 last_error。"),
    OpSpec("sim.stop", "sim", "停止 PIE（等同 Stop 按钮）"),
    OpSpec("sim.state", "sim", "查询模拟状态（state / runtime_alive）"),
    # ── device ──
    OpSpec("device.save", "device", "不停采保存设备录制（session/buffer；返回 paths/samples/written）",
           (Param("device", "str", False, "会话名（省略 = 自动绑定唯一会话）"),
            Param("save_scope", "enum", False, '"session"（默认）/ "buffer"'),
            Param("elapsed_s", "float", False, "保存前 pump 到的仿真时间（可选）"),
            Param("tag", "str", False, "文件名标签（可选）"),
            Param("pool", "str", False, "池作用域（可选）"),
            Param("pump", "bool", False, "保存前补齐数据（默认 true）"))),
    # ── view / camera ──
    OpSpec("view.set_mode", "view", "设置 Scene Type（3d / 2d / overlay；含 game_type + 视口）",
           (Param("mode", "enum", True, '"3d" / "2d" / "overlay"'),)),
    OpSpec("view.set_grid", "view", "显示/隐藏编辑器视口网格（View 菜单 Show Grid 同路径）",
           (Param("visible", "bool", True, "true=显示 false=隐藏"),)),
    # ── ui panels ──
    OpSpec("ui.panels", "ui", "列出编辑器面板（内置 + 扩展窗口）及可见性"),
    OpSpec("ui.panel", "ui", "读/写单个面板可见性（打开/关闭；与 View 菜单同路径）",
           (Param("name", "str", True, "面板名（ui.panels 列表；如 Node Editor/Scene/Settings）"),
            Param("visible", "bool", False, "true=打开 false=关闭（省略 = 只读）"),
            Param("toggle", "bool", False, "true=取反（可选；与 visible 二选一）")),
           detail="Node Editor 额外返回 view 诊断: canvas_w/zoom/mouse/selected_nodes/box/nodes/groups（只读）。"),
    OpSpec("ui.mouse", "ui", "移动鼠标（屏幕坐标；同时移动真实 GLFW 光标并聚焦编辑器）",
           (Param("x", "float", True, "屏幕 X"),
            Param("y", "float", True, "屏幕 Y"))),
    OpSpec("ui.mouse_button", "ui", "按下/抬起鼠标键（down=true/false；0/1/2 = 左/右/中）",
           (Param("down", "bool", True, "true=按下 false=抬起"),
            Param("button", "int", False, "0=左键（默认）/1=右键/2=中键"),
            Param("x", "float", False, "可选：同时移动到的 X"),
            Param("y", "float", False, "可选：同时移动到的 Y"))),
    OpSpec("ui.click", "ui", "在 (x,y) 执行真实点击（移动→按下→抬起，跨 3 帧）",
           (Param("x", "float", True, "屏幕 X"),
            Param("y", "float", True, "屏幕 Y"),
            Param("button", "int", False, "0=左键（默认）/1=右键/2=中键"))),
    OpSpec("ui.drag", "ui", "从 (x0,y0) 拖到 (x1,y1)（逐帧移动，默认 8 步）",
           (Param("x0", "float", True, "起点 X"),
            Param("y0", "float", True, "起点 Y"),
            Param("x1", "float", True, "终点 X"),
            Param("y1", "float", True, "终点 Y"),
            Param("steps", "int", False, "中间移动帧数 1..120（默认 8）"),
            Param("button", "int", False, "0=左键（默认）/1=右键/2=中键"))),
    OpSpec("ui.wheel", "ui", "滚轮输入（dy 正数向上；画布缩放/列表滚动）",
           (Param("dy", "float", True, "纵向滚轮量，正数向上"),
            Param("dx", "float", False, "横向滚轮量（默认 0）"))),
    OpSpec("ui.key", "ui", "按下/抬起键盘键（key=escape/delete/… 或 ImGui key code）",
           (Param("key", "str", True, "键名或整数 code"),
            Param("down", "bool", False, "true=按下（默认）false=抬起"))),
    # ── renderer ──
    OpSpec("renderer.snapshot", "renderer",
           "渲染器状态快照（后端 / GL 信息 / 资源计数 / 视口 / 帧统计; 无头时 available=false）"),
    # ── threads ──
    OpSpec("threads.snapshot", "threads",
           "线程注册表快照（注册/未注册漂移/停滞检测; 见 Doc/Dev/threading_protocol.md）"),
    OpSpec("camera.get", "view", "读取场景摄像机（Transform + Camera）",
           (Param("role", "enum", False, '"3d"(默认) / "2d" / "overlay"'),)),
    OpSpec("camera.set", "view", "修改场景摄像机（仅传字段）",
           (Param("role", "enum", True, '"3d" / "2d" / "overlay"'),
            Param("position", "json", False, "[x,y,z]"),
            Param("rotation", "json", False, "[x,y,z] 角度"),
            Param("projection", "enum", False, '"persp" / "ortho"'),
            Param("ortho_size", "float", False, ""),
            Param("fov", "float", False, ""))),
    # ── entity ──
    OpSpec("entity.list", "entity", "列出实体（roots_only=true 仅根；with_transform=true 附带位姿）",
           (Param("roots_only", "bool", False, "默认 false"),
            Param("with_transform", "bool", False, "true=每项附 transform{position,rotation_deg,scale}（省逐个 entity.get）")),
           example="roots_only=true with_transform=true"),
    OpSpec("entity.get", "entity", "读取实体快照（组件/层级/可见性/transform）", _E),
    OpSpec("entity.add", "entity", "新建实体（Transform only；有选中时成为其子级；自动选中新实体）",
           (Param("name", "str", False, "实体名"),
            Param("parent", "str", False, '父实体 id/名称；"none"=强制根实体')),
           detail=("返回: {entity_id, name, components, ...} — 后续 op 用 id=entity_id。"
                   "批量建独立根实体时必须传 parent=\"none\"（否则后建的会成为前一个的子级）。"),
           example='name=JudgeGreen parent="none"'),
    OpSpec("entity.rename", "entity", "重命名实体（不强制唯一）", _E + (Param("new_name", "str", True, ""),)),
    OpSpec("entity.delete", "entity", "删除实体（scope: one/tree/list；默认 tree）",
           _E + (Param("ids", "json", False, "实体 id/名称列表（可选）"),
                 Param("scope", "enum", False, "one / tree（默认） / list"),
                 Param("reparent_children", "bool", False, "scope=one 时子实体重挂到父级（默认 true）"))),
    OpSpec("entity.transform", "entity", "设置 transform（编辑器坐标；rotation 角度；relative=相对调整）",
           _E + (Param("position", "json", False, "[x,y,z]"),
                 Param("rotation", "json", False, "[x,y,z] 角度"),
                 Param("scale", "json", False, "标量或 [x,y,z]"),
                 Param("local", "bool", False, "本地坐标"),
                 Param("relative", "bool", False, "位移加/旋转加/缩放乘（gizmo 语义）")),
           detail=("坐标约定: position/rotation 一律是**编辑器坐标** X 右 / Y 前 / Z 上，"
                   "旋转单位=度。2D 场景只看 x / y（z 不参与投影也不控遮挡）。"
                   "落盘的 .scene 用 GL 坐标（x, z, -y），是另一套表示 —— 不要拿"
                   ".scene 里的字段顺序反推本 op 的数组顺序。"),
           example='name=JudgeGreen position=[0,6,0]'),
    OpSpec("entity.visible", "entity", "设置可见性（editor=眼图标; render=MeshRenderer；scope one/tree/list）",
           _E + (Param("ids", "json", False, "实体 id/名称列表（可选）"),
                 Param("scope", "enum", False, "one / tree / list；editor 默认 tree，render 默认 one"),
                 Param("editor", "bool", False, "编辑器视口"),
                 Param("render", "bool", False, "运行时渲染"))),
    OpSpec("entity.reparent", "entity", "设置父实体（parent=\"none\" 解除）",
           _E + (Param("parent", "str", True, 'id/名称/"none"'),)),
    # ── selection ──
    OpSpec("selection.get", "selection", "当前选中实体"),
    OpSpec("selection.set", "selection", "选中实体（gizmo=true 同时显示 gizmo）",
           _E + (Param("gizmo", "bool", False, "默认 true"),)),
    OpSpec("selection.clear", "selection", "清除选中"),
    # ── component ──
    OpSpec("component.types", "component", "已注册组件类型表"),
    OpSpec("component.list", "component", "实体的组件名列表", _E),
    OpSpec("component.add", "component", "添加组件（MeshRenderer 自动绑默认 Cube）",
           _E + (Param("type", "str", True, "Camera / MeshRenderer / Transform"),)),
    OpSpec("component.remove", "component", "移除组件（Transform 不可移除）",
           _E + (Param("type", "str", True, ""),)),
    OpSpec("component.get", "component", "读取组件字段快照（MeshRenderer 附 mesh/material 摘要）",
           _E + (Param("type", "str", True, ""),)),
    OpSpec("component.set", "component", "部分字段更新（Transform/MeshRenderer/Camera 专用 setter）",
           _E + (Param("type", "str", True, ""),
                 Param("fields", "json", True, '字段 dict，如 {"color":[1,0,0]}'),
                 Param("local", "bool", False, ""),
                 Param("relative", "bool", False, ""))),
    # ── scene ──
    OpSpec("scene.list", "scene", "场景列表 + 活跃场景"),
    OpSpec("scene.switch", "scene", "切换场景（内存态；不写盘 —— 改过磁盘文件请用 reload=true / scene.load）",
           (Param("name", "str", True, "场景名（scene.list）"),
            Param("reload", "bool", False, "true=从该场景的 .scene 文件重新读取（手改 JSON 后用）")),
           detail="**不会保存到磁盘**。switch 只把 ECS / 画布切到内存里的另一份场景；"
                  "手改了 .scene 文件却直接 switch，看到的是内存里的旧数据。",
           example="name=MI-SSSEP"),
    OpSpec("scene.create", "scene", "新建场景并切换为活跃（含视口/节点图同步）", (Param("name", "str", True, ""),)),
    OpSpec("scene.save", "scene", "保存当前场景（省略 path 用最近路径）",
           (Param("path", "str", False, ""),)),
    OpSpec("scene.load", "scene", "从磁盘加载 .scene 并设为活跃（只加载，不写盘）",
           (Param("path", "str", True, ".scene 文件路径（相对/绝对）"),),
           example="path=scenes/MI-SSSEP.scene"),
    # ── resource ──
    OpSpec("resource.list", "resource", "资源列表",
           (Param("kind", "enum", True, "mesh / shader / texture / material / prefab"),)),
    OpSpec("resource.find", "resource", "按名查找（返回全部匹配）",
           (Param("kind", "enum", True, ""), Param("name", "str", True, ""))),
    OpSpec("resource.material.get", "resource", "材质详情（shader/颜色/纹理槽/uniform）",
           (Param("id", "int", False, "id / name 二选一"), Param("name", "str", False, ""))),
    # ── graph ──
    OpSpec("graph.list", "graph", "节点图快照（nodes: id/type/owner/alias/description/props/pins; links）"),
    OpSpec("graph.types", "graph", "发现可用节点类型（含扩展 node_pack）: type/label/category/owner/pins",
           (Param("owner", "str", False, "只看某个扩展，如 device"),
            Param("category", "str", False, "只看某个分类"))),
    OpSpec("graph.add", "graph", "添加节点（等同 Add 菜单；不要求连线，可先建节点池）",
           (Param("type", "str", True, "节点类型名，如 EntitySpawn / graph.types 查询"),
            Param("props", "json", False, "节点属性 dict"),
            Param("description", "str", False, "节点描述（agent/新手可读）"),
            Param("position", "json", False, "[x,y] 画布位置"))),
    OpSpec("graph.link", "graph", "连接两个引脚（from/to 各 {node,pin}；pin 是引脚名，不是 pin id）",
           (Param("from", "json", True, '{"node":1,"pin":"exec"}'),
            Param("to", "json", True, '{"node":2,"pin":"exec_in"}')),
           detail="引脚名用 graph.list 的 nodes[].pins 查（如 Value / MICode / exec_in）。",
           example='from={"node":402,"pin":"Value"} to={"node":10800,"pin":"MICode"}'),
    OpSpec("graph.unlink", "graph", "删除连线（link=<id> 或 from/to 引脚）",
           (Param("link", "int", False, "连线 id（graph.list 的 links[].id）"),
           Param("from", "json", False, '{"node":1,"pin":"exec"}（与 to 成对）'),
           Param("to", "json", False, '{"node":2,"pin":"exec_in"}（与 from 成对）')),
           example="link=500"),
    OpSpec("graph.remove_node", "graph", "删除节点及其所有连线（等同画布 Delete）",
           (Param("node", "int", False, "节点 id"),
           Param("nodes", "json", False, "[id, ...] 批量删除（不存在的 id 进 missing）")),
           example="nodes=[10800,10801]"),
    OpSpec("graph.set_props", "graph", "更新节点属性（props 按 id 白名单改，不要用切片批量套）",
           (Param("node", "int", True, "节点 id"),
            Param("props", "json", True, '{"frequency": 10}')),
           example='node=10800 props={"frequency": 10}'),
    OpSpec("graph.set_description", "graph", "读写节点描述（省略 description=读取；空串=清除）",
           (Param("node", "int", True, "节点 id"),
            Param("description", "str", False, "节点描述"))),
    OpSpec("graph.validate.start", "graph", "启动干跑校验（静态+模拟；source=canvas/graph）",
           (Param("source", "enum", False, "canvas(默认) / graph"),
            Param("graph", "json", False, "source=graph 时必填"),
            Param("frames", "int", False, "默认 360"),
            Param("seed", "int", False, "默认 0"),
            Param("verbose", "bool", False, "默认 true"))),
    OpSpec("graph.validate.state", "graph", "校验任务状态（task_id 省略=最新）",
           (Param("task_id", "int", False, ""),)),
    OpSpec("graph.validate.report", "graph", "取回校验报告（可 save_path 落盘）",
           (Param("task_id", "int", False, ""), Param("save_path", "str", False, ".json/.txt"))),
    OpSpec("graph.validate.cancel", "graph", "取消校验任务（帧间生效）",
           (Param("task_id", "int", False, ""),)),
    OpSpec("graph.export", "graph", "导出画布 JSON（path 落盘；inline=false 只回摘要 — 省 token）",
           (Param("path", "str", False, "落盘路径（自动补 .json）"),
            Param("include_rules", "bool", False, "默认 true；不需规则文档时传 false"),
            Param("inline", "bool", False, "默认 true 返回完整图；false 只回 counts+saved_path"))),
    OpSpec("graph.import", "graph", "导入图替换画布（validate_first 默认开；有静态 error 拒绝）",
           (Param("graph", "json", False, "graph dict（或 path）"),
            Param("path", "str", False, ".json 文件"),
            Param("validate_first", "bool", False, "默认 true"))),
    OpSpec("graph.fit", "graph", "视图适配全部节点（等同节点编辑器工具栏 Fit；截图前常用）"),
    OpSpec("console.tail", "editor", "读引擎控制台日志（stdout/stderr tee；since/lines/level）",
           (Param("since", "int", False, "只返回 seq > since（轮询用）"),
           Param("lines", "int", False, "最多返回多少行（默认 200，上限 4000）"),
           Param("level", "str", False, "按级别过滤：info / warn / error"))),
    OpSpec("graph.group.merge", "graph",
           "把选中节点合并为组（等同画布右键 Merge into Group；不改节点位置）",
           (Param("nodes", "json", True, "[2,3] 或节点 alias 列表"),
            Param("alias", "str", False, "组别名；省略自动 group_N"))),
    OpSpec("graph.group.ungroup", "graph",
           "拆分组框（保留成员节点与子组；等同 Groups 窗口 Ungroup）",
           (Param("group", "str", True, "组 gid 或 alias"),)),
    OpSpec("graph.group.delete", "graph",
           "删除组框（默认连同子组；只删元数据，成员节点保留）",
           (Param("group", "str", True, "组 gid 或 alias"),
            Param("recursive", "bool", False, "默认 true；false 只删当前组框"))),
    OpSpec("graph.group.destroy", "graph",
           "销毁组（组框、子组和全部成员节点一起删除；等同画布 Destroy Group）",
           (Param("group", "str", True, "组 gid 或 alias"),
            Param("recursive", "bool", False, "默认 true；false 只销毁当前组"))),
    # ── project ──
    OpSpec("project.open", "project", "打开 .myproj 工程（资源+场景全加载）",
           (Param("path", "str", True, ".myproj 路径"),)),
    OpSpec("project.save", "project", "保存工程（File ▸ Save Project；带 path = Save As）",
           (Param("path", "str", False, "省略=保存到当前路径（需已保存过）；提供=Save As"),)),
    OpSpec("project.export", "project", "导出工程包（File ▸ Export；include_player=true 附游戏层成品）",
           (Param("target_parent", "str", True, "父目录 → 输出 <target_parent>/<Name>/"),
            Param("include_player", "bool", False, "默认 true（含 runtime 自包含）；false=纯工程包"))),
    # ── extension（扩展体系: 增量扫描发现 ext.<id>.* 扩展 op） ──
    OpSpec("extension.list", "extension", "扩展列表+状态+扩展 op（ext.<id>.* 在此发现）",
           detail="扩展 op 为运行期增量注册（不在本静态表中）— 用 extension.list 获取当前清单。"),
    OpSpec("extension.enable", "extension", "启用扩展（等同 Extensions 菜单勾选; 加载 on_load/on_enable）",
           (Param("id", "str", True, "扩展 id（如 sigproc）"),)),
    OpSpec("extension.disable", "extension", "停用扩展（on_disable/on_unload + 注销其全部 ops）",
           (Param("id", "str", True, "扩展 id"),)),
    # ── settings（编辑器全局设置; 与 Settings 面板同一单点 EditorSettings） ──
    OpSpec("settings.get", "settings", "读取编辑器设置（省略 key = 全量; UI: Settings 面板 Common 页）",
           (Param("key", "str", False, "如 ui.font_scale / ui.language"),)),
    OpSpec("settings.set", "settings", "写入编辑器设置（校验+钳制 → 持久化 → 下一渲染帧生效）",
           (Param("key", "str", True, "如 ui.font_scale / ui.language"),
            Param("value", "json", True, "新值（数值 / 字符串）"))),
    OpSpec("debug.events", "settings", "读写 Debug ▸ Terminal 事件上报配置（enabled / events）",
           (Param("enabled", "bool", False, "总开关"),
           Param("events", "json", False, '[key, ...] 或 "a,b"；未知 key 丢弃')),
           example="events=[\"input.key\",\"scene.new\"]"),
    # ── frame（内部；agent 侧请用 capture / engine_capture）──
    OpSpec("frame.request", "frame", "请求抓下一渲染帧（内部）",
           (Param("target", "enum", True, "editor / pie"),), internal=True),
    OpSpec("frame.fetch", "frame", "取帧（内部；就绪时带二进制尾帧）",
           (Param("target", "enum", True, ""), Param("generation", "int", True, "")), internal=True),
    # ── editor ──
    OpSpec("editor.quit", "editor", "请求关闭编辑器（下一帧正常退出）"),
]}

# 旧 MCP 工具名 → op 别名（engine_call / CLI 兼容老提示词与文档）
ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "editor_run_pie": ("sim.play", {}),
    "editor_stop_pie": ("sim.stop", {}),
    "editor_sim_state": ("sim.state", {}),
    "editor_switch_2d": ("view.set_mode", {"mode": "2d"}),
    "editor_set_scene_type": ("view.set_mode", {}),
    "editor_camera_get": ("camera.get", {}),
    "editor_camera_set": ("camera.set", {}),
    "editor_graph_list": ("graph.list", {}),
    "editor_graph_add": ("graph.add", {}),
    "editor_graph_link": ("graph.link", {}),
    "editor_graph_set_props": ("graph.set_props", {}),
    "editor_graph_set_description": ("graph.set_description", {}),
    "editor_graph_export": ("graph.export", {}),
    "editor_graph_import": ("graph.import", {}),
    "editor_project_open": ("project.open", {}),
    "editor_entity_list": ("entity.list", {}),
    "editor_entity_get": ("entity.get", {}),
    "editor_entity_add": ("entity.add", {}),
    "editor_entity_rename": ("entity.rename", {}),
    "editor_entity_delete": ("entity.delete", {}),
    "editor_entity_transform": ("entity.transform", {}),
    "editor_entity_visible": ("entity.visible", {}),
    "editor_entity_reparent": ("entity.reparent", {}),
    "editor_selection_get": ("selection.get", {}),
    "editor_selection_set": ("selection.set", {}),
    "editor_selection_clear": ("selection.clear", {}),
    "editor_component_types": ("component.types", {}),
    "editor_component_list": ("component.list", {}),
    "editor_component_add": ("component.add", {}),
    "editor_component_remove": ("component.remove", {}),
    "editor_component_get": ("component.get", {}),
    "editor_component_set": ("component.set", {}),
    "editor_scene_list": ("scene.list", {}),
    "editor_scene_switch": ("scene.switch", {}),
    "editor_scene_create": ("scene.create", {}),
    "editor_scene_save": ("scene.save", {}),
    "editor_scene_load": ("scene.load", {}),
    "editor_resource_list": ("resource.list", {}),
    "editor_resource_find": ("resource.find", {}),
    "editor_resource_material_get": ("resource.material.get", {}),
    "editor_quit": ("editor.quit", {}),
}

# engine_help / CLI `help <topic>` 的主题索引（完整文本按需返回 — 渐进披露）
TOPIC_HELP = {
    "mcp": (
        "lite 档 MCP 工具（6 个）:\n"
        "  engine_help(op|topic)      — 本目录 / 单 op 详情（按需读取，省 token）\n"
        "  engine_call(op, args)      — 执行 1 个 op（兼容旧工具名; 大载荷自动瘦身）\n"
        "  engine_batch(calls)        — 一次调用顺序执行多个 op\n"
        "  engine_validate_graph(...) — 图干跑校验（detail=summary 默认）\n"
        "  engine_capture(target)     — 抓帧（图像直回; 想省 token 用 CLI capture）\n"
        "  engine_launch(...)         — 启动引擎 + 自动端口握手（多 agent 各用自己的端口）\n"
        "完整档: 启动参数 --profile full 或 env MGE_MCP_PROFILE=full（45 个 editor_* 旧工具 + engine_launch）。"
    ),
    "cli": (
        "engine-editor-cli（终端模式，零常驻上下文成本 — 首选）:\n"
        "  engine-editor-cli launch [--port auto] [--language en|zh] [--set k=v]  # 启动引擎 + 握手\n"
        "  engine-editor-cli engines                    # 扫描 8977..9076，列出运行中的编辑器\n"
        "  engine-editor-cli --port 8977 call ...       # 指定实例（全局 --port 放子命令前）\n"
        "  engine-editor-cli ops                        # op 目录\n"
        "  engine-editor-cli help <op>                  # 单 op 详情\n"
        "  engine-editor-cli call <op> k=v ... [--json '{...}']\n"
        "  engine-editor-cli batch ops.json             # 顺序批处理（- = stdin）\n"
        "  engine-editor-cli exec script.py             # 脚本模式（全局 engine 客户端）\n"
        "  engine-editor-cli validate [--detail full]   # 图干跑校验（阻塞编排）\n"
        "  engine-editor-cli capture pie --out f.png    # 抓帧落盘（只回路径）\n"
        "  engine-editor-cli setup [--workspace DIR] [--port N]  # 安装 skill + mcp.json\n"
        "值解析: 先尝试 JSON（数字/bool/数组/对象/引号字符串），失败按纯字符串。\n"
        "多引擎: 每个 agent 先 launch --port auto，后续统一用返回的 --port N。\n"
        "脚本模式: engine.ok('sim.play'); engine.try_send(...); engine.capture('pie'); engine.batch([...])"
    ),
    "skill": (
        "Skill（渐进披露, 推荐安装）: engine-editor-cli setup --workspace <你的项目>\n"
        "  写入 <ws>/.github/skills/engine-editor/SKILL.md（+ references/ops.md, workflows.md）\n"
        "  并合并 .vscode/mcp.json 注册（lite 档）。\n"
        "  Skill 按需加载: SKILL.md 只在相关任务时进入上下文; references 只在明确需要时读取。\n"
        "  VS Code / Claude Code / Codex 等终端型 agent 均可用（CLI 通道无需 MCP）。"
    ),
    "capture": (
        "抓帧两种方式:\n"
        "  MCP engine_capture(target) — PNG 落盘 + 图像直回（agent 能看到画面; 适合'看一眼'）\n"
        "  CLI capture [editor|pie]   — 只落盘并回路径（省 token; 图片由用户/工具查看）\n"
        "  目录: <临时目录>/engine_editor_mcp/frames（MGE_MCP_FRAMES_DIR 覆盖; server 启动清空）\n"
        "  pie 需 PIE 运行中; editor 随时可抓。"
    ),
}


def resolve(op_or_alias: str) -> tuple[str, dict[str, Any]]:
    """把 op 名或旧工具名解析为 (op, 默认 args)。未知名返回 ("", {})。

    例外: `ext.<id>.*` 为扩展 op（运行期增量注册, 无静态元数据）— 直接透传到引擎端,
    由引擎的扩展注册表解析（清单/状态经 `extension.list` 获取）。
    """
    if op_or_alias in OPS:
        return op_or_alias, {}
    if op_or_alias in ALIASES:
        return ALIASES[op_or_alias]
    if op_or_alias.startswith("ext."):
        return op_or_alias, {}
    return "", {}


def op_names(include_internal: bool = False) -> list[str]:
    return [n for n, o in OPS.items() if include_internal or not o.internal]


def example_args(spec: OpSpec) -> str:
    """给帮助文本生成一行 CLI 示例（挑前 2 个参数）。

    json 参数优先用 `Param.summary` 里写好的字面量（如 `{"node":1,"pin":"exec"}`），
    这样能直接复制粘贴；没有字面量时退回中性占位（并标注需替换），不伪造可直接信的值。
    """
    parts: list[str] = []
    for p in spec.params[:2]:
        if p.kind in ("int", "float"):
            val = "5" if p.required or p.name == "id" else "0"
        elif p.kind == "bool":
            val = "true"
        elif p.kind == "json":
            hint = (p.summary or "").strip()
            literal = hint.split("（")[0].split(" (")[0].strip()
            val = literal if literal[:1] in ("{", "[") else "'<json>'"
        elif p.kind == "enum":
            val = '"2d"' if "3d" in p.summary else '"mesh"'
        else:
            val = "VALUE"
        parts.append(f"{p.name}={val}")
    return " ".join(parts)


def format_ops_list() -> str:
    """engine_help 无参 / CLI `ops` 的输出：按类别列出一行式 op 目录。"""
    lines: list[str] = ["engine op 目录（engine-editor-cli call <op> k=v ...）:"]
    for cat, label in CATEGORY_ORDER:
        items = [o for o in OPS.values() if o.category == cat and not o.internal]
        if not items:
            continue
        lines.append(f"[{label}]")
        for o in items:
            lines.append(f"  {o.name} — {o.summary}")
    lines.append("详情: engine-editor-cli help <op>  或  engine_help(op)")
    return "\n".join(lines)


def suggest_ops(name: str, limit: int = 8) -> list[str]:
    """未知 op 的相近候选（同前缀优先，不命中时按前 3 字符包含关系兜底）。"""
    key = (name or "").strip().lower()
    if not key:
        return []
    prefix = key.split(".")[0]
    near = [n for n in op_names() if n.split(".")[0] == prefix]
    if not near:
        head = key[:3]
        near = [n for n in op_names() if head and head in n]
    return near[:limit]


def format_op_help(op_or_alias: str) -> str:
    """单 op 详情（engine_help(topic) / CLI `help <op>`）。未知名 → 建议。"""
    name, defaults = resolve(op_or_alias)
    if not name:
        near = suggest_ops(op_or_alias)
        hint = ("相近: " + ", ".join(near)) if near else "用 `ops` 看全部目录"
        return f"unknown op: {op_or_alias!r} — {hint}"
    spec = OPS[name]
    lines = [f"{spec.name} — {spec.summary}"]
    if spec.detail:
        lines.append(spec.detail)
    if spec.params:
        lines.append("参数:")
        for p in spec.params:
            flag = "必填" if p.required else "可选"
            t = f"{p.name}:{p.kind}"
            extra = f" — {p.summary}" if p.summary else ""
            lines.append(f"  {t} ({flag}){extra}")
    else:
        lines.append("参数: 无")
    call = spec.example or example_args(spec)
    if defaults:
        lines.append(f"alias: {op_or_alias} → {name}（默认 args={json.dumps(defaults, ensure_ascii=False)}）")
    lines.append(f"示例: engine-editor-cli call {name}" + (f" {call}" if call else ""))
    if spec.internal:
        lines.append("（内部 op — agent 请用 capture / engine_capture 封装）")
    return "\n".join(lines)


# ── agent 通道共享辅助（CLI / lite MCP / 批处理共用）──


def prepare_args(op_name: str, args: dict) -> dict:
    """调用前的轻量适配: graph.export 带 path 且未显式 inline → 默认 inline=false（避免全图回传）。"""
    if op_name == "graph.export" and args.get("path") and "inline" not in args:
        args = dict(args)
        args["inline"] = False
    return args


def call_timeout(op_name: str) -> float:
    if op_name == "project.open":
        return 60.0
    if op_name == "project.export":
        return 600.0  # 游戏层复制 runtime 镜像 (数百 MB / 上万文件) — 分钟级
    if op_name in ("graph.export", "graph.import", "graph.validate.report"):
        return 30.0
    return 15.0


def unknown_args(op_name: str, args: dict) -> list[str]:
    """对照注册表找出可疑参数名（引擎会静默忽略未知名 — 这里提醒 agent 防手误）。"""
    spec = OPS.get(op_name)
    if spec is None:
        return []
    known = {p.name for p in spec.params}
    return [k for k in args if k not in known]


def trim_result(op_name: str, result: dict, detail: str = "auto", log_cap: int = 120) -> dict:
    """返回瘦身: detail=full 原样; auto 对已知大载荷截断（graph.validate.report 的 log）。"""
    if detail == "full" or not isinstance(result, dict) or "error" in result:
        return result
    if op_name == "graph.validate.report" and isinstance(result.get("report"), dict):
        report = result["report"]
        log = report.get("log")
        if isinstance(log, list) and len(log) > log_cap:
            result = dict(result)
            report = dict(report)
            report["log_total"] = len(log)
            report["log_truncated"] = True
            report["log"] = log[:log_cap]
            result["report"] = report
    return result


def summarize_report(report: dict, log_cap: int = 30) -> dict:
    """校验报告摘要（engine_validate_graph detail=summary / CLI validate 默认）。"""
    if not isinstance(report, dict):
        return report
    out: dict = {}
    for key in ("task_id", "state", "ok", "counts", "graph"):
        if key in report:
            out[key] = report[key]
    timing = report.get("timing")
    if isinstance(timing, dict) and "duration_ms" in timing:
        out["duration_ms"] = timing["duration_ms"]
    static = report.get("static")
    if isinstance(static, dict):
        errors = static.get("errors") or []
        warnings = static.get("warnings") or []
        out["static"] = {
            "errors": errors[:20],
            "warnings": warnings[:20],
            "errors_total": len(errors),
            "warnings_total": len(warnings),
        }
    runtime = report.get("runtime")
    if isinstance(runtime, dict):
        rt = {
            k: runtime[k]
            for k in ("skipped", "cancelled", "frames_simulated", "total_events", "events_by_type", "killed_sessions")
            if k in runtime
        }
        errors = runtime.get("errors") or []
        rt["errors"] = errors[:20]
        rt["errors_total"] = len(errors)
        out["runtime"] = rt
    log = report.get("log")
    if isinstance(log, list) and log:
        out["log"] = log[:log_cap]
        if len(log) > log_cap:
            out["log_total"] = len(log)
            out["log_truncated"] = True
    out["detail"] = "summary（完整报告: detail='full' 或 editor_graph_validate_report / save_path）"
    return out

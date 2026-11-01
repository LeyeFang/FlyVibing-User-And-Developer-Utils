# `.scene` 文件格式（实体 / 节点图 / 数据模型）

面向: 需要**直接读写** `.scene` JSON 的开发者与 agent —— 先把格式看清楚，再用
`scene.load` / `graph.import` 载入；不要靠猜字段。

> 优先用 op 改场景（`entity.*` / `graph.*`），手改 JSON 是**离线/批量**手段。
> 手改之后必须 `scene.load path=...`（或 `scene.switch reload=true`）才会生效：
> `scene.switch` 只在内存里换场景，**不读盘也不写盘**。

## 1. 顶层结构

```jsonc
{
  "scene": {
    "name": "MI-SSSEP",
    "game_type": "2d",                     // 决定 PIE 用哪台场景摄像机
    "entities": { "13": { ... }, "17": { ... } },   // dict! key = id 的字符串形式
    "node_graph": {
      "nodes": { "10800": { ... } },       // dict! key = 节点 id 字符串
      "links": { "500": { ... } },         // dict! key = 连线 id 字符串
      "node_groups": { }                   // 不透明保留（工具的组元数据）
    }
  }
}
```

三条容易踩的：

1. `entities` / `nodes` / `links` 都是 **dict 不是 list**，key 是 id 的十进制字符串，
   内层的 `id` 字段是整数 —— 两边必须一致，否则加载后 id 与引用对不上。
2. `node_graph` 里**未注册的节点类型会被保留**（不丢节点），但不会被求值：
   加载时打印 `[NodeCanvas] WARNING: unknown node type(s)`，并把清单记到
   `canvas.unknown_node_types`；`sim.play` 会**拒绝启动**（`force=true` 可强跑），
   `graph.validate` 报 `unknown_type` error。原因九成是扩展没启用。
3. 场景坐标是 GL 系，**不是**编辑器系（见 §4）。

## 2. 实体条目

```jsonc
{
  "13": {
    "id": 13,
    "name": "JudgeGreen",
    "parent_id": null,                     // null = 根实体
    "editor_visible": true,
    "render_visible": true,
    "components": {
      "Transform": {
        "position_x": 0.0, "position_y": 0.0, "position_z": 0.0,
        "rotation_x": 0.0, "rotation_y": 0.0, "rotation_z": 0.0,
        "scale_x": 1.0,    "scale_y": 1.0,    "scale_z": 1.0,
        "local_pos_x": 0.0, "local_pos_y": 0.0, "local_pos_z": 0.0,
        "local_rot_x": 0.0, "local_rot_y": 0.0, "local_rot_z": 0.0,
        "local_scale_x": 1.0, "local_scale_y": 1.0, "local_scale_z": 1.0
      },
      "MeshRenderer": { "mesh_id": 3, "material_id": 1, "visible": true }
    }
  }
}
```

- **`position_*` 与 `local_pos_*` 必须一起改**。只写前者不生效：父级/世界矩阵由
  `local_*` 重新算出，加载时后者会覆盖前者。
- 旋转字段是**弧度**。op 层（`entity.transform`）用度，落盘换成弧度 —— 手改 JSON 时
  自己换算（`rad = deg * π / 180`）。
- 组件按名字做 key；没写的组件 = 实体没有该组件。

## 3. 节点图：`links` 是 pin 级，不是节点级

```jsonc
{
  "nodes": {
    "10800": {
      "id": 10800,
      "node_type": "ext.missssep.Infer",
      "props": { "threshold": 0.5 },
      "pin_ids": { "MICode": 10003, "exec_in": 10801 },   // 引脚名 → pin id
      "pos": [420.0, 160.0],
      "alias": "Infer",
      "description": "…"
    }
  },
  "links": {
    "500": { "id": 500, "from_pin": 10001, "to_pin": 10003 }   // 只有 pin id
  }
}
```

**两套表示，必须对照看**：

| 场合 | 表示 | 例子 |
|---|---|---|
| `.scene` / `graph.list` 的 `links[]` | 纯 pin id | `{"from_pin": 10001, "to_pin": 10003}` |
| `graph.link` / `graph.unlink` 的参数 | 节点 id + **引脚名** | `from={"node":402,"pin":"Value"}` |
| `graph.list` 的 `nodes[]` | 名字 ↔ id 的对照表 | `"pins": {"Value": 10001, ...}` |

所以：手改 `links` 时用 `pin_ids` 反查节点；用 op 连线时传**引脚名**（不是 pin id）。
引脚名以 `graph.list` 的 `pins` 为准 —— 名字写错会得到 `ValueError`，不会静默错连。

## 4. 坐标系：文件用 GL，op 用编辑器

| 坐标系 | 轴 | 谁在用 |
|---|---|---|
| 编辑器 | +X 右 / +Y 前 / +Z 上（旋转度） | `entity.transform` / `entity.get` / Inspector / 节点图 vector 引脚 |
| GL（落盘） | +X 右 / +Y 上 / +Z 后（旋转弧度） | `.scene` 的 `position_*` / `local_pos_*` |

转换（唯一定义处：`Application/Core/Math/CoordinateSystem.py`）：

```text
editor → GL : (x, y, z) → (x, z, -y)
GL → editor : (x, y, z) → (x, -z, y)
```

推论：`entity.transform position=[0,0,6]`（y=6 = 向前 6）落盘是 `(0, 6, 0)`。
2D 场景只有 x / y 参与投影，z 不控遮挡 —— 想让实体"跑出画面"就调 x / y。

## 5. 手改流程（推荐顺序）

```powershell
# 0) 先存一份，再改（scene.save 用最近路径；带 path = 另存）
engine-editor-cli call scene.save
# 1) 改 .scene JSON（编辑器/工具都可以）
# 2) 只加载不保存 —— 这一步才会读盘
engine-editor-cli call scene.load path=scenes/MI-SSSEP.scene
# 3) 核对（op 返回编辑器坐标）
engine-editor-cli call entity.list with_transform=true
```

反面教材：改完文件直接 `scene.switch` → 看到的是内存里的旧数据（switch 不读盘）。

## 6. 批量改属性 / 节点的安全做法

- **按 id 白名单**改：`graph.set_props node=<id> props={...}`。
  不要用"列表切片"批量套（`consts[:2]` 这类会把别人的节点一起改掉）。
- 批量删：`graph.remove_node nodes=[...]`（级联删连线，不存在的 id 进 `missing`）。
- 改完跑一次 `graph.validate`（静态 + 干跑），确认连线类型/未知类型都没问题。

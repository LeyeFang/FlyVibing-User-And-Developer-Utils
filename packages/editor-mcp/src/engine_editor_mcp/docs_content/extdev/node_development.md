# 节点开发指南（扩展 Node Pack）

> 读者：扩展作者 / agent。目标：用 `NodePackRegistry` 公开协议增加节点类型、求值器和声明式字段，
> 不修改 `Application/Core/NodeGraph/**`，不 import Editor / imgui。
>
> 先读规则索引：`extension_dev_protocol.md` §8；节点图完整规则由
> `flyvibing-node-editor rules` 提供。

## 1. 节点包放哪里

| 场景 | 位置 | 发现方式 |
|---|---|---|
| 引擎内置/官方扩展 | `Application/Functions/<Extension>/node_pack.py` | `NodeGraph` 自动发现，**不依赖扩展 enable** |
| 外部扩展运行期注册 | `on_load` 中 `ctx.nodes.register_pack(pack)` | 需要 manifest `capabilities` 含 `"nodes"` |

节点类型是 .scene 的持久身份，必须全局唯一；同一个 type 不能被不同 owner 覆盖。
官方从核心迁出的旧类型保留原名（例如 `SerialSend`）；新扩展建议使用
`ext.<id>.<Type>` 命名，避免与未来核心节点冲突。

## 2. 最小节点包

```python
def my_eval(node_id, ctx, graph):
    inst = graph._canvas.nodes[node_id]
    gain = float(inst.props.get("gain", 1.0))
    value = 0.0  # 需要上游时参考官方 pack 的 _read_input_raw helper
    if ctx.dry_run:
        ctx.emit_log(node_id, "MyNode", "apply", f"gain={gain}, value={value}")
        return
    # 真实副作用放这里；不要阻塞主线程
    print(f"[MyNode] gain={gain} value={value}")


def register() -> dict:
    return {
        "id": "myext",
        "name": "My Extension",
        "owner": "myext",
        "signature": "@ACME",
        "nodes": [
            {
                "type": "ext.myext.MyNode",
                "label": "My Node",
                "category": "My Extension",
                "color": (0.50, 0.70, 0.90),
                "props_text": "One-line description shown on the card.",
                "evaluator": my_eval,
                "pins": [
                    {"name": "exec_in", "kind": "exec", "direction": "input"},
                    {"name": "exec_out", "kind": "exec", "direction": "output"},
                    {"name": "Value", "kind": "data", "direction": "input",
                     "data_type": "variant"},
                ],
                "fields": [
                    {"key": "gain", "label": "Gain", "kind": "float", "default": 1.0},
                ],
            }
        ],
        "menu": [("My Extension", [("My Node", "ext.myext.MyNode")])],
    }
```

`register()`（或 `get_pack()`）必须返回 dict；不要只注册一半：`NodePackRegistry` 会先校验
全部节点、引脚和字段，再一次落地，失败不会留下半个包。

## 3. Pack / Node / Pin / Field 契约

### Pack

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | pack 唯一标识 |
| `owner` | 建议 | 缺省 = `id`；节点 type 的归属者 |
| `name` | ✅ | Add 菜单/诊断显示名 |
| `signature` | 建议 | 提供者签名，如 `@Official` / `@ACME`；缺省扩展节点显示 `@Community` |
| `nodes` | ✅ | 节点声明列表 |
| `menu` | 建议 | `[(标题, [子菜单项])]`；没有菜单也能被 `graph.add` 添加 |

### Node

| 字段 | 说明 |
|---|---|
| `type` / `type_name` | 持久类型名；必须唯一 |
| `label` | 编辑器显示名 |
| `category` | 卡片分类 |
| `color` | `(r, g, b)` 0..1 |
| `pins` | 至少一个引脚 |
| `fields` | 声明式控件（Node Editor 自动渲染） |
| `evaluator` | 可选 `callable(node_id, ctx, graph)` |
| `props_text` | 卡片说明；详细说明建议放节点实例 `description` |

### Pin

```json
{"name": "exec_in", "kind": "exec", "direction": "input"}
{"name": "Value", "kind": "data", "direction": "input", "data_type": "variant"}
```

- `kind`: `exec` / `data`
- `direction`: `input` / `output`
- `data_type`: `exec` / `variant` / `int` / `float` / `bool` / `string` / `entity_ref` / `device` 等
- `optional`: `true` 表示可空

### Field

当前通用控件支持的 `kind`：

| kind | 用途 | 关键参数 |
|---|---|---|
| `text` | 单行文本 | `default` |
| `int` | 整数 | `default` / `min` / `max` |
| `float` | 浮点 | `default`（当前不做 min/max 夹取） |
| `bool` | 开关 | `default` |
| `enum` | 下拉选择 | `choices`（`[[label, value], ...]`）/ `default` |
| `serial_port` | 串口/设备名选择 | `default` |

字段只负责**编辑 props**；求值器从 `inst.props` 读取。不要在字段里塞运行时状态。

### Provider 签名（节点卡灰色小字）

- 核心节点自动显示 `@Official`；官方扩展 pack 在 `register()` 返回的 pack 里写
  `"signature": "@Official"`。
- 社区扩展写自己的提供者，例如 `"signature": "@ACME"`；不写时扩展节点显示
  `@Community`，**绝不会自动冒充 `@Official`**。
- 签名渲染在节点标题下一行（灰色），与 `description` 分离；不要把签名塞进
  `props_text` 或描述。
- `engine-editor-cli call graph.types` / `NodePackRegistry.catalog()` 会返回
  `signature`，agent 可据此区分官方与社区节点。
- 校验：签名必须以 `@` 开头、不含空白/路径分隔符；非法值回退到默认签名。

> 数据输入读取：当前核心只提供 `graph._read_input(pin_id, ctx)`（私有，随版本可能变化）。
> 官方 pack 在 `node_pack.py` 里封装 `_read_input_raw(node_id, pin_name, ctx, graph, default)`
> 并沿 data 连线读取上游；扩展可复制这一小段模式，但不要把它当稳定公开 API 依赖。

## 4. 求值器纪律

1. **确定性**：同样输入 → 同样输出；随机数必须显式传入 seed。
2. **dry-run 第一等公民**：所有副作用节点必须检查 `ctx.dry_run`，调用 `ctx.emit_log`
   记录“本应执行”的动作；干跑不碰硬件、不落盘、不开线程。
3. **不阻塞主线程**：长任务交给已有设备线程/任务通道；不要在 evaluator 里 `sleep` 或等待 IO。
4. **不 import Editor / imgui**：扩展目录加入 `sys.path` 后可导入自己的私有模块；
   禁止反向依赖编辑器 UI。
5. **异常显式**：用 `ctx.emit_log(..., "error", ...)` 或明确抛出，不要静默吞错。
6. **数据输入读取**：参考 `SerialParallelDevice/node_pack.py` 的 `_read_input_raw`
   模式，沿 data 连线读取上游；未连接时使用 props fallback。

## 5. 注册、发现与验证

```powershell
# 发现当前节点类型（含扩展 pack）
engine-editor-cli call graph.types
engine-editor-cli call graph.types owner=myext

# 只建节点池（不连线），agent 常用
engine-editor-cli call graph.add type=ext.myext.MyNode

# 离线校验（不启动编辑器）
flyvibing-node-editor rules
python -m flyvibing_node_editor.node_graph_validator scenes/main.scene --frames 360
```

节点包自动发现与扩展 enable 状态解耦：内置 pack 在扩展停用后仍保留，因为节点类型属于
场景可加载性；运行期通过 `ctx.nodes` 注册的 pack 在 stop/unload 时反注册。

## 6. 测试与提交

```powershell
# 扩展静态审查（含节点/import/UI 规则）
python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>

# 建议为 pack 增加无头测试：test_<id>_node_pack.py
```

测试至少覆盖：

- `register()` 返回合法 pack，type/owner 唯一；
- 每个节点有至少一个 pin，字段 key 不重复；
- evaluator 在 dry-run 下只 emit_log、不触发真实副作用；
- 节点图保存/加载往返后 type/字段保持一致；
- 同 owner 重复注册幂等，不同 owner 覆盖会报错。

## 7. 节点组与 Example

节点组（macro）不是新的求值器；它由节点图工具展开成普通节点。构建/修改 Example 时，
优先用 `flyvibing-node-editor` 的 `add_group` / `set_group` / `apply-ops`，并用 alias
和 description 记录语义。

**重要**：组参数（`node_groups[gid].params`）是**构建参数**，不会自动回写已有节点的
`props`。例如串口组参数改了 `serial_baud`，但 `SerialSend.props.baud_rate` 仍是旧值时，
运行时使用的是节点 props。改组参数后必须重新展开/更新组，或直接改节点 props。

参考：`packages/node-editor/README.md`（组模板、alias、`set_group`）、
`Application/Functions/SerialParallelDevice/node_pack.py`（完整官方 pack）、
`Application/Functions/VirtualDevice/node_pack.py`（设备族 pack）。

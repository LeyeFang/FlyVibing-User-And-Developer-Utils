# 开发指南索引

> 本页把**扩展开发 / UI 开发 / 节点开发 / Example 开发**的入口集中到工具仓。
> 规范正文仍是单一来源：`packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/**`；
> 引擎仓库 `Doc/ExtDev/` 只保留指针 stub，不再维护第二份正文。

## 1. 按任务选择

| 你要做什么 | 读什么 | 命令 |
|---|---|---|
| 写第一个扩展 | [扩展开发入口](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/README.md) | `engine-editor-cli doc show extdev/README` |
| 给扩展加编辑器面板 | [UI 开发指南](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/ui_development.md) | `engine-editor-cli doc outline extdev/ui_development` |
| 给扩展加节点 | [节点开发指南](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/node_development.md) | `engine-editor-cli doc outline extdev/node_development` |
| 做一个官方/用户 Example | [Example 开发指南](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/example_development.md) | `engine-editor-cli doc outline extdev/example_development` |
| 在用户目录注入自己的 Example（不污染主线） | [Example 开发指南 §1.1](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/example_development.md) | 写入 `%APPDATA%/FlyVibingEngine/examples/<Name>/`，`.myproj` 加 `provider` |
| 让扩展自带 Example（推荐，零拷贝） | [Example 开发指南 §1.2](../packages/editor-mcp/src/engine_editor_mcp/docs_content/extdev/example_development.md) | 放 `<extension_dir>/Examples/<Name>/`；额外根目录用 `capabilities:["examples"]` + `ctx.examples.register` |
| 在图中保存设备录制（不停采） | [设备 IO 协议 §3](../packages/editor-mcp/src/engine_editor_mcp/docs_content/dev/device_io_protocol.md) | 节点 `SaveDeviceData`（Device ▸ Save）或 `engine-editor-cli call device.save ...`；`pump` 后落盘 |
| 端到端实验流程 | [TUTORIAL.md](TUTORIAL.md) | `engine-editor-cli doc outline dev/...`（内部协议） |
| 扩展静态审查 | [extension-kit README](../packages/extension-kit/README.md) | `flyvibing-review <extension-dir>` |
| 离线节点图工具 | [node-editor README](../packages/node-editor/README.md) | `flyvibing-node-editor --help` |

## 2. 建议阅读顺序

1. `extdev/README` — 扩展体系是什么、manifest、生命周期。
2. `extdev/ui_development` 或 `extdev/node_development` — 按你的贡献面选择。
3. `extdev/example_development` — 把能力放进可运行 Example。
4. `extension_dev_protocol.md` — 需要精确契约时查全文。
5. `Doc/Dev/`（引擎内部）— 只有改引擎核心时才需要；扩展作者不必通读。

## 3. 文档位置约定

- **工具仓是权威**：扩展/节点/Example 指南与 `docs_content/extdev/**` 都在本仓库维护。
- 引擎仓库 `Doc/ExtDev/README.md` 只提供 CLI 阅读入口和指针，不复制正文。
- 本文档索引随工具版本发布；新增指南时同步更新本页、`extdev/README` 与根 `README.md` 的文档表。

## 4. 验证命令

```powershell
# 查看 CLI 内文档主题
engine-editor-cli doc
engine-editor-cli doc outline extdev/ui_development
engine-editor-cli doc show extdev/node_development#2

# 扩展/节点/Example 的静态检查
flyvibing-review Application/Functions/<Extension>
flyvibing-node-editor rules
python -m flyvibing_node_editor.node_graph_validator scenes/main.scene --frames 360
```

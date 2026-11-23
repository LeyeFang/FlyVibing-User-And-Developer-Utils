## FlyVibing 工具链（Agent 入口）

## 先看这里：CLI 优先

- 实时编辑器（需要编辑器运行中）：
  - `engine-editor-cli ops --json` — 机器可读命令清单（`engine-cli/manifest/v1`）
  - `engine-editor-cli help <op|主题>` — 单 op 参数/示例，按需读取
  - `engine-editor-cli call <op> k=v ...` / `batch` / `exec` / `validate` / `capture`
- 离线节点图（不需要引擎）：
  - `flyvibing-node-editor schema` — 命令清单（`flyvibing-node-editor/manifest/v1`）
  - `flyvibing-node-editor rules` — 按节读取节点图规则
  - `flyvibing-node-editor build` / `apply` / `validate` / `query` / `patch` / `simulate`
- 任意能跑命令的 agent 都能用 CLI；MCP 是可选的工具通道（lite 档 6 个元工具），不是必需依赖。
- stdout 始终是 JSON（失败也是）；退出码：0 成功 / 1 运行错误 / 2 用法错误。按退出码分支，不要 grep 文本。

## 安装到工作区

```text
engine-editor-cli setup --workspace <dir> --target auto
```

按已存在的 `.vscode` / `.claude` / `.cursor` / `.github` 写入对应 MCP 配置与 skill，并生成
`AGENTS.md` 标记块；未内置支持的客户端用 `--print` 只打印片段，不硬写路径。

## 上下文纪律

- 先索引后内容：`ops` / `schema` / `rules`（目录）→ `help <op>` / `rules <section>`。
- 大输出落盘再局部读：`--out` / `save_path` / `graph.export path=...`。
- 多步操作合并成 `batch` 或 `exec` 脚本，避免十几次单 op 往返。

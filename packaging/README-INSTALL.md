# FlyVibing Tools {{VERSION}} — 安装说明

发布包是一个 zip：解压后双击 `install.cmd`（Windows），或在 macOS/Linux 执行
`sh install.sh`。安装器只需要 Python 3.10+，会安装 zip 内的三个 wheel：

- `engine-editor-mcp`（`engine-editor-cli` / `engine-editor-mcp`）
- `flyvibing-node-editor`（`flyvibing-node-editor`）
- `flyvibing-extension-kit`（`flyvibing-review`）

## Windows

```text
双击 install.cmd
```

可选：把技能/MCP 配置直接写入一个工作区：

```text
install.cmd --workspace C:\path\to\project
```

`install.cmd` 会先找 Python 3.10+，再调用 `install.ps1` / `install.py`。如果直接运行
PowerShell 脚本时被执行策略拦截：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

## macOS / Linux

```sh
sh install.sh
sh install.sh --workspace /path/to/project
```

## 安装位置与 PATH

- 普通 Python：安装到当前用户的 user site；console scripts 通常位于
  `%APPDATA%\Python\Python3xx\Scripts`（Windows）或 `~/.local/bin`（Linux/macOS）。
- 虚拟环境：检测到 venv 时自动安装到该 venv，不使用 `--user`。
- 若 `engine-editor-cli` 不在 PATH，安装器会打印实际的 scripts 目录；把它加入 PATH
  后即可直接运行。脚本的完整调用方式也始终可用：

```powershell
python -m engine_editor_mcp.cli --help
python -m flyvibing_node_editor.cli --help
```

## 依赖与离线安装

安装器默认让 pip 解析 `mcp`、`Pillow`、`numpy` 及其依赖；如果目标机器已有这些依赖，
可以完全离线：

```text
install.cmd --offline
python install.py --offline
```

离线模式不会下载任何包；缺少依赖时会明确失败。

## 验证

```powershell
engine-editor-cli --version
engine-editor-cli ops
engine-editor-cli engines
flyvibing-node-editor rules
python -c "import flyvibing_extension_kit; print('extension-kit ok')"
```

`engine-editor-cli setup --workspace DIR` 会写入 `.vscode/mcp.json` 与
`.github/skills/engine-editor/`；安装完成并重载 IDE 窗口后，agent 才能看到 MCP 工具。

## 手动安装

```powershell
python -m pip install --upgrade --find-links .\wheels `
  engine-editor-mcp flyvibing-node-editor flyvibing-extension-kit
```

卸载三个包：

```powershell
python -m pip uninstall engine-editor-mcp flyvibing-node-editor flyvibing-extension-kit
```

## English quick start

Unzip the archive and run `install.cmd` on Windows (or `sh install.sh` on macOS/Linux).
The installer requires Python 3.10+, installs the three bundled wheels, and can optionally
register the skill and MCP configuration in a workspace:

```text
install.cmd --workspace C:\path\to\project
```

Use `--offline` when the machine already has `mcp`, `Pillow`, and `numpy`; use
`--python <path>` to select a specific interpreter. Verify with `engine-editor-cli ops`
and reload the IDE after setup.

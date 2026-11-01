#!/bin/sh
# ── engine-editor-cli 包装器（macOS / Linux，2026-11-01）────────────────────
# console script 通常不在 PATH（在 Python 的 bin 目录）；本包装器以模块方式调用。
#
# 用法：
#   chmod +x engine-cli.sh && ./engine-cli.sh call sim.state
#   指定解释器：FVE_PYTHON=/path/to/python3 ./engine-cli.sh ops
#
# 退出码直通（0 成功 / 1 op 或连接失败 / 2 用法错误）。
set -u
if [ -n "${FVE_PYTHON:-}" ]; then
  exec "$FVE_PYTHON" -m engine_editor_mcp.cli "$@"
fi
exec python3 -m engine_editor_mcp.cli "$@"

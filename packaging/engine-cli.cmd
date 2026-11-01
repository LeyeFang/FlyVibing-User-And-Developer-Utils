@echo off
rem ── engine-editor-cli 包装器（2026-11-01）────────────────────────────────
rem 目的：console script（engine-editor-cli.exe）装在 Python 的 Scripts 目录，
rem 通常不在 PATH 上 —— 本包装器用“当前 Python”以模块方式调用，无需改 PATH。
rem
rem 用法：
rem   把本文件所在目录加入 PATH，或直接 engine-cli.cmd call sim.state
rem   指定解释器：set FVE_PYTHON=C:\path\to\python.exe
rem
rem 退出码直通（0 成功 / 1 op 或连接失败 / 2 用法错误）。
setlocal
if defined FVE_PYTHON (
  "%FVE_PYTHON%" -m engine_editor_mcp.cli %*
) else (
  python -m engine_editor_mcp.cli %*
)
exit /b %ERRORLEVEL%

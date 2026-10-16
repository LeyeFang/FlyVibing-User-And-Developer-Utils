"""
Dev 入口 shim — 真实实现为**独立包**（单一源码）。

  实现:  packages/editor-mcp/src/engine_editor_mcp/server.py
  发布:  packages/editor-mcp（build_wheel.py → console script `engine-editor-mcp`）

本 shim 保留仓库内既有用法（`python Utils\\ExtDev\\EditorMcp\\mcp_server.py`,
或通过引擎仓库 junction 路径直接运行本文件；旧的
`python -m engine_editor_mcp.mcp_server` 写法已失效——包内无此子模块,
统一入口为 `python -m engine_editor_mcp`）,
行为与独立包完全一致。
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_PKG_SRC = os.path.join(_REPO_ROOT, "Utils", "ExtDev", "EditorMcp", "src")
if _PKG_SRC not in sys.path:
    sys.path.insert(0, _PKG_SRC)

from engine_editor_mcp.server import (  # noqa: E402,F401
    DEFAULT_PORT,
    FRAMES_DIR,
    _capture_png,
    _encode_and_save,
    _port,
    _send,
    _send_raw,
    _wipe_frames_dir,
    apply_profile,
    main,
    mcp,
)

if __name__ == "__main__":
    main()

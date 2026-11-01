"""engine_editor_mcp — MyGameEngine 编辑器实时 MCP / CLI（独立发布包）。

用法:
    python -m engine_editor_mcp [--profile lite|full] [--port N]   （或 console script: engine-editor-mcp）
    engine-editor-cli <ops|help|call|batch|exec|validate|capture|setup|launch|engines>   （终端通道）

依赖**运行中的**引擎编辑器（默认 127.0.0.1:8977; 环境变量 MGE_EDITOR_MCP_PORT
两侧设置一致可改端口）。纯 socket 客户端 — 不依赖引擎源码, 可放入任何三方项目
工作区使用（独立分发）。

v0.6.0: 双档位（lite 6 工具 / full 46 工具）+ CLI + Skill; 新增引擎启动/自动端口协商
（`launch` / `engines` / MCP `engine_launch`）; op 注册表见 ops.py。
"""

__version__ = "0.6.1"

import warnings as _warnings

# ── 启动噪声治理 (2026-11-01) ─────────────────────────────────────────────
# 导入 `mcp` → `pydantic_settings` 时，上游会对自己的内部模型发一条
# `IncompleteFieldDefinitionWarning`（`lifespan` 前向引用未解析）。它与本包行为
# 无关，却出现在**每一次** CLI / MCP 调用的 stderr 上，导致用户为了干净输出而
# `2>$null`，把真正的错误（unknown op 等）一起吞掉。只屏蔽这一条。
_warnings.filterwarnings(
    "ignore",
    message=r".*incomplete definition.*unresolved forward reference.*",
)

from .server import mcp  # noqa: E402,F401

__all__ = ["mcp", "__version__"]

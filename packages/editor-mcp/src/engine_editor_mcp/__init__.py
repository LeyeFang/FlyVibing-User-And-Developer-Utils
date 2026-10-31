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

__version__ = "0.6.0"

from .server import mcp  # noqa: E402,F401

__all__ = ["mcp", "__version__"]

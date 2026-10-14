"""flyvibing_extension_kit — 扩展作者工具包（静态审查 + 无头 GUI 测试基建）。

模块:
    review_extension  提交前静态审查（M/C 规则, 见引擎 Doc/ExtDev/extension_dev_protocol.md）
    imgui_headless    无头 imgui 上下文唯一入口（自动禁用布局持久化/ini）
"""

__all__ = ["imgui_headless", "review_extension"]
__version__ = "0.1.0"

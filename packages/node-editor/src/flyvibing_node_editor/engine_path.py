"""定位引擎源码根并注入 sys.path。

离线工具包（node-editor）的校验/静态流分析需要引擎的节点类型注册表
（`Application.Core.NodeGraph`），但 CLI 可能从任意工作目录启动。本模块按以下顺序
定位引擎根，找到后插入 `sys.path`：

  1. 环境变量 `MGE_ROOT` / `FLYVIBING_ENGINE_ROOT`
  2. 从本包文件向上查找（部署副本位于引擎树内时命中）
  3. 从当前工作目录向上查找

找不到时返回 None，调用方自行决定报错方式。
"""

from __future__ import annotations

import os
import sys

_MARK = os.path.join("Application", "Core", "NodeGraph")


def _is_engine_root(path: str | None) -> bool:
    return bool(path) and os.path.isdir(os.path.join(path, _MARK))


def _walk_up(start: str):
    cur = os.path.abspath(start)
    while cur:
        yield cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent


def ensure_engine_importable() -> str | None:
    """确保 `import Application...` 可用；返回检测到的引擎根（找不到为 None）。"""
    try:
        import Application  # noqa: F401
        origin = getattr(Application, "__file__", None)
        if origin:
            return os.path.dirname(os.path.dirname(os.path.abspath(origin)))
        for loc in (getattr(Application, "__path__", None) or []):
            return os.path.dirname(os.path.abspath(loc))
        return None
    except ImportError:
        pass

    candidates: list[str] = []
    for env_name in ("MGE_ROOT", "FLYVIBING_ENGINE_ROOT"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    # 引擎 venv（<engine>/.venv-py314t）或运行时镜像内的解释器
    candidates.extend(_walk_up(sys.prefix))
    candidates.extend(_walk_up(os.path.dirname(os.path.abspath(sys.executable))))
    candidates.extend(_walk_up(os.path.dirname(os.path.abspath(__file__))))
    candidates.extend(_walk_up(os.getcwd()))

    for cand in candidates:
        if _is_engine_root(cand):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            return cand
    return None

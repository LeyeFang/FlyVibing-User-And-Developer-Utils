"""Engine launcher — MCP / CLI 共用的“启动引擎 + 端口协商”实现。

设计目标（多引擎 / 多 agent）:
  - 启动前在 8977..9076 频段选一个空闲端口，显式传给引擎 `--port`；
  - 启动后等待 `sim.state` 握手，返回实际端口；MCP 进程将该端口设为后续 op 的默认端口；
  - 引擎设置面板的 `server.port` 仍可作为手动启动的默认值；环境变量
    `MGE_EDITOR_MCP_PORT` 的优先级更高（两侧一致即可）。
  - `engines()` 扫描同一频段，供 CLI 发现已运行实例；每个 agent 使用自己的端口，
    避免两个编辑器/两个 agent 互相串话。

不依赖引擎源码；引擎根目录通过 `--engine-root` / `MGE_ENGINE_ROOT` / 向上查找
`startup.bat` 确定。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from .client import DEFAULT_PORT, send_raw

PORT_RANGE_START = DEFAULT_PORT          # 8977
PORT_RANGE_END = DEFAULT_PORT + 99      # 9076
_ENV_ENGINE_ROOT = "MGE_ENGINE_ROOT"
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_ENV_NO_PAUSE = "MGE_NO_PAUSE"
_LOG_ROOT = os.path.join(tempfile.gettempdir(), "engine_editor_mcp", "engines")


class LaunchError(RuntimeError):
    """启动失败（找不到引擎根目录 / 端口占用 / 进程提前退出 / 握手超时）。"""


def _looks_like_engine(root: Path) -> bool:
    return (root / "startup.bat").is_file() and (root / "Application" / "EntryPoint.py").is_file()


def find_engine_root(explicit: str | None = None) -> Path:
    """定位引擎根目录（含 startup.bat 与 Application/EntryPoint.py）。

    优先级: explicit > MGE_ENGINE_ROOT > 当前目录向上查找。
    找不到时抛 LaunchError，并提示 `--engine-root`。
    """
    candidates: list[Path] = []
    explicit_text = (explicit or "").strip()
    if explicit_text and explicit_text.lower() != "auto":
        root = Path(explicit_text).expanduser()
        try:
            root = root.resolve()
        except OSError:
            root = Path(explicit_text)
        if not _looks_like_engine(root):
            raise LaunchError(
                f"not an engine root: {explicit_text!r} "
                "(need startup.bat + Application/EntryPoint.py)"
            )
        return root
    env_root = os.environ.get(_ENV_ENGINE_ROOT, "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    here = Path.cwd().resolve()
    candidates.extend([here, *here.parents])
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except OSError:
            continue
        if _looks_like_engine(root):
            return root
    raise LaunchError(
        "engine root not found (need startup.bat + Application/EntryPoint.py) — "
        "pass --engine-root DIR or set MGE_ENGINE_ROOT"
    )


def is_port_free(port: int) -> bool:
    """本机回环端口是否可绑定；已在监听的端口视为占用。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.15):
            return False
    except (ConnectionRefusedError, socket.timeout, TimeoutError):
        pass
    except OSError:
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def choose_port(preferred: int | str | None = None,
                start: int = PORT_RANGE_START, end: int = PORT_RANGE_END) -> int:
    """选择端口: preferred=None/"auto" → 频段内首个空闲; 指定端口 → 必须空闲。"""
    if preferred is None or str(preferred).strip().lower() in ("", "auto"):
        for port in range(int(start), int(end) + 1):
            if is_port_free(port):
                return port
        raise LaunchError(f"no free editor port in {start}..{end}")
    try:
        port = int(preferred)
    except (TypeError, ValueError) as e:
        raise LaunchError(f"invalid port: {preferred!r} (use auto or 1024..65535)") from e
    if not (1024 <= port <= 65535):
        raise LaunchError(f"port must be 1024..65535, got {port}")
    if not is_port_free(port):
        raise LaunchError(f"port {port} is already in use — choose another port or use --port auto")
    return port


def _build_settings(settings: dict | None, port: int, language: str | None) -> dict:
    merged = dict(settings or {})
    merged["server.port"] = int(port)
    if language:
        merged["ui.language"] = str(language)
    return merged


def _tail(path: Path, limit: int = 20) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _wait_ready(port: int, proc: subprocess.Popen, timeout_s: float) -> dict:
    deadline = time.monotonic() + max(0.5, float(timeout_s))
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return {"ready": False, "error": f"engine exited with code {proc.returncode}",
                    "returncode": proc.returncode}
        result, _payload = send_raw("sim.state", {}, timeout=0.5, port=port)
        if "error" not in result:
            return {"ready": True, "state": result.get("state"),
                    "runtime_alive": result.get("runtime_alive")}
        last_error = str(result.get("error", ""))
        time.sleep(0.2)
    return {"ready": False, "timeout": True, "error": last_error or "engine handshake timeout"}


def launch_engine(
    engine_root: str | None = None,
    port: int | str | None = "auto",
    language: str | None = None,
    settings: dict | None = None,
    timeout_s: float = 30.0,
) -> dict:
    """启动一个独立的编辑器实例并等待命令总线就绪。

    Returns:
        {"ok": true, "port": N, "pid": ..., "engine_root": ..., "ready": true,
         "state": ..., "log_path": ..., "command": [...]}
        失败会抛 LaunchError（CLI/MCP 捕获后返回 error）。
    """
    if language is not None and language not in ("en", "zh"):
        raise LaunchError(f"language must be en or zh, got {language!r}")
    root = find_engine_root(engine_root)
    chosen = choose_port(port)
    merged = _build_settings(settings, chosen, language)

    log_dir = Path(_LOG_ROOT)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"engine_{chosen}_{os.getpid()}_{stamp}.log"
    settings_path = log_dir / f"engine_{chosen}_{os.getpid()}_{stamp}_settings.json"
    settings_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    log_file = open(log_path, "a", encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env[_ENV_NO_PAUSE] = "1"
    env[_ENV_PORT] = str(chosen)
    command = [str(root / "startup.bat"), "--port", str(chosen),
               "--settings", f"@{settings_path}"]
    popen_args: list[str]
    if os.name == "nt":
        popen_args = ["cmd", "/c", *command]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        popen_args = command
        creationflags = 0
    try:
        proc = subprocess.Popen(
            popen_args,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError as e:
        log_file.close()
        raise LaunchError(f"cannot start engine: {e}") from e
    finally:
        # Popen 已复制句柄；父进程不需要继续持有写端。
        log_file.close()

    ready = _wait_ready(chosen, proc, timeout_s)
    result = {
        "ok": bool(ready.get("ready")),
        "port": chosen,
        "pid": proc.pid,
        "engine_root": str(root),
        "ready": bool(ready.get("ready")),
        "state": ready.get("state"),
        "runtime_alive": ready.get("runtime_alive"),
        "log_path": str(log_path),
        "settings_path": str(settings_path),
        "command": command,
        "settings": merged,
    }
    if not result["ok"]:
        result["error"] = ready.get("error") or "engine did not become ready"
        result["log_tail"] = _tail(log_path)
        if proc.poll() is None:
            # 仍存活但握手超时：不杀进程，留下端口/日志让用户诊断；MCP/CLI 返回可操作错误。
            result["hint"] = "engine process still running; inspect log_path or retry with a larger --timeout"
        raise LaunchError(json.dumps(result, ensure_ascii=False))
    return result


def discover_engines(start: int = PORT_RANGE_START, end: int = PORT_RANGE_END,
                     timeout: float = 0.25) -> list[dict]:
    """扫描端口频段，返回能响应 `sim.state` 的编辑器实例（升序）。"""
    found: list[dict] = []
    for port in range(int(start), int(end) + 1):
        result, _payload = send_raw("sim.state", {}, timeout=timeout, port=port)
        if "error" in result:
            continue
        found.append({
            "port": port,
            "state": result.get("state"),
            "runtime_alive": result.get("runtime_alive"),
        })
    return found


__all__ = [
    "LaunchError",
    "PORT_RANGE_START",
    "PORT_RANGE_END",
    "choose_port",
    "discover_engines",
    "find_engine_root",
    "is_port_free",
    "launch_engine",
]

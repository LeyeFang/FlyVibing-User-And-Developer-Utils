"""Port ledger — 本机开发实例的端口台账（读 / 登记 / 冲突说明）。

与引擎 `Application/Editor/Services/PortLedger.py` 共用**同一容器格式**（schema 1）与
同一目录（系统临时目录下的 `engine_editor_mcp/ports/<port>.json`），一侧写、另一侧读。
格式与纪律见 `docs_content/dev/editor_live_protocol.md`（§2.2 端口台账）。

为什么需要:
  端口被占时后来者只看到「连不上」，只能靠频段硬撞 —— 冲突暴露得太晚（两个 agent 抢同一个
  工程 / 同一个 PIE 窗口）。台账把「谁 / 为什么 / 会碰什么」写在端口旁边，选端口前就能躲。

三条使用路径:
  1. agent 启动前: `engine-editor-cli ports` → 看到每个被占端口的 purpose / owner / project；
  2. `launch --purpose ...` → 启动前先写 `status=starting`，启动后引擎改写为 `ready`；
  3. 其它开发工具（web 预览、调试代理等）: `register(port, kind="devtool", purpose=...)`，
     退出时 `unregister(port, pid=os.getpid())`。

判活规则（读者侧，不依赖 psutil）:
  - 端口在监听 → 占用（有条目则用条目描述，没有则 `occupied`）；
  - 端口空闲但条目存在 → `stale`；若 `status=starting` 且 3 分钟内更新过 → `reserved`
    （另一进程正在启动，`choose_port` 会跳过，避免抢占）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

SCHEMA = 1

_ENV_DIRS = ("FVE_PORT_LEDGER_DIR", "MGE_PORT_LEDGER_DIR")     # 新名优先
_ENV_OFF = ("FVE_PORT_LEDGER", "MGE_PORT_LEDGER")
_SUBDIR = "engine_editor_mcp"
_PORTS_SUBDIR = "ports"
_RESERVE_TTL_S = 180.0          # `status=starting` 条目的有效期


# ── 环境 / 路径 ─────────────────────────────────────────────


def ledger_enabled() -> bool:
    for name in _ENV_OFF:
        raw = (os.environ.get(name) or "").strip().lower()
        if raw:
            return raw not in ("0", "false", "off", "no")
    return True


def ledger_dir() -> Path:
    for name in _ENV_DIRS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw) / _PORTS_SUBDIR
    return Path(tempfile.gettempdir()) / _SUBDIR / _PORTS_SUBDIR


def entry_path(port: int) -> Path:
    return ledger_dir() / f"{int(port)}.json"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ── 单条读写 ────────────────────────────────────────────────


def read_entry(port: int) -> dict | None:
    """读某端口的台账条目（不存在 / 损坏 / schema 不符 → None）。"""
    try:
        with open(entry_path(port), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    return data


def list_entries() -> list[dict]:
    """列出全部台账条目（按端口升序；坏文件跳过）。"""
    directory = ledger_dir()
    if not directory.is_dir():
        return []
    entries: list[dict] = []
    for path in directory.glob("*.json"):
        if not path.stem.isdigit():
            continue
        entry = read_entry(int(path.stem))
        if entry:
            entries.append(entry)
    entries.sort(key=lambda e: int(e.get("port") or 0))
    return entries


def write_entry(entry: dict) -> Path | None:
    """原子写一条台账（临时文件 + os.replace，读者不会读到半截 JSON）。"""
    if not ledger_enabled():
        return None
    payload = dict(entry)
    payload["schema"] = SCHEMA
    payload["updated_at"] = _now_iso()
    target = entry_path(int(payload["port"]))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return None
    return target


def remove_entry(port: int, pid: int | None = None) -> bool:
    """删除台账；给 pid 时只删自己的（pid 缺失的条目按「无主」处理）。"""
    if pid is not None:
        current = read_entry(port)
        if current is None or int(current.get("pid") or 0) not in (0, int(pid)):
            return False
    try:
        entry_path(port).unlink()
        return True
    except OSError:
        return False


def register(port: int, *, kind: str = "devtool", status: str = "ready",
             purpose: str = "", owner: str = "", tags=(), touches=(), notes: str = "",
             extra: dict | None = None) -> dict | None:
    """登记一个端口（启动时调用；`kind` 取 `editor` / `devtool` / 其它自定值）。"""
    port = int(port or 0)
    if port <= 0 or not ledger_enabled():
        return None
    previous = read_entry(port) or {}
    entry = {
        "port": port,
        "kind": kind,
        "status": status,
        "pid": os.getpid(),
        "started_at": previous.get("started_at") or _now_iso(),
        "purpose": purpose or previous.get("purpose", ""),
        "owner": owner or previous.get("owner", ""),
        "tags": list(tags) if tags else list(previous.get("tags") or []),
        "touches": list(touches) if touches else list(previous.get("touches") or []),
        "notes": notes or previous.get("notes", ""),
    }
    entry.update(extra or {})
    write_entry(entry)
    return entry


def unregister(port: int, pid: int | None = None) -> bool:
    return remove_entry(port, pid=pid if pid is not None else os.getpid())


# ── 端口探测 ────────────────────────────────────────────────


def is_port_free(port: int, timeout: float = 0.15) -> bool:
    """回环端口是否可绑定（已在监听 → 占用；bind 失败 → 占用）。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
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


def _age_seconds(entry: dict) -> float | None:
    """条目 `updated_at` 距今秒数（解析失败 → None）。"""
    raw = entry.get("updated_at") or entry.get("started_at")
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now().astimezone() - stamp).total_seconds())


def is_reserved(port: int) -> bool:
    """端口是否被「正在启动」的实例预占（端口还没监听，但选端口时应跳过）。"""
    entry = read_entry(port)
    if not entry or entry.get("status") != "starting":
        return False
    age = _age_seconds(entry)
    return age is None or age <= _RESERVE_TTL_S


# ── 扫描 / 描述 ─────────────────────────────────────────────


def _listening_pids() -> dict[int, int]:
    """一次 `netstat` 拿到 {监听端口: pid}（Windows）；拿不到 → 空表。

    只在存在「未登记占用」时才调用（最多 1 次/扫描），避免拖慢正常路径。
    """
    if os.name != "nt":
        return {}
    try:
        # 按字节收、再宽松解码: Windows 控制台代码页不一定是 UTF-8（netstat 输出近全 ASCII）
        raw = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             timeout=8.0).stdout or b""
    except (OSError, subprocess.SubprocessError):
        return {}
    mapping: dict[int, int] = {}
    for line in raw.decode("ascii", "replace").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        try:
            mapping[int(local.rsplit(":", 1)[1])] = int(parts[4])
        except (TypeError, ValueError):
            continue
    return mapping


def _process_name(pid: int) -> str:
    """进程名（Windows: tasklist 单次查询；失败 → 空串）。"""
    if not pid or os.name != "nt":
        return ""
    try:
        raw = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=5.0).stdout or b""
    except (OSError, subprocess.SubprocessError):
        return ""
    out = raw.decode("mbcs", "replace").strip()
    first = out.splitlines()[0] if out else ""
    return first.split('","')[0].strip('"') if first.startswith('"') else ""


def _unknown_summary(pid: int | None) -> str:
    if pid:
        name = _process_name(pid)
        if name:
            return f"未登记进程占用（{name} pid {pid}）"
        return f"未登记进程占用（pid {pid}）"
    return "未登记进程占用（非本工具链启动 / 台账被清理）"


def describe(entry: dict) -> str:
    """一行人类可读描述（错误信息 / 表格用）。"""
    bits: list[str] = []
    kind = entry.get("kind") or "unknown"
    pid = entry.get("pid")
    bits.append(f"{kind} pid {pid}" if pid else str(kind))
    if entry.get("purpose"):
        bits.append(f"「{entry['purpose']}」")
    if entry.get("owner"):
        bits.append(f"@{entry['owner']}")
    project = entry.get("project_name") or ""
    if project:
        bits.append(f"工程 {project}")
    age = _age_seconds(entry)
    if age is not None:
        bits.append(f"{int(age // 60)}m 前" if age >= 60 else f"{int(age)}s 前")
    return " · ".join(bits)


def scan(start: int, end: int, *, timeout: float = 0.08,
         include_free: bool = False) -> list[dict]:
    """扫描端口频段 → 每个端口的占用状况与台账描述。

    返回项: `{"port", "state": free|editor|occupied|reserved|stale, "entry": dict|None,
    "summary": str}`；默认只返回非 free 的端口（agent 只关心谁占了）。
    """
    rows: list[dict] = []
    listeners: dict[int, int] | None = None       # 惰性: 只有未登记占用才查
    for port in range(int(start), int(end) + 1):
        entry = read_entry(port)
        if is_port_free(port, timeout=timeout):
            if entry is None:
                if include_free:
                    rows.append({"port": port, "state": "free", "entry": None, "summary": "空闲"})
                continue
            state = "reserved" if is_reserved(port) else "stale"
            rows.append({"port": port, "state": state, "entry": entry, "summary": describe(entry)})
            continue
        if entry is not None:
            state = "editor" if (entry.get("kind") or "editor") == "editor" else "occupied"
            summary = describe(entry)
        else:
            state = "occupied"
            if listeners is None:
                listeners = _listening_pids()
            pid = listeners.get(port)
            summary = _unknown_summary(pid)
            rows.append({"port": port, "state": state, "entry": None, "summary": summary,
                         "pid": pid})
            continue
        rows.append({"port": port, "state": state, "entry": entry, "summary": summary})
    return rows


def holder_hint(port: int) -> str:
    """端口冲突时的一句话说明（没有台账 → 提示是未登记进程）。"""
    entry = read_entry(port)
    if not entry:
        return f"port {port} is in use by an unregistered process"
    return f"port {port} is in use by {describe(entry)}"


__all__ = [
    "SCHEMA",
    "describe",
    "entry_path",
    "holder_hint",
    "is_port_free",
    "is_reserved",
    "ledger_dir",
    "ledger_enabled",
    "list_entries",
    "read_entry",
    "register",
    "remove_entry",
    "scan",
    "unregister",
    "write_entry",
]

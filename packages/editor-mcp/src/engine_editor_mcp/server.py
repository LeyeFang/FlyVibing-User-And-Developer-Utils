"""
Engine Editor Live MCP — 运行中编辑器的热注入工具（v0.5.0: 双档位 + CLI/Skill + 自动启动/端口协商）。

档位（--profile lite|full > env MGE_MCP_PROFILE > 默认 full）:
  lite（推荐, 省 token — 6 个工具）:
    engine_help(op|topic)        → op 目录 / 单 op 详情 / 主题帮助（按需读取, 不常驻）
    engine_call(op, args)        → 执行 1 个 op（兼容旧工具名; 大载荷自动瘦身）
    engine_batch(calls)          → 一次调用顺序执行多个 op
    engine_validate_graph(...)   → 图干跑校验（detail=summary 默认）
    engine_capture(target)       → 抓帧（图像直回; 想省 token 用 CLI capture）
    engine_launch(...)           → 启动引擎 + 自动端口握手（MCP 进程随后使用该端口）
  full（兼容旧用法 — 45 个 editor_* 工具 + engine_launch, 见下）:
    editor_run_pie / editor_stop_pie / editor_sim_state  → PIE 启停与状态
    editor_switch_2d / editor_set_scene_type             → 场景类型按钮语义（影响 PIE 摄像机）
    editor_camera_get / editor_camera_set                → 场景摄像机读写（3d / 2d / overlay）
    editor_graph_validate(_report/_cancel)               → 节点图干跑校验（引擎内服务: 静态+模拟）
    editor_graph_export / editor_graph_import            → 节点图 JSON 导入导出（含 _rules 文档）
    editor_project_open                                  → 打开 .myproj 工程（资源+场景全加载）
    editor_capture                                       → 抓帧（editor / pie 窗口）→ PNG + 图片返回
    editor_quit                                          → 请求关闭编辑器引擎
    （含 entity/selection/component/scene/resource 容器级工具）

原理（详见 Doc/Dev/editor_live_protocol.md）:
    MCP(stdio) → 本工具 → 本机回环 TCP 127.0.0.1:8977
    → 编辑器 LiveCommandServer → 主线程 pump 执行（复用编辑器按钮同款 API）。
    帧图像 = NDJSON 回执行 + 二进制尾随帧（binary_bytes=N ⇒ 行后紧跟 N 字节 RGBA8）。
    PNG 编码在本进程完成（不阻塞引擎）; 抓帧文件: <临时目录>/engine_editor_mcp/frames
    （MGE_MCP_FRAMES_DIR 可覆盖; 仅入口进程启动时清空）。
编辑器未运行时工具返回明确错误（先启动 startup.bat）。

独立分发的三种消费形态（同一 wheel, 同一 op 注册表 ops.py）:
    CLI（零常驻上下文成本, 任意终端型 agent 首选）: engine-editor-cli
    MCP lite / full: python -m engine_editor_mcp --profile lite|full
    Skill（渐进披露）: engine-editor-cli setup --workspace <项目目录> --target auto

dev 仓库内等价入口: python Utils\\ExtDev\\EditorMcp\\mcp_server.py （薄 shim, 同一源码）
"""

import asyncio
import inspect
import io
import json
import os
import sys

from mcp.server.fastmcp import FastMCP, Image

from . import ops as op_registry
from .client import (
    DEFAULT_PORT,
    FRAMES_DIR,
    EngineError,
    capture_png,
    editor_port,
    encode_and_save,
    execute_calls,
    send,
    send_raw,
    validate_graph_orchestrate,
    wipe_frames_dir,
)

# 供 dev shim（packages/editor-mcp/mcp_server.py）与外部集成（E2E 脚本）复用的符号
# （v0.4.0: 底层实现移至 client.py — 名称与行为保持不变）
__all__ = [
    "mcp",
    "FRAMES_DIR",
    "DEFAULT_PORT",
    "_send",
    "_send_raw",
    "_port",
    "_capture_png",
    "_encode_and_save",
    "_wipe_frames_dir",
    "apply_profile",
    "main",
]

mcp = FastMCP("Engine Editor Live", version="0.6.0")

# ── 低层函数（v0.4.0 起实现位于 client.py; 此处保留模块级名以兼容 shim / E2E 脚本）──

_send = send
_send_raw = send_raw
_capture_png = capture_png
_encode_and_save = encode_and_save


def _port() -> int:
    return editor_port()


# ── 阻塞调用的返回点纪律（2026-11-16）─────────────────────────
# FastMCP 对同步工具是**在事件循环里直接调用**的：一次卡住的抓帧/op 会把整个
# stdio 服务器冻住（别的工具、甚至协议层 ping 都排不上队），agent 会话表现为
# "工具不给结果"。所以所有可能阻塞的工具都改为: 丢到 worker 线程 + 硬超时。


class _DeadlineExceeded(RuntimeError):
    """worker 线程超过预算仍未返回 — 放弃等待，把结论交还给调用方。"""


async def _offload(fn, budget: float, *args, **kwargs):
    """在 worker 线程执行阻塞调用，最多等 budget 秒。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs), timeout=max(0.5, float(budget))
        )
    except asyncio.TimeoutError as exc:
        raise _DeadlineExceeded(f"{getattr(fn, '__name__', 'call')} 超过 {budget:g}s 未返回") from exc


def _batch_budget(calls: list) -> float:
    """批量预算 = 各 op 超时之和 + 余量（封顶 20 分钟）。"""
    total = 5.0
    for call in calls or []:
        try:
            name = str(call.get("op", "")) if isinstance(call, dict) else str(call[0])
        except Exception:  # noqa: BLE001 — 形状错就让执行体自己报错
            continue
        total += op_registry.call_timeout(op_registry.resolve(name)[0] or name)
    return min(total, 1200.0)


def _wipe_frames_dir() -> None:
    """清空抓帧目录（server 启动时调用 — 仅入口进程执行；import 不清空）。"""
    wipe_frames_dir()


# ════════════════════════════════════════════════════════════════
# v4: 图校验（引擎内服务） / 图导入导出 / 工程打开
# ════════════════════════════════════════════════════════════════

_LOG_CAP = 500


def _trim_report(report: dict) -> dict:
    """报告瘦身（MCP 回传用）: log 超过 _LOG_CAP 条则截断 + 标记。"""
    if not isinstance(report, dict):
        return report
    log = report.get("log")
    if isinstance(log, list) and len(log) > _LOG_CAP:
        report = dict(report)
        report["log_total"] = len(log)
        report["log_truncated"] = True
        report["log"] = log[:_LOG_CAP]
    return report


def _validate_orchestrate(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    dt: float = 0.0,
    verbose: bool = True,
    seed: int = 0,
    realtime: bool = False,
    allow_long: bool = False,
    save_path: str | None = None,
    timeout_s: float = 120.0,
) -> dict:
    """校验编排（start→poll→report）— 实现位于 client.py（MCP 工具与 CLI validate 共用）。"""
    return validate_graph_orchestrate(
        source=source,
        graph=graph,
        frames=frames,
        dt=dt,
        verbose=verbose,
        seed=seed,
        realtime=realtime,
        allow_long=allow_long,
        save_path=save_path,
        timeout_s=timeout_s,
    )


@mcp.tool()
async def editor_graph_validate(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    verbose: bool = True,
    seed: int = 0,
    save_path: str | None = None,
    timeout_s: float = 120.0,
) -> dict:
    """干跑校验节点图（引擎内服务: 静态检查 + fake-time 模拟, 需要引擎运行中）。

    提示: lite 档的 engine_validate_graph 默认只回摘要（省 token）— 本工具回全量报告。
    Args:
        source: "canvas"（当前编辑器画布快照, 默认）| "graph"（直接传 graph dict, agent 生成图先验）
        graph:  仅 source="graph" 时必填
        frames: 模拟帧数（默认 360 = 6s @60fps）
        seed:   随机种子（确定性干跑, 默认 0）
        save_path: 可选 — 报告落盘路径（.json / .txt）

    Returns:
        {found, report: {ok, state, counts, static, runtime, log: [...], graph}, saved_path?}
        或 {"error": ...}（引擎未运行）
    """
    try:
        result = await _offload(_validate_orchestrate, timeout_s + 30.0, source, graph, frames,
                                verbose, seed, save_path, timeout_s)
    except _DeadlineExceeded as e:
        return {"error": str(e), "error_code": "timeout"}
    if "error" in result or not isinstance(result.get("report"), dict):
        return result
    result = dict(result)
    result["report"] = _trim_report(result["report"])
    return result


@mcp.tool()
def editor_graph_validate_report(task_id: int | None = None, save_path: str | None = None) -> dict:
    """取回已完成的校验报告（task_id 省略 → 最新一份; save_path 落盘 .json/.txt）。"""
    args: dict = {}
    if task_id is not None:
        args["task_id"] = task_id
    if save_path:
        args["save_path"] = save_path
    result = _send("graph.validate.report", args)
    if "error" in result:
        return result
    result["report"] = _trim_report(result.get("report") or {})
    return result


@mcp.tool()
def editor_graph_validate_cancel(task_id: int | None = None) -> dict:
    """取消正在运行的校验任务（帧间生效）。"""
    args: dict = {}
    if task_id is not None:
        args["task_id"] = task_id
    return _send("graph.validate.cancel", args)


# ════════════════════════════════════════════════════════════════
# v3: 实体 / 选中 / 组件 / 场景 / 资源（编辑器的容器级操作）
# ════════════════════════════════════════════════════════════════


@mcp.tool()
async def editor_capture(target: str = "editor", timeout_s: float = 6.0):
    """抓取窗口帧图像 → PNG 存 <临时目录>/engine_editor_mcp/frames/ 并返回画面。

    引擎侧只做 glReadPixels（渲染线程帧末）; PNG 编码在本进程（不阻塞引擎）。
    整条链路有硬预算：无论引擎/窗口处于什么状态都会返回结论（成功或明确错误）。

    Args:
        target: "editor"（编辑器窗口）或 "pie"（运行时窗口, 需 PIE 运行中）
        timeout_s: 等待渲染线程完成抓帧的上限（秒）
    Returns:
        [图像内容块, 说明文本（含文件路径/尺寸）] — agent 可直接查看画面。
    """
    try:
        path, png_bytes = await _offload(_capture_png, timeout_s + 5.0, target, timeout_s)
    except (_DeadlineExceeded, RuntimeError) as e:
        raise ValueError(f"capture failed: {e}") from e
    return [Image(data=png_bytes, format="png"), f"saved: {path}"]


# ════════════════════════════════════════════════════════════════
# v0.5.0: 档位（profile）— lite 精简工具集 / full 兼容旧工具集
#   选择: 启动参数 --profile lite|full > env MGE_MCP_PROFILE > 默认 full
#   lite 目标: 旧 45×schema（约 17.9k 字符常驻）→ 6×schema（约 3.3k 字符）;
#   完整 op 参考按需获取（engine_help / CLI / Skill），不再常驻上下文。
# ════════════════════════════════════════════════════════════════

_ENV_PROFILE = "MGE_MCP_PROFILE"
LITE_TOOL_NAMES = (
    "engine_help",
    "engine_call",
    "engine_batch",
    "engine_validate_graph",
    "engine_capture",
    "engine_launch",
)
# 同时保留在 full 档的新工具（full 只排除 lite 专属工具，不排除共享工具）
_SHARED_TOOL_NAMES = ("engine_launch",)

_HELP_TOPICS = op_registry.TOPIC_HELP  # 主题帮助的单一事实源位于 ops.py（CLI 同用）


def _requested_profile(argv: list[str] | None = None) -> str:
    """档位解析: --profile[-=] 参数 > env > 默认 full。"""
    args = list(sys.argv[1:] if argv is None else argv)
    value = ""
    for i, a in enumerate(args):
        if a == "--profile" and i + 1 < len(args):
            value = args[i + 1]
            break
        if a.startswith("--profile="):
            value = a.split("=", 1)[1]
            break
    if not value:
        value = os.environ.get(_ENV_PROFILE, "")
    return "lite" if value.strip().lower() == "lite" else "full"


def apply_profile(profile: str) -> str:
    """按档位裁剪工具集（幂等 — 可在任意当前档切到另一档; 返回实际档位）。

    lite → 仅保留 LITE_TOOL_NAMES; full → 移除 lite 专属工具（保留旧 45 工具集 + 共享 engine_launch）。
    内部结构不可用时 fail-open（保留全部并告警）。
    """
    profile = "lite" if str(profile).strip().lower() == "lite" else "full"
    try:
        tools = mcp._tool_manager._tools  # mcp>=1.10 FastMCP 内部注册表
    except AttributeError:
        print(
            f"[engine-editor-mcp] WARNING: tool filter unavailable — profile {profile!r} not applied",
            file=sys.stderr,
        )
        return profile
    if not _ALL_TOOL_OBJECTS:
        print(
            f"[engine-editor-mcp] WARNING: tool master table empty — profile {profile!r} not applied",
            file=sys.stderr,
        )
        return profile
    tools.clear()
    if profile == "lite":
        tools.update({n: t for n, t in _ALL_TOOL_OBJECTS.items() if n in LITE_TOOL_NAMES})
    else:
        tools.update({n: t for n, t in _ALL_TOOL_OBJECTS.items()
                      if n not in LITE_TOOL_NAMES or n in _SHARED_TOOL_NAMES})
    return profile


# 共享辅助（prepare_args / call_timeout / unknown_args / trim_result / summarize_report）
# 位于 ops.py（CLI 与 lite MCP 共用单一实现）。


@mcp.tool()
def engine_help(op: str = "") -> str:
    """Op 目录（无参）/ 单 op 详情 / 主题（mcp, cli, probe, exitcodes, skill, capture）。按需读取，不常驻上下文。"""
    topic = (op or "").strip()
    if not topic or topic in ("ops", "all"):
        return op_registry.format_ops_list()
    if topic in _HELP_TOPICS:
        return _HELP_TOPICS[topic]
    return op_registry.format_op_help(topic)


@mcp.tool()
async def engine_call(op: str, args: dict | None = None, detail: str = "auto") -> dict:
    """执行一个编辑器 op（名字见 engine_help()）; 兼容旧工具名（editor_run_pie 等）。detail='full' 关闭自动瘦身。"""
    name, defaults = op_registry.resolve(op)
    if not name:
        return {"error": f"unknown op: {op!r}", "hint": "engine_help() 获取 op 目录"}
    call_args = dict(defaults)
    call_args.update(args or {})
    call_args = op_registry.prepare_args(name, call_args)

    def _do() -> dict:
        result = _send(name, call_args, timeout=op_registry.call_timeout(name))
        unknown = op_registry.unknown_args(name, call_args)
        if unknown and isinstance(result, dict) and "error" not in result:
            result = dict(result)
            result["_unknown_args"] = unknown
        return result

    try:
        result = await _offload(_do, op_registry.call_timeout(name) + 5.0)
    except _DeadlineExceeded as e:
        return {"error": f"{name}: {e}", "error_code": "timeout"}
    return op_registry.trim_result(name, result, detail)


@mcp.tool()
async def engine_batch(calls: list[dict], continue_on_error: bool = False) -> dict:
    """一次调用顺序执行多个 op（省往返）: calls=[{"op": "entity.add", "args": {...}}, ...]。出错默认中断。"""
    try:
        results = await _offload(execute_calls, _batch_budget(calls), calls, continue_on_error)
    except _DeadlineExceeded as e:
        return {"error": str(e), "error_code": "timeout", "results": []}
    return {"count": len(results), "results": results}


@mcp.tool()
async def engine_validate_graph(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    dt: float = 0.0,
    verbose: bool = False,
    seed: int = 0,
    realtime: bool = False,
    allow_long: bool = False,
    save_path: str | None = None,
    detail: str = "summary",
    timeout_s: float = 120.0,
) -> dict:
    """干跑校验节点图（静态 + 模拟; 需引擎运行中）。

    默认 fake-time；`realtime=True` 走 wall-clock 实速以暴露调度抖动。
    detail='summary'（默认）省 token; 'full' 完整报告。报告始终带 `timebase`（含两种模式提示）。
    """
    try:
        result = await _offload(_validate_orchestrate, timeout_s + 30.0, source, graph, frames,
                                dt, verbose, seed, realtime, allow_long, save_path, timeout_s)
    except _DeadlineExceeded as e:
        return {"error": str(e), "error_code": "timeout"}
    if "error" in result:
        return result
    report = result.get("report")
    if isinstance(report, dict):
        result = dict(result)
        if detail == "full":
            result["report"] = _trim_report(report)
        else:
            result["report"] = op_registry.summarize_report(report)
    return result


@mcp.tool()
async def engine_capture(target: str = "editor", timeout_s: float = 6.0):
    """抓取窗口帧图像 → PNG 落盘 + 图像直回（agent 可直接看到画面）。target: "editor" / "pie"。

    有硬预算：窗口最小化/引擎阻塞时会在几秒内返回明确错误，不会挂住整个会话。
    """
    try:
        path, png_bytes = await _offload(_capture_png, timeout_s + 5.0, target, timeout_s)
    except (_DeadlineExceeded, EngineError) as e:
        raise ValueError(f"capture failed: {e}") from e
    return [Image(data=png_bytes, format="png"), f"saved: {path}"]


@mcp.tool()
async def engine_launch(
    engine_root: str | None = None,
    port: str | int = "auto",
    language: str | None = None,
    settings: dict | None = None,
    timeout_s: float = 30.0,
    describe: dict | None = None,
) -> dict:
    """启动一个编辑器实例并等待命令总线就绪（多引擎/多 agent 自动端口协商）。

    Args:
        engine_root: 引擎根目录（省略 → env MGE_ENGINE_ROOT 或当前目录向上查找）
        port: "auto"（默认，8977..9076 首个空闲）或固定端口
        language: "en" / "zh"（省略用 Settings 当前值）
        settings: 与 Settings 面板同键的覆盖，如 {"ui.font_scale": 1.15}
        timeout_s: 等待就绪秒数
        describe: 实例自述（写端口台账，其它 agent 查端口时可见）—
                  {purpose, owner, tags, touches, notes}; 也可事后 engine_call instance.describe

    成功后本 MCP 进程的后续 engine_call/batch/capture 自动使用返回的 port。
    启动前建议先看 `engine-editor-cli ports`，能复用已有实例就不要另起。
    """
    from .launcher import LaunchError, launch_engine
    meta = dict(describe or {})
    unknown = sorted(set(meta) - {"purpose", "owner", "tags", "touches", "notes"})
    if unknown:
        return {"ok": False, "error": "bad_describe", "detail": f"unknown keys: {unknown}"}
    try:
        result = await _offload(launch_engine, timeout_s + 30.0, engine_root, port, language,
                                settings, timeout_s, **meta)
    except LaunchError as e:
        try:
            payload = json.loads(str(e))
        except ValueError:
            payload = {"ok": False, "error": str(e)}
        return payload
    except _DeadlineExceeded as e:
        return {"ok": False, "error": "timeout", "detail": str(e)}
    os.environ["MGE_EDITOR_MCP_PORT"] = str(result["port"])
    return result


# ════════════════════════════════════════════════════════════════
# full 档旧工具 — 由 op 注册表生成（server 不再是第二份工具定义）
#   名字/参数/转发目标来自 ops.py; 这里只负责把 ToolSpec 变成 FastMCP 工具。
#   特例（抓帧 / 校验编排）仍手写：它们不是单个 op 的直传。
# ════════════════════════════════════════════════════════════════


def _assign_arg(args: dict, path: str, value) -> None:
    """按参数路径写入；`from.node` 这类路径组装嵌套 dict。"""
    if "." not in path:
        args[path] = value
        return
    head, _, tail = path.partition(".")
    args.setdefault(head, {})[tail] = value


def _legacy_tool_doc(tool: op_registry.ToolSpec) -> str:
    lines = [tool.summary or tool.op, "", f"op: `{tool.op}`（旧工具名保留兼容）"]
    if tool.fixed:
        fixed = ", ".join(f"{k}={v!r}" for k, v in tool.fixed)
        lines += ["", f"固定参数: {fixed}"]
    if tool.params:
        lines += ["", "Args:"]
        for p in tool.params:
            req = "必填" if p.required else "可选"
            lines.append(f"    {p.name}: {p.summary or '—'}（{req}）")
    lines += ["", "返回引擎结果 dict；超时返回 {error, error_code: \"timeout\"}。"]
    return "\n".join(lines)


def _make_legacy_tool(tool: op_registry.ToolSpec):
    async def call(**kwargs):
        args = dict(tool.fixed)
        for p in tool.params:
            value = kwargs.get(p.name)
            if value is not None:
                _assign_arg(args, p.arg, value)
        args = op_registry.prepare_args(tool.op, args)
        timeout = op_registry.call_timeout(tool.op)
        try:
            return await _offload(_send, timeout + 5.0, tool.op, args, timeout)
        except _DeadlineExceeded as e:
            return {"error": f"{tool.op}: {e}", "error_code": "timeout"}

    call.__name__ = tool.name
    call.__doc__ = _legacy_tool_doc(tool)
    call.__signature__ = inspect.Signature(
        [
            inspect.Parameter(
                p.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=inspect.Parameter.empty if p.required else p.default,
                annotation=p.annotation,
            )
            for p in tool.params
        ],
        return_annotation=dict,
    )
    return call


for _tool in op_registry.legacy_tool_specs():
    mcp.add_tool(_make_legacy_tool(_tool), name=_tool.name)


try:
    _ALL_TOOL_OBJECTS: dict = dict(mcp._tool_manager._tools)
except AttributeError:
    _ALL_TOOL_OBJECTS = {}


def _requested_port(argv: list[str] | None = None) -> int | None:
    """MCP 启动参数 --port（优先于 env / 默认 8977）; 无则 None。"""
    args = list(sys.argv[1:] if argv is None else argv)
    value = ""
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            value = args[i + 1]
            break
        if a.startswith("--port="):
            value = a.split("=", 1)[1]
            break
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        print(f"[engine-editor-mcp] WARNING: invalid --port {value!r}; using env/default", file=sys.stderr)
        return None


def main() -> None:
    """入口: 解析端口/档位 → 裁剪工具集 → 清空抓帧目录 → 启动 stdio 服务器。"""
    port = _requested_port()
    if port is not None:
        os.environ["MGE_EDITOR_MCP_PORT"] = str(port)
    apply_profile(_requested_profile())
    _wipe_frames_dir()
    mcp.run()


if __name__ == "__main__":
    main()

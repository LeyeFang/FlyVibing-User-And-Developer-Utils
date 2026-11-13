"""Extension 静态审查器 v0 — 扩展开发者的规范自查工具（无需引擎运行）。

用法:
    python packages/extension-kit/review_extension.py <extension_dir> [<dir>...]
    python packages/extension-kit/review_extension.py --all    # 扫仓库内全部 Application/Functions/*/

检查项（对照 Doc/ExtDev/extension_dev_protocol.md）:

  [manifest]
    M1 extension.json 存在且为合法 JSON
    M2 id 合法（^[a-z][a-z0-9_]*$）
    M3 api_version 与宿主兼容（前缀 "1"）
    M4 entry 格式合法且文件存在（无 entry = planned/partial 允许）
    M5 capabilities 取值合法（ops/ui/nodes/threads/jobs/settings/device/graph/examples）
    M6 description 非空（菜单 tooltip）

  [code]（entry 存在时静态扫描）
    C1 capabilities 含 ui → entry 类继承 UIExtensionBase（语言层强制）
    C2 capabilities 含 ui → 实现 on_ui_event
    C3 register_window 调用声明 close_policy（窗口 X 语义显式化 — §7）
    C4 ops 注册名不得自带 "ext." 前缀（前缀由宿主强制）
    C5 无 monkey-patch 迹象（顶层引擎赋值启发式）
    C6 Application.* import 在常用白名单内
    C7 imgui 文本字形安全（字体图集外字符显示为 '?' — 与主应用 test_ui_text_safety 同源规则）
    C8 imgui 窗口栈配对纪律：begin_child 不得被条件门控（全裁剪 0x0 时返回 False）
    C9 combo/tab_item 反向规则：end_combo/end_tab_item 仅在 begin 返回 True 时调用
    C10 无顶层 imgui 上下文/窗口/GL 创建（纯导入允许 — M0 口径）
    M7  manifest `python` 解释器声明合法（mode/path/requirements/probe —
        extdev protocol §11.1）
    M8  manifest `python.runtime` 依赖契约合法，且随产物分发的扩展必须声明
        （extdev protocol §11.2；规范实现在 Application/Core/Extension/
        ExtensionRuntimeDeps.py，本处是镜像 — 两边对拍见 test_extension_python_contract）
    C12 不自备解释器: 不写死绝对 python 路径、不 Popen(sys.executable)（用 ctx.python.spawn）
    C11 不触碰宿主全局 imgui 状态（create/destroy_context、set_ini_filename、io/style 赋值 —
        含 get_io()/get_style() 链式与别名写法）

  [files]
    F2 TODO.md 存在（状态档案）

退出码: 0 = 无 FAIL（WARN 不失败）; 1 = 存在 FAIL; 2 = 用法错误。
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

_CAPABILITIES = {"ops", "ui", "nodes", "threads", "jobs", "settings", "device", "graph", "examples"}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IMPORT_RE = re.compile(
    r"^\s*from\s+(Application[\w\.]*)\s+import|^\s*import\s+(Application[\w\.]*)", re.M)
_IMPORT_ALLOW = (
    "Application.Core.Extension",
    "Application.Functions",
    "Application.Core.Events",
    "Application.Core.ThreadRegistry",
    # 跨机器设备身份（协议 device_io_protocol §12）— 别名**能力凭据**
    # （实现归扩展；核心只在中间做注册/查询，2026-11-14 起是 DeviceAliases）
    "Application.Core.DeviceAliases",
)
_MONKEY_RE = re.compile(r"^Application\w*(?:\.\w+)*\s*=", re.M)
_UI_BASE_RE = re.compile(r"class\s+\w+\s*\([^)]*UIExtensionBase")

# 字形安全集（与主应用 Test/Application/Editor/test_ui_text_safety.py 同源；字体图集 = 
# ASCII + Latin-1 + General Punctuation 子集 + FontAwesome 私有区）
_SAFE_RANGES = [
    (0x0020, 0x007E),
    (0x00A0, 0x00FF),
    (0x2013, 0x2014),
    (0x2018, 0x201D),
    (0x2022, 0x2022),
    (0x2026, 0x2026),
    (0xF000, 0xFFFF),
]


def unsafe_chars(text: str) -> list:
    """返回 imgui 字体图集外字符（去重排序 → 渲染为 '?' 的隐患）；换行/制表符放行。"""
    bad = set()
    for ch in text:
        if ch in "\n\t":
            continue
        cp = ord(ch)
        if not any(a <= cp <= b for a, b in _SAFE_RANGES):
            bad.add(ch)
    return sorted(bad)


# ── imgui 窗口栈纪律（C8/C9/C10 — 与 Doc/Dev/ui_protocol.md §2.13 同源规则） ──
_BEGIN_CHILD = ("begin_child",)
_BEGIN_SCOPED = ("begin_combo", "begin_tab_item", "begin_menu", "begin_popup")
_END_SCOPED = ("end_combo", "end_tab_item", "end_menu", "end_popup")
_CTX_CREATE = ("create_context", "glfw_init", "glfw_init_for_opengl", "opengl2_init",
               "opengl3_init", "new_frame", "end_frame", "render", "run",
               "manually_render", "manually_show_gui")


def _imgui_call(node: ast.AST) -> tuple:
    """`imgui.xxx(...)` / `hello_imgui.xxx(...)` → (base 名, 属性名); 其它 → ("", "")。"""
    if not isinstance(node, ast.Call):
        return "", ""
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id, f.attr
    return "", ""


def gated_begin_child(tree: ast.AST) -> list:
    """把 `begin_child` 当条件用的位置 → ["L<行> …"]。

    反模式: `if imgui.begin_child(...): … imgui.end_child()` —— 宿主窗口被完全裁剪
    （最小化 0x0）时返回 False → 漏 `end_child` → 窗口栈失衡 → 之后任意 `end()` 断言。
    """
    out: list[str] = []
    for node in ast.walk(tree):
        test = None
        if isinstance(node, (ast.If, ast.While)):
            test = node.test
        elif isinstance(node, ast.IfExp):
            test = node.test
        if test is None:
            continue
        for sub in ast.walk(test):
            _base, attr = _imgui_call(sub)
            if attr in _BEGIN_CHILD:
                out.append(f"L{node.lineno} {attr}() 被当作条件")
    return out


def unguarded_scoped_ends(tree: ast.AST) -> list:
    """函数内不在任何 `if` 体内的 `end_combo/end_tab_item` 等 → ["L<行> …"]（反向规则）。"""
    out: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        guarded: set = set()
        for sub in ast.walk(fn):
            if isinstance(sub, ast.If):
                for stmt in sub.body:
                    for c in ast.walk(stmt):
                        if isinstance(c, ast.Call) and _imgui_call(c)[1] in _END_SCOPED:
                            guarded.add(id(c))
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                _base, attr = _imgui_call(sub)
                if attr in _END_SCOPED and id(sub) not in guarded:
                    out.append(f"L{sub.lineno} {attr}() 不在任何 if 体内")
    return out


def toplevel_context_calls(tree: ast.Module) -> list:
    """模块顶层（**不含**函数/类体内）的 imgui 上下文/窗口/GL 创建 → ["L<行> …"]。

    注意: `ast.walk` 会钻进函数体 — 必须逐层剪掉函数/类作用域, 否则窗口回调里的
    `imgui.new_frame()` 之类会被误判（实测踩过）。
    """
    out: list[str] = []
    scope_cut = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack: list = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, scope_cut):       # 在"取出时"剪枝（压入时剪不掉自身）
            continue
        base, attr = _imgui_call(node)
        if base in ("imgui", "hello_imgui") and attr in _CTX_CREATE:
            out.append(f"L{node.lineno} {base}.{attr}()")
        stack.extend(ast.iter_child_nodes(node))
    return out


# C11: 扩展不得触碰宿主全局 imgui 状态（会污染整个编辑器与其它扩展）
_GLOBAL_FORBIDDEN_CALLS = ("create_context", "destroy_context", "set_ini_filename")
_GLOBAL_FORBIDDEN_IO_ATTRS = ("get_io", "get_style")


def _is_io_source(node: ast.AST) -> bool:
    """`imgui.get_io()` / `imgui.get_style()` 调用（全局 io/style 来源）。"""
    return isinstance(node, ast.Call) and _imgui_call(node)[1] in _GLOBAL_FORBIDDEN_IO_ATTRS


def global_imgui_state_writes(tree: ast.AST) -> list:
    """扩展对宿主全局 imgui 状态的写入 → ["L<行> …"]（C11）。

    禁止: `create_context` / `destroy_context` / `set_ini_filename`（任意位置, 含
          `imgui.get_io().set_ini_filename(...)` 链式写法与 `io = imgui.get_io()`
          别名写法）; `imgui.get_io().x = …` / `imgui.get_style().x = …` 赋值。
    允许: 窗口内 `push_style_color / push_style_var`（局部作用域, 由宿主窗口包裹）;
          纯导入与只读查询（`io.display_size` 之类）。
    """
    out: list[str] = []
    nodes = list(ast.walk(tree))

    # 第一遍: 收集指向 get_io()/get_style() 返回对象的变量名（别名流）
    io_aliases: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Assign) and _is_io_source(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    io_aliases.add(tgt.id)

    def _flag(lineno: int, what: str) -> None:
        out.append(f"L{lineno} {what}")

    # 第二遍: 检出禁用调用与全局状态赋值
    for node in nodes:
        if isinstance(node, ast.Call):
            _base, attr = _imgui_call(node)
            if attr in _GLOBAL_FORBIDDEN_CALLS:                 # imgui.create_context() …
                _flag(node.lineno, f"{attr}()")
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute):
                if _is_io_source(fn.value):                     # imgui.get_io().set_ini_filename(…)
                    _flag(node.lineno, f"get_io()/get_style().{fn.attr}()")
                    continue
                if isinstance(fn.value, ast.Name) and fn.value.id in io_aliases:
                    _flag(node.lineno, f"{fn.value.id}.{fn.attr}()")   # io = get_io(); io.font_…(…)
                    continue
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                if _is_io_source(tgt.value):                    # imgui.get_io().x = …
                    _flag(node.lineno, f"get_io()/get_style().{tgt.attr} = ...")
                elif isinstance(tgt.value, ast.Name) and tgt.value.id in io_aliases:
                    _flag(node.lineno, f"{tgt.value.id}.{tgt.attr} = ...")
    return out


class Report:
    """单扩展审查报告（可导入使用 — 测试/CI）。"""

    def __init__(self, ext_dir: str) -> None:
        self.dir = ext_dir
        self.lines: list[str] = []
        self.passes = 0
        self.warns = 0
        self.fails = 0

    def _add(self, level: str, code: str, msg: str) -> None:
        self.lines.append(f"  [{level:4}] {code:2} {msg}")
        if level == "PASS":
            self.passes += 1
        elif level == "WARN":
            self.warns += 1
        else:
            self.fails += 1

    def ok(self, code: str, msg: str = "") -> None:
        self._add("PASS", code, msg)

    def warn(self, code: str, msg: str) -> None:
        self._add("WARN", code, msg)

    def fail(self, code: str, msg: str) -> None:
        self._add("FAIL", code, msg)


def review_extension(ext_dir: str) -> Report:
    """审查单个扩展目录（纯静态 — 不 import 扩展代码）。"""
    rep = Report(ext_dir)
    manifest_path = os.path.join(ext_dir, "extension.json")
    if not os.path.isfile(manifest_path):
        rep.fail("M1", "extension.json 缺失")
        return rep
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        rep.ok("M1", "extension.json 合法")
    except Exception as e:  # noqa: BLE001
        rep.fail("M1", f"extension.json 解析失败: {e}")
        return rep

    ext_id = str(manifest.get("id", ""))
    if _ID_RE.match(ext_id):
        rep.ok("M2", f"id='{ext_id}' 合法")
    else:
        rep.fail("M2", f"id='{ext_id}' 非法（要求 ^[a-z][a-z0-9_]*$）")

    api = str(manifest.get("api_version", ""))
    if api.split(".")[0] == "1":
        rep.ok("M3", f"api_version='{api}'")
    else:
        rep.fail("M3", f"api_version='{api}' 与宿主不兼容（当前需要 1.x）")

    caps = manifest.get("capabilities") or []
    bad_caps = [c for c in caps if c not in _CAPABILITIES]
    if bad_caps:
        rep.fail("M5", f"capabilities 含非法值: {bad_caps}")
    else:
        rep.ok("M5", f"capabilities={caps if caps else '(未声明)'}")

    _review_python_manifest(rep, manifest)

    if str(manifest.get("description", "")).strip():
        rep.ok("M6", "description 非空")
    else:
        rep.warn("M6", "description 为空（Extensions 菜单 tooltip 建议填写）")

    entry = str(manifest.get("entry", ""))
    entry_file = entry.split(":")[0] if entry else ""
    if not entry:
        rep.ok("M4", "无 entry（planned/partial 允许; 提供后可启用）")
        _review_files(rep, ext_dir)
        return rep
    entry_path = os.path.join(ext_dir, entry_file)
    if not os.path.isfile(entry_path):
        rep.fail("M4", f"entry 文件不存在: {entry_file}")
        return rep
    rep.ok("M4", f"entry={entry}")

    # ── 代码静态检查 ────────────────────────────────────────────
    try:
        with open(entry_path, encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:  # noqa: BLE001
        rep.fail("C0", f"entry 读取失败: {e}")
        return rep

    if "ui" in caps:
        if _UI_BASE_RE.search(src):
            rep.ok("C1", "entry 类继承 UIExtensionBase")
        else:
            rep.fail("C1", "capabilities 含 ui → entry 类必须继承 UIExtensionBase（语言层强制）")
        if "def on_ui_event" in src:
            rep.ok("C2", "实现 on_ui_event")
        else:
            rep.fail("C2", "capabilities 含 ui → 必须实现 on_ui_event（窗口生命周期完备性）")

    if "register_window(" in src:
        if "close_policy" in src:
            rep.ok("C3", "register_window 声明 close_policy")
        else:
            rep.warn("C3", "register_window 未声明 close_policy（窗口 X 语义未显式化 — dev protocol §7）")

    if re.search(r"\.register\(\s*['\"]ext\.", src):
        rep.fail("C4", "ops 注册名不得自带 'ext.' 前缀（宿主自动加 ext.<id>.）")
    else:
        rep.ok("C4", "ops 注册名无 ext. 前缀")

    monkey = _MONKEY_RE.findall(src)
    if monkey:
        rep.warn("C5", f"疑似顶层引擎赋值（monkey-patch 黑名单, 人工复核）: {monkey[:3]}")
    else:
        rep.ok("C5", "无 monkey-patch 迹象")

    offenders = []
    for m in _IMPORT_RE.finditer(src):
        mod = m.group(1) or m.group(2)
        if mod and not any(mod.startswith(prefix) for prefix in _IMPORT_ALLOW):
            offenders.append(mod)
    if offenders:
        rep.warn("C6", f"import Application.* 超出常用白名单（人工复核）: {sorted(set(offenders))}")
    else:
        rep.ok("C6", "Application.* import 均在白名单")

    # C7: imgui 文本字形安全（图集外字符 → '?'）
    try:
        entry_tree = ast.parse(src)
        bad_texts = []
        for node in ast.walk(entry_tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            base = node.func.value
            if not (isinstance(base, ast.Name) and base.id == "imgui"):
                continue
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        bad = unsafe_chars(sub.value)
                        if bad:
                            bad_texts.append(f"L{sub.lineno} {bad} in {sub.value[:48]!r}")
        if bad_texts:
            extra = f" (+{len(bad_texts) - 2} more)" if len(bad_texts) > 2 else ""
            rep.fail("C7", "imgui 文本含图集外字符（显示为 '?'）: " + "; ".join(bad_texts[:2]) + extra)
        else:
            rep.ok("C7", "imgui 文本字形安全")
    except SyntaxError as e:  # noqa: BLE001
        rep.warn("C7", f"entry 语法错误, 跳过字形检查: {e}")

    # C8/C9/C10: imgui 窗口栈纪律（协议 §7.7 + ui_protocol §2.13 同源规则）
    try:
        tree8 = ast.parse(src)
    except SyntaxError as e:  # noqa: BLE001
        rep.warn("C8", f"entry 语法错误, 跳过窗口栈检查: {e}")
        tree8 = None
    if tree8 is not None:
        gated = gated_begin_child(tree8)
        if gated:
            rep.fail("C8", "begin_child 被条件门控（全裁剪 0x0 返回 False → 漏 end_child 会腐蚀"
                           "窗口栈, 之后任意 end 断言杀渲染循环; 用 try/finally 无条件配对）: "
                     + "; ".join(gated[:2]))
        else:
            rep.ok("C8", "窗口栈配对纪律（begin_child 未被条件门控）")
        loose = unguarded_scoped_ends(tree8)
        if loose:
            rep.warn("C9", "end_combo/end_tab_item 疑似无条件调用（应仅 begin 返回 True 时 end）: "
                     + "; ".join(loose[:2]))
        else:
            rep.ok("C9", "combo/tab_item 反向规则 OK")
        top = toplevel_context_calls(tree8)
        if top:
            rep.fail("C10", "顶层创建 imgui 上下文/窗口/GL（应放在窗口回调/运行时内）: "
                     + "; ".join(top[:2]))
        else:
            rep.ok("C10", "无顶层 imgui 上下文/窗口/GL 创建（纯导入允许）")

        global_writes = global_imgui_state_writes(tree8)
        if global_writes:
            rep.fail("C11", "触碰宿主全局 imgui 状态（会污染编辑器与其它扩展; 窗口内 "
                            "push_style_* 才可以）: " + "; ".join(global_writes[:2]))
        else:
            rep.ok("C11", "无全局 imgui 状态写入")

    _review_python_code(rep, ext_dir)
    _review_files(rep, ext_dir)
    return rep


_PY_MODES = ("engine", "venv", "path")
_RT_MODES = ("engine", "bundle", "none")
#: `python.runtime` 允许的键（与 Application/Core/Extension/ExtensionRuntimeDeps.py
#: 的 KNOWN_KEYS 必须一致 — 守卫 Test/Application/Extensions/test_extension_python_contract.py）
_RT_KEYS = frozenset({"mode", "requires", "probe", "optional", "path", "env", "note"})
_PY_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_PY_REQ_RE = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*")
_ABS_PY_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'\n]*python(?:\.exe)?", re.IGNORECASE)
_SPAWN_FUNCS = {"Popen", "run", "call", "check_output", "check_call", "spawnv", "spawnve"}


def _review_python_manifest(rep: Report, manifest: dict) -> None:
    """M7 — `python` 声明结构合法（extdev protocol §11.1 + §11.2 依赖契约）。"""
    raw = manifest.get("python")
    if raw in (None, "", {}):
        rep.ok("M7", "未声明 python（默认引擎解释器）")
        _review_runtime_contract(rep, manifest, python={})
        return
    if isinstance(raw, str):
        mode = raw.strip().lower()
        if mode in _PY_MODES:
            rep.ok("M7", f"python='{mode}'")
        else:
            rep.fail("M7", f"python='{raw}' 非法（允许 engine / venv / path）")
        _review_runtime_contract(rep, manifest, python={"mode": mode})
        return
    if not isinstance(raw, dict):
        rep.fail("M7", "python 必须是字符串或对象（extdev protocol §11.1）")
        return

    problems: list[str] = []
    mode = str(raw.get("mode") or "engine").strip().lower()
    if mode not in _PY_MODES:
        problems.append(f"mode={mode!r} 非法（engine/venv/path）")
    path = str(raw.get("path") or "").strip()
    if mode in ("venv", "path") and not path:
        problems.append(f"mode={mode} 需要 path")
    if path and _ABS_PY_RE.search(path) and "%" not in path:
        problems.append(f"path 写死了机器路径 {path!r}（用 %EXT_DATA% / %EXT_DIR% 变量）")
    req = raw.get("requirements")
    if req not in (None, "") and not str(req).strip():
        problems.append("requirements 不能是空串（省略即可）")
    probe = raw.get("probe")
    if probe is not None:
        if not isinstance(probe, list) or not all(
                isinstance(x, str) and _PY_IMPORT_RE.match(x) for x in probe):
            problems.append("probe 必须是 import 名列表（如 ['serial', 'numpy']）")
    if problems:
        rep.fail("M7", "python 声明有问题: " + "; ".join(problems))
    else:
        rep.ok("M7", f"python mode={mode}"
                     + (f" probe={probe}" if probe else ""))
    _review_runtime_contract(rep, manifest, python=raw)


def _review_runtime_contract(rep: Report, manifest: dict, *, python: dict) -> None:
    """M8 — 产物侧依赖契约 `python.runtime`（2026-11-14，导出强制）。

    这条检查是**规范镜像**：真正的判据在
    `Application/Core/Extension/ExtensionRuntimeDeps.py`（导出器与成品共用）。
    本文件刻意不 import 引擎代码（审查器要能在裸工具链里跑），两边一致性由
    `Test/Application/Extensions/test_extension_python_contract.py` 用同一组夹具
    对拍守住 —— 改规则请同时改两边。
    """
    raw = python.get("runtime") if isinstance(python, dict) else None
    ext_id = str(manifest.get("id") or "<id>")
    ships = bool(manifest.get("entry")) and (
        "nodes" in (manifest.get("capabilities") or ())
        or isinstance(manifest.get("nodes"), dict)
        or bool(python)
    )
    if raw is None:
        if ships:
            rep.fail("M8", f"随产物分发的扩展必须声明 python.runtime —— 成品用独立运行时"
                           f"镜像，未声明的依赖在成品里必然缺失。无三方依赖也请写 "
                           f"{{\"mode\": \"none\"}}")
        else:
            rep.ok("M8", "不随产物分发，无需 runtime 契约")
        return
    if not isinstance(raw, dict):
        rep.fail("M8", "python.runtime 必须是对象")
        return

    problems: list[str] = []
    unknown = sorted(set(raw) - _RT_KEYS)
    if unknown:
        problems.append(f"未知键 {unknown}（允许: {sorted(_RT_KEYS)}）")
    mode = str(raw.get("mode") or ("engine" if str(python.get("mode") or "engine")
                                   in ("engine",) else "bundle")).strip().lower()
    if mode not in _RT_MODES:
        problems.append(f"mode={mode!r} 非法（{'/'.join(_RT_MODES)}）")
    requires = raw.get("requires")
    if requires is not None:
        if not isinstance(requires, list) or not all(
                isinstance(x, str) and x.strip() for x in requires):
            problems.append("requires 必须是 PEP 508 字符串列表")
        else:
            for item in requires:
                if not _PY_REQ_RE.match(item):
                    problems.append(f"requires 项非法: {item!r}")
    if mode == "none" and (requires or []):
        problems.append("mode=none 不应带 requires（要装包请用 mode=engine）")
    if mode == "bundle":
        path = str(raw.get("path") or python.get("path") or "").strip()
        if not path:
            problems.append("mode=bundle 需要 path（或外层 python.path）")
    if mode == "engine":
        for item in (requires or []):
            module = re.split(r"[<>=!~\[;]", str(item), 1)[0].strip().replace("-", "_")
            if module and not _PY_IMPORT_RE.match(module):
                problems.append(f"requires 项无法推导 import 名: {item!r}")
    probe = raw.get("probe")
    if probe is not None and (not isinstance(probe, list) or not all(
            isinstance(x, str) and _PY_IMPORT_RE.match(x) for x in probe)):
        problems.append("probe 必须是 import 名列表")
    optional = raw.get("optional")
    if optional is not None and not isinstance(optional, bool):
        problems.append("optional 必须是 true/false")
    env = raw.get("env")
    if env is not None and (not isinstance(env, dict) or
                            not all(isinstance(k, str) and isinstance(v, str)
                                    for k, v in env.items())):
        problems.append("env 必须是 {str: str}")

    if problems:
        rep.fail("M8", f"[{ext_id}] python.runtime 有问题: " + "; ".join(problems))
    else:
        detail = f"mode={mode}"
        if requires:
            detail += f" requires={requires}"
        rep.ok("M8", detail)


def _scan_py_files(ext_dir: str) -> list:
    out = []
    for cur, dirs, files in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(cur, name))
    return sorted(out)


def _review_python_code(rep: Report, ext_dir: str) -> None:
    """C12 — 扩展不应自备解释器（写死路径 / Popen(sys.executable)）。"""
    hardcoded: list[str] = []
    spawns: list[str] = []
    for path in _scan_py_files(ext_dir):
        rel = os.path.relpath(path, ext_dir)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        for idx, line in enumerate(src.splitlines(), 1):
            if _ABS_PY_RE.search(line) and not line.lstrip().startswith("#"):
                hardcoded.append(f"{rel}:{idx}")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if name not in _SPAWN_FUNCS:
                continue
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                for sub in ast.walk(arg):
                    if (isinstance(sub, ast.Attribute) and sub.attr == "executable"
                            and isinstance(sub.value, ast.Name) and sub.value.id == "sys"):
                        spawns.append(f"{rel}:{getattr(node, 'lineno', 0)}")
    if hardcoded:
        rep.fail("C12", "写死解释器路径（换机器即断；用 manifest python.path + 变量）: "
                 + "; ".join(hardcoded[:3]))
    elif spawns:
        rep.fail("C12", "用 sys.executable 自起子进程（依赖/回收都没有宿主兜底；"
                        "改用 ctx.python.spawn）: " + "; ".join(spawns[:3]))
    else:
        rep.ok("C12", "未自备解释器（用 ctx.python 协议）")


def _review_files(rep: Report, ext_dir: str) -> None:
    if os.path.isfile(os.path.join(ext_dir, "TODO.md")):
        rep.ok("F2", "TODO.md 存在（状态档案）")
    else:
        rep.warn("F2", "建议提供 TODO.md（状态档案 — 开发规范 §3）")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args == ["--all"]:
        root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Application", "Functions"))
        if not os.path.isdir(root):
            print(f"Application/Functions 目录不存在: {root}")
            return 2
        dirs = []
        for dirpath, _dirnames, filenames in os.walk(root):
            if "extension.json" in filenames:
                dirs.append(dirpath)
        dirs.sort()
    else:
        dirs = [os.path.abspath(a) for a in args]

    total_fail = 0
    for ext_dir in dirs:
        rep = review_extension(ext_dir)
        name = os.path.basename(ext_dir.rstrip("/\\"))
        print(f"== review: {name}  ({ext_dir}) ==")
        for line in rep.lines:
            print(line)
        print(f"   -> {rep.passes} pass / {rep.warns} warn / {rep.fails} fail")
        print()
        total_fail += rep.fails

    print(f"SUMMARY: {len(dirs)} extension(s), fails={total_fail} — "
          + ("OK" if total_fail == 0 else "FAIL"))
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

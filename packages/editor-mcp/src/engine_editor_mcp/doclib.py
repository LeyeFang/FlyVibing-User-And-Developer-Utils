"""内置文档 CLI — Doc/Dev 与 Doc/ExtDev 的只读服务层 (2026-10-16, Doc CLI 化)。

三层消费模型 (用户定稿 — "agent 面对 doc 更多时间在查字典索引"):
  ① 大方向指引: 引擎仓 Doc/** 的 md 只答两个问题 — 这份文档"面对什么问题"、内容"去哪获得";
  ② 字典索引 (最常停留): ``doc`` = 全主题两级索引 (主题目的行 + 次级标题);
     ``doc outline <topic>`` = 单主题章节索引 (标题 + 一行预览); ``doc search <kw>`` 跨主题;
  ③ 内容: ``doc show <topic>[#节号]`` 按节拉取 — 只在确定要读哪节时才输出正文。

用法:
  engine-editor-cli doc                     # 两级索引 (全主题)
  engine-editor-cli doc dev                 # 只索引 dev 区
  engine-editor-cli doc outline dev/x       # 章节索引 (标题 + 预览)
  engine-editor-cli doc show dev/x#3        # 第 3 节 (或 #标题片段)
  engine-editor-cli doc search 关键词        # 跨主题检索
  engine-editor-cli doc tools               # 开发工具索引 (引擎仓 Utils/Dev)
  engine-editor-cli doc tool <名>           # 单工具用法 (真实 --help)
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs_content")
AREAS = ("dev", "extdev")

_H2 = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_JUNK_LINE = re.compile(r"[-:|\s=]+")


def _iter_topics():
    """(topic, path) — topic 形如 "dev/project_export_protocol"。"""
    for area in AREAS:
        d = os.path.join(DATA_DIR, area)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md"):
                yield f"{area}/{fn[:-3]}", os.path.join(d, fn)


def resolve(topic: str) -> tuple[str, str]:
    """topic → (规范名, 路径)。接受 "dev/x"; 裸名 "x" 在唯一时可用。"""
    topic = (topic or "").strip().replace("\\", "/").strip("/")
    if not topic:
        raise ValueError("缺少主题名 (见 `doc list`); 例: doc show dev/project_export_protocol")
    if topic.endswith(".md"):
        topic = topic[:-3]
    topics = dict(_iter_topics())
    if topic in topics:
        return topic, topics[topic]
    bare = [t for t in topics if t.split("/", 1)[-1] == topic]
    if len(bare) == 1:
        return bare[0], topics[bare[0]]
    if len(bare) > 1:
        raise ValueError(f"主题名不唯一, 请带领域前缀: {', '.join(sorted(bare))}")
    raise ValueError(f"未知主题: {topic!r} (见 `doc list`)")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _doc_title(text: str, topic: str) -> str:
    m = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
    title = m.group(1).strip() if m else topic
    head, sep, tail = title.partition(" — ")  # 去 "xxx_protocol.md — " 文件名前缀
    if sep and head.endswith(".md"):
        return tail.strip() or title
    return title


def _clean_inline(text: str) -> str:
    """行内 markdown 清理 (供索引行/预览使用)。"""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    return text.strip()


def _normalize_text(text: str) -> str:
    """合并换行空白 + 去 CJK 间空格 + 去标点后空格 (中文折行伪影清理)。"""
    text = re.sub(r"\s+", " ", _clean_inline(text)).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"([，、。：；！？（）])\s+", r"\1", text)
    return text


def _purpose(text: str, topic: str) -> str:
    """文档目的行 = H1 后首段 (句号处收尾, 最多 3 行; 截断 120)。"""
    started = False
    para: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not started:
            if s.startswith("# "):
                started = True
            continue
        s = re.sub(r"^>\s*", "", s).strip()
        if not s:
            if para:
                break
            continue
        if not para and s.startswith(("-", "|", "#", "```")):
            break  # 首段不是散文 → 放弃 (回退 topic)
        para.append(s)
        if s.endswith(("。", "！", "？")) or len(para) >= 3:
            break
    joined = _normalize_text(" ".join(para))
    if len(joined) > 120:
        joined = joined[:118].rstrip("，、：:；;/ ") + "…"
    return joined or topic


def _preview(body: str, limit: int = 80) -> str:
    """节预览 = 正文首个可读行 (跳过代码块/表格/引用/分隔线; 去列表标记)。"""
    for ln in body.splitlines():
        s = ln.strip()
        if (not s or s.startswith(("```", "|", ">", "#"))
                or _JUNK_LINE.fullmatch(s)):
            continue
        s = re.sub(r"^[-*]\s+(?:\[[ xX]\]\s+)?", "", s)
        s = _normalize_text(s)
        if s:
            return s[:limit].rstrip("，、：:；;/ .") + ("…" if len(s) > limit else "")
    return ""


def _sections(text: str) -> list[tuple[str, str]]:
    """[("", preamble), (title, body), ...] — 按 ## 分节 (body 不含标题行)。"""
    matches = list(_H2.finditer(text))
    if not matches:
        return [("", text.strip("\n"))]
    parts: list[tuple[str, str]] = []
    preamble = text[:matches[0].start()]
    if preamble.strip():
        parts.append(("", preamble.strip("\n")))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts.append((m.group(1).strip(), text[m.end():end].strip("\n")))
    return parts


# ── 对外 ────────────────────────────────────────────────────────────


def list_all(area: str = "") -> str:
    """两级索引: 主题 (目的行) → 次级标题 — 字典索引层, 默认输出。area 过滤 dev/extdev。"""
    area = (area or "").strip()
    if area and area not in AREAS:
        raise ValueError(f"未知领域: {area!r} (可选: {', '.join(AREAS)})")
    topics = [(t, p) for t, p in _iter_topics() if not area or t.split("/", 1)[0] == area]
    if not topics:
        return f"(无主题{'' if not area else ' —— 领域 ' + area})"
    out: list[str] = []
    for topic, path in topics:
        text = _read(path)
        out.append(f"{topic} — {_doc_title(text, topic)}")
        out.append(f"    面向: {_purpose(text, topic)}")
        n = 0
        for title, _body in _sections(text):
            if title:
                n += 1
                out.append(f"    {n}. {re.sub(r'^[0-9]+[.、] *', '', title)}")
        out.append("")
    out.append("逐级深入: doc outline <topic> (章节索引) → doc show <topic>#<节号|标题片段>")
    return "\n".join(out)


def outline(topic: str) -> str:
    """章节索引 (标题 + 一行预览) — 索引层, 决定要读哪节用。"""
    canon, path = resolve(topic)
    text = _read(path)
    lines = [f"# {canon} — {_doc_title(text, canon)}",
             f"面向: {_purpose(text, canon)}"]
    n = 0
    for title, body in _sections(text):
        if not title:
            continue
        n += 1
        prev = _preview(body)
        t = re.sub(r"^[0-9]+[.、] *", "", title)
        lines.append(f"  {n}. {t}" + (f" — {prev}" if prev else ""))
    lines.append("")
    lines.append(f"读取: engine-editor-cli doc show {canon}#<序号或标题片段>")
    return "\n".join(lines)


def show(topic: str, section: str = "") -> str:
    canon, path = resolve(topic)
    text = _read(path)
    section = (section or "").strip()
    if not section:
        return text.rstrip() + "\n"
    sections = _sections(text)
    hits = [(t, b) for t, b in sections if t]
    sel = None
    if section.isdigit():
        idx = int(section)
        if 1 <= idx <= len(hits):
            sel = hits[idx - 1]
    if sel is None:  # 标题片段匹配 (忽略大小写)
        frag = section.lower()
        for t, b in hits:
            if frag in t.lower():
                sel = (t, b)
                break
    if sel is None:
        raise ValueError(f"{canon} 无匹配节: {section!r} (见 `doc outline {canon}`)")
    return f"## {sel[0]}\n\n{sel[1].strip()}\n"


def search(keyword: str, max_hits: int = 30) -> str:
    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("缺少搜索词")
    low = kw.lower()
    out: list[str] = []
    for topic, path in _iter_topics():
        text = _read(path)
        n = 0
        for title, body in _sections(text):
            if title:
                n += 1
            scope = f"{title}\n{body}"
            if low in scope.lower():
                label = f"{topic}#{n}" if title else topic
                first = next((ln.strip() for ln in scope.splitlines() if low in ln.lower()), "")
                out.append(f"{label:<52}{first[:90]}")
                if len(out) >= max_hits:
                    out.append("... (截断, 调整关键词缩小范围)")
                    return "\n".join(out)
    return "\n".join(out) if out else f"无匹配: {kw!r}"


# ── 开发工具索引 (Utils/Dev — 引擎核心开发者 CLI 工具; 数据源=工具文件本身) ──

_DEFAULT_ENGINE_ROOT = "c:/WorkSpace/FLY/MyGameEngine-Python"


def _engine_root() -> str:
    """引擎仓根 (含 Utils/Dev 视为命中): cwd → MGE_ROOT → 默认路径; 找不到回空串。"""
    for cand in (os.getcwd(), os.environ.get("MGE_ROOT", ""), _DEFAULT_ENGINE_ROOT):
        if cand and os.path.isdir(os.path.join(cand, "Utils", "Dev")):
            return os.path.abspath(cand)
    return ""


def _iter_tools(root: str) -> list[tuple[str, str]]:
    """(工具名, 路径) — Utils/Dev 顶层 py/bat + Utils/Dev/Installer 顶层 py (不含暂存树)。"""
    dev = os.path.join(root, "Utils", "Dev")
    found: list[tuple[str, str]] = []
    for fn in sorted(os.listdir(dev)):
        p = os.path.join(dev, fn)
        if os.path.isfile(p) and fn != "__init__.py" and fn.endswith((".py", ".bat")):
            found.append((fn.rsplit(".", 1)[0], p))
    inst = os.path.join(dev, "Installer")
    if os.path.isdir(inst):
        for fn in sorted(os.listdir(inst)):
            p = os.path.join(inst, fn)
            if os.path.isfile(p) and fn.endswith(".py") and fn != "__init__.py":
                found.append((fn.rsplit(".", 1)[0], p))
    return sorted(found)


def _bat_leading_comments(path: str, limit: int = 14) -> list[str]:
    """bat 头部注释块 (:: / REM 行)。"""
    out: list[str] = []
    for ln in _read(path).splitlines():
        s = ln.strip()
        if s.startswith("::"):
            c = s[2:].strip(" =")
            if c:
                out.append(c)
        elif s.lower().startswith("rem "):
            c = s[4:].strip()
            if c:
                out.append(c)
        elif out:
            break
        if len(out) >= limit:
            break
    return out


def _tool_purpose(path: str) -> str:
    """工具用途 = docstring 首段首行 (bat: 头部注释); 去 '工具名 — ' 前缀, 截断 100。"""
    if path.endswith(".bat"):
        comments = _bat_leading_comments(path, 1)
        first = comments[0] if comments else ""
    else:
        try:
            doc = ast.get_docstring(ast.parse(_read(path))) or ""
        except SyntaxError:
            doc = ""
        first = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
    head, sep, tail = first.partition(" — ")
    stem = os.path.splitext(os.path.basename(path))[0]
    if sep and (head in (stem, stem + ".py", stem + ".bat") or head.endswith((".py", ".bat"))):
        first = tail.strip()
    first = _normalize_text(first)
    return first[:100] + "…" if len(first) > 100 else first


def _argparse_rows(text: str) -> list[str]:
    """静态提取 add_argument 概要 (无 argparse 或 --help 失败时的回退)。"""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    rows: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        pos = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        kw: dict = {}
        for k in node.keywords:
            if isinstance(k.value, ast.Constant) and isinstance(k.value.value, (str, int, float)):
                kw[k.arg] = k.value.value
        if pos and pos[0].startswith("-"):
            label = ", ".join(pos)
        elif pos:
            label = str(kw.get("metavar", pos[0])).upper()
        else:
            label = "(arg)"
        help_text = str(kw.get("help", "")).strip()
        rows.append(f"  {label:<26}{help_text}"[:150])
    return rows


def list_tools() -> str:
    """开发工具索引 — 引擎仓 Utils/Dev (test_runner / thread_probe / i18n_tool ...)。"""
    root = _engine_root()
    if not root:
        raise ValueError("未找到引擎仓 (需含 Utils/Dev): 在引擎仓内运行, 或设置环境变量 MGE_ROOT")
    tools = _iter_tools(root)
    width = max((len(n) for n, _ in tools), default=12) + 2
    out = ["引擎开发工具 — Utils/Dev（用法: doc tool <名>; 均可直接命令行运行）", ""]
    for name, path in tools:
        purpose = _tool_purpose(path)
        out.append(f"  {name:<{width}}{purpose}" if purpose else f"  {name}")
    out.append("")
    out.append(f"定位: {root}  (MGE_ROOT 可覆盖)")
    return "\n".join(out)


def tool_help(name: str) -> str:
    """单工具用法 — argparse 工具实跑 --help (权威); 其余给 docstring/注释 + 静态概要。"""
    root = _engine_root()
    if not root:
        raise ValueError("未找到引擎仓 (需含 Utils/Dev): 在引擎仓内运行, 或设置环境变量 MGE_ROOT")
    raw = (name or "").strip()
    if not raw:
        raise ValueError("缺少工具名 (见 `doc tools`)")
    raw = raw.replace("/", " ").split()[-1]
    if raw.endswith((".py", ".bat")):
        raw = raw.rsplit(".", 1)[0]
    tools = dict(_iter_tools(root))
    path = tools.get(raw)
    if not path:
        close = [n for n in tools if raw.lower() in n.lower()]
        hint = f"; 相近: {', '.join(close)}" if close else ""
        raise ValueError(f"未知工具: {raw!r} (见 `doc tools`){hint}")
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    purpose = _tool_purpose(path)
    head = f"# {rel}" + (f" — {purpose}" if purpose else "")
    if path.endswith(".bat"):
        body = "\n".join(_bat_leading_comments(path)) or "(无头部注释)"
        return f"{head}\n\n{body}\n\n(批处理入口 — 直接运行; 无 --help)\n"
    text = _read(path)
    if "argparse" in text:  # 仅 argparse 工具才可安全实跑 --help (无 argparse 的脚本会真执行)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.run(
                [sys.executable, path, "--help"], cwd=root, env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30)
            real = (proc.stdout or "").strip()
            if proc.returncode == 0 and real:
                return f"{head}\n\n{real}\n"
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        doc = ast.get_docstring(ast.parse(text)) or ""
    except SyntaxError:
        doc = ""
    parts = [head, "", doc.strip() or "(无 docstring)"]
    rows = _argparse_rows(text)
    if rows:
        parts += ["", "参数概要 (静态提取):", *rows]
    parts += ["", "(静态概要 — 未取到真实 --help; 运行 `python <工具> --help` 验证)"]
    return "\n".join(parts) + "\n"

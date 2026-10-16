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
"""

from __future__ import annotations

import os
import re

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

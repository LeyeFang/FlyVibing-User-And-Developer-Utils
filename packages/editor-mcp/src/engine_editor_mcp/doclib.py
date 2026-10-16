"""内置文档 CLI — Doc/Dev 与 Doc/ExtDev 的只读服务层 (2026-10-16, Doc CLI 化第一章)。

设计:
  - 内容随 wheel 分发: ``docs_content/{dev,extdev}/<topic>.md`` (单一权威 = 工具仓);
    引擎仓 ``Doc/**`` 同名文件保留为"指针 stub"(提示内容在 CLI)。
  - 按二级标题 (``## ``) 分节读取; 目标是 agent **按节拉取**省 token
    (对照 node-editor ``get_rules`` 的渐进披露)。

用法:
  engine-editor-cli doc                     # 主题目录
  engine-editor-cli doc outline dev/x       # 章节目录
  engine-editor-cli doc show dev/x          # 全文
  engine-editor-cli doc show dev/x#3        # 第 3 节 (或 #标题片段)
  engine-editor-cli doc search 关键词        # 跨主题搜索
"""

from __future__ import annotations

import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs_content")
AREAS = ("dev", "extdev")

_H2 = re.compile(r"^##\s+(.*)$", re.MULTILINE)


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
    return m.group(1).strip() if m else topic


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


def list_all() -> str:
    topics = list(_iter_topics())
    if not topics:
        return "(docs_content 为空 — wheel 未打包文档数据)"
    lines = [f"{'topic':<44}{'节数':<6}{'行数':<6}标题"]
    for topic, path in topics:
        text = _read(path)
        n_sec = len(_H2.findall(text))
        n_line = text.count("\n") + 1
        lines.append(f"{topic:<44}{n_sec:<6}{n_line:<6}{_doc_title(text, topic)}")
    return "\n".join(lines)


def outline(topic: str) -> str:
    canon, path = resolve(topic)
    text = _read(path)
    lines = [f"# {canon} — {_doc_title(text, canon)}"]
    n = 0
    for title, body in _sections(text):
        if not title:
            lines.append(f"  (前言 {body.count(chr(10)) + 1} 行)")
            continue
        n += 1
        lines.append(f"  {n}. {re.sub(r'^[0-9]+[.、] *', '', title)}")
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

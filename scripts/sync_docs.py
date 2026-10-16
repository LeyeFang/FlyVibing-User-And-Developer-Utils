"""Doc CLI 化 — 迁移正文到 docs_content + 生成引擎侧指针 stub (工具仓脚本)。

用法（在工具仓根运行）:
  python scripts/sync_docs.py dev/ui_protocol dev/i18n_protocol   # 迁移指定主题
  python scripts/sync_docs.py --check                             # 校验 stub <-> 内容 一致
  python scripts/sync_docs.py --restub dev/x                      # 仅用内容重生成 stub（模板更新后）
  python scripts/sync_docs.py --dry dev/x                         # 预览不写盘

引擎仓根解析: --engine-root 参数 > MGE_ROOT 环境变量 > 默认 MyGameEngine-Python 路径。
迁移 = ①正文原样复制到 packages/editor-mcp/src/engine_editor_mcp/docs_content/<area>/<name>.md
      ②引擎仓 Doc/<Area>/<name>.md 改写为指针 stub (面对什么问题 / 去哪获得内容)。

stub 格式由 doclib 提取器驱动 (_doc_title/_purpose/_sections) — 与 CLI 索引同源，保证一致。
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_ROOT = os.path.dirname(HERE)
SRC_DIR = os.path.join(TOOLS_ROOT, "packages", "editor-mcp", "src")
sys.path.insert(0, SRC_DIR)

from engine_editor_mcp import doclib  # noqa: E402

CONTENT_DIR = doclib.DATA_DIR
AREA_DOCS = {"dev": "Doc/Dev", "extdev": "Doc/ExtDev"}
DEFAULT_ENGINE = r"c:\WorkSpace\FLY\MyGameEngine-Python"

STUB_TMPL = """# {title}

> ★ 本页正文已 CLI 化（{date}）。markdown 只做**大方向指引** —— 回答"这份文档面对什么问题 /
> 内容去哪获得"；具体内容按节走 CLI（避免整篇加载）。方案与进度：`Doc/Dev/doc_cli_plan.md`。

## 面对什么问题

{purpose}

## 去哪获得内容（逐级深入 —— 先索引后内容）

```powershell
engine-editor-cli doc                                   # 全部主题两级索引（先在这找）
engine-editor-cli doc outline {topic}                   # 本章节索引（标题 + 一行预览）
engine-editor-cli doc show {topic}#<节号|标题片段>      # 单节内容
engine-editor-cli doc search <关键词>                    # 跨主题检索
```

章节：{sections}

内容权威（唯一）：工具仓 `packages/editor-mcp/src/engine_editor_mcp/docs_content/{topic}.md`。
"""


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_stub(topic: str, text: str, date: str) -> str:
    title = doclib._doc_title(text, topic)
    purpose = doclib._purpose(text, topic)
    secs: list[str] = []
    for t, _b in doclib._sections(text):
        if t:
            secs.append(re.sub(r"^[0-9]+[.、] *", "", t))
    joined = " · ".join(f"{i} {t}" for i, t in enumerate(secs, 1)) or "（无二级章节）"
    return STUB_TMPL.format(title=title, date=date, purpose=purpose,
                            topic=topic, sections=joined)


def migrate(engine_root: str, topic: str, dry: bool) -> None:
    area, _, name = topic.partition("/")
    if area not in AREA_DOCS or not name:
        raise SystemExit(f"bad topic: {topic!r} (expect dev/<name> or extdev/<name>)")
    src = os.path.join(engine_root, AREA_DOCS[area], name + ".md")
    if not os.path.isfile(src):
        raise SystemExit(f"missing engine doc: {src}")
    text = _read(src)
    n_lines = text.count("\n") + 1
    content_dst = os.path.join(CONTENT_DIR, area, name + ".md")
    if "本页正文已 CLI 化" in text:
        raise SystemExit(
            f"{topic}: engine doc is already a stub — refusing to migrate "
            f"(would clobber content). Use --restub to refresh the stub.")
    stub = make_stub(topic, text, datetime.date.today().isoformat())
    if dry:
        print(f"[dry] {topic}: {n_lines} lines -> content; stub {len(stub)} chars")
        return
    _write(content_dst, text)
    _write(src, stub)
    print(f"[ok] {topic}: {n_lines} lines -> docs_content; stub {len(stub)} chars")


def restub(engine_root: str, topic: str, dry: bool) -> None:
    """仅从 docs_content 重生成引擎侧 stub（模板/提取器更新后用）。"""
    area, _, name = topic.partition("/")
    if area not in AREA_DOCS or not name:
        raise SystemExit(f"bad topic: {topic!r} (expect dev/<name> or extdev/<name>)")
    content_src = os.path.join(CONTENT_DIR, area, name + ".md")
    if not os.path.isfile(content_src):
        raise SystemExit(f"no content file: {content_src}")
    stub = make_stub(topic, _read(content_src), datetime.date.today().isoformat())
    dst = os.path.join(engine_root, AREA_DOCS[area], name + ".md")
    if dry:
        print(f"[dry] restub {topic}: stub {len(stub)} chars")
        return
    _write(dst, stub)
    print(f"[ok] restub {topic}: stub {len(stub)} chars")


def check(engine_root: str) -> int:
    fails: list[str] = []
    topics = list(doclib._iter_topics())
    for topic, _path in topics:
        area, _, name = topic.partition("/")
        stub_path = os.path.join(engine_root, AREA_DOCS[area], name + ".md")
        if not os.path.isfile(stub_path):
            fails.append(f"{topic}: engine stub missing")
            continue
        if f"doc show {topic}" not in _read(stub_path):
            fails.append(f"{topic}: stub lacks 'doc show {topic}' pointer")
    for f in fails:
        print("FAIL:", f)
    print(f"checked {len(topics)} topics, {len(fails)} fail")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("topics", nargs="*", help="dev/<name> | extdev/<name>")
    ap.add_argument("--check", action="store_true", help="仅校验 stub 与内容一致性")
    ap.add_argument("--dry", action="store_true", help="预览模式 (不写盘)")
    ap.add_argument("--restub", action="store_true",
                    help="仅从 docs_content 重生成 stub (模板更新后)")
    ap.add_argument("--engine-root", default=os.environ.get("MGE_ROOT", DEFAULT_ENGINE))
    ns = ap.parse_args()
    engine_root = os.path.abspath(ns.engine_root)
    if ns.check:
        return check(engine_root)
    if not ns.topics:
        ap.print_help()
        return 2
    fn = restub if ns.restub else migrate
    for topic in ns.topics:
        fn(engine_root, topic, ns.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

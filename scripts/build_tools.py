"""构建全部工具 wheel + CHECKSUMS，并把 `skills/` 同步进各包的打包负载。

用法:
    python scripts/build_tools.py            # 产出到 dist/
    python scripts/build_tools.py --no-sync  # 只构建（跳过 skills 同步）

约定（单一事实源）:
    skills/               权威源（agent 技能）
    → packages/editor-mcp/src/engine_editor_mcp/skills/        （engine-editor）
    → packages/node-editor/src/flyvibing_node_editor/skills/   （node-graph）
    打包负载同步后**不手改**；改技能只改 skills/ 再跑本脚本。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYNC_TARGETS = (
    (os.path.join("skills", "engine-editor"),
     os.path.join("packages", "editor-mcp", "src", "engine_editor_mcp", "skills", "engine-editor")),
    (os.path.join("skills", "node-graph"),
     os.path.join("packages", "node-editor", "src", "flyvibing_node_editor", "skills", "node-graph")),
)
PACKAGES = ("editor-mcp", "node-editor", "extension-kit")


def sync_skills() -> None:
    for src_rel, dst_rel in SYNC_TARGETS:
        src = os.path.join(ROOT, src_rel)
        dst = os.path.join(ROOT, dst_rel)
        if not os.path.isdir(src):
            print(f"  [skip] {src_rel} 不存在")
            continue
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        print(f"  [sync] {src_rel} -> {dst_rel}")


def build_wheels(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    wheels: list[str] = []
    for name in PACKAGES:
        pkg = os.path.join(ROOT, "packages", name)
        print(f"  [build] packages/{name}")
        rc = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", out_dir, pkg],
            capture_output=True, text=True)
        if rc.returncode != 0:
            print(rc.stdout[-800:])
            print(rc.stderr[-800:])
            raise SystemExit(f"build failed: {name}")
    for f in sorted(os.listdir(out_dir)):
        if f.endswith(".whl"):
            wheels.append(os.path.join(out_dir, f))
    return wheels


def write_checksums(wheels: list[str], out_dir: str) -> None:
    lines = []
    for w in wheels:
        h = hashlib.sha256(open(w, "rb").read()).hexdigest()
        lines.append(f"{h}  {os.path.basename(w)}")
    path = os.path.join(out_dir, "CHECKSUMS.sha256")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"  [sha256] {os.path.relpath(path, ROOT)} ({len(lines)} files)")


def main() -> int:
    out_dir = os.path.join(ROOT, "dist")
    print("== sync skills ==")
    if "--no-sync" not in sys.argv:
        sync_skills()
    print("== build wheels ==")
    wheels = build_wheels(out_dir)
    print("== checksums ==")
    write_checksums(wheels, out_dir)
    print(f"OK — {len(wheels)} wheel(s) in dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

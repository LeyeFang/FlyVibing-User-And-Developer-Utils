"""build_wheel.py — 零依赖 wheel 构建器（离线环境用）。

用法:
    python packages/node-editor/build_wheel.py
产物:
    packages/node-editor/dist/flyvibing_node_editor-<version>-py3-none-any.whl
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import zipfile

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(PKG_DIR, "src", "flyvibing_node_editor")
DIST = os.path.join(PKG_DIR, "dist")
NAME = "flyvibing-node-editor"
DIST_NAME = "flyvibing_node_editor"


def _version() -> str:
    with open(os.path.join(PKG_DIR, "pyproject.toml"), encoding="utf-8") as fh:
        match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def main() -> None:
    version = _version()
    wheel_name = f"{DIST_NAME}-{version}-py3-none-any.whl"
    os.makedirs(DIST, exist_ok=True)
    wheel_path = os.path.join(DIST, wheel_name)

    with open(os.path.join(PKG_DIR, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {NAME}\n"
        f"Version: {version}\n"
        "Summary: Offline node-graph tool: experiment spec -> graph JSON -> .scene injection\n"
        "License: MIT\n"
        "Requires-Python: >=3.10\n"
        "Description-Content-Type: text/markdown\n"
        "\n" + readme + "\n"
    ).encode("utf-8")
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: flyvibing-node-editor build_wheel.py\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    entry_points = (
        "[console_scripts]\n"
        "flyvibing-node-editor = flyvibing_node_editor.cli:main\n"
    ).encode("utf-8")

    dist_info = f"{DIST_NAME}-{version}.dist-info"
    files: list[tuple[str, bytes]] = []
    for root, dirs, fnames in os.walk(SRC):
        dirs[:] = [d for d in sorted(dirs) if d != "__pycache__"]
        for fname in sorted(fnames):
            if fname.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, SRC).replace(os.sep, "/")
            with open(full, "rb") as fh:
                files.append((f"{DIST_NAME}/{rel}", fh.read()))
    files.append((f"{dist_info}/METADATA", metadata))
    files.append((f"{dist_info}/WHEEL", wheel_meta))
    files.append((f"{dist_info}/entry_points.txt", entry_points))

    record_lines = [f"{path},{_hash(data)},{len(data)}" for path, data in files]
    record_lines.append(f"{dist_info}/RECORD,,")
    files.append((f"{dist_info}/RECORD", ("\n".join(record_lines) + "\n").encode("utf-8")))

    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in files:
            zf.writestr(path, data)

    print(f"[wheel] {wheel_path}")
    print(f"[wheel] files: {len(files)}  size: {os.path.getsize(wheel_path)} bytes")


if __name__ == "__main__":
    main()

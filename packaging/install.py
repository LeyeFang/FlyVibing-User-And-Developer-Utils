#!/usr/bin/env python3
"""Cross-platform installer for the FlyVibing Tools zip.

Usage:
    python install.py
    python install.py --workspace C:\\path\\to\\project
    python install.py --workspace . --profile full
    python install.py --dry-run
    python install.py --offline

The installer uses the interpreter that runs this file.  It installs the
bundled wheels into that interpreter (user site for a normal Python install,
the active environment for a venv), then optionally writes the engine-editor
skill and MCP configuration into ``--workspace``.
"""

from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
import sysconfig
from pathlib import Path

HERE = Path(__file__).resolve().parent
WHEELS = HERE / "wheels"
PACKAGES = (
    "engine-editor-mcp",
    "flyvibing-node-editor",
    "flyvibing-extension-kit",
)
WHEEL_STEMS = tuple(name.replace("-", "_") for name in PACKAGES)


def _tool_version() -> str:
    path = HERE / "VERSION"
    if not path.is_file():
        return "unknown"
    return path.read_text(encoding="utf-8").strip()


def _check_wheels() -> None:
    names = [p.name for p in WHEELS.glob("*.whl")] if WHEELS.is_dir() else []
    missing = [
        stem for stem in WHEEL_STEMS
        if not any(name.startswith(stem + "-") for name in names)
    ]
    if missing:
        raise SystemExit(
            "missing bundled wheels: " + ", ".join(missing)
            + f"\n  expected under: {WHEELS}"
        )


def _pip_command(offline: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "--disable-pip-version-check",
        "--find-links",
        str(WHEELS),
    ]
    if sys.prefix == sys.base_prefix:
        cmd += ["--user", "--no-warn-script-location"]
    if offline:
        cmd += ["--no-index", "--no-deps"]
    cmd.extend(PACKAGES)
    return cmd


def _run(cmd: list[str]) -> int:
    print(">> " + " ".join(cmd))
    return subprocess.call(cmd)


def _scripts_dir() -> Path:
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable).resolve().parent
    scheme = "nt_user" if os.name == "nt" else "posix_user"
    scripts = sysconfig.get_path("scripts", scheme=scheme)
    if scripts:
        return Path(scripts)
    return Path(site.getuserbase()) / ("Scripts" if os.name == "nt" else "bin")


def _on_path(scripts: Path) -> bool:
    target = os.path.normcase(os.path.abspath(str(scripts)))
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and os.path.normcase(os.path.abspath(entry)) == target:
            return True
    return False


def _setup_command(workspace: Path, profile: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "engine_editor_mcp.cli",
        "setup",
        "--workspace",
        str(workspace),
        "--profile",
        profile,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="workspace to receive skill + mcp.json")
    parser.add_argument("--profile", choices=("lite", "full"), default="lite")
    parser.add_argument("--no-setup", action="store_true",
                        help="install packages only; do not write workspace files")
    parser.add_argument("--offline", action="store_true",
                        help="only use bundled wheels (dependencies must already exist)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print(
            f"ERROR: Python 3.10+ is required, current is {sys.version.split()[0]}",
            file=sys.stderr,
        )
        return 2
    try:
        _check_wheels()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    version = _tool_version()
    print("=" * 58)
    print(f"  FlyVibing Tools {version} - installer")
    print("=" * 58)
    print(f"  Python : {sys.executable}")
    print(f"  Wheels : {WHEELS}")
    print()

    pip_cmd = _pip_command(args.offline)
    setup_cmd = None
    if args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
        if not workspace.is_dir():
            print(f"ERROR: workspace does not exist: {workspace}", file=sys.stderr)
            return 2
        setup_cmd = _setup_command(workspace, args.profile)
    elif not args.no_setup:
        print("[info] no --workspace given; packages will be installed without setup")
        print()

    if args.dry_run:
        print("[dry-run] " + " ".join(pip_cmd))
        if setup_cmd:
            print("[dry-run] " + " ".join(setup_cmd))
        return 0

    rc = _run(pip_cmd)
    if rc != 0:
        print()
        print("ERROR: package installation failed.", file=sys.stderr)
        print("  If this machine is offline, install mcp, Pillow and numpy first,",
              file=sys.stderr)
        print("  then rerun: python install.py --offline", file=sys.stderr)
        return rc

    verify = _run([
        sys.executable,
        "-c",
        (
            "import engine_editor_mcp, flyvibing_node_editor, "
            "flyvibing_extension_kit; "
            "from importlib.metadata import version; "
            "print('engine-editor-mcp', version('engine-editor-mcp')); "
            "print('flyvibing-node-editor', version('flyvibing-node-editor')); "
            "print('flyvibing-extension-kit', version('flyvibing-extension-kit'))"
        ),
    ])
    if verify != 0:
        print("ERROR: installed packages cannot be imported.", file=sys.stderr)
        return verify

    if setup_cmd:
        rc = _run(setup_cmd)
        if rc != 0:
            print("ERROR: workspace setup failed.", file=sys.stderr)
            return rc

    scripts = _scripts_dir()
    print()
    print("[ok] toolchain installed")
    print(f"[path] console scripts: {scripts}")
    if not _on_path(scripts):
        print("[note] add the path above to PATH to run engine-editor-cli directly")
    if setup_cmd is None:
        print()
        print("Next: register a workspace with:")
        print(f'  "{sys.executable}" -m engine_editor_mcp.cli setup --workspace <project>')
    else:
        print("[note] reload the IDE window (or restart MCP servers) to load the tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

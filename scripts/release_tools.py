"""Build the FlyVibing Tools zip release.

The release layout is::

    dist/releases/v<version>/any/
        FlyVibing-Tools-<version>.zip
        FlyVibing-Tools-<version>.zip.sha256
        release-manifest.json

The zip has one top-level folder containing the wheels, installers, docs and
the two checksum/manifest files.  ``any`` means the Python 3.10+ wheel set is
platform independent; the one-click installers select the local interpreter.

Usage::

    python scripts/release_tools.py
    python scripts/release_tools.py --skip-build
    python scripts/release_tools.py --version 0.5.0 --keep-stage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from build_tools import build_wheels, sync_skills  # noqa: E402

PRODUCT = "FlyVibing-Tools"
PLATFORM = "any"
PYTHON_REQUIRES = ">=3.10"
EXPECTED_PACKAGES = (
    "engine-editor-mcp",
    "flyvibing-node-editor",
    "flyvibing-extension-kit",
)
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "release"
RELEASE_ROOT = DIST / "releases"
ASSETS = (
    "install.cmd",
    "install.ps1",
    "install.sh",
    "install.py",
    "README-INSTALL.md",
    "engine-cli.cmd",
    "engine-cli.sh",
)
ROOT_DOCS = ("CHANGELOG.md", "LICENSE", "VERSION")


def _version_from_file() -> str:
    path = ROOT / "VERSION"
    if not path.is_file():
        raise SystemExit(f"missing VERSION file: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"invalid VERSION value: {version!r}")
    return version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(
            (name for name in archive.namelist()
             if name.endswith(".dist-info/METADATA")),
            None,
        )
        if metadata_name is None:
            raise SystemExit(f"wheel has no METADATA: {path}")
        text = archive.read(metadata_name).decode("utf-8", "replace")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith(("Name: ", "Version: ")):
            key, _, value = line.partition(": ")
            fields[key] = value.strip()
    try:
        return fields["Name"], fields["Version"]
    except KeyError as exc:
        raise SystemExit(f"incomplete wheel metadata: {path}") from exc


def _collect_wheels(wheels: list[Path]) -> tuple[list[Path], dict[str, str]]:
    selected: dict[str, Path] = {}
    versions: dict[str, str] = {}
    for wheel in sorted(wheels):
        name, version = _wheel_metadata(wheel)
        if name in selected:
            raise SystemExit(
                f"duplicate wheel for {name}: {selected[name].name}, {wheel.name}")
        selected[name] = wheel
        versions[name] = version
    missing = [name for name in EXPECTED_PACKAGES if name not in selected]
    if missing:
        raise SystemExit(f"missing wheels: {', '.join(missing)}")
    extra = [name for name in selected if name not in EXPECTED_PACKAGES]
    if extra:
        raise SystemExit(f"unexpected wheels: {', '.join(extra)}")
    return [selected[name] for name in EXPECTED_PACKAGES], versions


def _copy_assets(stage: Path, version: str) -> None:
    for name in ASSETS:
        src = PACKAGING / name
        if not src.is_file():
            raise SystemExit(f"missing packaging asset: {src}")
        text = src.read_text(encoding="utf-8") if name == "README-INSTALL.md" else None
        dst = stage / name
        if text is not None:
            dst.write_text(text.replace("{{VERSION}}", version), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
    for name in ROOT_DOCS:
        src = ROOT / name
        if not src.is_file():
            raise SystemExit(f"missing release document: {src}")
        if name == "VERSION":
            (stage / name).write_text(version + "\n", encoding="utf-8")
        else:
            shutil.copy2(src, stage / name)


def _write_checksums(stage: Path) -> None:
    lines = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file() or path.name == "CHECKSUMS.sha256":
            continue
        rel = path.relative_to(stage).as_posix()
        lines.append(f"{_sha256(path)}  {rel}")
    (stage / "CHECKSUMS.sha256").write_text(
        "\n".join(lines) + "\n", encoding="ascii")


def _zip_stage(stage: Path, bundle_name: str, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                rel = path.relative_to(stage).as_posix()
                archive.write(path, arcname=f"{bundle_name}/{rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="toolchain version (default: VERSION)")
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse existing wheels in dist/")
    parser.add_argument("--no-sync", action="store_true",
                        help="skip syncing skills/ into packages")
    parser.add_argument("--keep-stage", action="store_true",
                        help="keep build/release/stage for inspection")
    args = parser.parse_args()

    version = args.version or _version_from_file()
    version = version.lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise SystemExit(f"invalid version: {version!r}")

    BUILD.mkdir(parents=True, exist_ok=True)
    wheel_out = BUILD / "wheels"
    if args.skip_build:
        wheel_paths = sorted(DIST.glob("*.whl"))
        if not wheel_paths:
            raise SystemExit(f"no wheels in {DIST}; run without --skip-build")
    else:
        shutil.rmtree(wheel_out, ignore_errors=True)
        wheel_out.mkdir(parents=True)
        if not args.no_sync:
            print("== sync skills ==")
            sync_skills()
        print("== build wheels ==")
        wheel_paths = [Path(p) for p in build_wheels(str(wheel_out))]

    wheels, package_versions = _collect_wheels(wheel_paths)
    bundle_name = f"{PRODUCT}-{version}"
    stage = BUILD / "stage" / bundle_name
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    wheels_dir = stage / "wheels"
    wheels_dir.mkdir()
    for wheel in wheels:
        shutil.copy2(wheel, wheels_dir / wheel.name)

    _copy_assets(stage, version)
    files = [
        str(path.relative_to(stage)).replace("\\", "/")
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    ]
    files.extend(["CHECKSUMS.sha256", "release-manifest.json"])
    files = sorted(set(files))
    inner_manifest = {
        "product": PRODUCT,
        "version": version,
        "platform": PLATFORM,
        "python": PYTHON_REQUIRES,
        "built": date.today().isoformat(),
        "packages": package_versions,
        "files": files,
    }
    (stage / "release-manifest.json").write_text(
        json.dumps(inner_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _write_checksums(stage)

    release_dir = RELEASE_ROOT / f"v{version}" / PLATFORM
    release_dir.mkdir(parents=True, exist_ok=True)
    zip_path = release_dir / f"{bundle_name}.zip"
    zip_path.unlink(missing_ok=True)
    _zip_stage(stage, bundle_name, zip_path)

    digest = _sha256(zip_path)
    (release_dir / f"{bundle_name}.zip.sha256").write_text(
        f"{digest}  {zip_path.name}\n", encoding="ascii")
    outer_manifest = dict(inner_manifest)
    outer_manifest.update({
        "archive": zip_path.name,
        "sha256": digest,
        "size": zip_path.stat().st_size,
    })
    (release_dir / "release-manifest.json").write_text(
        json.dumps(outer_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    if not args.keep_stage:
        shutil.rmtree(stage.parent, ignore_errors=True)

    print(f"[release] {zip_path}")
    print(f"  sha256: {digest}")
    print(f"  packages: {', '.join(f'{k} {v}' for k, v in package_versions.items())}")
    print(f"  stage: {'kept' if args.keep_stage else 'cleaned'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

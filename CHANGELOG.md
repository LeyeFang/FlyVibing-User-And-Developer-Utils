# Changelog

All notable toolchain changes are recorded here. Package versions may move
independently; the toolchain release version is stored in `VERSION`.

## 0.5.0 (2026-10-24)

First zip-based toolchain release.

- Added `scripts/release_tools.py` to build and package all tool wheels into
  `dist/releases/v<version>/any/FlyVibing-Tools-<version>.zip`.
- Added one-click installers inside the zip: `install.cmd` / `install.ps1` for
  Windows and `install.sh` for macOS/Linux.
- `engine-editor-mcp` 0.5.0: lite/full profiles, CLI, skills, `engine_launch`
  and `engines` with automatic port negotiation.
- `flyvibing-node-editor` 0.1.0 and `flyvibing-extension-kit` 0.1.0 are bundled
  at their current independent versions.

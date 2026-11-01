# Changelog

All notable toolchain changes are recorded here. Package versions may move
independently; the toolchain release version is stored in `VERSION`.

## Unreleased

- Added `graph.remove_node` / `graph.unlink` / `console.tail` to the op registry
  (74 core ops); `references/ops.md` regenerated.
- `extdev/node_development.md` gained §8 “common graph/entity/time pitfalls”: iterative
  graph editing with the new remove ops, `TimeTrigger` edge semantics, per-frame rendering
  state, `entity.add` parenting, editor-vs-GL coordinates, and `console.tail` debugging.
- `rules.md` / `graph_flow.py`: `TimeDelay` removed, `TimeTrigger` documented as
  edge-triggered.

## 0.6.0 (2026-10-31)

Toolchain release aligned with FlyVibingEngine 1.0.2.

- `engine-editor-mcp` 0.6.0, `flyvibing-node-editor` 0.1.1,
  `flyvibing-extension-kit` 0.1.1.
- Added `docs/DEVELOPMENT_GUIDES.md` and `extdev` guides for extension UI, node packs, and
  Example development; extension docs now point to the tools repository as the single source.
- Documented the split distribution contracts: game export is on-demand from scene node
  types and honors `export:false`; the installer uses the mainline
  `Application/Functions/official_extensions.json` allowlist (never local fixtures, never
  dropping official extensions just because they opt out of game export). Both exclude
  `Application/Editor/Config` local state.
- Added community Example injection guidance: user examples live under
  `%APPDATA%/FlyVibingEngine/examples` (or `FVE_EXAMPLES_DIR`) with a
  `provider` signature in `.myproj`, never inside the mainline `Examples/` tree.
- Added extension-contributed Example guidance: `<extension_dir>/Examples/` is
  auto-discovered while the extension is enabled; extra roots use
  `capabilities:["examples"]` + `ctx.examples.register`; no copying into the
  user tree. `flyvibing-review` accepts the new `examples` capability key.
- Added node-pack `signature` guidance (`@Official` / `@ACME`; default
  `@Community`) and Example provider display rules.
- Expanded `ctx.graph` for extensions: owned-node retrieval, create/update/replace/
  remove, link management, and `request_redraw()`; documented ownership restrictions.
- Added `device.save` (71 core ops) for saving a device recording without stopping;
  documented `SaveDeviceData`, pump-before-save, unique tagged file names, and the
  legacy `session.save(scope)` fallback in `dev/device_io_protocol.md`.

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

# Changelog

All notable toolchain changes are recorded here. Package versions may move
independently; the toolchain release version is stored in `VERSION`.

## Unreleased

- Added `debug.events` (Settings ▸ Debug ▸ Terminal event reporting) — 75 core ops.
- Added `graph.remove_node` / `graph.unlink` / `console.tail` to the op registry
  (74 core ops); `references/ops.md` regenerated.
- `extdev/node_development.md` gained §8 “common graph/entity/time pitfalls”: iterative
  graph editing with the new remove ops, `TimeTrigger` edge semantics, per-frame rendering
  state, `entity.add` parenting, editor-vs-GL coordinates, and `console.tail` debugging.
- `rules.md` / `graph_flow.py`: `TimeDelay` removed, `TimeTrigger` documented as
  edge-triggered.

## 0.6.1 (2026-11-01)

Toolchain release aligned with FlyVibingEngine 1.0.4 (unreleased) — tooling-friction fixes.

- **Errors are now machine-readable.** `engine-editor-cli` writes a structured failure
  receipt to **stdout** (`{"ok": false, "error": "unknown_op", "op": ..., "suggest": [...]}`)
  and keeps stderr for human text only, so `2>$null` can no longer hide real errors.
  Exit codes stay 0 / 1 (op or connection failure) / 2 (usage, unknown op).
- **Silenced the startup warning.** Importing the MCP server no longer prints
  `pydantic_settings` `IncompleteFieldDefinitionWarning` on every CLI call.
- **Copy-pasteable examples.** `help <op>` shows real examples (`graph.link`,
  `graph.unlink`, `graph.remove_node`, `entity.transform`, `entity.add`, `scene.switch`,
  `entity.list`, `debug.events`); JSON placeholders prefer the literal written in the
  parameter docs instead of `{"k":1}`.
- **Coordinates are stated.** `entity.transform` documents editor coordinates (X right /
  Y forward / Z up, degrees) vs the GL order stored in `.scene`.
- **`entity.list with_transform=true`** — positions in one call instead of one
  `entity.get` per entity.
- **`scene.switch reload=true`** — the op never writes to disk; use `reload` (or
  `scene.load`) after editing a `.scene` file by hand.
- **`sim.play` pre-flight** — refuses to start when the graph contains unregistered node
  types (they are not evaluated, so the chain would break silently); `force=true` overrides.
- **Docs** — new topic `dev/scene_format` (`.scene` schema, `links` pin-id vs `graph.link`
  pin names, editor vs GL coordinates, hand-edit workflow) with an engine stub; CLI output
  contract + `probe`/`capture` framing in `dev/editor_live_protocol`; dev-vs-release
  extension loading in `extdev/extension_dev_protocol` §3.1; PATH guidance and the
  `engine-cli.cmd` / `engine-cli.sh` wrappers (shipped in the release zip).

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

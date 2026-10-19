# FlyVibing Utils

**Language:** English | [简体中文](docs/README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)

FlyVibing Utils is the authoring and automation toolchain for [FlyVibingEngine](https://github.com/LeyeFang/MyGameEngine-Python). It provides standalone Python packages for controlling a running editor, designing node graphs offline, and validating extensions, without modifying engine source.

> New to the toolchain? The [end-to-end tutorial](docs/TUTORIAL.md) covers an empty workspace, engine setup, graph authoring, and export.

## Packages

| Package | Entry points | Purpose | Editor required |
|---|---|---|---|
| **`editor-mcp`** | `engine-editor-cli`, `engine-editor-mcp` | Live editor control over the loopback command bus, available as a CLI and as an MCP server (lite/full profiles). | Yes |
| **`node-editor`** | `flyvibing-node-editor` | Offline pipeline from experiment spec to graph JSON to `.scene` injection; includes a rules reference, validation, and static flow inspection. | No |
| **`extension-kit`** | `flyvibing-review` | Static extension review and a headless Dear ImGui test harness. | No |

The `skills/` directory contains the source for the `engine-editor` and `node-graph` skills. The build synchronizes them into the `editor-mcp` and `node-editor` packages. `engine-editor-cli setup` installs the `engine-editor` skill and MCP configuration; the `node-graph` skill ships with `node-editor`.

## Requirements

- Python 3.10 or newer for all tooling.
- A running FlyVibingEngine editor for live operations. Offline graph authoring and extension review do not require the engine to be running.
- Engine source on `PYTHONPATH` when using `node-editor` validation, because validation reuses the engine's node registry and graph constraints. See [`packages/node-editor/README.md`](packages/node-editor/README.md).

## Installation

From the repository root:

```powershell
pip install -e packages/editor-mcp
pip install -e packages/node-editor
pip install -e packages/extension-kit
```

Wheels can also be built locally:

```powershell
python scripts/build_tools.py
```

This synchronizes the skills into `editor-mcp` and `node-editor`, builds the three wheels, and writes `dist/CHECKSUMS.sha256`.

## Quick start

### Live editor control

Start the editor and confirm the command server is ready (`[Live] Editor command server on 127.0.0.1:8977`).

```powershell
engine-editor-cli ops
engine-editor-cli call sim.state
engine-editor-cli call entity.add name=Cue
engine-editor-cli validate
engine-editor-cli capture pie --out frame.png
```

Register the MCP server and skills in a workspace:

```powershell
engine-editor-cli setup --workspace C:\path\to\project
```

Manual MCP configuration:

```json
{
  "servers": {
    "engine-editor-live": {
      "type": "stdio",
      "command": "engine-editor-mcp",
      "args": ["--profile", "lite"]
    }
  }
}
```

The lite profile exposes five tools (`engine_help`, `engine_call`, `engine_batch`, `engine_validate_graph`, `engine_capture`). The full profile preserves the legacy 44-tool surface.

### Offline node-graph authoring

The examples below assume a project containing `scenes/main.scene`, `spec.json`, and `ops.json`; substitute your own paths.

```powershell
flyvibing-node-editor rules
flyvibing-node-editor entities scenes/main.scene
flyvibing-node-editor build --spec spec.json --out graph.json
flyvibing-node-editor apply --scene scenes/main.scene --graph graph.json
flyvibing-node-editor flow --scene scenes/main.scene --event OnFrameUpdate
flyvibing-node-editor pins TimeTrigger
```

Validation uses the same implementation as the engine:

```powershell
python -m flyvibing_node_editor.node_graph_validator scenes/main.scene --frames 360
```

Incremental edits are supported through `apply-ops`:

```powershell
flyvibing-node-editor apply-ops --scene scenes/main.scene --ops ops.json          # dry run
flyvibing-node-editor apply-ops --scene scenes/main.scene --ops ops.json --write  # write after validation
```

### Extension review

Run from the engine repository root:

```powershell
flyvibing-review Application/Functions/SerialParallelDevice
flyvibing-review --all
```

Exit code 0 means no failures; exit code 1 means at least one failure and can be used directly in CI.

## Design boundaries

Node-graph behavior has one implementation and one source of rules:

| Concern | Offline `node-editor` | Live `editor-mcp` |
|---|---|---|
| Graph creation | Spec → graph JSON (reproducible, versionable) | Graph JSON import and interactive edits |
| Validation | Headless call into the engine implementation | `graph.validate.*` service inside the editor |
| Scene writes | Reads and writes `.scene` files (CI, batch, no GUI) | Live scene only; does not write scene files directly |

- Design-time and batch work use the offline tools; runtime and interactive work use the live tools.
- Direct `.scene` writes are restricted to the offline path to avoid concurrent writes from a running editor.
- `rules.md` is the reference documentation; validation logic is shared with the engine and not reimplemented in the tooling.

## Repository layout

| Path | Contents |
|---|---|
| `packages/editor-mcp/` | CLI and MCP server for live editor control |
| `packages/node-editor/` | Offline graph builder, validator, flow analyzer, and MCP server |
| `packages/extension-kit/` | Extension reviewer and headless ImGui helper |
| `skills/` | Source for the `engine-editor` and `node-graph` skills, synchronized into the packaged copies during build |
| `scripts/` | Build and documentation synchronization scripts |
| `docs/` | Tutorial and localized documentation |

## Development

```powershell
python scripts/build_tools.py           # sync skills, build wheels, write checksums
python scripts/build_tools.py --no-sync # build only
```

Skill sources live in `skills/`; the copies under `packages/*/.../skills/` are generated during the build.

Roadmap: extension type stubs (`ExtensionBase`/`ExtensionContext`) and templates under `sdk/`.

`extension-kit` and `node-editor` do not import editor internals. `node-editor` validation reuses `Application.Core.NodeGraph` from the engine to avoid rule drift; distribution details are covered in [`packages/node-editor/README.md`](packages/node-editor/README.md).

## Related repositories

| Repository | Scope |
|---|---|
| [**MyGameEngine-Python**](https://github.com/LeyeFang/MyGameEngine-Python) | Engine, editor, runtime, built-in modules, and engine development tools |
| **FlyVibing-User-And-Developer-Utils** (this repository) | Authoring and automation toolchain for engine projects |

## Documentation

| Document | Contents |
|---|---|
| [`docs/TUTORIAL.md`](docs/TUTORIAL.md) | End-to-end workflow: from an empty workspace to a design project and a runnable build |
| [`packages/editor-mcp/README.md`](packages/editor-mcp/README.md) | CLI/MCP profiles, operations, environment variables, and capture behavior |
| [`packages/node-editor/README.md`](packages/node-editor/README.md) | Offline graph workflows, incremental edits, aliases, and node groups |
| [`packages/extension-kit/README.md`](packages/extension-kit/README.md) | Static review rules and headless ImGui testing |
| Engine repository `Doc/Dev/` | Live protocol, node-graph protocol, and validation protocol |

## Contributing

Issues and pull requests are welcome. Graph rule changes must keep `rules.md`, the validator, and the engine-side adapter in sync.

## License

[MIT](LICENSE) © 2026 Leye Fang

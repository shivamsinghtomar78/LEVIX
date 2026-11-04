# levix-hello - the reference LEVIX plugin

The smallest third-party module that exercises the whole plugin contract: it registers
through an entry point, appears in `levix --help` and `levix plugins list`, receives the
core's `LevixContext`, and runs without touching a network or a disk outside the profile.

Read it top-down: `pyproject.toml` (registration) -> `src/levix_hello/__init__.py`
(the manifest, pure data) -> `src/levix_hello/cli.py` (the commands, imported late).

## Install it into a LEVIX environment

```bash
pip install -e plugin-examples/hello
levix plugins list          # hello now appears with origin "third_party"
levix hello greet levix
levix hi levix --times 3   # `hi` is the manifest's alias of `greet`, mounted by the router
levix hello where           # paths, configuration and this module's own history
```

`pip install -e` is enough because registration is one entry point in the
`levix.plugins` group; nothing registers by name, by folder, or by editing LEVIX.

`CommandInfo.aliases` become top-level shortcuts for the command they name -
`levix hi levix ...` reaches the same command as `levix hello greet levix ...`, because the
router prefixes the aliased subcommand when it forwards. The core uses the same mechanism for
`levix q` (an alias of `ai ask`) and `levix cmd` (an alias of `ai command`).

## What the manifest is for

| Field | Who reads it | Why |
| --- | --- | --- |
| `name` | the router | `levix <name>`; the registry keys everything on it |
| `title`, `summary` | `--help`, `levix plugins info`, the dashboard | listing without importing the module |
| `cli_path` | `ModuleRegistry.build_cli` | the one deferred import that builds the Typer app |
| `commands` | the router, the dashboard | help text and aliases that must match the real CLI |
| `requirements` | `levix.deps` gate | decides exit 3 (`MISSING_DEPENDENCY`) before any import is attempted |
| `extras`, `install_hint` | gate messages, `doctor` | how to get what is missing |
| `permissions` | `levix plugins info`, the dashboard | disclosure to a human, not enforcement (see below) |
| `ui` | the dashboard | `suspend`, `screen`, or `hidden` - this example hides itself |
| `documentation` | `levix plugins info`, the dashboard | where the real docs live |

`origin` and `provider` are **stamped by the registry**, never taken from the plugin: a
third party cannot declare itself `official`, and `provider` is the distribution that
actually provided the entry point.

## The two rules a plugin has to keep

1. **`__init__.py` stays pure data.** It is imported for every module during
   `levix --help`, so an import there runs on every single LEVIX invocation. Put heavy
   work in `cli.py`, behind `cli_path`.
2. **Read the environment from `ctx.obj`.** The core builds one `LevixContext` per
   process - paths, config, database, terminal profile, logger - and forwards it into
   the module's own click context. A plugin that re-derives its own defaults will
   disagree with `levix config show`.

## Limits this example is honest about

- **`permissions` is disclosure, not a sandbox.** A plugin is ordinary Python inside the
  LEVIX process: it can import `os`, open any path, and make any request. The declared
  set is what LEVIX *shows you* so a human can decide before installing. Do not treat
  it as a security boundary.
- **A plugin cannot add configuration keys.** `levix.config.SCHEMA` is owned by the
  core and unknown keys are rejected, so `hello.*` would be a config error. This example
  therefore reads only core keys (`general.theme`, `general.history_limit`). Namespaced
  plugin configuration is a core feature that is not built yet - see
  `docs/roadmap/CURRENT_STATUS.md`.
- **The dependency gate is the module's own callback.** `levix.deps.ensure_dependencies`
  is not part of `levix.sdk` yet, so a plugin that declares `requirements` has to call
  the gate from its Typer callback the way the official modules do (see
  `src/levix/modules/tube/cli.py`), or its missing package surfaces as an `ImportError`
  instead of exit 3 with an install hint.

## Licence

MIT, the same as LEVIX.

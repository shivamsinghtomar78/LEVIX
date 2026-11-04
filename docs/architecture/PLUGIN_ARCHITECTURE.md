# Plugin architecture

LEVIX has one extension mechanism: Python entry points in the distribution metadata
group `levix.plugins`. There is no plugin directory, no `sys.path` scanning, no
hot-reload and no sandbox.

## Discovery

| Item | Value | Where |
|------|-------|-------|
| Group | `levix.plugins` | `registry.GROUP` |
| Declared by LEVIX itself | seven entries, each `NAME = "levix.modules.<pkg>:MANIFEST"` | `pyproject.toml` `[project.entry-points."levix.plugins"]` |
| Lookup | `importlib.metadata.entry_points(group="levix.plugins")` | `registry._entry_points` |
| Test injection | `ModuleRegistry(extra_entry_points=(EntryPoint…))` | `registry.py:34`, merged at `registry.py:75-76` |
| Cache | `discover()` fills `self._cache` once per registry | `registry.py:38-73` |
| Deliberately absent | "no `sys.path` scanning and no drop-in folder import in this phase, because standard metadata entry points already answer 'what is installed'" | `registry.py:3-7` |

For each entry point:

| Step | Code | Behaviour |
|------|------|-----------|
| 1 | `entry_point.load()` | imports the target and returns the object; for official modules this executes only `modules/<x>/__init__.py`, which is pure data |
| 2 | `isinstance(manifest, ModuleManifest)` | anything else becomes a broken manifest with a `TypeError` explanation |
| 3 | `provider = entry_point.dist.name` | the distribution that shipped the entry point; wrapped in `try/except` because metadata is best effort |
| 4 | `origin = _origin_for(provider, name)` | `OFFICIAL` only when `provider == "levix"`, or when `provider == ""` and the name is in `OFFICIAL_NAMES` (the test-injection path) |
| 5 | `replace(manifest, origin=…, provider=…, version=…)` | a stamped copy; the author's own `origin` and `provider` values are overwritten |
| 6 | key = `manifest.name or entry_point.name` | so the entry-point name and the manifest name may differ (`game` → `levix.modules.arcade`) |

A plugin cannot claim to be official: `tests/test_registry.py::test_a_plugin_cannot_claim_to_be_official`
asserts it, and the mechanism is that step 4 and 5 always run against `entry_point.dist`.

### Failure isolation

| Failure | Result |
|---------|--------|
| `load()` raises anything | `_broken(entry_point, exc)` → a manifest with `cli_path=""`, `summary="failed to load: <Type>: <exc>"`, correct origin and provider |
| returns a non-manifest | `_broken` with `TypeError("entry point returned X, not ModuleManifest")` |
| `entry_point.dist` unavailable | `provider=""`; origin falls back to the `OFFICIAL_NAMES` test |
| version metadata missing | `""` shown as `-` by `plugins list` |

`is_broken(manifest)` is `not manifest.cli_path`. A broken module is still listed, still
described, still counted by `doctor` as `MISSING`, and never crashes LEVIX. The comment at
`registry.py:47-48` states the rule: "A broken plugin must not make LEVIX unstartable."

## Loading and running

| Concern | Decision |
|---------|----------|
| Where the plugin's code is first imported | `registry.build_cli(manifest)` — `_resolve(manifest.cli_path)` — "The single deferred-import site for module CLIs" (`registry.py:94-97`) |
| Format of `cli_path` | `"package.module:attribute"`; `partition(":")`, then `importlib.import_module` and `getattr`. With no colon the module object itself is returned |
| Who calls it | `router._forward`, once per invocation |
| Screens | `registry.build_screen(manifest)` resolves `UiSpec.screen_path`; it raises `LookupError("module 'x' declares no dashboard screen")` when absent, and no manifest in the tree uses it |
| Isolation | none. The plugin's `build_app()` runs in LEVIX's interpreter, with LEVIX's import access and the invoking user's filesystem and network rights |

## The SDK

`levix/sdk.py` is 44 lines of re-exports and contains no logic, by design: "A façade with
re-exports gives plugin authors an API we can promise not to break, without a parallel
implementation that could drift from the real one."

| Exported | Kind |
|----------|------|
| `ModuleManifest`, `CommandInfo`, `PackageRef`, `Permission`, `Origin`, `UiSpec` | contract |
| `LevixContext` | the object a command receives as `ctx.obj`: `paths`, `config`, `database`, `profile`, `logger`, `value()`, `probe()`, `secret()`, `glyph()` |
| `LevixError`, `DependencyError`, `UnknownModuleError`, `ConfigError`, `UserCancelledError`, `ExternalToolError`, `ProviderError` | errors whose `exit_code` the entry point honours |

A plugin may therefore read configuration, open the shared database, resolve a secret,
check a capability and pick a glyph without touching a private module. Anything not in
`__all__` is internal.

## Permissions are disclosure, not enforcement

`ModuleManifest.permissions` is a `frozenset[Permission]` of seven values
(`module.py:25-35`). The engine never
consults it on a code path that grants or refuses a capability. The only places it is
read are two display functions:

| Surface | What it prints |
|---------|----------------|
| `levix plugins info NAME` | `permissions: audio, fs_read, network, subprocess` and, for a `THIRD_PARTY` module that declares any, the sentence "note: declared permissions are a promise by the author, not an enforced limit. Python plugins can do anything LEVIX can." (`plugins_cmd.py:84-91`) |
| dashboard `_describe` | `permissions <values>` when the set is non-empty (`dashboard/app.py:284-286`) |

Full analysis, per-module table and the honest limits: `../security/PERMISSIONS.md`.

## What `levix create-module` really generates

The scaffold is the same shape the official modules use, so that "scaffolding a module
and loading its manifest through the real registry is the only way to know the SDK is not
fiction" (`create_module_cmd.py:5`).

| Path | Content |
|------|---------|
| `pyproject.toml` | hatchling `>=1.33`, `name = "levix-<name>"`, `version = "0.1.0"`, `requires-python = ">=3.12"`, `license = "MIT"`, `dependencies = ["levix>=0.4"]`, `[project.entry-points."levix.plugins"] <name> = "levix_<name>:MANIFEST"`, `dev = ["pytest>=9", "ruff>=0.17"]`, wheel `packages = ["src/levix_<name>"]` |
| `src/levix_<name>/__init__.py` | `MANIFEST` with one `CommandInfo(name="hello", …)`, `cli_path="levix_<name>.cli:build_app"`, `version="0.1.0"`, `requirements=()`, `permissions=frozenset({Permission.FS_READ})`, `documentation="README.md"`, plus a `build_app()` that imports `levix_<name>.cli` inside its body |
| `src/levix_<name>/cli.py` | `typer.Typer(name, help=MANIFEST.summary, no_args_is_help=True)` with a `hello` command printing through `rich.console.Console` |
| `README.md` | development install steps and the rule "Heavy imports belong inside command functions, never at module scope." |
| `tests/test_manifest.py` | asserts `MANIFEST.name`, that `cli_path.endswith(":build_app")`, `command_names() == ("hello",)`, and that `build_app()._name` matches |

Rules and guards:

| Guard | Behaviour |
|-------|-----------|
| name pattern | `^[a-z][a-z0-9_-]{1,29}$`, else `ConfigError` (exit 5) |
| non-empty target without `--force` | `ConfigError`, "Refusing to overwrite" |
| non-empty target with `--force` | `require_approval(…, destructive=True)` — a typed `DELETE`, `--yes` cannot substitute — then `shutil.rmtree` |
| package name | `"levix_" + name.replace("-", "_")` |
| closing message | "Third-party plugins run with LEVIX's full privileges. See docs/security/PERMISSIONS.md and docs/architecture/PLUGIN_ARCHITECTURE.md." (`create_module_cmd.py:74-75`) |

## Installation and removal are not implemented

`commands/plugins_cmd.py:1-8` states the position: third-party Python code executes with
LEVIX's full privileges, and the consent flow plus the pipx/frozen-environment questions
must be settled before a command that installs arbitrary code can honestly exist. The
command surface is therefore `list` and `info` only; there is no `install`, `uninstall`,
`dev`, `test`, `package` or `publish`. A plugin is installed by pip or pipx into the same
environment as LEVIX, which is the only supported route, and `levix doctor` and
`levix plugins list` are how you notice what arrived.

| Question | Current answer |
|----------|----------------|
| Where does a plugin's code run? | in-process, same interpreter, same privileges |
| Version pinning? | the template suggests `levix>=0.4`; nothing enforces a compatibility range at load time |
| Signing or provenance? | none. `provider` is the distribution name, which the publisher chooses |
| Revocation? | `pip uninstall` |
| Capability limits? | none (disclosure only) |
| Isolated build? | the scaffold is a normal hatchling project, so yes for packaging, not for running |

## Known gaps

1. **The gate is not part of the template.** Every official module registers a Typer
   `callback=_gate` calling `deps.gate(MANIFEST)` (`tube/cli.py:49-52` is the shortest);
   the generated `cli.py` has neither, and its manifest declares `requirements=()`. A
   plugin that later adds a requirement gets no exit-3 message and instead raises
   `ImportError` at `build_cli` time — exit 1 with a traceback. `plugin-examples/hello`
   requires nothing, so it does not demonstrate the gate either: an author with an
   optional dependency has to read an official module to find the pattern.
2. **The generated `hello` command has no parameter model in the manifest** (correct, per
   `CommandInfo`'s docstring) but also no `aliases` demonstration, so nothing in the
   scaffold exercises the alias path in `router.register_modules`.
   `plugin-examples/hello` does: its `greet` command declares `aliases=("hi",)`, and
   `tests/test_plugin_example.py` runs `levix hi alias --times 3` through the real router.
3. **`mode="screen"` and `screen_path` are unreachable in practice.** No manifest sets
   them, `build_screen` is only tested for its failure branch
   (`tests/test_registry.py:166-169`), and the dashboard has no code path that calls it.
   Documented API surface, unimplemented capability.
4. **Origin stamping trusts the distribution name.** `_origin_for` treats
   `provider == "levix"` as official, which is correct, but the fallback
   `provider == "" and name in OFFICIAL_NAMES` also marks official any entry point whose
   metadata cannot be read. In a malformed environment a same-named plugin could inherit
   official status; `OFFICIAL_NAMES` is a closed set, so the exposure is limited to those
   seven names — but it means a plugin shadowing `tube` with unreadable metadata is
   displayed as official and gets `pip install "levix[…]"` hints.
5. **`levix plugins info` shows `cli entry`** — the manifest's `cli_path` string — which
   discloses nothing sensitive but also validates nothing: an author may point it at any
   importable attribute of any installed package.
6. **No version-compatibility check exists between a plugin and LEVIX.** `discover()`
   loads whatever the entry point resolves to; a plugin built against a future
   `ModuleManifest` with new required fields fails at construction and becomes a broken
   manifest. That is the intended graceful outcome, but there is no warning before it.

### Three gaps that used to be here are closed

- **`LevixModuleProtocol` is gone.** It sat in `module.py`, exported through `levix.sdk`,
  declared `manifest()` / `build_command()` raising `NotImplementedError`, described itself as
  "the shape `levix create-module` scaffolds" while the scaffold emits a `MANIFEST` object and a
  `build_app()` function instead, and was implemented by nothing — not the seven official
  modules, not `plugin-examples/hello`. A loader never reads a class, only `cli_path`, so the
  name was an affordance that did nothing. `levix.sdk` now re-exports 14 names.
- **`plugin-examples/` exists.** `plugin-examples/hello/` is an installable hatchling
  distribution (`pyproject.toml`, `README.md`, `src/levix_hello/{__init__.py,cli.py}`)
  declaring one `levix.plugins` entry point. `tests/test_plugin_example.py` registers it
  for real — it writes a `levix_hello-0.1.0.dist-info` directory with `METADATA` and
  `entry_points.txt` into a temp dir, puts that dir and the example's `src/` on `sys.path`,
  and then runs the actual router over it: discovery as `THIRD_PARTY` with
  `provider="levix-hello"`, `levix hello greet levix`, `levix hi alias --times 3`,
  `levix plugins list`, the shared history a plugin reads back, and the proof that loading
  the manifest does not import `levix_hello.cli`. No pip, no network, no mocks. The path is
  listed in `[tool.hatch.build.targets.sdist]`, and the sdist build succeeds with it
  present.
- **The documents those commands point at exist.** `create-module`'s closing message names
  `docs/security/PERMISSIONS.md` and `docs/architecture/PLUGIN_ARCHITECTURE.md`
  (`create_module_cmd.py:74-75`), and `commands/plugins_cmd.py:1-8` names this page plus
  `docs/roadmap/CURRENT_STATUS.md`. There is no `docs/plugins/` directory and nothing
  references it.

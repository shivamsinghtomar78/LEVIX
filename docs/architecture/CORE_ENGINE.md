# Core engine

One file per responsibility, in `src/levix`. The engine knows the words "module" and
"manifest"; it does not know what a playlist, a score or a subtitle is. This document
states what each file owns, what it may import and what it must never do.

## Import budget

The engine's most important property is what it refuses to import.

| Trigger | Verified imports present afterwards | Absent |
|---------|--------------------------------------|--------|
| `levix --help` | `typer`, `typer._click`, `rich.*`, `tomlkit`, `tomllib`, `platformdirs`, `sqlite3` | `textual`, `yt_dlp`, `psutil`, `soundfile`, `sounddevice`, `httpx`, `keyring` and every module package (`levix.modules.*`) |
| `levix tube --help` | the above plus `typer`/`rich` for the sub-app and `yt_dlp`? — no: `levix tube -h` still does not import yt-dlp because `build_app()` in `modules/tube/cli.py` only imports `core` lazily inside command bodies (`_make_ydl`) | `yt_dlp` |

Honest caveat on the "only typer/rich/click" shorthand: it is not literally true.
`app.py` imports `config`, `context`, `logging_setup`, `paths` and `storage` at module
scope, so `levix --help` also pays for `tomlkit`, `platformdirs` and `sqlite3`. What is
true, and what the design guarantees, is that **help touches no module dependency and no
Textual** — see invariant 1 in `SYSTEM_ARCHITECTURE.md`. `sqlite3` is imported
because `LevixContext` is constructed with a `Database` handle whose module imports the
driver.

`levix --help` also touches no files: `--help` is an eager option, so click exits before
the root callback that would call `build_context()` (`app.py:24-29`).

## Files

| File | Owns | Public surface | Must never |
|------|------|----------------|------------|
| `__init__.py` | package identity, 24 lines | `__version__` via `__getattr__`, resolved lazily through `importlib.metadata`, `"0.0.0+unknown"` in a source checkout | import `importlib.metadata` at module scope (the docstring records that it measurably slows `--help`) |
| `__main__.py` | `python -m levix` | `sys.exit(main())` | do anything else |
| `app.py` | the Typer root: options, eager platform commands, `config`/`plugins` sub-groups, module registration | `APP_HELP`, `build_context`, `build_app(registry=None)` | import any `levix.modules.*` package or `levix.dashboard` at module scope |
| `main.py` | context creation, invoke, exception classification, best-effort history, timing | `main(argv) -> int` | let an unexpected exception escape to the interpreter |
| `router.py` | turning manifests into thin click commands and forwarding argv | `register_modules(app, registry)` | subclass or monkeypatch click; import a module to register it |
| `registry.py` | entry-point discovery, origin/provider/version stamping, deferred CLI construction, the process-level accessor | `ModuleRegistry`, `GROUP`, `OFFICIAL_NAMES`, `OFFICIAL_DISTRIBUTION`, `active()`, `use()`, `is_broken()` | trust a plugin's self-declared `origin`; scan `sys.path`; import a module during `discover()` |
| `module.py` | the registration contract | `ModuleManifest`, `CommandInfo`, `PackageRef`, `Permission`, `Origin`, `UiSpec` | import anything except `dataclasses`, `enum`, `typing`; a second contract shape no loader reads |
| `sdk.py` | the stable public name for plugin authors | 14 re-exports in `__all__` | contain a single line of logic |
| `context.py` | the one dependency-injection object | `LevixContext` slots dataclass: `paths`, `config`, `database`, `profile`, `logger`, `value`, `probe`, `secret`, `store_secret`, `forget_secret`, `glyph` | hold user data or a live child handle; log a secret value (`context.py:38-55` logs names, sources and a removal flag only) |
| `config.py` | four-layer resolution and validation | `SCHEMA`, `Spec`, `Config`, `ResolvedValue`, `is_secret_key`, `read_user_document`, `write_user_value`, `remove_user_value` | consult a config file for a secret; use pydantic; rewrite the user's file without `tomlkit` |
| `paths.py` | platform filesystem locations | `APP_NAME`, `Paths`, `resolve_paths(app=APP_NAME)` | hardcode a home directory; create a directory outside `Paths.ensure()` |
| `storage.py` | the shared SQLite file and migration ledger | `Database`, `MIGRATIONS`, `SCHEMA_TABLE`, `Migration`, `_core_v1` | cache a connection across calls; accept a module's SQL at runtime |
| `deps.py` | the single answer to "is this installed?" | `Availability`, `PackageStatus`, `check`, `resolve`, `missing`, `ensure_dependencies`, `gate` | let another file write `try: import x except ImportError` for availability; depend on `packaging` |
| `errors.py` | the exception hierarchy and the exit-code table | 10 `EXIT_*` constants, `EXIT_CODE_MEANINGS`, 7 exception classes | define a new exit code without adding it to `EXIT_CODE_MEANINGS` |
| `terminal.py` | what the console can render | `TerminalProfile`, `detect`, `glyphs`, `active_glyphs`, `bar`, `encode_safe`, `_windows_vt_enabled` | emit a box-drawing character without asking `active_glyphs()` |
| `spawn.py` | running LEVIX again as a child | `is_frozen`, `levix_argv`, `run` | build a shell string |
| `secrets.py` | secret resolution and the hardened fallback file | `SERVICE`, `backend`, `get_secret`, `set_secret`, `delete_secret`, `env_var_for` | describe the file fallback as encryption; store a secret in config |
| `approve.py` | the one confirmation gate | `require_approval(action, detail, *, assume_yes, destructive, prompt_word)` | treat non-interactive stdin as consent |
| `capabilities.py` | "can this machine do it?" | `Status`, `ProbeResult`, `register`, `probe`, `report`, 10 probes | raise out of `probe()`; invent a value the platform cannot supply |
| `doctor.py` | the single definition of healthy | `Finding`, `environment`, `modules`, `capabilities_report`, `build_report`, `worst_status`, `exit_code_for` | be a second availability oracle (it calls `deps.resolve`) |
| `logging_setup.py` | redacted, rotating diagnostics | `LOGGER_NAME`, `RedactFilter`, `setup`, `get_logger` | write to stdout |
| `data/defaults.toml` | packaged defaults, one key per `SCHEMA` entry | 21 values across 9 sections | omit a key: `Config.load` raises `ConfigError("packaged defaults are missing s.k")` |
| `commands/*` | platform commands, not module commands | six Typer callables | import a module package |
| `dashboard/*` | the Textual front end | `LevixDashboard`, `ModuleRow`, `recent_lines`, theme registry | decide availability itself; run module code in-process |

## Capability probes registered in `capabilities.py`

| Probe | Reports | When it says `UNSUPPORTED` |
|-------|---------|----------------------------|
| `ffmpeg` | path from `shutil.which` | never (missing says `MISSING`) |
| `media_player` | first of mpv, vlc, ffplay, mplayer | never |
| `audio_output` | sounddevice + soundfile present | never |
| `psutil` | installed / not | never |
| `temperature` | sensor names from psutil | when psutil exposes no thermal sensor |
| `battery` | percent and time left | when no battery is reported |
| `gpu` | — | always: "LEVIX has no GPU probe that is honest on every platform" |
| `keyring` | backend class name | when the extra is absent the status is `DEGRADED` |
| `terminal` | columns × rows, ANSI state | never; a pipe is `DEGRADED` |
| `platform` | system, release, machine | never |

`probe()` never raises: an unregistered name returns `UNSUPPORTED`, and a probe that
throws is reported as `DEGRADED` with the exception type and message.

## Terminal as an architectural constraint

`terminal.detect()` decides unicode support from `"utf" not in encoding.lower()`. That
is not cosmetic. On a Windows console whose Python encoding is cp1252, writing U+2588
raises `UnicodeEncodeError` inside Rich's win32 writer — a crash, not a glyph problem —
and the same writer rejects the emoji and non-Latin names that remote sites put in
video titles. Consequently:

| Rule | Mechanism |
|------|-----------|
| No renderer embeds a box-drawing character directly | `active_glyphs()`, `@lru_cache(maxsize=1)` |
| No progress bar is built by hand | `bar(percent, width=20)` with thresholds at 60% and 85% |
| Text from outside the terminal is adapted before printing | `encode_safe()`: control characters become `\xNN`, unencodable characters are backslash-replaced, everything is forced onto one line |
| Rich markup in foreign text is inert | `terminal.markup_safe()` is `escape(str(value))`; each module wraps it with the encoding half in its own render helper — `_show` (`tube/cli.py:38`, `hacker/cli.py:33`, `music/cli.py:105`, `ai/cli.py:58`), `show` (`files/cli.py:49`), `terminal.markup_safe` directly in systempulse, `plugins_cmd` and the dashboard — and `main._plain` (`main.py:108-124`) escapes error text line by line |
| Raw ANSI is only emitted after the console has been asked for VT | `_windows_vt_enabled()` sets `ENABLE_VIRTUAL_TERMINAL_PROCESSING` (`0x0004`) and never raises |

## Dependency gate

`deps.gate(manifest)` is called from every module's Typer callback, so
`levix <module> <anything>` fails before argument parsing reaches business logic. It
resolves the manifest through `registry.active().get(name)` first (`deps.py:135-147`) and
falls back to the local copy: the registry's stamped copy carries `origin` and
`provider`, and `resolved_install_hint()` needs them to turn `extras=("tube",)` into
`pip install "levix[tube]"`. Gating the module's own un-stamped constant produced "no
install hint is declared for this module" for an official module — true, and useless.

| Status | Meaning | `describe` |
|--------|---------|------------|
| `INSTALLED` | importable and a known version satisfying `minimum` | `"<dist> <version>"` |
| `MISSING` | `find_spec` failed | `"<dist> is not installed"` |
| `TOO_OLD` | numeric prefix below `minimum` | `"<dist> <v> is older than the required <m>"` |
| `UNCERTAIN` | importable, but no version metadata or an unparseable version | `"<dist> importable but version unknown"` |

`satisfied` is true for `INSTALLED` and `UNCERTAIN`. `UNCERTAIN` counts as satisfied by
design: refusing to run because a version string cannot be parsed would be worse than
trying. `_version_tuple` compares only the leading numeric components, which is enough
for the pins actually used (`psutil>=7.2`, `soundfile>=0.14`, `sounddevice>=0.5`) and
avoids a permanent `packaging` dependency.

Failure message shape, which is the only place this text is built:

```text
error: module 'tube' needs yt-dlp is not installed
  install it with: pip install "levix[tube]"
```

exit code 3, because `DependencyError.exit_code = EXIT_MISSING_DEPENDENCY`.

## Context plumbing

`ctx.obj` is the only channel from the root callback to a command, and forwarding it is
load-bearing rather than decorative:

```python
result = command.main(
    args=[*prefix, *ctx.args],
    prog_name=f"levix {manifest.name}",
    standalone_mode=False,
    obj=ctx.obj,
)
```

`router.py:90-98` explains why: `command.main()` starts a brand-new click context with
no parent, so without `obj` the `LevixContext` built by the root callback stops at the
forwarding command and every module would read its `tube.*` / `music.*` configuration as
the built-in fallback. `prefix` is empty for a module's own name and holds the canonical
subcommand when the invocation arrived through a manifest alias, which is what makes
`levix q hello` arrive as `levix ai ask hello` (`router.py:54-61`).

## Known gaps

* `registry.py` is the only piece of process-level mutable state (`_ACTIVE`,
  `active()`, `use()`). It is deliberate and commented — click instantiates the group
  class itself, so a registry cannot be threaded through a constructor — but it does
  mean two callers of `build_app()` in one process share a registry unless one of them
  injects. The dashboard's `action_reload` installs a fresh `ModuleRegistry` for exactly
  this reason (`dashboard/app.py:194-197`).
* `capabilities.py` registers ten probes, while module manifests list capability names
  that are not probes at all: `yt-dlp`, `progress-hooks`, `ffmpeg-gate`,
  `external-player`, `libsndfile`, `portaudio`, `openai-compatible`, `ollama`,
  `sse-streaming`, `ndjson-streaming`, `rich-live`, `ipconfig`, `getadapterconfig`,
  `route`, `ip`, `ifconfig`, `resolv-conf`, `hosts-file`. Nothing compares the two lists:
  `doctor` runs `capabilities.report()` over its own ten names (`doctor.py:94-98`) and
  never asks about a manifest's, and the only reader of `manifest.capabilities` anywhere
  in the tree is one assertion in `tests/modules/test_systempulse.py:420`. So
  `capabilities` is descriptive metadata with no consumer — `probe("yt-dlp")` would answer
  `UNSUPPORTED: no probe registered for 'yt-dlp'`, but no command calls it that way.
* `context.py` exposes `probe()` and `glyph()`; no official module command calls either —
  modules use `terminal` and `capabilities` directly or read `ctx.profile`. The one caller
  in the tree is the example plugin's `greet`
  (`plugin-examples/hello/src/levix_hello/cli.py:53`), which is the proof that the channel
  reaches third-party code.
* `deps.check` maps an import name to a distribution via `packages_distributions()`
  when `dist_name` is not declared, which is a full metadata scan per call. Tube and
  Arcade declare the pair explicitly (`PackageRef("yt_dlp", "yt-dlp")`); the AI
  manifest declares only `PackageRef("httpx")`, relying on the scan.
* No `levix --help` fast path exists for `sqlite3`. If startup cost ever matters,
  `Database` would need to become a lazy handle; nothing in the tree does this today.

# Module architecture

A LEVIX module is one package under `src/levix/modules/` that supplies a pure-data
manifest and a lazily imported Typer app. This document states the contract, the rules
that make lazy loading work, and a complete walk-through of one module (`tube`).

## The contract

`src/levix/module.py` defines it, `src/levix/sdk.py` re-exports it, and both official
modules and third-party plugins implement exactly the same shape.

| Field | Type | Required | Read by | Notes |
|-------|------|----------|---------|-------|
| `name` | `str` | yes | router, dashboard, database namespace | the command token; `monitor` and `game` differ from their package names `systempulse` and `arcade` |
| `title` | `str` | yes | help, dashboard, error text | display name, e.g. "SystemPulse" |
| `summary` | `str` | yes | root help, sub-app help | the only text the root ever shows for a module |
| `cli_path` | `str` | yes | `registry.build_cli` | `"levix.modules.tube.cli:build_app"`; `""` marks a broken module |
| `commands` | `tuple[CommandInfo, …]` | yes | router aliases, module `build_app`, dashboard | `CommandInfo(name, help, aliases=())` |
| `version` | `str` | no (default `""`) | `plugins list` | empty means "take it from the distribution"; official modules therefore show `0.4.0` |
| `requirements` | `tuple[PackageRef, …]` | no | `deps`, gate, doctor, dashboard | `PackageRef(import_name, dist_name=None, minimum=None)` |
| `extras` | `tuple[str, …]` | no | `resolved_install_hint` | the pip extra names, `("tube",)`, `("ai",)` |
| `capabilities` | `tuple[str, …]` | no | nothing at runtime (see gap 1) | not enforced; the names do not have to match `capabilities.PROBES` |
| `permissions` | `frozenset[Permission]` | no | `plugins info`, dashboard `_describe` | disclosure only, see `../security/PERMISSIONS.md` |
| `ui` | `UiSpec \| None` | no | dashboard `module_list.build_rows` (membership) and `app._argv_for` (the line it runs), `plugins info` | `mode` is `suspend` (the default) or `hidden`; the seven official modules all use `suspend`, `plugin-examples/hello` hides itself, and `None` means "default: suspend, no argv" |
| `install_hint` | `str \| None` | no | `deps`, `plugins info` | overrides the derived line; only `hacker` uses it |
| `documentation` | `str \| None` | no | `plugins info` | a repository-relative path |
| `origin` | `Origin` | no (default `THIRD_PARTY`) | hint derivation, `plugins list` | **the registry overwrites it**; a plugin cannot claim `OFFICIAL` |
| `provider` | `str` | no (default `""`) | hint derivation, `_origin_for` | **the registry overwrites it** from `entry_point.dist.name` |

There is exactly **one** contract, and it is data plus one callable. `registry.build_cli`
resolves `cli_path` to a callable and calls it (`registry.py:93-96`, `_resolve` at `112-117`),
the entry point resolves to a `ModuleManifest` *instance*, and what `levix create-module`
scaffolds is the same pair the seven official modules export: a module-level `MANIFEST` and a
`build_app()` function (`create_module_cmd.py:109`, `:111`, `:124`). `module.LevixModuleProtocol`
used to sit alongside that as a second, class-shaped contract (`manifest()`, `build_command()`,
both raising `NotImplementedError`), exported through `levix.sdk` and implemented by nothing —
including the scaffold its own docstring described. It has been deleted rather than documented:
a name in the public façade that no loader reads is an affordance that quietly does nothing.

## Rules a module must follow

| # | Rule | Why | Verified in |
|---|------|-----|-------------|
| 1 | `__init__.py` is pure data | `levix --help` imports it once per module; the registry must be able to list every module without importing a heavy dependency | tube/systempulse/arcade/files/hacker/music/ai `__init__.py` docstrings all say so and hold only a `MANIFEST = ModuleManifest(...)` plus `levix.sdk` imports |
| 2 | Registration comes from the manifest | `levix <module> -h` and the dashboard's view cannot disagree | `tube/cli.py:63-70`, `ai/cli.py:80-102` (ai also registers hidden aliases from `CommandInfo.aliases`) |
| 3 | The dependency gate is the Typer `callback`, and it returns early when `invoked_subcommand is None` | help stays available when the extra is missing | `tests/test_router.py:223` asserts `levix stub -h` exits 0 with a missing package |
| 4 | Third-party imports live behind exactly one seam, and that seam is a function | testability: a stub replaces one function instead of monkeypatching a module | `_make_ydl`, `build_client`, `play_samples`, `inspect_file`/`load` |
| 5 | `core.py` returns plain data and raises only `levix.sdk` errors | every rule is unit-testable without a console | `files/core.py:1-22` states it; `tube/core` returns frozen dataclasses |
| 6 | `cli.py` owns rendering | — | all seven |
| 7 | Dynamic text is escaped before printing | Rich eats `[abcdef]` in a real file name or title as a style tag, a `[/...]` raises `MarkupError` and the command dies, and a cp1252 console raises on an emoji | `_show` (`tube/cli.py:38`, `hacker/cli.py:33`, `music/cli.py:112`, `ai/cli.py:58`), `show` (`files/cli.py:49`), `_clip` (`music/cli.py:130`), `terminal.markup_safe` in systempulse, `plugins_cmd` and the dashboard, `main._plain` (`main.py:108-124`). Arcade prints only values LEVIX itself wrote |
| 8 | No shell strings | invariant 5 of `SYSTEM_ARCHITECTURE.md` | `tube/core.player_command` + `launch`, `hacker/core.run_tool`, `ai/core.run_proposal` |
| 9 | Unknown is rendered as unknown | a `0` where a site reported nothing is a lie about the data | `tube/core.summarize` and `_format_row` use `"-"`/`"not reported"` |
| 10 | SQLite access goes through the shared `Database` and a registered migration | `_levix_schema` stays truthful for `doctor` | `music/core.ensure_schema`, `arcade/scores.register_migration` |

### The seam rule has two degrees, and the difference matters

| Module | Heavy library | Imported | Effect when the extra is absent |
|--------|---------------|----------|---------------------------------|
| tube | `yt_dlp` | inside `_make_ydl` (`core.py:251`) | clean exit 3 with `pip install "levix[tube]"` |
| monitor | `psutil` | inside each of eight functions (`core.py:70…269`) | clean exit 3 |
| music | `soundfile`, `sounddevice`, `numpy`, `yt_dlp` | inside the functions that decode, play or move samples (`core.py:343,360,395,407,448,815,816,873`), and inside `_make_ydl` (`core.py:667`) for the one source that is a link; `numpy` appears only under `TYPE_CHECKING` at module level (`core.py:50`) | clean exit 3 - and a URL missing yt-dlp is exit 3 naming `levix[tube]`, which is where it comes from |
| ai | `httpx` | inside the five request functions (`core.py:807,819,874,907,939`); `TYPE_CHECKING`-only at module level (`core.py:36`) | clean exit 3 |
| arcade, files, hacker | none (stdlib + Textual) | Textual inside `screens.py`/`browse.py`, but those files are imported inside a command body | `levix game -h` and `levix files -h` never import Textual |

Verified as a matrix in `tests/test_router.py:129-136`, which runs one subprocess per
official module and asserts `levix <module> -h` leaves `HEAVY` (`test_router.py:31`:
psutil, yt_dlp, sounddevice, soundfile, numpy, textual) empty for all seven names;
`tests/test_router.py:124` asserts the same for `levix --help` itself. `music` and `ai`
failed this until their cores imported `numpy`/`httpx` at module scope, which turned a
missing extra into exit 1 plus a traceback instead of exit 3 plus the pip line; the
comment in each `core.py` records that.

## Worked example: `levix tube download URL --convert-to mp3`

| Step | File | What happens |
|------|------|--------------|
| 1 | `main.py:41` | `click_app.make_context("levix", args)` — only the root group is built |
| 2 | `app.py:83` | root callback builds `LevixContext` (paths, config, logging, database, profile) and puts it on `ctx.obj` |
| 3 | `router.py:60` | the thin `tube` command runs; `ctx.args` is `["download", "URL", "--convert-to", "mp3"]` |
| 4 | `router.py:81` | `manifest.cli_path` is non-empty, so the module is loadable |
| 5 | `registry.py:93` | `build_cli` → `_resolve("levix.modules.tube.cli:build_app")` → `importlib.import_module` (`registry.py:115`) — the only deferred-import site |
| 6 | `tube/cli.py:55` | `build_app()` builds a Typer named `tube`, `callback=_gate`, registering `info`, `download`, `play` from `MANIFEST.commands` |
| 7 | `router.py:99-104` | `command.main(args=[*prefix, *ctx.args], prog_name="levix tube", standalone_mode=False, obj=ctx.obj)` — `prefix` is empty for the module's own name and carries the canonical subcommand for an alias |
| 8 | `tube/cli.py:49-52` | `_gate` sees a subcommand, calls `gate(MANIFEST)`, which gates against the registry's stamped manifest (`deps.py:135-147`); with yt-dlp absent this raises `DependencyError` → exit 3 |
| 9 | `tube/cli.py:196` | `download()` validates `--convert-to` against `core.CONVERTIBLE` (`_validate_convert` → `typer.BadParameter` → exit 2) |
| 10 | `tube/cli.py:197` | `requested = format_spec or _configured(typer_ctx, "tube.default_format", "best")`; conversion with no explicit format switches the request to `"audio"` |
| 11 | `tube/core.py:108` | `ffmpeg_path()` = `shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")` |
| 12 | `tube/core.py:116` | `plan_format(requested, has_ffmpeg=…, convert_to="mp3")` → `FormatPlan(spec, requires_ffmpeg=True, convert_to="mp3", note=…)`; without ffmpeg the alias resolves to `ALIASES_SINGLE_FILE` and the note explains the downgrade |
| 13 | `tube/core.py:145` | `ensure_ffmpeg` raises `ExternalToolError` (exit 7) with the OS-specific install command if ffmpeg is required and missing |
| 14 | `tube/core.py:192` | `resolve_output_dir(flag, configured)` returns `(directory, which layer chose it)`: `--output` → `tube.output_dir` → `~/Downloads` |
| 15 | `tube/cli.py:212-214` | the chosen directory and source are printed through `_show`; `--playlist` prints `PLAYLIST_WARNING` |
| 16 | `tube/core.py:214` | `build_options(plan, output_dir=…, playlist=…, allow_file_url=…)` — see the table below |
| 17 | `tube/cli.py:220-221` | a `rich.live.Live` progress hook is appended to `options["progress_hooks"]` |
| 18 | `tube/core.py:282` | `fetch(url, options)` → `_make_ydl(options)` → Tube's only `import yt_dlp` → `extract_info(url, download=True)` (Music keeps its own single seam, `music/core.py:667`, for `play URL`) |
| 19 | `tube/core.py:273` | any yt-dlp exception that is not a `LevixError` becomes `ProviderError` (exit 8), with a `--allow-file-url` hint when yt-dlp says "file:// URLs are disabled". `KeyboardInterrupt` is a `BaseException`, so Ctrl+C still reaches `main.py`'s exit-130 path |
| 20 | `tube/cli.py:229` | `_report_download` prints the summary; a non-terminal console gets a blank line first so the final progress frame and the summary do not collide |

### Options yt-dlp is given, and why each is there

`build_options` is the whole surface; nothing else constructs a YoutubeDL option dict.

| Key | Value | Purpose |
|-----|-------|---------|
| `format` | `plan.spec` | the alias was expanded by us, so the selector is known |
| `noplaylist` | `not playlist` | a playlist URL is a list only after an explicit `--playlist` |
| `quiet`, `no_warnings`, `noprogress` | `True` | LEVIX renders; yt-dlp must not print over it |
| `ignoreerrors` | `False` | a failure must reach `_run` and become exit 8, not be skipped silently |
| `overwrites` | `False` | existing files keep their bytes; `download` reports "already downloaded" |
| `progress_hooks` | `[]`, filled by the CLI | the only channel from yt-dlp to the bar |
| `paths.home` | output directory | set only when downloading |
| `outtmpl` | `"%(title)s [%(id)s].%(ext)s"` | id in the name makes a re-fetch collision-proof |
| `postprocessors` | `FFmpegExtractAudio` with `preferredquality "0"` | only when `--convert-to` |
| `enable_file_urls` | `True` | only when `--allow-file-url`; yt-dlp disables `file://` by default and so do we |

Deliberately never set: `cookiefile`, `cookiesfrombrowser`, `username`, `password`,
`ap_mxac_for_mweb`, `extractor_args`, `external_downloader`. `tests/modules/test_tube.py`
asserts each of these is absent from `build_options` output. Tube implements yt-dlp's own
policy and nothing beyond it — `core.py:12-13`: "no DRM or download-protection
circumvention, no cookie extraction, no account abuse."

### How the other six modules differ

| Module | Core files (lines, 2026-11-05) | Seam | Local error classes | Writes |
|--------|-----------|------|--------------------|--------|
| systempulse (`monitor`) | `core.py` (271), `cli.py` (308) | `import psutil` per function | none; returns `None`/`{}` for unavailable metrics | nothing |
| hacker | `core.py` (1612), `cli.py` (543) | `run_tool(argv, …)` with `shutil.which`, `shell=False`, timeout 8.0 (`hacker/core.py:280`) | none | nothing; reads `hosts`, `resolv.conf`, `nsswitch.conf`, capped at `MAX_READ_BYTES = 262_144` (`hacker/core.py:1070`) |
| files | `core.py` (983), `cli.py` (538), `browse.py` (429) | stdlib only; Textual inside `browse` | `FilesError` (1), `UnsafePathError` (2), `RequestError` (2) | disk, behind the path wall and `require_approval` |
| arcade (`game`) | `scores.py` (211), `snake.py` (230), `tetris.py` (355), `screens.py` (312), `cli.py` (383) | none: rules are pure functions of state plus an explicit RNG | `ArcadeError` (1), `ArcadeUsage` (2) | `levix_arcade_score` |
| music | `core.py` (1094), `cli.py` (632), `visual.py` (245) | `soundfile` in `inspect_file`/`load`, `sounddevice` in `play_samples`, `yt_dlp` in `_make_ydl` | `MusicError` (1), `RequestError` (2), `DependencyError` (3), `BackendError` (7), `ProviderError` (8), `UnsupportedFormatError`, `AudioDeviceError` | `music_playlist`, plus `<cache_dir>/streams/…` for a fetched link |
| ai | `core.py` (972), `cli.py` (594) | `httpx.Client` in `build_client` | uses `levix.errors` directly | nothing; a proposal runs only via `run_proposal` |

Every module reads configuration through the forwarded `LevixContext` rather than a
global, and every module keeps its own `NAMESPACE` string when it owns tables
(`music`, `arcade`).

## Adding a module

| Step | Action |
|------|--------|
| 1 | `levix create-module NAME [-d DIR] [--title T] [--force]` — name must match `^[a-z][a-z0-9_-]{1,29}$` |
| 2 | generates `pyproject.toml` with `[project.entry-points."levix.plugins"] NAME = "levix_NAME:MANIFEST"`, `src/levix_NAME/{__init__.py,cli.py}`, `README.md`, `tests/test_manifest.py` |
| 3 | `pip install -e .` in the generated directory |
| 4 | `levix plugins list` shows it with `origin=third_party`; `levix plugins info NAME` shows its permissions plus the disclosure warning |
| 5 | `levix doctor` reports it, including `broken` if the entry point fails to import |

See `PLUGIN_ARCHITECTURE.md` for the trust model and the limitations of the generated
template.

## Known gaps

1. **`capabilities` is descriptive, and nothing in the product reads it.** Manifests list
   names such as `progress-hooks`, `ffmpeg-gate`, `sse-streaming`, `libsndfile` and
   `portaudio`, while `capabilities.PROBES` registers ten differently-named probes
   (`ffmpeg`, `media_player`, `audio_output`, `psutil`, `temperature`, `battery`, `gpu`,
   `keyring`, `terminal`, `platform`). Only `systempulse` uses names that are also probe
   names. The mismatch is harmless rather than misleading, because `doctor` builds its
   capability rows from `capabilities.report()` alone (`doctor.py:94-98`) and never passes
   a manifest's names to `probe()`; `capabilities.probe("nope")` would return
   `UNSUPPORTED: no probe registered for …`, but no caller asks. The single reader of
   `manifest.capabilities` in the tree is one assertion in
   `tests/modules/test_systempulse.py:420`.
2. **No test enforces rule 1 or rule 4 across the tree.** `tests/test_router.py:129-136`
   proves the runtime half for all seven official modules (help imports nothing heavy), and
   `tests/test_router.py:124` proves it for `levix --help`; nothing asserts that every
   `modules/*/__init__.py` imports only `levix.sdk`, or that each module has exactly one
   seam. A future module can break lazy loading silently.
3. **`arcade` declares `permissions=frozenset()`** although it writes to SQLite
   (`levix_arcade_score`) and runs a full-screen Textual app. The empty set is not
   accurate even as disclosure; see `../security/PERMISSIONS.md`.
4. **`files` and `game` have no install hint at all** (`extras=()`, no `install_hint`), so
   `resolved_install_hint()` is `None` for them. Correct today because they require nothing
   beyond the core; if either grows a dependency it must declare `extras`, or the gate
   prints `no install hint is declared for this module` (`deps.py:131`).

### Three gaps that used to be here are closed

- **The gate no longer says "no install hint is declared" for official modules.** Each
  `cli.py::_gate` now calls `deps.gate(MANIFEST)` (`ai/cli.py:52-55`, `arcade/cli.py:44-47`,
  `files/cli.py:43-46`, `hacker/cli.py:64-67`, `music/cli.py:46-49`,
  `systempulse/cli.py:26-29`, `tube/cli.py:49-52`), and `gate()` resolves the manifest
  through `registry.active().get(name)` before checking
  (`deps.py:135-147`), so it sees the stamped copy whose `origin` makes
  `resolved_install_hint()` produce `pip install "levix[<extra>]"`. With `yt_dlp` blocked,
  `levix tube info …` now prints that pip line; `tests/test_deps.py` covers both the
  official and the third-party path.
- **The seam rule is uniform.** `numpy` (`music/core.py:50`) and `httpx`
  (`ai/core.py:36`) are `TYPE_CHECKING`-only at module scope and imported inside the
  functions that use them, so a core install without the extras gives exit 3 with the pip
  line rather than an exit-1 traceback - proven for all seven modules by
  `tests/test_router.py:129-136`.
- **`hacker` escapes markup.** `hacker/cli.py:33-48` `_show()` routes every external value
  through `terminal.markup_safe`, and renders `None` as the empty string so the
  `value or "not reported by this platform"` sentinels still work. A hostname or interface
  name containing `[...]` is printed, not styled.

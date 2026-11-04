# Technology Stack

This document describes the stack LEVIX actually runs on, as read from
`pyproject.toml`, the installed development environment (`.venv`, `pip list` of
2026-11-05) and the source under `src/levix/`. Versions cited are the versions
installed in this repository's `.venv`, not guesses.

## Layers at a glance

| Layer | Choice | Installed version | Why this one |
|---|---|---|---|
| Runtime | Python (CPython) | 3.12.10 (MSC v.1943, AMD64) | `requires-python = ">=3.12"`; the code uses `StrEnum`, PEP 695-era typing and `tomllib` (stdlib, 3.11+). |
| CLI framework | Typer | 0.27.3 | Type-hint-driven parsers; command signatures are the single source of truth for arguments (see `src/levix/module.py`, `CommandInfo` docstring). |
| CLI engine under Typer | Typer's vendored click fork (`typer._click`) plus declared click | click 8.5.0 declared in core deps | See "Decision that bites #1" below. |
| Terminal rendering | Rich | 15.0.0 | Tables, `Live`, markup escaping; `Console` is the only writer in module CLIs. |
| TUI | Textual | 8.2.8 | Dashboard (`src/levix/dashboard/`) and the two Arcade screens. A **core** dependency: `levix dashboard` must always work, so Textual is not hidden behind an extra. |
| Config reading | stdlib `tomllib` | - (stdlib) | Read-only parser for the packaged defaults and the user file. |
| Config writing | tomlkit | 0.15.2 | See "Decision that bites #2" below. |
| Config validation | hand-maintained `SCHEMA` table (`src/levix/config.py`) | - | `pydantic` would pull compiled `pydantic-core` to validate ~30 keys; the docstring in `config.py` records that trade-off. |
| Storage | stdlib `sqlite3` via one shared database (`src/levix/storage.py`) | - (stdlib) | One file (`levix.db`), WAL, 5 s busy timeout, namespaced Python-callable migrations. |
| Paths | platformdirs | 4.14.3 | Per-OS config/data/cache/state/log locations; overridable with `LEVIX_HOME` and `LEVIX_*_DIR`. |
| Secrets | keyring (optional, `[secrets]` extra) | 25.7.0 | OS keyring preferred; owner-only plaintext file fallback, honestly reported as DEGRADED by `levix doctor`. |
| Audio | sounddevice + soundfile | 0.5.6 / 0.14.0 | Bundled PortAudio and libsndfile; decoding and output are in-process, no ffmpeg for `levix music`. |
| Numerics (audio) | numpy | 2.5.4 | Declared in the `[music]` extra, not relied on transitively from soundfile; `modules/music/core.py` imports it inside the functions that handle samples, never at module scope. |
| Media | yt-dlp (`[tube]` extra) | 2026.10.26 | Tube is a thin, gated surface over yt-dlp's own policy; `yt_dlp` is imported at exactly one seam (`core._make_ydl`). |
| Network (AI) | httpx (`[ai]` extra) | 0.28.1 | One `httpx.Client` built by `ai.core.build_client`, so tests substitute a `MockTransport`. |
| Network (self-update check) | stdlib `urllib.request` | - | `levix update` queries `https://pypi.org/pypi/levix/json`; the only default network call in core. |
| Games | stdlib `random` (`random.Random(seed)`, `random.SystemRandom()` for entropy seeds) | - | Determinism for replay, not cryptography; documented at `arcade/scores.py::game_rng`. |
| Plugins | stdlib `importlib.metadata` entry points, group `levix.plugins` | - | Discovery without imports: manifests are pure data (`src/levix/registry.py`). |
| Logging | stdlib `logging` + `RotatingFileHandler` (`src/levix/logging_setup.py`) | - | File logging optional (`logging.file_enabled`); redaction of key-shaped strings. |
| Dev tooling | pytest 9.2.0, ruff 0.17.3, mypy 2.4.1, pre-commit 4.7.0, build 1.6.1, pytest-cov 7.1.0 | as listed | Configured in `pyproject.toml`; hooks in `.pre-commit-config.yaml`. |

## Decision that bites #1: Typer 0.27.3 vendors its own click fork

Typer 0.27 runs on `typer._click`, and its `TyperGroup` does **not** derive from
`click.Group`. The standard lazy-mounting trick - subclassing `click.Group` and
overriding `get_command` - therefore targets a class hierarchy that does not exist
at runtime. Two consequences are visible in the source:

- `src/levix/router.py` registers each module as a thin command with
  `add_help_option=False` and `ignore_unknown_options`, then forwards the module's
  argv into the sub-app built on demand (`command.main(..., standalone_mode=False,
  obj=ctx.obj)`). Lazy loading needs no private API.
- `src/levix/main.py` matches click exceptions **by class name**
  (`"UsageError" in names`) rather than `isinstance`, because `isinstance(exc,
  click.UsageError)` is False for the exceptions Typer's fork actually raises.

## Decision that bites #2: `tomllib` is read-only, so writes go through tomlkit

Config is parsed with stdlib `tomllib` (`src/levix/config.py`), which cannot write.
Serialising the merged plain dict back would silently delete every comment and
reorder the user's hand-edited `config.toml` on the first `levix config set`. Writes
therefore re-parse the user file with `tomlkit`, set one key, and dump - preserving
comments and ordering (`write_user_value`, `remove_user_value`).

## The lazy-loading architecture

`levix --help` imports every registered module's `__init__.py`, so manifests stay
pure data (no Rich, no Typer app, no heavy third-party imports). Heavy imports live
behind documented seams, each with a test proving help never crosses it:

- `yt_dlp` only inside `tube/core.py::_make_ydl`.
- `sounddevice` only inside `music/core.py::play_samples` / `list_devices`;
  `soundfile`/`numpy` only inside `music/core.py`.
- Textual only inside the command bodies of `dashboard_cmd.py`,
  `dashboard/app.py` and `arcade/screens.py`.
- `psutil` only in the systempulse module and `capabilities.py` probes.

The dependency gate (`src/levix/deps.py::ensure_dependencies`, called from each
module's Typer callback) turns a missing extra into exit 3 with the exact
`pip install "levix[...]"` line, never an `ImportError`.

## Exit-code contract

`src/levix/errors.py` is the single exit-code table: 0 success, 1 unhandled runtime
error, 2 usage, 3 missing dependency, 4 unknown module, 5 config, 6 user declined
confirmation, 7 external tool failed, 8 provider/network failed, 130 Ctrl+C.
Scripts are expected to rely on codes rather than prose.

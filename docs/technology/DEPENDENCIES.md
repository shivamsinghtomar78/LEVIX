# Dependencies

Source of truth: `pyproject.toml` (declared) and `.venv/Scripts/python.exe -m pip
list` run in this repository on 2026-11-05 (installed). The installed versions
below are the ones development was run against.

Licences: every "verified here" entry was read from the installed distribution's
metadata (`pip show <pkg>`, `License` or `License-Expression` field). That field is
a claim by the upstream package, not the licence text; anything else is marked
*not re-verified here*. LEVIX itself is MIT (`pyproject.toml` `license = "MIT"`,
`LICENSE` file).

## Core dependencies (a plain `pip install levix` pulls all of these)

| Package | Installed | Licence | Extra that carries it | Core install needs it? |
|---|---|---|---|---|
| typer | 0.27.3 | MIT (verified here) | core | Yes |
| click | 8.5.0 | BSD-3-Clause (verified here) | core | Yes |
| rich | 15.0.0 | MIT (verified here) | core | Yes |
| textual | 8.2.8 | MIT (verified here) | core | Yes |
| tomlkit | 0.15.2 | MIT (verified here) | core | Yes |
| platformdirs | 4.14.3 | MIT (verified here) | core | Yes |

Transitive dependencies observed in the venv (not declared in `pyproject.toml`):
markdown-it-py, mdurl, linkify-it-py, mdit-py-plugins, Pygments, shellingham,
annotated-doc, anyio, idna, h11, httpcore, certifi, colorama, typing_extensions,
and others. They are what Rich/Textual/httpx pull in.

## Optional extras (`[project.optional-dependencies]`)

| Extra | Declared pins | Installed | Licence | Notes |
|---|---|---|---|---|
| `[monitor]` | `psutil>=7.2,<8` | 7.2.2 | BSD-3-Clause (verified here) | systempulse module |
| `[tube]` | `yt-dlp>=2026.10.26` (no upper bound) | 2026.10.26 | Unlicense (verified here) | imported inside `tube/core.py::_make_ydl`, and inside `music/core.py::_make_ydl` when - and only when - `levix music play` is handed an `http(s)` link. Music declares no extra of its own for it: the message names `levix[tube]`, because that is where it comes from |
| `[music]` | `sounddevice>=0.5,<1`, `soundfile>=0.14,<1`, `numpy>=2.0,<3` | 0.5.6, 0.14.0, 2.5.4 | sounddevice MIT (verified here); soundfile metadata reads **"BSD 3-Clause License"** (verified here) - contradicts the "MIT" note carried in earlier repo work; not re-verified against upstream licence text; numpy not re-verified here | bundles PortAudio and libsndfile respectively. numpy is declared because the `music` module imports it directly - inside the functions that handle samples (`core.py`, `visual.py`, `cli.py`), never at module scope |
| `[ai]` | `httpx>=0.28,<1` | 0.28.1 | BSD-3-Clause (verified here) | |
| `[secrets]` | `keyring>=25.7,<26` | 25.7.0 | MIT (verified here) | pulls jaraco.\*, pywin32-ctypes on Windows (transitive) |
| `[all]` | `levix[ai,monitor,music,secrets,tube]` | - | - | meta-extra only |
| `[dev]` | `build>=1.6`, `mypy>=2.4`, `pre-commit>=4.7`, `pytest>=9.2`, `pytest-cov>=7.1`, `ruff>=0.17` | 1.6.1, 2.4.1, 4.7.0, 9.2.0, 7.1.0, 0.17.3 | all MIT (verified here) | tooling, never imported at runtime |

Not installed in this venv at all: **hatchling** (the build backend, declared in
`[build-system]`; fetched by build isolation into a throwaway env; licence MIT
upstream - *not re-verified here*), **PyInstaller** (mentioned nowhere but in the
deferred standalone-binary plan; upstream licence is GPL-2.0-or-later **with its
linking exception** - *not re-verified here because it is not installed*. An MIT
project can produce PyInstaller binaries because of that exception, not because
PyInstaller is MIT).

## The lazy-loading invariant

Rule: **module-specific heavy packages stay out of the core install.** psutil,
yt-dlp, sounddevice, soundfile, numpy, httpx and keyring are all confined to
extras; a core install pulls none of them.

Note the honest exception, visible in `pyproject.toml` itself: **textual IS a core
dependency** (installed 8.2.8). The dashboard and the Arcade screens are core
features, so "a core install must pull no textual" is not how the project is
currently configured, and this document does not pretend otherwise.

Also note: `music/core.py` imports `numpy` inside the functions that need it, never at
module scope, and `numpy>=2.0,<3` is declared in the `music` extra rather than relied on
transitively from soundfile. An earlier revision of this document recorded the opposite -
a module-scope import and no declaration - which is exactly the undeclared reliance that
the pin removed.

Verification status of the invariant: **verified by a throwaway-environment install** on
2026-11-05, from the built wheel with `pip install <wheel>` into an empty `python -m venv`
(see `docs/technology/PYTHON_PACKAGING.md`). That install pulled `levix 0.4.0` and exactly
`typer`, `click`, `rich`, `textual`, `tomlkit`, `platformdirs` plus their own transitive
dependencies (`annotated-doc`, `colorama`, `linkify-it-py`, `markdown-it-py`,
`mdit-py-plugins`, `mdurl`, `Pygments`, `shellingham`, `typing-extensions`). None of
`psutil`, `yt-dlp`, `sounddevice`, `soundfile`, `numpy`, `httpx`, `keyring` was installed,
and in that environment `levix monitor cpu`, `music devices`, `ai models` and `tube info x`
each answered exit 3 with the correct `pip install "levix[<extra>]"` line, while
`levix <module> -h` worked for all seven modules. Earlier the same check could not be run,
because `pip install .` failed at the wheel step (duplicate `force-include` of
`levix/data/defaults.toml`); that defect is fixed. What remains unverified is the same
check on Linux and macOS.

What was verified before that, and still holds:

1. Static reading of `pyproject.toml` (the table above).
2. Subprocess tests that prove the *runtime* half of the invariant -
   `levix tube -h` does not import `yt_dlp` (`test_tube_help_never_imports_yt_dlp`),
   importing the music manifest pulls no audio libraries
   (`test_importing_the_manifest_pulls_in_no_audio_libraries`),
   `levix music info -h` needs no PortAudio (`test_info_help_needs_no_portaudio`),
   and the arcade equivalents (`test_importing_the_manifest_pulls_in_nothing_heavy`,
   `test_the_screen_is_not_imported_by_help_or_scores`).

## Dependency gate

`src/levix/deps.py` is the single "is this installed?" oracle (find_spec plus
`importlib.metadata` version check, no blind imports). Every module's Typer
callback calls `ensure_dependencies(MANIFEST)`; unsatisfied requirements raise
`DependencyError` -> exit 3 with the install hint computed by
`ModuleManifest.resolved_install_hint()` (e.g. `pip install "levix[tube]"`).

## Tool configuration (from `pyproject.toml`)

- **ruff**: line-length 100, `target-version = "py312"`, rules `E,F,W,I,UP,B,C4,SIM,RUF,T20,S`; ignores `S603`, `S607`; per-file ignores for the Typer `B008` idiom and for two hand-reviewed `S608` SQL sites (`music/core.py`, `arcade/scores.py` - all values bind via `?` placeholders).
- **mypy**: `python_version = "3.12"`, `files = ["src/levix"]`, `strict = false`, `warn_unused_ignores = true`, `disallow_untyped_defs = true`.
- **pytest**: `testpaths = ["tests"]`, `addopts = "-q --strict-markers"`, markers `integration` and `slow`; coverage over `src/levix` with branch coverage on.
- **pre-commit** (`.pre-commit-config.yaml`): yaml/toml/large-file/end-of-line hooks, `ruff --fix`, `ruff-format`, `mypy` over `src/levix/`.

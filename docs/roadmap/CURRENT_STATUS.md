# Current status

**Read this first if you are picking the project up cold.** Every other page in `docs/`
describes the shape of the code; this page states what is actually true on what machine,
what was proven how, and what is still open. It is written from a hand run, not from
memory: each claim names the command or test that shows it.

- Version: `levix 0.4.0` (`levix --version`), plus the unreleased work in `CHANGELOG.md`.
- Date of the state below: 2026-11-05.
- Verified on **one machine**: Windows 11 build 26200, AMD64, Python 3.12.10 in the
  project-local `.venv`, 8 GB RAM, stdout captured (not a TTY) for every test run.
- **Nothing here was executed on Linux or macOS.** Both are designed for and both are
  unproven. Do not quote this project as cross-platform verified.

## One-paragraph summary

LEVIX is one executable fronting seven terminal applications, with a plugin contract built
on `importlib.metadata` entry points. The core is six lightweight dependencies
(click, platformdirs, rich, textual, tomlkit, typer); every module-specific dependency
(psutil, yt-dlp, soundfile/sounddevice/numpy, httpx, keyring) is an extra and is gated at
run time with a message that names the extra. The dashboard is a launcher: it never calls
module internals, it re-enters `levix <module> …` in a child process with the terminal
suspended. Commands, modules, errors, exit codes, configuration layering and the
dependency gate are covered by a 580-function suite that runs without network, without a
real device and without a real terminal.

## What is built, and how each part is proven

| Part | Exists | Proven by |
| --- | --- | --- |
| Core engine (registry, router, config, storage, secrets, deps gate, capabilities, errors, logging, terminal) | 21 top-level modules under `src/levix/` | 10 test files in `tests/` (127 functions, 137 collected cases) |
| Textual dashboard (module list, detail panel, history, theme, suspend-and-run launcher) | `src/levix/dashboard/` | `tests/test_dashboard.py` (15) driven headlessly through Textual's Pilot |
| Platform commands: `doctor`, `config`, `plugins`, `history`, `create-module`, `update`, `secrets` handling | `src/levix/commands/` | `tests/test_doctor.py` (6), `tests/test_config.py` (20), `tests/test_markup_safety.py` (9); `update` and `create-module` have no test |
| Tube | `src/levix/modules/tube/` | 62 functions / 76 cases against a fake `yt_dlp`, no network |
| Hacker | `…/hacker/` | 52 / 78, OS reporting driven with captured text |
| SystemPulse (`monitor`) | `…/systempulse/` | 40 / 46 against a psutil stand-in in `sys.modules`, plus five `run_cli` cases against real psutil |
| AI | `…/ai/` | 82 / 97 against a stubbed httpx transport |
| Music | `…/music/` | 57 / 74; one case is marked `integration` and needs an output device |
| Arcade (`game`) | `…/arcade/` | 39 / 43, rules as pure functions plus Pilot-driven screens |
| Files | `…/files/` | 121 / 147 in a temporary filesystem |
| Plugin contract and a real third-party module | `levix.sdk` (14 re-exports), `plugin-examples/hello/` | `tests/test_registry.py` (12), `tests/test_plugin_example.py` (7) which registers the example through a hand-built `dist-info` and runs the real router over it |

## Test suite as last run

```
.venv/Scripts/python.exe -m pytest -o addopts="" -q
580 test functions in 17 files, collecting to 698 parametrised cases
693 passed, 5 skipped, 2 warnings in 157.55 s   (exit 0)
```

The `-o addopts=""` clears `-q --strict-markers`; it changes nothing about which cases run,
because `addopts` deselects no marker.

- The five skips are all symlink cases in `tests/modules/test_files.py`: two fail with
  `WinError 1314` (this account cannot create symlinks) and three state that POSIX symlinks
  need no privilege here. They are skipped, never silently passed.
- Eight cases carry `@pytest.mark.integration` (`pytest -m integration` collects exactly
  `8/698 tests, 690 deselected`). The repository's `addopts` is `-q --strict-markers` and
  deselects nothing, so the default run above already includes them - among them the real
  audio-device playback test, which skips itself when PortAudio reports no output device.
- `.strict-markers` is on, so an unregistered marker is an error rather than a warning.

## Static checks

| Check | Command | Result on this machine |
| --- | --- | --- |
| Lint | `.venv/Scripts/python.exe -m ruff check src tests plugin-examples` | exit 0, "All checks passed!" |
| Format | `.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples` | exit 0, "80 files already formatted" |
| Types | `.venv/Scripts/python.exe -m mypy` | exit 0, "no issues found in 61 source files" (`[tool.mypy].files` covers `src/levix` **and** `plugin-examples/hello/src`, so the copy-pasteable plugin is checked with the core). Since run #1, `--platform win32`, `--platform linux` and `--platform darwin` are all run here too, because a Linux runner is what found the one Windows-only attribute the tree had |
| Install | `.venv/Scripts/python.exe -m pip install -e ".[dev,all]"` | the only install proven here |
| Distribution | `python -m build` then install the wheel into an empty venv | sdist + wheel build (66 wheel entries, `levix/py.typed` present, `levix/data/defaults.toml` exactly once); in the clean venv all seven modules answer `-h` with 0, the four heavy ones refuse with 3 naming the right extra, and no heavy package is imported (`CHANGELOG.md` §Verification) |
| CI | `.github/workflows/ci.yml`, `.github/workflows/release.yml` | **has run once** (run #1, commit `fcbcb22`, 2026-11-05): `Bare core install (no extras)` **passed on Ubuntu**, which is the first time the extras gate was proven on a platform other than this laptop. All four Linux/macOS matrix jobs stopped at `Types` on one real cross-platform defect (`st_file_attributes` is Windows-only; `mypy` on a POSIX runner has no stub for it - fixed, and now proven against `--platform win32`, `linux` and `darwin`). Both Windows jobs passed Lint, Format and Types and failed at `Test suite`; the cause is not yet known, and the next run annotates the failing test names so they are readable without a signed-in account |
| Doctor | `levix doctor --json` | verdict `degraded`, exit 0; capabilities `ffmpeg`, `media_player`, `audio_output`, `psutil`, `battery`, `keyring`, `platform` are `ok`; `temperature` `degraded` (this psutil has no `sensors_temperatures`), `gpu` `unsupported`, `terminal` `degraded` (stdout not a TTY) |
| Update check | `levix update` | exit 8, `could not check for updates: PyPI returned 404` - the name is unclaimed, and the command refuses to imply "up to date" when it could not ask |

Eleven `# noqa` comments remain, each for a rule that fires on correct code: `S105` on the
three `SECRET_*` names that are lookup keys rather than credentials, `S311` on the seeded
game/hacker RNGs, `S310` on the single HTTPS release feed, `S104` on the any-address literal
Hacker describes, `B009` on two `getattr(os, "getuid")` lookups, and `E731`/`S108` in
`tests/modules/test_ai.py`.

## Defects found by reading the docs against the code

This build's method was to write the documentation first, then verify every claim against
the source. Each row below is a case where the code was wrong, not the doc.

| Defect | Fix | Pinned by |
| --- | --- | --- |
| A documented alias reached the module's group, so `levix nt hello` exited 4 | `router._attach` prepends the aliased subcommand | `tests/test_router.py::test_a_command_alias_reaches_the_command_it_names` |
| `config reset --yes` deleted the user's configuration without asking | `require_approval(..., destructive=True)` | `tests/test_config.py::test_reset_yes_cannot_delete_a_configuration_without_a_typed_word` |
| Foreign text was interpolated into Rich markup unescaped in five modules, the dashboard and `levix plugins`; an unbalanced `[/...]` killed the printing command | per-module escape helpers over `terminal.markup_safe` / `encode_safe` | `tests/test_markup_safety.py`, per-module markup tests |
| `main._plain()` ran multi-line messages through a one-line escaper, so intended newlines arrived as literal `\x0a` | escape per line | `tests/test_deps.py::test_a_two_line_refusal_stays_two_lines_on_the_screen` |
| `monitor network` was the one OS-sourced cell still reaching Rich raw | `_network_table` extracted, every cell escaped | `test_systempulse.py::test_an_interface_name_with_brackets_is_still_shown` |
| `files search --max-bytes 0` capped every file at the default instead of meaning "no cap" | `0` = no cap, negative = default | `test_files.py::test_max_bytes_zero_means_no_cap` |
| `doctor --only modules` / `--only capabilities` printed everything | the computed prefix is applied | `tests/test_doctor.py` (6) |
| Wheel build aborted: `defaults.toml` was force-included twice | redundant `force-include` entry removed | `python -m build` succeeds; clean-venv install proves the extras split |
| Two inert configuration keys (`general.confirm_destructive`, `dashboard.show_system_info`) and one inert flag (`config set --yes`) promised behaviour that did not exist | removed from `SCHEMA`, `defaults.toml` and the CLI rather than wired | `tests/test_config.py::test_no_declared_key_is_secret_shaped`, `test_packaged_defaults_cover_every_schema_key` |
| `module.LevixModuleProtocol` was public SDK surface implementing nothing, describing a scaffold shape that was not the scaffold | deleted; one contract remains (`MANIFEST` + `cli:build_app`) | `tests/test_plugin_example.py` drives that contract for real |
| `[set, hidden]` was swallowed by Rich as a style tag, so masked secrets rendered as nothing | `_MASK` is markup-free | `tests/test_markup_safety.py::test_the_config_mask_reaches_the_screen_as_words` |

## What is not verified, and should not be claimed

1. **POSIX.** `chmod 0600` on the secrets file, the OS keyring backend, the
   `ip addr show` / `ifconfig` / `resolv.conf` / `nsswitch.conf` / `route -n` parsers, and
   the platformdirs layout on Linux/macOS. The suite drives those paths with fakes or
   captured POSIX text; only the Windows branches (`icacls`, `ipconfig`, `route print`) ran.
2. **A real terminal.** The dashboard on a screen, `files browse`, `monitor live`,
   `hacker matrix` animating, Snake and Tetris played by key. Every one is exercised through
   Textual's Pilot or through the non-TTY refusal path.
3. **Typed destructive words.** No human typed `DELETE`, `OVERWRITE` or `RUN` at a prompt;
   `approve.py:51-59` is covered only by the pipe refusal.
4. **Sound and video.** Audible playback is the `integration` device test. `ffmpeg`,
   `ffprobe` and `ffplay` are installed on this machine and probe `ok`, but merged-stream
   download and `--convert-to` were never run against a real URL.
5. **Any network call.** No test reached a site: Tube's `_make_ydl` seam is replaced, AI's
   transport is stubbed, and `levix update` needs a PyPI entry for a name that is not
   published. `levix ai` has never spoken to a real model server.
6. **Log redaction.** `logging_setup.RedactFilter` is load-bearing for a security promise
   and is asserted by no test; `tests/conftest.py:4-5` disables file logging for the whole
   suite because an open handle stops Windows deleting the temporary home.
7. **`levix update` and `levix create-module`.** No tests; the scaffold the generator emits
   is the shape `tests/test_plugin_example.py` proves by hand, but the generated tree is
   never executed.
8. **Plugin install/publish.** `levix plugins` offers `list` and `info` only; installing a
   plugin means `pip install` in this environment. Deliberate, documented, and still a gap.
9. **`UiSpec(mode="screen")`.** `registry.build_screen` exists and is tested for its failure
   branch; no manifest in the tree declares a screen, all seven use `suspend`.
10. **A green matrix.** `.github/workflows/ci.yml` has now run (run #1): the bare-wheel job
    passed on Ubuntu, four POSIX jobs failed on a Windows-only stat attribute that is fixed,
    and the two Windows jobs failed inside the suite for a reason the log does not yet name.
    `release.yml` has **not** run, and it cannot pass until the PyPI project and its trusted
    publisher exist (`docs/technology/PYTHON_PACKAGING.md` §Publishing).
11. **Coverage.** `[tool.coverage.run]` sets `branch = true`, but no `--cov` is in
    `addopts` and no threshold is enforced.
12. **Pre-commit hooks.** `.pre-commit-config.yaml` exists and names `ruff --fix`,
    `ruff-format` and mypy; installing and running the hooks was never done here.

## What to do next, in order

1. Read run #2. The POSIX columns now get past `Types`, so the first real Linux and macOS
   suite results arrive there, and the Windows columns fail with the failing test names in
   their annotations rather than only in a log that needs a signed-in account. Assume Linux
   and macOS disagree with something: the POSIX items in the list above are where to look -
   secrets hardening, the keyring backend, Hacker's four parsers - and the moment a column
   is green, this page's platform warning can be narrowed to the parts that still have no
   runner.
2. Write the redaction test that gap 6 is asking for. It is the only security promise in the
   docs that no test holds, and it does not need a terminal or a network.
3. Add tests for `levix update` (against a stubbed PyPI) and `levix create-module` (generate
   into a temp dir, then import the scaffolded `MANIFEST`).
4. Decide the fate of `mode="screen"`: either give one module a real embedded screen or drop
   the mode. Documented-but-unused API is a tax on every reader.
5. Do the one-time PyPI side that a checkout cannot do: the account with 2FA, the project
   `levix`, the trusted publisher naming this repo + `release.yml` + the `pypi` environment,
   and that environment in GitHub Settings. Then `git tag v0.4.0 && git push origin v0.4.0`,
   which is the first time README's `pipx install levix` is true and the first time
   `levix update` has a real answer to give.
6. Only after a release exists: the standalone binaries (starting with the frozen-metadata
   question in `PYTHON_PACKAGING.md`), a winget manifest, and `levix plugins install` /
   `publish`.

## How to reproduce the numbers in this page

```bash
.venv/Scripts/python.exe -m pytest -q                           # the suite, all 698 cases
.venv/Scripts/python.exe -m pytest -m "not integration"          # the 690 CI runs
.venv/Scripts/python.exe -m pytest -m integration -q             # just the 8 device/OS cases
.venv/Scripts/python.exe -m ruff check src tests plugin-examples        # lint
.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples  # format
.venv/Scripts/python.exe -m mypy                                 # types (core + example plugin)
COLUMNS=100 .venv/Scripts/levix.exe doctor --json                # what this machine can actually do
```

Those six lines are `.github/workflows/ci.yml`'s `suite` job, run by hand on one platform.
The repository's `addopts = "-q --strict-markers"` deselects no marker, so an unmodified
`pytest` is the full 698 cases here; a job that must not touch a device or an OS tool has to
say `-m "not integration"` explicitly rather than assume the config does it.

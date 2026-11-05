# Current status

**Read this first if you are picking the project up cold.** Every other page in `docs/`
describes the shape of the code; this page states what is actually true on what machine,
what was proven how, and what is still open. It is written from a hand run, not from
memory: each claim names the command or test that shows it.

- Version: `levix 0.4.0` (`levix --version`), plus the unreleased work in `CHANGELOG.md`.
- Date of the state below: 2026-11-05.
- Verified on **one machine**: Windows 11 build 26200, AMD64, Python 3.12.10 in the
  project-local `.venv`, 8 GB RAM, stdout captured (not a TTY) for every test run.
- **Nothing was hand-run on Linux or macOS.** GitHub Actions has executed the suite there -
  three runs, all on 2026-11-05 - and the third was red on all six columns, on eight tests
  that quietly assumed this laptop. All eight are fixed in the tree and the fourth run has to
  agree, so no Linux or macOS result is *proven* yet and this project must not be quoted as
  cross-platform verified. `docs/technology/COMPATIBILITY.md` and §What is not verified below
  say what each platform is missing.

## One-paragraph summary

LEVIX is one executable fronting seven terminal applications, with a plugin contract built
on `importlib.metadata` entry points. The core is six lightweight dependencies
(click, platformdirs, rich, textual, tomlkit, typer); every module-specific dependency
(psutil, yt-dlp, soundfile/sounddevice/numpy, httpx, keyring) is an extra and is gated at
run time with a message that names the extra. The dashboard is a launcher: it never calls
module internals, it re-enters `levix <module> …` in a child process with the terminal
suspended. Commands, modules, errors, exit codes, configuration layering and the
dependency gate are covered by a 583-function suite that runs without network, without a
real device and without a real terminal.

## What is built, and how each part is proven

| Part | Exists | Proven by |
| --- | --- | --- |
| Core engine (registry, router, config, storage, secrets, deps gate, capabilities, errors, logging, terminal) | 21 top-level modules under `src/levix/` | 10 test files in `tests/` (127 functions, 137 collected cases) |
| Textual dashboard (module list, detail panel, history, theme, suspend-and-run launcher) | `src/levix/dashboard/` | `tests/test_dashboard.py` (15) driven headlessly through Textual's Pilot |
| Platform commands: `doctor`, `config`, `plugins`, `history`, `create-module`, `update`, `secrets` handling | `src/levix/commands/` | `tests/test_doctor.py` (6), `tests/test_config.py` (20), `tests/test_markup_safety.py` (9); `update` and `create-module` have no test |
| Tube | `src/levix/modules/tube/` | 62 functions / 76 cases against a fake `yt_dlp`, no network |
| Hacker | `…/hacker/` | 53 / 79, OS reporting driven with captured text |
| SystemPulse (`monitor`) | `…/systempulse/` | 40 / 46 against a psutil stand-in in `sys.modules`, plus five `run_cli` cases against real psutil |
| AI | `…/ai/` | 82 / 97 against a stubbed httpx transport |
| Music | `…/music/` | 57 / 74; three cases are marked `integration` and need a machine with sound hardware |
| Arcade (`game`) | `…/arcade/` | 39 / 43, rules as pure functions plus Pilot-driven screens |
| Files | `…/files/` | 123 / 153 in a temporary filesystem |
| Plugin contract and a real third-party module | `levix.sdk` (14 re-exports), `plugin-examples/hello/` | `tests/test_registry.py` (12), `tests/test_plugin_example.py` (7) which registers the example through a hand-built `dist-info` and runs the real router over it |

## Test suite as last run

```
.venv/Scripts/python.exe -m pytest -o addopts="" -q
583 test functions in 17 files, collecting to 705 parametrised cases
700 passed, 5 skipped, 2 warnings in 124.42 s   (exit 0)
```

The `-o addopts=""` clears `-q --strict-markers`; it changes nothing about which cases run,
because `addopts` deselects no marker.

- The five skips are all symlink cases in `tests/modules/test_files.py`: two fail with
  `WinError 1314` (this account cannot create symlinks) and three state that POSIX symlinks
  need no privilege here. They are skipped, never silently passed.
- Ten cases carry `@pytest.mark.integration` (`pytest -m integration` collects exactly
  `10/705 tests, 695 deselected`). The repository's `addopts` is `-q --strict-markers` and
  deselects nothing, so the default run above already includes them - among them the real
  audio-device playback test, which skips itself when PortAudio reports no output device.
  Three of the ten ask the operating system which sound hardware it has; CI run #3 moved
  them out of the matrix jobs, because a headless runner answers that question with either
  no PortAudio or an empty device list, and neither is a defect.
- `.strict-markers` is on, so an unregistered marker is an error rather than a warning.

## Static checks

| Check | Command | Result on this machine |
| --- | --- | --- |
| Lint | `.venv/Scripts/python.exe -m ruff check src tests plugin-examples` | exit 0, "All checks passed!" |
| Format | `.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples` | exit 0, "80 files already formatted" |
| Types | `.venv/Scripts/python.exe -m mypy` | exit 0, "no issues found in 61 source files" (`[tool.mypy].files` covers `src/levix` **and** `plugin-examples/hello/src`, so the copy-pasteable plugin is checked with the core). Since run #1, `--platform win32`, `--platform linux` and `--platform darwin` are all run here too, because a Linux runner is what found the one Windows-only attribute the tree had |
| Install | `.venv/Scripts/python.exe -m pip install -e ".[dev,all]"` | the only install proven here |
| Distribution | `python -m build` then install the wheel into an empty venv | sdist + wheel build (66 wheel entries, `levix/py.typed` present, `levix/data/defaults.toml` exactly once); in the clean venv all seven modules answer `-h` with 0, the four heavy ones refuse with 3 naming the right extra, and no heavy package is imported (`CHANGELOG.md` §Verification) |
| CI | `.github/workflows/ci.yml`, `.github/workflows/release.yml` | **has run three times.** #1 (`fcbcb22`): the bare-wheel job **passed on Ubuntu** - the first time the extras gate was proven on a platform other than this laptop - and the four POSIX matrix jobs stopped at `Types` on one real cross-platform defect (`st_file_attributes` is Windows-only; `mypy` on a POSIX runner has no stub for it - fixed, and now proven against `--platform win32`, `linux` and `darwin`). #2 (`726909c`) reported "5 successful and 2 failing" and was wrong in both directions: the `Test suite` step piped pytest through `tee` under a shell without `pipefail`, so Linux and macOS went green over a red suite, and both Windows jobs died in pwsh before pytest ran. #3 (`5fdc644`) is the first honest result: **all six columns red, eight test functions between them**, every one of them dependent on the machine it ran on - typer forces a terminal whenever `GITHUB_ACTIONS` is set so the help-page assertions met escape codes, the delete path judged a symlink by its target and refused a safe removal, `os.readlink` returns `\\?\`-prefixed targets on Windows, two tests asked a headless runner about its sound cards, a 68-character macOS runner hostname did not fit the host table's value column, and the AI cap notice wrapped at 80 columns. All eight are addressed in this commit; run #4 is what says whether that was the whole list. `release.yml` has **not** run, and it cannot pass until the PyPI project and its trusted publisher exist (`docs/technology/PYTHON_PACKAGING.md` §Publishing) |
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

## Defects found by CI, on platforms this laptop is not

Same method, different instrument: the runner disagreed with the suite in eight places, and
in each one the runner was right about itself. None of these fixes can be re-checked here, so
each is confirmed by run #4 or not at all.

| Defect | Where it showed | Fix | Pinned by |
| --- | --- | --- | --- |
| Deleting a link judged it by its target, so a link inside the wall pointing outside it was refused | Ubuntu, macOS | `core.resolve(..., keep_link=True)`, used by `plan_delete` alone | `test_a_link_deleted_as_a_link_is_judged_at_its_own_place` |
| A link's target was shown as `\\?\C:\Users\...`, the DOS-device form `os.readlink` returns | Windows | `core.strip_device_prefix` | `test_the_device_prefix_windows_stores_in_a_link_is_removed` |
| The hostname was folded in the middle of the token by a 65-character table column | macOS (68-character runner name) | the name prints as a full-width line under the host table | `test_a_hostname_longer_than_the_table_stays_in_one_piece` |
| Help-page assertions met escape codes, because typer forces a terminal when `GITHUB_ACTIONS` is set | all six columns | `tests/test_router.py::capsys_text` strips them before matching | the two router cases run with `GITHUB_ACTIONS=true` here |
| Two cases asked a headless runner which sound cards it has | Ubuntu (no PortAudio), Windows (no devices) | marked `integration`, and each skips out loud | `pytest -m integration` collects 10 |
| The cap notice wrapped after "showing" at 80 columns | Ubuntu | the case pins `COLUMNS=200` | `test_explain_sends_only_the_capped_prefix` |
| A Windows-only stat attribute typed clean on Windows and failed `mypy` on POSIX | Ubuntu, macOS (`Types`) | `getattr(os.lstat(path), "st_file_attributes", 0)` | `mypy --platform win32\|linux\|darwin` |
| The suite step reported success over a failing suite (`pytest \| tee`, no `pipefail`), and pwsh ran bash-only syntax | run #2, both were false | `defaults.run.shell: bash`, redirect then echo, `FAILED` lines re-emitted as annotations | no test can hold a workflow file |

## What is not verified, and should not be claimed

1. **POSIX.** `chmod 0600` on the secrets file, the OS keyring backend, the
   `ip addr show` / `ifconfig` / `resolv.conf` / `nsswitch.conf` / `route -n` parsers, and
   the platformdirs layout on Linux/macOS. The suite drives those parsers with captured
   POSIX text and never runs the tools, so even a green Ubuntu column would not be evidence
   for them; what run #3 does add is narrower - the POSIX branches the tests *do* reach
   executed on Ubuntu and macOS, and none of the eight failures were in them. End to end,
   only the Windows branches (`icacls`, `ipconfig`, `route print`) have been observed.
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
10. **A green matrix.** Run #3 is the first run whose suite result can be trusted, and it is
    red on all six columns: eight test functions that depend on the machine they run on.
    Each is fixed here, and each fix is unverified on the machine that found it - this box
    cannot create symlinks, has PortAudio and real devices, and is not macOS. Run #4 is the
    first evidence for any of them. `release.yml` has **not** run, and it cannot pass until
    the PyPI project and its trusted publisher exist (`docs/technology/PYTHON_PACKAGING.md`
    §Publishing).
11. **Coverage.** `[tool.coverage.run]` sets `branch = true`, but no `--cov` is in
    `addopts` and no threshold is enforced.
12. **Pre-commit hooks.** `.pre-commit-config.yaml` exists and names `ruff --fix`,
    `ruff-format` and mypy; installing and running the hooks was never done here.
13. **`FORCE_COLOR=1`.** Proven on this machine, and deliberately left alone: with that
    variable set, Rich styles the error paths too, so
    `tests/test_router.py::test_an_unknown_command_is_reported_with_the_modules_that_do_exist`
    fails on `unknown command: nostalgia` while the screen shows the same words in bold.
    The output is right and the assertion is the fragile part - it reads a styled stream as
    plain text. GitHub Actions does not set `FORCE_COLOR`, and `GITHUB_ACTIONS=true` alone
    leaves these 16 router cases green (checked here); only typer's own help renderer forces
    a terminal there, which is the one place the suite now strips escape codes. The rest of
    the suite still assumes a colourless stream.

## What to do next, in order

1. Read run #4. Two things are decided there. Whether the eight were the whole list - the
   `Test suite` step now writes `pytest.log`, prints it, and turns every `FAILED` line into
   an annotation, so a red column names itself without a signed-in account. And what the
   fixes newly expose: `test_deleting_a_link_removes_the_link_and_never_the_target` and the
   symlink preview case reached a real link on Ubuntu and macOS for the first time, so if
   `keep_link` is wrong in some way this laptop cannot produce, that is where it shows. When
   a column is green, narrow this page's platform warning to what still has no runner - the
   POSIX items above - rather than calling the tree portable.
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
.venv/Scripts/python.exe -m pytest -q                           # the suite, all 705 cases
.venv/Scripts/python.exe -m pytest -m "not integration"          # the 695 CI runs
.venv/Scripts/python.exe -m pytest -m integration -q             # just the 10 device/OS cases
.venv/Scripts/python.exe -m ruff check src tests plugin-examples        # lint
.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples  # format
.venv/Scripts/python.exe -m mypy                                 # types (core + example plugin)
COLUMNS=100 .venv/Scripts/levix.exe doctor --json                # what this machine can actually do
```

Those six lines are `.github/workflows/ci.yml`'s `suite` job, run by hand on one platform.
The repository's `addopts = "-q --strict-markers"` deselects no marker, so an unmodified
`pytest` is the full 705 cases here; a job that must not touch a device or an OS tool has to
say `-m "not integration"` explicitly rather than assume the config does it.

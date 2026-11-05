# Current status

**Read this first if you are picking the project up cold.** Every other page in `docs/`
describes the shape of the code; this page states what is actually true on what machine,
what was proven how, and what is still open. It is written from a hand run, not from
memory: each claim names the command or test that shows it.

- Version: `levix 0.4.0` (`levix --version`), plus the unreleased work in `CHANGELOG.md`.
- Date of the state below: 2026-11-05.
- Hand-run on **one machine**: Windows 11 build 26200, AMD64, Python 3.12.10 in the
  project-local `.venv`, 8 GB RAM, stdout captured (not a TTY) for every test run.
- **CI run #4 (`5b047ad`) is the first green run**: all six matrix columns - Windows,
  Ubuntu and macOS at 3.12 and 3.13 - passed `Lint`, `Format`, `Types` and `Test suite`, and
  the bare-core wheel job passed on Ubuntu. So the suite has now executed on three operating
  systems and four Python versions, on GitHub's runners. It does not make this project
  "cross-platform verified": those columns run `-m "not integration"` - 690 passed and 5
  skipped at run #4's smaller suite, 701 passed, 5 skipped and 10 deselected in this tree -
  so the ten device/OS-tool cases have only ever run here, nothing has been
  hand-run on Linux or macOS, and §What is not verified item 1 lists the POSIX behaviours no
  test asserts even when an Ubuntu runner is the one executing them.
  `docs/technology/COMPATIBILITY.md` says what each platform is missing.

## One-paragraph summary

LEVIX is one executable fronting seven terminal applications, with a plugin contract built
on `importlib.metadata` entry points. The core is six lightweight dependencies
(click, platformdirs, rich, textual, tomlkit, typer); every module-specific dependency
(psutil, yt-dlp, soundfile/sounddevice/numpy, httpx, keyring) is an extra and is gated at
run time with a message that names the extra. The dashboard is a launcher: it never calls
module internals, it re-enters `levix <module> …` in a child process with the terminal
suspended. Commands, modules, errors, exit codes, configuration layering and the
dependency gate are covered by a 589-function suite that runs without network, without a
real device and without a real terminal.

## What is built, and how each part is proven

| Part | Exists | Proven by |
| --- | --- | --- |
| Core engine (registry, router, config, storage, secrets, deps gate, capabilities, errors, logging, terminal) | 21 top-level modules under `src/levix/` | 11 test files in `tests/` (133 functions, 148 collected cases), `tests/test_logging.py` (6 / 11) among them |
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
589 test functions in 18 files, collecting to 716 parametrised cases
711 passed, 5 skipped, 2 warnings in 97.06 s   (exit 0)
```

The same tree, one process at a time, split the way CI splits it:

```
-m "not integration"   701 passed, 5 skipped, 10 deselected in 103.69 s   (exit 0)
-m integration         10 passed, 706 deselected, 2 warnings in 10.36 s   (exit 0)
```

The `-o addopts=""` clears `-q --strict-markers`; it changes nothing about which cases run,
because `addopts` deselects no marker.

- The five skips are all symlink cases in `tests/modules/test_files.py`: two fail with
  `WinError 1314` (this account cannot create symlinks) and three state that POSIX symlinks
  need no privilege here. They are skipped, never silently passed.
- Ten cases carry `@pytest.mark.integration` (`pytest -m integration` collects exactly
  `10/716 tests, 706 deselected`). The repository's `addopts` is `-q --strict-markers` and
  deselects nothing, so the default run above already includes them - among them the real
  audio-device playback test, which skips itself when PortAudio reports no output device.
  Three of the ten ask the operating system which sound hardware it has; CI run #3 moved
  them out of the matrix jobs, because a headless runner answers that question with either
  no PortAudio or an empty device list, and neither is a defect.
- `.strict-markers` is on, so an unregistered marker is an error rather than a warning.

### One observed flake, not yet explained

Two runs failed while several pytest processes shared this 8 GB machine, and each command
line ended in `| tail`, which threw the traceback away:

- A `-m integration` run overlapping a full-suite run:
  `tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles`
  (`tests/modules/test_arcade.py:560`) **failed**.
- A full-suite (716-case) run overlapping two `-m integration` runs: **one test failed and its
  name was lost with the traceback**. It is not established to be the arcade case.

Seventeen deliberate reproductions since then came back green, every one with `-rf --tb=line`
so a failure would name itself: three concurrent full-suite runs, six concurrent
`-m integration` runs, two integration runs alongside a full suite, five repeats of the six
arcade-screen cases while a full suite ran beside them, and one standalone full suite. Some of
those carried more concurrency than either failure did.

No fix has been made, because there is no named failing assertion to fix. What reading the
code does say: the arcade case is `@pytest.mark.integration` (`tests/modules/test_arcade.py:559`),
so **no CI column runs it** - the green matrix cannot catch this and a red matrix never will.
It is also machine-sensitive by construction: the app ticks on a real `set_interval` timer
(`src/levix/modules/arcade/screens.py:117`, armed with `interval=0.02` by the test) and the
test advances it by burning a bounded number of `await pilot.pause(0.01)` calls, so its budget
is wall-clock and the scheduler decides whether the snake reaches the wall inside it. `_tick`
itself is synchronous end to end - `step_state`, `draw_state`, `is_over`, `_settle` in that
order (`screens.py:119-127`) - and `snake.py:228` derives `GAME OVER` from `state.alive` with
no timing input, so the two races first suspected (an await reachable between the key and the
assertion, and a stale board string) are not it. That is as far as the evidence goes.

What the observations do support is a practice: on a small machine run one pytest process at a
time, and never pipe the suite through `tail` (`CONTRIBUTING.md` §Development workflow).

## Static checks

| Check | Command | Result on this machine |
| --- | --- | --- |
| Lint | `.venv/Scripts/python.exe -m ruff check src tests plugin-examples` | exit 0, "All checks passed!" |
| Format | `.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples` | exit 0, "81 files already formatted" |
| Types | `.venv/Scripts/python.exe -m mypy` | exit 0, "no issues found in 61 source files" (`[tool.mypy].files` covers `src/levix` **and** `plugin-examples/hello/src`, so the copy-pasteable plugin is checked with the core). Since run #1, `--platform win32`, `--platform linux` and `--platform darwin` are all run here too, because a Linux runner is what found the one Windows-only attribute the tree had |
| Install | `.venv/Scripts/python.exe -m pip install -e ".[dev,all]"` | the only install proven here |
| Distribution | `python -m build` then install the wheel into an empty venv | sdist + wheel build (66 wheel entries, `levix/py.typed` present, `levix/data/defaults.toml` exactly once); in the clean venv all seven modules answer `-h` with 0, the four heavy ones refuse with 3 naming the right extra, and no heavy package is imported (`CHANGELOG.md` §Verification) |
| CI | `.github/workflows/ci.yml`, `.github/workflows/release.yml` | **has run four times.** #1 (`fcbcb22`): the bare-wheel job **passed on Ubuntu** - the first time the extras gate was proven on a platform other than this laptop - and the four POSIX matrix jobs stopped at `Types` on one real cross-platform defect (`st_file_attributes` is Windows-only; `mypy` on a POSIX runner has no stub for it - fixed, and now proven against `--platform win32`, `linux` and `darwin`). #2 (`726909c`) reported "5 successful and 2 failing" and was wrong in both directions: the `Test suite` step piped pytest through `tee` under a shell without `pipefail`, so Linux and macOS went green over a red suite, and both Windows jobs died in pwsh before pytest ran. #3 (`5fdc644`) is the first honest result: **all six columns red, eight test functions between them**, every one of them dependent on the machine it ran on - typer forces a terminal whenever `GITHUB_ACTIONS` is set so the help-page assertions met escape codes, the delete path judged a symlink by its target and refused a safe removal, `os.readlink` returns `\\?\`-prefixed targets on Windows, two tests asked a headless runner about its sound cards, a 68-character macOS runner hostname did not fit the host table's value column, and the AI cap notice wrapped at 80 columns. **#4 (`5b047ad`) is green: run id `42068621524`, all seven jobs `success`, and on each of the six matrix jobs the four steps `Lint`, `Format`, `Types` and `Test suite` individually report `success` - Windows 3.12 and 3.13, Ubuntu 3.12 and 3.13, macOS 3.12 and 3.13 - and the annotation lists hold only GitHub's own `actions/checkout` Node.js-20 deprecation warning plus runner notices, with no `FAILED` line from the suite step. That is the first time this tree has been red-free anywhere other than this laptop, and it confirms all eight fixes on the machines that found them. What the columns do *not* cover: they run `-m "not integration"`, so 690 passed / 5 skipped / 10 deselected per column at that commit and the ten device and OS-tool cases have still only ever run on Windows 11 here; and no column asserts anything about the POSIX items in §What is not verified item 1. `release.yml` has **not** run, and it cannot pass until the PyPI project and its trusted publisher exist (`docs/technology/PYTHON_PACKAGING.md` §Publishing) |
| Doctor | `levix doctor --json` | verdict `degraded`, exit 0; capabilities `ffmpeg`, `media_player`, `audio_output`, `psutil`, `battery`, `keyring`, `platform` are `ok`; `temperature` `degraded` (this psutil has no `sensors_temperatures`), `gpu` `unsupported`, `terminal` `degraded` (stdout not a TTY) |
| Update check | `levix update` | exit 8, `could not check for updates: PyPI returned 404` - the name is unclaimed, and the command refuses to imply "up to date" when it could not ask |

Twelve `# noqa` comments remain, each for a rule that fires on correct code: `S105` on the two
`Permission.SECRET_*` names and `ai/core.SECRET_NAME` (lookup keys, not credentials) and on the
invented `ghp_…` string in `tests/test_logging.py:34`, `S311` on the seeded game/hacker RNGs,
`S310` on the single HTTPS release feed, `S104` on the any-address literal Hacker describes,
`B009` on two `getattr(os, "getuid")` lookups, and `E731`/`S108` in
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
in each one the runner was right about itself. None of these fixes could be re-checked here -
this box cannot create symlinks, has PortAudio and real devices, and is not macOS. Run #4
(`5b047ad`) came back with all six columns green, which is the confirmation; the last column
says exactly what closed each row.

| Defect | Where it showed | Fix | Pinned by | Closed by run #4 |
| --- | --- | --- | --- | --- |
| Deleting a link judged it by its target, so a link inside the wall pointing outside it was refused | Ubuntu, macOS | `core.resolve(..., keep_link=True)`, used by `plan_delete` alone | `test_a_link_deleted_as_a_link_is_judged_at_its_own_place` | Ubuntu and macOS `Test suite` green, and `test_deleting_a_link_removes_the_link_and_never_the_target` ran against a real link on both |
| A link's target was shown as `\\?\C:\Users\...`, the DOS-device form `os.readlink` returns | Windows | `core.strip_device_prefix` | `test_the_device_prefix_windows_stores_in_a_link_is_removed` | Windows 3.12 and 3.13 green, with the five parametrized prefix cases included |
| The hostname was folded in the middle of the token by a 65-character table column | macOS (68-character runner name) | the name prints as a full-width line under the host table | `test_a_hostname_longer_than_the_table_stays_in_one_piece` | macOS 3.12 and 3.13 green, both on that 68-character name |
| Help-page assertions met escape codes, because typer forces a terminal when `GITHUB_ACTIONS` is set | all six columns | `tests/test_router.py::capsys_text` strips them before matching | the two router cases run with `GITHUB_ACTIONS=true` here | all six green, so the stripping works under the real variable |
| Two cases asked a headless runner which sound cards it has | Ubuntu (no PortAudio), Windows (no devices) | marked `integration`, and each skips out loud | `pytest -m integration` collects 10 | they no longer run in CI, so the columns are silent about them; `-m integration` is still green here (10 passed) |
| The cap notice wrapped after "showing" at 80 columns | Ubuntu | the case pins `COLUMNS=200` | `test_explain_sends_only_the_capped_prefix` | Ubuntu green - the case no longer reads the width the runner happens to have |
| A Windows-only stat attribute typed clean on Windows and failed `mypy` on POSIX | Ubuntu, macOS (`Types`) | `getattr(os.lstat(path), "st_file_attributes", 0)` | `mypy --platform win32\|linux\|darwin` | `Types` green on all six |
| The suite step reported success over a failing suite (`pytest \| tee`, no `pipefail`), and pwsh ran bash-only syntax | run #2, both were false | `defaults.run.shell: bash`, redirect then echo, `FAILED` lines re-emitted as annotations | no test can hold a workflow file | both directions now observed: #3 failed the step and named eight tests in annotations, #4 passed it and annotated no failure |

## What is not verified, and should not be claimed

1. **POSIX behaviours no test asserts.** The `chmod` in `secrets._harden` does run on the
   Ubuntu and macOS columns (`tests/modules/test_ai.py:587` writes the file store, and the
   chmod at `secrets.py:136-137` runs on every platform - wrapped in `suppress(OSError)`, so a
   failure is silent by design), but nothing stats the resulting mode, so
   "the secrets file is owner-only on Linux" is still a reading of the code, not an
   observation. Same for the OS keyring backend, the `ip addr show` / `ifconfig` /
   `resolv.conf` / `nsswitch.conf` / `route -n` parsers - the suite feeds them captured POSIX
   text and never runs the tools - and for the platformdirs layout on Linux/macOS. Run #4
   proves the POSIX *branches* the tests reach execute cleanly on Ubuntu and macOS; it proves
   none of the four things above, and no POSIX command's real output has been parsed here.
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
6. **Redaction outside the four patterns.** `tests/test_logging.py` (6 functions, 11 cases)
   now pins what `RedactFilter` promises - bearer header, `sk-…`, `ghp_`-shaped token,
   `key=value` where the key says `api_key`/`token`/`secret`/`password` - including that a key
   does not reach the log file and that a handler added by someone else still gets redacted.
   What is still not covered is the shape the patterns do not name: a JWT in a provider's
   error body is logged verbatim, because redaction is regex-based, not schema-based
   (`docs/security/THREAT_MODEL.md` Known gaps 2). The file-backed case has also only run on
   Windows so far; the run #5 columns are what will say it holds on Linux and macOS.
7. **`levix update` and `levix create-module`.** No tests; the scaffold the generator emits
   is the shape `tests/test_plugin_example.py` proves by hand, but the generated tree is
   never executed.
8. **Plugin install/publish.** `levix plugins` offers `list` and `info` only; installing a
   plugin means `pip install` in this environment. Deliberate, documented, and still a gap.
9. **`UiSpec(mode="screen")`.** `registry.build_screen` exists and is tested for its failure
   branch; no manifest in the tree declares a screen, all seven use `suspend`.
10. **A release, and a green run of the whole suite off this laptop.** Run #4 is green on all
    six columns, so the eight machine-dependent fixes are confirmed; but each column runs
    `-m "not integration"`, so what Linux and macOS have never executed is the ten device and
    OS-tool cases, and the new redaction tests arrive only in run #5. `release.yml` has **not**
    run, and it cannot pass until the PyPI project and its trusted publisher exist
    (`docs/technology/PYTHON_PACKAGING.md` §Publishing). The matrix is 3.12 and 3.13 only - no
    runner has ever used another Python version.
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

1. Read run #5. Run #4 (`5b047ad`) is green on all six columns, so the eight machine-dependent
   fixes are confirmed on the machines that found them - including
   `test_deleting_a_link_removes_the_link_and_never_the_target`, which failed on Ubuntu and
   macOS in #3 and therefore really does reach a symlink there. Run #5 adds
   `tests/test_logging.py`: the file-backed redaction case is the first test in the CI set
   that opens a real rotating log, so its result on Linux and macOS is the new thing to look
   at.
2. Assert the mode of the secrets file rather than the code that sets it. `secrets._harden`
   runs `chmod 0600` on every platform and swallows the failure, and no test stats the result
   - that is the first half of gap 1, and unlike the parsers it needs no fake.
3. Close the arcade flake by removing its dependence on the scheduler, not by guessing at a
   cause: `test_the_snake_screen_steers_on_a_key_redraws_and_settles` advances a real
   `set_interval` timer with a fixed count of `pilot.pause(0.01)` calls, so its budget is
   wall-clock. If it fails again, run it without `| tail` and read the assertion; if it does
   not, the budget is still the thing to change. See §One observed flake, not yet explained.
4. Add tests for `levix update` (against a stubbed PyPI) and `levix create-module` (generate
   into a temp dir, then import the scaffolded `MANIFEST`).
5. Decide the fate of `mode="screen"`: either give one module a real embedded screen or drop
   the mode. Documented-but-unused API is a tax on every reader.
6. Do the one-time PyPI side that a checkout cannot do: the account with 2FA, the project
   `levix`, the trusted publisher naming this repo + `release.yml` + the `pypi` environment,
   and that environment in GitHub Settings. Then `git tag v0.4.0 && git push origin v0.4.0`,
   which is the first time README's `pipx install levix` is true and the first time
   `levix update` has a real answer to give.
7. Only after a release exists: the standalone binaries (starting with the frozen-metadata
   question in `PYTHON_PACKAGING.md`), a winget manifest, and `levix plugins install` /
   `publish`.

## How to reproduce the numbers in this page

```bash
.venv/Scripts/python.exe -m pytest -o addopts="" -q              # the suite, all 716 cases
.venv/Scripts/python.exe -m pytest -o addopts="" -q -m "not integration"   # the 706 CI runs
.venv/Scripts/python.exe -m pytest -o addopts="" -q -m integration         # just the 10 device/OS cases
.venv/Scripts/python.exe -m ruff check src tests plugin-examples        # lint
.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples  # format
.venv/Scripts/python.exe -m mypy                                 # types (core + example plugin)
COLUMNS=100 .venv/Scripts/levix.exe doctor --json                # what this machine can actually do
```

Those six lines are `.github/workflows/ci.yml`'s `suite` job, run by hand on one platform.
The repository's `addopts = "-q --strict-markers"` deselects no marker, so an unmodified
`pytest` is the full 716 cases here; a job that must not touch a device or an OS tool has to
say `-m "not integration"` explicitly rather than assume the config does it. `-o addopts=""`
is in the lines above because adding `-q` to the config's own `-q` gives `-qq`, which prints
progress but no summary line - the numbers in this page would otherwise be unrepeatable.

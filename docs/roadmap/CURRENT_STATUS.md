# Current status

**Read this first if you are picking the project up cold.** Every other page in `docs/`
describes the shape of the code; this page states what is actually true on what machine,
what was proven how, and what is still open. It is written from a hand run, not from
memory: each claim names the command or test that shows it.

- Version: `levix 0.4.0` (`levix --version`), plus the unreleased work in `CHANGELOG.md`.
- Date of the state below: 2026-11-05.
- Hand-run on **one machine**: Windows 11 build 26200, AMD64, Python 3.12.10 in the
  project-local `.venv`, 8 GB RAM, stdout captured (not a TTY) for every test run.
- **CI runs #4 (`5b047ad`), #5 (`75daed2`) and #6 (`3d460df`) are all green**: all six matrix columns -
  Windows, Ubuntu and macOS at 3.12 and 3.13 - passed `Lint`, `Format`, `Types` and `Test suite`, and
  the bare-core wheel job passed on Ubuntu. Run #6 is the one that matters more: it is the first
  to carry `tests/test_secrets.py`, so its three POSIX-only permission cases - which skip on this
  laptop because Windows derives `st_mode` from file attributes - executed on Ubuntu 3.12, Ubuntu
  3.13, macOS 3.12 and macOS 3.13 and reached no failure. That is the first evidence off this
  machine that a real `secrets.json` written by the real `secrets.set_secret` comes out mode `0600`
  under a POSIX umask, including when `Path.chmod` is sabotaged.
- **Run #7 (`c49d608`, run id `42083876435`) has conclusion `failure`, and the tree is not why.**
  Six of its seven jobs report `success` - the bare-core wheel job on Ubuntu, and `Lint`, `Format`,
  `Types` and `Test suite` individually `success` on Windows 3.12, Windows 3.13, Ubuntu 3.12,
  Ubuntu 3.13 and macOS 3.13. The seventh, `macos-latest / Python 3.12`, is `cancelled` with **no
  runner name and no steps at all**, and the run page annotates it "The job was not acquired by
  Runner of type hosted even after multiple attempts"; the run took 15 m 3 s against the ~6 m of
  the green runs, which is what waiting for a runner looks like. So this is a fact about GitHub's
  macOS capacity, not about LEVIX, and it is recorded as a non-green run rather than smoothed over.
  What it does prove is the useful half: run #7 is the first tree carrying `tests/test_update.py`
  (10 functions) and `tests/test_create_module.py` (9 functions, 13 cases), so both executed on
  Ubuntu 3.12/3.13, Windows 3.12/3.13 and macOS 3.13 - including the case that generates a plugin
  into a temporary directory, registers it as a distribution and runs `pytest` **inside the
  generated project** in a child interpreter. Five columns ran that, and none reached a failure.
  It was read with two API calls (`/actions/runs/{id}`, then `/jobs`) after the rate limit reset,
  not by polling: the earlier poll loop spent the whole hour's budget and never saw the run.
So the suite has executed on three
operating systems and four Python versions, on GitHub's runners. It does not make this project
"cross-platform verified". Two limits hold.
First, those columns run `-m "not integration"`, which on run #6's tree was 710 of its 720
cases and on run #7's was 733 of 743: the ten device/OS-tool cases have only ever run here, and
nothing has been hand-run on Linux or macOS. Second, the per-column pass and skip counts were
never read - GitHub returns
403 for a run's log archive to an unauthenticated caller, and the attempt to re-read run #6's
per-job annotations exhausted the 60-calls-per-hour unauthenticated limit partway through (five
`404`s and one `403`, with `/rate_limit` then reporting `core.remaining = 0`) - so what is known
about a column is its step conclusions (`Lint`, `Format`, `Types`, `Test suite` all `success`)
and nothing finer. A green column says the selection reached no failure; it does not
say which cases skipped, and §What is not verified item 1 lists the POSIX behaviours no test
asserts even when an Ubuntu runner is the one executing them.
`docs/technology/COMPATIBILITY.md` says what each platform is missing.

## One-paragraph summary

LEVIX is one executable fronting seven terminal applications, with a plugin contract built
on `importlib.metadata` entry points. The core is six lightweight dependencies
(click, platformdirs, rich, textual, tomlkit, typer); every module-specific dependency
(psutil, yt-dlp, soundfile/sounddevice/numpy, httpx, keyring) is an extra and is gated at
run time with a message that names the extra. The dashboard is a launcher: it never calls
module internals, it re-enters `levix <module> …` in a child process with the terminal
suspended. Commands, modules, errors, exit codes, configuration layering and the
dependency gate are covered by a 664-function suite that runs without network, without a
real device and without a real terminal.

## What is built, and how each part is proven

| Part | Exists | Proven by |
| --- | --- | --- |
| Core engine (registry, router, config, storage, secrets, deps gate, capabilities, errors, logging, terminal) | 21 top-level modules under `src/levix/` | 14 test files in `tests/` (161 functions, 180 collected cases), `tests/test_logging.py` (6 / 11) and `tests/test_secrets.py` (4 / 4) among them |
| Textual dashboard (module list, detail panel, history, theme, suspend-and-run launcher) | `src/levix/dashboard/` | `tests/test_dashboard.py` (19) driven headlessly through Textual's Pilot |
| Platform commands: `doctor`, `config`, `plugins`, `history`, `create-module`, `update`, `secrets` handling | `src/levix/commands/` | `tests/test_doctor.py` (6), `tests/test_config.py` (20), `tests/test_markup_safety.py` (9), `tests/test_update.py` (10) against a stubbed `urlopen`, `tests/test_create_module.py` (9 / 13) which generates a project into a temp dir, registers it as a distribution and runs it through the real router |
| Tube | `src/levix/modules/tube/` | 62 functions / 76 cases against a fake `yt_dlp`, no network |
| Hacker | `…/hacker/` | 53 / 79, OS reporting driven with captured text |
| SystemPulse (`monitor`) | `…/systempulse/` | 40 / 46 against a psutil stand-in in `sys.modules`, plus five `run_cli` cases against real psutil |
| AI | `…/ai/` | 82 / 97 against a stubbed httpx transport |
| Music | `…/music/` | 104 / 155; three cases are marked `integration` and need a machine with sound hardware. The fetch runs against a fake `yt_dlp` in a second seam, so no case contacts a network; the spectrum rules are pure functions in `music/visual.py` |
| Arcade (`game`) | `…/arcade/` | 39 / 43, rules as pure functions plus Pilot-driven screens |
| Files | `…/files/` | 123 / 153 in a temporary filesystem |
| Plugin contract and a real third-party module | `levix.sdk` (14 re-exports), `plugin-examples/hello/` | `tests/test_registry.py` (12), `tests/test_plugin_example.py` (8) which registers the example through a hand-built `dist-info` and runs the real router over it |

## Test suite as last run

```
.venv/Scripts/python.exe -m pytest -o addopts="" -q
664 test functions in 21 files, collecting to 829 parametrised cases
821 passed, 8 skipped, 2 warnings in 123.32 s   (exit 0)
```

The same tree, one process at a time, split the way CI splits it:

```
-m "not integration"   811 passed, 8 skipped, 10 deselected in 100.90 s   (exit 0)
-m integration         10 passed, 819 deselected, 2 warnings in 10.85 s   (exit 0)
```

The `-o addopts=""` clears `-q --strict-markers`; it changes nothing about which cases run,
because `addopts` deselects no marker.

- The eight skips split by why. Five are symlink cases in `tests/modules/test_files.py`: two
  fail with `WinError 1314` (this account cannot create symlinks) and three state that POSIX
  symlinks need no privilege here. Three are the POSIX-only permission cases in
  `tests/test_secrets.py`, guarded by `skipif(os.name != "posix")` - they skipped here and ran on
  the Ubuntu and macOS columns of CI run #6, which is where that half of the claim now comes from.
  Every skip names its reason; none is a silent pass.
- Ten cases carry `@pytest.mark.integration` (`pytest -m integration` collects exactly
  `10/829 tests, 819 deselected`). The repository's `addopts` is `-q --strict-markers` and
  deselects nothing, so the default run above already includes them - among them the real
  audio-device playback test, which skips itself when PortAudio reports no output device.
  Three of the ten ask the operating system which sound hardware it has; CI run #3 moved
  them out of the matrix jobs, because a headless runner answers that question with either
  no PortAudio or an empty device list, and neither is a defect.
- `.strict-markers` is on, so an unregistered marker is an error rather than a warning.

### The flake, explained and closed

Two runs failed while several pytest processes shared this 8 GB machine, and each command
line ended in `| tail`, which threw the traceback away:

- A `-m integration` run overlapping a full-suite run:
  `tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles`
  (`tests/modules/test_arcade.py:560`) **failed**.
- A full-suite (716-case) run overlapping two `-m integration` runs: **one test failed and its
  name was lost with the traceback**. It is not established to be the arcade case.

Seventeen deliberate reproductions came back green, every one with `-rf --tb=line` so a failure
would name itself: three concurrent full-suite runs, six concurrent `-m integration` runs, two
integration runs alongside a full suite, five repeats of the six arcade-screen cases while a
full suite ran beside them, and one standalone full suite. Those green runs were read as
evidence for contention, which was the wrong reading - they only show the failure is rare.

The case then named itself, in a sequential `-m integration` run with no other pytest process
alive and no pipe on the command line:

```
>       assert app.state.alive and app.state.direction == "right", "r starts a new round"
E       AssertionError: r starts a new round
E       assert (False)
E        +  where False = Snake(width=12, height=8, body=((11, 4), (10, 4), (9, 4)), direction='right', food=(7, 1), score=0, ticks=6, alive=False, full_board=False).alive

tests\modules\test_arcade.py:601: AssertionError
FAILED tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles
1 failed, 9 passed, 710 deselected, 2 warnings in 9.67s
```

That traceback falsifies contention as the *cause*: it reproduced alone. The cause is the test's
own arithmetic. `snake_rules.new_game` (`src/levix/modules/arcade/snake.py:88-90`) puts the head
at `width // 2` heading right, so on the 12-column board this case builds the restarted snake
has six columns to cross and dies on its sixth tick; `interval=0.02` makes that about 120 ms.
`restart_game` re-arms the timer (`screens.py:106-117`) and `pilot.pause()` returns once the
message pump is idle, so by the time that line read `app.state.alive` the clock had already run
the snake into the wall - the reported `ticks=6` is exactly the predicted number. The assertion
measured scheduling, not the `r` binding.

The fix takes the clock out of that assertion instead of widening its budget: the case now pins
the *new* round's tick at 60 s through the lever the app already documents for tests
(`app.forced_interval`, `screens.py:206-207`, read by `interval_seconds()` when `restart_game`
re-arms), and then asserts what the binding is actually responsible for - `(direction, ticks,
score)` back at `("right", 0, 0)`, head at `(cols // 2, rows // 2)`, body at `START_LENGTH`, the
board no longer showing `GAME OVER`, and still exactly one row stored
(`tests/modules/test_arcade.py:602-611`). The polls above the death check keep their wall-clock
budgets because they wait for the snake to *die*, where extra elapsed time only costs more
iterations; the one below it waited for the snake to be *alive*, where extra elapsed time in
that window ends the round before the assertion reads it. That asymmetry is why this single
assertion was the only thing that ever failed.

Verified by running that one case fifteen times in a row with no other pytest process alive:
fifteen passes, no `FAILED` line, and `-m integration` green at 10 passed. Fifteen green
repeats is evidence, not proof; the argument that closes it is that at 60 s per tick no timer
can fire inside the assertion's window.

Two practices come out of it. On a small machine, run one pytest process at a time and never
pipe the suite through `tail` (`CONTRIBUTING.md` §Development workflow) - the two lost tracebacks
cost more investigation than the fix did. And note where the matrix stands: this case is
`@pytest.mark.integration` (`tests/modules/test_arcade.py:559`), so **no CI column runs it**;
the green matrix could not have caught this defect and would not catch its return. Any future
work on the screens has to be verified here, because the runners do not look at it.

## Static checks

| Check | Command | Result on this machine |
| --- | --- | --- |
| Lint | `.venv/Scripts/python.exe -m ruff check src tests plugin-examples` | exit 0, "All checks passed!" |
| Format | `.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples` | exit 0, "85 files already formatted" (the 85th is `src/levix/modules/music/visual.py`). The same check over `.` is also clean (126 files) because ruff 0.17 formats fenced Python inside Markdown - prose blocks re-wrap only when a snippet is genuinely mis-wrapped |
| Types | `.venv/Scripts/python.exe -m mypy` | exit 0, "no issues found in 62 source files" (`[tool.mypy].files` covers `src/levix` **and** `plugin-examples/hello/src`, so the copy-pasteable plugin is checked with the core). Since run #1, `--platform win32`, `--platform linux` and `--platform darwin` are all run here too, because a Linux runner is what found the one Windows-only attribute the tree had; each of the three reports the same 62 clean |
| Install | `.venv/Scripts/python.exe -m pip install -e ".[dev,all]"` | the only install proven here |
| Distribution | `python -m build` then install the wheel into an empty venv | sdist + wheel build (66 wheel entries, `levix/py.typed` present, `levix/data/defaults.toml` exactly once); in the clean venv all seven modules answer `-h` with 0, the four heavy ones refuse with 3 naming the right extra, and no heavy package is imported (`CHANGELOG.md` §Verification) |
| CI | `.github/workflows/ci.yml`, `.github/workflows/release.yml` | **has run nine times, and the eighth and ninth are green.** #1 (`fcbcb22`): the bare-wheel job **passed on Ubuntu** - the first time the extras gate was proven on a platform other than this laptop - and the four POSIX matrix jobs stopped at `Types` on one real cross-platform defect (`st_file_attributes` is Windows-only; `mypy` on a POSIX runner has no stub for it - fixed, and now proven against `--platform win32`, `linux` and `darwin`). #2 (`726909c`) reported "5 successful and 2 failing" and was wrong in both directions: the `Test suite` step piped pytest through `tee` under a shell without `pipefail`, so Linux and macOS went green over a red suite, and both Windows jobs died in pwsh before pytest ran. #3 (`5fdc644`) is the first honest result: **all six columns red, eight test functions between them**, every one of them dependent on the machine it ran on - typer forces a terminal whenever `GITHUB_ACTIONS` is set so the help-page assertions met escape codes, the delete path judged a symlink by its target and refused a safe removal, `os.readlink` returns `\\?\`-prefixed targets on Windows, two tests asked a headless runner about its sound cards, a 68-character macOS runner hostname did not fit the host table's value column, and the AI cap notice wrapped at 80 columns. **#4 (`5b047ad`) is green: run id `42068621524`, all seven jobs `success`, and on each of the six matrix jobs the four steps `Lint`, `Format`, `Types` and `Test suite` individually report `success` - Windows 3.12 and 3.13, Ubuntu 3.12 and 3.13, macOS 3.12 and 3.13 - and the annotation lists hold only GitHub's own `actions/checkout` Node.js-20 deprecation warning plus runner notices, with no `FAILED` line from the suite step. That is the first time this tree has been red-free anywhere other than this laptop, and it confirms all eight fixes on the machines that found them. **#5 (`75daed2`) is green too: run id `42074244730`, all seven jobs `success`, the same four steps individually `success` on all six columns, annotations again only GitHub's Node.js-20 deprecation warning plus the `ubuntu-latest` migration and macOS capacity notices.** Run #5 is the first to carry `tests/test_logging.py`, so `test_a_key_never_reaches_the_log_file` - the only case that opens a real rotating `levix.log` - has now executed on Ubuntu and macOS as well, which is the thing that row was added to find out. **#6 (`3d460df`) is green as well: run id `42078880293`, all seven jobs `success`, and the four steps `Lint`, `Format`, `Types` and `Test suite` individually `success` on every one of the six columns.** Run #6 is the first to carry `tests/test_secrets.py`, whose three POSIX-only cases therefore ran on Ubuntu 3.12, Ubuntu 3.13, macOS 3.12 and macOS 3.13 instead of skipping, and the columns still came back green - the `0600` the `os.open` asks for is now a measured fact about a POSIX filesystem rather than an assertion only this laptop could make. This time the per-job annotations could not be read at all: the attempt ran into the 60-calls-per-hour unauthenticated limit partway through the loop (five `404`s, one `403`, `/rate_limit` then reporting `core.remaining = 0`), so run #6 is recorded from the run conclusion and the step conclusions only. **#7 (`c49d608`, run id `42083876435`) is `failure`, and reading it is the reason §What to do next no longer describes a poll loop**: six of seven jobs `success` - the wheel job, and `Lint`/`Format`/`Types`/`Test suite` individually `success` on Windows 3.12, Windows 3.13, Ubuntu 3.12, Ubuntu 3.13 and macOS 3.13 - while `macos-latest / Python 3.12` is `cancelled` with no runner name and no steps, annotated "The job was not acquired by Runner of type hosted even after multiple attempts", in a run that took 15 m 3 s against the ~6 m of a green one. Nothing in the tree was implicated: GitHub never gave that job a machine. Run #7 is still the first run whose tree carried `tests/test_update.py` and `tests/test_create_module.py`, so those 19 functions and 23 cases executed on five columns - Ubuntu both versions, Windows both versions and macOS 3.13 - and the generator's child-interpreter `pytest` step ran on Linux and macOS for the first time; none of the five reached a failure. **#8 (`b748591`, run id `42089712550`) is green: all seven jobs `success`, `Lint`/`Format`/`Types`/`Test suite` individually `success` on all six columns - Windows 3.12 and 3.13, Ubuntu 3.12 and 3.13, and macOS 3.12 and 3.13 both with a named hosted runner - the wheel job's six named steps (`Build the distribution` through `The stdlib-only modules and the platform commands still work`) `success`, and the per-job `annotations` arrays empty this time.** Run #8 is the first tree with the hidden-module cases, and it carries `tests/test_secrets.py`, so that file's three POSIX cases ran on all four POSIX columns rather than skipping; the macOS 3.12 column that run #7 lost to runner starvation is the one that came back here, which is the whole difference between a `failure` conclusion and a `success` one on this project's matrix. **#9 (`2971bf9`, run id `42104375387`) is green the same way - all seven jobs `success`, the four steps individually `success` on all six columns, both macOS columns with named runners, the wheel job's six named steps `success`, annotations empty again - and it is the run that matters for this feature: it is the first tree carrying the 81 stream-visualiser cases, so the URL gate, the cache containment, the byte cap and the spectrum rules have now executed on Ubuntu and macOS as well as Windows.** Run #9 took 2 m 22 s from creation to its last job completing, against run #8's 6 m 12 s, which is what `cache: pip` buys: `2971bf9` did not touch `pyproject.toml`, so the cache key the #8 install warmed is still the key. What the columns do *not* cover: they run `-m "not integration"`, which was 710 of run #6's 720 cases, 738 of run #8's 748 and is 819 of run #9's - and this tree's - 829 - and the per-column pass and skip counts were never read, because GitHub answers an unauthenticated `GET /actions/runs/{id}/logs` with 403, so what is known about a column is its step conclusions - plus, for runs #4, #5, #8 and #9, their annotations - and nothing finer. Either way the ten `integration` cases - three `music` needing a real device, two `arcade` and three `files` driving a screen, two `hacker` running the OS's own network tools - have only ever run on Windows 11 here; and no column asserts anything about the POSIX items still open in §What is not verified item 1. `release.yml` has **not** run, and it cannot pass until the PyPI project and its trusted publisher exist (`docs/technology/PYTHON_PACKAGING.md` §Publishing) |
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
| The scaffold's manifest put `Permission.FS_READ` in `permissions` **as a string**, so `levix plugins info <new-module>` died on `p.value` with an `AttributeError` | `frozenset({{Permission.FS_READ}})` in `_template` - the enum member, as `docs/architecture/PLUGIN_ARCHITECTURE.md` already documented | `tests/test_create_module.py::test_the_generated_manifest_loads_through_the_real_registry`, `::test_the_disclosure_report_reads_the_generated_permissions` |
| The scaffold's own README told the author to run `levix <name> hello`; Typer mounts a one-command app as the command, so click refused the extra argument (exit 2) while `levix <name> -h` still advertised `hello` | the README shows `levix <name>` and `levix <name> you`, and the test asserts the string `hello` is not in it | `tests/test_create_module.py::test_the_scaffold_writes_every_file_the_contract_needs`, `::test_the_generated_command_runs_through_the_real_router` |
| The scaffold's command body interpolated `{display}`, a variable that exists only in the generator, so the first run of a fresh module raised `NameError: name 'display' is not defined` | prints `MANIFEST.title` with `markup=False`, which also stops a caller-supplied `[/bold]` from being read as a style tag | `tests/test_create_module.py::test_the_generated_command_runs_through_the_real_router` |
| The scaffold's own `tests/test_manifest.py` asserted `build_app()._name`, an attribute Typer 0.27 does not have, so `pytest` failed inside a brand-new project | asserts `build_app().info.name` | `tests/test_create_module.py::test_the_generated_project_passes_its_own_test_suite`, which runs the generated suite in a child interpreter |
| `UiSpec(mode="hidden")` was documented as "not offered by the dashboard" while `module_list.build_rows` returned a row for **every** discovered manifest, so the example plugin's declaration hid nothing and `levix hello` was listed like the rest | `build_rows` skips a manifest whose `ui.mode` is `hidden`, and the docstring now describes what the code does | `tests/test_plugin_example.py::test_the_hidden_example_is_discovered_but_gets_no_dashboard_row` (the real plugin, not a stub), `tests/test_dashboard.py::test_a_module_hidden_from_the_dashboard_gets_no_row`, `::test_a_hidden_module_reaches_no_widget_the_app_builds` |
| `levix plugins info` printed `dashboard : not offered` for a manifest that declares no `UiSpec` - the opposite of the app, which lists it and runs `<name> -h` | prints the effective mode, `suspend (no UiSpec declared)` | `tests/test_dashboard.py::test_a_manifest_with_no_uispec_is_disclosed_as_offered_by_default` |

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

1. **POSIX behaviours no test asserts.** The secrets file is no longer one of them, in either
   sense: `tests/test_secrets.py` stats `secrets.json` after a real write and asserts mode `0600`,
   with the `chmod` refused, and with a pre-existing `0644` store overwritten back to `0600`. Those
   three cases skip on this laptop (Windows derives `st_mode` from file attributes, not from
   anything `_harden` does) and ran for the first time on a POSIX filesystem in CI run #6, on
   Ubuntu 3.12/3.13 and macOS 3.12/3.13, where they did not skip and did not fail. The Windows half
   of the same file reads the real `icacls` output here. What is still unread as
   behaviour: the OS keyring backend, the `ip addr show` / `ifconfig` / `resolv.conf` /
   `nsswitch.conf` / `route -n` parsers - the suite feeds them captured POSIX text and never
   runs the tools - and the platformdirs layout on Linux/macOS. Run #4
   proves the POSIX *branches* the tests reach execute cleanly on Ubuntu and macOS; it proves
   none of the things above, and no POSIX command's real output has been parsed here.
2. **A real terminal.** The dashboard on a screen, `files browse`, `monitor live`,
   `hacker matrix` animating, Snake and Tetris played by key. Every one is exercised through
   Textual's Pilot or through the non-TTY refusal path.
3. **Typed destructive words.** No human typed `DELETE`, `OVERWRITE` or `RUN` at a prompt;
   `approve.py:51-59` is covered only by the pipe refusal.
4. **Sound and video.** Audible playback is the `integration` device test. `ffmpeg`,
   `ffprobe` and `ffplay` are installed on this machine and probe `ok`, but merged-stream
   download and `--convert-to` were never run against a real URL. Nor was a fetched stream ever
   *heard*: what the loopback run below exercised is the failure path, and the spectrum bars are
   asserted as numbers (`music/visual.py`) and as a flag-and-config gate - never as rendered
   frames, because no case runs the `Live` renderer with a terminal attached
   (`docs/modules/MUSIC.md` gap 11).
5. **Any network call.** No test reached a site: Tube's `_make_ydl` seam is replaced, Music's
   own `core._make_ydl` seam is replaced the same way for `music play <url>`, AI's
   transport is stubbed, and `levix update` is now pinned by `tests/test_update.py` against a
   fake `urllib.request.urlopen` - which proves the parsing, the comparison, the exit codes and
   the request shape, and proves nothing about what `pypi.org/pypi/levix/json` actually answers.
   The hand run still says `PyPI returned 404`, because the name is unclaimed.
   `levix ai` has never spoken to a real model server. The one real outbound attempt made for the
   record was `levix music play http://127.0.0.1:1/tone` - yt-dlp, ffmpeg on `PATH`, a closed
   port on the loopback interface - which took about 3.8 s, printed one message and exited 8;
   that pins the failure mapping and the one-report rule and says nothing about any site
   (`docs/modules/MUSIC.md` gap 8).
6. **Redaction outside the four patterns.** `tests/test_logging.py` (6 functions, 11 cases)
   now pins what `RedactFilter` promises - bearer header, `sk-…`, `ghp_`-shaped token,
   `key=value` where the key says `api_key`/`token`/`secret`/`password` - including that a key
   does not reach the log file and that a handler added by someone else still gets redacted.
   What is still not covered is the shape the patterns do not name: a JWT in a provider's
   error body is logged verbatim, because redaction is regex-based, not schema-based
   (`docs/security/THREAT_MODEL.md` Known gaps 2). The file-backed case has run on the Linux and
   macOS columns since (`75daed2`, run #5, green on all six), so the rotating-log path is not a
   Windows-only result.
7. **`levix update` and `levix create-module`.** Both are covered now, and the coverage found four
   defects in the scaffold - the quoted `Permission`, the `{display}` `NameError`, the README's
   `levix <name> hello`, and a generated `tests/test_manifest.py` that asserted a private
   `Typer._name` and failed on the author's first `pytest` (§Defects found by reading the docs
   against the code). What the tests do not do: no case runs `pip install -e .` on the generated
   project (the `dist-info` is written by hand, exactly as in `tests/test_plugin_example.py`), and
   `levix update` has never been pointed at the real PyPI, because there is no `levix` distribution
   to answer yet.
8. **Plugin install/publish.** `levix plugins` offers `list` and `info` only; installing a
   plugin means `pip install` in this environment. Deliberate, documented, and still a gap.
9. **`UiSpec(mode="screen")` - closed by deletion, and `hidden` made real.**
   `registry.build_screen`, `UiSpec.screen_path` and the `"screen"` literal are gone: no manifest
   declared a screen, nothing called the resolver, and the mode could not have worked anyway,
   because the dashboard is itself a Textual app and one TTY hosts one. The more serious half was
   that `hidden`, documented as "not offered by the dashboard", filtered nothing:
   `module_list.build_rows` returned a row for every discovered manifest, so the example plugin's
   `UiSpec(mode="hidden")` hid nothing at all. `build_rows` filters now, `plugins info` no longer
   prints `not offered` for a manifest that declares no `UiSpec` (the dashboard offers exactly
   those, with the default mode), and
   `tests/test_dashboard.py::test_a_module_hidden_from_the_dashboard_gets_no_row`,
   `::test_a_hidden_module_reaches_no_widget_the_app_builds`,
   `::test_no_official_module_hides_itself_from_the_dashboard` and
   `tests/test_registry.py::test_a_module_hidden_from_the_dashboard_is_still_discovered_and_routable`
   are the proof. Deleting a field from `levix.sdk` is safe only because nothing has been
   published yet - see item 10 and `docs/technology/PYTHON_PACKAGING.md` §Publishing.
10. **A release, and a green run of the whole suite off this laptop.** Runs #4, #5, #6, #8 and #9
    are green on all six columns, so the eight machine-dependent fixes are confirmed, the redaction
    tests and the three POSIX permission cases have executed on Linux and macOS, and so has every
    case added since - the four hidden-module ones and the 81 stream-visualiser ones; but each column
    runs `-m "not integration"`, so what Linux and macOS have never executed is the ten
    `integration` cases - three `music`, two `arcade`, three `files`, two `hacker` - and the full
    suite has still never run outside this laptop.
    `release.yml` has **not**
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

1. Do the one-time PyPI side that a checkout cannot do: the account with 2FA, the project
   `levix`, the trusted publisher naming this repo + `release.yml` + the `pypi` environment,
   and that environment in GitHub Settings. Then `git tag v0.4.0 && git push origin v0.4.0`,
   which is the first time README's `pipx install levix` is true and the first time
   `levix update` has a real answer to give. Nothing in this repository tags itself, and no
   agent run does it on the maintainer's behalf.
2. Only after a release exists: the standalone binaries (starting with the frozen-metadata
   question in `PYTHON_PACKAGING.md`), a winget manifest, and `levix plugins install` /
   `publish`.

_How a run gets read, since two runs were mis-read before this method worked_: read a
**finished** run, not a waiting one. The unauthenticated API allows 60 calls an hour, and the
loop that polled run #7 every 20 seconds spent the whole budget and died on
`403 rate limit exceeded` before the run was legible. Runs #7, #8 and #9 each took two calls -
the run list, then `/jobs` - and the CI row of §Static checks is what those four answers gave.
Note the shape of run #7 in particular: a run can end `failure` while every job that actually
executed is green, so "the suite is green on CI" needs the job list, not the run badge.

## How to reproduce the numbers in this page

```bash
.venv/Scripts/python.exe -m pytest -o addopts="" -q              # the suite, all 829 cases
.venv/Scripts/python.exe -m pytest -o addopts="" -q -m "not integration"   # the 819 CI runs
.venv/Scripts/python.exe -m pytest -o addopts="" -q -m integration         # just the 10 device/OS cases
.venv/Scripts/python.exe -m ruff check src tests plugin-examples        # lint
.venv/Scripts/python.exe -m ruff format --check src tests plugin-examples  # format
.venv/Scripts/python.exe -m mypy                                 # types (core + example plugin)
COLUMNS=100 .venv/Scripts/levix.exe doctor --json                # what this machine can actually do
```

Four of those lines are `.github/workflows/ci.yml`'s `suite` job - `Lint`, `Format`, `Types` and
`Test suite` - and the `Test suite` step is the `-m "not integration"` line; the bare run and the
`-m integration` line are how this machine covers the ten cases the matrix deselects.
The repository's `addopts = "-q --strict-markers"` deselects no marker, so an unmodified
`pytest` is the full 829 cases here; a job that must not touch a device or an OS tool has to
say `-m "not integration"` explicitly rather than assume the config does it. `-o addopts=""`
is in the lines above because adding `-q` to the config's own `-q` gives `-qq`, which prints
progress but no summary line - the numbers in this page would otherwise be unrepeatable.

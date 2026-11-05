# Changelog

All notable changes to LEVIX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

Everything below is work done after the `0.4.0` commit and is not yet released: the
documentation set, the packaging fix, a set of defects found by reading the docs against the
code, and a second set found by GitHub Actions on platforms this laptop is not.

### Added

- `docs/`: the documentation set the README points at - `docs/INDEX.md` as the map,
  requirements (PRD, FR/NFR, user stories, acceptance criteria), eight architecture pages,
  one page per official module, the threat model and the permissions model, five technology
  pages and six ADRs. Every claim in them is checked against the source, and each page ends
  with the gaps it does not paper over.
- `docs/roadmap/CURRENT_STATUS.md`, the cold-start handoff: what is built, what is tested,
  on which platform, and what to do first.
- `plugin-examples/hello/`: a real, installable example plugin with its own
  `pyproject.toml`, a `levix.plugins` entry point and one command, loaded through the same
  registry the official modules use (`tests/test_plugin_example.py`).
- `tests/modules/test_systempulse.py`: 40 test functions (46 collected cases) against a fake
  `psutil`, covering the sampling wrappers, the unsupported rows, the `--watch` deltas, the
  limit semantics, the markup-sensitive cells and the CLI exit codes. This module previously
  had no test file.
- `tests/test_logging.py`: 6 test functions (11 collected cases) for the one security promise
  that lived only in a docstring. Six credential shapes through `RedactFilter.redact`, one
  through a real `LogRecord`, one that lets `setup()` open a real rotating `levix.log` and
  then reads the bytes back, one that adds a handler carrying **no** filter to prove the
  logger-level filter is what does the work, one that `filter()` returns `True` (a redaction
  that dropped the record would hide the command, not protect it), and one that the only
  console handler writes to stderr at `WARNING`. It closes gap 6 of
  `docs/roadmap/CURRENT_STATUS.md`; what it does not claim is coverage of a credential in a
  shape the four patterns do not name.
- `levix ai key set` / `levix ai key clear`: the write path for the provider credential,
  through `LevixContext.store_secret()` / `forget_secret()` to `secrets.set_secret()` /
  `delete_secret()`. The key is prompted with echoing off, so it never enters argv, the
  process list or a crash report; `LEVIX_DISABLE_FILE_SECRETS=1` refuses the plaintext tier.
- `Permission.SECRET_WRITE`, so a module that can replace a credential discloses something
  different from one that can only read it. Disclosure, as always, not enforcement.
- `.github/workflows/ci.yml`: the matrix the documentation kept promising - `ubuntu-latest`,
  `macos-latest` and `windows-latest` × Python 3.12 and 3.13, each running
  `ruff check`, `ruff format --check`, `mypy` and `pytest -m "not integration"` after
  installing `.[all,dev]` - plus a `core-stays-light` job that builds the wheel, installs it
  into an empty venv with **no** extras, and asserts that no heavy package was pulled, that
  `monitor overview` / `music devices` / `tube info` / `ai check` each refuse with exit 3,
  that the stdlib-only surface still answers (`--version`, `hacker info`, `files search`,
  `game scores`, and `plugins list` marking what is missing) with `doctor --json` accepted at
  exit 0 **or** 3 - a bare install *should* report its missing extras - and that the archive
  carries `levix/py.typed` and exactly one `levix/data/defaults.toml`.
- `.github/workflows/release.yml`, triggered only by a `v*` tag: the tag must equal
  `[project].version`, the checks run again, `python -m build` plus `twine check` produce the
  artefacts, a GitHub Release attaches them with `SHA256SUMS.txt`, and `pypa/gh-action-pypi-publish`
  uploads to PyPI through **trusted publishing** (an OIDC token scoped to this repo, this
  workflow file and the `pypi` environment - no API token lives in the repository or on a
  laptop). The PyPI project and its trusted publisher still have to be created by a human;
  see `docs/technology/PYTHON_PACKAGING.md` §Publishing.
- `src/levix/py.typed`: `pyproject.toml` has claimed the `Typing :: Typed` classifier since
  0.4.0, but PEP 561 means an editor only gets inline types from `levix.sdk` if the marker
  ships, so plugin authors were being promised typing the distribution did not provide.

### Changed

- `pyproject.toml`: the redundant `[tool.hatch.build.targets.wheel.force-include]` entry is
  gone. It made hatchling add `levix/data/defaults.toml` to the archive twice, so
  `python -m build` aborted at the wheel step and `pip install .` failed while preparing
  metadata.
- `[music]` now declares `numpy>=2.0,<3`, which `music/core.py` imports directly rather
  than getting by luck from soundfile.
- `levix ai`'s refusal when no key is found puts the sentence in the error and the remedy in
  the hint (`LEVIX_AI_API_KEY`, `levix ai key set`, the keyring service and user name), so
  the two parts stay separately readable instead of one run-on line.
- `README.md` no longer opens with a command that cannot work. The install section puts the
  verified source install first (`pip install "levix[all] @ git+https://…"`), states that the
  PyPI name is unclaimed today, and keeps `pipx install levix` under a heading that says it
  describes the release the workflows produce. The tagline and the Status section now carry
  the same boundary: Windows 11 is where the numbers came from.
- `CONTRIBUTING.md`'s check commands are CI's commands: `ruff check src tests
  plugin-examples`, `ruff format --check src tests plugin-examples` and a bare `mypy`, whose
  configured `files` already cover the example plugin. `mypy src/levix` checked 59 of the 61
  files the project actually types.
- Where the documentation was wrong rather than the code, the text was cut back to the size
  of the evidence: three pages still described the masked secret as `[set, hidden]` after the
  brackets had come out of `_MASK`; the file-store-disabled refusal was quoted as exiting 7
  when `EXIT_MISSING_DEPENDENCY` is 3; and `tests/modules/test_systempulse.py` was said to
  hold 45 tests where the collector reports 40 functions and 46 cases. `levix.sdk`'s export
  count moved with the code, from 15 names to 14. Every count in `docs/` now comes from
  `pytest --collect-only` and every claim names the file or test that shows it.
- Two `music` device cases moved to `@pytest.mark.integration`:
  `test_list_devices_reports_roles_and_defaults` and `test_devices_command_prints_a_table` ask
  the machine which sound hardware it has, and CI's runners answer with either no PortAudio at
  all (Ubuntu: `OSError: PortAudio library not found`) or PortAudio and no devices (Windows: an
  empty listing). That is a fact about a headless runner, not a defect to be reported as one,
  so the matrix no longer asks - `integration` is 10 cases where it was 8, and each of them now
  skips out loud rather than failing.
- `tests/test_router.py` reads help-page *text* with the escape codes stripped. Typer forces a
  terminal whenever `GITHUB_ACTIONS` is set (`typer/rich_utils.py:77-82`), so a runner rendered
  `Usage:` in bold and the style split the literal two cases were matching on. Colour is not
  what forwarding is about; the text is, and markup escaping has its own test file.
- `tests/modules/test_ai.py::test_explain_sends_only_the_capped_prefix` pins `COLUMNS=200`, the
  same way the other width-sensitive cases in this suite do. At the 80 columns Rich assumes for
  a captured stdout, CI's Ubuntu runner wrapped the cap notice after "showing" and the
  assertion was reading half a sentence.

### Fixed

- A command alias reached the module's group instead of the command it names, so a
  documented alias such as `levix nt hello` exited 4 with `unknown command: hello`.
  `router._forward` now prefixes the aliased subcommand (`tests/test_router.py`).
- `levix config reset --yes` deleted the user's configuration file without asking, because
  it never went through the approval gate. It now calls
  `approve.require_approval(..., destructive=True)`, and `--yes` cannot authorise it - the
  same rule `files delete` already enforced.
- Text a module did not author was interpolated into Rich markup unescaped across the
  `hacker`, `music`, `files`, `ai` and `systempulse` renderers, the dashboard and
  `levix plugins`. A `[bold]` in a file name or a model name silently restyled the console;
  an unbalanced `[/...]` raised `MarkupError` and killed the command that printed it; a
  `[k10temp]` chip label disappeared from the temperature row. Each module now renders
  through its own escape helper over `terminal.markup_safe` / `encode_safe`.
- The `levix ai models` table printed the model names a remote server chose without
  escaping them.
- Intentional line breaks in error messages were flattened to literal `\x0a`, because
  `main._plain()` ran the whole message through the one-line `encode_safe`. It now escapes
  per line, so the two-line dependency refusal reaches the terminal as two lines.
- `src/levix/commands/update_cmd.py` cited `docs/security/SECURITY_OVERVIEW.md`, a file that
  does not exist; the disclosure lives in `docs/security/THREAT_MODEL.md`.
- `levix monitor network` was the one OS-sourced cell that reached Rich unescaped: a Linux
  interface alias or a Windows adapter description containing `[...]` silently restyled or
  killed the table. The row builder is now `cli._network_table`, every cell goes through
  `terminal.markup_safe`, and
  `tests/modules/test_systempulse.py::test_an_interface_name_with_brackets_is_still_shown`
  pins an interface called `veth[0abc]`.
- `levix files search --grep PATTERN --max-bytes 0` capped every file at the packaged 2 MiB
  default instead of meaning "no cap", so a file above the default was silently reported as
  skipped. `0` now means no cap and a negative value falls back to the default
  (`modules/files/cli.py:188`,
  `tests/modules/test_files.py::test_max_bytes_zero_means_no_cap`).
- `levix config set --yes` was accepted, documented in one place and read by nothing. The
  flag is removed rather than wired up: `config set` never prompts, so the option promised a
  behaviour that did not exist.
- `doctor --only modules` and `--only capabilities` printed the whole report - `prefix` was
  computed and never applied (`commands/doctor_cmd.py:43-54`). The filter applies, a filtered
  `--json` verdict is computed from the rows actually shown, and `tests/test_doctor.py` (6
  functions) pins each slice.
- Two comments described commands that do not exist: `dashboard/app.py::refresh_modules`
  promised that `levix plugins install` in another shell would become visible, and
  `modules/ai/core.py:42` referred to a `levix secrets` command. Both now name what actually
  happens (the registry is re-read; the env var and `levix ai key set` are the routes).
- `module.LevixModuleProtocol` is deleted. It declared `manifest()` and `build_command()`
  raising `NotImplementedError`, was re-exported through `levix.sdk`, described itself as the
  shape `levix create-module` scaffolds while the scaffold emits a `MANIFEST` object and a
  `build_app()` function, and was implemented by nothing. The loader reads only `cli_path`, so
  the class was public API that did nothing; `levix.sdk` now re-exports 14 names.
- `files.core.is_hidden` read `os.lstat(path).st_file_attributes`, an attribute that only
  exists on Windows, so `mypy` on the Linux and macOS runners failed the new `Types` step
  with `"stat_result" has no attribute "st_file_attributes"` while the same command was green
  on this laptop. The behaviour was already correct - `HIDDEN_ATTR` is `0` off Windows, so the
  line never runs there - and it now reads through
  `getattr(os.lstat(path), "st_file_attributes", 0)`, the pattern `core.py:239` already uses
  for `st_birthtime`. `python -m mypy --platform win32|linux|darwin` is clean, which is how
  one machine checks what four runners reported.
- `levix files delete` refused to remove a symbolic link that lived inside the wall when its
  target lived outside it. The plan validated each target with `core.resolve()`, which
  resolves *through* a link - the rule every other command needs, because reading, copying and
  moving really do follow one. Removing a link writes nothing outside the wall and frees no
  bytes from the target, so the refusal blocked exactly the safe case, and CI run #3 met it on
  Ubuntu and on macOS. `plan_delete` now asks for `core.resolve(..., keep_link=True)`, used by
  no other caller, and the decision is pinned by
  `tests/modules/test_files.py::test_a_link_deleted_as_a_link_is_judged_at_its_own_place`,
  which fakes "is a link" and "resolves outside" because the account running a suite may not be
  allowed to create either.
- `files preview` printed a Windows link's target as `\\?\C:\Users\...`. `os.readlink()`
  hands back the DOS-device form the reparse record holds, so the table showed a path the user
  cannot type back; `core.strip_device_prefix` now drops it, and turns `\\?\UNC\server\share`
  into `\\server\share`. CI's Windows runner found this one - that account can create symlinks,
  this laptop's cannot.
- `levix hacker info` split the machine's own hostname in the middle. A table cell is only as
  wide as its column, the host table's value column is 65 characters inside the 80 a captured
  stdout implies, and the macOS runner's mDNS name is 68, so `overflow="fold"` broke the token
  across two lines and the user read `iad20-...-C64BF1B94850.` newline `local`. The name is now
  printed as a full-width line under that table, which wraps between words
  (`tests/modules/test_hacker.py::test_a_hostname_longer_than_the_table_stays_in_one_piece`).
- `.github/workflows/ci.yml`'s `Test suite` step reported its own success over a failing suite,
  because `pytest | tee pytest.log` under Actions' default `bash -e` - no `pipefail` - hands
  the step `tee`'s exit code. It redirects into the log, echoes it, and exits with pytest's
  code; run #2's five green checks were the bug, not the tree.

### Verification

- `python -m ruff check src tests plugin-examples` and `python -m ruff format --check src tests
  plugin-examples` exit 0 (81 files already formatted); bare `python -m mypy` exits 0 with no
  issues in 61 source files - `src/levix` plus the example plugin, which is what
  `[tool.mypy].files` declares and what CI now runs - and `--platform win32`, `--platform linux`
  and `--platform darwin` each report the same 61 clean.
- The suite, on this machine: `.venv/Scripts/python.exe -m pytest -o addopts="" -q` runs
  **589 test functions in 18 files, collecting 716 parametrised cases** and reports
  **711 passed, 5 skipped, 2 warnings in 97.06 s**, exit 0. The same tree without the ten
  `integration` cases - which is what every CI column runs - is
  **701 passed, 5 skipped, 10 deselected in 103.69 s**, and those ten alone are
  **10 passed, 706 deselected in 10.36 s**. The five skips are the symlink
  cases in `tests/modules/test_files.py` (this account cannot create symlinks; three more
  state that POSIX symlinks need no privilege there). The two warnings are a NumPy 2.5
  deprecation inside `sounddevice`, raised by the one real-device playback test. All three
  were run with one pytest process at a time; see `docs/roadmap/CURRENT_STATUS.md`
  §One observed flake for why that is said out loud.
- Two runs failed while several pytest processes shared this 8 GB machine, and both command
  lines ended in `| tail`, so neither traceback survived. One names itself:
  `tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles`
  in a `-m integration` run overlapping a full-suite run. The other is a full-suite run
  overlapping two integration runs in which one test failed and its name was lost - it is not
  established to be the arcade case. Seventeen later attempts, all with `-rf --tb=line`, came
  back green: three concurrent full-suite runs, six concurrent `-m integration` runs, two more
  integration runs alongside a full suite, five repeats of the six arcade-screen cases while a
  full suite ran beside them, and one standalone full suite - some carrying more concurrency
  than either failure had. Nothing was changed, because no traceback means no named assertion
  to aim at. What the code does say: that case is `@pytest.mark.integration`
  (`tests/modules/test_arcade.py:559`), so no CI column runs it and the green matrix neither
  catches nor excuses it, and it advances a real `set_interval` timer
  (`src/levix/modules/arcade/screens.py:117`) with a bounded number of `pilot.pause(0.01)`
  calls - a wall-clock budget the scheduler decides, which is the machine-dependence
  `CONTRIBUTING.md` already tells authors to avoid. `_tick` is synchronous end to end and
  `snake.py:228` derives `GAME OVER` from `state.alive`, so the two races first suspected are
  not it.
- Every `file:line` citation and every `::test_...` name in `docs/` was re-checked against
  this tree with a throwaway script - 205 cited test names among the 580 it held at that
  point, 312 line ranges, none missing or out of bounds. The script was not committed;
  `docs/roadmap/CURRENT_STATUS.md` is the page that states which of the claims are
  machine-verified and which are not. The tests added since then are named in the pages that
  cite them and were checked against `pytest --collect-only`.
- `levix doctor --json` on this machine answers exit 0 with verdict `degraded`:
  `ffmpeg`, `media_player` (`ffplay`), `audio_output`, `psutil`, `battery`, `keyring` and
  `platform` are `ok`, while `temperature` is `degraded` (this `psutil` has no
  `sensors_temperatures`), `gpu` is `unsupported` and `terminal` is `degraded` (stdout was
  captured, not a TTY). `--only modules` and `--only capabilities` show only their rows.
- `python -m build` produces both an sdist and a wheel, and the wheel was installed into an
  empty virtualenv: all seven modules answer `-h` with exit 0, the four heavy modules refuse
  with exit 3 and name the right extra, `levix plugins list` marks them `needs psutil` /
  `needs yt-dlp` / `needs soundfile, sounddevice`, and no heavy package was pulled. That is
  the core/extras split proven from an installed distribution rather than an editable one.
- The wheel's contents were measured, not assumed: 66 entries, `levix/py.typed` present,
  `levix/data/defaults.toml` present exactly once, 26 files under `levix/modules/` and
  `levix-0.4.0.dist-info/entry_points.txt` there for `importlib.metadata` to read - which is
  the same three assertions `ci.yml` now makes about every build.
- Every shell command in `ci.yml`'s `core-stays-light` job was replayed by hand against
  `dist/levix-0.4.0-py3-none-any.whl` installed into an empty venv, under
  `bash -eo pipefail` like the runner's default shell: no heavy package in `pip freeze`,
  the four module commands each exiting 3, `--version` / `hacker info` / `files search` /
  `game scores` each exiting 0, `doctor --json` exiting 3 with verdict `missing` and 21
  findings, and four `needs` rows in `plugins list`. The job then ran that exact list on an
  Ubuntu runner and passed.
- Installing from the repository was proven in a throwaway venv against the pushed `main`:
  `python -m pip install "levix @ git+https://github.com/shivamsinghtomar78/LEVIX.git"`
  installs `levix 0.4.0` with the six direct dependencies and their transitive ones and
  **no** psutil / yt-dlp / soundfile / sounddevice / numpy / httpx / keyring,
  `levix --version` answers, `levix plugins list` marks `needs yt-dlp` /
  `needs soundfile, sounddevice`, and `levix monitor cpu` exits 3.
- `levix update` on this machine answers `could not check for updates: PyPI returned 404` and
  exits 8 (`EXIT_PROVIDER`): the name is unclaimed, and the command refuses to imply the user
  is up to date when it could not ask.
- **CI ran four times on 2026-11-05**, each time on the commit that changed it. Run #1
  (`fcbcb22`): `Bare core install (no extras)` passed on `ubuntu-latest` in 31 s, so the
  no-extras install, the four exit-3 refusals and the wheel-content assertions are proven on
  a second platform; all four POSIX matrix columns stopped at `Types` on the Windows-only
  stat attribute, and both Windows columns passed Lint, Format and Types and failed inside
  the suite. Run #2 (`726909c`) reported "5 successful and 2 failing" and both halves were
  false: the suite step piped pytest through `tee`, Actions' default shell is `bash -e`
  **without** `pipefail`, so Linux and macOS reported `tee`'s exit 0 over a failing suite,
  while the Windows jobs died in pwsh on bash-only syntax before pytest started. The step now
  declares `defaults.run.shell: bash`, redirects into `pytest.log` and echoes it, and turns
  every `FAILED` line into a `::error::` annotation so a red column names itself without a
  signed-in account. Run #3 (`5fdc644`) is the first result that means something: **all six
  columns red, eight test functions between them**, every one of them dependent on the
  machine it ran on. All eight are addressed in that commit; the wheel job passed on Ubuntu in
  every run. **Run #4 (`5b047ad`, run id `42068621524`) is green: all seven jobs `success`,
  and on each of the six matrix jobs the four steps `Lint`, `Format`, `Types` and
  `Test suite` report `success` individually** - `windows-latest`, `ubuntu-latest` and
  `macos-latest` at Python 3.12 and 3.13 - with no failure annotation left behind (the only
  annotations are GitHub's own Node.js-20 deprecation warning and runner notices). That
  confirms all eight fixes on the platforms that found them, including the two POSIX symlink
  cases this laptop can only fake. `docs/roadmap/CURRENT_STATUS.md` §Defects found by CI
  records each one with the column that closed it.
- What run #4 does **not** prove: each column runs `pytest -m "not integration"`, so the ten
  device and OS-tool cases still have only ever executed on Windows 11 here; no command has
  been run by hand on Linux or macOS; and a green column says a branch was reached without
  failing, not that the behaviour was asserted. The POSIX items in
  `docs/roadmap/CURRENT_STATUS.md` §What is not verified - the *effect* of the secrets-file
  `chmod`, real `ip addr show` / `ifconfig` output, a real POSIX keyring, the platformdirs
  layout under a real `$XDG_*` - have no test at all, on any platform. `release.yml` has
  never run, because the PyPI project and its trusted publisher do not exist yet.

## 0.4.0 - initial official modules

### Added

- Core engine: lazy forwarding router (`levix.router`), `levix.plugins` entry-point
  discovery with origin stamping, layered TOML configuration, shared SQLite storage
  with namespaced migrations, dependency gate, capability probes, redacted rotating
  logs, and a single documented exit-code table.
- Interactive Textual dashboard: manifest-driven module list, keyboard bindings,
  theme selection, recent command history, and module launching through
  `App.suspend()` plus a subprocess so one terminal is never owned by two apps.
- Modules: SystemPulse (`levix monitor`), Hacker (`levix hacker`), Files
  (`levix files`), Tube (`levix tube`), Arcade (`levix game`), Music (`levix music`),
  AI (`levix ai`).
- Platform commands: `dashboard`, `config` (show/list/get/set/unset/reset/path/edit),
  `doctor`, `plugins` (list/info), `update` (check-only), `create-module`.
- Plugin SDK façade (`levix.sdk`) and a generated scaffold that loads through the same
  registry the official modules use.
- Documentation set: requirements, architecture, technology, module specs, plugin
  guide, security model, roadmap and task index.

### Known gaps

- `levix install/uninstall/dev/test/package/publish` are not implemented; installing
  third-party code needs the consent and environment model settled in
  `docs/architecture/PLUGIN_ARCHITECTURE.md` first.
- No CI matrices, no PyPI upload and no standalone binaries yet.
- Verified on Windows only. Linux and macOS behaviour is designed for, not proven.

## 0.1.0 - 0.3.0

Not released. The project was built from an empty repository through phases 0-3 in a
single pass, and the first published version will be the one that ships the modules.

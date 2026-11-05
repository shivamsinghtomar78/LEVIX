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
- `tests/test_secrets.py`: 4 test functions that stat the key store instead of reading the code
  that protects it. On POSIX the file must be mode `0600` after a real `set_secret`, must stay
  owner-only when a faked `Path.chmod` refuses the call (the case asserts the chmod was
  attempted, so a Python that moved the method cannot silently turn it into a no-op), and must
  come back to `0600` when an existing `0644` store is overwritten. On Windows it runs the real
  `icacls` and requires one explicit grant, to this user, with nothing inherited - because
  `st_mode` there reports `0o666` for every ordinary file and proves nothing. The three POSIX
  cases `skip` on Windows; CI run #6 (`3d460df`) carried them onto Ubuntu 3.12/3.13 and macOS
  3.12/3.13, where they ran and the columns stayed green.
- `tests/test_update.py`: 10 test functions for `levix update`, against a `urllib.request.urlopen`
  the case replaces - no socket is opened. It pins that a newer release is named and the upgrade
  is left to the user, that the comparison is `>=` rather than `>` (so an equal version is
  "up to date"), what `--json` carries, that an HTTP 503 and a `URLError` are both reported as
  failures with `EXIT_PROVIDER` instead of being dressed up as "up to date", that a payload with
  no version is a provider failure rather than a crash, what the request itself looks like
  (`https://pypi.org/pypi/levix/json`, a `levix/<version>` user agent, `Accept: application/json`,
  the timeout the option was given), and that an absurd `--timeout` is refused before any request
  is made.
- `tests/test_create_module.py`: 9 test functions (13 collected cases) that run the generator for
  real. `levix create-module weather` writes into a temporary directory; the test then registers
  the result the way `pip install -e .` would (a hand-built `levix_weather-0.1.0.dist-info`, the
  scaffold's `src/` on `sys.path`, the process-wide registry reset) and drives it through the real
  router: `plugins info`, the module command itself, the lazy-import rule, the name rules, the
  refusal to overwrite, and `--force` with a captured stdin - which must exit 6 and delete
  nothing. The last case runs `pytest` **inside the generated project** in a child interpreter, so
  a scaffold whose own tests fail cannot pass here. Writing this file found four defects in the
  scaffold; see §Fixed.
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
- `levix music play` takes a **link** as well as a file. `play URL` with an `http(s)` scheme
  asks yt-dlp for the best audio-only stream and converts it with ffmpeg - inside yt-dlp's own
  `FFmpegExtractAudio` postprocessor, so LEVIX still builds no command line - and hands the
  result to the same libsndfile decode a file uses. It is a fetch with rules, not an
  open end: the scheme is judged before either tool is looked for (any other scheme, `file:`
  included, is exit 2), `noplaylist` is always set, the cache path comes from `sha256(url)`
  rather than from anything the server said (`<cache_dir>/streams/<16 hex>/audio.mp3`) and a
  path yt-dlp reports from outside that folder is refused unopened at exit 7, `max_filesize`
  and a second check on the bytes that landed enforce `STREAM_MAX_BYTES` (134,217,728) at exit
  7, a cached link replays with no network and no yt-dlp, and a failing fetch is the one
  message this module prints - yt-dlp's own `logger` gets a silent sink - at exit 8. Missing
  `yt_dlp` or `ffmpeg` is exit 3 naming where each comes from (`pip install "levix[tube]"`,
  and this platform's ffmpeg command, a table Music duplicates from Tube and a test keeps
  them agreeing). `levix music play` on a path performs no fetch and touches neither.
- `levix music play --visual bar`: Winamp-style spectrum bars while the audio plays. The
  meter reads the samples at the PortAudio playhead through the `on_block` report the progress
  line already used, so no second seam into the device appears; the band maths, the peak-hold
  caps and the redraw gate live as pure functions in `src/levix/modules/music/visual.py`
  (0 dBFS ceiling at -54 dBFS floor, 40 Hz-15 kHz log-spaced, at most 24 columns, a band
  sharing its neighbour's bin when it is narrower than one FFT bin), and the drawing is a
  `Live(auto_refresh=False)` region the module clocks itself. `music.visual` is the new config
  key (`bar`/`off`, `choices` asserted against the renderer's own modes); the default quiets
  down to the one-line progress bar when stdout is redirected, and an explicit
  `--visual bar` on a pipe is refused at exit 2 rather than ignored.
- One test now writes **every** container the library scan offers - WAV/PCM_16, FLAC,
  OGG/VORBIS, OGG/OPUS at 48 kHz, MP3/MPEG_LAYER_III, AIFF under both `.aiff` and `.aif`, and
  AU - and another asserts that table equals `core.SCAN_SUFFIXES`, so adding a suffix to the
  scan without proving it decodes fails the suite. This is what replaced the old
  "not covered: `.opus`, `.aiff`, `.aif`, `.au`" line in `docs/modules/MUSIC.md`.

### Changed

- `pyproject.toml`: the redundant `[tool.hatch.build.targets.wheel.force-include]` entry is
  gone. It made hatchling add `levix/data/defaults.toml` to the archive twice, so
  `python -m build` aborted at the wheel step and `pip install .` failed while preparing
  metadata.
- `[music]` now declares `numpy>=2.0,<3`, which `music/core.py` imports directly rather
  than getting by luck from soundfile.
- The `music` manifest now declares `fs_write` and `network` beside `audio` and `fs_read`, and
  its summary is "Play, inspect and queue audio natively, from a file or one fetched link."
  Both new permissions belong to one command - `play URL` - and the disclosure is a disclosure,
  not a wall; `info`, `devices`, `library` and `playlist` touch neither. The `audio_output`
  capability detail and the module docstring say the same thing with the exception named ("a
  file on disk needs no ffmpeg"), and the decoder-refusal hint now reads "a file on this disk
  is never converted - only a fetched URL goes through ffmpeg" instead of promising that LEVIX
  never calls ffmpeg, which stopped being true for a link.
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
- `UiSpec` has two modes, not three. `mode="screen"`, its `screen_path` partner and
  `registry.build_screen` are deleted: nothing called them, no official module declared them,
  and they could not have worked - the dashboard is itself a Textual app, one TTY hosts one
  Textual app, and a module that wants the screen whole has to take the terminal *from* the
  dashboard, which is exactly what `suspend` already does. `mode` is now
  `Literal["suspend", "hidden"]` (`src/levix/module.py:67-81`) and its docstring states the
  reason instead of advertising a third option. Removing a field from a dataclass that
  `levix.sdk` re-exports is only safe because nothing has been published yet; after the first
  release this is a breaking change and has to be handled as one.

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
- `secrets._write_file` wrote `secrets.json` with `Path.write_text`, which creates at the
  default mode (`0666` minus umask, so world-readable on a typical Linux umask), and only then
  called `_harden`. `_harden`'s `chmod` is wrapped in `suppress(OSError)` on purpose - a key
  already on disk must not crash the command that stored it - which meant the one call standing
  between a readable file and an owner-only one was the call allowed to fail silently. Writing
  the permission test is what found it: the case that refuses the `chmod` would have caught a
  `0644` store on the first Linux column. `_write_file` now opens with `O_CREAT` at
  `stat.S_IRUSR | stat.S_IWUSR` (`src/levix/secrets.py:128-139`), so the mode is right at
  creation and the later `chmod` is a correction for the overwrite case rather than the only
  thing protecting the key; `0600` asks for no group or other bit, so umask has nothing left to
  remove.
- `tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles`
  asserted something the scheduler decided. After the round ended it pressed `r`, paused once,
  and required `app.state.alive` - but `restart_game` re-arms a real `set_interval` timer
  (`src/levix/modules/arcade/screens.py:106-117`) at the `interval=0.02` the case pins, and
  `snake_rules.new_game` starts the head at `width // 2` heading right
  (`src/levix/modules/arcade/snake.py:88-90`), so on that 12-column board the new snake dies on
  its sixth tick, about 120 ms later. Whether `alive` was still true measured how long the message
  pump took, which is why it failed twice under contention and once in a quiet run. The case now
  pins the *new* round's tick at 60 s through `app.forced_interval` - the lever the app documents
  for tests - and asserts what the `r` binding is actually responsible for: `(direction, ticks,
  score)` back at `("right", 0, 0)`, head at the centre, body at `START_LENGTH`, no `GAME OVER`
  on the board, and still exactly one stored row. The three polls above it keep their budgets
  because they wait for the snake to die, where elapsed time costs iterations rather than the
  verdict. Fifteen consecutive quiet repeats pass; `pytest -m integration` is green at 10.
- `ruff format --check .` was red on two ADRs, because ruff 0.17 formats fenced Python inside
  Markdown and `docs/decisions/ADR-0002…` and `ADR-0003…` each held a snippet written by hand. CI
  only checks `src tests plugin-examples`, so the column never saw it; both snippets are now
  re-wrapped in place, prose untouched, which makes the wider check clean.
- `levix create-module` emitted a project whose manifest was not its manifest. The template
  wrote `permissions=frozenset({"Permission.FS_READ"})` - a **string** that looks like the enum
  member - while `docs/architecture/PLUGIN_ARCHITECTURE.md` documented
  `frozenset({Permission.FS_READ})`. Discovery accepted it, the router accepted it, and then
  `levix plugins info <name>` asked the string for `.value` (`commands/plugins_cmd.py:88-89`, and
  the dashboard reads `p.value` the same way at `dashboard/app.py:284-285`) and died in the
  disclosure report - the one command whose whole job is to tell a user what a plugin claims.
- The same template's command body interpolated `{display}`, a name that exists only inside the
  generator's own f-string scope, so the generated `cli.py` raised
  `NameError: name 'display' is not defined` on the module's first run. It now prints
  `MANIFEST.title` with `markup=False`, which also stops a word typed at the prompt from being
  read as a Rich style tag.
- The scaffold's `README.md` told the author to run `levix <name> hello`. Typer mounts a
  one-command app as the command itself, so click refused `hello` as an extra argument (exit 2)
  while `levix <name> -h` still advertised it; the README now shows `levix <name>` and
  `levix <name> you`, and `tests/test_create_module.py` asserts the string `hello` is absent from
  it and that both real forms run.
- The scaffold's own `tests/test_manifest.py` asserted `build_app()._name`, and Typer 0.27's
  `Typer` has no `_name`, so a brand-new plugin was red on `pytest` before its author had written
  a line. It asserts `build_app().info.name` now, and the generator's test case runs that
  generated suite in a child interpreter so this class of drift cannot come back.
- `mode="hidden"` was documented and did nothing. `module_list.build_rows` returned every
  manifest it was handed, so a plugin that asked to stay out of the dashboard got a ready,
  launchable row anyway - and `plugin-examples/hello` had been declaring exactly that
  declaration as decoration. Calling the row builder with a hidden manifest proved the
  docstring false before any code changed. Membership now has one filter, in the one function
  that builds rows (`dashboard/module_list.py:94-106`), pinned by four cases:
  `tests/test_dashboard.py::test_a_module_hidden_from_the_dashboard_gets_no_row`,
  `::test_a_hidden_module_reaches_no_widget_the_app_builds` (the `ListView`'s children and
  `app.rows` must agree), `::test_no_official_module_hides_itself_from_the_dashboard` (the new
  filter must not quietly empty the real dashboard), and
  `tests/test_plugin_example.py::test_the_hidden_example_is_discovered_but_gets_no_dashboard_row`,
  which installs the example the way `pip` would and asserts both halves - no row, and
  `plugins info` still reporting `dashboard : hidden`. Three cases in
  `tests/test_markup_safety.py` had used `mode="hidden"` as inert filler; with the flag now
  doing something they would have filtered out their own rows, so they declare a plain
  `UiSpec()`.
- `levix plugins info` printed `dashboard : not offered` for a manifest that declares no
  `UiSpec` at all - the opposite of what the dashboard does with that manifest, which lists it
  and runs `<name> -h`. The disclosure line now names the effective mode,
  `suspend (no UiSpec declared)` (`commands/plugins_cmd.py:82-86`), and
  `tests/test_dashboard.py::test_a_manifest_with_no_uispec_is_disclosed_as_offered_by_default`
  pins the new string and the absence of the old one.
- A module hidden from the dashboard is still a command. The deleted `build_screen` test made
  way for
  `tests/test_registry.py::test_a_module_hidden_from_the_dashboard_is_still_discovered_and_routable`,
  which discovers a `hidden` manifest through the real loader and then asks the registry for it
  by name - `hidden` is a display rule, and a display rule must not be able to take a
  subcommand away.

### Verification

- `python -m ruff check src tests plugin-examples` and `python -m ruff format --check src tests
  plugin-examples` exit 0 (85 files already formatted - the 85th is the new
  `src/levix/modules/music/visual.py` - and the wider `.` scope is clean at 126);
  bare `python -m mypy` exits 0 with no
  issues in 62 source files - `src/levix` plus the example plugin, which is what
  `[tool.mypy].files` declares and what CI now runs - and `--platform win32`, `--platform linux`
  and `--platform darwin` each report the same 62 clean, re-run against this tree because
  `create_module_cmd._template`, `secrets._write_file`, `module.UiSpec`, `registry`,
  `dashboard/module_list` and now `music/core.py` and `music/cli.py` are all in it.
- The suite, on this machine: `.venv/Scripts/python.exe -m pytest -o addopts="" -q` runs
  **664 test functions in 21 files, collecting 829 parametrised cases** and reports
  **821 passed, 8 skipped, 2 warnings in 123.32 s**, exit 0. The same tree without the ten
  `integration` cases - which is what every CI column runs - is
  **811 passed, 8 skipped, 10 deselected in 100.90 s**, and those ten alone are
  **10 passed, 819 deselected, 2 warnings in 10.85 s**. Eight skips, and each names its reason:
  five symlink cases in `tests/modules/test_files.py` (this account cannot create symlinks; three
  more state that POSIX symlinks need no privilege there) and the three POSIX-only permission
  cases in `tests/test_secrets.py`, which CI run #6 executed on the Ubuntu and macOS columns
  instead of skipping. The two
  warnings are a NumPy 2.5 deprecation inside `sounddevice`, raised by the one real-device
  playback test. All three were run with one pytest process at a time; see
  `docs/roadmap/CURRENT_STATUS.md` §The flake, explained and closed for why that is said out loud.
- The flake that sentence refers to is now closed, and the contention story told here earlier was
  wrong in the way that matters. Two runs had failed with `| tail` on the command line, so no
  traceback survived; seventeen deliberate reproductions came back green, and those green runs
  were read as evidence that only concurrency could do it. The case then failed in a sequential
  `-m integration` run with the pipe removed, and the traceback named the cause: the assertion
  after `r` measured elapsed real time, and on a 12-column board at `interval=0.02` the restarted
  snake reaches the wall on its sixth tick - the reported `ticks=6` is the predicted number, not a
  coincidence. So concurrency could raise the odds but was never the mechanism, and the fix is in
  `test_arcade.py`, not in the scheduler: the case pins the new round's tick at 60 s and asserts
  the state `restart_game` writes. Fifteen consecutive quiet repeats of that single case pass, and
  `-m integration` is green at 10 passed. The honest residue: the arcade screen cases are
  `@pytest.mark.integration`, so no CI column runs any of them - the matrix neither caught this
  nor will catch its return.
- Every `file:line` citation and every `::test_...` name in `docs/` was re-checked against
  this tree with a throwaway script - 205 cited test names among the 580 it held at that
  point, 312 line ranges, none missing or out of bounds. The script was not committed;
  `docs/roadmap/CURRENT_STATUS.md` is the page that states which of the claims are
  machine-verified and which are not. The tests added since then are named in the pages that
  cite them and were checked against `pytest --collect-only`.
- The same sweep run again for this tree found that six `test_*` names written into the music
  pages during the spec phase had never existed as code - they described the cases the task
  intended, and the shipped cases earned different names. Every one now quotes a function
  `pytest --collect-only` actually lists, and the pass that fixed them caught one mistyped
  replacement too (`test_a_file_url_is_refused_before_anything_is_looked_for`, which is not what
  the file says: the shipped name is
  `tests/modules/test_music.py::test_a_refused_scheme_is_refused_before_anything_is_looked_for`).
  Every `file:line` range in the pages this feature touched was re-measured rather than
  adjusted, because `music/core.py` went from 699 lines to 1094 and every citation below the
  insertion point had moved.
- The one network-shaped thing run for real: `levix music play http://127.0.0.1:1/tone` on this
  machine, with yt-dlp `2026.10.26` importable and ffmpeg on `PATH`. It took about 3.8 seconds,
  printed exactly one message - `error: yt-dlp could not fetch …` carrying the tool's own
  `ERROR: [generic] … Unable to download webpage: [WinError 10061]` inside it, not beside it -
  and exited **8**. That is the loopback interface with nothing listening, so it pins the failure
  mapping and the one-report rule and says nothing about any site; no third-party download was
  performed for the record (`docs/modules/MUSIC.md` gap 8).
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
- **CI ran eight times on 2026-11-05**, each time on the commit that changed it. Run #1
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
  records each one with the column that closed it. **Run #5 (`75daed2`, run id `42074244730`)
  is green the same way** - all seven jobs `success`, the four steps individually `success` on
  all six columns, annotations again only GitHub's Node.js-20 warning and runner notices - and
  it is the run that matters more, because it is the first to carry `tests/test_logging.py`.
  `::test_a_key_never_reaches_the_log_file` calls `setup()` for real, lets `RotatingFileHandler`
  open `levix.log`, writes three secret-shaped lines and reads the bytes back off disk; it is
  the only case in the CI set that opens a log file, and it passed on Ubuntu and macOS as well
  as Windows. **Run #6 (`3d460df`, run id `42078880293`) is green the same way** - all seven jobs
  `success`, the four steps individually `success` on all six columns. It is the first run that
  carries `tests/test_secrets.py`, so its three POSIX-only cases - the ones that must `skip` on
  this laptop because Windows derives `st_mode` from file attributes - ran on Ubuntu 3.12, Ubuntu
  3.13, macOS 3.12 and macOS 3.13 without skipping, and none of those columns failed. The
  `0600` the code asks `os.open` for is therefore a measured fact about POSIX filesystems rather
  than a claim only this machine could make. Run #6's per-job annotations could not be read: the
  unauthenticated API limit is 60 calls an hour and reading the seven job records spent it, so
  this run is recorded from step conclusions alone.
- **Run #7 (`c49d608`, run id `42083876435`) has conclusion `failure`, and reading it carefully is
  the point.** Six of its seven jobs are `success`: the no-extras wheel job on Ubuntu, and `Lint`,
  `Format`, `Types` and `Test suite` individually `success` on Windows 3.12, Windows 3.13, Ubuntu
  3.12, Ubuntu 3.13 and macOS 3.13. The seventh, `macos-latest / Python 3.12`, is `cancelled` with
  no runner name and no steps at all, annotated on the run page "The job was not acquired by Runner
  of type hosted even after multiple attempts" - and the run took 15 m 3 s against the ~6 m of a
  green one. That is GitHub's macOS capacity, not this tree, and it is written down as a
  non-green run rather than rounded up, because a badge alone would have said the suite failed.
  What the five executed columns do prove is new: run #7 is the first tree carrying
  `tests/test_update.py` and `tests/test_create_module.py`, so those 19 functions and 23 cases ran
  on Ubuntu and macOS for the first time - including the case that generates a plugin, registers
  it as a distribution and runs `pytest` **inside the generated project** in a child interpreter -
  and none of them failed. This run was read with two calls (the run, then `/jobs`) after the
  `rate_limit` reset, replacing the 20-second poll loop that had spent the whole hour's budget
  without ever seeing the result.
- **Run #8 (`b748591`, run id `42089712550`) is green: all seven jobs `success`.** `Lint`,
  `Format`, `Types` and `Test suite` report `success` individually on six columns - Windows 3.12
  and 3.13, Ubuntu 3.12 and 3.13, and macOS 3.12 **and** 3.13, each with a named hosted runner -
  and the no-extras wheel job's six named steps - `Build the distribution` through
  `The stdlib-only modules and the platform commands still work` - are all `success`. The column that run #7 lost to
  runner starvation is the one that came back, so the difference between the two runs is GitHub
  handing out a macOS machine, not anything in the tree; run #8 took 6 m 12 s from creation to
  its last job update against run #7's 15 m 3 s. It is the first tree carrying the hidden-module
  cases and the second carrying `tests/test_secrets.py`, so that file's three POSIX-only cases
  ran on all four POSIX columns instead of skipping. The per-job `annotations` arrays came back
  empty, where runs #4 and #5 had carried GitHub's own `actions/checkout` Node.js-20 deprecation
  warning and some runner notices, and this was again two API calls: the run list, then the job
  list.
- What runs #4 through #8 do **not** prove: each column runs `pytest -m "not integration"` - 710
  of run #6's 720 cases, 733 of run #7's 743, 738 of run #8's 748 - so the ten device and OS-tool
  cases, and the 81 stream-visualiser cases that landed after `b748591`, have only ever executed on
  Windows 11 here; no command has
  been run by hand on Linux or macOS; and a green column says a branch was reached without
  failing, not that the behaviour was asserted. The per-column pass and skip counts have never
  been read, because an unauthenticated caller gets 403 for a run's log archive. The remaining
  POSIX items in `docs/roadmap/CURRENT_STATUS.md` §What is not verified - real `ip addr show` /
  `ifconfig`
  output, a real POSIX keyring, the platformdirs
  layout under a real `$XDG_*` - have no test at all, on any platform. The secrets-file
  permissions are no longer one of them: `tests/test_secrets.py` stats the file, and run #6
  executed the POSIX half of that on four columns. `release.yml` has
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

# Compatibility

## Python

- Declared: `requires-python = ">=3.12"` (`pyproject.toml`), with trove
  classifiers for 3.12 and 3.13 only. mypy pins `python_version = "3.12"` and
  ruff `target-version = "py312"`.
- The code uses 3.12-era features as a floor: `tomllib` (stdlib), `StrEnum`,
  `X | Y` typing syntax throughout, slots dataclasses with `frozen=True`.
- Any Python older than 3.12 is not supported and not tested; there is no
  `tomli` fallback (`tomli-w` from earlier notes is not a dependency either -
  writes go through `tomlkit`).

## Operating systems — honest status

Everything in this repository was **built and hand-tested on Windows 11 (build
26200, `sys.getwindowsversion().build`), CPython 3.12.10 (MSC v.1943, AMD64)**,
in Git Bash. That is still the only environment any statement in the docs is
*hand*-run against. GitHub Actions now executes the lint, the format check,
`mypy` and `pytest -m "not integration"` on `ubuntu-latest`, `macos-latest` and
`windows-latest` at Python 3.12 and 3.13; its fourth run (`5b047ad`), fifth (`75daed2`) and
sixth (`3d460df`) each came back
**green on all seven jobs**, after the third run - the first one whose suite
result could be trusted, see the `tee` story in
`docs/roadmap/CURRENT_STATUS.md` - came back **red on all six columns, on eight
test functions that depend on the machine**. So this tree's POSIX code paths are
*executed* on Linux and macOS and have never failed there. Run #6 is the one that first carried
`tests/test_secrets.py`, so the three POSIX file-mode cases that skip here ran on Ubuntu and
macOS instead of skipping - the only POSIX *behaviour* (as opposed to branch) this project has
evidence for. That is a weaker claim
than the table used to imply in the other direction, and a stronger one than
"not run at all": a green column proves the branch was reached and nothing
asserted otherwise, and the ten `integration` cases stay out of every column.
The separate bare-wheel job (install with no extras, four heavy modules refusing
with exit 3, `doctor --json` reporting them MISSING) has passed on Ubuntu in
every run, which is the one non-Windows behaviour in this table that is actually
exercised rather than inferred.

| Area | Windows 11 | Linux | macOS | Verified? |
|---|---|---|---|---|
| Core CLI, config, storage, dashboard | works, all tests hand-run here | the CI set (all but the 10 `integration` cases) green in run #4 | the CI set green in run #4 | executed green on all three; **hand-run Windows only**, and the 10 device/OS-tool cases have never run outside Windows |
| Paths (`platformdirs`) | `%APPDATA%\levix`, `%LOCALAPPDATA%\levix\Log` | `~/.config/levix` etc. | macOS equivalents | Windows resolved here; POSIX per platformdirs docs - **not executed anywhere**, because `tests/conftest.py` sets `LEVIX_HOME` on every platform, so the real POSIX defaults are never asked for |
| Terminal VT bootstrap (`terminal._windows_vt_enabled`) | `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)` via ctypes | n/a (returns True) | n/a (returns True) | Windows only |
| ffmpeg install advice (`tube/core.py`) | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` (fallback key) | `brew install ffmpeg` | strings are in the tree; **only the Windows branch's context was observed here** - `tests/modules/test_tube.py:193-202` checks the POSIX strings by calling `install_command_for(platform)` directly, so no POSIX host ever asked for them |
| psutil sensors (`capabilities.py`, monitor) | runs; temperature often UNSUPPORTED on Windows | temperature sensors typically present | partially | the monitor suite swaps `psutil` for a stand-in; run #4 did execute the real-psutil `run_cli` cases on Linux and macOS, but **no assertion is about a POSIX sensor reading** |
| keyring backends (`secrets.py`) | Windows Credential Store path | SecretService/libsecret (not installed/probed here) | macOS Keychain | **no real keyring on any platform**: every test replaces `secrets._keyring` with a fake (`tests/modules/test_ai.py:568-599`, `:922-990`) |
| Secrets-file permissions (`secrets.py:128-139` and `_harden` at `:142-163`) | created `O_CREAT` at `0600`, then `chmod` and `icacls /inheritance:r /grant:r <user>:F`; `tests/test_secrets.py::test_the_acl_holds_one_explicit_grant_and_no_inherited_read` runs the real `icacls` and requires one grant, to this user, with nothing inherited | created `O_CREAT` at `0600`, then `chmod 0600`; three cases assert the mode - after a real write, with the `chmod` forced to fail, and over a store that already existed at `0644` | same as Linux | **the Windows ACL is asserted here, and CI run #6 (`3d460df`) executed the three POSIX cases on Ubuntu 3.12/3.13 and macOS 3.12/3.13 without skipping and without failing** - so the POSIX mode is now asserted-on-a-POSIX-runner, not merely asserted-in-code. What is still unmeasured is *why* it holds on a given filesystem: no runner's umask, mount options or ACL default was read. `st_mode` on Windows reads `0o666` for any ordinary file, which is why the mode cases are POSIX-only instead of cross-checked |
| Audio (PortAudio via sounddevice, tested integration) | real playback test ran here | run #3: `OSError: PortAudio library not found` | run #3: neither failed nor reported | **not executed** on either; the three device cases are `integration` and stay out of the matrix, because a headless runner's honest answer is "no devices" |
| yt-dlp (stubbed in tests; no network in CI) | n/a | n/a | n/a | network path **not executed anywhere**; see `tests/modules/test_tube.py` docstring |

Rule of this document: where a column says "not executed", treat the code as
plausible, not promised. A green CI run does not upgrade a row either - it says
the code was *reached* on that platform without failing, not that the behaviour
the row names was observed.

## Console and codepage (the cp1252 constraint)

Windows consoles default to codepages like cp1252, where writing e.g. U+2588
raises `UnicodeEncodeError` **inside Rich's win32 writer - a crash, not cosmetic
damage** (recorded in `src/levix/terminal.py::active_glyphs`). Consequences, all
in code:

- `terminal.detect()` decides `supports_unicode` by checking whether
  `sys.stdout.encoding` contains "utf" (`LEVIX_NO_COLOR=1`, `NO_COLOR`,
  `TERM=dumb` also disable colour/unicode).
- `terminal.glyphs()` returns a unicode set (`█ ▓ · → ✓ ✗ ─` and a braille
  spinner) or an ASCII set (`# + . -> OK !! -` and `\|/-`). Renderers call
  `active_glyphs()`/`bar()`; **no non-ASCII glyph is hardcoded in any module**
  (`tube/cli.py` docstring, `arcade/screens.py` docstring: "Every glyph is
  ASCII"; `music/cli.py::_clip` truncates with `+`, "never Rich's U+2026").
- `terminal.bar(percent, width)` emits a Rich-markup usage bar with only
  codepage-safe characters; colours switch at 60% and 85%.
- `terminal.encode_safe(text)` rewrites foreign text for the current stream:
  non-printable/control characters become `\xNN`, and anything the encoding
  cannot hold is backslash-escaped (`\uXXXX`) via `backslashreplace`. The module
  CLIs wrap **every** dynamic value (site titles, device names, paths) in
  escape + encode_safe before printing: `tube/cli.py::_show`, `music/cli.py`'s
  `_show`/`_clip` over `core.safe_text`, `main.py::_plain`. This closes two
  crashes at once: Rich eating `[...]` in real filenames, and cp1252 refusing an
  emoji in a video title.

## stdout is not a TTY

`levix ... > file`, pipes, and captures are first-class:

- **Progress bars degrade to a single final frame.** Tube: `Live` is refreshed
  only `console.is_terminal`; the final frame prints once when the block exits,
  and a blank line is emitted before the summary so the table starts clean
  (`tube/cli.py::download/_progress_hook`). Music: `_Progress.__call__` returns
  immediately off a terminal, so the callback prints nothing to a pipe.
- **The dashboard refuses with exit 2.** `commands/dashboard_cmd.py`: if stdout
  or stdin is not a TTY it prints "The dashboard needs an interactive terminal."
  and raises `typer.Exit(code=EXIT_USAGE)` - Textual never emits escape
  sequences into someone's data.
- **Arcade screens refuse with exit 1** (`ArcadeError`) pointing at `--auto N`;
  `--auto` is the no-TTY path by design and runs the identical rule functions
  (`arcade/screens.py::require_terminal`, tested - see `test_arcade.py`).
- **Confirmations refuse, not assume.** `approve.require_approval` treats a
  non-TTY stdin as a refusal: `UserCancelledError`, exit 6.
- Colour: `NO_COLOR` and `LEVIX_NO_COLOR=1` disable colour in `detect()`; the
  test harness runs with `NO_COLOR=1` (`tests/conftest.py`).

## Exit codes (the scriptable contract)

From `src/levix/errors.py`: 0 ok, 1 unhandled runtime error, 2 usage (click
default), 3 missing dependency/extra, 4 unknown module, 5 configuration, 6 user
declined confirmation, 7 external tool failed (ffmpeg, mpv, PortAudio...), 8
network/provider failed, 130 Ctrl+C. `levix doctor --json` maps environment,
modules and capabilities to the same table.

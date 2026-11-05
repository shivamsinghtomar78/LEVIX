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

Everything in this repository was **built and tested on Windows 11 (build
26200, `sys.getwindowsversion().build`), CPython 3.12.10 (MSC v.1943, AMD64)**,
in Git Bash. That is still the only environment any statement in the docs is
*hand*-run against. GitHub Actions now executes the lint, the format check,
`mypy` and `pytest -m "not integration"` on `ubuntu-latest`, `macos-latest` and
`windows-latest` at Python 3.12 and 3.13, and its third run - the first one whose
suite result could be trusted, see the `tee` story in
`docs/roadmap/CURRENT_STATUS.md` - came back **red on all six columns, on eight
test functions that depend on the machine**. Each of the eight is fixed in the
tree; none of the fixes is proven until a run says so. The separate bare-wheel job
(install with no extras, four heavy modules refusing with exit 3, `doctor --json`
reporting them MISSING) has passed on Ubuntu in every run, which is the one
non-Windows behaviour in this table that is actually executed rather than inferred.

| Area | Windows 11 | Linux | macOS | Verified? |
|---|---|---|---|---|
| Core CLI, config, storage, dashboard | works, all tests hand-run here | same cases executed by CI | same cases executed by CI | **hand-run Windows only**; CI reaches all three and has not gone green yet |
| Paths (`platformdirs`) | `%APPDATA%\levix`, `%LOCALAPPDATA%\levix\Log` | `~/.config/levix` etc. | macOS equivalents | Windows resolved here; POSIX per platformdirs docs - **not executed** |
| Terminal VT bootstrap (`terminal._windows_vt_enabled`) | `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)` via ctypes | n/a (returns True) | n/a (returns True) | Windows only |
| ffmpeg install advice (`tube/core.py`) | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` (fallback key) | `brew install ffmpeg` | strings are in the tree; **only the Windows branch's context was observed here** |
| psutil sensors (`capabilities.py`, monitor) | runs; temperature often UNSUPPORTED on Windows | temperature sensors typically present | partially | **not executed on POSIX** |
| keyring backends (`secrets.py`) | Windows Credential Store path | SecretService/libsecret (not installed/probed here) | macOS Keychain | **not executed** on either |
| `icacls` ACL hardening of the secrets file | shelled out with fixed argv on `os.name == "nt"` | skipped (chmod only) | skipped (chmod only) | Windows only |
| Audio (PortAudio via sounddevice, tested integration) | real playback test ran here | run #3: `OSError: PortAudio library not found` | run #3: neither failed nor reported - skipped or passed, and the log that would say which needs a signed-in account | **not executed** on either; the three device cases are `integration` and stay out of the matrix, because a headless runner's honest answer is "no devices" |
| yt-dlp (stubbed in tests; no network in CI) | n/a | n/a | n/a | network path **not executed anywhere**; see `tests/modules/test_tube.py` docstring |

Rule of this document: where a column says "not executed", treat the code as
plausible, not promised. A CI run that has not gone green does not upgrade a row
either - it says the code was *reached* on that platform, not that it was right.

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

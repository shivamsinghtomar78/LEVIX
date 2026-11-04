# Changelog

All notable changes to LEVIX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

Everything below is work done after the `0.4.0` commit and is not yet released: the
documentation set, the packaging fix, and a set of defects found by reading the docs
against the code.

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
- `levix ai key set` / `levix ai key clear`: the write path for the provider credential,
  through `LevixContext.store_secret()` / `forget_secret()` to `secrets.set_secret()` /
  `delete_secret()`. The key is prompted with echoing off, so it never enters argv, the
  process list or a crash report; `LEVIX_DISABLE_FILE_SECRETS=1` refuses the plaintext tier.
- `Permission.SECRET_WRITE`, so a module that can replace a credential discloses something
  different from one that can only read it. Disclosure, as always, not enforcement.

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
- Where the documentation was wrong rather than the code, the text was cut back to the size
  of the evidence: three pages still described the masked secret as `[set, hidden]` after the
  brackets had come out of `_MASK`; the file-store-disabled refusal was quoted as exiting 7
  when `EXIT_MISSING_DEPENDENCY` is 3; and `tests/modules/test_systempulse.py` was said to
  hold 45 tests where the collector reports 40 functions and 46 cases. `levix.sdk`'s export
  count moved with the code, from 15 names to 14. Every count in `docs/` now comes from
  `pytest --collect-only` and every claim names the file or test that shows it.

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

### Verification

- `ruff check src tests` and `ruff format --check src tests` exit 0 (77 files already
  formatted); `mypy src/levix` exits 0 with no issues in 59 source files.
- The suite, on this machine: `.venv/Scripts/python.exe -m pytest -o addopts="" -q` runs
  **580 test functions in 17 files, collecting 698 parametrised cases** and reports
  **693 passed, 5 skipped, 2 warnings in 157.55 s**, exit 0. The five skips are the symlink
  cases in `tests/modules/test_files.py` (this account cannot create symlinks; three more
  state that POSIX symlinks need no privilege there). The two warnings are a NumPy 2.5
  deprecation inside `sounddevice`, raised by the one real-device playback test.
- Every `file:line` citation and every `::test_...` name in `docs/` was re-checked against
  this tree with a throwaway script - 205 cited test names among the 580, 312 line ranges,
  none missing or out of bounds. The script was not committed; `docs/roadmap/CURRENT_STATUS.md`
  is the page that states which of the claims are machine-verified and which are not.
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
- None of the above was run on Linux or macOS. Both are designed for and neither is proven.

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

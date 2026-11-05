# LEVIX Non-Functional Requirements

Constraints on how the behaviour in `FUNCTIONAL_REQUIREMENTS.md` must be delivered. Each
requirement names the code that carries it and, where one exists, the test that pins it.
Numbers marked *measured* come from this working tree on Windows 11 with Python 3.12.10 and
an editable `.venv` install; they are observations, not asserted budgets.

## NFR-1 Startup: help must stay cheap

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-1.1 | `levix --help` and `<module> -h` must not import `psutil`, `yt_dlp`, `sounddevice`, `soundfile`, `numpy` or `textual`. | `registry.discover` (loads manifest data only), `router._attach` (`add_help_option=False`), `registry.build_cli` as the single deferred-import site | `tests/test_router.py::test_help_forwarding_does_not_import_a_heavy_dependency`, `::test_an_official_module_help_does_not_import_its_own_dependency` |
| NFR-1.2 | The invariant is proved in a fresh interpreter, not in the test process, because the suite itself has already imported psutil and friends. | `tests/test_router.py::_child_heavy_loads` (spawns `[sys.executable, "-c", script]`, `shell=False`, `timeout=120`), `tests/modules/test_tube.py::_child` | the two tests above; per-module `test_importing_the_manifest_pulls_in_nothing_heavy` in `test_tube.py`, `test_files.py`, `test_arcade.py`, `test_music.py`, and `test_hacker.py::test_importing_the_module_package_pulls_in_no_heavy_dependency` |
| NFR-1.3 | `levix --help` and `levix --version` touch no files: no config, no database, no log directory. | `app.build_context` runs only after eager options have exited (`src/levix/app.py`) | `tests/test_router.py` child runs (`CODE=0` assertion) |
| NFR-1.4 | Importing the engine must not import a *module's* dependency; the cost of the core itself is accepted. | `pyproject.toml` core dependency list; `src/levix/__init__.py` resolves `__version__` lazily | measured: importing `levix.main` into a bare interpreter adds 186 modules; `levix --help` completes in 1.01 s best-of-3 here, `levix tube -h` in 1.03 s |
| NFR-1.5 | A full-screen module must not be imported to render the list; `textual` enters only through the dashboard or a screen command. | `commands/dashboard_cmd.py` (import inside the function), `modules/files/browse.py`, `modules/arcade/screens.py` | `tests/modules/test_arcade.py::test_the_screen_is_not_imported_by_help_or_scores`, `tests/modules/test_files.py::test_browse_help_does_not_start_a_screen` |

No test asserts a wall-clock budget. The design goal is *which imports happen*, and that is
what is enforced.

## NFR-2 Exit-code stability and failure containment

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-2.1 | The set of exit codes is closed and documented once; nothing may invent a code locally. | `src/levix/errors.py` (`EXIT_CODE_MEANINGS`, `LevixError.exit_code`) | exit-code-named tests across `tests/modules/` |
| NFR-2.2 | Click's own codes survive forwarding, including a module's own `typer.Exit(code=N)`. | `router._forward` (`standalone_mode=False`, integer return), `main._classify` | `tests/test_router.py::test_a_module_can_exit_with_its_own_code` |
| NFR-2.3 | Exceptions raised by Typer's vendored click fork are still classified: matching is by MRO class **name**, since `isinstance(exc, click.UsageError)` is false there. | `src/levix/main.py` header docstring, `_classify` | `tests/test_router.py` forwarding and help tests |
| NFR-2.4 | A broken plugin must not make LEVIX unstartable; it is listed and explained. | `registry.discover` `except Exception` branch, `_broken` | `tests/test_registry.py::test_the_good_modules_survive_a_broken_one_in_the_real_list` |
| NFR-2.5 | Non-critical work (history, logging setup, closing a context, a capability probe) must never change a user's exit code; failures are swallowed deliberately and narrowed. | `main._record`, `main` finally-block, `logging_setup.setup`, `capabilities.probe` | `tests/test_storage.py` (history behaviour), rest unverified |
| NFR-2.6 | A genuine bug is reported as a bug: type, message, a pointer to `levix doctor`, the last 1500 characters of traceback, exit 1. | `main._report_unexpected` | unverified |

## NFR-3 Portability and terminal resilience

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-3.1 | No output may assume the console can encode Unicode. Writing `U+2588` through Rich's win32 writer raises `UnicodeEncodeError`, so glyph sets come from `terminal.active_glyphs()` (cached, `lru_cache(maxsize=1)`). | `src/levix/terminal.py` (`glyphs`, `active_glyphs`, `bar`) | `tests/test_terminal.py` (19 tests) |
| NFR-3.2 | Text that arrives from outside the terminal (site titles, file names, model replies) is folded onto one printable line, with unencodable characters as `\uXXXX` and control characters as `\xNN`, before it reaches the console. | `terminal.encode_safe`, `main._plain`, `modules/tube/cli.py::_show`, `modules/files/cli.py::show`, `modules/files/core.py::printable` | `tests/modules/test_files.py::test_printable_survives_a_name_the_console_cannot_encode` |
| NFR-3.3 | Markup inside dynamic values must not be interpreted: everything user-supplied is `rich.markup.escape`d on the way out. | `main._plain`, `_show`, `show`, `dashboard/app.py` `markup=False` notifications | `tests/modules/test_files.py::test_printable_keeps_what_the_console_can_encode` |
| NFR-3.4 | On Windows, ANSI escape sequences are emitted only after `ENABLE_VIRTUAL_TERMINAL_PROCESSING` (0x0004) has been confirmed; a failure degrades to plain text and never raises. | `terminal._windows_vt_enabled` (ctypes `GetStdHandle`/`GetConsoleMode`/`SetConsoleMode`) | `tests/test_terminal.py` |
| NFR-3.5 | Colour obeys `NO_COLOR`, `LEVIX_NO_COLOR=1`, `TERM=dumb` and a non-TTY stdout. | `terminal.detect` | `tests/test_terminal.py`, `tests/conftest.py` |
| NFR-3.6 | Python 3.12+ only, Windows, Linux and macOS paths resolved through platformdirs; `LEVIX_HOME` moves all five directories at once, and `LEVIX_{CONFIG,DATA,CACHE,STATE,LOG}_DIR` override one each. | `src/levix/paths.py` | `tests/test_config.py`, `tests/conftest.py` |
| NFR-3.7 | A frozen (PyInstaller-style) build re-executes its own executable; a source checkout re-executes `sys.executable -m levix`, never whatever `python` is first on `PATH`. | `src/levix/spawn.py::levix_argv` | `tests/test_dashboard.py::test_enter_on_a_ready_row_runs_the_same_command_line` (argv captured) |

## NFR-4 Plain-text accessibility when not a TTY

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-4.1 | Interactive surfaces refuse with an explanation and a pipe-friendly alternative instead of emitting escape sequences into data. | `commands/dashboard_cmd.py` (exit 2), `modules/files/browse.py::run_browse` (exit 1 + hint), `modules/arcade/screens.py::require_terminal` | `tests/test_dashboard.py::test_dashboard_refuses_a_redirected_terminal_with_the_usage_code` |
| NFR-4.2 | Animation is bounded when nothing can watch it: `hacker matrix` on a captured stream requires `--iterations` or `--duration`, and `arcade --auto` is capped at 100000 steps. | `modules/hacker/cli.py:99-103`, `modules/arcade/cli.py::_auto_steps` | `tests/modules/test_hacker.py::test_matrix_seed_repeats_a_run` |
| NFR-4.3 | Progress output is either a single final frame or nothing when captured, and throttled to 0.1 s when drawn. | `modules/tube/cli.py::_progress_hook`, `modules/music/cli.py::_Progress`, `Live(..., refresh=console.is_terminal)` | `tests/modules/test_tube.py` progress-hook tests |
| NFR-4.4 | A captured stream must not have its last frame run into the summary line. | `tube/cli.py::download`, `hacker/cli.py` (`console.print()` when not a terminal) | `tests/modules/test_tube.py` |
| NFR-4.5 | Machine-readable output exists where a script would want it: `doctor --json` and `update --json`. No module command offers `--json`. | `commands/doctor_cmd.py`, `commands/update_cmd.py` | observed: `levix monitor cpu --json` exits 2 ("No such option: --json") |

## NFR-5 Security and privacy

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-5.1 | **No `shell=True` anywhere.** Every subprocess is an argument list, resolved through `shutil.which` where the program is chosen dynamically. | `spawn.run`, `secrets._harden`, `config_cmd.edit`, `tube/core.py::launch` (`shell=False`), `ai/core.py::run_proposal`, `hacker/core.py::run_tool` | `tests/modules/test_tube.py::test_a_player_is_handed_an_argument_list_not_a_shell_string`; `pyproject.toml` keeps flake8-bandit `S` rules selected (only `S603`, `S607` ignored) |
| NFR-5.2 | Commands proposed by a model are refused before approval if they contain a pipeline, `;` or a redirection; execution is `shell=False` on a `shutil.which`-resolved path. | `ai/core.py::extract_proposal`, `run_proposal` | `tests/modules/test_ai.py::test_command_refuses_a_pipeline_proposal_before_any_approval` |
| NFR-5.3 | Credentials never enter logs. Redaction is a `logging.Filter` attached to the logger, so a module that logs a formatted exception cannot bypass it: `Authorization: bearer …`, `sk-…`, `ghp_`/`gho_`/`github_pat_…` and any `*api[_-]?key\|token\|secret\|password*=…` pair are replaced. | `src/levix/logging_setup.py` (`RedactFilter`, `_PATTERNS`) | `tests/test_logging.py` — six parametrised shapes through `redact`, one through a real `LogRecord`, one that writes a real rotating log file and greps it, one that adds an unfiltered handler to prove the logger-level filter. **Residual:** patterns, not a schema — a credential in a shape they do not name (a JWT, say) is still logged; see Known gaps |
| NFR-5.4 | Nothing is logged to stdout, which would corrupt Rich and Textual output; only a stderr WARNING handler exists when no file handler could be opened. | `logging_setup.setup` | `tests/test_logging.py::test_the_only_console_handler_writes_to_stderr` (the fallback handler's stream is `sys.stderr` and its level is `WARNING`) |
| NFR-5.5 | Secrets are never read from or written to configuration files; `config list`/`show` mask secret-shaped keys and `config set` refuses them. | `secrets.py` docstring, `config.is_secret_key`, `commands/config_cmd.py` (`_MASK`) | `tests/test_config.py`; observed masking of `ai.max_tokens` |
| NFR-5.6 | The plaintext secret fallback is described as what it is — owner-only access control, not encryption — and `doctor` reports it as `degraded`. `LEVIX_DISABLE_FILE_SECRETS=1` removes it entirely. | `secrets.backend`, `doctor.environment` | `tests/modules/test_ai.py::test_key_from_the_owner_only_file_when_no_keyring` |
| NFR-5.7 | No request ever asks a media site for cookies, credentials or account state, and there is no DRM or download-protection bypass; `file://` URLs stay off until explicitly allowed. | `modules/tube/core.py` | `tests/modules/test_tube.py::test_no_request_ever_asks_for_credentials_or_cookies`, `::test_file_urls_stay_disabled_until_they_are_explicitly_allowed` |
| NFR-5.8 | LEVIX never modifies its own installation; the one default network call is to the PyPI JSON API and is disclosed in the output. | `commands/update_cmd.py` | unverified (needs network) |
| NFR-5.9 | A key is never sent to a host that is not the configured provider; remote hosts without a key are refused, loopback and Ollama are exempt. | `ai/core.py::resolve_key` | `tests/modules/test_ai.py::test_resolve_key_refuses_a_remote_host_without_a_key` |
| NFR-5.10 | Plugin permissions are disclosure, not enforcement, and `plugins info` says so to the user. | `commands/plugins_cmd.py` | unverified as a test; message is in code |
| NFR-5.11 | SQL is parameterised; the only interpolated identifier is a module-level table-name constant, and the two files where that is visible carry a reviewed `S608` per-file ignore rather than a project-wide silence. | `storage.py`, `pyproject.toml` `[tool.ruff.lint.per-file-ignores]` | `tests/test_storage.py` |

## NFR-6 Safety of the user's data

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-6.1 | One destructive gate for the whole product, so the AI module cannot invent a weaker prompt than the file module. | `src/levix/approve.py` header docstring | `tests/modules/test_files.py::test_delete_yes_cannot_authorize_a_deletion`, `tests/modules/test_ai.py::test_command_yes_cannot_authorize_a_run`, `tests/modules/test_arcade.py::test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it` |
| NFR-6.2 | Non-interactive stdin is a refusal, never consent, and the refusal names the way out. | `approve.require_approval` | `tests/modules/test_files.py::test_delete_refuses_without_a_terminal_and_removes_nothing` |
| NFR-6.3 | Downloads and file copies never overwrite silently; a collision needs `--force` **and** the typed word `OVERWRITE`. | `tube/cli.py`, `files/cli.py::_confirm_overwrite` | `tests/modules/test_tube.py::test_existing_files_are_never_overwritten`, `tests/modules/test_files.py::test_copy_with_force_still_needs_a_terminal` |
| NFR-6.4 | `config reset` keeps `config.toml.bak` before removing the file. | `commands/config_cmd.py::reset` | unverified |
| NFR-6.5 | Path escaping is refused before any filesystem work: the `--root` wall confines browse, copy, move, rename and delete. | `modules/files/core.py` (`UnsafePathError`) | `tests/modules/test_files.py` (146 tests) |
| NFR-6.6 | Pruning only ever touches LEVIX's own command history, bounded by `general.history_limit`. | `storage.prune_history`, `main._record` | `tests/test_storage.py` |

## NFR-7 Honesty of reporting

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-7.1 | A metric that cannot be read is reported as unknown, never as zero. The words used are "not reported", "not reported by this platform", "unsupported". | `modules/systempulse/cli.py:85,96,98,119`, `capabilities.py` docstring (`UNSUPPORTED` is a real answer), `modules/tube/cli.py` size/uploader rows | `tests/modules/test_tube.py::test_summary_reports_a_field_the_site_did_not_provide_as_unknown`, `::test_an_unknown_total_is_said_as_unknown_rather_than_zero` |
| NFR-7.2 | An unavailable capability with an installed package is distinguished from a missing package: probes differ from `deps`. | `capabilities.py` vs `deps.py` | observed: `gpu` row prints "unsupported - psutil exposes no GPU API" while psutil 7.2.2 is installed |
| NFR-7.3 | An install hint is omitted rather than guessed when it would not name a real package. | `module.resolved_install_hint`, `deps.ensure_dependencies` ("no install hint is declared for this module") | `tests/test_registry.py::test_a_module_that_names_no_provider_gets_no_invented_pip_line` |
| NFR-7.4 | Version comparison that cannot be parsed yields `uncertain`, which is surfaced, not treated as satisfied silently. | `deps.Availability.UNCERTAIN`, `describe` | `tests/test_deps.py` |
| NFR-7.5 | An update check that fails says it is a network limitation, not that the user is current. | `commands/update_cmd.py` | unverified |
| NFR-7.6 | An unknown theme is reported in the UI rather than ignored. | `dashboard/theme.py::apply` | `tests/test_dashboard.py::test_theme_binding_cycles_only_through_registered_themes` |
| NFR-7.7 | `hacker network` prints which tool produced each row and never implies it queried anything remote. | `modules/hacker/cli.py:404,495` ("Where the data came from") | `tests/modules/test_hacker.py` |

## NFR-8 Performance and resource behaviour

| ID | Requirement | Delivered by | Verified by |
| --- | --- | --- | --- |
| NFR-8.1 | SQLite is opened per call, never cached, so Textual workers and a suspended child process each get their own connection; WAL plus a 5-second busy timeout absorb the shared file. | `storage.Database.connect` | `tests/test_storage.py` |
| NFR-8.2 | Logs rotate at 512,000 bytes with 3 backups. | `logging_setup.setup` | unverified |
| NFR-8.3 | Discovery and probes are cached for the life of a run; the dashboard's `r` reload installs a new registry rather than trusting the cache. | `registry.discover`, `context._probe_cache`, `LevixDashboard.action_reload` | `tests/test_registry.py::test_active_registry_is_injectable_and_resettable` |
| NFR-8.4 | Bounded work by default: history capped at 50 rows, `monitor.process_limit` 15 (1-200), `dashboard.recent_commands` 10 (0-200), `explain` reads 32,000 bytes per file, `grep` skips files over 2 MiB, AI HTTP timeout 60 s, `run_proposal` timeout, `update --timeout` 1-60 s (default 6.0). | `defaults.toml`, `config.SCHEMA`, `ai/core.py`, `files/core.py`, `update_cmd.py` | `tests/test_config.py`, `tests/modules/test_files.py` |
| NFR-8.5 | Measured on this machine: `levix doctor --json` completes in 2.56 s best-of-3 (it runs every probe and touches the database); `levix --help` in 1.01 s. | observation, 2026-11-04 | no budget is asserted |

## NFR-9 Maintainability

| ID | Requirement | Delivered by | Evidence |
| --- | --- | --- | --- |
| NFR-9.1 | Every function in `src/levix` is annotated: mypy runs with `disallow_untyped_defs = true` (not full `strict`). | `pyproject.toml` `[tool.mypy]` | `mypy src/levix` exits 0 ("no issues found in 59 source files") — see the closed item below |
| NFR-9.2 | A manifest carries only what help, the dashboard and the gate need; command parameters are never duplicated into it. | `module.CommandInfo` docstring | `ADR-0002` |
| NFR-9.3 | One piece of process-level state is allowed, and it is documented as such. | `registry._ACTIVE`, `active()`, `use()` | `tests/conftest.py::_reset_registry` autouse fixture |
| NFR-9.4 | Availability logic exists in exactly one place; nothing else may `try: import x except ImportError` to decide. | `deps.py` docstring | `tests/test_deps.py::test_no_availability_check_imports_the_module_it_probes` |
| NFR-9.5 | Lint rules encode the safety requirements: `S` (bandit), `T20` (no print), `B`, `SIM`, `UP`, `I`; `T20`/`S101` relaxed only for tests, `B008` only where Typer's signature idiom requires it. | `pyproject.toml` `[tool.ruff]` | `ruff check src tests` exits 0; `ruff format --check src tests` reports 77 files already formatted |
| NFR-9.6 | Line length 100, `target-version = "py312"`, source dirs `src` and `tests`. | `pyproject.toml` `[tool.ruff]` | — |
| NFR-9.7 | The public plugin surface is a façade with no logic, so it can be promised stable without a parallel implementation. | `src/levix/sdk.py` | — |

## NFR-10 Compatibility and dependency policy

| ID | Requirement | Delivered by | Evidence |
| --- | --- | --- | --- |
| NFR-10.1 | Heavy dependencies are optional extras; the core installs six packages. | `pyproject.toml` | `ADR-0006` |
| NFR-10.2 | Upper bounds pin every core dependency: `typer>=0.27,<0.28`, `click>=8.5,<9`, `rich>=15.0,<16`, `textual>=8.2,<9`, `platformdirs>=4.14,<5`, `tomlkit>=0.15,<1`. | `pyproject.toml` | installed: typer 0.27.3, click 8.5.0, rich 15.0.0, textual 8.2.8, platformdirs 4.14.3, tomlkit 0.15.2 |
| NFR-10.3 | The coupling to Typer's vendored click fork is a documented, pinned risk rather than an assumption about `click`. | `router.py`, `main.py` docstrings | `ADR-0003` |
| NFR-10.4 | No `packaging` dependency for version comparison; a 3-component numeric prefix is enough for the pins in use and is honest about the rest. | `deps._VERSION_RE`, docstring | `tests/test_deps.py` |
| NFR-10.5 | stdlib `tomllib` for reads, `tomlkit` for writes; no third-party TOML writer. | `config.py` | `ADR-0004` |

## NFR-11 Testability

| ID | Requirement | Delivered by | Evidence |
| --- | --- | --- | --- |
| NFR-11.1 | No test touches a real user profile: the `levix_home` fixture deletes every `LEVIX_*` variable, sets `LEVIX_HOME`, disables file logging and forces `NO_COLOR=1`. | `tests/conftest.py` | file logging is disabled because an open handle makes Windows fail to delete the temp directory |
| NFR-11.2 | Tests run the real entry point so exit codes and history are exercised, not just command bodies. | `tests/conftest.py::run_cli` → `levix.main.main(list(argv))` | `711 passed, 5 skipped` suite (the skips are all symlink cases) |
| NFR-11.3 | The registry is injectable, and reset before and after every test. | `registry.use`, `conftest._reset_registry` (autouse) | `tests/test_registry.py::test_active_registry_is_injectable_and_resettable` |
| NFR-11.4 | The dashboard is tested headless with Textual's Pilot (`run_test(headless=True, size=(100, 30))`) because the suite runs where there is no terminal. | `tests/test_dashboard.py` header, `app.run_test` | 15 dashboard tests |
| NFR-11.5 | Markers `integration` and `slow` are declared and `--strict-markers` is on; 10 tests are marked `integration`. | `pyproject.toml` `[tool.pytest.ini_options]` | no test uses `slow`. Three of the ten ask the machine which sound devices it has, which is what CI's headless runners cannot answer |

## Known gaps

- **Redaction matches patterns, not a schema.** `tests/test_logging.py` now proves what
  `RedactFilter` claims to remove, and proves it reaches the file. What remains true is the
  other half: a credential in a shape the four patterns do not name — a JWT in a provider's
  error body, an opaque `X-Auth: …` header — is logged verbatim, because nothing here parses
  the message.
- **POSIX behaviours are still unasserted.** CI run #4 (`5b047ad`) is green on Ubuntu and
  macOS, so the POSIX branches of the code the suite reaches do execute there — including the
  `chmod` in `secrets._harden`. What no test does is stat the resulting mode, run the OS's own
  network tools and parse their real output (`ip addr show`, `ifconfig`, `resolv.conf`,
  `nsswitch.conf`, `route -n`), or exercise the POSIX keyring. The parsers are fed captured
  POSIX text; that is a test of the parser, not of the platform.
- **Coverage is configured but no threshold is enforced** (`[tool.coverage.run]` with
  `branch = true`; no `--cov` in `addopts`).
- **The pre-commit hooks are configured, not run.** `.pre-commit-config.yaml` names
  `ruff --fix`, `ruff-format` and mypy on `^src/levix/`; installing the hooks and letting them
  rewrite a commit is not verified here.

## Closed since the first draft of this page

- **NFR-5.3 and NFR-5.4 had no test.** `tests/test_logging.py` (6 functions, 11 cases) drives
  `RedactFilter` through six credential shapes, through a real `LogRecord`, into a real
  rotating log file, and through a handler that carries no filter of its own - which is the
  only way to show the promise lives on the logger rather than on a handler someone could
  replace. It also asserts the fallback handler is a `WARNING`-level stderr one. The file
  writes to disk even though `tests/conftest.py` keeps file logging off for the rest of the
  suite, so it closes its own handlers: an open handle is what stops Windows deleting a
  temporary directory.
- **There were no monitor tests.** `tests/modules/test_systempulse.py` now holds 40 test
  functions (46 collected cases), the sampling layer against a fake `psutil` and the command
  surface against the real machine, so NFR-7.1's most visible instance - the `temp` and `gpu`
  rows - is asserted rather than shown by hand.
- **Doctor filtering was inert.** `--only modules` / `--only capabilities` computed a
  `prefix` in `commands/doctor_cmd.py` and never applied it, so every area printed. The
  filter is applied at `doctor_cmd.py:43-54` and `tests/test_doctor.py` (6 cases) asserts
  each area's row prefixes and that `--json` verdicts come from the rows actually shown.
- **Lint and typing were dirty.** `ruff check src tests`, `ruff format --check src tests`
  and `mypy src/levix` now all exit 0 on Windows with the `.venv` in this repo (the numbers
  behind the earlier 44-findings/65-errors state are gone). Nine `# noqa` remain in
  `src/levix`, every one a rule that fires on correct code: `S105` on the two
  `Permission.SECRET_*` enum values and on `ai/core.SECRET_NAME` (a lookup key name, not a
  credential), `S311` on the seeded pseudo-random generators in Arcade and Hacker (game dice,
  not crypto), `S310` on the single HTTPS release-check feed in `update_cmd.py`, `S104` on the
  `0.0.0.0` literal Hacker uses to describe an any-address bind, and `B009` on two
  `getattr(os, "getuid")` lookups. Two more sit in `tests/modules/test_ai.py` (`E731` on a
  two-line stand-in for `ctx.secret`, `S108` on a path that is only ever asserted absent) and
  one in `tests/test_logging.py` (`S105` on an invented `ghp_…` string whose only job is to be
  unmistakable in a failure message).
- **No inert configuration keys.** The two that existed (`general.confirm_destructive`,
  `dashboard.show_system_info`) are removed from `SCHEMA` and `defaults.toml` rather than
  wired up: the first would have made the destructive-action gate optional, and the second
  described a header panel the dashboard does not have.
- **The theme vocabulary and the schema now agree.** `config.SCHEMA` offers
  `default|hacker|minimal|high-contrast` and `dashboard/theme.py` maps all four onto a
  registered theme (a `levix-contrast` palette was added for the last one);
  `tests/test_dashboard.py::test_every_documented_theme_name_resolves` fails if they drift.

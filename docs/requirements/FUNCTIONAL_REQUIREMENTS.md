# LEVIX Functional Requirements

Every requirement below describes behaviour that exists in the 0.4.0 tree. The
`Where implemented` column is a real path or command; `Verified by` names a test that is
collected today (664 test functions, 829 cases). Where nothing verifies a requirement it says
**unverified** rather than guessing.

Conventions: exit codes are the ones in `src/levix/errors.py`; `<module>` means any of
`monitor`, `hacker`, `files`, `tube`, `game`, `music`, `ai` or an installed plugin.

## A. Discovery and registration

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-01 | Modules are discovered only from the `levix.plugins` entry-point group. No `sys.path` scanning, no drop-in folder import. | `src/levix/registry.py` (`GROUP`), `pyproject.toml` `[project.entry-points."levix.plugins"]` | `tests/test_registry.py::test_every_official_module_is_discovered` |
| FR-02 | Discovery loads a data object (`…:MANIFEST`) and must not import the module's dependencies or its Typer app. | `registry.discover`, `src/levix/modules/tube/__init__.py` | `tests/modules/test_tube.py::test_importing_the_manifest_pulls_in_nothing_heavy` |
| FR-03 | Discovery results are cached per `ModuleRegistry` instance; `levix plugins list` and the dashboard read the same cache. | `registry.discover` (`self._cache`) | `tests/test_registry.py::test_the_good_modules_survive_a_broken_one_in_the_real_list` |
| FR-04 | `origin` is stamped by the registry from the provider distribution name; a third party declaring `Origin.OFFICIAL` is rewritten to `third_party`, while its own declared version survives. | `registry._origin_for`, `_dist_version` | `tests/test_registry.py::test_a_plugin_cannot_claim_to_be_official`, `::test_a_plugin_version_comes_from_its_distribution_when_unset` |
| FR-05 | Official modules report LEVIX's own version, because they ship inside the `levix` distribution. | `registry._dist_version` | `tests/test_registry.py::test_official_modules_are_stamped_by_the_registry_not_by_themselves` |
| FR-06 | An entry point that raises on load becomes a broken manifest: empty `cli_path`, summary `failed to load: <ExcType>: <msg>`. LEVIX still starts and still lists the good modules. | `registry._broken`, `registry.is_broken` | `tests/test_registry.py::test_a_broken_entry_point_is_listed_and_explained_not_fatal` |
| FR-07 | An entry point that returns something other than a `ModuleManifest` is reported broken, never used. | `registry.discover` | `tests/test_registry.py::test_a_non_manifest_is_reported_as_broken_rather_than_used` |
| FR-08 | A manifest's command aliases are searchable: `registry.get("q")` returns the `ai` manifest. | `registry.get` | `tests/test_registry.py::test_a_command_alias_resolves_to_its_module` |
| FR-09 | The active registry is process-injectable and resettable, and injection triggers discovery once. | `registry.active`, `registry.use` | `tests/test_registry.py::test_active_registry_is_injectable_and_resettable`, `tests/conftest.py::_reset_registry` (autouse) |
| FR-10 | The set of declarable permissions is closed: `network`, `fs_read`, `fs_write`, `subprocess`, `audio`, `secret_read`, `secret_write`. | `src/levix/module.py` (`Permission`, seven members) | `tests/test_registry.py::test_permissions_are_a_closed_disclosure_set` |
| FR-11 | Each of the seven official manifests states how the dashboard opens it, so `ui` is never `None` where the shipped product is concerned; `mode` is `suspend` or `hidden`, and `hidden` is the example plugin's answer. A plugin that declares no `UiSpec` is not rejected - it is offered with the default, which is what `plugins info` now says out loud. There is no embedding mode: `registry.build_screen` and `UiSpec.screen_path` were deleted, because one TTY cannot host two Textual apps and the dashboard is one. | `module.UiSpec` (`module.py:67-81`), `module.ModuleManifest.ui` (`module.py:98`, `UiSpec \| None = None`), all seven `src/levix/modules/*/__init__.py`, `plugin-examples/hello/src/levix_hello/__init__.py` | `tests/test_registry.py::test_permissions_are_a_closed_disclosure_set` (asserts `manifest.ui is not None` for every discovered module), `::test_a_module_hidden_from_the_dashboard_is_still_discovered_and_routable` (hiding is the dashboard's rule, not the router's), `tests/test_dashboard.py::test_a_manifest_with_no_uispec_is_disclosed_as_offered_by_default` |
| FR-12 | An install hint is only produced when it would be a valid command: an official module with no extras, or a plugin with no provider, yields `None` so the caller can say "no install hint is declared". | `module.ModuleManifest.resolved_install_hint` | `tests/test_registry.py::test_a_module_that_names_no_provider_gets_no_invented_pip_line` |

## B. Command surface and routing

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-13 | `levix` prints the root help-style banner and opens the dashboard when there are no arguments. | `src/levix/app.py` (`invoke_without_command=True`) | `tests/test_dashboard.py::test_dashboard_refuses_a_redirected_terminal_with_the_usage_code` (same call path) |
| FR-14 | `levix --help`, `levix -h`, `<module> --help` and `<module> -h` exit 0. | `app.py` context settings, `router._attach` | `tests/modules/test_hacker.py::test_help_lists_all_three_commands`, `test_tube.py::test_tube_help_never_imports_yt_dlp` |
| FR-15 | `levix --version` / `-V` is an eager option that prints `levix <version>` and exits 0 before any paths, config or logging are touched. | `app.py` root callback | unverified as a named test; `build_context` docstring records the invariant |
| FR-16 | `--help` reaches the module's own parser: `<module> -h` shows Typer's real help for that module, not a copy written by the router. | `router._attach` (`add_help_option=False`, `ignore_unknown_options`) | `tests/modules/test_files.py::test_module_help_lists_every_command` |
| FR-17 | Arguments and flags after a module name are forwarded verbatim to the module app. | `router._forward` (`args=list(ctx.args)`) | `tests/test_router.py::test_module_arguments_and_flags_survive_the_forwarding` |
| FR-18 | The forwarded sub-application receives the root `LevixContext`, so module configuration keys resolve to real values rather than fallbacks. | `router._forward` (`obj=ctx.obj`), `commands/*` `_ctx` helpers | `tests/test_router.py::test_a_module_command_receives_the_context_built_by_the_root` |
| FR-19 | A module command's own integer return value becomes LEVIX's exit code. | `router._forward`, `main.main` | `tests/test_router.py::test_a_module_command_receives_the_context_built_by_the_root`, `::test_a_module_can_exit_with_its_own_code` |
| FR-20 | Help output touches no files: `levix --help` does not create config, data or log paths. | `app.build_context` docstring and the eager `--help` option | `tests/test_router.py::test_help_forwarding_does_not_import_a_heavy_dependency` (child interpreter) |
| FR-21 | A root-level alias IS the command it names: `router._attach` prepends the canonical subcommand, so `levix q hello` arrives as `levix ai ask hello` and `levix q -h` prints that command's own page with `prog_name` "levix ai ask". | `router.register_modules` alias loop, `router._attach` (`prefix`), `router._forward` | `tests/test_router.py::test_a_command_alias_reaches_the_command_it_names`, `::test_the_alias_help_shows_the_page_of_the_command_it_aliases`, `::test_the_alias_is_listed_with_the_help_the_manifest_declares` |

## C. Errors and exit codes

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-22 | One documented exit-code table: 0 success, 1 runtime, 2 usage, 3 missing dependency, 4 unknown module, 5 config, 6 cancelled, 7 external tool, 8 provider, 130 interrupted. | `src/levix/errors.py` (`EXIT_CODE_MEANINGS`) | exit-code-named tests listed in FR-23 to FR-29 |
| FR-23 | A missing optional dependency or extra exits 3 and prints the pip line that fixes it. | `errors.DependencyError`, `deps.ensure_dependencies` | `tests/modules/test_files.py::test_module_help_does_not_import_the_heavy_optional_dependencies`, `tests/test_deps.py` (17 functions, 20 cases) |
| FR-24 | An unknown command exits 4 and lists the available module names. | `main._classify`, `_show_alternatives` | `tests/modules/test_files.py::test_unknown_command_is_a_reported_error_not_a_crash`; observed exit 4 for `levix nosuch` and `levix plugins info nosuch` |
| FR-25 | Invalid configuration — bad key, bad value, unreadable TOML, unknown path name — exits 5. | `errors.ConfigError`, `config.Spec.coerce` | `tests/test_config.py` (20 functions, 23 cases), `tests/modules/test_music.py::test_a_bad_volume_flag_exits_five` |
| FR-26 | A refused confirmation exits 6. | `errors.UserCancelledError`, `approve.require_approval` | `tests/modules/test_files.py::test_delete_refuses_without_a_terminal_and_removes_nothing` |
| FR-27 | An external tool that ran and failed, or that LEVIX needs but cannot find, exits 7. | `errors.ExternalToolError`, `tube.core.ensure_ffmpeg`, `music/core.py BackendError` | `tests/modules/test_music.py::test_play_of_an_undecodable_file_exits_seven`, `::test_an_undecodable_file_names_the_decoder_and_exits_seven` |
| FR-28 | A network or model-provider failure exits 8. | `errors.ProviderError`, `commands/update_cmd.py`, `modules/ai/core.py` | `tests/modules/test_ai.py::test_non_2xx_maps_to_provider_error`, `::test_timeout_maps_to_provider_error` |
| FR-29 | Ctrl+C exits 130, whether raised as `KeyboardInterrupt` or swallowed by click's `Abort`. | `main._classify` | `tests/modules/test_music.py::test_ctrl_c_during_playback_exits_130_and_says_the_device_is_free` |
| FR-30 | Click exceptions are recognised even though Typer 0.27.3 raises its own vendored click classes: matching is by MRO class name. | `main._classify` (`names = {klass.__name__ …}`) | `tests/test_router.py` forwarding tests; FR-24 observation |
| FR-31 | An unforeseen exception prints "unexpected error", the traceback tail (last 1500 characters), logs it with `exc_info`, and exits 1. | `main._report_unexpected` | unverified as a named test |

## D. Configuration

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-32 | Values resolve in layers: packaged defaults → user `config.toml` → `LEVIX_<SECTION>_<KEY>` → flags, and the winning layer is reported as `default`, `user` or `env`. | `src/levix/config.py` (`Config.load`, `ResolvedValue`), `src/levix/data/defaults.toml` | `tests/test_config.py` (20 functions, 23 cases) |
| FR-33 | The schema is a hand-maintained table of 9 sections and 23 keys (the module docstring rounds this to "about thirty") with kinds, ranges and choices; an unknown section or key is an error, not a silent ignore. | `config.SCHEMA`, `Config.load` | `tests/test_config.py` |
| FR-34 | Every schema key must exist in the packaged defaults file; a missing default is an error naming the key. | `config.Config.load` | `tests/test_config.py` |
| FR-35 | Type coercion accepts the shapes TOML and environment variables actually produce, including `yes`/`no`/`1`/`0` for booleans, and reports the offending value. | `config.Spec.coerce` | `tests/test_config.py`, `tests/modules/test_music.py::test_volume_accepts_the_ways_a_config_value_arrives` |
| FR-36 | `levix config show` prints key, value, source and file; `list [SECTION]` prints `key=value` lines safe to pipe. | `commands/config_cmd.py` | `tests/test_config.py` |
| FR-37 | `config set` persists one override while preserving the user's comments and ordering; `unset` removes only that override. | `config.write_user_value`, `remove_user_value` (tomlkit) | `tests/test_config.py` |
| FR-38 | A key whose last component contains `key`, `token`, `secret` or `password` is refused by `config set` and masked in `show`/`list` as `set, hidden` — deliberately without brackets, because the mask lands in a Rich table cell where `[set, hidden]` would parse as a style tag and vanish. The refusal names the env var and `levix ai key set`, both of which exist. | `config.is_secret_key`, `commands/config_cmd.py` (`_MASK`, 25-28) | `tests/test_config.py::test_config_set_refuses_a_key_that_looks_like_a_credential`, `::test_the_refusal_names_the_environment_variable_for_that_key`, `::test_no_declared_key_is_secret_shaped`, `tests/test_markup_safety.py` (the mask is markup-free) |
| FR-39 | `config reset` keeps a `config.toml.bak` copy and demands the typed word `DELETE`. `--yes` is accepted but cannot authorise the deletion — it is passed to `require_approval(..., destructive=True)`, which prompts anyway and says why. | `commands/config_cmd.py::reset` (`require_approval(..., destructive=True)`) | `tests/test_config.py::test_reset_yes_cannot_delete_a_configuration_without_a_typed_word`, `::test_reset_without_a_configuration_says_so_and_exits_zero` |
| FR-40 | `config path [config|file|data|cache|state|log|database]` prints a resolved directory or file; an unknown name exits 5. | `commands/config_cmd.py::path` | `tests/test_config.py` |
| FR-41 | `config edit` creates a commented stub if the file is missing and opens `$EDITOR`/`$VISUAL`, defaulting to `notepad` on Windows and `vi` elsewhere, with an argument list and no shell. | `commands/config_cmd.py::edit` | unverified as a named test |
| FR-42 | A module that cannot read a configuration value falls back to its documented default rather than failing the user's command. | `modules/tube/cli.py::_configured`, `dashboard/app.py::_value` | `tests/modules/test_tube.py` config-precedence tests |

## E. Storage and command history

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-43 | One SQLite file (`levix.db` under the data directory) serves the core and every module. | `src/levix/paths.py` (`Paths.database`), `src/levix/storage.py` | `tests/test_storage.py` (10 tests) |
| FR-44 | Connections are short-lived and open WAL, `busy_timeout=5000` and foreign keys, because the dashboard and a suspended module are two processes on one file. | `storage.Database.connect` | `tests/test_storage.py` |
| FR-45 | Migrations are Python callables registered per namespace in `storage.MIGRATIONS`, applied idempotently and recorded in `_levix_schema` so `doctor` can say what was applied. | `storage.apply_migrations`, `SCHEMA_TABLE` | `tests/test_storage.py` |
| FR-46 | Modules with no packaged tables fill their reserved empty namespace at runtime (`arcade/scores.py`, `music/core.py`). | `src/levix/modules/arcade/scores.py:72`, `src/levix/modules/music/core.py:1026-1028` | `tests/modules/test_arcade.py::test_scores_sort_highest_first_and_newest_first_inside_a_tie`, music playlist tests |
| FR-47 | Every command invocation is logged best-effort: argv, module, exit code, duration, UTC timestamp; a logging failure never changes the user's exit code. | `main._record`, `storage.log_command` | `tests/test_storage.py`, `tests/test_router.py:220` |
| FR-48 | Rows whose first token starts with `-` are not recorded, so flag-only invocations do not pollute history. | `main._record` | `tests/test_storage.py` |
| FR-49 | History is pruned to `general.history_limit` (default 50, range 0-10000) after each write. | `main._record`, `storage.prune_history`, `defaults.toml` | `tests/test_storage.py` |
| FR-50 | `levix doctor --vacuum` compacts the shared database and reports the path. | `commands/doctor_cmd.py`, `storage.vacuum` | unverified as a named test |

## F. Secrets

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-51 | Secret lookup order is `LEVIX_<NAME>` → OS keyring (service `levix`) → owner-only file `secrets.json`; the source is returned with the value. | `src/levix/secrets.py` (`get_secret`) | `tests/modules/test_ai.py::test_key_from_the_environment_wins`, `::test_key_from_the_keyring_when_env_is_silent`, `::test_key_from_the_owner_only_file_when_no_keyring`; the file's own permissions are `tests/test_secrets.py` (the Windows ACL case runs here, the three POSIX mode cases skip here) |
| FR-52 | Config files are never consulted for secrets, and the AI module prints only the key's source. | `config.is_secret_key`, `secrets.py` docstring, `modules/ai/cli.py::check` | `tests/modules/test_ai.py::test_no_key_anywhere_reports_none` |
| FR-53 | Writing a secret prefers the keyring and removes any stale file copy. | `secrets.set_secret` | `tests/modules/test_ai.py` (keyring-path tests) |
| FR-54 | The fallback file is hardened on every write: `chmod 0600` plus, on Windows, `icacls /inheritance:r /grant:r <user>:F`. | `secrets._harden` | `tests/modules/test_ai.py::test_key_set_falls_back_to_the_owner_only_file` (the Windows `icacls` argument list runs), `tests/test_secrets.py` (the real `icacls` output here, and the three `st_mode == 0o600` cases that ran on Ubuntu and macOS in CI run #6 after skipping on Windows) |
| FR-55 | `LEVIX_DISABLE_FILE_SECRETS=1` refuses the plaintext store outright and says to use the environment variable instead. | `secrets.backend`, `secrets.set_secret` | `tests/modules/test_ai.py::test_key_set_with_the_file_store_disabled_is_a_dependency_error` (with no keyring, the refusal exits 3, names `levix[secrets]` and does not echo the value) |
| FR-56 | `doctor` reports the plaintext-file fallback as `degraded`, never as success, with `pip install "levix[secrets]"` as the remedy. | `doctor.environment` | `tests/test_doctor.py::test_the_full_report_carries_all_three_areas` pins the report's areas, not this branch; on this machine the keyring answers, so `secrets` reads `ok | OS keyring (backend probe failed; falls back per call)` in `levix doctor --json` |

## G. Dependency gate and capability probes

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-57 | Availability is answered by one oracle using `importlib.util.find_spec`, so checking never imports the module being checked. | `src/levix/deps.py` (`check`) | `tests/test_deps.py::test_no_availability_check_imports_the_module_it_probes` |
| FR-58 | `import_name` and `dist_name` are separate because they differ (`yt_dlp` vs `yt-dlp`), and the reported hint uses the distribution name. | `module.PackageRef`, `deps.check`, `_dist_for` | `tests/test_deps.py::test_package_status_describe_for_installed_reads_distribution_not_import_name`, `::test_a_multi_extra_hint_names_one_distribution_not_several` |
| FR-59 | Four availability states exist — installed, missing, too_old, uncertain — and a minimum version is compared with a deliberately tiny numeric-prefix rule, with an unparseable version reported rather than accepted. | `deps.Availability`, `deps._version_tuple` | `tests/test_deps.py` (17 functions, 20 cases) |
| FR-60 | Each module's Typer callback runs the gate before any command body, so `… -h` stays free of heavy imports while a real command exits 3 when its extra is absent. | `modules/*/cli.py::_gate`, `deps.ensure_dependencies` | `tests/modules/test_tube.py::test_tube_help_never_imports_yt_dlp` |
| FR-61 | Capability probes are separate from package probes: an installed package can still be unusable, and `UNSUPPORTED` is a permitted answer. | `src/levix/capabilities.py` (`Status`, `probe`, `report`) | `tests/modules/test_hacker.py`, observed in `levix monitor overview` ("unsupported - psutil exposes no GPU API") |
| FR-62 | A probe that raises is reported as `degraded` with the exception name; probes never take the CLI down. | `capabilities.probe` | unverified as a named test |
| FR-63 | Probes are memoised per `LevixContext` so one command run does not re-run `shutil.which` repeatedly. | `src/levix/context.py` (`_probe_cache`, `probe`) | unverified as a named test |

## H. Terminal output and logging

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-64 | Glyphs come from `terminal.active_glyphs()`, which returns an ASCII set when the stream cannot carry Unicode, because the Windows cp1252 writer raises on `U+2588`. | `src/levix/terminal.py` (`glyphs`, `bar`, `active_glyphs`) | `tests/test_terminal.py` (15 functions, 19 cases); observed ASCII bars in `levix monitor overview` when piped |
| FR-65 | Colour is disabled by `NO_COLOR`, `LEVIX_NO_COLOR=1`, `TERM=dumb` or a non-TTY stdout. | `terminal.detect` | `tests/test_terminal.py`, `tests/conftest.py` (`NO_COLOR=1`) |
| FR-66 | On Windows, ANSI is only emitted after `ENABLE_VIRTUAL_TERMINAL_PROCESSING` (0x0004) has been set through `GetConsoleMode`/`SetConsoleMode`; failure degrades instead of raising. | `terminal._windows_vt_enabled` | `tests/test_terminal.py` (unit-level) |
| FR-67 | Anything dynamic that came from outside — a URL, file name, model reply, remote title, OS interface name — is markup-escaped and encoding-adapted before printing. The two helpers are `terminal.markup_safe` (brackets) and `terminal.encode_safe` (codepage), composed at each render site: `main._plain`, `tube/cli.py::_show`, `files/cli.py::show`, `systempulse/cli.py::_network_table` and every cell builder there, `hacker/cli.py`, the dashboard (`app.py`, `module_list.py`, `history.py`), `doctor_cmd`, `plugins_cmd`, `config_cmd`, `create_module_cmd`. | `src/levix/terminal.py` (`markup_safe`, `encode_safe`) | `tests/test_markup_safety.py` (9 functions: the renderer round-trip, an unbalanced tag raises, the config mask, doctor/plugin/dashboard/history surfaces), `tests/modules/test_files.py::test_printable_survives_a_name_the_console_cannot_encode`, `::test_preview_survives_a_name_the_console_cannot_encode`, `tests/modules/test_systempulse.py::test_an_interface_name_with_brackets_is_still_shown` |
| FR-68 | Logs go to a rotating file (`levix.log`, 512 KB × 3 backups) and never to stdout; only when no file handler could be opened does a WARNING stream handler (stderr) appear. | `src/levix/logging_setup.py` | `tests/test_logging.py::test_a_key_never_reaches_the_log_file` (a real `levix.log` is written and read back), `::test_the_only_console_handler_writes_to_stderr` |
| FR-69 | Redaction is a filter on the logger itself, so it cannot be bypassed by a module that logs a formatted exception: bearer headers, `sk-…`, `ghp_`/`gho_`/`github_pat_…` and `*key\|token\|secret\|password=…` pairs are replaced. | `logging_setup.RedactFilter` | `tests/test_logging.py` (6 functions, 11 cases) — the shapes, a real `LogRecord`, the file, and an unfiltered handler added afterwards. A credential in a shape the four patterns do not name is still logged verbatim (`NON_FUNCTIONAL_REQUIREMENTS.md` Known gaps) |
| FR-70 | When stdout is redirected, interactive surfaces refuse instead of drawing: `dashboard` exits 2, `files browse` exits 1 and both name a pipe-friendly alternative. | `commands/dashboard_cmd.py`, `modules/files/browse.py::run_browse` | `tests/test_dashboard.py::test_dashboard_refuses_a_redirected_terminal_with_the_usage_code`, `tests/modules/test_files.py::test_browse_help_does_not_start_a_screen` |
| FR-71 | Long-running animation in a captured stream is bounded, not endless: `hacker matrix` without `--iterations`/`--duration` on a non-TTY is a usage error (exit 2). | `modules/hacker/cli.py` | `tests/modules/test_hacker.py::test_matrix_needs_a_bound_when_stdout_is_captured`, `::test_matrix_stops_at_the_frame_limit`, `::test_matrix_stops_at_the_time_limit`, `::test_matrix_seed_repeats_a_run` |

## I. Confirmation of destructive actions

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-72 | One shared gate exists for all destructive or externally influenced actions. | `src/levix/approve.py` (`require_approval`) | `tests/modules/test_files.py::test_delete_yes_cannot_authorize_a_deletion` |
| FR-73 | A destructive action must be typed: `DELETE` by default, `OVERWRITE` for copy/move/rename collisions, `RUN` for an AI-proposed command. | `approve.require_approval` (`prompt_word`), `modules/files/cli.py::_confirm_overwrite`, `modules/ai/cli.py`, `modules/arcade/cli.py:345` | `tests/modules/test_arcade.py::test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it`, `tests/modules/test_ai.py::test_command_yes_cannot_authorize_a_run` |
| FR-74 | `--yes` never authorises a destructive action; it prints why and prompts anyway. | `approve.require_approval` (`destructive and assume_yes`) | `tests/modules/test_ai.py::test_command_yes_cannot_authorize_a_run`, `tests/modules/test_files.py::test_copy_with_force_still_needs_a_terminal` |
| FR-75 | A stdin that is not a terminal is a refusal (exit 6), not consent. | `approve.require_approval` | `tests/modules/test_files.py::test_delete_refuses_without_a_terminal_and_removes_nothing`, `tests/modules/test_ai.py::test_command_with_run_refuses_without_a_terminal` |
| FR-76 | `files delete` prints the plan (what and how much) before asking, and `--force` on copy/move/rename only permits a collision, never a silent replacement. | `modules/files/cli.py::delete`, `_confirm_overwrite` | `tests/modules/test_files.py` |
| FR-77 | `create-module --force` requires the typed confirmation before `shutil.rmtree` on an existing non-empty scaffold. | `commands/create_module_cmd.py` | `tests/test_create_module.py::test_force_without_a_terminal_refuses_and_deletes_nothing` (exit 6, the marker file and the `pyproject.toml` both still there) and `::test_an_existing_project_is_never_overwritten_unasked` (exit 5 without `--force`) |

## J. Dashboard

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-78 | The dashboard lists every registered module built from manifests only, with three distinct states: ready, needs install, broken — and no row at all for a module that declares `UiSpec(mode="hidden")`. | `src/levix/dashboard/module_list.py` (`STATE_MARK`, `row_for`, `build_rows`) | `tests/test_dashboard.py::test_rows_carry_the_state_that_the_gate_actually_reports`, `::test_a_needs_install_row_names_the_extra_to_install`, `::test_a_module_hidden_from_the_dashboard_gets_no_row`, `::test_a_hidden_module_reaches_no_widget_the_app_builds`, `::test_no_official_module_hides_itself_from_the_dashboard` |
| FR-79 | A needs-install row embeds the actionable pip line; a broken row embeds the load failure. They are never merged into one word. | `module_list.row_for`, `dashboard/app.py::_why_not` | `tests/test_dashboard.py::test_a_plugin_that_names_no_provider_does_not_invent_a_pip_line` |
| FR-80 | Typing narrows the list over name, title and summary, case-insensitively. | `module_list.filter_rows`, `LevixDashboard.on_input_changed` | `tests/test_dashboard.py::test_filtering_matches_name_title_and_summary` |
| FR-81 | Launching a module suspends the dashboard and re-enters `levix …` in a child process, so exactly one Textual app owns the terminal. | `dashboard/app.py::_run` (`with self.suspend(): spawn.run(*argv)`), `src/levix/spawn.py` | `tests/test_dashboard.py::test_enter_on_a_ready_row_runs_the_same_command_line` |
| FR-82 | The launched argv is the manifest's declared `ui.argv`, else `<name> -h`. | `dashboard/app.py::_argv_for` | `tests/test_dashboard.py::test_launching_the_declared_argv_runs_that_command_line`, `::test_a_module_that_declares_no_argv_opens_its_help` |
| FR-83 | Unavailable rows refuse to launch and say why. | `LevixDashboard.action_launch`, `_why_not` | `tests/test_dashboard.py::test_enter_on_an_unavailable_row_says_why_instead_of_running_it` |
| FR-84 | Bindings: enter launch, space details, f filter, r reload, t theme, h history, q quit, escape clear-or-quit, ctrl+c quit. | `LevixDashboard.BINDINGS` | `tests/test_dashboard.py::test_theme_binding_cycles_only_through_registered_themes`, `::test_history_can_be_hidden_without_touching_the_log` |
| FR-85 | Reload installs a fresh registry rather than re-asking the cached one, so a package installed in another shell appears. | `LevixDashboard.action_reload`, `registry.use` | `tests/test_dashboard.py::test_dashboard_lists_every_module_and_reflects_the_filter` |
| FR-86 | The history panel shows the last `dashboard.recent_commands` (default 10) rows and colour-codes exit codes: 0 green; 2, 3, 4, 5, 6, 130 yellow; anything else red. | `src/levix/dashboard/history.py`, `app.py::refresh_history` | `tests/test_dashboard.py::test_history_panel_shows_the_commands_that_were_logged` |
| FR-87 | Three themes are registered (`levix-dark`, `levix-green`, `levix-light`); an unknown configured name is reported to the user rather than silently ignored. | `src/levix/dashboard/theme.py` (`THEMES`, `ALIASES`, `apply`) | `tests/test_dashboard.py::test_theme_binding_cycles_only_through_registered_themes` |
| FR-88 | Detail panel shows title, summary, command list, packages, permissions and the declared doc path. | `dashboard/app.py::_describe` | `tests/test_dashboard.py::test_rows_render_as_list_items` |

## K. Platform command behaviour

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-89 | `levix plugins list [--origin all|official|third-party]` is a table of name, origin, version, commands and readiness; the option value is normalised (`third-party` → `third_party`). | `commands/plugins_cmd.py::list_plugins` | observed: seven official modules at 0.4.0, state ready |
| FR-90 | `levix plugins info NAME` prints origin, provider, cli entry, dashboard mode, docs path, permissions, per-requirement verdicts and the install hint; an unknown name exits 4. | `commands/plugins_cmd.py::info` | `tests/test_dashboard.py::test_a_manifest_with_no_uispec_is_disclosed_as_offered_by_default`, `tests/test_plugin_example.py::test_the_hidden_example_is_discovered_but_gets_no_dashboard_row` (asserts `dashboard : hidden` for the real example); observed exit 4 |
| FR-91 | `doctor` reports areas `paths`, `config`, `storage`, `secrets`, `module:<name>` and `capability:<name>`, each with a status word and a remedy. | `src/levix/doctor.py`, `commands/doctor_cmd.py` | `tests/test_doctor.py::test_the_full_report_carries_all_three_areas`, `tests/test_deps.py`, `tests/test_storage.py` cover the underlying data |
| FR-92 | `doctor` exits 3 only when a module reports `missing`; degraded and unsupported findings, including missing capabilities, exit 0. | `doctor.exit_code_for`, `Finding.worst` | observed on this machine: verdict `degraded` (temperature probe fails, GPU `unsupported`, stdout not a TTY) with exit 0; every module and the ffmpeg/media_player/audio_output/psutil/keyring capabilities report `ok` |
| FR-93 | `doctor --json` emits `{verdict, findings[]}` (each finding is `area`, `status`, `detail`, `hint`) and raises the same exit code; `--only` restricts the report to `env`, `modules` or `capabilities` and the verdict is computed from the rows actually shown. | `commands/doctor_cmd.py` (filter at 43-54) | `tests/test_doctor.py` (6 functions: the full three-area report, each `--only` slice, an unknown area is a config error, a filtered report states its own verdict) |
| FR-94 | `levix update` reads `https://pypi.org/pypi/levix/json`, states whether the installed version is current, and prints `pip install --upgrade levix`, `pipx upgrade levix` and the standalone instruction. It never modifies the installation. | `commands/update_cmd.py` | `tests/test_update.py` (10 functions against a replaced `urlopen`, no socket opened): the newer release is named, an equal version counts as current, `--json` carries both versions, and the request's URL, user agent, `Accept` and timeout are asserted |
| FR-95 | An unreachable or malformed PyPI response exits 8 and says the failure is a network limitation, not evidence of being up to date. `--timeout` is accepted in 1-60 seconds (default 6.0). | `commands/update_cmd.py` | `tests/test_update.py::test_a_pypi_http_status_is_a_provider_failure_not_a_quiet_zero` (503 → exit 8, the status on the screen, and no "latest release" wording), `::test_no_response_is_reported_as_a_limitation_and_not_as_being_up_to_date`, `::test_the_json_answer_still_reports_the_failure`, `::test_a_response_without_a_version_is_an_error_rather_than_a_guess`, `::test_an_absurd_timeout_is_refused_before_any_request` (0.5 and 600 → exit 2, and the fake transport records that no request was made) |
| FR-96 | `levix create-module NAME` requires 2-30 characters of `[a-z0-9_-]` starting with a letter, and exits 5 otherwise. | `commands/create_module_cmd.py` (`_NAME_RE`) | `tests/test_create_module.py::test_a_name_that_is_not_a_module_id_is_refused_and_creates_nothing` (5 parametrised names: `Weather`, `w`, `has space`, `9lives`, 31 characters - exit 5 and no directory created) |
| FR-97 | The scaffold is the same shape the official modules use: `levix-<name>` distribution, `levix_<name>` package, `levix.plugins` entry point to `MANIFEST`, `cli.py:build_app` deferred, `dependencies = ["levix>=0.4"]`, README and a manifest test. | `create_module_cmd._template` | `tests/test_create_module.py` - the generator runs into a temp dir, the result is registered through a hand-built `dist-info` and loaded by the real `ModuleRegistry` (`Origin.THIRD_PARTY`, `provider == "levix-weather"`, `permissions` holding real `Permission` members), driven through the real router, read by `levix plugins info`, proven not to import `cli` at manifest time, and its own generated `pytest` suite is executed in a child interpreter |

## L. Module behaviour

### monitor (SystemPulse)

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-98 | Seven read-only commands: overview, cpu, memory, disk, network, processes, live. The manifest declares `fs_read` only — nothing here writes or reaches the network. | `modules/systempulse/cli.py`, `modules/systempulse/__init__.py` | `tests/modules/test_systempulse.py` (40 functions / 46 collected): `::test_monitor_commands_run_and_exit_zero` drives all six non-`live` commands through the real CLI, `::test_the_live_view_terminates_on_its_own` bounds `live`, `::test_the_manifest_claims_only_disk_reads` |
| FR-99 | psutil is imported only inside `core`, reached from command bodies. | `modules/systempulse/cli.py` docstring, `core.py` (`import psutil` inside each function) | `tests/test_router.py` heavy-import invariant (`psutil` in `HEAVY`); the per-function import is what lets `tests/modules/test_systempulse.py` put a stand-in module in `sys.modules` and still exercise the real import site, while the `run_cli` tests at the bottom of that file run against real psutil |
| FR-100 | Where the OS exposes no sensor, the row says "unsupported here - no sensors exposed through psutil" or "not reported by this platform"; LEVIX never prints a invented zero. | `modules/systempulse/cli.py:85,96,98,119`, `capabilities.py` | observed: `temp` and `gpu` rows in `levix monitor overview` |

### hacker

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-101 | Three commands, all read-only: matrix, info, network; core uses the standard library only. | `modules/hacker/cli.py`, `modules/hacker/core.py` | `tests/modules/test_hacker.py::test_importing_the_module_package_pulls_in_no_heavy_dependency`, `::test_help_lists_all_three_commands` |
| FR-102 | Matrix rain is reproducible under `--seed` and configurable within `hacker.matrix_fps` (1-120) and `hacker.matrix_density` (0.001-0.5). | `hacker/core.py` (`MatrixScene`), `cli.py` | `tests/modules/test_hacker.py::test_seeded_scene_repeats_every_frame_exactly`, `::test_matrix_seed_repeats_a_run` |
| FR-103 | Network tables say where each value came from and run only OS reporting tools with an argument list, never a shell. | `hacker/cli.py:404,495`, `hacker/core.py::run_tool` (`shell=False`) | `tests/modules/test_hacker.py::test_route_print_on_link_rows_are_not_reported_as_gateways` |

### files

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-104 | A `--root` wall confines resolution, copy, move and delete; escaping it is an `UnsafePathError` (exit 2). | `modules/files/core.py` (`UnsafePathError`), `cli.py` | `tests/modules/test_files.py` (121 functions, 147 cases) |
| FR-105 | Search offers name, extension and content modes with a 2 MiB default per-file cap, an 8 KiB sniff and a 256 KiB head budget. | `files/core.py` (`SNIFF_BYTES`, `HEAD_BUDGET`, `DEFAULT_GREP_MAX_BYTES`) | `tests/modules/test_files.py::test_grep_unreadable_file_is_reported_not_fatal` |
| FR-106 | Text decoding chains UTF-8 then cp1252 and labels a lossy Latin-1 fallback instead of pretending it was clean. | `files/core.py` (`ENCODING_CHAIN`) | `tests/modules/test_files.py::test_decode_chain_prefers_utf8_then_cp1252_then_labels_latin1_lossy` |
| FR-107 | A missing file in `preview` exits 2; an unreadable one during a search is reported and the run continues. | `files/cli.py`, `files/core.py` | `tests/modules/test_files.py::test_preview_of_a_missing_file_exits_two` |

### tube

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-108 | `info`, `download` and `play` are the whole surface; yt-dlp is reached only through one seam, `_make_ydl`. | `modules/tube/cli.py`, `modules/tube/core.py` | `tests/modules/test_tube.py::test_a_leaving_of_the_seam_is_the_only_import_site` |
| FR-109 | Named formats expand to real selectors: with ffmpeg `best`/`video` → `bv*+ba/b`, `audio` → `ba/b`; without ffmpeg they fall back to single-file selectors and say so. An explicit selector is never rewritten. | `tube/core.py` (`ALIASES_WITH_FFMPEG`, `ALIASES_SINGLE_FILE`, `plan_format`) | `tests/modules/test_tube.py::test_the_gate_refuses_and_names_the_command_that_would_fix_it`, `::test_an_explicit_selector_is_never_quietly_rewritten` |
| FR-110 | A request that needs ffmpeg while ffmpeg is absent exits 7 and prints the install command for this platform (`winget install Gyan.FFmpeg`, `brew install ffmpeg`, fallback `sudo apt install ffmpeg`). | `tube/core.py::ensure_ffmpeg`, `FFMPEG_INSTALL_COMMANDS` | `tests/modules/test_tube.py::test_the_install_advice_is_the_one_for_this_platform` |
| FR-111 | Play hands a stream URL to a player found on PATH as an argument list with `shell=False`; nothing is written to disk. No player found exits 7 and lists every name tried. | `tube/core.py::find_player`, `player_command`, `launch`, `tube/cli.py::play` | `tests/modules/test_tube.py::test_a_player_is_handed_an_argument_list_not_a_shell_string`, `::test_a_player_that_cannot_be_started_is_an_external_tool_failure` |
| FR-112 | Downloads never overwrite an existing file and say so; `file://` URLs stay disabled until `--allow-file-url`; playlists are one entry at a time unless `--playlist` opts in, which prints the rate-limit warning. | `tube/cli.py`, `tube/core.py` | `tests/modules/test_tube.py::test_existing_files_are_never_overwritten`, `::test_file_urls_stay_disabled_until_they_are_explicitly_allowed`, `::test_opting_into_a_playlist_turns_the_guard_off_and_warns_loudly` |
| FR-113 | No request asks for credentials or cookies, and there is no DRM or download-protection bypass. | `modules/tube/core.py` | `tests/modules/test_tube.py::test_no_request_ever_asks_for_credentials_or_cookies` |
| FR-114 | A field the site does not report prints "not reported" instead of a blank or a zero. | `tube/cli.py::_media_table`, `core.human_bytes` | `tests/modules/test_tube.py::test_summary_reports_a_field_the_site_did_not_provide_as_unknown` |

### game (Arcade)

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-115 | Snake and Tetris run in Textual screens with scores in the shared database; `scores` works without a terminal. | `modules/arcade/screens.py`, `modules/arcade/scores.py`, `arcade/cli.py` | `tests/modules/test_arcade.py::test_scores_on_an_empty_profile_says_so`, `::test_the_screen_is_not_imported_by_help_or_scores` |
| FR-116 | Board sizes and auto-play steps are capped (120×60, `--auto` ≤ 100000) and refusals name the cap. | `arcade/cli.py` (`MAX_COLS`, `MAX_ROWS`, `MAX_AUTO`, `_auto_steps`) | `tests/modules/test_arcade.py` |
| FR-117 | `--seed` replays identical food placement; an unpinned run still records the seed it used. | `arcade/cli.py`, `arcade/snake.py` | `tests/modules/test_arcade.py::test_an_auto_game_is_reproducible_and_an_unpinned_one_still_records_its_seed`, `::test_the_same_seed_places_the_same_food_and_a_different_seed_does_not` |
| FR-118 | Clearing scores requires the typed word `DELETE`; `--yes` cannot supply it. | `arcade/cli.py:345` | `tests/modules/test_arcade.py::test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it` |

### music

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-119 | Play, info, devices, library and playlist exist; every container the library scan offers - WAV, FLAC, OGG (Vorbis and Opus), MP3, AIFF under both `.aiff` and `.aif`, and AU - decodes through soundfile/libsndfile with no ffmpeg in the file path. | `modules/music/cli.py`, `music/core.py` | `tests/modules/test_music.py` (104 functions, 155 cases), incl. `::test_every_container_the_scan_offers_decodes_here` and `::test_the_container_table_is_the_scan_suffixes` |
| FR-120 | `sounddevice`/`soundfile` are imported only via `core`, so `levix music -h` costs no PortAudio. | `modules/music/cli.py` docstring | `tests/modules/test_music.py` manifest-import test |
| FR-121 | Volume is a 0.0-1.0 config value; a bad value is exit 5 with the exact `levix config set music.volume 0.8` or `--volume 0.8` remedy, and an undecodable file is exit 7 naming the decoder. | `music/core.py` (`ConfigError`, `BackendError`), `defaults.toml` | `tests/modules/test_music.py::test_a_bad_volume_flag_exits_five`, `::test_play_of_an_undecodable_file_exits_seven` |
| FR-122 | An empty `music.library_dir` is an exit-5 configuration error that names both the config key and the `--root` flag. | `music/core.py:930-932` | `tests/modules/test_music.py` library tests |
| FR-123 | Playlists live in the shared database and are managed by `list`, `add`, `remove`, `clear`, `play`. | `modules/music/cli.py` (`playlist_app`), `music/core.py` | `tests/modules/test_music.py` playlist tests |

### music: streaming and the visualiser

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-135 | `levix music play SOURCE` accepts an `http`/`https` URL as well as a path. The URL is fetched through yt-dlp as audio-only and converted to MP3 by ffmpeg before libsndfile sees it, because libsndfile refuses the container the stream arrives in. Missing `yt_dlp` or `ffmpeg` is exit 3 naming what to install; any other scheme is exit 2, judged before either tool is looked for. | `music/core.py` (`is_url`, `fetch_audio`, `_stream_options`), `modules/music/cli.py::play` | `tests/modules/test_music.py::test_what_counts_as_a_link`, `::test_a_link_is_fetched_into_the_cache_and_played`, `::test_a_refused_scheme_is_refused_before_anything_is_looked_for`, `::test_a_url_without_ffmpeg_refuses_with_the_dependency_code`, `::test_a_url_without_yt_dlp_names_the_extra_it_comes_from` |
| FR-136 | No text the remote side chose becomes a path on this disk. The cache directory is `sha256(url)`-derived, yt-dlp is told to write a fixed `audio.%(ext)s` name inside it, the path it reports is refused unless it lives in that directory, and a second play of the same URL performs no fetch at all. `noplaylist` is always set. | `music/core.py` (`stream_dir`, `fetch_audio`) | `tests/modules/test_music.py::test_the_cache_folder_is_the_url_and_not_anything_a_server_chose`, `::test_playing_the_same_link_twice_never_reaches_the_network`, `::test_a_reported_path_outside_the_url_folder_is_not_opened`, `::test_the_ask_is_audio_only_one_item_and_never_a_file_url`, `::test_a_file_url_cannot_make_this_process_read_a_file` |
| FR-137 | `--visual bar` draws log-spaced spectrum bars from the frames at the playhead, through the same `on_block` report the progress line already used; the band math, peak-hold caps and redraw gate are pure functions with no device, terminal or Rich in them. Glyphs come from `terminal.active_glyphs()`. The default follows `music.visual`; off a TTY the default quietly keeps the progress line and an explicit `--visual bar` is exit 2 naming `--visual off`. | `music/visual.py`, `modules/music/cli.py` (`_visual_for`, `_Spectrum`), `config.SCHEMA` (`music.visual`) | `tests/modules/test_music.py::test_a_tone_lights_the_band_that_contains_it`, `::test_silence_sits_on_the_floor_and_full_scale_on_the_top`, `::test_a_peak_holds_and_then_decays_toward_the_current_level`, `::test_the_redraw_is_gated_to_the_frame_budget`, `::test_an_explicit_visual_on_a_piped_stdout_exits_two`, `::test_visual_off_keeps_the_one_line_progress` |
| FR-138 | A fetch is bounded and speaks with one voice. `STREAM_MAX_BYTES` (134,217,728) goes to yt-dlp as `max_filesize` and the file that landed is measured against the same number before anything decodes it - over the cap, or a reported path outside the URL's own folder, is exit 7 and nothing is opened. yt-dlp's own output is routed to a silent logger, so a failed fetch is the one mapped message this module prints, at exit 8. | `music/core.py` (`fetch_audio`, `_reported_path`, `_refuse_oversize`, `_QuietLogger`, `_run`) | `tests/modules/test_music.py::test_a_stream_over_the_byte_cap_is_refused_before_it_is_decoded`, `::test_yt_dlp_failing_becomes_one_clean_message`, `::test_a_fetch_that_reports_no_path_is_a_provider_error`, `::test_the_logger_yt_dlp_writes_to_says_nothing` |
| FR-139 | The URL never shadows the file: a local path performs no fetch and needs neither yt-dlp nor ffmpeg, `yt_dlp` is imported in exactly one function, and the only announcement of a wait is a download that is really about to happen. | `music/core.py` (`open_source`, `_make_ydl`), `modules/music/cli.py` (`_source`, `_origin`) | `tests/modules/test_music.py::test_a_local_file_never_touches_the_stream_path`, `::test_yt_dlp_is_imported_in_exactly_one_place`, `::test_only_a_link_that_really_downloads_announces_a_wait`, `::test_the_ffmpeg_advice_does_not_drift_from_tubes` |

### ai

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-124 | Six commands: ask (`q`), explain, command (`cmd`), models, check, and `key` — a group with `set` and `clear` — over OpenAI-compatible or Ollama endpoints. `key set` prompts with echoing off; the key is never a command-line argument. | `modules/ai/cli.py` (`key_app`, `_prompt_key`), `ai/core.py` | `tests/modules/test_ai.py::test_openai_chat_request_sends_the_bearer_key_and_sse_accept`, `::test_ollama_streams_through_api_chat`, and the `key` surface itself: `::test_key_set_writes_the_keyring_and_never_prints_the_value`, `::test_key_set_falls_back_to_the_owner_only_file`, `::test_key_set_refuses_an_empty_entry_without_touching_the_store`, `::test_key_set_without_a_terminal_names_the_environment_variable`, `::test_key_clear_removes_what_key_set_wrote`, `::test_key_clear_says_the_environment_still_holds_a_key` |
| FR-125 | The key is looked up as `AI_API_KEY` through env → keyring → file, never read from config, and `check` prints only the source. Loopback and Ollama endpoints are exempt from requiring a key. | `ai/core.py` (`SECRET_NAME`, `resolve_key`), `ai/cli.py::check` | `tests/modules/test_ai.py::test_resolve_key_refuses_a_remote_host_without_a_key`, `::test_no_key_anywhere_reports_none` |
| FR-126 | A proposed command is parsed into an argv of at most one program; pipelines, `;` and redirection are refused before any approval is offered. | `ai/core.py::extract_proposal` | `tests/modules/test_ai.py::test_command_refuses_a_pipeline_proposal_before_any_approval` |
| FR-127 | `--run` executes only after the typed word `RUN`; if `ai.require_approval` is set false the user is warned that LEVIX will run without asking. | `ai/cli.py:308-320` | `tests/modules/test_ai.py::test_command_yes_cannot_authorize_a_run` |
| FR-128 | Provider failures (non-2xx, timeout, malformed body, stream error) are `ProviderError` exit 8 and name the provider and URL, never the key. | `ai/core.py` | `tests/modules/test_ai.py::test_non_2xx_maps_to_provider_error`, `::test_connection_failure_names_the_provider_and_url` |
| FR-129 | `explain` reads a capped prefix of each file (default 32,000 bytes) and says what it left out. | `ai/core.py` (`DEFAULT_MAX_FILE_BYTES`), `ai/cli.py` | `tests/modules/test_ai.py` explain tests |
| FR-130 | `models` prints what the provider reports, or states that the provider reported none (a 404 returns no list rather than an error). | `ai/core.py::fetch_models` | `tests/modules/test_ai.py::test_parse_models_reads_both_shapes` |

## M. Plugin SDK

| ID | Requirement | Where implemented | Verified by |
| --- | --- | --- | --- |
| FR-131 | Plugin authors import from `levix.sdk`, a stable façade with no logic, re-exporting 14 names. | `src/levix/sdk.py` (`__all__`, 29-43) | `tests/test_plugin_example.py::test_the_example_itself_imports_nothing_heavy_at_manifest_time` (the example's `MANIFEST` is built entirely from `levix.sdk` imports), `tests/test_registry.py` (the core contract lives in `levix.module`) |
| FR-132 | There is one contract: a package exporting `MANIFEST` (a `ModuleManifest` instance) plus a `build_app()` callable named by `cli_path`; `registry.build_cli` resolves and calls it. `module.LevixModuleProtocol` was a second, class-shaped contract implemented by nothing — it is deleted, not documented. | `registry.build_cli` (`registry.py:93-96`), `_resolve` (`registry.py:112-117`), all seven `modules/*/__init__.py` | `tests/modules/test_tube.py::test_the_manifest_declares_the_packaged_contract`, `tests/test_plugin_example.py` (drives the hello plugin through its real `MANIFEST` + `cli:build_app` pair) |
| FR-133 | Command parameters are not modelled in the manifest: Typer type hints are the single source of truth, so `CommandInfo` carries only name, help and aliases. | `module.CommandInfo` docstring | `tests/test_registry.py::test_permissions_are_a_closed_disclosure_set` |
| FR-134 | `levix plugins install`, `uninstall` and `publish` do not exist in 0.4.0. | `commands/plugins_cmd.py` docstring | observed: `list` and `info` only |

## Known gaps against these requirements

Requirements the code does not meet as written, or that no test holds:

- FR-94/FR-95: tested now, against a `urlopen` the case replaces. What no test can say is what
  `https://pypi.org/pypi/levix/json` actually answers, because that distribution does not exist
  yet; the hand run reports `PyPI returned 404` and exits 8.
- FR-96/FR-97: closed by `tests/test_create_module.py`, which runs the generator, registers its
  output the way an editable install would and executes it - and found four defects in the
  scaffold on the way (a `permissions` entry that was the *string* `"Permission.FS_READ"` and so
  broke `levix plugins info`, a command body that interpolated the generator-only `{display}` and
  raised `NameError`, a README that told the author to type a `hello` subcommand that Typer does
  not mount, and a generated `tests/test_manifest.py` asserting a private `Typer._name`). What
  remains unproven: no case runs `pip install -e .` on the generated project, and the scaffold's
  `dependencies = ["levix>=0.4"]` is never resolved against a real index.
- The POSIX half of several requirements is still unasserted even though CI runs #4 (`5b047ad`),
  #5 (`75daed2`) and #6 (`3d460df`) are green on Ubuntu and macOS: FR-103 (the `ip addr show`,
  `ifconfig`, `resolv.conf` and `route -n` parsers are
  fed captured POSIX text; the tools themselves are never run), and the keyring backend
  selection under FR-51/FR-53/FR-55. A green column means the POSIX *branches* the tests reach
  do not crash; it does not mean any of the behaviours above was observed.
  FR-54 is no longer in that list: `tests/test_secrets.py` stats the mode of a real
  `secrets.json`, and run #6 executed those three cases on Ubuntu 3.12/3.13 and macOS
  3.12/3.13 - the first POSIX evidence, rather than a Windows skip of a POSIX assertion.
- FR-70/FR-71 bound or refuse when stdout is a pipe, which is how every interactive surface is
  tested here. Real TTY behaviour — the dashboard on a screen, `files browse`, `monitor live`,
  `hacker matrix` animating, playing Snake by key — is exercised only through Textual's Pilot.
- FR-73: the typed words `DELETE`, `OVERWRITE` and `RUN` are asserted through the non-TTY
  refusal, not by a human typing them at a prompt (`approve.py:51-59` has no interactive test).
  FR-118 and FR-127 are the same situation for Arcade and AI.

## Closed since the first draft of this page

Each of these was a real gap and is now either implemented or removed from the requirements:

- FR-68 and FR-69: the logging promises are now run, not read. `tests/test_logging.py`
  (6 functions, 11 cases) sends six credential shapes through `RedactFilter.redact`, formats
  one through a real `LogRecord`, writes a real `levix.log` and reads it back, adds a handler
  with no filter to show the logger-level filter still redacts it, and asserts the fallback
  console handler is a stderr `WARNING` one. File logging stays off for the rest of the suite
  (`tests/conftest.py:38`) because an open handle stops Windows deleting the temporary home;
  this file closes its own handlers for exactly that reason.
- FR-21: aliases no longer forward to the module group. `router._attach` prepends the canonical
  subcommand (`src/levix/router.py:54-58`), so `levix nt via-alias` arrives as
  `levix stub note via-alias`; `levix q hello` works. Held by
  `tests/test_router.py::test_a_command_alias_reaches_the_command_it_names` and
  `::test_the_alias_help_shows_the_page_of_the_command_it_aliases`.
- FR-38: `levix ai key set` / `key clear` exist (`modules/ai/cli.py:519-594`, nine tests in
  `tests/modules/test_ai.py` from `::test_key_set_writes_the_keyring_and_never_prints_the_value`
  to `::test_key_clear_says_the_environment_still_holds_a_key`), so the refusal message now
  points at a command that is there. `ai/core.py:156` and `ai/cli.py:541` both name it.
- FR-39: `config reset --yes` can no longer delete a configuration without a typed word —
  `commands/config_cmd.py:132-137` calls `require_approval(..., destructive=True)`, which
  refuses to let a flag authorise a destructive action. `tests/test_config.py:197` asserts the
  refusal exits 6. The inert `--yes` on `config set` was removed instead of wired up: that
  command never prompts, so accepting the flag promised a behaviour it did not have.
- FR-72/FR-74: the inert `general.confirm_destructive` key is gone from `SCHEMA` and
  `defaults.toml` instead of being plumbed in. `require_approval` is the only gate, by design
  (`src/levix/config.py:86` records why).
- FR-91/FR-92/FR-93: `tests/test_doctor.py` (6 functions) exists, and `--only` really filters —
  `commands/doctor_cmd.py:43-54` applies the prefix it computes. A filtered `--json` verdict is
  computed from the rows actually shown.
- FR-98/FR-99: `tests/modules/test_systempulse.py` exists — 40 functions, 46 collected cases —
  sampling against a psutil stand-in in `sys.modules` and the commands against the real machine.
- FR-134: the `dashboard/app.py::refresh_modules` comment that promised `levix plugins install`
  would become visible now says what actually happens: the registry is re-read, so a plugin
  installed into this environment appears (`src/levix/dashboard/app.py:115`).
- FR-67: the escaping rule was not just documented but closed. OS-sourced values — process
  names, mount points, interface names — go through `terminal.markup_safe` at every render site
  (`tests/test_markup_safety.py`, 9 functions, plus
  `tests/modules/test_systempulse.py::test_an_interface_name_with_brackets_is_still_shown`), and
  the config mask stopped being a Rich style tag.
- FR-131/FR-132: `module.LevixModuleProtocol` is deleted. It declared `manifest()` and
  `build_command()`, raised `NotImplementedError` in both, was exported through `levix.sdk`,
  was implemented by nothing in the tree — including the scaffold its own docstring claimed —
  and was read by no line of the loader. One contract remains (`MANIFEST` + `cli:build_app`),
  and `levix.sdk` now re-exports 14 names instead of 15.
- FR-105 (`files search --max-bytes 0`): `0` means no cap, as the help always claimed;
  a negative value falls back to the packaged default instead of silently capping every file.
  `src/levix/modules/files/cli.py:188`, `tests/modules/test_files.py::test_max_bytes_zero_means_no_cap`.

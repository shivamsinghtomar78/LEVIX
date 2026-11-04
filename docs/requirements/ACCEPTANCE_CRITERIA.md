# LEVIX Acceptance Criteria

Each criterion states behaviour asserted by a named test in `tests/` or observable from a documented command. Exit codes are the table in
`src/levix/errors.py`: 0, 1, 2, 3, 4, 5, 6, 7, 8, 130. The suite holds 580 test functions in 17 files (10 in `tests/`, 7 in `tests/modules/`)
collecting to 698 parametrised cases, 8 marked `integration`; the hand run behind every line below is `693 passed, 5 skipped` (the five skips
are all symlink cases - this Windows account cannot `os.symlink`, and three of them are POSIX-only by design). All of it was measured
on Windows 11 with Python 3.12.10 in an editable `.venv` install; no Linux or macOS run backs any line below. `tests/conftest.py` keeps runs
off a real profile (`LEVIX_*` cleared, `LEVIX_HOME` in a temp directory, `NO_COLOR=1`, file logging disabled at `conftest.py:38`, registry
reset per test) and `run_cli` calls the real entry point `levix.main.main(list(argv))`, so exit codes and history rows are part of what is
asserted. Checks: `python -m pytest -q` (698 collected, 157.55 s, no network, no real TTY - and yes, that includes the 8 `integration` cases,
because `addopts = "-q --strict-markers"` deselects nothing), `python -m pytest -m integration` (those 8 alone: `8/698 tests, 690
deselected`), `python -m ruff check src tests` and `python -m ruff format --check src tests` (both exit 0), `python -m mypy src/levix`
(59 files, no issues), `levix doctor`. Citations: a bare `file.py:line` is under `src/levix/`; `tests/FILE.py` names a test file (module tests are
`tests/modules/FILE.py`) and each identifier after it is one of its test functions.

## A. Installation and lightweight core

**AC-01 — six core packages, no more.** Given `levix` installed without extras, when any command runs, then only `click`, `platformdirs`,
`rich`, `textual`, `tomlkit`, `typer` are required and every heavy package sits in an extra. Check: `pyproject.toml:30-36`, `39-57`;
`levix doctor --json` reports `module:<name>` as `missing` per absent extra.

**AC-02 — both entry points answer before setup work.** Given an installed distribution, when `levix --version`, `levix -V` or
`python -m levix --version` runs, then it prints `levix 0.4.0` and exits 0 without building paths, config or logging; from a checkout with no
distribution it prints `levix 0.0.0+unknown`. Check: `pyproject.toml:59-60`, `__main__.py`, `app.py:75-79`, `__init__.py:13-22`; no named test
covers it (`PRD.md` FR-15).

**AC-03 — help imports nothing heavy, screens least of all.** Given a bare interpreter, when `levix --help`, `levix tube -h` or
`levix game scores` runs, then none of `psutil`, `yt_dlp`, `sounddevice`, `soundfile`, `numpy`, `textual` appears in `sys.modules`, because
discovery reads only the `MANIFEST` and `registry.py:94` is the single deferred-import site. Check: `tests/test_router.py`
`test_help_forwarding_does_not_import_a_heavy_dependency`, `test_an_official_module_help_does_not_import_its_own_dependency`;
`tests/modules/test_arcade.py` `test_the_screen_is_not_imported_by_help_or_scores`.

## B. Routing and exit codes

**AC-04 — arguments, context and codes survive forwarding.** Given a stub module, when `levix stub note loud --loud --proof PATH` runs, then
it receives exactly those arguments on the root's `LevixContext`, and its own `return 7` becomes the process code; missing extra is 3 and bad
configuration 5. Check: `tests/test_router.py` `test_module_arguments_and_flags_survive_the_forwarding`,
`test_a_module_can_exit_with_its_own_code`, `test_a_levix_error_raised_inside_a_module_keeps_its_exit_code` (8),
`test_a_module_that_is_missing_its_package_refuses_with_the_gate_message`, `test_a_bad_configuration_value_is_reported_as_a_config_error`.

**AC-05 — usage errors are 2, unknown names are 4.** Given a registry holding a plugin named `stub`, when `levix stub note --no-such-flag`
runs, then the code is 2 and the prefix is `levix stub`; a bare group prints help at 2; `levix nostalgia` exits 4 with
`unknown command: nostalgia` and lists the registered names. Check: `tests/test_router.py`
`test_a_bad_flag_inside_a_module_is_usage_error_not_a_crash`, `test_a_group_called_with_no_arguments_shows_its_help_and_calls_it_a_usage_error`,
`test_an_unknown_command_is_reported_with_the_modules_that_do_exist`.

**AC-06 — exceptions are classified by name, and a bug is reported as a bug.** Given Typer 0.27 raising its own click fork's exceptions, when
one escapes to `main`, then `LevixError` keeps its code, `KeyboardInterrupt` is 130, `SystemExit` its own code, and the rest is matched by MRO
class name, not `isinstance`: `Abort` to 130, `Exit` to its `exit_code`, `UsageError`/`BadParameter` to 4 when the message says "No such
command" else 2, `ClickException` to its own code (2 in click, 1 if absent). An unrecognised exception prints "unexpected error", the type, a
pointer to `levix doctor` and the last 1500 traceback characters at exit 1. Check: `main.py:61-96`, `main.py:145-170` (asserted by no test,
`PRD.md` FR-31).

**AC-07 — the codes modules produce in practice.** Given stubbed boundaries: refused confirmation 6, external tool 7, provider 8, Ctrl+C 130,
bad flag 2. Check: `tests/modules/test_files.py` `test_delete_refuses_without_a_terminal_and_removes_nothing`,
`tests/modules/test_tube.py` `test_play_without_a_player_names_what_it_looked_for`, `tests/modules/test_ai.py`
`test_provider_failure_exits_8`, `tests/modules/test_music.py` `test_ctrl_c_during_playback_exits_130_and_says_the_device_is_free`,
`test_a_bad_volume_flag_exits_five` (5).

## C. Configuration layers

**AC-08 — layering with provenance, and one switch that moves the profile.** Given no user file, when `levix config show` runs, then every
schema key resolves from `default`; a `config.toml` value beats it and reports `user`; `LEVIX_<SECTION>_<KEY>` beats the file and reports
`env`; given `LEVIX_HOME`, config, data, cache, state and log all move, while `LEVIX_DATA_DIR` overrides one directory and wins. Check:
`tests/test_config.py` `test_defaults_load_without_a_user_file`, `test_env_layer_sits_above_the_user_file`,
`test_levix_home_redirects_every_directory`, `test_single_directory_override_wins`; `paths.py:71-92`.

**AC-09 — invalid configuration is 5, not a traceback.** Given a malformed `config.toml`, an unknown section, an unknown key or an
out-of-range value, when any command loads configuration, then the code is 5 and the message names the key and file. Check:
`tests/test_config.py` `test_bad_config_is_a_reported_error_not_a_traceback` (parametrised), `test_config_error_carries_the_documented_exit_code`.

**AC-10 — writes preserve the file; secret-shaped keys are refused; a module falls back.** Given a commented `config.toml`, when
`levix config set general.theme default` runs, then only that override is written, comments and ordering survive (`tomlkit`), `unset` removes
just that key, `reset` keeps a `config.toml.bak`, and a key whose last component holds `key`, `token`, `secret` or `password` is refused with
5 and masked in `show`/`list` as `set, hidden` (no brackets — the mask goes into a Rich table cell, where `[set, hidden]` parsed as a style tag
and printed nothing); an unreadable value inside Tube falls back to the documented default instead of aborting the download. Check:
`config.py:280-296`, `commands/config_cmd.py:28,48,68,92`, `modules/tube/cli.py:348-357`, `tests/modules/test_tube.py`
`test_the_configured_directory_is_used_when_no_flag_is_given`, `tests/test_config.py::test_config_set_refuses_a_key_that_looks_like_a_credential`,
`tests/test_markup_safety.py::test_the_config_mask_reaches_the_screen_as_words`.
Both gaps this criterion used to carry are closed: `config set` no longer accepts a `--yes` it never read, and
`config reset --yes` now goes through `require_approval(..., destructive=True)` (`commands/config_cmd.py:132-137`), asserted by
`tests/test_config.py::test_reset_yes_cannot_delete_a_configuration_without_a_typed_word`.

## D. Storage and history

**AC-11 — one database, WAL, short-lived connections, idempotent migrations, vacuumable.** Given a data directory, when `levix` runs, then
every table lives in `<data>/levix.db`, each connection sets `journal_mode=WAL` with a `busy_timeout` of at least 5000, and two `connect()`
calls hand out different objects; `apply_migrations(("core",))` run twice returns `[]`, every namespace is declared even when empty, Arcade
and Music fill only their own slots; `levix doctor --vacuum` runs `VACUUM` with the history intact. Check: `tests/test_storage.py`
`test_the_shared_database_uses_wal_and_a_busy_timeout`, `test_a_connection_is_not_reused_across_calls`, `test_migrations_are_idempotent`,
`test_a_module_registers_its_migration_into_its_reserved_slot`, `test_vacuum_runs_on_the_shared_file`; `commands/doctor_cmd.py:36-38`.

**AC-12 — history is newest-first, bounded and cannot break a run.** Given several runs, when `levix` writes history, then rows carry argv,
module, exit code, duration and a UTC timestamp; `prune_history(3)` keeps the newest and reports the dropped count; a failure inside `_record`
never changes the user's exit code. Check: `tests/test_storage.py` `test_history_round_trips_in_newest_first_order`,
`test_prune_keeps_the_newest_rows_and_reports_what_it_dropped`; `tests/test_router.py` `test_a_run_command_is_written_to_the_shared_history`.
The "first token starting with `-` is skipped" rule (`main.py:184`) has no test, contrary to `FUNCTIONAL_REQUIREMENTS.md:82`.

## E. Terminal safety: cp1252 and Rich markup

**AC-13 — glyphs and colour follow the stream, never the wish.** Given a cp1252 console, when a bar or arrow renders, then the ASCII set
(`#`, `+`, `->`, `OK`, `!!`, `\|/-`) is used and no box-drawing character is written; given `NO_COLOR`, `LEVIX_NO_COLOR=1`, `TERM=dumb` or a
non-TTY stdout, colour is off, and on Windows a TTY gets ANSI only after `ENABLE_VIRTUAL_TERMINAL_PROCESSING` (0x0004) succeeds - failure
degrades instead of raising. Check: `tests/test_terminal.py` `test_a_codepage_terminal_gets_ascii_and_never_a_box_character`,
`test_a_forced_ascii_profile_writes_only_bytes_a_cp1252_console_can_encode`, `test_detect_uses_the_environment_it_is_given`,
`test_a_captured_stream_is_not_a_terminal_and_gets_no_vt_bootstrap`.

**AC-14 — outside text is escaped and flattened.** Given a file name, site title or model reply containing `[bold]`, a control character or a
character this console cannot encode, when LEVIX prints it, then the markup is not interpreted, the value stays on one line, unencodable
characters come back as `\uXXXX`/`\xNN`, and no `UnicodeEncodeError` is raised. Check: `main.py:108-120` (`_plain`), `terminal.py:121-138`
(`encode_safe`), `tests/modules/test_files.py` `test_printable_survives_a_name_the_console_cannot_encode`.

**AC-15 — captured streams get a bound or a refusal.** Given stdout is a pipe, when `levix hacker matrix` runs with neither `--iterations`
nor `--duration`, then it exits 2 and explains; when `levix files browse` or `levix game snake` runs, then it exits 1 naming the
pipe-friendly alternative; when `levix dashboard` runs, then it exits 2 with no traceback. Check: `tests/modules/test_hacker.py`
`test_matrix_needs_a_bound_when_stdout_is_captured`, `tests/modules/test_files.py` `test_browse_refuses_a_piped_stdout_cleanly`,
`tests/modules/test_arcade.py` `test_a_screen_refuses_a_piped_stdout_and_points_at_auto`, `tests/test_dashboard.py`
`test_dashboard_refuses_a_redirected_terminal_with_the_usage_code`.

## F. Dashboard

**AC-16 — rows reflect the gate, not a wish.** Given a ready module, a module whose package is absent and a broken entry point, when rows are
built, then the states are `ready`, `needs install`, `broken`, only `ready` is runnable, the install row embeds
`pip install "levix[music]"`, and a provider-less plugin gets no invented pip line. Check: `tests/test_dashboard.py`
`test_rows_carry_the_state_that_the_gate_actually_reports`, `test_a_plugin_that_names_no_provider_does_not_invent_a_pip_line`.

**AC-17 — filter, launch, argv shape, `t`/`h`/`r`.** Given three rows, when the user types `monitor`, one row remains; when `enter` is
pressed on a ready row, `spawn.run()` is called inside `suspend()` with the manifest's `ui.argv`, argv being
`[sys.executable, "-m", "levix", ...]` with no shell; on an unavailable row nothing runs, and a module with no declared argv opens
`<name> -h`; `t` visits only registered themes, `h` empties the history panel without touching the log, `r` installs a fresh registry. Check:
`tests/test_dashboard.py` `test_dashboard_lists_every_module_and_reflects_the_filter`,
`test_enter_on_a_ready_row_runs_the_same_command_line`, `test_enter_on_an_unavailable_row_says_why_instead_of_running_it`,
`test_theme_binding_cycles_only_through_registered_themes`, `test_history_can_be_hidden_without_touching_the_log`; `spawn.py:19-35`.

## G. The dependency gate

**AC-18 — availability is decided without importing, in four states, and the hint is honest.** Given a package name, when `deps.check` asks
whether it is installed, then `importlib.util.find_spec` answers and the probed module is never imported; given a package that is absent, too
old, importable without metadata, or whose version string will not parse, availability is `missing`, `too_old`, `uncertain`, `uncertain`, and
`uncertain` still satisfies the gate; given `yt_dlp` versus `yt-dlp`, status names the distribution, an official module gets
`pip install "levix[<extra>]"` naming one distribution even for several extras, and a provider-less plugin gets no pip line at all. Check:
`deps.py:76-109`, `tests/test_deps.py` `test_no_availability_check_imports_the_module_it_probes`,
`test_an_absent_package_is_missing_and_not_satisfied`, `test_a_version_below_the_pin_is_reported_not_masked`,
`test_an_importable_package_without_metadata_is_uncertain_but_allowed`, `test_an_unparseable_installed_version_is_uncertain_not_accepted_silently`,
`test_the_gate_raises_with_the_exact_install_line_for_an_official_module`, `test_the_gate_refuses_to_invent_a_pip_line_for_a_provider_less_plugin`.

## H. Plugins

**AC-19 — discovery is metadata only: a broken plugin is listed, not fatal, and origin is stamped.** Given an entry point that raises on load
or returns a non-`ModuleManifest`, when `discover()` runs, then that name is listed with `cli_path=""` and a `failed to load: <Type>: <msg>`
summary while the seven good modules remain; given the example plugin installed, `origin` is `third_party` whatever the manifest asserts and
`version` is the distribution's `0.1.0`. Check: `tests/test_registry.py` `test_a_broken_entry_point_is_listed_and_explained_not_fatal`,
`test_a_non_manifest_is_reported_as_broken_rather_than_used`, `test_official_modules_are_stamped_by_the_registry_not_by_themselves`.

**AC-20 — a plugin runs through the same router and sees the same session.** Given the example installed, when `levix hello greet levix`
runs, then it exits 0 and prints `theme=default`, the value the core resolved; when `levix hi alias --times 3` runs (the manifest's
alias, which is the `greet` command itself), the same command runs three times; when `levix hello where` runs, it prints this run's profile and lists the earlier
`levix hello greet profile` from shared history. Check: `tests/test_plugin_example.py`
`test_a_third_party_command_runs_through_the_router`, `test_a_plugin_sees_the_paths_and_history_of_the_run_it_is_in`.

**AC-21 — permissions are a closed disclosure set of seven.** Given any manifest, `permissions` holds only `network`, `fs_read`, `fs_write`,
`subprocess`, `audio`, `secret_read`, `secret_write`, as a `frozenset`, and every manifest declares a dashboard `ui`. Check:
`tests/test_registry.py` `test_permissions_are_a_closed_disclosure_set`, `module.py:25-35`. The three places that used to list six —
`FUNCTIONAL_REQUIREMENTS.md` FR-10, `PRD.md:70` and `docs/security/PERMISSIONS.md` — now name `secret_write`, which
`modules/ai/__init__.py:54-62` declares. Nothing enforces any of them - they inform a human.

**AC-22 — installing a plugin is pip, and nothing else.** Given a new plugin, when its author runs `pip install -e .`, then
`levix plugins list` shows it and `levix <name>` works; there is no `plugins install`, `uninstall` or `publish`, and `plugins info` on an
unknown name exits 4. Check: `commands/plugins_cmd.py:1-8` (the deliberate omission), `plugin-examples/hello/README.md:10-21`.
`levix create-module` scaffolds the project (`create_module_cmd.py:78-186`); no test installs the generated package end-to-end.

## I. Security invariants

**AC-23 — no shell anywhere a subprocess starts.** Given a player, a proposed command, an OS reporting tool, the editor or `icacls`, when
LEVIX runs it, the call is an argument list with `shell=False`. Check: `tests/modules/test_tube.py`
`test_a_player_is_handed_an_argument_list_not_a_shell_string`, `tests/modules/test_ai.py`
`test_run_proposal_uses_an_argument_list_and_no_shell` (a `shutil.which`-resolved path), `test_run_proposal_actually_runs_a_real_process`;
`tests/modules/test_hacker.py` `test_run_tool_runs_an_argument_list_not_a_shell`. NFR-5.1's "no `shell=True`" is acceptable by grep plus
these tests; "every subprocess call is tested" is not - `config edit` and the `icacls` hardening have no test.

**AC-24 — a model cannot smuggle a shell construct.** Given a proposal containing a pipeline, `;` or a redirection, when
`levix ai command REQUEST --run` runs against a stubbed provider, then the code is 0, the output says "no command offered" and "nothing has
run", and no approval prompt is reached. Check: `tests/modules/test_ai.py` `test_command_refuses_a_pipeline_proposal_before_any_approval`,
`test_extract_proposal_refuses_what_a_shell_would_interpret`, `test_split_argv_keeps_a_quoted_windows_path_together`.

**AC-25 — `--yes` never authorises a destructive action.** Given `files delete`, `files copy --force`, `game scores --clear` or
`ai command --run`, when `--yes`/`-y` is passed with stdin not a terminal, then the code is 6, the message contains "--yes cannot authorize",
and the target is unchanged. Check: `approve.py:34-49`, `tests/modules/test_files.py` `test_delete_yes_cannot_authorize_a_deletion`,
`test_copy_with_force_still_needs_a_terminal`; `tests/modules/test_arcade.py`
`test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it`; `tests/modules/test_ai.py` `test_command_yes_cannot_authorize_a_run`. Not
acceptable as documented: no configuration key turns the gate on or off — the
`general.confirm_destructive` key that used to be declared (`defaults.toml`, `config.py`) was read
by nothing and has been removed from the schema, so `PRD.md` S5 and FR-72/74 must be read as "the
gate always asks", not "the gate honours a setting".

**AC-26 — every destructive prompt asks for a typed word.** Given a real terminal, the words are `DELETE` (`files delete`,
`game scores --clear`), `OVERWRITE` (copy/move/rename collisions) and `RUN` (an AI proposal), and `create-module --force` does go through the
same gate before its `shutil.rmtree` (`create_module_cmd.py:50-55`); anything else exits 6. Check: `approve.py:51-59`,
`modules/files/cli.py:340-353,478-490`, `modules/ai/cli.py:342-349`. No command lets a flag skip it any more — `config reset`
joined the gate (`commands/config_cmd.py:132-137`, AC-10) — and no test drives an interactive prompt, so the typed words themselves
hold by reading and by the refusal path, not by a human typing `DELETE` on this machine.

**AC-27 — the file wall.** Given `--root DIR`, when `files` resolves, copies, moves, renames or deletes, then a path outside the wall is
refused before any disk work, a sibling sharing a name prefix is refused, another drive and a UNC share are never "inside", and Windows
comparison is case-insensitive. Check: `tests/modules/test_files.py` `test_resolve_refuses_a_traversal_out_of_the_root`,
`test_a_different_drive_is_never_inside_the_wall`, `test_a_unc_share_is_never_inside_a_local_root`,
`test_windows_paths_are_matched_case_insensitively`, `test_deleting_a_link_removes_the_link_and_never_the_target`.

**AC-28 — a key goes only to its own provider and is never printed.** Given no `LEVIX_AI_API_KEY`, an empty keyring and no `secrets.json`,
when `levix ai check` runs, then it exits 0 and reports source `none`; a remote non-loopback base URL without a key is refused, while
loopback and Ollama need none; a provider failure names provider and URL with the key value on neither stream. Check:
`tests/modules/test_ai.py` `test_check_runs_offline_and_reports_no_key`, `test_resolve_key_refuses_a_remote_host_without_a_key`,
`test_resolve_key_never_asks_ollama_for_a_key`, `test_key_set_writes_the_keyring_and_never_prints_the_value`,
`test_openai_body_without_choices_names_the_provider_not_the_key`.

**AC-29 — no DRM circumvention, no cookies, no quiet file URLs, no overwrites.** Given any Tube request, no option asks for credentials,
cookies or account state; `file://` stays disabled until `--allow-file-url`; a playlist is refused unless `--playlist` opts in, and opting in
prints the rate-limit warning; existing files are never overwritten. Check: `tests/modules/test_tube.py`
`test_no_request_ever_asks_for_credentials_or_cookies`, `test_file_urls_stay_disabled_until_they_are_explicitly_allowed`,
`test_existing_files_are_never_overwritten`.

**AC-30 — recon stays local.** Given `hacker info` and `hacker network`, only local tools and stdlib calls are used, every value names the
tool that produced it, an `on_link` route is not reported as a gateway, and no placeholder gateway is printed; the module has no scanning,
exploitation or packet-capture capability. Check: `tests/modules/test_hacker.py` `test_network_reports_real_local_configuration`,
`test_network_never_shows_a_placeholder_gateway`, `test_route_print_on_link_rows_are_not_reported_as_gateways`.

**AC-31 — honest unknowns.** Given a metric the platform cannot read, output says "unsupported here - no sensors exposed through psutil",
"unsupported - psutil exposes no GPU API", "not reported by this platform" or "unknown" rather than a zero; a failed update check is reported
as a network limitation; an unknown theme is announced. Check: `modules/systempulse/cli.py:95,105-106,127`, `dashboard/theme.py:95-103`,
`tests/modules/test_tube.py` `test_an_unknown_total_is_said_as_unknown_rather_than_zero`. `levix doctor` is tested by `tests/test_doctor.py`
(six cases: the full report carries all three areas, `--only modules` hides capabilities and env, `--only capabilities` hides modules,
`--only env` is the environment slice, an unknown area is a `ConfigError`, and a filtered report states its own verdict); the `prefix`
filter is applied at `commands/doctor_cmd.py:43-54`.

## Criteria that cannot be accepted on this machine yet

| Subject | What cannot be accepted | Why |
| --- | --- | --- |
| POSIX-only paths | the `chmod 0600` effect and keyring branch of `secrets.py:81-104`; the `ip addr show`, `ifconfig`, `resolv.conf`, `nsswitch.conf`, `route -n` parsers in `hacker`; `brew install ffmpeg` / `sudo apt install ffmpeg` advice | only the Windows branch (`icacls /inheritance:r /grant:r <user>:F`) and only `ipconfig` / `route print` ran here; `tests/modules/test_ai.py::test_key_from_the_owner_only_file_when_no_keyring` and `tests/modules/test_hacker.py::test_ip_addr_show_lists_interfaces_addresses_and_flags` drive those paths with fakes or captured text, never a real POSIX host, and `modules/tube/core.py:40-51` picks advice by `sys.platform` |
| Real TTY behaviour | playing Snake or Tetris by key, `files browse`, `monitor live`, animated `hacker matrix`, the dashboard on a screen | AC-15 forces refusal or bounding when stdout is a pipe; screens are driven headlessly by Textual's Pilot (`tests/test_dashboard.py`, `tests/modules/test_files.py::test_browse_screen_copies_previews_and_deletes`, `tests/modules/test_arcade.py::test_the_snake_screen_steers_on_a_key_redraws_and_settles`, the last two `integration`) |
| Typed destructive words | a human typing `DELETE`, `OVERWRITE` or `RUN` at a real prompt | AC-25/AC-26 are asserted only through the non-TTY refusal; `approve.py:51-59` has no interactive test |
| Audible playback and a real download | sound actually reaching a device; a merged-stream download and a `--convert-to` that really ran | `tests/modules/test_music.py::test_zero_five_seconds_of_a_real_tone_reaches_a_real_output_device` is `integration` and device-dependent; the tube tests drive the ffmpeg verdict through `core.ffmpeg_path()` patched in a test (`tests/modules/test_tube.py::test_a_conversion_works_when_ffmpeg_is_present`), and no download was ever performed for real because the build made no network requests. Note the machine state: `ffmpeg`, `ffprobe` and `ffplay` ARE on PATH here (a winget `yt-dlp.FFmpeg` build), so `capabilities.probe("ffmpeg")` and `probe("media_player")` both report `ok` and the exit-7 refusal is not reachable on this host without patching |
| Network providers | live Tube downloads, `levix ai` against a real server, `levix update` against PyPI | the suite substitutes Tube's `_make_ydl` seam and the AI transport; `levix update` and `update --json` have no test (`PRD.md` FR-94, FR-95) and need a reachable `https://pypi.org/pypi/levix/json` for a name that is not published |
| Log redaction | "secrets never reach the log" | `logging_setup.RedactFilter` is read but asserted by no test, and `tests/conftest.py:38` disables file logging (`NON_FUNCTIONAL_REQUIREMENTS.md` NFR-5.3) |
| Distribution | `pipx install levix`, wheels, standalone binaries | `README.md:13-23` advertises them and `CHANGELOG.md` says nothing is published; the only accepted install is `pip install -e ".[dev,all]"` from this tree |
| CI evidence | "the suite is green on every push" | there is no `.github/workflows` or any pipeline in this tree; the suite figure quoted above is a hand run on Windows 11 |

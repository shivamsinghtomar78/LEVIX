# LEVIX User Stories

Written against the 0.4.0 tree as it stands. The hand verification behind every line is
Windows 11 with Python 3.12.10. GitHub Actions now executes the non-integration suite on
Ubuntu and macOS too; its third run failed eight test functions that depend on the machine
they run on, all eight were fixed, and its **fourth run (`5b047ad`), fifth (`75daed2`) and
sixth (`3d460df`) are each green on all seven
jobs**. So a story marked `Satisfied today` is a cross-platform result for the cases CI runs
and still a Windows-only result for the ten `integration` cases and for anything a runner
never asserts. Run #6 is also the first that executed the POSIX file-mode cases of
`tests/test_secrets.py` on Linux and macOS rather than skipping them here.
`Satisfied today` names commands read in `src/levix`; `Verified by` names tests collected in
`tests/`; `Not implemented` states plainly what is only partly met.
Personas are the three in `PRD.md` §3: **DEV** (developer on their own machine),
**OPS** (script or CI author shelling out to `levix`), **AUTH** (third-party module author).

Deferred across several stories, and where that is recorded instead of invented: plugin
`install`/`uninstall`/`publish` (`commands/plugins_cmd.py:1-8`, `PRD.md` §7), PyPI distribution,
standalone binaries (`CHANGELOG.md` "Known gaps") and a CI matrix that is not green on
every column yet. POSIX behaviour is likewise deferred
(`CHANGELOG.md`). The open-work list is `docs/roadmap/CURRENT_STATUS.md`, which every
deferred story points at rather than restating.

## US-01 — One executable for the whole toolset (DEV)

As a developer I want one installed command covering monitoring, network facts, file work,
downloads, local audio, games and model chat, so that I stop maintaining six tools with six
config files and six credential conventions.

- Satisfied today: `levix --help` prints `APP_HELP` ("One CLI. Multiple applications. Unlimited
  extensibility.", `app.py:21`) and lists `dashboard`, `doctor`, `update`, `create-module`,
  `config`, `plugins` plus the seven modules `monitor`, `hacker`, `files`, `tube`, `game`,
  `music`, `ai` (`app.py:87-98`); `levix --version`/`-V` prints `levix 0.4.0`, exit 0;
  `levix plugins list` shows the same seven at 0.4.0 with origin, commands and readiness.
- Verified by: `tests/test_registry.py::test_every_official_module_is_discovered`,
  `::test_official_modules_are_stamped_by_the_registry_not_by_themselves`.
- Not implemented: nothing is published, so today's install is from the tree —
  `python -m venv .venv`, then `pip install -e ".[dev,all]"` (`CONTRIBUTING.md:13-19`).
  `README.md:13-23` shows `pipx install levix`; that is a forward-looking claim.

## US-02 — Help that costs nothing (DEV)

As a developer I want `levix --help` and `levix tube -h` to answer instantly with the module's
own real help, so that looking up a flag never imports yt-dlp or psutil.

- Satisfied today: each module is a forwarding command with `add_help_option=False` and
  `ignore_unknown_options` (`router.py:49-57`), so `-h` reaches the module's Typer parser;
  discovery loads only the `MANIFEST` data object and `registry.build_cli` is "the single
  deferred-import site" (`registry.py:93-96`). A bare module name prints that module's help and
  exits 2, because click 8.5 raises `NoArgsIsHelpError`.
- Verified by: `tests/test_router.py::test_help_forwarding_does_not_import_a_heavy_dependency` and
  `::test_an_official_module_help_does_not_import_its_own_dependency` — both run the real entry
  point in a fresh interpreter and assert no `psutil`, `yt_dlp`, `sounddevice`, `soundfile`,
  `numpy`, `textual` in `sys.modules` (`_child_heavy_loads`, `test_router.py:234-257`);
  `tests/modules/test_tube.py::test_tube_help_never_imports_yt_dlp`,
  `tests/modules/test_files.py::test_module_help_lists_every_command`,
  `tests/test_router.py::test_a_group_called_with_no_arguments_shows_its_help_and_calls_it_a_usage_error`.

## US-03 — Optional power, demanded only when used (DEV)

As a developer I want the base install light and a module whose extra is missing to name the
exact install command, so that I install only what I actually use and never see an `ImportError`.

- Satisfied today: six core dependencies (`pyproject.toml:30-37`); `monitor`, `tube`, `music`,
  `ai`, `secrets`, `all`, `dev` are extras (`pyproject.toml:39-57`). Each module's Typer callback
  runs `deps.ensure_dependencies` before any command body, so `levix music play x.wav` without the
  extra exits 3 with `pip install "levix[music]"` while `levix music -h` still exits 0
  (`deps.py:120-132`). For a module that names no provider the message is "no install hint is
  declared for this module" — no invented pip line.
- Verified by: `tests/test_deps.py` (14, incl. `test_the_gate_raises_with_the_exact_install_line_for_an_official_module`,
  `test_no_availability_check_imports_the_module_it_probes`),
  `tests/test_router.py::test_a_module_that_is_missing_its_package_refuses_with_the_gate_message`,
  `::test_help_is_still_available_when_a_dependency_is_missing`.
- Note: `PRD.md:69` lists the `music` extra as `sounddevice` + `soundfile`; it also pins
  `numpy>=2.0,<3` (`pyproject.toml:44`).

## US-04 — One launcher for everything installed (DEV)

As a developer I want a launcher that lists what is ready, narrows as I type, launches the pick in
this terminal and shows what I ran recently, so that I do not memorise command names.

- Satisfied today: bare `levix` or `levix dashboard` (`app.py:84-87`, `commands/dashboard_cmd.py`).
  Rows come from manifests only, and exactly one declaration changes membership rather than
  wording: `UiSpec(mode="hidden")` gets no row (`dashboard/module_list.py:94-106`). The rows
  that do appear carry three distinct states — `ready`, `needs install` (with the
  pip line), `broken` (with the load failure) (`dashboard/module_list.py:42-86`). Typing filters
  name/title/summary case-insensitively. Bindings: `enter` launch, `space` details, `f` filter,
  `r` reload with a fresh registry, `t` theme cycle, `h` history toggle, `q` quit, `escape`
  clear-or-quit, `ctrl+c` quit (`dashboard/app.py:75-85`). Launch is
  `with self.suspend(): spawn.run(*argv)`, argv = `ui.argv` else `<name> -h`, so one Textual app
  owns the terminal (`dashboard/app.py:166-177,255-264`); `levix tube` declares no argv, so its row opens
  Tube help. The history panel shows the last `dashboard.recent_commands` (default 10) rows with
  codes coloured green/yellow/red (`dashboard/history.py:13-42`). With stdout or stdin redirected
  it explains and exits 2 (`dashboard_cmd.py:23-30`).
- Verified by: `tests/test_dashboard.py` (19, incl.
  `test_rows_carry_the_state_that_the_gate_actually_reports`, `test_enter_on_a_ready_row_runs_the_same_command_line`,
  `test_enter_on_an_unavailable_row_says_why_instead_of_running_it`,
  `test_theme_binding_cycles_only_through_registered_themes`, `test_history_can_be_hidden_without_touching_the_log`,
  `test_a_module_hidden_from_the_dashboard_gets_no_row`,
  `test_a_hidden_module_reaches_no_widget_the_app_builds`,
  `test_no_official_module_hides_itself_from_the_dashboard`,
  `test_dashboard_refuses_a_redirected_terminal_with_the_usage_code`).
- Not implemented: no module runs inside the dashboard, and the API no longer pretends
  otherwise. `UiSpec.mode` is `suspend` or `hidden`; `registry.build_screen` and
  `UiSpec.screen_path` — which nothing called, and which could not have worked because one
  TTY hosts one Textual app — are deleted, and `hidden` is now enforced where it was only
  documented (`module_list.py:94-106`, with
  `tests/test_registry.py::test_a_module_hidden_from_the_dashboard_is_still_discovered_and_routable`
  keeping the router out of it).
  The theme vocabulary used to disagree — `config.SCHEMA` accepted `hacker`, `minimal` and
  `high-contrast` (`config.py:85`) while `dashboard/theme.py` knew only `default|dark|green|matrix|light`,
  so a configured `hacker` printed "unknown theme 'hacker'; using levix-dark". Both tables now
  cover the four documented names and `test_dashboard.py::test_every_documented_theme_name_resolves`
  fails if they drift apart again.

## US-05 — Find and read files without leaving the terminal (DEV)

As a developer I want name, extension and content search plus a preview that admits what it could
not decode, so that "where is that config and what is in it" is answered from a prompt.

- Satisfied today: `levix files search ROOT PATTERN` with `--glob/-g`, `--case-sensitive`,
  `--include-hidden`, repeatable `--ext`, `--limit/-n`, `--max-depth`, `--grep TEXT`,
  `--grep-regex`, `--max-bytes` (2 MiB default per file), reporting count, elapsed time and every
  category deliberately skipped; `levix files preview PATH --lines N --no-line-count` prints the
  head plus metadata, decoding chained UTF-8 → cp1252 with a labelled lossy Latin-1 fallback.
  A missing preview is exit 2; an unreadable file during a search is reported and the scan continues.
- Verified by: `tests/modules/test_files.py` (120, incl. `test_search_prints_matches_count_and_elapsed`,
  `test_grep_skips_binary_by_nul_sniffing_and_counts_it`, `test_grep_skips_files_over_the_size_cap`,
  `test_decode_chain_prefers_utf8_then_cp1252_then_labels_latin1_lossy`, `test_preview_of_a_missing_file_exits_two`,
  `test_preview_survives_a_name_the_console_cannot_encode`).

## US-06 — Change the disk without losing data by accident (DEV)

As a developer I want writes confined to a directory I named and destruction gated behind a typed
word, so that no habit, flag or pipe can silently wipe a tree.

- Satisfied today: `files copy SRC DEST`, `move`, `rename PATH NEW` take `--root` (the wall) and
  `--force`; a collision without `--force` is refused, and with `--force` the shared gate demands
  the typed word `OVERWRITE` (`modules/files/cli.py:340-353`). `files delete PATH... --root .
  [--recursive]` measures and prints the plan, then requires the typed word `DELETE`
  (`cli.py:459-490`). Symlinks go as links, never as their targets; escaping the wall is
  `UnsafePathError`, exit 2. `--yes` cannot authorise any of it ("--yes cannot authorize a
  destructive action"), and a non-TTY stdin is a refusal, exit 6 (`approve.py:34-49`).
- Verified by: `tests/modules/test_files.py::test_delete_yes_cannot_authorize_a_deletion`,
  `::test_delete_refuses_without_a_terminal_and_removes_nothing`, `::test_copy_with_force_still_needs_a_terminal`,
  `::test_delete_above_the_named_root_is_refused`, `::test_resolve_refuses_a_traversal_out_of_the_root`.
- Not implemented: nothing can switch the gate off. A `general.confirm_destructive` key used
  to be declared and defaulted `true` while `approve.py` never consulted it; the key is
  removed rather than wired, because a destructive action that asks is the promise, not an
  option. `ai.require_approval` remains the one deliberate opt-out and it says so loudly.

## US-07 — Inspect, download or play online video with honest gates (DEV)

As a developer I want Tube to say what a URL is, save only where I chose, never overwrite, and
refuse merged or converted formats when ffmpeg is absent instead of failing mid-download, so that
it stays predictable and inside site terms.

- Satisfied today: `tube info URL [--formats] [--playlist] [--allow-file-url]`,
  `download URL [--output DIR] [--format best|video|audio|SELECTOR] [--convert-to mp3|...]
  [--playlist] [--allow-file-url]`, `play URL [--player mpv]` (`modules/tube/cli.py:79-321`).
  Without ffmpeg, `best`/`video`/`audio` resolve to single-file selectors and say so; a merged
  selector or any `--convert-to` exits 7 with this platform's install command — `winget install
  Gyan.FFmpeg` on Windows (`modules/tube/core.py:40-51`). `play` resolves a single-file stream URL,
  hands it to a PATH-found player as an argument list with `shell=False`, writes nothing, and exits
  7 listing every name tried (`mpv`, `ffplay`, `vlc`, `mplayer`). Posture in code, not prose: no DRM
  or download-protection circumvention, no cookie or credential requests, `file://` off until
  `--allow-file-url`, existing files never overwritten, playlists one entry unless `--playlist`
  opts in with a loud warning.
- Verified by: `tests/modules/test_tube.py::test_the_gate_refuses_and_names_the_command_that_would_fix_it`,
  `::test_an_explicit_selector_is_never_quietly_rewritten`, `::test_existing_files_are_never_overwritten`,
  `::test_a_merged_format_is_refused_before_any_request_is_made`, `::test_a_player_is_handed_an_argument_list_not_a_shell_string`,
  `::test_play_without_a_player_names_what_it_looked_for`, `::test_no_request_ever_asks_for_credentials_or_cookies`.
- Not implemented here: no test reaches a site — `yt_dlp` is reached through one seam, `_make_ydl`,
  which the suite substitutes, so live downloads, live playback and the macOS/Linux advice strings
  are unproven on this machine.

## US-08 — Local audio with no ffmpeg dependency (DEV)

As a developer I want WAV, FLAC, OGG and MP3 decoded and played in-process, plus a library scan and
a stored playlist, so that audio works on a machine that has never heard of ffmpeg.

- Satisfied today: `music play FILE [--device/-d N] [--rate/-r Hz] [--volume/-v 0.0-1.0]
  [--block N]`, `info FILE`, `devices [--kind all|output|input]`,
  `library [--root DIR] [--suffix EXT] [--limit/-n N] [--include-hidden]`,
  `playlist list|add|remove|clear|play` (`modules/music/cli.py`). Decoding is soundfile/libsndfile,
  output is sounddevice/PortAudio, `core.py` uses `numpy` directly, and nothing shells out
  (`modules/music/__init__.py:1-10`). Bad `--volume` is exit 5 with the `levix config set
  music.volume 0.8` remedy; bad `--rate` is exit 2; an undecodable file is exit 7 naming
  libsndfile; Ctrl+C is exit 130 and says the device is free; an unset `music.library_dir` is exit 5
  naming both the key and `--root`; playlist rows live in the shared SQLite database and `clear`
  needs a terminal.
- Verified by: `tests/modules/test_music.py` (57, incl. `test_a_bad_volume_flag_exits_five`,
  `test_play_of_an_undecodable_file_exits_seven`, `test_ctrl_c_during_playback_exits_130_and_says_the_device_is_free`,
  `test_an_unset_library_says_so_instead_of_printing_nothing`, `test_playlist_commands_round_trip_through_the_cli`,
  `test_importing_the_manifest_pulls_in_no_audio_libraries`).
- Needs hardware: one test, `test_zero_five_seconds_of_a_real_tone_reaches_a_real_output_device`
  (marked `integration`), requires a real output device.

## US-09 — Watch the machine and trust what it cannot read (DEV)

As a developer I want a refreshing system view, and where the OS exposes no sensor I want the row
to say so, so that I never act on a fabricated number.

- Satisfied today: `monitor overview [--limit N]`, `cpu`, `memory`, `disk`,
  `network [--watch SECONDS]`, `processes [--limit/-n N] [--by cpu|memory]`,
  `live [--iterations N] [--interval S]` (`modules/systempulse/cli.py:53-229`). `live` clears and
  redraws every `monitor.interval_seconds` (default 1.0); Ctrl+C prints "stopped." and returns
  exit 0. The overview prints "unsupported here - no sensors exposed through psutil" for
  temperature and "unsupported - psutil exposes no GPU API" for GPU rather than a zero
  (`cli.py:105-106`).
- Not implemented: `live` has no non-TTY guard — unlike `hacker matrix`, an unbounded `live` on a
  redirected stream runs forever unless `--iterations N` is given. And `tests/modules/` contains no
  test file for this module, so its rows and its honest-unsupported behaviour are shown by
  observation only (`PRD.md` FR-98, `NON_FUNCTIONAL_REQUIREMENTS.md` Known gaps).

## US-10 — Play a game, and read the scores from a script (DEV)

As a developer I want Snake and Tetris in the terminal with high scores in LEVIX's own database,
plus a headless way to run a game and read the board, so that the leaderboard is not a text file.

- Satisfied today: `game snake [--seed N] [--auto N] [--speed F] [--cols C] [--rows R]`,
  `tetris [--seed N] [--auto N] [--speed F]`, `scores [--game snake|tetris] [--limit/-n N] [--clear]`
  (`modules/arcade/cli.py`). Keys: arrows or WASD steer, `p` pause, `r` restart, `q`/Esc quit. Board
  capped at 120x60, `--auto` at 100000 steps, an unknown `--game` is exit 2; `--seed` replays the
  same food and an unpinned run records the seed it used; `scores` sorts highest first, newest
  first inside a tie; `--clear` needs the typed word `DELETE` and `--yes` cannot supply it; a piped
  stdout refuses the screen with exit 1 and points at `--auto`.
- Verified by: `tests/modules/test_arcade.py` (39, incl. `test_scores_on_an_empty_profile_says_so`,
  `test_snake_auto_play_writes_a_real_row`, `test_an_auto_game_is_reproducible_and_an_unpinned_one_still_records_its_seed`,
  `test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it`, `test_a_screen_refuses_a_piped_stdout_and_points_at_auto`,
  `test_the_migration_lives_in_the_arcade_namespace_only`).

## US-11 — Look cool, read only my own machine (DEV)

As a developer I want a Matrix rain and a read-only tour of my own host and network setup that
names where each value came from, so that "hacker" stays cosmetic and educational rather than
something that touches a machine I do not own.

- Satisfied today: `hacker matrix [--duration S] [--iterations N] [--density F] [--fps N]
  [--seed N] [--width C] [--height R]`, `hacker info`, `hacker network`
  (`modules/hacker/cli.py`). Core is the standard library plus the OS's own reporting tools run as
  an argument list with `shell=False` (`hacker/core.py::run_tool`). `network` prints adapters,
  gateway, DNS and the hostname resolution order under "Where the data came from" and never shows a
  placeholder gateway; a rain without a bound on a captured stream is exit 2.
- Scope as the product states it: authorised/educational recon of the machine you are sitting at.
  There is no exploitation, no stealth, no scanning of other hosts and no packet capture anywhere
  in the module.
- Verified by: `tests/modules/test_hacker.py` (50, incl. `test_matrix_needs_a_bound_when_stdout_is_captured`,
  `test_seeded_scene_repeats_every_frame_exactly`, `test_run_tool_runs_an_argument_list_not_a_shell`,
  `test_network_reports_real_local_configuration`, `test_network_never_shows_a_placeholder_gateway`).
- Windows paths observed here (`ipconfig`, `route print`); the `ip`, `ifconfig`, `resolv.conf` and
  `nsswitch.conf` parsers are tested from captured text but no POSIX host was used.

## US-12 — Ask my own model server, with a capped and honest context (DEV)

As a developer I want AI to answer a prompt, explain files by sending only what it actually read,
and report a provider failure as a provider failure, so that a local Ollama or any
OpenAI-compatible endpoint is usable from the terminal.

- Satisfied today: `ai ask "PROMPT" [--system/-s TEXT] [--stream] [--show-usage] [--provider]
  [--model/-m] [--base-url] [--ollama-url] [--temperature] [--max-tokens] [--timeout]` (piped stdin
  may supply the prompt), `explain FILE... [--focus TEXT] [--max-bytes N]` (default cap 32,000
  bytes per file, and it says what it left out), `models`, `check [--live]` (`modules/ai/cli.py`).
  Providers are `openai-compatible` and `ollama` (`ai/core.py:33-35`); `check` is offline by
  default and prints only the key's source. Non-2xx, timeout, malformed body and stream errors are
  `ProviderError` exit 8 naming provider and URL, never the key; a 404 on the models endpoint is
  reported as "the provider reported none", not as an error.
- Verified by: `tests/modules/test_ai.py` (82 test functions, 97 collected cases, incl. `test_ask_prints_the_reply_and_usage`,
  `test_ask_streams_sse_frames`, `test_explain_sends_only_the_capped_prefix`,
  `test_read_snippet_caps_and_reports_truncation`, `test_timeout_maps_to_provider_error`,
  `test_models_degrades_honestly_on_404`).
- Not implemented: the suite drives a stubbed transport, so nothing here is proven against a real
  server. The aliases `q`/`cmd` are now the commands they name: `levix q "hi"` runs `levix ai ask
  "hi"` because `router._attach` prepends the canonical subcommand (`src/levix/router.py:54-58`);
  the earlier behaviour — the alias mounting as a second route to the **ai** group, so
  `levix q "hi"` exited 4 with "unknown command" — is closed and pinned by
  `tests/test_router.py::test_a_command_alias_reaches_the_command_it_names`.

## US-13 — A model may propose a command; only I run it (DEV)

As a developer I want `levix ai command` to show one proposed command and refuse to execute it
until I type a word in a real terminal, so that model output never becomes a shell command by
default.

- Satisfied today: without `--run` the proposal prints and nothing executes ("print-only (the
  default): nothing ran."). With `--run`, `require_approval(..., destructive=True,
  prompt_word="RUN")` decides (`modules/ai/cli.py:310-325`); the flag's own help says "Accepted and
  ignored: only a typed RUN runs a command". A non-TTY stdin exits 6 having run nothing. A
  proposal containing a pipeline, `;` or a redirection is refused by `extract_proposal` before any
  approval is offered, printing "no command offered" and "nothing has run.", and execution is a
  `shutil.which`-resolved `shell=False` argument list (`ai/core.py::run_proposal`). If
  `ai.require_approval` is set `false`, LEVIX warns that your configuration opted out before
  running rather than doing it silently.
- Verified by: `tests/modules/test_ai.py::test_command_prints_the_proposal_and_runs_nothing`,
  `::test_command_yes_cannot_authorize_a_run`, `::test_command_with_run_refuses_without_a_terminal`,
  `::test_command_refuses_a_pipeline_proposal_before_any_approval`, `::test_run_proposal_uses_an_argument_list_and_no_shell`.

## US-14 — Keep my API key out of every file I would commit (DEV)

As a developer I want the key resolved from environment, then OS keyring, then an owner-only file,
and never printed, logged or written into `config.toml`, so that reporting a problem cannot leak a
credential.

- Satisfied today: `secrets.get_secret` returns `(value, source)` with source
  `env|keyring|file|none`, looking up `LEVIX_AI_API_KEY` (keyring service `levix`) before the
  keyring before `secrets.json` (`secrets.py:60-78`). `ai check` prints only the source and states
  the value is never printed, logged or echoed (`ai/cli.py:489-491`). Configuration never supplies
  secrets: `config set` refuses any key whose last component contains `key`, `token`, `secret` or
  `password` (exit 5) and `config show`/`list` mask such values as `set, hidden` — without
  brackets, because the mask lands in a Rich table cell (`config_cmd.py:28,48,68,92`,
  `config.py:132`). Writes prefer the keyring and delete a stale
  file copy; the fallback file is created at `0600` and hardened on every write with
  `chmod 0600` plus, on Windows,
  `icacls /inheritance:r /grant:r <user>:F` (`secrets.py:81-104,128-139,142-163`).
  `LEVIX_DISABLE_FILE_SECRETS=1` refuses the plaintext store outright; `doctor` reports it as
  `degraded`, never success, with `pip install "levix[secrets]"` as the remedy (`doctor.py:49-57`).
  Loopback and Ollama endpoints need no key; a remote host without one is refused (`ai/core.py:162-170`).
- Not implemented: nothing here is untested any more — `tests/test_logging.py` (6 functions, 11
  cases) asserts redaction, including that a key written by a real command does not appear in a
  real `levix.log`, and `tests/test_secrets.py` (4 functions) stats the secrets file instead of
  reading the code that protects it: on Windows it asserts the ACL `icacls` reports holds one
  grant, to this user, with inheritance removed, and on POSIX it asserts mode `0600` — including
  with the `chmod` forced to fail, which is why `_write_file` now creates the file at `0600`
  rather than writing it and hardening it afterwards. The POSIX half runs only on the Linux and
  macOS columns (it skips here, where `st_mode` is not what Windows enforces), so it is written
  but not yet *observed*: the first run of `ci.yml` that carries those three cases is the moment
  the claim becomes an observation.
  What used to be on this list is closed: `levix ai key set` and `levix ai key clear`
  exist (`ai/cli.py:519-594`), so the hint in `config_cmd.py:92-99` points at a real command, and
  `ai/core.py:42` no longer advertises a `levix secrets` command that was never built.
- Verified by: `tests/modules/test_ai.py::test_key_from_the_environment_wins`,
  `::test_key_from_the_owner_only_file_when_no_keyring`, `::test_no_key_anywhere_reports_none`,
  `::test_resolve_key_refuses_a_remote_host_without_a_key`, `::test_provider_failure_exits_8`
  (asserts the key value appears on neither stream), and the storage side:
  `::test_key_set_writes_the_keyring_and_never_prints_the_value`,
  `::test_key_set_falls_back_to_the_owner_only_file`,
  `::test_key_set_with_the_file_store_disabled_is_a_dependency_error`,
  `::test_key_set_without_a_terminal_names_the_environment_variable`,
  `::test_key_clear_removes_what_key_set_wrote`, and on the permissions themselves:
  `tests/test_secrets.py::test_a_stored_key_lands_in_a_file_only_the_owner_can_read`,
  `::test_a_chmod_that_fails_leaves_no_more_access_than_the_open_gave`,
  `::test_rewriting_an_existing_store_does_not_widen_its_access`,
  `::test_the_acl_holds_one_explicit_grant_and_no_inherited_read`.

## US-15 — Ship a module using only packaging metadata (AUTH)

As a third-party author I want a scaffold and a contract that need nothing from LEVIX's source, so
that `pip install -e .` in someone else's environment is enough to make `levix <name>` exist.

- Satisfied today: `levix create-module NAME [--directory/-d PATH] [--title TEXT] [--force]`
  (`commands/create_module_cmd.py`); the name must be 2-30 characters of `[a-z0-9_-]` starting with
  a letter or the command exits 5 (`_NAME_RE`, line 21). The scaffold is the shape the official
  modules use — `levix-<name>` distribution, `levix_<name>` package,
  `[project.entry-points."levix.plugins"] <name> = "levix_<name>:MANIFEST"`,
  `cli_path="levix_<name>.cli:build_app"` deferred, `dependencies = ["levix>=0.4"]`, README and
  `tests/test_manifest.py`. Re-running over a non-empty directory refuses until `--force` **and**
  the typed destructive confirmation. After `pip install -e .`, `levix plugins list` shows it as
  `third_party` and `levix <name> <command>` runs through the router.
- An author can rely on: `levix.sdk` (a façade with no logic re-exporting 14 names, `sdk.py:29-43`),
  the forwarded `LevixContext` (`router.py:99-104`), shared `Paths`/`Config`/`Database`,
  `terminal.active_glyphs()`, `ModuleManifest`/`UiSpec`/`Permission`.
- An author cannot: claim `official` (the registry stamps `origin` from the provider distribution),
  add configuration keys (`config.SCHEMA` is the core's; unknown keys are errors), treat
  `permissions` as a sandbox (`plugin-examples/hello/README.md:57-60`: "Python plugins can do
  anything LEVIX can"), or expect `ensure_dependencies` in `levix.sdk` — a plugin declaring
  `requirements` must call the gate from its own Typer callback or a missing package surfaces as
  `ImportError` instead of exit 3.
- Not implemented: `levix plugins install`, `uninstall`, `publish`; PyPI distribution (the
  release workflow would publish it, but no PyPI project exists to publish to); a pipeline
  result (the workflows are written and unrun).
- Verified by: `tests/test_plugin_example.py` (7, incl.
  `test_the_entry_point_is_discovered_as_a_third_party_module`, `test_a_third_party_command_runs_through_the_router`,
  `test_a_plugin_sees_the_paths_and_history_of_the_run_it_is_in`,
  `test_the_example_itself_imports_nothing_heavy_at_manifest_time`),
  `tests/test_registry.py::test_a_broken_entry_point_is_listed_and_explained_not_fatal`.

## US-16 — Predictable codes and clean output when I am not watching (OPS)

As a script or CI author I want one documented exit-code table, refusal instead of escape
sequences on a redirected stream, and machine-readable output where a script needs it, so that
wrapping `levix` is safe.

- Satisfied today: `errors.py` is the only table — 0 success, 1 unhandled runtime error, 2 bad
  usage, 3 optional dependency missing, 4 unknown module or command, 5 invalid configuration,
  6 declined confirmation, 7 external tool failed, 8 provider failed, 130 interrupted. A module's
  own integer return or `typer.Exit(code=N)` becomes LEVIX's code (`router.py:79-85`,
  `main.py:41-44`). Interactive surfaces refuse: dashboard 2, `files browse` 1, `game snake` 1
  (both point at a pipe-friendly path), `hacker matrix` 2 until bounded. `--json` exists on exactly
  two commands, `doctor` and `update`; `levix monitor cpu --json` is exit 2. `levix config list
  [SECTION]` prints `key=value` lines, and colour follows `NO_COLOR` / `LEVIX_NO_COLOR=1` /
  `TERM=dumb` / a non-TTY stdout (`terminal.detect`). History is best-effort: any failure inside
  `main._record` is swallowed and cannot change your code.
- Not implemented: the pipeline is **green** but not **complete**. `.github/workflows/ci.yml`
  ran six times on 2026-11-05; its wheel job passed on Ubuntu each time, its third run was
  the first whose suite result could be trusted (see `docs/technology/PYTHON_PACKAGING.md`)
  and failed all six matrix columns on eight tests that depend on the machine they run on,
  and its **fourth (`5b047ad`), fifth (`75daed2`) and sixth (`3d460df`) runs are green on all
  seven jobs**. What is still missing is not
  a red column: the ten `integration` cases have run on no platform but Windows 11, no column
  asserts the POSIX items in `ACCEPTANCE_CRITERIA.md` §What is not verified, and
  `.github/workflows/release.yml` has never run because the PyPI project and its trusted
  publisher do not exist yet. The checks themselves are the
  commands in `CONTRIBUTING.md` §Development workflow, and the pass figure in `PRD.md` S4 was
  produced by hand on Windows 11. `levix update` also presumes a published `levix`
  name on PyPI, which does not exist yet.

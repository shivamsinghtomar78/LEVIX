# Threat model

Scope: LEVIX 0.4.0 as built, `src/levix` and `pyproject.toml`. Method: enumerate the
assets a local user actually has, the entry points through which an outside influence can
reach them, and the specific code that resists each threat. Where nothing resists a
threat, that is stated instead of implied.

This document is about the shipped product's attack surface. `SECURITY.md` at the
repository root is how to report a vulnerability.

## Assets

| Asset | Why it matters | Where it lives |
|-------|----------------|----------------|
| The user's files | `files` writes and deletes; `tube` writes downloads | user's disk |
| The user's shell history and credentials | a proposed command runs with the user's privileges | outside LEVIX |
| The AI provider key | spendable, and proof of identity to a provider | keyring, `LEVIX_AI_API_KEY`, or `Paths.secrets_file` |
| Provider endpoint and model choice | points prompts at a server | `config.toml`, environment |
| Prompts and file excerpts sent to a provider | the user's own content, leaving the machine | in flight only |
| Downloaded media | what the user asked for, and nothing else | `tube.output_dir` or the chosen `--output` |
| Command history and high scores | reveals what the user ran; small | `levix.db` |
| `levix.log` | stack traces, paths, provider URLs | `Paths.log_file`, rotated |
| Integrity of the LEVIX installation | a tampered `levix` runs arbitrary code as the user | site-packages / pipx venv |
| Terminal display | a spoofed prompt or a hidden line makes the human the attack vector | the console |

## Entry points and trust boundaries

| Boundary | Attacker reach | Controlled by |
|----------|----------------|---------------|
| Command line | whoever types | `main.py`, Typer parsing |
| Configuration file and environment | anyone who can write to `%APPDATA%\levix` or the parent process's environment | `config.py`, `paths.py` |
| Python environment and entry points | anyone who can `pip install` into LEVIX's environment | `registry.py` |
| Network content: video pages, yt-dlp metadata, model replies, PyPI JSON | the remote server, and anything between | `tube/core.py`, `ai/core.py`, `update_cmd.py` |
| Local filesystem content: file names, host names, interface names, tool output | a name chosen by another program or a remote site | `terminal.encode_safe`, `terminal.markup_safe`, `_plain`, `_show`, `printable`, `safe_name` |
| External tools found on `PATH` | whoever can write to a directory earlier on `PATH` | `shutil.which` + resolved-path execution |
| Operating-system terminal | any process attached to the same console | Textual, `App.suspend()`, `spawn.py` |

Everything runs with the invoking user's privileges. There is no service, no daemon, no
network listener, no setuid binary and no elevated path in the tree.

## Controls, with the code that implements them

### Subprocesses are argument lists, always

Grep result for the whole tree: the only occurrence of `shell=True` is in `ai/core.py:13`,
in a docstring stating that nothing here uses it. `subprocess.run` appears six times and
`shell=False` is written out in four of them (the other two are `spawn.run` and
`config_cmd.edit`, which pass a list).

| Call site | Program | Form | Extra discipline |
|-----------|---------|------|------------------|
| `spawn.py:31` | LEVIX itself | `[sys.executable, *args]` when frozen, else `[sys.executable, "-m", "levix", *args]` | "Never uses a shell"; `check=False`, return code propagated |
| `tube/core.py:179` | media player | `[player, url]` from `player_command` | player found only via `shutil.which`, "Never guesses a location it did not find on PATH"; `OSError` → `ExternalToolError` (7) |
| `hacker/core.py:291` | `ipconfig`, `route`, `ip`, `ifconfig` | `shutil.which(command[0])` then `[path, *rest]` | executes the resolved path, "so the two searches cannot disagree"; `timeout=8.0` default; `capture_output=True`; output decoded through a candidate chain that never raises |
| `ai/core.py:424` | a model-proposed program | `[resolved, *argv[1:]]` with `argv` from `shlex.split` | `shutil.which` first, `timeout`, `check=False`; refusal of shell metacharacters before this point |
| `secrets.py:150` | `icacls` | fixed argv `/inheritance:r /grant:r <user>:F` | `check=False`, `timeout=10`, `capture_output=True`; no `noqa` is needed because ruff ignores `S603` tree-wide (`pyproject.toml:108`) |
| `commands/config_cmd.py:181` | `$EDITOR` / notepad / vi | `[editor, str(config_file)]` | `check=False`, `OSError` turned into a `ConfigError` that names the editor; the editor is the user's own choice, so this is a deliberate trust of the environment |

| Consequence | Detail |
|-------------|--------|
| No metacharacter interpretation | `;`, `&&`, `\|`, `>` can never acquire meaning by passing through LEVIX |
| Refusal instead of escape | `extract_proposal` rejects a proposal containing any of `;`, `&&`, `\|\|`, `\|`, `>`, `<`, `` ` ``, `$(`, `${`, newline or carriage return, with the reason "LEVIX runs an argument list, not a shell, so pipelines, chains and redirection are refused" (`ai/core.py:386-396`) |
| Timeout everywhere it matters | hacker 8.0 s, ai configurable, `icacls` 10 s, the update request has a timeout argument |

### The files path wall

| Rule | Code |
|------|------|
| A named root is a wall | `core.resolve(raw, root=…)` compares **resolved** `Path` objects with `relative_to`; `UnsafePathError` (exit 2) with a hint to widen it |
| String prefixes are not used | `is_within` — "`C:\root\abc` starts with `C:\root\ab` but is not inside it"; `relative_to` also handles Windows drives, UNC shares and case-insensitivity |
| Symlinks are never followed into a descent or a delete | `walk_paths(followlinks=False)`; "a link is removed as a link, which is the only interpretation that cannot destroy data somewhere else" |
| Delete is confined by default | `files delete --root` defaults to `"."`, so the wall exists even when the user forgets it |
| Copy, move and rename are not confined by default | `--root` defaults to `""`, documented as "no wall by default"; `rename` adds the entry's own directory as a wall regardless |
| New names are validated | `validate_new_name`: no separators, no drive or UNC prefix, no trailing dot or space, ≤255 bytes, and Windows reserved device names (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`) refused because `nul.txt` "leaves an entry that cannot be opened or deleted later" |
| Reads are bounded | `SNIFF_BYTES = 8192`, `HEAD_BUDGET = 256 KiB`, `DEFAULT_GREP_MAX_BYTES = 2 MiB`, `LINE_COUNT_MAX_BYTES = 8 MiB` |
| Nothing destructive is decided in core | `core.py:16-18`: "The caller must pass `levix.approve` first" |

### Human confirmation for destructive and externally-influenced actions

| Control | Detail |
|---------|--------|
| One gate | `approve.require_approval` is shared by `files` deletes, `files copy/move --force` (`prompt_word="OVERWRITE"`), `arcade scores --clear` (`DELETE`), `ai command --run` (`RUN`) and `config reset` — so the AI module cannot invent a weaker prompt than the file module |
| `--yes` cannot authorise a destructive action | when `destructive and assume_yes`, it prints "`--yes` cannot authorize a destructive action; confirming interactively." and forces the prompt anyway (`approve.py:34-39`); `files delete --help` says "Accepted and ignored: --yes cannot authorize a delete." and `config reset --help` says "Cannot skip this confirmation." |
| Non-interactive stdin is a refusal | `not sys.stdin.isatty()` → `UserCancelledError` (6) "refusing to {action} without a terminal to confirm in"; `EOFError` is also a refusal |
| Typed word, not a keypress | expected input is `prompt_word or ("DELETE" if destructive else "yes")`, case-folded comparison; anything else is "cancelled by user" |
| The plan precedes the prompt | `delete` measures and prints file count, directory count and bytes before asking |
| AI approval is on by default | `ai.require_approval` defaults to `true`; when a user sets it to `false`, `ai/cli.py` prints a bold-yellow warning that the command runs without asking, rather than silently complying |
| Deletion is logged | `files delete` writes a `warning` line with the count, bytes and wall — no file names |

### Tube: no circumvention, no credentials, opt-in scale

| Constraint | Evidence |
|------------|----------|
| Implements yt-dlp's own policy and nothing beyond it | `tube/core.py:12-13`: "no DRM or download-protection circumvention, no cookie extraction, no account abuse" |
| Authentication options are never set | `tests/modules/test_tube.py` parametrises over `cookiefile`, `cookiesfrombrowser`, `username`, `password`, `ap_mxac_for_mweb`, `extractor_args`, `external_downloader` and asserts each is absent from `build_options(...)` |
| `file://` stays opt-in | `enable_file_urls` is set only with `--allow-file-url`; without it a `file://` URL is refused with the hint "pass --allow-file-url to let yt-dlp read a file on this disk" |
| A playlist is many requests, and it says so | `PLAYLIST_WARNING` prints on every `--playlist` run, naming the rate-limit consequence and the permission question |
| Existing files are not clobbered | `"overwrites": False` |
| Errors are not swallowed | `"ignoreerrors": False`, so a failed entry reaches `ProviderError` (8) |
| ffmpeg-dependent requests are refused up front | `ensure_ffmpeg` raises `ExternalToolError` (7) with the OS-specific install command instead of failing mid-download |

### Network surface

| Egress | Where | Data leaving the machine | Gate |
|--------|-------|--------------------------|------|
| `https://pypi.org/pypi/levix/json` | `update_cmd.py:23,85-88` | a `GET` with `Accept: application/json` and `User-Agent: levix/<version>`; fixed host, no user input in the URL (`# noqa: S310`) | only when the user runs `levix update`; never on startup, never in the background |
| the configured provider | `ai/core.build_client`, the only `httpx.Client` site | prompts, and for `explain` a capped prefix of each named file (`DEFAULT_MAX_FILE_BYTES = 32_000`, and the reply says what was left out) | only from `ai` commands; URL and key are shown by `levix ai check` |
| media sites, through yt-dlp | `tube/core._make_ydl` | the URL the user typed, and whatever yt-dlp negotiates | only from `tube` commands |

| Claim | Verification |
|-------|--------------|
| No telemetry | the three rows above are the complete set of network calls in `src/levix`; there is no analytics endpoint, no crash reporter and no startup fetch |
| No silent update | `levix update` prints `pip install --upgrade levix` / `pipx upgrade levix` / "standalone: download … from the GitHub Releases page" and states "LEVIX does not modify its own installation"; it never spawns pip |
| No DNS from the "hacker" module | `hacker/core.local_hostname` uses `socket.gethostname()` with a `platform.node()` fallback and avoids `socket.getfqdn` explicitly because it "queries DNS"; the module's other reads are `hosts`, `resolv.conf`, `nsswitch.conf`, capped at `MAX_READ_BYTES = 262_144` |
| Nothing listens | no `socket.bind`, no `listen`, no HTTP server anywhere in the tree |

### Secrets and logs

| Control | Code |
|---------|------|
| Never stored in configuration | no `SCHEMA` key holds a credential; `config set` refuses secret-shaped keys; `Config.load` never reads the secrets store |
| Resolution order | `LEVIX_AI_API_KEY` → OS keyring (`service="levix"`, `user="AI_API_KEY"`) → `Paths.secrets_file`; `get_secret` returns `(value, source)` |
| Honest description of the fallback | `backend()` calls it "plaintext file at … with owner-only permissions (access control, not encryption)", and `doctor` marks it `DEGRADED` rather than pretending the key is encrypted at rest |
| File hardening | `_write_file` creates `secrets.json` at `0600` (`secrets.py:128-139`), so the mode never depends on a later call succeeding; `_harden` then `chmod`s it again and, on Windows, runs `icacls /inheritance:r /grant:r <user>:F` (`secrets.py:142-163`). `chmod` failures are swallowed because a key already on disk must not crash the command that stored it - and `tests/test_secrets.py::test_a_chmod_that_fails_leaves_no_more_access_than_the_open_gave` asserts the file is still owner-only when it is refused |
| Opt out of plaintext | `LEVIX_DISABLE_FILE_SECRETS=1` makes `set_secret` raise a `RuntimeError` telling the user to set the environment variable; `backend()` then reports `("none", "no keyring installed and file store disabled")` |
| Never printed | `levix ai check` prints the key *source*, not the value; `config show`/`list` mask secret-shaped keys; `context.secret` logs `"secret %s resolved from %s"` with the name and the source, never the value |
| Never a command-line argument | `levix ai key set` reads the key with `typer.prompt(..., hide_input=True)`, so it stays out of shell history, out of the process list and out of any crash report that carries argv; with no terminal to prompt in it raises `ConfigError` naming the environment variable rather than accepting the key from a pipe |
| Never logged | `logging_setup.RedactFilter` with four patterns — bearer tokens, `sk-…`, `ghp_`/`gho_`/`github_pat_…`, and any `*api_key|token|secret|password* = <value>` — attached to both the handler and the logger, so it "cannot be bypassed by a module that logs a formatted exception containing a bearer token"; nothing is written to stdout; rotation is 512 KB × 3 backups. `tests/test_logging.py` asserts all of that (`::test_a_key_never_reaches_the_log_file`, `::test_a_handler_without_a_filter_still_gets_redacted`, `::test_the_only_console_handler_writes_to_stderr`) |

### Terminal integrity

| Threat | Mitigation |
|--------|------------|
| A file name or video title containing `[bold]` restyling the console | `escape()` in `_plain`, `_show`, `printable`, `safe_text`/`safe_name`; in the modules, each file's own render helper — `tube/cli._show`, `hacker/cli._show`, `music/cli._show`+`_clip`, `files/cli.show`, `ai/cli._show`, `systempulse/cli` via `terminal.markup_safe`, and `terminal.markup_safe` across the dashboard |
| A name that the console cannot encode crashing the command that prints it | `encode_safe()` — control characters to `\xNN`, unencodable characters backslash-replaced, forced onto one line (`main._plain` splits on newlines first, so a message LEVIX authored with a line break in it is not flattened to literal `\x0a`) |
| A name containing `[/weird]` aborting the command that prints it | the same escape sites: Rich reads an unmatched closing tag as a `MarkupError` rather than deleting it, so the missing-escape failure mode includes a traceback and a non-zero exit, not only a silently shortened string (`tests/test_markup_safety.py`) |
| ANSI injection from tool output | `hacker/core.decode_console_output` decodes bytes to text without emitting raw escape sequences, and `terminal.detect` reports `protocol_enabled` rather than assuming it |
| Two Textual apps fighting over one TTY | `UiSpec` documents that one TTY cannot host two apps; the dashboard calls `App.suspend()` before `spawn.run` so exactly one app owns the screen at a time |
| Escape sequences emitted into redirected output | `dashboard_cmd` refuses when `sys.stdout` or `sys.stdin` is not a TTY, exit 2 (`tests/test_dashboard.py` asserts no traceback) |

### Plugins

| Property | Detail |
|----------|--------|
| Trust model | a plugin is ordinary Python in the same interpreter. `plugins_cmd.py:3-7` states that install and uninstall are deliberately unimplemented "before a command that installs arbitrary code can honestly exist" |
| Disclosure only | `permissions` is never consulted on a decision path; see `PERMISSIONS.md` |
| Origin is not self-declared | the registry overwrites `origin` and `provider` from `entry_point.dist`, so a plugin cannot claim to be official (`tests/test_registry.py`) |
| Broken plugin is contained | `entry_point.load()` is wrapped; a failure becomes a manifest with `cli_path=""` and is surfaced by `plugins list`, `plugins info` and `doctor` |
| Lint posture | ruff selects `S` (bandit rules) tree-wide and ignores only `S603` and `S607`, i.e. subprocess-with-argv and relative executable paths, each of which is justified at its own call site |

## What remains unmitigated

| # | Risk | Why it is not mitigated | Practical exposure |
|---|------|-------------------------|--------------------|
| 1 | **Untrusted third-party plugins** | entry points in LEVIX's environment are imported and executed with no sandbox, no allow-list, no signature and no capability enforcement. A normal subprocess is **not** a sandbox either: `spawn.run` gives the child the same user, the same environment, the same filesystem and the same interpreter, so running a plugin "in a child process" would change only its TTY, not its privileges. The only real isolation would be an OS-level boundary (separate user, container, Job Object) or a capability broker, and neither exists in this tree | anyone who can `pip install` into LEVIX's environment can run code as the user whenever the user runs `levix` |
| 2 | **Config file and database permissions** | `Paths.ensure()` creates directories with default umask/ACLs; `config.toml` is written by `tomlkit` with no hardening, and `levix.db` inherits the data directory's permissions. Only `secrets.json` is chmod-ed. On POSIX a shared `~/.local/share/levix` with permissive parents exposes provider URLs, models, history and high scores | another user on a shared machine can read the user's configuration and command history |
| 3 | **The plaintext secret fallback** | it is access-controlled plaintext, explicitly not encryption. A `chmod` failure no longer exposes the key, because the file is created at `0600` and `tests/test_secrets.py` asserts that with the `chmod` refused; on Windows the `icacls` reset is still best-effort, and its result is asserted only by a case that skips off Windows | if the keyring extra is absent, the key sits in a JSON file that is readable only by its owner - by ACL, not by cipher. Anyone who is the owner, or who already has root, has the key |
| 4 | **Model-proposed commands** | LEVIX refuses shell syntax and requires a typed `RUN`, but it does not classify the command: `rm -rf` inside an argument list is still `rm -rf` with the user's own privileges. The protection is the human reading the line | a user who types `RUN` without reading authorises the deletion |
| 5 | **Prompt and file content sent to a provider** | `ai explain` sends up to 32 000 bytes per file to whatever `ai.base_url` points at. The cap and the disclosure are mitigations; the egress itself is the feature | a misconfigured `base_url` sends private files to an unexpected server; `levix ai check` exists to make this visible |
| 6 | **`$EDITOR` trust** | `config edit` executes whatever `EDITOR`/`VISUAL` names, resolving to notepad/vi only when neither is set | an attacker who controls the environment controls execution — but they already control the user's session |
| 7 | **`PATH` precedence** | `shutil.which` follows the OS order; executing the resolved path removes the second lookup but cannot remove the first | a writable directory earlier on `PATH` can substitute `ffmpeg`, `mpv` or a proposed program |
| 8 | **Downloaded content** | yt-dlp's output, a remote site's title, is rendered safely but is still untrusted data on disk; nothing verifies or scans it | a file name chosen by a remote site |
| 9 | **Installation integrity** | no dependency pinning hashes (no lock file), no wheel signature verification, no `pip install --require-hashes` story in the docs | supply-chain substitution at install time, outside LEVIX's control |
| 10 | **Log content beyond secrets** | `RedactFilter` targets credentials; a file path, host name or URL typed by the user is logged verbatim in `levix.log` and in the traceback tail of an unexpected error | anyone reading the log directory |

## Known gaps

1. **`Permission` cannot express database writes or TTY control**, so the disclosure set
   (seven members) does not cover two things official modules actually do. Details and the
   per-module table: `PERMISSIONS.md`.
2. **Redaction is regex-based, not schema-based.** A provider that returns a key in an
   unexpected shape — a JWT in an error body, for instance — is logged verbatim.
   `tests/test_logging.py` pins exactly what the four patterns do cover (six shapes, a real
   `LogRecord`, a real log file, and a handler that carries no filter of its own), so this gap
   is now the documented edge of the implementation rather than an untested assumption.
3. **No verification that the update check's response is a version and not an instruction.**
   `update_cmd._fetch_latest` parses JSON and compares numeric prefixes, and prints a
   command string the user must run; there is no signature on `latest`, so a hostile proxy
   could advertise a version that does not exist. It cannot make LEVIX install anything,
   because it never does.
4. **No test asserts the absence of `shell=True` or of a network call at import time.** The
   tube option-absence tests and `tests/test_router.py`'s heavy-load check are the closest;
   a project-wide guard would be cheap and does not exist.
5. **Asserted on Windows only, except where it is now asserted on POSIX too.** CI runs #4
   (`5b047ad`), #5 (`75daed2`) and #6 (`3d460df`) execute the tree on Ubuntu and macOS
   and nothing there fails, so the POSIX *branches* are no longer unread. Run #6 also closed the
   one behaviour this page used to list as code-only: `tests/test_secrets.py` stats the mode of a
   real `secrets.json`, and its three POSIX cases - which skip on this machine, where `st_mode`
   answers `0o666` for any ordinary file - ran on the Ubuntu and macOS columns instead of skipping
   and reached no failure. So the `0600` is now observed on a POSIX filesystem; the Windows half
   (the real `icacls` output) has been asserted here all along. What still has no
   observation behind it: every
   keyring test replaces `secrets._keyring` with a fake (`tests/modules/test_ai.py:568-599`,
   `:922-990`) so no OS keyring has ever been asked on any platform, and the suite runs under
   `LEVIX_HOME`, so `paths`' real POSIX layout is resolved with an override rather than the
   platform's own defaults. `SECURITY.md` keeps "verified on Windows only" among its gaps for
   that reason, and this page's mitigation rows are evidence of what was *read and run*, not of
   what was observed on a POSIX box.

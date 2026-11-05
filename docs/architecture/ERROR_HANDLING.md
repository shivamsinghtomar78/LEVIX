# Error handling

One table, one hierarchy, one classifier. `src/levix/errors.py` defines the codes,
`src/levix/main.py` owns the mapping from exception to code, and nothing else in the tree
calls `sys.exit`.

## Exit codes

Reproduced verbatim from `errors.py:9-31` (`EXIT_*` and `EXIT_CODE_MEANINGS`), verified at
runtime for the rows marked ✓.

| Code | Constant | Meaning | Producer | Verified |
|------|----------|---------|----------|----------|
| 0 | `EXIT_OK` | success | a command that returns nothing | ✓ `levix --version` |
| 1 | `EXIT_RUNTIME` | unhandled runtime error | `_report_unexpected`, `LevixError` itself, `FilesError`, `MusicError`, `ArcadeError` | ✓ `levix music -h` with numpy absent |
| 2 | `EXIT_USAGE` | bad command line usage (click default) | click `UsageError`/`BadParameter`, `UnsafePathError`, `RequestError`, `ArcadeUsage`, `SystemExit` with a string code | ✓ `levix monitor --nope` |
| 3 | `EXIT_MISSING_DEPENDENCY` | an optional dependency or extra is not installed | `DependencyError` from the gate, `router._forward` for an unloadable manifest, `doctor.exit_code_for` | ✓ `levix monitor cpu` with psutil blocked |
| 4 | `EXIT_UNKNOWN_MODULE` | no module or command with that name | `main._classify` on click's `No such command`, `plugins info` raising `typer.Exit(code=4)` | ✓ `levix nostalgia` and `levix plugins info nope` |
| 5 | `EXIT_CONFIG` | configuration file or value is invalid | `ConfigError` from `Spec.coerce`, `Config.load`, `create-module` name rules | ✓ `levix config set monitor.interval_seconds 999` |
| 6 | `EXIT_CANCELLED` | the user declined the confirmation prompt | `UserCancelledError` from `approve.require_approval` | ✓ unit-tested through `files delete` and `arcade` |
| 7 | `EXIT_TOOL_FAILED` | an external tool ran and failed (ffmpeg, mpv, …) | `ExternalToolError`, `tube/core.launch` on `OSError`, `tube/core.ensure_ffmpeg`, `music.BackendError` | |
| 8 | `EXIT_PROVIDER` | a network or model-provider call failed | `ProviderError` from `ai/core`, `tube/core._run`, `update_cmd._fetch_latest` | ✓ `levix ai ask "hi"` with no key configured |
| 130 | `EXIT_INTERRUPTED` | interrupted (Ctrl+C) | `KeyboardInterrupt`, click `Abort` | ✓ unit-tested |

Scripts may rely on these numbers; `EXIT_CODE_MEANINGS` is the machine-readable form of
the same table and is what `levix doctor --json` can reason over.

## Hierarchy

```
Exception
├── LevixError(message, *, hint=None)          exit 1   base: clean message, no traceback
│   ├── DependencyError                        exit 3   also raised in modules/music/core.py: a URL without yt-dlp or without ffmpeg
│   ├── UnknownModuleError                     exit 4   (declared, never raised — see gaps)
│   ├── ConfigError                            exit 5
│   ├── UserCancelledError                     exit 6
│   ├── ExternalToolError                      exit 7
│   ├── ProviderError                          exit 8   also raised in modules/music/core.py: yt-dlp failed to fetch, or reported no file path
│   ├── FilesError                             exit 1   modules/files/core.py
│   ├── UnsafePathError                        exit 2   modules/files/core.py
│   ├── RequestError                           exit 2   modules/files/core.py and music/core.py
│   ├── MusicError                             exit 1   modules/music/core.py
│   ├── BackendError                           exit 7   modules/music/core.py
│   │   ├── UnsupportedFormatError             exit 7   (inherits)
│   │   └── AudioDeviceError                   exit 7   (inherits)
│   ├── ArcadeError                            exit 1   modules/arcade/scores.py
│   └── ArcadeUsage                            exit 2   modules/arcade/scores.py
├── KeyboardInterrupt                          → 130
├── SystemExit                                 → code, None → 0, str → stderr + 2
└── everything else                            → 1 after a traceback tail
```

| Mechanic | Detail |
|----------|--------|
| Constructor | `LevixError.__init__(message, *, hint=None)` stores the message as the exception argument and assigns `hint` on the instance only when given, so a subclass may keep a class-level `hint` |
| `message` property | `str(self)` — the rendering layer never touches `args` |
| Subclass cost | a new failure class is two lines: a subclass and `exit_code = EXIT_…` |
| Plugin use | `sdk.py` re-exports all seven engine errors, so a plugin's raise reaches `main` with its code intact |

## Classification

`main()` wraps everything in `try / except BaseException / finally`, and `_classify` runs
in this order. The order matters: `LevixError` first so a module's own code always wins,
`Exit` before `UsageError` so a Typer exit is not read as a usage problem, and the
name-based tests after the two `isinstance` tests that are safe.

| # | Test | Result |
|---|------|--------|
| 1 | `isinstance(exc, LevixError)` | `_render_error(exc)` then `exc.exit_code` |
| 2 | `isinstance(exc, KeyboardInterrupt)` | `sys.stderr.write("\ninterrupted\n")` then 130 |
| 3 | `isinstance(exc, SystemExit)` | `code is None` → 0; `int` → the code; anything else → written to stderr, 2 |
| 4 | `"Abort" in MRO names` | 130 |
| 5 | `"Exit" in MRO names` | `int(exc.exit_code or 0)` |
| 6 | `"UsageError" or "BadParameter" in MRO names` | if `_NO_SUCH_COMMAND` matches the message → `_show_alternatives` + 4; else `_show_click` + `exc.exit_code or 2` |
| 7 | `"ClickException" in MRO names` | `_show_click` + `exc.exit_code or 1` |
| 8 | otherwise | `return None` → `_report_unexpected` |

**Returning `None` is the design.** `_classify` maps only failures it can explain. A
genuine bug falls through to `_report_unexpected`, which logs the traceback at `error`
level, prints `<ExceptionType>: <message>`, tells the user "This is a LEVIX bug.
`levix doctor` reports the environment; the traceback tail is below." and prints the last
1500 characters of the formatted traceback. Exit 1. Converting an unknown exception into a
tidy one-line message would hide the bug from the person best placed to fix it.

### Why class names and not `isinstance`

`main.py:1-7` and the tree itself give two independent reasons, both verified:

| Reason | Evidence |
|--------|----------|
| Typer 0.27.3 vendors click. `typer.BadParameter.__mro__` is `BadParameter → UsageError → ClickException → TyperException`, all from `typer._click.exceptions`; `isinstance(exc, click.UsageError)` is therefore **False** for the exceptions the CLI actually raises. | measured |
| Control-flow exceptions are `RuntimeError` subclasses: `typer.Exit.__mro__` = `Exit → RuntimeError → Exception`, same for `Abort`. Matching on the class *name* set avoids both accidentally catching a real `RuntimeError` and accidentally missing an `Exit`. | measured |
| The same fork reason makes `click.Group` subclassing useless for routing — see `COMMAND_ARCHITECTURE.md` | `issubclass(typer.core.TyperGroup, click.Group)` is False |

```python
names = {klass.__name__ for klass in type(exc).__mro__}
```

## Rendering

| Function | Output | Rule |
|----------|--------|------|
| `_render_error(exc)` | `error: <message>` on stderr, bold red label; then `hint: <hint>` in dim, **only when `hint and hint not in exc.message`** | prevents the duplication seen when a `DependencyError` builds its install line into the message and also passes it as `hint` |
| `_plain(value)` | `"\n".join(escape(encode_safe(line)) for line in str(value).splitlines())` (`main.py:108-124`) | closes two crashes at once, per its docstring: Rich reads the `[...]` inside a typed URL, path or module name as a style tag and deletes it, and a cp1252 console raises `UnicodeEncodeError` on a name it cannot encode — "the report would no longer match the thing that failed". Line by line, because `encode_safe` is one-line by design: a message LEVIX authored with a break in it keeps that break. It closes nothing else, and that is deliberate: Rich's second parser over a printed `str` reads `:abc:` as the emoji whose shortcode that is, and there is no escaping for a colon that means itself — that one is switched off on the console, two rows below |
| `_show_alternatives(name)` | `unknown command: <name>` plus `available: <sorted module names>` plus a pointer to `levix -h` | wrapped in `try/except` — "a hint must never replace the real error"; if discovery fails the hint is simply skipped |
| `_show_click(exc)` | `exc.show()`, falling back to `<Type>: <exc>` | the vendored `show()` may itself fail on a dumb terminal |
| `_report_unexpected(exc, args)` | logs with `exc_info=True`, prints type, message, the LEVIX-bug sentence, then `_plain(traceback)[-1500:]` | the tail, not the whole, because a chained traceback from Typer is kilobytes |

All five print through `terminal.new_console(stderr=True, highlight=False)`
(`terminal.py:160-176`), which is `Console(..., emoji=False)`: diagnostics never go to
stdout, so `levix config list ai | grep …` is not polluted by a warning, and the text the
report quotes back is the text that was typed. Before that console was a factory, `levix
music play magnet:abc` named the link it refused as `magnet` + U+1F524 + ` only http and
https are played from a URL` — `:abc:` is a live shortcode in Rich's table and the colon
that ended the sentence went with it (`tests/test_markup_safety.py::test_a_refused_link_is_quoted_back_as_it_was_typed`).

## Module behaviour under failure

| Module command | Failure | Code |
|----------------|---------|------|
| any `levix <module> …` with the extra absent | `deps.ensure_dependencies` → `DependencyError` | 3 |
| `levix <broken-module> …` | `router._forward` sees `cli_path=""` → `DependencyError` with the load error as summary | 3 |
| `levix tube …` where yt-dlp raises | `core._run` maps it to `ProviderError`, re-raising any `LevixError` untouched | 8 |
| `levix tube --format bv*+ba/b` without ffmpeg | `core.ensure_ffmpeg` → `ExternalToolError` with the OS install command | 7 |
| `levix tube play URL` with no player on PATH | `ExternalToolError` naming the candidates tried | 7 |
| `levix files delete X` outside `--root` | `UnsafePathError` with a hint to widen the wall | 2 |
| `levix files delete DIR` without `--recursive` | `RequestError` | 2 |
| `levix files copy A B` where B exists | `require_approval(…, destructive=True, prompt_word="OVERWRITE")` → decline is `UserCancelledError` | 6 |
| `levix ai command "…" --run` | typed `RUN`; `ai.require_approval=false` runs without asking and says so in bold yellow | 6 / 7 |
| `levix ai …` with no key | `ProviderError` naming the resolution order | 8 |
| `levix game scores --clear` | `require_approval(destructive=True, prompt_word="DELETE")` | 6 |
| `levix music play X` on a dead device | `AudioDeviceError` (via `BackendError`) | 7 |
| `levix music play URL` with no `yt_dlp`, or no ffmpeg on PATH | `DependencyError` naming `pip install "levix[tube]"` in the first case and this platform's ffmpeg command in the second | 3 |
| `levix music play ftp://…` or `file:///…` | `RequestError`: the scheme is refused before either tool is looked for, so a link this command will not fetch is never reported as a missing dependency | 2 |
| `levix music play URL` where yt-dlp raises | `core._run` maps it to `ProviderError`, quoting the tool's own reason inside the one message; yt-dlp's duplicate line is swallowed by the logger it is given | 8 |
| `levix music play URL` whose reported path is outside the URL's own cache folder, or whose bytes are over `STREAM_MAX_BYTES` | `BackendError` - raised before the file is opened or decoded | 7 |
| `levix dashboard` with a redirected stdout or stdin | `typer.Exit(code=EXIT_USAGE)` with an explanation | 2 |
| `levix update` when pypi.org is unreachable | `ProviderError` | 8 |
| Ctrl+C anywhere | `KeyboardInterrupt` → `\ninterrupted\n` | 130 |

## The finally block

```python
finally:
    if ctx is not None:
        try: ctx.close()
        except Exception: pass
    duration_ms = (time.perf_counter() - started) * 1000.0
    _record(getattr(ctx, "obj", None), tuple(args), exit_code, duration_ms)
```

| Rule | Reason |
|------|--------|
| `ctx.close()` swallows everything | closing must not change the exit code |
| `obj` is read here, **after** `invoke`, via `getattr(ctx, "obj", None)` | the root callback builds it during invoke; capturing it earlier handed `_record` a `None` every time and the dashboard's history stayed empty. `main.py:53-56` records that lesson and `tests/test_router.py:240` now asserts a run command reaches the shared history |
| `_record` swallows everything, then logs at debug | "Failing to record must never fail the user's command" |
| `_record` returns early when `obj is None`, argv is empty, or `argv[0].startswith("-")` | help and version are not commands |

## Logging as a failure surface

| Property | Value |
|----------|-------|
| Logger | `logging.getLogger("levix")`, `propagate = False` |
| File | `Paths.log_dir / "levix.log"`, `RotatingFileHandler(maxBytes=512_000, backupCount=3, encoding="utf-8")` |
| Level | `config.get("logging.level")`, default `info`; unknown names fall back to `INFO` |
| Disabled | `logging.file_enabled=false`; `tests/conftest.py` sets `LEVIX_LOGGING_FILE_ENABLED=false` so no test writes into a user's log |
| Unwritable directory | `OSError` is tolerated with a warning — "A machine we cannot write logs to must still run the command" |
| Fallback | a stderr handler at `WARNING` only when no handler was attached at all |
| Redaction | `RedactFilter` on the handler *and* the logger, four patterns: `authorization: bearer <tok>`, `sk-…`, `ghp_/gho_/github_pat_…`, and any `*api_key|token|secret|password* = <value>` |
| stdout | never written to, "because interleaved log lines would corrupt" Rich and Textual |

## Known gaps

1. **Class-name matching is a name-based contract.** `_classify` inspects `__name__`, not
   identity, so a plugin exception called `Exit`, `Abort`, `UsageError` or
   `ClickException` would be classified as though it were click's. `typer.Exit` and
   `typer.Abort` are ordinary `RuntimeError` subclasses, so a plugin raising a class named
   `Exit` for an unrelated reason silently gets its `exit_code` attribute interpreted as a
   status. Low probability, total surprise; a comment in `main.py` would be cheap.
2. **A bad module *subcommand* is reported as exit 4 with module suggestions.** Verified:
   `levix monitor platform` prints `unknown command: platform` / `available: ai, files,
   game, hacker, monitor, music, tube` and exits 4. `_classify` matches click's
   `No such command` without knowing the error came from a forwarded sub-app, so the user
   is told to pick a module when the fix is `levix monitor -h`. This is the same
   mechanism as the intended `levix nostalgia` → 4 path.
3. **`UnknownModuleError` is never raised.** Exit 4 comes from `_classify`'s regex path and
   from `plugins info` raising `typer.Exit(code=4)` directly (`plugins_cmd.py:70-72`). The
   class exists for API completeness, so a plugin author who raises it expecting `hint`
   rendering gets a correct code but nothing else that is not already available.
4. **`EXIT_RUNTIME` is the default for `LevixError`**, so a module that subclasses
   `LevixError` and forgets `exit_code` gets 1 — a crash code — for a routine failure. Two
   module files define a second subclass precisely for this (`FilesError` 1 versus
   `RequestError` 2; `MusicError` 1 versus `RequestError` 2). Nothing enforces choosing
   deliberately.
5. **`hint` suppression is substring-based.** `_render_error` omits the hint when
   `hint in message`. `DependencyError` builds its message to contain the install line, so
   the hint is suppressed — intended — but a future error whose message merely happens to
   contain the hint text would also lose it.
6. **No error is ever raised from `_record`'s failure path**, by design, which means a
   silently broken history (wrong permissions on the data directory, disk full) is visible
   only in the debug log; `levix doctor` checks that the migrations apply, not that rows
   are being written, so a read-only data directory still reports `storage OK` while
   history stops accumulating.
7. **`SystemExit` with a string code prints without a newline** (`sys.stderr.write(str(code))`)
   and then returns 2. Only reachable through a direct `sys.exit("text")`, which no LEVIX
   code does, but the missing newline would concatenate with the next prompt.
8. **Tests do not cover the interrupt paths as a process.** `_classify`'s `Abort`,
   `KeyboardInterrupt` and `SystemExit` branches are exercised through `run_cli` for
   `Exit` and `UsageError` in `tests/test_router.py`; the 130 paths are asserted only via
   `approve`'s cancellation, which is a different exception. A real Ctrl+C through a
   suspended Textual child is not covered.

### Closed since the first draft of this page

* **Multi-line messages are no longer flattened.** `_plain` used to call `encode_safe` on
  the whole string, so an authored break reached the screen as literal `\x0a` text:
  `…and none was found.\x0a  set the LEVIX_AI_API_KEY…`. It now splits first and escapes
  per line (`main.py:108-124`), because `encode_safe` is deliberately a one-line function
  — control characters and unencodable bytes still become `\xNN`, but a break we wrote
  stays a break. Verified with the real binary: `levix ai ask "hi"` with no key configured
  prints `error: … needs an API key and none was found.` and `hint: set the
  LEVIX_AI_API_KEY environment variable, run \`levix ai key set\`, or store the key in the
  OS keyring …` on separate lines with no `\x0a` anywhere, and the exit-3 gate message
  keeps its second `  install it with: pip install "levix[tube]"` line. Covered by
  `tests/test_deps.py::test_a_two_line_refusal_stays_two_lines_on_the_screen`.

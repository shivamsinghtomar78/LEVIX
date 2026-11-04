# AI (`levix ai`)

A chat assistant in the terminal, talking to an OpenAI-compatible server or to Ollama over
plain HTTP with `httpx`. No vendor SDK is used: both adapters build request specs and parse
documented wire formats, so a wire regression is a test failure rather than a silent
behaviour change.

Source: `src/levix/modules/ai/` (`__init__.py` manifest, `cli.py` command surface, `core.py`
providers, prompts, stream parsing, key handling and the guarded run path). Entry point:
`levix.modules.ai.cli:build_app`. Declared documentation path: `docs/modules/AI.md`.

## The posture the module promises

Quoted from the manifest docstring, because it is the contract this page documents:

> `The security posture this module promises: a model-proposed command is never executed`
> `without a typed confirmation in a real terminal, `--yes` cannot buy that confirmation,`
> `and the API key is read through `levix.secrets` and never printed, logged or echoed.`

and from `core.py`:

> `Nothing here logs a key, uses `shell=True`, or contacts a host`
> `other than the one the user configured.`

Both hold in the code as written; the exceptions worth knowing are in Known gaps.

## What is actually implemented

Six commands, registered from the manifest so `levix ai -h` and the dashboard cannot
disagree, plus two hidden aliases:

| Command | Alias | Purpose |
| --- | --- | --- |
| `levix ai ask [PROMPT]` | `levix ai q` | Send one prompt, print the reply; `--stream` follows tokens. |
| `levix ai explain FILE...` | | Explain files; only a capped prefix of each is sent, and the truncation is reported. |
| `levix ai command REQUEST` | `levix ai cmd` | Propose exactly one shell command; `--run` offers to execute it after a typed `RUN`. |
| `levix ai models` | | List what the provider reports, or say it cannot. |
| `levix ai check` | | Print provider, URLs, key source and options. Offline unless `--live`. |
| `levix ai key set` / `key clear` | | Store or forget `AI_API_KEY` — prompted with echoing off, never an argument. |

`q` and `cmd` are also top-level shortcuts for the commands they name: `levix q "hi"` is
`levix ai ask "hi"` (`router._attach` prefixes `ask` onto the forwarded argv). `key` is a
group, not a flat command, because two verbs share one subject and a value must never
appear in a command name.

There is no chat session, no history file, no conversation memory and no tool/function
calling: every command is a single request/response turn. There is no image input, no
embedding endpoint and no retry/backoff logic. `levix ai` with no subcommand prints the
help and exits 2.

## Providers and endpoints

`ai.provider` selects an adapter; both are chosen by `core.provider_for()`.

| | `openai-compatible` | `ollama` |
| --- | --- | --- |
| Root URL | `ai.base_url` (default `https://api.openai.com/v1`) | `ai.ollama_url` (default `http://127.0.0.1:11434`) |
| Completion | `POST {root}/chat/completions` | `POST {root}/api/chat`; `POST {root}/api/generate` with `"raw": true` for `command` |
| Model list | `GET {root}/models` | `GET {root}/api/tags` |
| Streaming | `data:` SSE frames, ended by `data: [DONE]` | newline-delimited JSON objects, ended by `"done": true` |
| Auth | `Authorization: Bearer <key>` **only when a key was found** | none ("Ollama needs no API key; its /api endpoints are unauthenticated by default, so keep it on localhost.") |
| Sampling knobs | `temperature`, `max_tokens` (omitted when 0) | `options.temperature`, `options.num_predict` |

URLs are joined by `AIConfig.url()`, which strips trailing `/` from the root and leading
`/` from the path. `ai.base_url` is a *root*, so it must already include the version prefix
(`/v1`) for an OpenAI-compatible server; `levix ai check` prints the assembled
`completion url` and `models url` precisely so the mistake is visible before a request is
sent.

One `httpx.Client` is built per command by `core.build_client(timeout=...)`, inside a
`with` block; that single construction point is what lets the tests inject a
`MockTransport`.

## Configuration

Flags beat configuration, and nothing is invented when both are silent
(`core.resolve_config()`).

| Key | Type / bounds | Packaged default | Overriding flag |
| --- | --- | --- | --- |
| `ai.provider` | str, one of `openai-compatible`, `ollama` | `openai-compatible` | `--provider` |
| `ai.model` | str | `gpt-4o-mini` | `--model`, `-m` |
| `ai.base_url` | str | `https://api.openai.com/v1` | `--base-url` |
| `ai.ollama_url` | str | `http://127.0.0.1:11434` | `--ollama-url` |
| `ai.temperature` | float, 0–2 | `0.2` | `--temperature` |
| `ai.max_tokens` | int, 1–32000 | `1024` | `--max-tokens` |
| `ai.require_approval` | bool | `true` | none — deliberately not overridable on the command line |
| — | timeout | 60 s (`core.DEFAULT_TIMEOUT`) | `--timeout` |

Environment overrides follow the usual `LEVIX_<SECTION>_<KEY>` rule
(`LEVIX_AI_MODEL`, `LEVIX_AI_BASE_URL`, `LEVIX_AI_PROVIDER`,
`LEVIX_AI_REQUIRE_APPROVAL`, …). `LEVIX_AI_API_KEY` and `LEVIX_HOME` are **exempted** in
`config._env_overrides()` — the key never becomes a configuration value, because config
files are plain text and `levix config show` masks secret-shaped keys.

A rejected value fails before any socket opens:

```
error: ai.provider must be one of openai-compatible, ollama, got 'bogus'      (exit 5)
error: --timeout must be a positive number of seconds, got 0                  (exit 5)
error: ai.base_url is empty, so there is no provider to talk to               (exit 5)
hint: set ai.base_url with `levix config set` or pass the matching flag
```

### Per-command options

`MANIFEST.commands` lists six entries: `ask`, `explain`, `command`, `models`, `check` and the
`key` group. All five model-facing commands accept `--provider`, `--base-url`,
`--ollama-url` and `--timeout`.
`--model` is accepted by `ask`, `explain`, `command` and `check`; `--temperature` and
`--max-tokens` only by `ask`, `explain` and `command` (`check` prints them, it does not
override them). `--show-usage` is accepted by `ask`, `explain` and `command`.
`models` takes `--provider`, `--base-url`, `--ollama-url` and `--timeout` and nothing else.
`key` is a subgroup, not a flag-carrying command: `key set` and `key clear` take no options,
and a bare `levix ai key` shows the group help and exits 2.
Command-only options:

| Command | Option | Default | Effect |
| --- | --- | --- | --- |
| `ask` | `PROMPT` (argument) | `""` | Empty means "read the prompt from stdin". |
| `ask` | `--system`, `-s` | built-in | Replaces the default system message. |
| `ask` | `--stream` | off | Print tokens as they arrive. |
| `explain` | `FILES...` (argument) | required | `Error: Missing argument 'files'.` if absent (exit 2). |
| `explain` | `--focus` | none | Appended to the instruction sentence. |
| `explain` | `--max-bytes` | `32000` | Per-file read cap; must be positive. |
| `command` | `--run` | off | Offer to execute the proposal. Without it the command never runs. |
| `command` | `--yes`, `-y` | off | "Accepted and ignored: only a typed RUN runs a command." |
| `check` | `--live` | off | One read-only request to the model-list endpoint. |
| `models` | — | | Sends exactly one `GET`. |

## The API key

`core.SECRET_NAME` is `AI_API_KEY`. `levix.secrets.get_secret()` resolves it in this order
and reports which layer answered:

1. environment `LEVIX_AI_API_KEY` → source `env`;
2. OS keyring, service `levix`, user `AI_API_KEY` → source `keyring`;
3. owner-only `secrets.json` in the LEVIX data directory, chmod 0600 plus an `icacls`
   grant on Windows → source `file`;
4. nothing → source `none`.

The value itself never leaves the lookup: `LevixContext.secret()` logs only the name and
source, `check` prints the source with an explicit promise, and every provider error is
asserted not to contain the key.

```
key: none (stored as AI_API_KEY; the value is never printed, logged or echoed)
```

`core.resolve_key()` only insists on a key when the target is a non-loopback
`openai-compatible` server; a loopback URL and Ollama are allowed to go unauthenticated.
When it does insist and finds nothing:

```
error: openai-compatible at https://api.openai.com/v1 needs an API key and none was found.
hint: set the LEVIX_AI_API_KEY environment variable, run `levix ai key set`, or store the
key in the OS keyring (service 'levix', user 'AI_API_KEY'). Resolution order is env ->
keyring -> owner-only file, and `levix ai check` shows which one answered without revealing
the value
```

exit 8, on two lines. Captured from the real binary on 2026-11-05; `core.py:149-159` builds
the message and the hint separately, and `main._plain()` escapes each line without flattening
the break between them.

**Writing the key.** `levix ai key set` reads the key with echoing off and stores it through
`LevixContext.store_secret()` → `secrets.set_secret()`, which prefers the OS keyring and
removes any stale file copy; `levix ai key clear` forgets it again. Nothing is a command-line
argument, so the value cannot land in shell history, in the process list or in a crash report,
and the prompts and errors name the key but never its contents. If no keyring backend answers,
the write falls back to the owner-only file and says out loud that the file is access-controlled
plaintext rather than encryption, with `pip install "levix[secrets]"` as the remedy.
`LEVIX_DISABLE_FILE_SECRETS=1` makes that fallback a refusal instead (exit 3), for a machine
where plaintext-on-disk is not acceptable. `levix ai key` with no subcommand prints help and
exits 2.

## `levix ai check`

Offline by default: no `httpx` request, no socket. Real output on a machine with no key:

```
                                levix ai check
+-----------------------------------------------------------------------------+
| provider       | openai-compatible (ai.provider source: default)            |
| model          | gpt-4o-mini                                                |
| base url       | https://api.openai.com/v1                                  |
| ollama url     | http://127.0.0.1:11434                                     |
| completion url | https://api.openai.com/v1/chat/completions                 |
| models url     | https://api.openai.com/v1/models                           |
| temperature    | 0.2                                                        |
| max tokens     | 1024                                                       |
| timeout        | 60s                                                        |
| approval gate  | on - a typed confirmation is required to run a proposed    |
|                | command                                                    |
| httpx          | 0.28.1                                                     |
+-----------------------------------------------------------------------------+
key: none (stored as AI_API_KEY; the value is never printed, logged or echoed)
warning: no key found for AI_API_KEY - looked in LEVIX_AI_API_KEY, then the OS
keyring, then the owner-only file. A request to this non-local host would fail
with exit 8.
no request was sent; pass --live for one read-only probe.
```

The `provider` row names the layer that answered (`default`, `user`, `env` or
`command line flag`). The gate row reads
`OFF in your configuration - commands run without asking` when `ai.require_approval` is
false, and the "would fail with exit 8" warning is suppressed for loopback hosts and for
Ollama.

`--live` performs exactly one read-only `GET` of the model-list endpoint through
`core.ping()` and prints `live: openai-compatible answered with 1 model(s).`, or, when the
server has no model list, `live: openai-compatible answered <url> with 404: reachable.` A
failure here is a provider error and exits 8.

## `ask`, and what stdin does

| Argument | stdin | Result |
| --- | --- | --- |
| present | pipe/file | Stdin becomes *context*: the user message is rewritten as `Context from stdin:\n<text>\n\nRequest: <prompt>`, and the console says `adding 18 bytes of stdin as context`. |
| absent | pipe/file | Stdin **is** the prompt; there is no separate context. |
| present | tty | Normal one-turn request. |
| absent | tty or empty | Usage error: `no prompt given: pass one as an argument or pipe it in` (exit 2). |

`_piped_stdin()` only reads when `sys.stdin` is not a tty, so an interactive shell never
blocks. An empty or whitespace-only argument counts as absent.

The default system message asks for plain text:

> `You are LEVIX ai, a concise assistant running in a terminal. Reply in plain text. The`
> `terminal may not render markdown, colour or non-ASCII glyphs, so do not use them.`

Replies are printed with `markup=False, highlight=False`, so a model answer containing
`[bold]` stays characters. Text the module *does* put through markup — the `models` table,
the `check` rows, a rejected proposal, a provider's own explanation — goes through
`cli._show()` (`cli.py:58-69`), which is `escape(encode_safe(str(value)))`: Rich would
otherwise read a `[4]` inside a model name as a style tag and delete it, a `[/weird]` would
raise `MarkupError` and kill the command, and a cp1252 console would raise on a model name
in a script it cannot encode. `tests/modules/test_ai.py::test_a_model_name_the_server_named_with_brackets_is_printed_whole`
feeds a server response of `gpt-[4]mini` / `org[/weird]` and asserts both print whole.
`--stream` prints each parsed chunk as it arrives
(`core.stream_completion` with a `sink`); the SSE/NDJSON parsers skip comment lines,
non-`data:` lines and empty deltas, and stop at `[DONE]` / `"done": true`. `iter_ndjson_text`
also turns a mid-stream `{"error": "..."}` frame into a provider error, truncated to
`core.ERROR_BODY_CHARS` (240) characters.

`--show-usage` prints `usage: prompt N  completion M  total T  model NAME`, with `-` for any
count the provider did not report; a streamed reply has none by definition, and says so:
`usage: this reply carried no token counts (streamed responses do not include them)`.

## `explain`

`core.read_snippet()` reads at most `--max-bytes` bytes per file, decodes UTF-8 and, on
failure, re-decodes with `errors="replace"` — it never dies on a binary byte. A missing path
(`error: no such file: X`) and a directory (`error: X is a directory; `levix ai explain`
takes files`) are `LevixError`s and exit 1. Truncation is announced **before** the request,
in these words:

```
path: showing the first 32000 of 40000 bytes; the rest was NOT sent to the provider (raise it with --max-bytes)
```

Each file is delimited in the prompt by `--- <path> (<size> bytes) ---`, and a truncated one
ends with `[truncated: only the bytes above were read]`. `explain` never streams.

## `command`, the proposal gate

1. The system prompt is `core.COMMAND_SYSTEM`, formatted with the platform
   (`Windows` / `cmd.exe style (a single executable with its own arguments)` or
   `POSIX` / `/bin/sh style`). It demands one command on line 1, an optional caveat from
   line 2, and `NONE <reason>` when the request needs more than one command. For Ollama the
   request goes to `/api/generate` with `"raw": true`, so no chat template reformats the
   two lines (`core.render_raw_prompt()` writes the `SYSTEM:` / `USER:` / trailing
   `ASSISTANT:` labels itself).
2. `core.extract_proposal()` strips markdown fences (closed or not), a leading
   `assistant:` label, a copied `$ ` or `> ` prompt, and lone fence/label lines. First
   surviving line = the command; the rest = the explanation.
3. Refusals happen before anything could run, and each produces
   `no command offered: <reason>` followed by `nothing has run.`:

   * empty reply → `the model returned nothing usable`;
   * blank first line → `empty command line`;
   * line starting with `NONE` → the model's own reason, or `declined`;
   * the line contains any of `;`, `&&`, `||`, `|`, `>`, `<`, `` ` ``, `$(`, `${`, newline
     or carriage return → `it contains '<token>'; LEVIX runs an argument list, not a shell,`
     `so pipelines, chains and redirection are refused`;
   * `shlex` cannot parse it → `cannot parse: <detail>`;
   * nothing left after parsing → `no executable named`.
4. The proposal is shown in an ASCII-boxed panel titled `PROPOSED COMMAND`, ending with
   `provider <p> model <m> - this text came from a model, not from you`.
5. Without `--run` the command stops there:
   `print-only (the default): nothing ran. Add --run to be asked whether to execute it.`

### With `--run`

The gate is the shared `levix.approve.require_approval()` with `destructive=True` and
`prompt_word="RUN"` — the same oracle `levix files delete` uses, so this module cannot
invent a weaker prompt. Observed on a non-interactive stream:

```
--yes cannot authorize a destructive action; confirming interactively.
? run the model-proposed command: <line>  (argv: 'prog' 'arg')
  type 'RUN' to continue (anything else aborts) > error: no input available; run the model-proposed command aborted
```

exit 6, and the proposed process never starts. `--yes` (or `-y`) is parsed, honoured by no
part of the design, and explicitly neutralised: it cannot authorise a run. When stdin is
not a terminal at all the gate refuses rather than consenting, with
`refusing to run the model-proposed command without a terminal to confirm in: <detail>`
`  pass --yes for a non-destructive action, or run this interactively` (also exit 6).
Anything other than `RUN` — including an empty line — raises
`run the model-proposed command cancelled by user`, exit 6.

If `ai.require_approval` is false, the gate is skipped entirely and the console says, in
these words:

```
ai.require_approval is false: running the proposal without asking, because your configuration opted out of the gate.
```

then runs it. Verified end-to-end: the next lines were
`running: <argv>` , the child's own output, and
`the command finished with exit code 0`. There is no flag to restore the gate for one
invocation, and no configuration key besides `ai.require_approval` itself: the
`general.confirm_destructive` key that used to sit in the schema was read by nothing and
has been removed, because a documented safety property is not a setting.

Execution is `core.run_proposal()`: `shutil.which(argv[0])` first
(`cannot run 'x': it is not on PATH`, exit 7), then `subprocess.run([...], shell=False,`
`timeout=config.timeout, check=False)` with the child attached to the user's terminal. A
timeout is `'<prog>' did not finish within Ns` (exit 7, hint "the process may still be`
`running; check your task manager"), a non-zero child becomes
`'prog' ran and exited with code N` (exit 7) — so a successful run exits 0 and any other
result exits 7, never the child's own code.

## `models`

`core.fetch_models()` treats HTTP 404 as a normal answer meaning "this server offers no
model list", not as a failure, and the command degrades honestly:

```
https://provider.test/v1/models answered HTTP 404. This server does not implement a model
list, which is common for OpenAI-compatible gateways; nothing is guessed.
configured model: gpt-4o-mini at https://provider.test/v1
```

A successful list is a two-column ASCII table (`model`, `detail`; `-` when there is nothing
to say), an empty array prints `the provider answered with an empty list`, and a configured
model that is absent from the list adds
`note: configured model 'gpt-4o-mini' is not in this list; check `levix ai check`.`.

## Failures at the wire

Every non-2xx response becomes a `ProviderError` (exit 8) through
`core._describe_status()`, with a 240-character excerpt of the server's body appended when
there is one, and the key is never included:

| Status | Message |
| --- | --- |
| 401 / 403 | `<provider> rejected our credentials with HTTP N for <url>.` + hint about `levix ai check` |
| 404 | `<provider> answered HTTP 404 for <url>.` + hint about `levix ai models` |
| 429 | `<provider> rate limited this request (HTTP 429) at <url>.` |
| 5xx | `<provider> failed the request at <url> with HTTP N.` |
| other | `<provider> answered HTTP N for <url>.` |

Transport problems are mapped too: `cannot reach <provider> at <url>: ConnectError`
(hint: "is the server running and the URL right? `levix ai check --live` tests it"),
`<provider> did not answer <url> within Ns (change --timeout): ConnectTimeout`, and
mid-stream `stalled` / `stream … failed` variants. A 2xx body that is not JSON, a chat
response with no `choices`, or a choice with no textual content are all provider errors
naming the provider and the keys it did send.

## What this module touches

| Aspect | Fact |
| --- | --- |
| Declared permissions | `{NETWORK, SECRET_READ, SECRET_WRITE, FS_READ, SUBPROCESS}`. |
| Network | One request per command to `ai.base_url` / `ai.ollama_url` only; `ask`/`explain`/`command` = 1 POST, `models` = 1 GET, `check` = 0 (1 with `--live`), `key` = 0. |
| Secrets | Reads `AI_API_KEY` through `levix.secrets`; writes it only when you run `levix ai key set` (`LevixContext.store_secret` → `secrets.set_secret`), deletes it with `key clear`; never prints, logs or echoes the value, and the value is never a command-line argument. |
| Files read | The config chain, and the `--max-bytes` prefix of each `explain` argument. `read_snippet()` does **not** apply the `files` module's path wall: any path you name is read. |
| Files written | None by the module itself. |
| Subprocess | Only `core.run_proposal()`, only after `RUN` (or an explicit config opt-out), `shell=False`, single program resolved via `shutil.which`. |
| Configuration written | Never. |
| Database rows | One `levix_command_log` row per invocation, written by `levix.main._record` like every other command. The prompt text is *not* stored; only argv is, so a prompt passed as an argument appears in `levix dashboard` history. |
| Log file | `obj.logger.debug("ai request to %s (key source: %s)", ...)`: the description and the source name, never the value. |

## Examples

```bash
levix ai check
levix ai check --live
levix ai models --provider ollama
levix ai ask "what does a WAL checkpoint do?"
git diff | levix ai ask "summarise this change"
cat error.log | levix ai ask
levix ai ask "be brief" --stream --show-usage --temperature 0
levix ai explain src/levix/approve.py --focus "why --yes is neutralised"
levix ai explain big.log --max-bytes 2000
levix ai command "list the five largest files here"
levix ai command "list the five largest files here" --run        # then type RUN
LEVIX_AI_API_KEY=... levix ai ask hi
levix ai ask hi --provider ollama --model llama3 --ollama-url http://127.0.0.1:11434
levix config set ai.provider ollama
```

## Exit codes and troubleshooting

| Code | Meaning here | How to tell |
| --- | --- | --- |
| 0 | A reply was printed (even an empty one), the gate ran a command successfully, or `check`/`models` answered. | `the provider returned an empty answer` is still exit 0. |
| 1 | `explain` on a missing path or a directory, or an internal error. | `error: no such file: <path>`. |
| 2 | Usage: `levix ai` alone, missing `files` argument, `--max-bytes 0`, no prompt and no stdin. | `Error: Invalid value: no prompt given: …` |
| 3 | `httpx` not installed. **Not reliably reachable** — see Known gap 1. | expected `error: module 'ai' needs httpx is not installed`; what actually happens is `unexpected error: ModuleNotFoundError` and exit 1. |
| 4 | Unknown module name. | `unknown command: aii`. |
| 5 | Bad `ai.*` value from any layer, empty root, non-positive `--timeout`. | `error: ai.provider must be one of openai-compatible, ollama, got 'bogus'` |
| 6 | The proposal was declined, or there was no terminal to decline it in. | `--yes cannot authorize a destructive action; confirming interactively.` then a refusal. |
| 7 | The approved command was not on PATH, failed to start, timed out, or exited non-zero. | `error: 'prog' ran and exited with code 2` |
| 8 | Any provider/transport failure, including "needs an API key and none was found". | `error: cannot reach openai-compatible at <url>: ConnectError` |
| 130 | Ctrl+C outside a command's own handling. | `interrupted` on stderr. |

Symptoms worth knowing:

* **`the provider returned an empty answer` after `--stream`** — the server ignored
  `"stream": true` and answered with an ordinary JSON body. The SSE parser only consumes
  `data:` lines, so it yields nothing. Re-run without `--stream`.
* **A reply that never arrives** — `--timeout` defaults to 60 s per request and applies to
  the whole call, including the proposal run.
* **`httpx` row in `check`** — the installed version, so a proxy/TLS problem can be pinned
  to a build.
* **Nothing in `levix ai models` matches `ai.model`** — the note after the table says so
  rather than guessing a model for you.
* **Exit 7 where you expected the child's code** — `run_proposal()` maps every non-zero
  child to 7; read the message, not the code, for the child's status.

## Tests

`tests/modules/test_ai.py` — 82 test functions, 97 collected cases (three functions are
parametrised over six cases each: `test_extract_proposal_accepts_a_plain_command`,
`test_extract_proposal_refuses_what_a_shell_would_interpret`, and
`test_non_2xx_maps_to_provider_error`). `tests/test_deps.py` adds 2 cases about the
install-hint format. `tests/test_router.py` adds 2 more: a stub module missing its package
refuses with exit 3 and the words `no install hint is declared`, with `pip install`
asserted absent, while `levix stub -h` still works. Those two use a constructed manifest with no extras and no provider — which is exactly the
case where inventing a pip line would be a lie — while
`test_the_gate_reads_the_stamped_manifest_not_the_modules_own_copy` in the same file proves
the opposite branch: with the registry's stamped copy in front of it, `deps.gate()` raises
with `install it with: pip install "levix[music]"`, which is the line `levix ai` without its
extra prints too (`extras=("ai",)`).

What is pinned down:

* the manifest contract (`cli_path`, `requirements == ["httpx"]`, `extras == ("ai",)`,
  `documentation == "docs/modules/AI.md"`, the command names as an exact set
  `{ask, explain, command, models, check, key}`, non-empty help on every `CommandInfo`, and
  `NETWORK`/`SECRET_READ`/`SECRET_WRITE`/`SUBPROCESS` inside `permissions`);
* config precedence — flags beat configuration, configuration is used when no flag is
  given, unknown provider and blank URL are `ConfigError`s, `--timeout 0` is refused;
* prompt construction — system message present, stdin injected as context, `--system`
  replaces the default, the platform and the single-line rule appear in the `command`
  prompt, `render_raw_prompt()` flattens roles and ends with `ASSISTANT:`;
* `read_snippet` truncation, whole-file case, undecodable bytes, missing file, and that an
  `explain` prompt carries every file;
* proposal extraction over 6 accepting and 6 rejecting spellings (fences, `$ ` prompts,
  `ASSISTANT:` labels, whitespace, pipelines, `&&`, redirection, `;`, `$(…)`), the caveat
  staying separate, the empty reply, and Windows quoted paths (`split_argv` with
  `posix=False`), skipped off-Windows;
* stream parsing: SSE deltas and `[DONE]`, malformed chunk → provider error, NDJSON
  `message.content` and `response` frames, malformed frame;
* request shape per provider, including the bearer header only for OpenAI, `/api/chat` vs
  `/api/generate` with `"raw": true`, and both model-list endpoints;
* usage decoding for OpenAI and Ollama (`prompt_eval_count` / `eval_count`), and unusable
  bodies becoming provider errors;
* the 6-way status mapping plus connect/timeout/non-JSON cases, each asserting
  `"sekret-value" not in message` — the key never leaks into an error;
* the key chain: env wins, keyring when env is silent, the owner-only file when there is no
  keyring, `none` when nothing answers, refusal for a remote host without a key, and
  permission for a loopback host and for Ollama;
* `run_proposal`: argument list with no shell, a real process actually running, missing
  executable and failing child both becoming `ExternalToolError`;
* the CLI surface through the real entry point (`levix ai -h`, offline `check`, the
  no-key warning, `ask` printing reply + usage, streamed SSE, the no-prompt usage error,
  piped stdin as the prompt, `explain` sending only the capped prefix, `models` listing and
  degrading on 404 for both providers, provider failure → exit 8, `command` running
  nothing, `--run` without a terminal → exit 6, `--yes` → exit 6 with
  `--yes cannot authorize a destructive action`, pipeline proposals refused before any
  approval, and the Ollama variants).

The CLI tests never open a socket: `_install_transport()` monkeypatches
`core.build_client` to hand back an `httpx.Client` over a `MockTransport`, and requests are
recorded so assertions can read the payload. `MARKER = "/tmp/levix-ai-must-not-exist"` is
used as the proposed `touch` target and asserted *absent* after every gate test, which is
how "nothing ran" is proven rather than claimed.

Behaviour documented above that no test covers:

* `--live` on `check`, and `core.ping()`'s two report strings;
* the `q` and `cmd` aliases (registered in a loop, asserted only indirectly through
  `MANIFEST.command_names()`);
* the `ai.require_approval is false` message and the un-gated run;
* the `--provider`-source row and `--show-usage` output of `check`/`ask` (`check` is tested
  only in its no-key form);
* `explain --focus`, and the `Notice` line as printed on the console;
* `iter_ndjson_text`'s mid-stream `error` frame, `_STREAM_UNSAFE` tokens `` ` `` and `${`,
  `core.human_size()` in Ollama model details;
* exit 130 and exit 3 for this module;
* Ctrl+C while a proposed command runs.

## Known gaps

1. **`--stream` against a server that ignores streaming yields an empty answer, not an**
   **error.** `iter_sse_text` skips every line that is not `data:`, so a JSON body is
   silently discarded; the exit code stays 0.
2. **An empty flag is treated as no flag.** `--base-url ""` / `--ollama-url ""` fall through
   to the configured value because `resolve_config` uses `base_url or …`; the
   "there is no provider to talk to" error only triggers when the *configuration* is empty.
3. **`check --live` reassigns the `provider` option variable** with the adapter object after
   the table has been printed. Harmless today because the table is already rendered, but the
   row source and the adapter read the same name.
4. **`explain` has no path wall.** `files` confines every operation to a resolved root;
   `read_snippet()` reads any path passed to it, which is the point of the command but is
   worth knowing before piping results to a hosted provider.
5. **Prompt text can end up in command history.** `main._record` logs argv, so a prompt
   given as an argument is stored in `levix.db` and shown by `levix dashboard`. Nothing in
   the module special-cases AI.
6. **The manifest's four capabilities are decorative.** `("openai-compatible", "ollama",`
    `"sse-streaming", "ndjson-streaming")` are not probe names registered in
    `levix.capabilities`, and nothing asks: `doctor` reports its own ten probes
    (`doctor.py:94-98`) and never passes a manifest's capability names to `probe()`. The
    field is documentation that no code reads.
7. **The `MARKER` used to prove nothing ran is a POSIX path.** A proposed `touch` of
   `/tmp/levix-ai-must-not-exist` is asserted absent; on Windows that path never exists in
   the first place, so the assertion is weaker there than the wording suggests.

Four gaps in this list are closed, and three of them are the ones that made the module
unusable without its extra:

* `httpx` is imported inside `build_client()`, `post_completion()`, `stream_completion()`,
  `fetch_models()` and `httpx_version()`, so `levix ai -h` builds the app without the
  optional dependency. A child-interpreter `sys.modules` check in `tests/test_router.py`
  runs that for every module, and it is what the `cli.py` header docstring now describes.
* `levix ai key set` / `key clear` is the write path for the credential: `set` stores through
  `LevixContext.store_secret()` (OS keyring first, owner-only file second, and
  `LEVIX_DISABLE_FILE_SECRETS=1` makes the file tier refuse), `clear` removes it with
  `forget_secret()`, and `levix ai check` prints which tier answered (`env`, `keyring`,
  `file`, `none`) without ever printing the value. `levix config set ai.api_key` refuses,
  because a configuration file is plain text.
* `deps.gate()` looks the manifest up in the active registry, so the official modules report
  against their *stamped* copy and `levix ai` without the extra ends with
  `pip install "levix[ai]"` rather than `no install hint is declared for this module`.
* The `needs an API key` refusal keeps its line break. `ApiKey.needs_key_error()` composes a
  message and a hint, and `main._plain()` used to render the pair with a literal `\x0a`
  between them; it now escapes line by line (`main.py:108-124`), which is what the quoted
  output at the top of this page shows.

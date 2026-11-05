# ADR-0005 - Secrets: environment first, OS keyring second, owner-only file last

Status: accepted
Date: 2026-11-04

## Context

Only the AI module needs a credential today (`AI_API_KEY` for an OpenAI-compatible
server), but the decision is core: it governs where a user's key physically lives, what
`levix config show` prints, what ends up in a log file and what a plugin can reach.

| Option | Why it was not chosen |
| --- | --- |
| Store it in `config.toml` | That file is plain text, is meant to be pasted into bug reports, and `levix config show` prints every key in it |
| Environment variable only | Correct for CI, useless for a desktop user who does not want a key in every child process' environment |
| OS keyring only | On a bare Linux box, a container or a machine without `keyring` installed there is no store to write to, so the CLI would simply fail |
| Encrypt with a key file (`cryptography`, Fernet) | The decrypting key sits next to the ciphertext on the same disk; it adds a dependency and a false sense of protection |
| `env → keyring → owner-only file` | Each step is what the machine can actually do, and the last step says so out loud |

## Decision

`src/levix/secrets.py` resolves in one order and returns the source with the value, so
callers can be honest about where a key came from:

```python
def get_secret(name, *, paths) -> tuple[str | None, str]:   # source: env | keyring | file | none
```

- **Environment**: `LEVIX_AI_API_KEY` (`env_var_for(name)`) wins over everything.
- **OS keyring**: service `levix`, user `AI_API_KEY`. `keyring` is an *optional* extra
  (`pip install "levix[secrets]"`) and is reached through `_keyring()`, which probes with
  `importlib.util.find_spec` before importing - a machine without it costs nothing. A
  keyring that refuses (locked collection, no daemon) is expected control flow, so the
  write is attempted under `contextlib.suppress(Exception)` and the next tier takes over.
- **Owner-only file**: `secrets.json` under the state directory, written then hardened
  with `chmod 0600` and, on Windows, `icacls <path> /inheritance:r /grant:r <user>:F`
  as a `subprocess.run` with an **argument list** (`shell=False` is never turned on
  anywhere in this project), `capture_output=True`, `check=False` and a 10-second timeout.
  `LEVIX_DISABLE_FILE_SECRETS=1` turns this tier off entirely: `set_secret` then raises
  and tells the user to set the environment variable instead.

Three rules hold everywhere else in the codebase:

1. **Configuration never holds a secret.** `config.is_secret_key` matches any key whose
   last segment contains `key`, `token`, `secret` or `password`; `levix config set` refuses
   those keys, and `config show` / `config list` replace a non-empty value with `set, hidden`
   (written markup-free in `commands/config_cmd.py:24-27`; the bracketed form was parsed by
   Rich as a style tag and the column rendered empty). No `SCHEMA` key is secret-shaped and
   an unknown key is rejected at load, so the mask is defence in depth -
   `tests/test_config.py::test_no_declared_key_is_secret_shaped` holds that line. `config
   get` is the one command that does not mask: it prints a warning and then the value it was
   asked for (`commands/config_cmd.py:76-80`).
2. **A secret is never an argument and never printed.** `levix ai key set` prompts with
   `hide_input=True`, because argv lands in shell history, in the process list and in crash
   reports. Nothing prints the value back: `levix ai key set` reports the store it used, and
   `levix ai check` reports only the key's *source*.
3. **Logging is redacted at the source.** `logging_setup.RedactFilter` is attached to the
   logger and to both handlers, so a message cannot bypass it, and it rewrites bearer
   tokens, `sk-…` and `ghp_…`/`gho_…`/`github_pat_…` strings and any `api_key=`, `token=`,
   `secret=` or `password=` pair before the record is formatted.

Writing prefers the keyring and deletes any stale copy from the file, so a machine that
gains a keyring later does not keep a second plaintext value around.

## Consequences

- The fallback is **access-controlled plaintext, not encryption**, and LEVIX says so in
  three places: `levix doctor` reports the secrets area as `DEGRADED` (never OK) with
  `pip install "levix[secrets]"` as the remedy, `levix ai key set` prints the warning when
  it writes the file, and `docs/security/THREAT_MODEL.md` treats "another process running
  as the same user" as out of scope rather than blocked.
- On Windows the file's *NTFS* ACL is what restricts access; `chmod` there maps to the
  read-only attribute and is not the mechanism. Both are applied, and only the Windows
  path has been executed on this machine.
- Plugins get the same store, not a private one: `LevixContext.secret`,
  `store_secret` and `forget_secret` are the SDK surface, and `Permission.SECRET_READ` /
  `SECRET_WRITE` are what an author declares. The `levix ai key` group is the first
  shipped write path; before it, `set_secret` had no caller at all and the keyring tier was
  read-only in practice.
- There is no passphrase, no hardware token and no per-key ACL. A user who needs that
  should keep the key in the environment of the process that needs it, which is the tier
  this order puts first.
- Nothing is uploaded, and no command sends a key anywhere except to the configured
  provider's own URL over the transport the AI module builds.

## Verification

`tests/modules/test_ai.py` - the secret chain (4: environment wins, keyring when the
environment is silent, owner-only file when there is no keyring, `(None, "none")` when
there is nothing anywhere) and `levix ai key` (8: keyring write with a recording fake and
an assertion that the value appears nowhere in the output; the plaintext-file fallback
naming itself and the extra; an empty entry storing nothing; no terminal naming
`LEVIX_AI_API_KEY`; `LEVIX_DISABLE_FILE_SECRETS=1` exiting 3 with the keyring hint; clear
removing what set wrote; clear warning that an environment key is still in use; and a bare
`levix ai key` exiting 2 with its help).
`tests/test_config.py` covers the refusal of a secret-shaped key.

Not verified here: the real keyring round trip. `keyring` 25.7.0 **is** installed in this
development venv, but on this machine `kr.get_current_keyring()` raises, so
`secrets.backend()` reports `("keyring", "OS keyring (backend probe failed; falls back per
call)")` and every store operation goes through the per-call `suppress` path - which means
the plaintext file is what this box actually uses, and the warning that names it is the
output a user here will see. The tests inject a fake keyring rather than trusting that.
Also unverified: the POSIX `chmod` outcome (this run is Windows) and `icacls` on a state
directory whose filesystem has no ACLs (the call is suppressed, leaving `chmod`-hardened
plaintext).

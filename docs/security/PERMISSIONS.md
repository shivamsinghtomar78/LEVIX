# Permissions

`ModuleManifest.permissions` is a declared set of capability labels. **Permissions in
LEVIX are disclosure, not enforcement.** A module's declaration is printed for a human to
read; it never grants, never refuses, and never changes what a module's code can do.

The engine says so itself, in the one place that prints the set for a third-party module
(`commands/plugins_cmd.py:88-95`):

> note: declared permissions are a promise by the author, not an enforced limit. Python
> plugins can do anything LEVIX can.

## The enumeration

`src/levix/module.py:25-35`, a `StrEnum` with exactly seven members.
`tests/test_registry.py:188-201` freezes them as a closed set and asserts that every
manifest's `permissions` is a `frozenset`.

| Member | Value | What it signals | What it does not do |
|--------|-------|-----------------|---------------------|
| `Permission.NETWORK` | `network` | the module opens outbound connections | no host allow-list, no proxy, no prompt on first contact |
| `Permission.FS_READ` | `fs_read` | the module reads files it did not create | no directory confinement; `files` gets its wall from `--root`, not from this flag |
| `Permission.FS_WRITE` | `fs_write` | the module creates, changes or removes files | no dry-run, no journal, no undo |
| `Permission.SUBPROCESS` | `subprocess` | the module executes another program | no path allow-list, no sandbox; the argument-list rule is a separate, real control |
| `Permission.AUDIO` | `audio` | the module opens an output device | no volume cap, no device restriction |
| `Permission.SECRET_READ` | `secret_read` | the module resolves a credential through `levix.secrets` | does not restrict which secret, and cannot prevent a plugin from reading the environment directly |
| `Permission.SECRET_WRITE` | `secret_write` | the module can store or forget a credential through `levix.secrets` | "can read your keys" and "can replace them" are separate labels on purpose; neither one limits which name is written |

There is no `DATABASE_WRITE`, no `TTY_CONTROL`, no `CLIPBOARD`, no `ENVIRONMENT_READ` and
no wildcard. The set is intentionally small and, as recorded under Known gaps, it does not
describe everything the shipped modules do.

| Property | Detail |
|----------|--------|
| Type | `frozenset[Permission]`, default `frozenset()` |
| Frozen manifest | `ModuleManifest` is `@dataclass(frozen=True, slots=True)`, so a module cannot mutate its own declaration after registration |
| Ordering | display sorts by `permission.value`, so the printed list is stable |
| Empty set | legal, and means "nothing declared" — not "nothing used" |

## Where permissions are read

The complete list of reads in the engine:

| Site | Behaviour |
|------|-----------|
| `commands/plugins_cmd.py:88-95` | `levix plugins info NAME` prints `permissions: <sorted values>` when the set is non-empty, and appends the disclosure warning when `origin is THIRD_PARTY` |
| `dashboard/app.py:284-286` | the detail panel appends `permissions <values>` when the set is non-empty |
| `commands/create_module_cmd.py:119` | the scaffolded manifest declares `{Permission.FS_READ}` |
| `tests/test_registry.py` | asserts the closed set and the `frozenset` type |

Nothing in `router.py`, `registry.py`, `deps.py`, `approve.py`, `secrets.py`, `spawn.py`,
`storage.py` or `config.py` consults `permissions`. There is no gate, no check, no
`if Permission.NETWORK in manifest.permissions` anywhere in `src/levix`. Consequently a
module that declares `frozenset()` may open a socket, and a module that declares all seven
is not more capable than one that declares none.

## Per-module declarations

Read from each `src/levix/modules/*/__init__.py` manifest and confirmed against
`ModuleRegistry().manifests()` at runtime. The "code that does it" column is the actual
implementation, not the declaration.

| Module | Declared | Filesystem | Network | Subprocess | Audio | Secrets |
|--------|----------|-----------|---------|------------|-------|---------|
| `monitor` (`systempulse`) | `fs_read` | reads `/proc`, sysfs and WMI-equivalents through psutil | none | none | none | none |
| `hacker` | `fs_read`, `subprocess` | `hosts`, `resolv.conf`, `nsswitch.conf`, capped at `MAX_READ_BYTES = 262_144` | none; `local_hostname` avoids `socket.getfqdn` precisely because it queries DNS | `ipconfig`, `getadapterconfig`, `route`, `ip`, `ifconfig` via `run_tool` with `shutil.which` and `shell=False` | none | none |
| `files` | `fs_read`, `fs_write` | full read/write/rename/delete, behind `core.resolve`'s wall, `validate_new_name` and `require_approval`; `delete --root` defaults to `"."` | none | none | none | none |
| `tube` | `network`, `fs_write`, `subprocess`, `audio` | writes downloads to `tube.output_dir` or `--output`, `overwrites: False` | the media site, through yt-dlp | the external player: `player_command` → `[player, url]`, `launch` with `shell=False` | the player produces sound; LEVIX never opens a device | none |
| `music` | `audio`, `fs_read`, `fs_write`, `network` | reads the library and the playlist table; writes only `music_playlist` and, on the `play URL` path, `<cache_dir>/streams/<sha256(url)[:16]>/audio.mp3` - the path is derived from the link, never from a title, and a path yt-dlp reports from outside that folder is refused before it is opened | the URL's own host, through yt-dlp, only when `play` is handed an `http(s)` link; every other scheme is refused with exit 2 *before* the tools are looked for, and `enable_file_urls` is never set so a link cannot make this process read this disk | none — `__init__.py`: "nothing here shells out for a file on disk… the conversion that makes it decodable runs inside yt-dlp's own postprocessor - LEVIX builds no command line" | `sounddevice` output via `play_samples`, the only hardware seam | none |
| `game` (`arcade`) | *(empty)* | **writes `levix_arcade_score` in `levix.db`**, and `scores --clear` deletes rows behind a typed `DELETE` | none | none | none | none |
| `ai` | `network`, `secret_read`, `secret_write`, `fs_read`, `subprocess` | `explain` reads a capped prefix of each named file (`DEFAULT_MAX_FILE_BYTES = 32_000`) | the configured provider, the only `httpx.Client` site (`build_client`) | `run_proposal` executes a human-approved argument list | none | reads `AI_API_KEY` through `context.secret` → `secrets.get_secret`, never printed; writes and forgets it only through `levix ai key set` / `key clear` → `context.store_secret` / `forget_secret` → `secrets.set_secret` / `delete_secret`, and the prompt echoes nothing |

Origin, provider and version are stamped by the registry, not declared, and they are what
change the *derived* install hint (`pip install "levix[<extra>]"` for official modules).
`permissions` is the only manifest field that is purely author-declared and left as
written.

## What surfacing looks like

```console
$ levix plugins info tube
Tube (tube)
  summary    : Inspect, download or play online video through yt-dlp, with honest gates.
  origin     : official
  provider   : levix
  version    : 0.4.0
  cli entry  : levix.modules.tube.cli:build_app
  commands   : info, download, play
  dashboard  : suspend
  docs       : docs/modules/TUBE.md
  permissions: audio, fs_write, network, subprocess
  requires   :
    + yt-dlp 2026.10.26
```

The warning line is conditional on `manifest.origin is Origin.THIRD_PARTY`, so an official
module prints its permissions without the sentence. That asymmetry is deliberate — the
seven official modules are reviewed in this repository — but it means a user sees the
honest caveat only for the code that most needs it, and `levix plugins list` never shows
permissions at all.

In the dashboard, pressing space on a row renders `_describe`, which includes the same
comma-separated values when non-empty. A row for `game` therefore shows no permissions line
at all, even though selecting it suspends the dashboard and writes to SQLite.

## Choosing a declaration for a new module

| If your module… | Declare |
|-----------------|---------|
| fetches anything from a URL | `NETWORK` |
| opens any file it did not create | `FS_READ` |
| creates, truncates, renames or removes anything | `FS_WRITE` |
| runs another program, including a media player | `SUBPROCESS` |
| writes samples to an output device | `AUDIO` |
| reads a credential through `levix.secrets` | `SECRET_READ` |
| stores or deletes a credential through `levix.secrets` | `SECRET_WRITE` |
| reads or writes `levix.db` | nothing available — see gap 1 |
| takes over the terminal with a Textual app | nothing available — see gap 1 |

The declaration costs nothing and gains nothing mechanically. Its entire value is that a
human reading `levix plugins info yourmodule` before installing can see what you said, and
that you said it in the open. Treat it as a labelling obligation, the way a privacy notice
is, and keep it accurate as the code grows.

| Real enforcement, for contrast | Mechanism |
|--------------------------------|-----------|
| Argument lists only, never a shell | code, in six call sites — `THREAT_MODEL.md` |
| Refusal of shell metacharacters in an AI proposal | `extract_proposal` and `_STREAM_UNSAFE` |
| Typed confirmation that `--yes` cannot bypass | `approve.require_approval(destructive=True)` |
| Path confinement for `files delete` | `core.resolve`'s wall, `--root` default `"."` |
| Credential never printed or logged | `RedactFilter`, config masking |
| yt-dlp authentication options never set | `build_options` plus `tests/modules/test_tube.py` |

Those are controls. `permissions` is a caption next to them.

## Known gaps

1. **The set cannot express two things official modules do.** `game` writes SQLite and
   declares nothing; `files browse`, `game snake` and the live monitor take over the
   terminal and declare nothing. Either add members (`DATABASE_WRITE`, `TTY_CONTROL`) or
   state in the SDK that a database write is covered by `FS_WRITE`, which today it is not —
   `arcade/scores.py` never mentions `Permission`.
2. **`game`'s empty declaration is actively misleading** in both surfaces, because
   `if manifest.permissions:` skips the line entirely rather than printing
   `permissions: none declared`. A user comparing `files` and `game` sees more disclosure
   for the module that asks for confirmation before deleting.
3. **`levix plugins list` shows no permissions column** — name, origin, version, commands
   and state only (`plugins_cmd.py:33-51`) — so the one command a user runs to survey what
   is installed is the one that never mentions capabilities. `info` requires knowing a name
   first.
4. **A plugin can under-declare with no consequence**, and there is no mechanical check
   even for the trivial case: nothing compares a declared set against observed behaviour,
   and no test asserts that the seven official declarations match the code above. Only the
   closed-set assertion in `tests/test_registry.py` exists.
5. **The disclosure warning is hidden for official modules.** Correct for reviewed code,
   but the *user-visible sentence* is attached to the module's origin rather than to the
   nature of the mechanism, so someone reading only `levix plugins info tube` may conclude
   permissions are enforced. The paragraph at the top of this document is currently the
   only place the general case is stated plainly.
6. **No permission is defined for reading the environment or the user's other files**,
   which any plugin can do with `os.environ` — the exact route `secrets.get_secret` itself
   uses.
7. **The scaffolded template declares `FS_READ` for a `hello` command that reads nothing**
   (`create_module_cmd.py:119`), so the first declaration a new author sees is inaccurate.
   A generated `{}` with a comment listing the seven members would teach the right habit.

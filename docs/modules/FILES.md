# Files (`levix files`)

Terminal file manager: browse, search, preview, copy, move, rename, delete.

Source: `src/levix/modules/files/` (`__init__.py` manifest, `cli.py` command surface,
`core.py` filesystem rules, `browse.py` the Textual screen). Module origin:
`levix.modules.files.cli:build_app`; declared documentation path: `docs/modules/FILES.md`.

## What is actually implemented

Seven commands, exactly the ones the manifest declares:

| Command | Purpose |
| --- | --- |
| `levix files browse [PATH]` | Full-screen directory browser (Textual). |
| `levix files search [ROOT] [PATTERN]` | Find entries by name, extension or line content. |
| `levix files preview PATH` | Head of a text file, or honest metadata. |
| `levix files copy SOURCE DESTINATION` | Copy, never overwriting silently. |
| `levix files move SOURCE DESTINATION` | Move, never overwriting silently. |
| `levix files rename PATH NEW_NAME` | Rename inside the entry's own directory. |
| `levix files delete PATH...` | Remove entries after a typed `DELETE`. |

**There is no `ls`, no `tree` and no `du`.** They are not implemented, in any form:

* a listing is `levix files search . --max-depth 1` (or `search .` for the whole tree);
* a recursive listing is `levix files search .`;
* sizes come from `levix files preview DIR` (entry count) and from the measured plan
  that `levix files delete` prints before it removes anything;
* typing `levix files ls` is answered with `unknown command: ls`, the list of registered
  modules and exit code 4.

`levix files` with no subcommand prints the help and exits 2 (click's
`no_args_is_help` usage error), which is deliberate, not a crash.

## Flags, as implemented

Short forms are only those listed; `-h` and `--help` are the only help spellings.

### `search`

| Flag | Default | Effect |
| --- | --- | --- |
| `ROOT` (argument) | `.` | Directory to walk; also the wall the walk is confined to. |
| `PATTERN` (argument) | `""` | Name substring; empty lists everything; with `--glob`, a glob. |
| `--glob`, `-g` | off | Match `PATTERN` with `fnmatch` instead of as a substring. |
| `--case-sensitive` | off | Distinguish case in names and in `--grep` content. |
| `--include-hidden` | off | Include dot-files and entries with the Windows hidden attribute. |
| `--ext EXT` | none | Extension filter; repeatable, and `py,md` / `py;md` / `*.py` all normalise to `.py`. |
| `--limit N`, `-n` | `0` | Stop after N matches; `0` means unlimited. |
| `--max-depth N` | `0` | Descend at most N levels **below ROOT**; `0` means unlimited. |
| `--grep TEXT` | `""` | Search file **content** instead of names. |
| `--grep-regex` | off | Treat `--grep` as a regular expression. |
| `--max-bytes N` | `2097152` | Size cap for `--grep` candidates; `0` means no cap, a negative value falls back to the packaged default. |

`--max-depth 1` reports the entries directly inside `ROOT` and nothing deeper, and the cut
applies to directories as well, so a listing never contains a directory it refused to
enter.

The summary after the matches is generated, not decorative:

```
1 match(es) for grep needle in C:\tmp\wall in 0.13s
1 file(s) read, 1 directory(ies) walked
skipped: 1 binary (NUL in head), 2 over the size cap, 1 hidden (use --include-hidden), 3 symlink(s) not read
```

plus `N unreadable location(s)`, up to three `! path: error` notes, and `stopped early:
match limit N reached` or `stopped early: interrupted by Ctrl+C` when the count is not the
whole answer.

### `preview`

| Flag | Default | Effect |
| --- | --- | --- |
| `PATH` (argument) | required | File or directory to describe. |
| `--lines N`, `-n` | `20` | Head lines to print; `0` prints as much as the 256 KiB read budget holds. |
| `--no-line-count` | off | Do not read the whole file to count lines. |

The table always shows `kind`, `size` (binary units **and** exact bytes), `modified`,
`accessed`, `created` (labelled `(birth)` or `(ctime)`), `permissions` (`stat.filemode`)
and, for a link, `link target`. For text it adds `encoding` and `lines`; for a binary file
it states `binary - NUL byte within the first 8192 bytes`; for a directory it states the
entry count. Anything that is not text is followed by
`no text shown: this is not a readable text file. The table above is all the filesystem
will honestly tell us.` Line counting is skipped for files above 8 MiB and for links, which
is reported as `not counted` rather than as `0`.

### `copy`, `move`

| Flag | Default | Effect |
| --- | --- | --- |
| `--root DIR` | `""` (no wall) | Refuse a destination outside `DIR`. |
| `--force`, `-f` | off | Replace an existing destination; still asks you to confirm. |
| `--yes`, `-y` | off | Cannot authorize an overwrite. |

A destination that is an existing directory means "inside it", as `cp` does. Copying a
directory uses `shutil.copytree(symlinks=True, dirs_exist_ok=force)`; a file uses
`shutil.copy2` (timestamps preserved). Moving uses `os.replace` when `--force` targets a
file (Windows refuses `os.rename` onto an existing file) and `shutil.move` otherwise, so
cross-filesystem moves copy-then-delete. Copying or moving a directory into itself is
refused, as is naming the same entry on both sides.

### `rename`

| Flag | Default | Effect |
| --- | --- | --- |
| `--root DIR` | `""` (extra wall) | The entry's own directory is already the wall. |
| `--force`, `-f` | off | Replace an existing name; still asks you to confirm. |
| `--yes`, `-y` | off | Cannot authorize an overwrite. |

`NEW_NAME` is validated before anything is touched (`core.validate_new_name`): empty,
surrounding whitespace, `.`, `..`, all-dots, any path separator, a drive letter or UNC
prefix, a trailing dot or space, a name longer than 255 bytes, and - on Windows only - the
reserved device names (`con`, `prn`, `aux`, `nul`, `com1`-`com9`, `lpt1`-`lpt9`) are all
refused. A rename therefore cannot become a move or an escape. Renaming onto an existing
**directory** is refused even with `--force`, with the hint to move the entry inside it
instead.

### `delete`

| Flag | Default | Effect |
| --- | --- | --- |
| `PATH...` (arguments) | required | Entries to remove; one or many. |
| `--root DIR` | `.` | Wall: nothing outside this directory may be deleted. |
| `--recursive`, `-r` | off | Required to remove a directory that has entries. |
| `--yes`, `-y` | off | Accepted and ignored: `--yes` cannot authorize a delete. |

## The path wall

`core.py` states the invariant and `core.resolve()` enforces it:

* a named root is a wall; any path whose **resolved** form escapes it is refused with
  `UnsafePathError` (exit 2):
  `path X is outside the wall Y`, hint `run this from inside Y, or widen it with --root DIR`;
* containment is decided with `Path.relative_to`, never a string prefix, so
  `C:\root\abc` is correctly *not* inside `C:\root\ab`, and Windows drive letters, UNC
  shares and case-insensitivity are handled by pathlib rather than by hand;
* `Path.resolve()` collapses `..` and follows links, so the comparison is made on the real
  location, not on what was typed - a detour that ends back inside the wall is allowed
  (`test_resolve_allows_a_detour_that_ends_back_inside`). `delete` is the one command that
  does not follow a link, and so the one command that does not judge one by its target:
  see §Symbolic links;
* relative arguments keep shell semantics (resolved against the current directory); the
  wall only decides what is allowed, never where a name is looked up.

Wall defaults differ per command, and this matters:

| Command | Wall by default |
| --- | --- |
| `browse` | the `PATH` argument - copy and delete inside the screen are confined to it |
| `search` | the `ROOT` argument |
| `preview` | none (read-only) |
| `copy` / `move` | none unless you pass `--root`; only the **destination** is ever walled |
| `rename` | the entry's own directory, plus `--root` if given |
| `delete` | `.` - the current directory |

## Symbolic links

* walking uses `os.walk(..., followlinks=False)`: a symlinked directory is listed but never
  descended into, so a link cycle cannot hang the walk and no file outside `ROOT` is reached;
* `--grep` never reads through a link (the payload may live outside the root we promised to
  search); such files are counted in `skipped: N symlink(s) not read`;
* `copy` of a tree recreates links as links (`copytree(symlinks=True)`);
* `delete` removes a link as a link and never its target
  (`test_deleting_a_link_removes_the_link_and_never_the_target`), including the
  Windows/POSIX split in `core.remove_entry` where a linked directory must go via
  `os.unlink` or `os.rmdir` depending on platform. Because removal touches only the link
  record - it frees no bytes from the target and cannot write outside anything - the wall is
  applied to **the link's own location**, so a link inside `ROOT` pointing outside it is
  deletable. Judging that removal by the target was a defect, found by CI run #3 on Ubuntu
  and macOS, where it refused the safe case. `core.resolve(..., keep_link=True)` is used by
  no other command, precisely because reading, copying and moving *do* follow a link. The
  decision is pinned by `test_a_link_deleted_as_a_link_is_judged_at_its_own_place`, which
  fakes "is a link" and "resolves outside" so it also runs on an account that cannot create
  one;
* a link target is shown as the user would type it: `core.strip_device_prefix` drops the
  `\\?\` DOS-device form that `os.readlink()` returns for an absolute Windows link and turns
  `\\?\UNC\server\share` into `\\server\share`;
* metadata is `lstat`-based: a link reports the length of the link record, a broken link is
  still "an existing entry", and `core.file_size()` returns 0 for links because deleting one
  frees no payload.

## Cost of `--grep`

Content search is the expensive path and the reporting tells you what it paid:

1. every candidate file is opened and its first 8192 bytes sniffed for a NUL byte;
2. a file whose head contains NUL is counted as binary and not searched;
3. files whose `lstat` size exceeds `--max-bytes` are skipped and counted; `0` turns the
   cap off (`search_contents` tests `if max_bytes and size > max_bytes`), which is what the
   flag's own help promises;
4. everything else is read to the end, line by line, and **every line is decoded**
   (utf-8, then cp1252, then latin-1 with replacement) before matching;
5. with `--grep-regex` the expression is compiled once, otherwise a casefolded substring
   test is used;
6. `--limit` stops the walk early and records `match limit N reached` so the printed count
   is honest.

There is no index and no cache: a second run pays the same cost. For a large tree, narrow it
with `--ext`, `--max-depth` and `--limit` before raising `--max-bytes`.

## Destructive paths and the confirmation gate

One gate serves the whole CLI: `levix.approve.require_approval`
(`src/levix/approve.py`).

* `destructive=True` **neutralises `--yes`**. The code prints, on stderr,
  `--yes cannot authorize a destructive action; confirming interactively.` and then prompts
  anyway. This is a feature, verified by `test_delete_yes_cannot_authorize_a_deletion`,
  `test_copy_with_force_still_needs_a_terminal` and, in the AI module,
  `test_command_yes_cannot_authorize_a_run`.
* No terminal is a **refusal, not consent**: with stdin that is not a tty the gate raises
  `UserCancelledError` (exit 6) -
  `refusing to delete without a terminal to confirm in: ... pass --yes for a
  non-destructive action, or run this interactively` - and nothing is removed.
* The expected word is `DELETE` for a delete and `OVERWRITE` for a forced copy/move/rename;
  anything else aborts. EOF at the prompt is also a refusal (`no input available; delete
  aborted`).
* `delete` measures the plan first and prints it as a table titled
  `about to delete N file(s) and M directory(ies), X KiB under WALL`, then confirms against
  those numbers, then removes children before their directories. Paths already covered by
  another argument are reported (`note: X is inside another listed path, so it is covered by
  that deletion`) instead of being deleted twice. A non-empty directory without
  `--recursive` is refused up-front:
  `deleting a tree cannot be undone; re-run with --recursive to say so`.
* Overwrites without `--force` are refused as a bad request (exit 2) with
  `pass --force to replace it (copy will still ask you to confirm)`.
* Partial failure is not fatal: each entry that cannot be removed is listed as
  `not removed: path: reason`, the rest of the batch continues, and the command ends with
  exit 1 and the Windows-specific hint `on Windows a file in use, a read-only entry or a
  locked folder is the usual cause`.
* Confirmation is unconditional: there is no configuration key that turns the gate off,
  by design — see Known gaps.

## `levix files browse` is a Textual screen

The manifest declares `ui = UiSpec(mode="suspend", argv=("files", "browse"))`. `suspend`
means the dashboard releases the terminal and re-enters `levix files browse` in a
subprocess, because one TTY cannot host two Textual apps. `browse.py` is the only file that
imports Textual, and the import sits inside the command body, so `levix files -h` never pays
for it. Textual `>=8.2,<9` is a core dependency, so `browse` needs no extra to be installed.

Keys: `enter`/`o` open or expand, `space` toggle, arrow keys move, `shift+left` to the
parent, `p` preview, `c` copy (destination is typed relative to the browser root and stays
inside it), `d` delete, `r` reload, `?` help, `q`/`ctrl+q` quit. Inside the screen a delete
uses `ConfirmScreen` - `type DELETE to continue - anything else aborts` - because Textual
owns the screen and the shared stdin gate cannot be used; the rule is reproduced, not
weakened. A directory with entries is refused with the hint to run
`levix files delete --recursive` in a terminal.

`browse` refuses to start when stdout is not a terminal:
`browse needs a real terminal (stdout is not a tty)` with hint
`use \`levix files search\` / \`preview\` for pipe-friendly output` (exit 1).

## What this module touches

| Aspect | Fact |
| --- | --- |
| Declared permissions | `Permission.FS_READ`, `Permission.FS_WRITE` (`files/__init__.py`) |
| Network | None. No socket, no HTTP client. |
| Subprocess | None. |
| Secrets | None. |
| Third-party extras | None: `requirements=()` and `extras=()`, so no `levix[...]` install is ever needed for `files`. |
| Files written | The user's own files, only under the resolved destination/wall; deletions remove the planned entries. |
| SQLite rows | One row per invocation in `levix_command_log` (`<data>/levix.db`), written by `levix.main._record`, not by this module; history is best-effort and never fails your command. |
| Log lines | On a successful delete, one warning to `<log>/levix.log`: `files delete: %s entries removed, %s bytes reclaimed under %s`. |
| Configuration read | Nothing. No `files.*` section exists in the schema. |
| Console output | Every dynamic string passes `show()` = `escape(core.printable(...))`, so `[bold]` inside a file name stays text and a cp1252 console cannot crash on an unencodable name. |
| Paths honoured | `LEVIX_HOME`, `LEVIX_CONFIG_DIR`, `LEVIX_DATA_DIR`, `LEVIX_LOG_DIR`, `LEVIX_CACHE_DIR`, `LEVIX_STATE_DIR` (`src/levix/paths.py`) |

## Examples

```console
$ levix files search src "parser" --ext py --max-depth 3
$ levix files search . --grep TODO --grep-regex --limit 40 --ext py,md
$ levix files preview src/levix/app.py --lines 40
$ levix files copy notes.md backup/            # refuses if backup/notes.md exists
$ levix files copy notes.md backup/ --force    # now asks you to type OVERWRITE
$ levix files rename tmp.log report.log
$ levix files delete build --recursive --root . # prints the plan, then asks for DELETE
$ levix files browse .                          # full screen
```

## Exit codes and troubleshooting

Codes come from `src/levix/errors.py` only.

| Code | Meaning here | Typical case and remedy |
| --- | --- | --- |
| 0 | Success | - |
| 1 | `FilesError`, the filesystem said no | Locked or unreadable file, `browse` on a piped stdout, a partially failed delete. Re-run in a terminal, or close whatever holds the file. |
| 2 | `UnsafePathError` / `RequestError`, bad request | Path outside the wall, missing path, existing destination without `--force`, a tree without `--recursive`, a file where a directory was needed, an illegal new name. |
| 3 | Missing dependency | Not reachable for `files`: its manifest declares no requirements. |
| 4 | Unknown module or command | `levix files ls`, `levix files tfee`. The error lists the registered modules. |
| 5 | Invalid configuration | `files` reads no keys, but the root callback loads `config.toml` for every command; a bad key or value exits 5 before the command runs. |
| 6 | Declined, or no terminal to confirm in | Aborted prompt, scripted delete. Run interactively; `--yes` will not help for a destructive action. |
| 130 | Interrupted | Ctrl+C during `search`; the partial counts are printed first. |
| unexpected error | A LEVIX bug | Report it; `levix doctor` prints the environment and the traceback tail is included. |

Note that `main._plain()` escapes markup and unencodable bytes **per line**
(`main.py:108-124`), so a message LEVIX authored with a break in it still prints on two
lines; only the control characters *inside* a line become `\xNN`.

## Tests

`tests/modules/test_files.py` - 121 test functions, 147 collected cases on Windows: three
parametrised sets (`human_bytes`, `count_lines`, and the 12/20-entry `DANGEROUS` name list,
which grows on Windows) and three `@pytest.mark.integration` Textual Pilot tests.

What they pin down:

* the packaged contract: manifest name, `cli_path`, the seven command names, empty
  requirements/extras, `UiSpec(mode="suspend", argv=("files","browse"))`, permissions,
  `documentation == "docs/modules/FILES.md"`;
* lazy import, by inspecting `sys.modules` of a **child process**:
  `test_importing_the_manifest_pulls_in_nothing_heavy` (expects `7 []`),
  `test_module_help_does_not_import_the_heavy_optional_dependencies` (expects
  `0 False []` - exit code 0, textual not loaded), `test_browse_help_does_not_start_a_screen`
  (expects `0 False`);
* the wall: component-wise containment, different drives, UNC, case-insensitivity,
  traversal out, absolute paths outside the root, the sibling that only shares a name
  prefix, detours that end back inside;
* the gates: `--yes` cannot authorize a deletion, forced copy still needs a terminal,
  a delete without a terminal removes nothing, `unknown command` exits 4 rather than crashing;
* search/grep accounting: binary sniff counts, size-cap counts, hidden counts, symlink
  skips, limit early-stop, unreadable-not-fatal;
* preview honesty: encoding chain including the `latin-1 (lossy)` label, binary described
  rather than dumped, directory and missing-path metadata, symlink-not-target, names the
  console cannot encode;
* delete mechanics: plan measurement, children-before-directory order, covered paths,
  per-entry failure reporting, links removed as links;
* the browser through Textual's Pilot: copy/preview/delete, and refusing a directory delete
  with a pointer at the CLI.

Documented behaviour with no test behind it: the `--glob`, `--case-sensitive`, `--max-depth`
and `--no-line-count` flags **at the command surface** (their `core` equivalents are covered,
the CLI plumbing is not), the Ctrl+C path that turns a partial search into exit 130, the
`OVERWRITE` prompt word itself, and the `files delete` log line.

## Known gaps

1. No `ls`, `tree` or `du`. Documented above as absent, not as planned.
2. There is no `general.confirm_destructive` key. One existed in `config.SCHEMA` and in the
   packaged defaults and was read by nothing, so `levix config set` accepted a value that
   changed no behaviour. The gate in `levix.approve` is unconditional and the schema no
   longer pretends otherwise; adding a switch would mean deciding that a documented
   safety property is optional, which is a design change, not a cleanup.
3. A delete cannot be scripted, by design, and there is no alternative non-interactive
   escape hatch for automation; the only supported route is to run it interactively.
4. `browse` deletes files and empty directories only. Whole trees must go through
   `levix files delete --recursive`; the screen says so rather than pretending otherwise.

## Closed since the first draft of this page

* **`--max-bytes 0` did fall back to the packaged default at the command surface.** The flag
  and the `core` docstring both promise `0 = no cap`, but `files/cli.py` passed
  `max_bytes if max_bytes > 0 else core.DEFAULT_GREP_MAX_BYTES`, so `--grep` over a 3.9 MiB
  text file still reported `skipped: 1 over the size cap`. The condition is now `>= 0`
  (`src/levix/modules/files/cli.py:188`), which is what the `if max_bytes and size >
  max_bytes` test in `search_contents` already assumed: `0` disables the cap, and a negative
  value - a typo, not a request to read the disk unbounded - keeps the default.
  `test_max_bytes_zero_means_no_cap` writes a file above the default cap and asserts both
  halves: `--max-bytes 0` finds it and never says "over the size cap", while the same search
  with no flag skips it and does.
* **Multi-line error messages are no longer flattened.** `main._plain()` encodes each line
  separately (`"\n".join(escape(encode_safe(line)) for line in str(value).splitlines())`,
  `src/levix/main.py:108-124`), so a delete refusal or a missing-dependency report arrives
  as the several lines it was written as. See `docs/architecture/ERROR_HANDLING.md` and
  `tests/test_deps.py::test_a_two_line_refusal_stays_two_lines_on_the_screen`.

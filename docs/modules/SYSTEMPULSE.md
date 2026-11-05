# SystemPulse (`levix monitor`)

Cross-platform system monitoring: CPU, memory, disk, network and process panels, plus a
refreshing dashboard view. Everything is read through `psutil`; nothing is shell-mediated
and nothing leaves the machine.

Source: `src/levix/modules/systempulse/` (`__init__.py` manifest, `cli.py` rendering,
`core.py` sampling). Entry point: `levix.modules.systempulse.cli:build_app`. Declared
documentation path: `docs/modules/SYSTEMPULSE.md`.

## Why the package is SystemPulse and the command is `monitor`

The manifest keeps both names, by design, and says so in its own module docstring:

> `Command name is `monitor` (short, verb-like); the package keeps the product name.`

So the distribution-level identity is `SystemPulse` (`MANIFEST.title`), the package is
`levix.modules.systempulse`, and every user-facing invocation spells the command
`monitor`: `levix monitor overview`. `MANIFEST.name` is `"monitor"`, which is what the
registry, `levix doctor`, the dashboard and the command history all use. There is no
`levix systempulse` command; typing it produces `unknown command: systempulse` and exit
code 4.

## What is actually implemented

Seven commands, exactly the ones the manifest declares:

| Command | What it prints |
| --- | --- |
| `levix monitor overview` | Uptime, CPU, memory, swap, battery, temperature, GPU, then the disk and process tables. |
| `levix monitor cpu` | One bar per logical core, plus logical/physical counts, frequency and load averages. |
| `levix monitor memory` | RAM and swap pools, plus `available to start new work: …`. |
| `levix monitor disk` | Every mounted filesystem `psutil` reports, with usage bars. |
| `levix monitor network` | Per-interface byte/packet counters, cumulative since boot; deltas when `--watch` is used. |
| `levix monitor processes` | The top processes, ranked by CPU. |
| `levix monitor live` | The overview, redrawn every interval until Ctrl+C. |

Names the README of a similar tool might use do **not** exist here:

* there is no `ps` command — the process list is `levix monitor processes`;
* there is no `net` command — interface counters are `levix monitor network`;
* there is no `--live` flag on `overview`. `live` is a separate command. Passing
  `levix monitor overview --live` is a usage error:
  `Error: No such option: --live (Possible options: --limit)` with exit code 2;
* there is no `--interval` on `overview`, `cpu`, `memory`, `disk`, `network` or
  `processes`. Only `live` refreshes, and only `network --watch` waits at all.

`levix monitor` with no subcommand prints the module help and exits 2 (click's
`no_args_is_help` usage path), which is deliberate.

## Flags, as implemented

`-h` and `--help` are the only help spellings on every command.

| Command | Flag | Default | Effect |
| --- | --- | --- | --- |
| `overview` | `--limit` | `8` | Rows in the process table. A literal default: `monitor.process_limit` is **not** consulted by `overview`. |
| `cpu` | — | | Takes no options. The sample window is fixed at 0.3 s. |
| `memory` | — | | Takes no options. |
| `disk` | — | | Takes no options; there is no `--all` to include virtual/fuse mounts (`psutil.disk_partitions(all=False)`). |
| `network` | `--watch SECONDS` | `0.0` | When greater than zero, counters are sampled twice with that gap and the differences are printed; the table title becomes `Network rates over Ns`. When zero, counters are cumulative since boot. |
| `processes` | `--limit`, `-n` | `0` | Rows to show; `0` uses `monitor.process_limit` (default 15). |
| `processes` | `--by` | `cpu` | `cpu` or `memory`. See the caveat below: ranking happens after the CPU cut. |
| `live` | `--iterations` | `0` | Stop after N frames; `0` runs forever. |
| `live` | `--interval` | `0.0` | Seconds between frames; `0` uses `monitor.interval_seconds` (default 1.0). |

`network --watch` is the only flag that blocks on purpose, and it sleeps for exactly the
interval it was given. There is no rate-per-second normalisation: the numbers printed are
raw byte deltas over that window.

## Configuration

The module reads two keys through `LevixContext.value`. Layers are packaged
`data/defaults.toml` → user `config.toml` → `LEVIX_<SECTION>_<KEY>` → flags.

| Key | Type / bounds | Packaged default | Read by |
| --- | --- | --- | --- |
| `monitor.process_limit` | int, 1–200 | `15` | `processes --limit 0` |
| `monitor.interval_seconds` | float, 0.1–60 | `1.0` | `live --interval 0` |

Environment overrides are `LEVIX_MONITOR_PROCESS_LIMIT` and
`LEVIX_MONITOR_INTERVAL_SECONDS`; they are validated like every other key, so a value
outside the range fails before the panel renders:

```
error: monitor.process_limit (environment) must be >= 1, got 0
```

exit code 5.

When no `LevixContext` reaches the command at all, the fallbacks in
`_configured_limit()` / `_configured_interval()` are `15` and `1.0`, matching the packaged
defaults.

## What `psutil` is actually asked for

`core.py` imports `psutil` **inside every function**, never at module level. That is what
keeps `levix monitor -h` cheap: a child process that runs `main(["monitor", "-h"])`
reports `psutil` absent from `sys.modules`. The dependency gate
(`cli.py:_gate` → `ensure_dependencies(MANIFEST)`) also only fires when a subcommand is
actually invoked.

| Function | `psutil` calls | Behaviour when the platform does not answer |
| --- | --- | --- |
| `cpu()` | `cpu_percent(interval, percpu=True)`, `cpu_count(logical=False)`, `cpu_freq()`, `getloadavg()`, `cpu_count(logical=True)` | `cpu_freq()` and `getloadavg()` are wrapped: `AttributeError`/`OSError` → `None`; the frequency and load rows disappear from `overview`, and `cpu` prints the honest sentence instead. |
| `memory()` | `virtual_memory()`, `swap_memory()` | A machine with no page file reports `swap_total_bytes == 0` and prints `none reported by the OS` / `none reported`. |
| `disks()` | `disk_partitions(all=False)`, `disk_usage(mountpoint)` | A mount that raises `PermissionError`/`OSError` is **skipped silently** (comment: "A read-only or protected mount on Windows is normal, not an error"). |
| `network()` | `net_io_counters(pernic=True)`, twice when `--watch` | New interfaces mid-window fall back to absolute counters; deltas are computed against a local `_DeltaNet` duck-type. |
| `processes()` | `process_iter([...])`, per-process `cpu_percent(None)`, `as_dict(...)`, `memory_info().rss` | Processes that vanish or deny access are dropped. `cpu_percent` is primed and then re-read after `time.sleep(0.15)` because "the first call always returns 0.0". Unknown name/status render `?`, unknown user `-`. |
| `temperatures()` | `getattr(psutil, "sensors_temperatures", None)` | Attribute absent (stock Windows) or any exception → `{}` → the unsupported row. |
| `battery()` | `getattr(psutil, "sensors_battery", None)` | Attribute absent or exception → `None` → `not reported by this platform`. |
| `uptime()` | `boot_time()` | `max(0.0, time.time() - boot_time)`. |
| — | GPU: no call exists | `psutil` has no GPU API, so the GPU row is a constant. |

`human_bytes()` in this module uses binary units (`B`, `KiB`, `MiB`, `GiB`, `TiB`, `PiB`,
one decimal place), which is why `memory` totals differ from `ai`'s decimal `KB/MB/GB`
helper.

## Honest "unavailable" reporting

The sampling docstring states the rule and the renderer obeys it in every case except the
one noted in Known gaps:

> `Honesty rule: when the platform does not expose a metric, this module returns None or`
> `an empty mapping and the renderer says so. Zero is never substituted for unknown.`

The strings below are in the code verbatim:

| Row | Text printed |
| --- | --- |
| `temp` (in `overview`, empty sensor map) | `unsupported here - no sensors exposed through psutil` |
| `gpu` (always) | `unsupported - psutil exposes no GPU API` |
| `swap` (in `overview`, no page file) | `none reported by the OS` |
| `swap` (in `memory`) | `none reported` |
| `battery` (in `overview`, `None`) | `not reported by this platform` |
| `cpu` (no physical count) | `physical count not reported by this platform` |
| `cpu` (no load average) | `load averages are not available on this platform.` |
| `disk` (no partitions) | `no mounted filesystems reported` |

These match `levix doctor`, which probes `psutil`, `temperature`, `battery` and `gpu`
through the same library and prints its own verdicts (`gpu` is
`psutil provides no GPU utilisation API on any platform`). The manifest's
`capabilities=("psutil", "temperature", "battery", "gpu")` are the names those probes use.

On the Windows 11 machine this page was verified on (`psutil 7.2.2`), `overview` printed:

```
| battery  | 34% (discharging)                                  |
| temp     | unsupported here - no sensors exposed through psutil |
| gpu      | unsupported - psutil exposes no GPU API              |
```

## `live`, and how it refreshes

`live` is a plain loop, not a `rich.live.Live` region and not a second Textual app:

```python
console.clear()
_render_overview(6)
console.print(f"[dim]refresh every {delay:.1f}s - Ctrl+C to stop (frame {frames + 1})[/dim]")
time.sleep(delay)
```

* the process table always shows 6 rows here; `--limit` does not exist on `live`, and
  `monitor.process_limit` is ignored;
* the footer line as printed looks like `refresh every 1.0s - Ctrl+C to stop (frame 1)`;
* Ctrl+C is caught inside the command and prints `stopped.`, exiting **0**; the process
  table of the interrupted frame is left as it was drawn;
* on a captured (non-tty) stream `console.clear()` emits no escape sequence, so `live`
  appends one full overview per frame rather than redrawing in place;
* `--iterations 1` is the scripted way to grab one frame for a log.

The dashboard launches this module through the manifest's `UiSpec(mode="suspend",
argv=("monitor", "live"))`: one TTY cannot host two Textual apps, so the dashboard
releases the terminal and re-runs `levix monitor live` in a subprocess.

## Missing dependency

`MANIFEST.requirements` is `(PackageRef("psutil", "psutil", minimum="7.2"),)` and
`MANIFEST.extras` is `("monitor",)`. With `psutil` unimportable, every subcommand is
refused before it runs:

```
error: module 'monitor' needs psutil is not installed
  install it with: pip install "levix[monitor]"
```

exit code 3, as verified by running `levix monitor overview` in a process whose
`sys.meta_path` refuses `psutil`. The two lines are two lines: `main._plain()` splits the
message and escapes each part, so the break LEVIX authored in
`deps.ensure_dependencies` survives to the terminal (see
`docs/architecture/ERROR_HANDLING.md`). The gate reads the manifest the registry stamped
with `Origin.OFFICIAL`, which is what makes `resolved_install_hint()` able to name the
extra; a plugin's own manifest would end with `no install hint is declared for this module`.

## Rendering, glyphs and encoding

Bars come from `levix.terminal.bar()`, which uses `active_glyphs()`: a Unicode terminal
gets `█` and `·`, a legacy or `TERM=dumb` console gets `#` and `-`. `levix monitor cpu`
renders each core with `width=28`, `overview` uses the default 20 and the disk column 12.

Every cell this module did not author goes through `levix.terminal.markup_safe()` before it
reaches `Table.add_row`: `row.name`, `row.username` and `row.status` in the process table
(`src/levix/modules/systempulse/cli.py:277-282`), `row.mountpoint`, `row.device` and
`row.fstype` in the disk table (`cli.py:248-250`), the interface name in the network table
(`cli.py:194`) and the `temp [k10temp]` label in `overview` (`cli.py:104`). That matches
what `files` does with `show()` and what `hacker` and `music` do with their own `_show()`.
The reason is concrete: on Linux the kernel threads are named `[kthreadd]` and
`[migration/0]`, and Rich reads a bare `[...]` as a style tag and deletes it, so an
unescaped name column prints a pid beside an empty cell.

One thing escaping does not fix: long names are still truncated by the column (`name` has
`max_width=28`, `user` has `overflow="ellipsis"`), and Rich emits the ellipsis through the
console encoding. Verified on a Windows pipe at `COLUMNS=60`, where the bytes captured are
`NT AUTHO\x85` — `\x85` is cp1252's `…`. `encode_safe()` is what turns such text into
`\xNN` ASCII, and it is applied to error and diagnostic lines in `main._plain()`, not to
table cells. See Known gaps.

## What this module touches

| Aspect | Fact |
| --- | --- |
| Declared permissions | `{Permission.FS_READ}` — the only one. |
| Network | None. No socket is opened by any command. |
| Subprocess | None. `psutil` is called in-process; no OS tool is spawned. |
| Secrets | None read, none written. |
| Files written by the module | Nothing. `core.py` and `cli.py` never open a path for writing. |
| Files read by the module | `psutil`'s own OS interfaces; plus the standard config chain (`data/defaults.toml`, the user `config.toml`) through `levix.config`. |
| Configuration written | Never. The module only reads `monitor.*`; use `levix config set monitor.interval_seconds 2`. |
| Database rows | One row per invocation in the shared `levix.db`, table `levix_command_log`, written by `levix.main._record` for every command (argv, module, exit code, duration). Not written by SystemPulse itself. |
| Log file | Nothing explicit; the root logger may capture a failure in `levix.log` per `logging.*`. |
| Terminal state | `live` calls `console.clear()`, which on a real terminal scrolls/clears the screen. |
| Time spent | `overview` ≈ 0.15 s (CPU window) + 0.15 s (process priming); `cpu` 0.3 s; `network --watch N` N s; `live` N frames × interval. |

## Examples

```bash
levix monitor overview
levix monitor overview --limit 20
levix monitor cpu
levix monitor memory
levix monitor disk
levix monitor network
levix monitor network --watch 2
levix monitor processes --limit 10
levix monitor processes -n 0 --by memory
levix monitor live --interval 0.5 --iterations 20
LEVIX_MONITOR_PROCESS_LIMIT=30 levix monitor processes
levix config set monitor.interval_seconds 2
levix doctor
```

For a log or a pastebin, capture one frame and drop colour with `NO_COLOR=1` (or
`LEVIX_NO_COLOR=1`); the bar glyphs switch to `#`/`-` only when the stream is not UTF-8 or
`TERM=dumb`, as `levix.terminal.detect()` decides:

```bash
NO_COLOR=1 levix monitor live --iterations 1 > monitor.txt
```

## Exit codes and troubleshooting

Codes are the single table in `src/levix/errors.py`.

| Code | Meaning here | How to tell |
| --- | --- | --- |
| 0 | Panel rendered. Also the code for `live` stopped with Ctrl+C. | `stopped.` on the last line. |
| 1 | Unhandled internal error; a traceback tail follows `unexpected error:`. | Most likely in `psutil`'s per-platform calls; report it. |
| 2 | Bad usage: unknown option (`overview --live`) or `levix monitor` with no subcommand. | `Error: No such option: …` or the module help. |
| 3 | `psutil` missing or older than declared. | `error: module 'monitor' needs psutil …` — install with `pip install "levix[monitor]"`. |
| 4 | Unknown module/command at the top level. | `levix systempulse` → `unknown command: systempulse`. |
| 5 | A `monitor.*` value is invalid, from any layer. | `error: monitor.process_limit (environment) must be >= 1, got 0`. |
| 130 | Ctrl+C outside the `live` loop (during the 0.15–0.3 s sample). | `interrupted` on stderr. |

Codes 6 (declined confirmation), 7 (external tool failed) and 8 (provider failed) are not
reachable here: this module has no approval gate, spawns nothing and talks to no server.

Symptoms worth knowing:

* **`Top processes by cpu (n=15 of limit 15)` but every CPU figure is tiny** — the
  per-process percentage is measured over the 0.15 s priming window, not over the life of
  the process. A busy process can read 0.0 in one frame.
* **A mount you can see in Explorer is missing from `disk`** — `psutil.disk_partitions(all=False)`
  excludes network/virtual mounts, and any mount that raises `PermissionError` is skipped
  without a note.
* **`load avg 0.00, 0.00, 0.00` on Windows** — this `psutil` answers `getloadavg()` with
  zeros rather than raising, so the honest "not available" sentence never prints. See
  Known gaps.
* **Nothing refreshes in `live`** — the loop sleeps after drawing; on a redirected stream
  each frame is appended instead of replacing the last.
* **`levix monitor bogus`** — reported as `unknown command: bogus` with the list of
  *modules* (`ai, files, game, hacker, monitor, music, tube`) and exit 4, because the
  router's unknown-command helper is shared. The module's own commands are listed by
  `levix monitor -h`.

## Tests

`tests/modules/test_systempulse.py` — 40 test functions, 46 collected cases on Windows.
Only the five that drive the commands through `run_cli` touch a real `psutil`; the rest use
one `install(monkeypatch, …)` factory that puts a stand-in in `sys.modules` (`core.py`
imports `psutil` inside each function, which is what makes that possible) or build a row
dataclass directly, so the numbers under test are values the test named, not values this
machine happened to have. A laptop on battery, a machine with no sensors and a machine with
three mounts therefore all produce the same result.

| Area | What is pinned |
| --- | --- |
| `cpu` | the reading is the average of the per-core list, not the first core; `threads` stays separate from `cores`; a missing frequency and a missing physical-core count stay `None`; zero cores cannot divide by zero; the counters are primed before the second read |
| load average | a platform with no `getloadavg` answers `None` rather than zeros; a platform with it answers the three numbers |
| memory, swap | the pools pass through untouched; a machine with no swap reports `0`, which is a fact, not a guess |
| `disk` | a mount whose `disk_usage()` raises `PermissionError` is skipped and the rest still report; an unnamed filesystem prints `-` instead of an empty cell |
| `network` | cumulative counters are reported untouched; `--watch` reports the difference and takes exactly two samples; an interface that appears mid-window is kept |
| `processes` | a process that vanishes between `pids()` and `Process()` is skipped; rows are ordered busiest-first; `--limit` caps the rows, not the work; a process naming itself as nothing still gets a row |
| sensors, battery | no getter, a raising getter and a `None` reading are each reported as absent rather than as zero; an unlabelled sensor is named after its chip; no battery is `None`, not `0%` |
| units | `human_bytes` is binary across `0 B` → `2.5 PiB`; a clock that jumps backwards cannot produce a negative uptime |
| rendering | `[kthreadd]`, a mount named with brackets, an interface named `veth[0abc]` and the `temp [k10temp]` row survive Rich's markup parser; the GPU row is never a number |
| CLI | `overview`, `cpu`, `memory`, `disk`, `network`, `processes --limit 3` and `live --iterations 1 --interval 0.05` exit 0; `cpu --nonsense` exits 2; a platform with no sensors says so in words |
| manifest | declares `fs_read` only, and declares `gpu` as a capability precisely so the report can say *unsupported* |

The four CLI tests above use the real `psutil`, because they are asserting that the
command runs, not what it measures.

Other files that touch this module:

| File | What it asserts about this module |
| --- | --- |
| `tests/test_router.py` | `levix monitor -h` imports no heavy dependency, `psutil` included — the lazy-import rule, measured in a child interpreter. |
| `tests/test_config.py` | `monitor.process_limit` resolves to `15` with source `default`; a user file value is coerced; `LEVIX_MONITOR_PROCESS_LIMIT` wins; a non-integer value is rejected. Keys only — no monitor code runs. |
| `tests/test_registry.py` | `"monitor"` is in the expected `OFFICIAL` name set, and its stamped manifest is in the closed permission set. |
| `tests/test_storage.py` | The migration namespace list contains `"monitor"`; `("monitor", "cpu", …)` argv strings are used as generic history rows. |
| `tests/test_dashboard.py` | Builds its **own** manifest stub named `monitor` to test `UiSpec(mode="suspend", argv=("monitor", "live"))` handling. It does not import `levix.modules.systempulse`, so a change to the real manifest would not fail it. |
| `tests/modules/test_arcade.py` | Asserts `storage.MIGRATIONS["monitor"] == ()`, i.e. that arcade did not register migrations here. |

Still not covered anywhere:

* `--by memory` — the reorder-then-truncate defect below is documented, not asserted;
* `ensure_dependencies` firing for `monitor` — no test removes `psutil`, and
  `tests/test_deps.py` exercises the gate with constructed manifests;
* the Ctrl+C (exit 0) and configuration-error (exit 5) paths, which need a real signal and
  a real bad value respectively;
* the numbers on a real host: what this machine reports is verified by running the CLI, on
  Windows only.

## Known gaps

1. **`load avg` breaks the module's own honesty rule on Windows.** `psutil 7.2.2` returns
   `(0.0, 0.0, 0.0)` from `getloadavg()` instead of raising, so `overview` prints zeros.
   The `Honesty rule` docstring says "Zero is never substituted for unknown", and the
   `cpu` command's `load averages are not available on this platform.` line only appears
   when the value is `None`, which this platform never produces.
2. **`--by memory` can only reorder what the CPU cut kept.** `core.processes(limit=n)`
   sorts every process by CPU and slices *before* returning, and `cli.processes()` then
   sorts that slice by `memory_percent`. The result is "the most CPU-hungry n processes,
   shown memory-first", not the memory hogs; the table header still reads `Top processes
   by memory`.
3. **`overview` ignores `monitor.process_limit`.** Its `--limit` default is a literal `8`
   and `processes` only consults the configured value when `--limit 0`, so the setting
   named in the configuration table drives one path; `live` uses a fixed `6` regardless of
   either.
4. **Skipped mounts are silent.** A `PermissionError` on `disk_usage()` drops the mount
   with no note and no count, unlike `files search`, which reports skipped categories.
5. **`live` is a clear-and-redraw loop, not a live region.** There is no
   `rich.live.Live`, no spinner, and no partial-frame update; it cannot be paused, and the
   first frame is drawn before the first sleep, so `--interval` sets the delay *after* the
   work rather than a cadence.
6. **The manifest's GPU capability is a constant.** `capabilities=("psutil",
    "temperature", "battery", "gpu")` are probe names only; no code consults
    `LevixContext.probe()` in this module, so the GPU row is printed whether or not the
    probe was ever run.
7. **A truncated cell emits the console encoding's own ellipsis byte.** `name` and `user`
   use `overflow="ellipsis"`, and Rich writes `…` through the stream encoding: verified on
   this machine, `levix monitor processes --limit 6` piped at `COLUMNS=60` produced
   `NT AUTHO\x85` (cp1252 for `…`) rather than ASCII the pipe can always carry. Table cells
   get `markup_safe`, not `encode_safe`, so the markup half of the problem is closed and the
   byte half is not. Raising `COLUMNS` or `--limit` avoids the truncation.

Three gaps that used to be on this list are closed, and are pinned by tests:

* **the exit-3 refusal did not name the extra to install.** `deps.gate()` now guards with
  the registry's *stamped* manifest (`active().get(name)`), so `origin` is known and the
  message ends with `pip install "levix[monitor]"`.
* **dynamic cells were read as Rich markup.** Process name, user and state, mount point,
  device, filesystem type, interface name and the `temp [k10temp]` label all go through
  `terminal.markup_safe`; on Linux `[kthreadd]` used to be swallowed by Rich's tag parser,
  an unbalanced `[/…]` in a mount name raised `MarkupError`, and `veth[0abc]` lost its
  suffix. `test_an_interface_name_with_brackets_is_still_shown` is the newest of the three
  tests that pin this. The encoding half of the problem is *not* closed — see gap 7.
* **intentional newlines inside error messages were flattened.** `main._plain()` escapes
  per line, so the two-line `ensure_dependencies` message reaches the terminal as two
  lines instead of literal `\x0a` (`tests/test_deps.py`).

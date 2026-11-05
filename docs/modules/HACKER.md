# Hacker (`levix hacker`)

Matrix rain plus a read-only tour of this machine's own network setup.

Source: `src/levix/modules/hacker/` (`__init__.py` manifest, `cli.py` command surface,
`core.py` simulation, tool runner, parsers). Entry point:
`levix.modules.hacker.cli:build_app`. Manifest declares `documentation =
"docs/modules/HACKER.md"`.

## Scope, and what this module is not

`hacker` is a terminal effect and a **local configuration reader**, intended for learning
what your own machine reports about itself and for recon you are authorised to do on a host
you own. Concretely, the code does not contain:

* a port scan, a ping, a traceroute, or any probe of another host;
* an exploit, payload, injector, credential reader or hash handling;
* any attempt at stealth - no spoofed user agent, no proxy, no randomised timing;
* any outbound connection, and any write to disk.

`core.py` states the two invariants in its own words: *"Honesty. A field is either parsed
from a real source or it stays None and the renderer says so. Nothing in this file
substitutes `0.0.0.0`, an empty MAC or a plausible adapter name for a value it could not
read."* and *"Local only. The helpers run read-only reporting tools (`ipconfig`, `route`,
`ip`, `ifconfig`) with `shell=False` and open a couple of well-known configuration files.
They never open a socket, never resolve a name through the network stack
(`socket.getfqdn` is unused on purpose because it can reach DNS), never send a packet and
never write anything."*

The two closing lines are printed by the commands themselves:

* `info` ends with: `every value above came from this machine: the OS, the interpreter and
  its own reporting tools. No packet left it.`
* `network` ends with: `read-only: this command runs the OS reporting tools and reads
  configuration files. It does not probe, scan or connect to anything.`

Be aware the output is still sensitive if you paste it elsewhere: MAC addresses, addresses,
DNS servers, hostname and your account name are exactly what these commands print.

## Commands

Three, registered from the manifest so `levix hacker -h` and the dashboard can never
disagree:

| Command | What it prints |
| --- | --- |
| `levix hacker matrix` | Matrix rain in the current terminal, `q` or Ctrl+C to stop. |
| `levix hacker info` | Host, interpreter, terminal and interface tables for this machine. |
| `levix hacker network` | Interfaces, default gateway, DNS servers, hostname resolution order, route table, and the source of every field. |

There is no `matrix`-style "hacker mode" switch, no profile file, and no command that takes
a target argument: **nothing here accepts a host, port or URL.**

### `matrix`

| Flag | Default | Effect |
| --- | --- | --- |
| `--duration SECONDS` | `0.0` | Stop after N seconds; `0` means no time limit. |
| `--iterations N` | `0` | Stop after N frames; `0` means no frame limit. |
| `--density CHANCE` | `0` | Per-column spawn chance; `0` uses `hacker.matrix_density`. |
| `--fps N` | `0` | Frames per second; `0` uses `hacker.matrix_fps`. Valid range 1-120. |
| `--seed N` | `-1` | Reproducible rain for one seed; `-1` means a different rain each run. |
| `--width N` | `0` | Columns; `0` uses the terminal width, clamped to the console width. |
| `--height N` | `0` | Rows; `0` uses `max(3, terminal rows - 2)` (one row for the status line, one so your prompt is not swallowed). |

Rules that are enforced rather than assumed:

* density must be between 0.001 and 0.5, fps between 1 and 120; outside those ranges the
  command exits 2 with `--fps must be between 1 and 120, got 500`;
* a negative `--duration` or `--iterations` is a usage error;
* **an unbounded run is refused when stdout is not a terminal**:
  `stdout is not a terminal, so the rain needs a bound: pass --iterations N or
  --duration SECONDS, otherwise nothing would ever stop it` (exit 2);
* `Live` is driven by hand (`auto_refresh=False`), so the frame rate is exactly `--fps` and
  the loop always terminates;
* `q` is polled without blocking - `msvcrt.kbhit`/`getwche` on Windows,
  `select` + `termios`/`tty` raw mode on POSIX with the saved settings restored on every
  path. Under a captured stream the poll returns `False` and never touches the tty;
* every glyph comes from `levix.terminal.active_glyphs()`, so a cp1252 console gets the
  ASCII set (`#`/`+`) instead of crashing Rich's win32 writer;
* the run ends with a factual summary, e.g.
  `2 frames at 60 fps across 79x22, stopped by --iterations, ASCII fallback for this stream`
  where the reason is `--iterations`, `--duration`, `the q key` or `Ctrl+C`.

The simulation (`core.MatrixScene`) uses digits as its charset, four brightness levels
(HEAD/NEAR/TAIL/FAINT), per-drop speeds 0.4-1.4, trails of 3-18 cells, a 2% per-frame
flicker chance, and `prime()` so the rain is already falling on the first frame. All
randomness comes from one owned `random.Random(seed)` - never global state - drawn in a
fixed order (spawn test per column, then per live drop, then per flicker), which is what
makes a seeded run reproducible. The `# noqa: S311` in the code says why: this is
decoration, and nothing security-relevant is drawn from it.

### `info`

Reads, in this order, and prints a table per group:

| Group | Fields and where each one comes from |
| --- | --- |
| This machine | `hostname` (`socket.gethostname()`, falling back to `platform.node()` with the reason printed), `system`/`release`/`version`/`machine`/`processor` (`platform.uname()`), `process id` (`os.getpid()`), `user` (`pwd` entry on POSIX, else `USERNAME`/`USER`/`LOGNAME`, else `getpass.getuser()`, each labelled with how it was obtained), `cpu count` (`os.cpu_count()`, logical only). |
| Interpreter | `platform.python_version()`, `platform.python_implementation()`, `sys.executable`. |
| Terminal | `shutil.get_terminal_size(fallback=(80,24))`, whether stdout is a tty, `sys.stdout.encoding`, `TERM`, the glyph mode in use, and the interface source that was found. |
| Local interfaces | The same interface table `network` prints. |
| Sources / notes | The tool table and the missing-data notes. |

The hostname is the line *under* that table rather than a row inside it. A cell is only as
wide as its column, and CI's macOS runner calls itself a 68-character mDNS name - three
characters more than the host table can afford at 80 columns - so a row folded it in the
middle of the token and the user got `iad20-...-C64BF1B94850.` newline `local` for the one
value here worth copying (`test_a_hostname_longer_than_the_table_stays_in_one_piece`).

`info` deliberately does **not** use `psutil`, and says so in its own output row:
`physical cores and load averages need psutil, which this module deliberately does not use;
\`levix monitor\` has them`. Verified against the source: the only imports in `core.py` are
standard library (`codecs`, `getpass`, `itertools`, `locale`, `os`, `platform`, `random`,
`re`, `shutil`, `socket`, `string`, `subprocess`, `sys`, `pathlib`, `dataclasses`,
`typing`), and the only `socket` call anywhere is `socket.gethostname()`.

### `network`

| Table | Content |
| --- | --- |
| Local interfaces | name, reported state, normalised MAC, addresses with CIDR prefix, DHCP yes/no/`-`. |
| Default gateway | address, interface, metric, and the source that reported it; `(directly connected, no gateway hop)` when the route table's gateway column was `0.0.0.0`. |
| DNS servers | ordered list with per-entry source, plus any search suffixes. |
| Hostname resolution order | numbered steps with the evidence file each one came from. |
| Route table | destination, prefix, gateway, interface, metric, source. |
| Where the data came from | every helper program that was tried, with status `ran`, `no data` or `missing`, and the absolute path it ran from. |
| notes | one yellow line per thing that could not be read. |

Address shapes are validated, not trusted: `normalise_mac` returns `None` unless exactly
twelve hex digits were found, `normalise_prefix` only converts a genuine netmask to a CIDR
length (a value like `255.255.255.1` is passed through rather than reported as a prefix it
never was), `strip_annotation` drops `(Preferred)`/`(Temporary)` markers, and `0.0.0.0` in
a gateway column is reported as "no gateway hop" instead of as an address.

## How the data is collected

`core.run_tool(argv, timeout=8.0)` is the only place a program is started, and it is
`shutil.which` first, then `subprocess.run([...], capture_output=True, timeout=8.0,
check=False, shell=False)` executing **the resolved absolute path**, so the PATH lookup and
the exec cannot disagree. Nothing is ever passed through a shell, and a command string is
never built. Output is decoded by trying `oem`, `cp850`, `cp437` then the locale encoding on
Windows (`oem` first, because console tools answer in the OEM codepage, not the ANSI one),
and the locale encoding then utf-8 elsewhere; the final fallback is `utf-8` with
replacement, so an unexpected byte can never raise.

Files are read with a 262,144-byte cap (`core.MAX_READ_BYTES`) and an unreadable file is
returned as `(None, reason)` rather than raised.

| Platform | Tools run | Files read |
| --- | --- | --- |
| Windows | `ipconfig /all`; `getadapterconfig /all`; `route print 0.0.0.0` | `%SYSTEMROOT%\System32\drivers\etc\hosts` |
| Linux with `ip` | `ip addr show`; `ip route show`; `ip -6 route show` | `/etc/resolv.conf`, `/etc/hosts`, `/etc/nsswitch.conf` |
| POSIX without `ip` | `ifconfig -a`; then `route -n get default` and `route -n` if `route` exists | the same three files |
| Anything else | nothing | the hosts file only, with the note `no reader is implemented for {system}, so nothing is reported` |

`getadapterconfig /all` is merged into the interface list when present, and its absence is
announced: on a stock Windows the note reads
`getadapterconfig is not installed (it is not a stock Windows program), so ipconfig /all is
the only interface source here` (observed on a real Windows run).

### "not available on this platform"

The renderer prints that literal - rather than an empty table or a guess - in four places:
`interface source` (no source found), `Default gateway` (no gateway candidate at all),
`DNS servers` (no server listed anywhere) and `Hostname resolution order` (nothing parsed).
Related honest strings: `no adapter could be read by any available tool` in the interface
table, `no route table could be read on this platform` in the route table,
`not reported` for a missing field, and `-` where a value is genuinely absent.

Platform-specific honesty notes you will actually see:

* `ipconfig /all` parsing keys off the **English** labels, so a localised Windows reports
  `ipconfig /all ran but matched no adapter sections; on a localised Windows the labels
  differ, so nothing was parsed rather than guessed`;
* on Linux, a failing `ip -6 route` is annotated `(IPv6 may be disabled)`;
* an empty `/etc/resolv.conf` nameserver list becomes
  `/etc/resolv.conf lists no nameserver (a stub resolver may own it)`;
* a missing `nsswitch.conf` `hosts:` line becomes
  `the resolution order below is only what could be read locally`;
* a tool that ran but produced nothing usable is reported as `no data`, distinct from
  `missing` (not on PATH) - `ToolResult` keeps `available` and `usable` as separate answers.

## Configuration

| Key | Schema | Default | Used by |
| --- | --- | --- | --- |
| `hacker.matrix_fps` | int, 1-120 | `30` (`data/defaults.toml`) | `matrix --fps 0` |
| `hacker.matrix_density` | float, 0.001-0.5 | `0.02` | `matrix --density 0` |

Both are read through the shared `LevixContext` (`ctx.value("hacker.matrix_fps")`) and can be
overridden by environment (`LEVIX_HACKER_MATRIX_FPS`, `LEVIX_HACKER_MATRIX_DENSITY`) or by
flag, in that precedence order: packaged default, then `config.toml`, then `LEVIX_*`, then
the flag. If reading a configured value raises, `matrix` falls back to the packaged default
and prints nothing about it, because a bad number must not kill the effect.

The manifest declares `requirements=()` and `extras=()` with the install hint
`nothing to install - \`hacker\` uses the Python standard library and the network tools
already shipped with your OS`, so there is no `levix[hacker]` extra and no dependency gate
that can fail. `info` and `network` still work when the OS tools are missing; they just
report that they are missing.

## What this module touches

| Aspect | Fact |
| --- | --- |
| Declared permissions | `Permission.SUBPROCESS`, `Permission.FS_READ` (`hacker/__init__.py`). The tests assert `Permission.NETWORK not in MANIFEST.permissions`. |
| Network | None. No socket is created; the only `socket` use is `gethostname()`. |
| Files read | The OS hosts file, `/etc/resolv.conf`, `/etc/nsswitch.conf` (POSIX paths only). Nothing under the user's home. |
| Files written | None. `core.py` states it and the code contains no write path. |
| Subprocesses | `ipconfig`, `getadapterconfig`, `route`, `ip`, `ifconfig`, via `shutil.which` + `shell=False`, 8-second timeout. |
| SQLite rows | One row per invocation in `levix_command_log`, written by `levix.main._record`, not by this module. |
| Log file | This module logs nothing itself. |
| Configuration read | `hacker.matrix_fps`, `hacker.matrix_density`. |
| Dashboard launch | `UiSpec(mode="suspend", argv=("hacker","matrix"))` - the dashboard releases the terminal and runs `levix hacker matrix` in a subprocess. |
| Lazy import | `__init__.py` is pure data; a child-process test asserts that importing it loads no `psutil`, `yt_dlp`, `sounddevice`, `soundfile`, `rich`, `typer`, `textual` or `httpx` and reports `3 []`. |

## Examples

```console
$ levix hacker matrix --iterations 200 --fps 60
$ levix hacker matrix --seed 7 --width 60 --height 12 --density 0.05
$ levix hacker info
$ levix hacker network
$ levix hacker network > netreport.txt      # bounded, captured output is fine for info/network
$ levix config set hacker.matrix_fps 20
```

## Exit codes and troubleshooting

| Code | Meaning here |
| --- | --- |
| 0 | Success, including a rain stopped by `q` or Ctrl+C. |
| 1 | Unexpected error - a LEVIX bug; the traceback tail is printed. |
| 2 | Bad usage: `--fps` or `--density` out of range, a negative `--duration`/`--iterations`, or an unbounded rain on a captured stream. |
| 3 | Not reachable: `hacker` declares no requirements. |
| 4 | Unknown command (`levix hacker recon` -> `unknown command: recon`). |
| 5 | Invalid configuration, raised while loading `config.toml` for any `levix` command. |
| 6 | Not reachable: `hacker` never asks for approval. |
| 7 | **Not used by this module**, and that is deliberate: a failing OS tool does not abort the command. `ToolResult` records `missing` / `no data` and the command prints it in the source table plus a note. Compare `levix ai command --run`, which does use exit 7. |
| 130 | Not reachable: Ctrl+C inside `matrix` is caught and reported as `stopped by Ctrl+C` with exit 0. |

Common symptoms:

| Symptom | Explanation |
| --- | --- |
| Every adapter table is empty on Windows | Localised Windows: the parsers key on English labels. The note says so instead of guessing. |
| `route` rows show `(directly connected, no gateway hop)` | The route table's gateway column contained `0.0.0.0`, which means no hop - it is not a missing value. |
| `getadapterconfig ... missing` in the source table | Normal on stock Windows. |
| Rain prints one frame and a summary | stdout is not a terminal; Rich writes the final frame and the summary states how many frames were produced. |
| `# ASCII fallback for this stream` | The stream cannot encode block glyphs, so the safe set was used. |

## Tests

`tests/modules/test_hacker.py` - 52 test functions, 78 collected cases on Windows, the extra
cases coming from five parametrised sets (invalid scene configurations, MAC spellings,
netmask forms, address shapes, out-of-range effect flags).

They cover:

* determinism and geometry of the simulation - a fixed seed repeats every frame exactly,
  different seeds differ, priming is deterministic too, the head character is always the
  head, higher density lights more cells, an unprimed scene reaches the bottom and resets;
* parsers against captured real output (`IPCONFIG_ALL`, `ROUTE_PRINT`, `IP_ADDR_SHOW`,
  `IP_ROUTE_SHOW`, `IFCONFIG_SHOW`, `RESOLV_CONF`, `NSSWITCH_CONF`, `ROUTE_N_SHOW`,
  `ROUTE_GET_DEFAULT`), including continuation lines as a second DNS server, annotations,
  on-link rows never becoming gateways, and gateway selection order
  (route table, lowest metric, then per-adapter value);
* that an empty gateway and a disconnected adapter stay unreported, and that `ipconfig`
  output with no adapter sections parses as nothing rather than as something;
* `run_tool`: a program not on PATH is reported, and a real run uses an argument list with
  no shell;
* the packaged contract, including `Permission.NETWORK not in MANIFEST.permissions`;
* lazy import, via a child process that must print `3 []`;
* the command surface: help lists all three commands, `info` prints the four tables and the
  real hostname without a traceback, `matrix` honours `--iterations`, `--duration`,
  `--seed` reproducibility and the captured-stream refusal, and out-of-range `--fps` /
  `--density` exit 2;
* two `@pytest.mark.integration` tests that run `network` for real and assert the four
  tables appear and that a placeholder gateway is never shown.

## Known gaps

1. **No test proves "no packet left the machine".** The claim in `cli.py` and the "never
   open a socket ... never send a packet" rule in `core.py` are carried today only by prose,
   by `assert Permission.NETWORK not in MANIFEST.permissions`, and by
   `test_run_tool_runs_an_argument_list_not_a_shell`. There is no socket guard, no
   `sys.modules`/`socket.socket` monkeypatch assertion and no `conftest.py` hook that would
   make a connect fail a test. A regression that opened a connection would not be caught.
   This is the module's central safety promise, so it deserves a test (for example an
   autouse fixture that patches `socket.socket`, `socket.create_connection` and
   `socket.getaddrinfo` to raise for the duration of the hacker tests).
2. The declared capabilities (`rich-live`, `ipconfig`, `getadapterconfig`, `route`, `ip`,
   `ifconfig`, `resolv-conf`, `hosts-file`) have no registered probe in
   `src/levix/capabilities.py`, and `levix doctor` reports only the registered probes
   (`capabilities.report()` with no names). Probing one of these names today returns
   `UNSUPPORTED` with `no probe registered for 'name'`. Nothing consumes
   `ModuleManifest.capabilities` at all, so this list is currently decoration.
3. Hosts-file content is counted, not shown: `network` reports how many static entries the
   hosts file has and never lists them, so a suspicious hosts file cannot be inspected with
   this module.
4. `matrix --fps`/`--density` silently fall back to the packaged defaults if reading the
   configured value raises, so a mis-set key shows up as an unexpected frame rate rather
   than as a configuration error. (The root callback normally validates `config.toml` before
   any command runs, so this path is defensive; it is untested.)
5. On a captured stream the rain cannot animate: Rich emits the final frame only. Documented
   above so nobody reads it as a broken effect.
6. `info` prints the CPU count from `os.cpu_count()`, which counts logical CPUs and is
   `None` on some platforms (`not reported by os.cpu_count()`). Physical cores, load
   averages, temperatures and GPU data are `levix monitor`'s job, and `info` points there.

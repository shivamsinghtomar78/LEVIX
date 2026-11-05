# LEVIX

**One CLI. Multiple applications. Unlimited extensibility.**

LEVIX is a modular terminal platform: a single `levix` command that launches a set of
terminal applications, wrapped in an interactive dashboard, and extensible by
third-party plugins that use the same interface the official modules use.

MIT licensed · Python 3.12+ · Windows, Linux and macOS (the suite has run on Windows 11 so far).

## Install

**From this repository — works today** (Python 3.12+ required):

```bash
python -m pip install "levix[all] @ git+https://github.com/shivamsinghtomar78/LEVIX.git"

# or isolated, one command per tool:
pipx install "levix @ git+https://github.com/shivamsinghtomar78/LEVIX.git"
pipx inject levix psutil          # add one module's capability at a time
```

Verified on 2026-11-05: this installs `levix 0.4.0` with the six direct dependencies and
their transitive ones - no psutil, yt-dlp, soundfile, httpx or keyring - `levix --version`
answers, `levix plugins list` marks the modules whose extras are absent (`needs yt-dlp`,
`needs psutil`, …), and `levix monitor cpu` refuses with exit 3 and names the extra to
install.

**From PyPI — after the first release.** `levix` is an unclaimed name on the index today
(`https://pypi.org/pypi/levix/json` returns 404), so these two lines describe the target, not
the present. `.github/workflows/release.yml` is what makes them true:

```bash
pipx install levix                 # recommended: isolated environment, one command
python -m pip install levix        # or into any environment you choose
```

Optional capabilities are separate extras, so the core stays light:

```bash
pipx inject levix psutil           # or install "levix[all]" for every module
```

| Extra | Enables |
|---|---|
| `[monitor]` | `levix monitor` (psutil) |
| `[tube]` | `levix tube` (yt-dlp) |
| `[music]` | `levix music` (sounddevice + soundfile) |
| `[ai]` | `levix ai` (httpx) |
| `[secrets]` | OS keyring storage for API keys (keyring) |

`levix music play` with an `http(s)` link instead of a file also needs `[tube]` (for
yt-dlp) and `ffmpeg` on `PATH`; a file on disk needs neither, because libsndfile decodes
it in-process.

## Use

```bash
levix                       # interactive dashboard
levix --help                # every command and module
levix --version

levix monitor cpu           # system vitals
levix monitor live
levix hacker matrix
levix files browse
levix tube download URL
levix music play song.wav
levix music play "https://example.com/song"   # a link needs [tube] + ffmpeg; bars on a TTY
levix game snake
levix ai ask "why is my build slow"

levix doctor                # what is installed, what works, what is unsupported
levix config show
levix plugins list
```

Running a module whose extra is missing tells you the exact install command and exits
with code `3`. LEVIX never prints an `ImportError` traceback at you.

## What LEVIX does not do

- **No fake metrics.** If the platform cannot read a temperature sensor or GPU usage,
  `levix monitor` says *unsupported* instead of showing a zero.
- **No automatic execution of AI output.** `levix ai command` shows you the command and
  requires you to type it back before anything runs.
- **No silent installs.** `levix update` reports a newer release and prints the command;
  it does not modify your environment.
- **No claim that plugins are sandboxed.** A Python plugin runs with LEVIX's full
  privileges. See [docs/security/THREAT_MODEL.md](docs/security/THREAT_MODEL.md).

## Extend it

```bash
levix create-module weather
cd weather && pip install -e .
levix plugins list
```

The scaffolded package exports a `ModuleManifest` (pure data) and a lazily imported
Typer app — the same two things every official module provides.
[docs/architecture/PLUGIN_ARCHITECTURE.md](docs/architecture/PLUGIN_ARCHITECTURE.md) is
the reference.

## Documentation

Start at [docs/INDEX.md](docs/INDEX.md): requirements, architecture, module specs,
plugin SDK, security model, and the phase roadmap.

## Status

Version 0.4.0 delivers the core engine, the dashboard and all seven official modules. What
is *not* done is stated rather than implied: every hand run behind these pages was made on
one Windows 11 machine, and the CI matrix that covers Linux and macOS has now run seven times
- the fourth (`5b047ad`), fifth (`75daed2`) and sixth (`3d460df`) are all **green on all
seven jobs**, so the
suite, the linter, the
formatter and the type checker pass on Ubuntu, macOS and Windows at Python 3.12 and 3.13,
and the no-extras wheel job passes on Ubuntu. The seventh (`c49d608`) ends `failure` without
implicating the tree: six of its seven jobs are `success`, and `macos-latest / Python 3.12` was
`cancelled` with no runner ever acquired - the run page says "The job was not acquired by Runner
of type hosted even after multiple attempts". Its useful half is that it is the first run carrying
`tests/test_update.py` and `tests/test_create_module.py`, so those 19 functions and 23 cases -
including the one that generates a plugin and runs `pytest` inside the generated project in a
child interpreter - executed on Ubuntu, Windows and macOS 3.13 and reached no failure.
Run #5 is the one that carries the log-redaction
tests, including the case that opens a real rotating `levix.log` and reads the bytes back, so
that promise now holds on three operating systems. Run #6 carries the key-store permission
tests (`tests/test_secrets.py`), whose three POSIX file-mode cases skip on this machine and
therefore *ran* - and did not fail - on the Ubuntu and macOS columns. What that does not buy:
the columns skip the
ten device and OS-tool cases, nothing here has been hand-run on Linux or macOS, a green column
proves a branch was reached rather than a POSIX behaviour observed, and the release workflow
that would put
`levix` on PyPI has never run. Plugin *install* and standalone binaries remain open.
[docs/roadmap/CURRENT_STATUS.md](docs/roadmap/CURRENT_STATUS.md)
lists what is proven, how it was proven, and the thirteen things no reader should quote as
verified.

## License

MIT. See [LICENSE](LICENSE).

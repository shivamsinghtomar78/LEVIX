# LEVIX

**One CLI. Multiple applications. Unlimited extensibility.**

LEVIX is a modular terminal platform: a single `levix` command that launches a set of
terminal applications, wrapped in an interactive dashboard, and extensible by
third-party plugins that use the same interface the official modules use.

MIT licensed · Python 3.12+ · Windows, Linux and macOS.

## Install

```bash
pipx install levix                 # recommended: isolated environment, one command
python -m pip install levix        # or into any environment you choose
```

Optional capabilities are separate extras, so the core stays light:

```bash
pipx install "levix[all]"          # every module dependency
pipx inject levix psutil           # or add one at a time
```

| Extra | Enables |
|---|---|
| `[monitor]` | `levix monitor` (psutil) |
| `[tube]` | `levix tube` (yt-dlp) |
| `[music]` | `levix music` (sounddevice + soundfile) |
| `[ai]` | `levix ai` (httpx) |
| `[secrets]` | OS keyring storage for API keys (keyring) |

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

Version 0.4.0 delivers the core engine, the dashboard and all seven official modules.
The plugin *install* workflow, CI matrices and standalone binaries are scheduled in
[docs/roadmap/CURRENT_STATUS.md](docs/roadmap/CURRENT_STATUS.md) — they are not
implemented yet, and this README does not pretend otherwise.

## License

MIT. See [LICENSE](LICENSE).

# Python Packaging

What is true today, as found in this tree on 2026-11-04 - not what the roadmap
hopes will be true.

## Build system

From `pyproject.toml`:

- Backend: `hatchling.build`, requires `hatchling>=1.33,<2`. Hatchling is **not**
  installed in `.venv`; build isolation fetches it into a throwaway env per build.
- Project: name `levix`, version `0.4.0`, `requires-python = ">=3.12"`,
  `license = "MIT"` with `license-files = ["LICENSE"]`.
- Console script: `levix = "levix.main:main"`. `src/levix/__main__.py` also
  exists, so `python -m levix ...` works - that is the form `src/levix/spawn.py`
  uses when re-entering LEVIX from the dashboard.
- Wheel target: `packages = ["src/levix"]`, plus a
  `[tool.hatch.build.targets.wheel.force-include]` entry mapping
  `src/levix/data` to `levix/data`.
- sdist target: includes `src`, `tests`, `docs`, `plugin-examples`, `README.md`,
  `LICENSE`, `CHANGELOG.md`. `plugin-examples/hello/` is a real, installable distribution
  (`levix-hello`, its own `pyproject.toml` and `src/` layout), so the include is not
  pointing at a directory that only exists in this document.

## How it is installed today

Development uses a project-local virtualenv, per `CONTRIBUTING.md`:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (the shell used for every command in this repo)
pip install -e ".[dev,all]"
pre-commit install
```

`pip list` confirms `levix 0.4.0` installed **editable** from
`C:\Users\Shiva\Downloads\project\LEVIX`. The editable path works because
hatchling's editable hook does not assemble a wheel archive.

## `python -m build` — both artefacts succeed

Verified by running `.venv/Scripts/python.exe -m build --outdir <temp dir>` (so no build
artefacts entered the repository) on 2026-11-05:

- **sdist: succeeds** - produced `levix-0.4.0.tar.gz`.
- **wheel: succeeds** - produced `levix-0.4.0-py3-none-any.whl`, 65 entries, with
  `levix/data/defaults.toml` present exactly once and 26 files under `levix/modules/`.
- Build isolation fetched `hatchling==1.33.0` into a throwaway environment; hatchling is
  still not installed in `.venv`, which is the point of isolation.

This section used to record a failure: `packages = ["src/levix"]` already ships everything
under `src/levix`, so the `force-include` of `src/levix/data` made hatchling add
`levix/data/defaults.toml` to the archive twice and abort the wheel with
`ValueError: A second file is being added to the wheel archive at the same path`. The same
failure broke any non-editable install from source (`pip install .` died preparing
metadata). The redundant `force-include` entry is gone, and `pyproject.toml` says so in a
comment so it does not come back.

### What the wheel was then checked against

The same day, the wheel was installed into a fresh `python -m venv` with nothing else in it
(`pip install <wheel>` only, so no extra, no source tree, no `.venv`), with `LEVIX_HOME`
pointed at a temporary directory:

| Check | Result |
|-------|--------|
| `levix --version` | `levix 0.4.0` |
| `levix <module> -h` for all seven modules | exit 0 for each - the lazy-import rule means a bare install still explains itself |
| `levix monitor cpu`, `music devices`, `ai models`, `tube info x` | exit 3 each, with the message on two lines and `install it with: pip install "levix[monitor]"` naming the right extra |
| `levix plugins list` | renders the seven official modules, three of them marked `needs psutil` / `needs soundfile, sounddevice` / `needs yt-dlp` |
| `levix game scores` | exit 0 - arcade needs no extra |
| `levix doctor` | exit 3, which is `exit_code_for()` reporting the missing extras as blocking findings, not a crash |

So the core/extras split is now verified from an installed distribution rather than only
from the editable install, which is what `docs/technology/DEPENDENCIES.md` previously said
could not be done.

## Extras design

`[project.optional-dependencies]` (exact pins in `DEPENDENCIES.md`): `monitor`,
`tube`, `music`, `ai`, `secrets` carry the one heavy dependency each module needs;
`all` is `levix[ai,monitor,music,secrets,tube]`; `dev` carries build, mypy,
pre-commit, pytest, pytest-cov, ruff. Core carries typer, click, rich, textual,
tomlkit, platformdirs - including Textual, so the dashboard works from a bare
install.

Extras are also a runtime contract, not just a build detail: each module's
`MANIFEST.requirements`/`extras` feed `deps.ensure_dependencies`, so running a
module whose extra is absent exits 3 with `pip install "levix[<extra>]"` printed
(`ModuleManifest.resolved_install_hint()`).

## How a plugin declares itself

Standard importlib metadata, group `levix.plugins`. The seven official modules do
it in `pyproject.toml`, e.g.:

```toml
[project.entry-points."levix.plugins"]
tube = "levix.modules.tube:MANIFEST"
music = "levix.modules.music:MANIFEST"
game = "levix.modules.arcade:MANIFEST"
```

A third-party distribution declares the same group for its own package;
`registry.discover()` loads each entry point (a pure-data `ModuleManifest`), and
origin is stamped by the registry from the provider distribution - a plugin
cannot claim to be official. A broken entry point does not stop LEVIX: it shows
up as `is_broken()` in `levix plugins list` and `levix doctor`. `levix
create-module yourname` scaffolds an installable package that follows this
contract.

## Deferred / not implemented

Confirmed absent from this tree as of writing:

- **PyPI / TestPyPI publication**: nothing has been uploaded; README's
  `pipx install levix` describes the target state. `levix update` queries
  `https://pypi.org/pypi/levix/json`, which cannot report a real "latest" while
  the name is unpublished.
- **Standalone binaries**: PyInstaller is not installed and not referenced in
  `pyproject.toml`; only `spawn.py::is_frozen()` anticipates a frozen build.
  (See `DEPENDENCIES.md` for the licence note: PyInstaller is GPL-2.0-or-later
  **with its linking exception** - that exception is why an MIT project may use
  it; PyInstaller is not MIT.)
- **CI**: no `.github/` directory exists; `.pre-commit-config.yaml` is the only
  gate, and CONTRIBUTING's claim "hooks mirror CI" describes something not built.
- **Wheel builds**: no longer the blocker they were - `python -m build` produces both
  artefacts and a throwaway install of the wheel behaves as recorded above. What is still
  missing is a place to put them: no index is configured, no release workflow exists, and
  the version has never been published.

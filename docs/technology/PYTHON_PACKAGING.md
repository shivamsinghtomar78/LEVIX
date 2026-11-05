# Python Packaging

What is true today, as found in this tree on 2026-11-05 - not what the roadmap
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
- Wheel target: `packages = ["src/levix"]` and nothing else. Every file under
  `src/levix` is carried by that one declaration, `data/defaults.toml` included;
  an additional `force-include` of the same directory is what once aborted the
  build (see below).
- Typing: `src/levix/py.typed` is present, because `pyproject.toml` claims the
  `Typing :: Typed` classifier and a plugin author's editor only gets inline
  types from `levix.sdk` if the marker ships with the distribution.
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
- **wheel: succeeds** - produced `levix-0.4.0-py3-none-any.whl`, 66 entries, with
  `levix/data/defaults.toml` present exactly once, `levix/py.typed` present and 26 files
  under `levix/modules/`. Re-measured after the typing marker was added (65 entries before
  it), and `levix-0.4.0.dist-info/entry_points.txt` is in the archive - which is how
  `registry.discover()` finds the seven official modules in an installed distribution at
  all. `.github/workflows/ci.yml` asserts exactly those two files and the single copy, so
  the claim is now a gate rather than a note.
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

## Publishing

Two workflow files do the work, and neither needs a secret stored in the repository.

**`.github/workflows/ci.yml`** runs on every push to `main` and every pull request. The
`suite` job is the matrix the rest of these pages keep promising: `ubuntu-latest`,
`macos-latest` and `windows-latest` × Python `3.12` and `3.13`, each installing
`.[all,dev]`, then `ruff check`, `ruff format --check`, bare `mypy` (whose configured
`files` also cover `plugin-examples`) and `pytest -m "not integration"`. The
`core-stays-light` job is the one that tests the design rather than the code: it builds the
wheel, installs it into an empty venv **with no extras**, then asserts that no heavy package
was pulled (`pip freeze` must not contain psutil, yt-dlp, soundfile, sounddevice, numpy,
httpx or keyring), that `monitor overview`, `music devices`, `tube info …` and `ai check`
each refuse with exit 3, that the stdlib-only surface still answers (`--version`,
`hacker info`, `files search`, `game scores`, and `plugins list` marking what is missing), and
that the archive contains `levix/py.typed` and exactly one `levix/data/defaults.toml`.
`doctor --json` is accepted there with exit 0 **or** 3 on purpose: `exit_code_for`
(`src/levix/doctor.py:116-123`) returns 3 when a `module:` row is MISSING, which is exactly
what a bare install should report, so a 0 would mean the diagnostic had gone quiet.
Every command in that job was run by hand on 2026-11-05 against `dist/*.whl` installed into
an empty venv on this Windows box - the whole list, under `bash -eo pipefail` like the
runner's default shell, green - and the job itself has run on a real Ubuntu runner, in all
three CI runs, and passed every time.

**`.github/workflows/release.yml`** runs **only on a `v*` tag**, in three jobs:

| Job | What it does | Why it is there |
| --- | --- | --- |
| `build` | checks the tag against `[project].version`, re-runs lint, types and the suite, then `python -m build` and `twine check dist/*`, and uploads `dist/` as an artefact | a tag that skipped the version bump would publish the previous release's bytes under a new name |
| `github-release` | `sha256sum` over the artefacts into `SHA256SUMS.txt`, then `gh release create --repo … --verify-tag --generate-notes` with `dist/*` attached (the job has no checkout, so the repo has to be named) | so someone can verify the file they downloaded without trusting the transport |
| `publish-pypi` | `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` and `environment: pypi` | trusted publishing: PyPI accepts a GitHub OIDC token because the project on PyPI names this repo, this workflow and this environment. No API token exists on this laptop or in the repo, and the pairing is revoked from the PyPI side |

### The one-time setup that only the maintainer can do

Nothing above is reachable until these exist; a checkout cannot create them.

1. A PyPI account with 2FA enabled - PyPI requires it for any upload.
2. The name. `https://pypi.org/pypi/levix/json` answers **404** today and
   `pip download levix` finds no distribution, so `levix` is unclaimed as of 2026-11-05.
   PyPI's own similar-name rules have the last word at upload time, so this is an
   observation, not a reservation.
3. A project called `levix` on PyPI, with a *trusted publisher* pointing at
   repository `shivamsinghtomar78/LEVIX`, workflow `release.yml`, environment `pypi`.
4. The `pypi` environment in GitHub Settings → Environments. The job names it; adding a
   required reviewer there is how a release gets a human gate instead of an automatic one.
5. `git tag v0.4.0 && git push origin v0.4.0` - no tag exists in this repository yet, which
   is the other reason "released" is not a word used anywhere in these pages.

Rehearsing against TestPyPI is manual: `release.yml` targets PyPI only, so a dry run is
`python -m build && python -m twine upload --repository testpypi dist/*` with a TestPyPI
account, or a temporary `repository-url: https://test.pypi.org/legacy/` on the action. It is
worth doing once, because PyPI refuses to overwrite a version - a mistaked first release is
yanked, not fixed.

## Deferred / not implemented

Confirmed absent from this tree as of writing:

- **Publication**: nothing has been uploaded. README's `pipx install levix` describes the
  state the workflows above reach, not today's. `levix update` therefore answers
  `could not check for updates: PyPI returned 404` and exits 8 - verified on this machine on
  2026-11-05 - because it refuses to imply you are up to date when it could not ask.
- **A green matrix**: three runs, all on 2026-11-05, on the commits that added the files.
  Run #1: the wheel job passed on Ubuntu in 31 s; the four POSIX columns died at `mypy` on a
  Windows-only stat attribute, and both Windows columns died inside the suite. Run #2
  reported "5 successful and 2 failing" and was wrong in both directions - Actions' default
  `run:` shell is `bash -e` **without** `pipefail`, so `pytest | tee pytest.log` handed the
  step tee's exit 0 and Linux/macOS went green over a failing suite, while the Windows jobs
  died in pwsh before pytest started at all. The job now pins `defaults.run.shell: bash` and
  redirects to a file instead of piping, and re-emits every `FAILED` line as a `::error::`
  annotation so a red column names itself to anyone, without a signed-in account. Run #3 is
  the first trustworthy result: red on all six columns, on eight test functions that depend
  on the machine they run on. All eight are fixed in the tree and run #4 decides whether that
  was the whole list, so the numbers quoted in these pages remain hand runs on one Windows 11
  laptop until a column goes green - which is what `docs/roadmap/CURRENT_STATUS.md` says at
  the top of its page.
- **Standalone binaries**: PyInstaller is not installed and not referenced in
  `pyproject.toml`; only `spawn.py::is_frozen()` anticipates a frozen build. A frozen build
  has one thing to prove before it is usable: discovery reads
  `levix-0.4.0.dist-info/entry_points.txt` through `importlib.metadata`, so the packaging
  step must carry that metadata (`--copy-metadata levix`) or `levix --help` lists nothing.
  (See `DEPENDENCIES.md` for the licence note: PyInstaller is GPL-2.0-or-later **with its
  linking exception** - that exception is why an MIT project may use it; PyInstaller is not
  MIT.)
- **Wheel builds**: no longer the blocker they were - `python -m build` produces both
  artefacts, a throwaway install of the wheel behaves as recorded above, and `ci.yml` now
  re-runs that install on every push. What is still missing is the index side: no project
  exists on PyPI, so the artefacts have nowhere to go.

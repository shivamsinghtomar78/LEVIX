# Documentation index

One repository, one documentation set, no duplicated pages. This is the map.

Two rules govern the whole set, and they are the reason the pages read the way they do:

* **A page says what the code does today, not what the roadmap hopes.** Where something is
  designed but not built, the page says so in a *Known gaps* section instead of describing
  the intention as if it shipped.
* **A claim is only as good as the platform it was checked on.** The hand runs behind these
  pages were made on Windows 11 (`sys.platform = "win32"`), Python 3.12.10. GitHub Actions
  has executed the suite on Ubuntu and macOS too, and run #4 (`5b047ad`) came back **green on
  all seven jobs** - `Lint`, `Format`, `Types` and `Test suite` on six columns and the
  no-extras wheel job. Run #3 had put all six columns red on eight machine-dependent tests;
  every one of those eight is now confirmed fixed on the machine that found it. What the
  green still does not say: the columns run `-m "not integration"`, so the ten device and
  OS-tool cases have never run anywhere but here; no human has run a command on Linux or
  macOS; and the POSIX behaviours listed in `docs/roadmap/CURRENT_STATUS.md` §What is not
  verified have no assertion behind them. Quote those, not the colour of the badge.

Start with `requirements/PRD.md` for the product, `architecture/SYSTEM_ARCHITECTURE.md`
for the shape, and `roadmap/CURRENT_STATUS.md` for where the work actually stands.

## requirements/ — what the product owes the user

| File | Read it for |
|---|---|
| `requirements/PRD.md` | the mission ("One CLI. Multiple applications. Unlimited extensibility."), the seven modules, the non-goals, and the doc-set decisions themselves. |
| `requirements/FUNCTIONAL_REQUIREMENTS.md` | the FR-numbered behaviour list, each row with the code that implements it and the test that pins it. |
| `requirements/NON_FUNCTIONAL_REQUIREMENTS.md` | NFR-numbered budgets: startup cost, lazy imports, log rotation, exit codes, accessibility of a text terminal. |
| `requirements/USER_STORIES.md` | the tasks in the user's own words, with the command that satisfies each one and the ones that do not. |
| `requirements/ACCEPTANCE_CRITERIA.md` | the checklist a release has to pass, marked with what has been run and where. |

## architecture/ — how the code is put together

| File | Read it for |
|---|---|
| `architecture/SYSTEM_ARCHITECTURE.md` | the whole diagram: process, layers, boundaries, and the questions each other page answers. |
| `architecture/CORE_ENGINE.md` | the modules under `src/levix/` and their contracts - router, registry, config, storage, deps gate, doctor, terminal rendering. |
| `architecture/COMMAND_ARCHITECTURE.md` | how `levix <thing>` becomes a running command, including the forwarding design and why it is not a `click.Group` subclass. |
| `architecture/MODULE_ARCHITECTURE.md` | what a module is: `ModuleManifest`, `CommandInfo`, `UiSpec`, gates, capabilities, the lazy-import rule. |
| `architecture/PLUGIN_ARCHITECTURE.md` | the `levix.plugins` entry-point group, origin stamping, the SDK façade, and what installing third-party code would require. |
| `architecture/CONFIGURATION_ARCHITECTURE.md` | the layered resolver (default → packaged file → user file → environment → flag), the `SCHEMA` table, and why secrets are refused at the config layer. |
| `architecture/DATA_STORAGE.md` | `levix.db`, the migration namespaces, retention, and how stored text is rendered back. |
| `architecture/ERROR_HANDLING.md` | the exception hierarchy, the single exit-code table, and what each code promises. |

## modules/ — one page per official module

| File | Command | One line |
|---|---|---|
| `modules/TUBE.md` | `levix tube` | Inspect, download or play online video through yt-dlp, with honest gates and no DRM circumvention. |
| `modules/HACKER.md` | `levix hacker` | Read-only local network and environment introspection, plus wrappers over the OS's own tools. Authorized use only. |
| `modules/SYSTEMPULSE.md` | `levix monitor` | CPU, memory, disk, network, processes, sensors and battery through psutil, with unsupported rows kept visible. |
| `modules/AI.md` | `levix ai` | Chat, explain and command-proposal against an OpenAI-compatible server or Ollama, with a typed gate before anything runs. |
| `modules/MUSIC.md` | `levix music` | Local playback and inspection through sounddevice/soundfile, in-process, no ffmpeg dependency. |
| `modules/ARCADE.md` | `levix game` | Tetris and Snake screens plus a shared score table, deterministic when seeded. |
| `modules/FILES.md` | `levix files` | Browse, search, preview, copy, move, rename and delete, behind a path wall and a typed confirmation. |

Each page documents its commands, flags, exit codes, observed behaviour on this machine,
its tests, and its known gaps. The `documentation` field of every shipped manifest points
into this directory, so `levix plugins info <name>` prints a path that exists.

## security/ — what is protected, and by what

| File | Read it for |
|---|---|
| `security/THREAT_MODEL.md` | the assets, the trust boundaries, each control with the code that implements it, and a table of what remains unmitigated. |
| `security/PERMISSIONS.md` | the `Permission` enumeration and the fact that it is disclosure, not enforcement - with the per-module declarations and the code that actually does the thing declared. |
| `../SECURITY.md` (repo root) | how to report a vulnerability, and what the project considers in scope. |

## technology/ — the stack as installed

| File | Read it for |
|---|---|
| `technology/TECH_STACK.md` | every dependency, its installed version and why it was chosen over the alternative. |
| `technology/DEPENDENCIES.md` | the core/extras split, licence notes, and the lazy-loading invariant with the tests that prove it. |
| `technology/PYTHON_PACKAGING.md` | hatchling config, what `python -m build` produces, the throwaway-install verification, and what is still unpublished. |
| `technology/COMPATIBILITY.md` | Python and OS support matrix, and which parts are proven by CI on which runner rather than by hand. |
| `technology/OPEN_SOURCE_TOOLS.md` | the external programs LEVIX can shell out to (ffmpeg, players, OS network tools) and how each is gated. |

## decisions/ — the six decisions that shape the rest

| File | Decision |
|---|---|
| `decisions/ADR-0001-entry-point-discovery.md` | Discovery is `importlib.metadata` entry points, not a directory scan. |
| `decisions/ADR-0002-one-contract-for-modules-and-plugins.md` | Official modules and third-party plugins share one contract. |
| `decisions/ADR-0003-forwarding-router.md` | A module is a forwarding command, not an import. |
| `decisions/ADR-0004-toml-config.md` | `tomllib` reads, `tomlkit` writes, and comments survive. |
| `decisions/ADR-0005-secret-storage.md` | Secrets: environment first, OS keyring second, owner-only file last. |
| `decisions/ADR-0006-extras-and-the-gate.md` | One distribution, optional extras, and a gate that refuses before importing. |
| `decisions/ADR_TEMPLATE.md` | The shape a new ADR has to follow. |

## roadmap/ — the handoff

| File | Read it for |
|---|---|
| `roadmap/CURRENT_STATUS.md` | What is built, what is tested, on which platform, what was fixed most recently, and what the next session should do first. Written to be read cold. |

## Outside `docs/`

| File | What it is |
|---|---|
| `README.md` | Install, first commands, the module table, and links into this set. |
| `CONTRIBUTING.md` | The coding rules a change has to satisfy, including the lazy-import rule and the markup-escaping rule. |
| `CHANGELOG.md` | Release history, with an `Unreleased` section that carries the current work. |
| `SECURITY.md` | Vulnerability reporting. |
| `LICENSE` | MIT. |
| `.github/workflows/ci.yml` | The matrix that runs the lint, type and `-m "not integration"` suite on Linux, macOS and Windows, plus a wheel installed with no extras. Added 2026-11-05, run five times: the wheel job has passed on Ubuntu every time, run #3 is the first suite result that can be trusted (red on all six columns, on eight machine-dependent tests, all eight then fixed) and **runs #4 (`5b047ad`) and #5 (`75daed2`) are green on all seven jobs**. Run #5 is the one that first executed the file-backed log-redaction case on Linux and macOS; the next run is the one that first executes the three POSIX file-mode cases in `tests/test_secrets.py`. The green covers only the non-`integration` set. |
| `.github/workflows/release.yml` | Tag-triggered build, GitHub release and PyPI upload through trusted publishing. Has never run, and cannot until the PyPI project exists. |
| `plugin-examples/hello/` | A real, installable example plugin: its own `pyproject.toml`, one manifest, one command. |
| `src/levix/` | The code. Docstring comments explain *why*; this directory explains *what*. |

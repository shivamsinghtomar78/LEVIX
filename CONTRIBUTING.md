# Contributing to LEVIX

Thank you for taking the time. This document tells you how the project is built so
that your change lands without a round trip of rework.

## Before you start

- Work on Python 3.12 or newer. LEVIX declares `requires-python = ">=3.12"`.
- Create the environment inside the repository. Never install into a shared
  interpreter:

```bash
python -m venv .venv
# Windows PowerShell / cmd
.venv\Scripts\activate
# Linux and macOS
source .venv/bin/activate

pip install -e ".[dev,all]"
pre-commit install
```

## The three rules that shape everything else

1. **The core stays light.** `levix` itself depends on typer, rich, textual, click,
   platformdirs and tomlkit only. A module dependency belongs in a PEP 621 extra, and
   the module must report the missing extra with an install hint rather than an
   `ImportError`.
2. **A module is data plus a lazy factory.** Export a `ModuleManifest` from
   `__init__.py` and build the Typer app in `cli.py`. Importing heavy packages at
   module scope breaks `levix --help`, which is a test failure, not a style opinion -
   see `tests/test_router.py::test_help_forwarding_does_not_import_a_heavy_dependency`,
   which runs the real entry point in a child interpreter and inspects its `sys.modules`.
3. **Text the core did not write is escaped before it is printed.** An install hint
   (`pip install "levix[tube]"`), a plugin's summary, a filename, a line of command
   history: Rich reads `[...]` as a style tag and deletes it. Use
   `levix.terminal.markup_safe` when interpolating into a markup string, or print with
   `markup=False`. `tests/test_markup_safety.py` is the regression net.

## Development workflow

```bash
ruff check src tests plugin-examples
ruff format src tests plugin-examples
mypy                                # [tool.mypy].files already includes plugin-examples
pytest                          # all 705 cases; no network, no real TTY
pytest -m integration           # only the 10 that touch a device or a real OS tool
pytest -m "not integration"     # the CI-safe subset (695 cases)
levix doctor
```

`.github/workflows/ci.yml` runs this same set - plus a job that installs the built wheel
with **no** extras and asserts the heavy modules refuse with exit 3 - on
`ubuntu-latest`, `macos-latest` and `windows-latest` against Python 3.12 and 3.13. Write
tests that do not depend on the machine: a case that needs sound hardware, a symlink the
runner may not be allowed to create, or a terminal width is an `integration` case or is
given its width explicitly, because a runner that disagrees with your laptop is the only
way this project finds out. The hooks in `.pre-commit-config.yaml` mirror the lint, format
and type steps so CI is not a surprise; the suite is not in a hook because it takes ~2.5
minutes.

Every command needs: help text, argument validation, a predictable exit code, an entry
in the exit-code table if it is a new failure class, and a test. If you add a
configuration key, add it to `SCHEMA` **and** to `src/levix/data/defaults.toml`; the
config loader raises if the two disagree, on purpose.

## Proposing a change

- Branch from `main`, one concern per branch.
- If the change alters an architectural decision, add an ADR to `docs/decisions/`
  using `docs/decisions/ADR_TEMPLATE.md`. ADRs record why, not just what.
- Update docs in the same commit as code. Documentation that contradicts behaviour is
  treated as a bug; `docs/requirements/NON_FUNCTIONAL_REQUIREMENTS.md` and this file are
  the standards a review is measured against.
- Run the full check set before opening the pull request and paste the output.

## Adding a module (or a plugin)

`levix create-module yourname` scaffolds a correct, installable package. Then:

- Declare `requirements` and `extras` truthfully; `levix doctor` and
  `levix plugins list` render exactly what you declare.
- Declare `permissions` as a disclosure of intent. They are not enforced, and the docs
  say so. Overstating them is a review blocker; understating them breaks users.
- Never write to paths outside `ctx.paths` without asking, and never log a secret.

## Reporting problems

Include `levix doctor` output (it contains no secrets - the log redactor also masks
key-shaped strings) and the exact command you ran. Note your OS and Python version;
platform-specific failures are taken seriously rather than closed as "works for me".

## Style

Ruff is the formatter and linter; its configuration in `pyproject.toml` wins over
personal preference. Type hints are required on public functions. Prefer a clear
10-line function over an abstraction that needs explaining. No `print()` in `src/`
(`T20` is enabled for that reason) - use the Rich console.

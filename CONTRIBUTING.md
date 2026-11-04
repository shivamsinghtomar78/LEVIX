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

## The two rules that shape everything else

1. **The core stays light.** `levix` itself depends on typer, rich, textual, click,
   platformdirs and tomlkit only. A module dependency belongs in a PEP 621 extra, and
   the module must report the missing extra with an install hint rather than an
   `ImportError`.
2. **A module is data plus a lazy factory.** Export a `ModuleManifest` from
   `__init__.py` and build the Typer app in `cli.py`. Importing heavy packages at
   module scope breaks `levix --help`, which is a test failure, not a style opinion -
   see `tests/test_lazy_loading.py`.

## Development workflow

```bash
ruff check src tests
ruff format src tests
mypy src/levix
pytest                          # unit + CLI tests, no network
pytest -m integration           # real end-to-end flows
levix doctor
```

Every command needs: help text, argument validation, a predictable exit code, an entry
in the exit-code table if it is a new failure class, and a test. If you add a
configuration key, add it to `SCHEMA` **and** to `src/levix/data/defaults.toml`; the
config loader raises if the two disagree, on purpose.

## Proposing a change

- Branch from `main`, one concern per branch.
- If the change alters an architectural decision, add an ADR to `docs/decisions/`
  using `ADR_TEMPLATE.md`. ADRs record why, not just what.
- Update docs in the same commit as code. Documentation that contradicts behaviour is
  treated as a bug, per `docs/development/CODING_STANDARDS.md`.
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

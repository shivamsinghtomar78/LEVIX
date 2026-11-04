"""Re-entering the LEVIX process, correctly, from inside itself.

The dashboard runs modules in a subprocess so that exactly one Textual app owns the
terminal at a time. Building that argv is subtly platform- and packaging-dependent:
a PyInstaller frozen build has no `-m levix` to invoke and must re-run its own
executable, while a source checkout must use the *same interpreter that has the
dependencies* rather than whatever `python` is first on PATH.
"""

from __future__ import annotations

import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def levix_argv(*args: str) -> list[str]:
    """argv for a child LEVIX process. Never uses a shell."""
    if is_frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", "levix", *args]


def run(*args: str) -> int:
    """Blocking exec of a subcommand. Returns its exit code."""
    import subprocess

    try:
        return subprocess.run(levix_argv(*args), check=False).returncode
    except OSError as exc:
        name = args[0] if args else "levix"
        sys.stderr.write(f"could not start {name}: {exc}\n")
        return 1

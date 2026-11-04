"""LEVIX - one CLI, multiple applications, unlimited extensibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["__version__"]

if TYPE_CHECKING:
    pass


def __getattr__(name: str) -> str:
    # Resolved lazily: importing importlib.metadata at module scope measurably
    # slows `levix --help`, and the version is only needed on demand.
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("levix")
        except PackageNotFoundError:  # source checkout without an installed dist
            return "0.0.0+unknown"
    msg = f"module 'levix' has no attribute {name!r}"
    raise AttributeError(msg)

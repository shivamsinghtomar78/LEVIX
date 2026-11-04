"""The dependency-injection object every command receives.

Passing one `LevixContext` through `ctx.obj` instead of using module-level globals is
what makes commands testable: a test builds a context over a tmp path and nothing
touches the real profile.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import capabilities, secrets
from .config import Config
from .paths import Paths
from .storage import Database
from .terminal import TerminalProfile


@dataclass(slots=True)
class LevixContext:
    paths: Paths
    config: Config
    database: Database
    profile: TerminalProfile
    logger: logging.Logger
    _probe_cache: dict[str, capabilities.ProbeResult] = field(default_factory=dict)

    def value(self, dotted: str) -> Any:
        return self.config.get(dotted)

    def probe(self, name: str) -> capabilities.ProbeResult:
        if name not in self._probe_cache:
            self._probe_cache[name] = capabilities.probe(name)
        return self._probe_cache[name]

    def secret(self, name: str) -> tuple[str | None, str]:
        value, source = secrets.get_secret(name, paths=self.paths)
        if value is None:
            self.logger.debug("secret %s not found (source=none)", name)
        else:
            self.logger.debug("secret %s resolved from %s", name, source)
        return value, source

    def store_secret(self, name: str, value: str) -> str:
        """Write a credential and return the store used. The value never reaches a log."""
        where = secrets.set_secret(name, value, paths=self.paths)
        self.logger.debug("secret %s stored in %s", name, where)
        return where

    def forget_secret(self, name: str) -> bool:
        removed = secrets.delete_secret(name, paths=self.paths)
        self.logger.debug("secret %s forgotten (removed=%s)", name, removed)
        return removed

    def glyph(self, key: str) -> str:
        from .terminal import glyphs

        return glyphs(self.profile)[key]

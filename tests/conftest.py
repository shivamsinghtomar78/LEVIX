"""Isolation shared by every test.

`LEVIX_HOME` is the single switch that keeps a test from touching the real profile:
config, database, secrets and logs all resolve underneath it. File logging is off by
default here because an open handle to the log file makes Windows fail to delete the
temporary directory afterwards.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import pytest

from levix import registry as registry_module
from levix.app import build_context
from levix.context import LevixContext
from levix.main import main as levix_main

_OVERRIDES = (
    "LEVIX_CONFIG_DIR",
    "LEVIX_DATA_DIR",
    "LEVIX_CACHE_DIR",
    "LEVIX_STATE_DIR",
    "LEVIX_LOG_DIR",
)


@pytest.fixture
def levix_home(tmp_path, monkeypatch) -> Path:
    for name in (*_OVERRIDES, *(k for k in os.environ if k.startswith("LEVIX_"))):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "levix-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LEVIX_HOME", str(home))
    monkeypatch.setenv("LEVIX_LOGGING_FILE_ENABLED", "false")
    monkeypatch.setenv("NO_COLOR", "1")
    return home


@pytest.fixture(autouse=True)
def _reset_registry():
    registry_module.use(None)
    yield
    registry_module.use(None)


@pytest.fixture
def context(levix_home) -> LevixContext:
    return build_context()


@pytest.fixture
def run_cli(levix_home) -> Callable[..., int]:
    """Invoke the real entry point, so exit codes and history are exercised too."""

    def go(*argv: str) -> int:
        return levix_main(list(argv))

    return go

"""Platform-appropriate filesystem locations.

`LEVIX_HOME` redirects every directory at once; the individual overrides exist so
tests can isolate one concern. Without these, unit tests would read and write the
real user profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import (
    user_cache_path,
    user_config_path,
    user_data_path,
    user_log_path,
    user_state_path,
)

APP_NAME = "levix"


@dataclass(frozen=True, slots=True)
class Paths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    state_dir: Path
    log_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def database(self) -> Path:
        return self.data_dir / "levix.db"

    @property
    def secrets_file(self) -> Path:
        return self.data_dir / "secrets.json"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "levix.log"

    def ensure(self) -> Paths:
        for directory in (
            self.config_dir,
            self.data_dir,
            self.cache_dir,
            self.state_dir,
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self


_ENV_HOME = "LEVIX_HOME"
_ENV_OVERRIDES = {
    "config_dir": "LEVIX_CONFIG_DIR",
    "data_dir": "LEVIX_DATA_DIR",
    "cache_dir": "LEVIX_CACHE_DIR",
    "state_dir": "LEVIX_STATE_DIR",
    "log_dir": "LEVIX_LOG_DIR",
}


def resolve_paths(app: str = APP_NAME) -> Paths:
    """Windows: %APPDATA%\\levix and %LOCALAPPDATA%\\levix\\Log. POSIX: ~/.config/levix."""
    home = os.environ.get(_ENV_HOME)
    base = Path(home).expanduser() if home else None

    defaults = {
        "config_dir": user_config_path(app, appauthor=False),
        "data_dir": user_data_path(app, appauthor=False),
        "cache_dir": user_cache_path(app, appauthor=False),
        "state_dir": user_state_path(app, appauthor=False),
        "log_dir": user_log_path(app, appauthor=False),
    }
    values: dict[str, Path] = {}
    for field, env in _ENV_OVERRIDES.items():
        override = os.environ.get(env)
        if override:
            values[field] = Path(override).expanduser()
        elif base is not None:
            values[field] = base / field.removesuffix("_dir")
        else:
            values[field] = Path(defaults[field])
    return Paths(**values)

"""Layered configuration: packaged defaults -> user file -> environment -> flags.

Reads use stdlib `tomllib`. Writes use `tomlkit`, because `tomllib` is read-only and
the naive alternative (serialise a plain dict) silently deletes every comment and
reorders the user's hand-edited file on the first `levix config set`.

Validation is a hand-maintained table rather than pydantic: pydantic pulls compiled
`pydantic-core`, which costs startup and complicates standalone builds, to validate
about thirty keys.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit

from .errors import ConfigError
from .paths import Paths

KIND = Literal["str", "int", "float", "bool"]
_SECRET_MARKERS = frozenset({"key", "token", "secret", "password", "credential"})


@dataclass(frozen=True, slots=True)
class Spec:
    kind: KIND
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None

    def coerce(self, raw: Any, where: str) -> Any:
        value: Any
        if self.kind == "bool":
            if isinstance(raw, bool):
                value = raw
            elif isinstance(raw, str) and raw.lower() in {"true", "false", "1", "0", "yes", "no"}:
                value = raw.lower() in {"true", "1", "yes"}
            else:
                msg = f"{where} must be a boolean, got {raw!r}"
                raise ConfigError(msg)
            return value
        if self.kind == "int":
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                msg = f"{where} must be an integer, got {raw!r}"
                raise ConfigError(msg)
            try:
                value = int(str(raw).strip())
            except ValueError as exc:
                msg = f"{where} must be an integer, got {raw!r}"
                raise ConfigError(msg) from exc
        elif self.kind == "float":
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                msg = f"{where} must be a number, got {raw!r}"
                raise ConfigError(msg)
            try:
                value = float(str(raw).strip())
            except ValueError as exc:
                msg = f"{where} must be a number, got {raw!r}"
                raise ConfigError(msg) from exc
        else:
            if not isinstance(raw, str):
                msg = f"{where} must be a string, got {raw!r}"
                raise ConfigError(msg)
            value = raw

        if self.minimum is not None and value < self.minimum:
            msg = f"{where} must be >= {self.minimum}, got {value}"
            raise ConfigError(msg)
        if self.maximum is not None and value > self.maximum:
            msg = f"{where} must be <= {self.maximum}, got {value}"
            raise ConfigError(msg)
        if self.choices is not None and value not in self.choices:
            msg = f"{where} must be one of {', '.join(self.choices)}, got {value!r}"
            raise ConfigError(msg)
        return value


SCHEMA: dict[str, dict[str, Spec]] = {
    "general": {
        "theme": Spec("str", choices=("default", "hacker", "minimal", "high-contrast")),
        # No `confirm_destructive` key on purpose: `approve.require_approval` gates every
        # destructive action unconditionally, and a setting that could switch that off
        # would make the guarantee optional - the same reason `--yes` is ignored there.
        "history_limit": Spec("int", minimum=0, maximum=10000),
    },
    "dashboard": {
        "recent_commands": Spec("int", minimum=0, maximum=200),
    },
    "monitor": {
        "interval_seconds": Spec("float", minimum=0.1, maximum=60),
        "process_limit": Spec("int", minimum=1, maximum=200),
    },
    "hacker": {
        "matrix_fps": Spec("int", minimum=1, maximum=120),
        "matrix_density": Spec("float", minimum=0.001, maximum=0.5),
    },
    "tube": {
        "output_dir": Spec("str"),
        "default_format": Spec("str", choices=("best", "video", "audio")),
    },
    "music": {
        "library_dir": Spec("str"),
        "volume": Spec("float", minimum=0.0, maximum=1.0),
    },
    "arcade": {"speed": Spec("float", minimum=0.25, maximum=4.0)},
    "ai": {
        "provider": Spec(
            "str",
            choices=("openai-compatible", "ollama"),
        ),
        "model": Spec("str"),
        "base_url": Spec("str"),
        "ollama_url": Spec("str"),
        "temperature": Spec("float", minimum=0.0, maximum=2.0),
        "max_tokens": Spec("int", minimum=1, maximum=32000),
        "require_approval": Spec("bool"),
    },
    "logging": {
        "level": Spec("str", choices=("debug", "info", "warning", "error")),
        "file_enabled": Spec("bool"),
    },
}

DEFAULTS_FILE = Path(__file__).parent / "data" / "defaults.toml"


def is_secret_key(dotted: str) -> bool:
    """Whether a configuration key names a credential rather than a setting.

    A key the schema declares as a number or a flag is never a credential, whatever it is
    called: `ai.max_tokens` is a count of tokens, and substring matching alone refused to
    write it while `LEVIX_AI_MAX_TOKENS` and a hand-edited `config.toml` were both
    accepted - the one command meant to set it was the only route that said no.
    """
    section, _, tail = dotted.rpartition(".")
    spec = SCHEMA.get(section, {}).get(tail)
    if spec is not None and spec.kind in {"int", "float", "bool"}:
        return False
    lowered = tail.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path} is not valid TOML: {exc}"
        raise ConfigError(msg) from exc
    except OSError as exc:
        msg = f"cannot read {path}: {exc}"
        raise ConfigError(msg) from exc


def _env_overrides() -> dict[str, dict[str, str]]:
    """LEVIX_AI_MODEL=gpt-4o -> {"ai": {"model": "gpt-4o"}}."""
    out: dict[str, dict[str, str]] = {}
    prefix = "LEVIX_"
    for name, value in os.environ.items():
        if not name.startswith(prefix) or name in {
            "LEVIX_HOME",
            "LEVIX_NO_COLOR",
            "LEVIX_API_KEY",
            "LEVIX_AI_API_KEY",
        }:
            continue
        parts = name[len(prefix) :].lower().split("_", 1)
        if len(parts) != 2 or parts[0] not in SCHEMA:
            continue
        section, key = parts
        if key in SCHEMA[section]:
            out.setdefault(section, {})[key] = value
    return out


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    dotted: str
    value: Any
    source: str  # default | user | env


class Config:
    def __init__(
        self, values: dict[str, dict[str, Any]], sources: dict[str, str], *, paths: Paths
    ) -> None:
        self._values = values
        self._sources = sources
        self.paths = paths

    @classmethod
    def load(cls, paths: Paths, *, create_user_file: bool = False) -> Config:
        defaults = _read_toml(DEFAULTS_FILE)
        merged: dict[str, dict[str, Any]] = {}
        sources: dict[str, str] = {}

        for section, specs in SCHEMA.items():
            merged[section] = {}
            for key, spec in specs.items():
                raw = defaults.get(section, {}).get(key)
                if raw is None:
                    msg = f"packaged defaults are missing {section}.{key}"
                    raise ConfigError(msg)
                merged[section][key] = spec.coerce(raw, f"defaults {section}.{key}")
                sources[f"{section}.{key}"] = "default"

        if paths.config_file.exists():
            user = _read_toml(paths.config_file)
            for section, table in user.items():
                if section not in SCHEMA:
                    msg = f"unknown configuration section [{section}] in {paths.config_file}"
                    raise ConfigError(msg)
                if not isinstance(table, dict):
                    msg = f"[{section}] must be a table in {paths.config_file}"
                    raise ConfigError(msg)
                for key, raw in table.items():
                    if key not in SCHEMA[section]:
                        msg = f"unknown configuration key {section}.{key} in {paths.config_file}"
                        raise ConfigError(msg)
                    where = f"{section}.{key} ({paths.config_file})"
                    merged[section][key] = SCHEMA[section][key].coerce(raw, where)
                    sources[f"{section}.{key}"] = "user"

        for section, overrides in _env_overrides().items():
            for key, raw in overrides.items():
                where = f"{section}.{key} (environment)"
                merged[section][key] = SCHEMA[section][key].coerce(raw, where)
                sources[f"{section}.{key}"] = "env"

        if create_user_file:
            paths.ensure()
        return cls(merged, sources, paths=paths)

    def get(self, dotted: str) -> Any:
        section, _, key = dotted.partition(".")
        try:
            return self._values[section][key]
        except KeyError:
            msg = f"unknown configuration key {dotted!r}"
            raise ConfigError(msg) from None

    def section(self, name: str) -> dict[str, Any]:
        if name not in self._values:
            msg = f"unknown configuration section {name!r}"
            raise ConfigError(msg)
        return dict(self._values[name])

    def source(self, dotted: str) -> str:
        return self._sources.get(dotted, "default")

    def resolved(self) -> list[ResolvedValue]:
        return [
            ResolvedValue(
                f"{section}.{key}", value, self._sources.get(f"{section}.{key}", "default")
            )
            for section, keys in self._values.items()
            for key, value in keys.items()
        ]

    def spec_for(self, dotted: str) -> Spec:
        section, _, key = dotted.partition(".")
        try:
            return SCHEMA[section][key]
        except KeyError:
            msg = f"unknown configuration key {dotted!r}"
            raise ConfigError(msg) from None


def read_user_document(paths: Paths) -> tomlkit.TOMLDocument:
    if not paths.config_file.exists():
        return tomlkit.document()
    return tomlkit.parse(paths.config_file.read_text(encoding="utf-8"))


def write_user_value(paths: Paths, dotted: str, raw: Any) -> Any:
    """Persist one override, preserving comments and ordering in the user's file."""
    section, _, key = dotted.partition(".")
    try:
        schema = SCHEMA[section][key]
    except KeyError:
        msg = f"unknown configuration key {dotted!r}"
        raise ConfigError(msg) from None
    value = schema.coerce(raw, dotted)

    paths.ensure()
    doc = read_user_document(paths)
    if section not in doc:
        doc.add(section, tomlkit.table())
    doc[section][key] = value
    paths.config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return value


def remove_user_value(paths: Paths, dotted: str) -> bool:
    section, _, key = dotted.partition(".")
    if not paths.config_file.exists():
        return False
    doc = read_user_document(paths)
    if section not in doc or key not in doc[section]:
        return False
    del doc[section][key]
    paths.config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return True

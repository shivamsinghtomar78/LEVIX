"""Module discovery and ownership stamping.

Two sources, one list:
  * `levix.plugins` entry points provided by the installed `levix` distribution
    (official modules) and by any other distribution (third-party plugins).
  * nothing else. There is no sys.path scanning and no drop-in folder import in this
    phase, because standard metadata entry points already answer "what is installed".

A manifest is pure data, so `entry_point.load()` costs almost nothing and never drags
in yt-dlp or psutil. The registry, not the plugin, sets `origin`: a third party cannot
claim to be official.
"""

from __future__ import annotations

import importlib
from dataclasses import replace
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any

from .module import ModuleManifest, Origin

if TYPE_CHECKING:
    # Typing only: the registry must not import a module CLI or Textual to answer a
    # question about manifests.
    import typer

GROUP = "levix.plugins"
OFFICIAL_DISTRIBUTION = "levix"


class ModuleRegistry:
    def __init__(self, *, extra_entry_points: tuple[EntryPoint, ...] = ()) -> None:
        self._extra = extra_entry_points
        self._cache: dict[str, ModuleManifest] | None = None

    def discover(self) -> dict[str, ModuleManifest]:
        if self._cache is not None:
            return self._cache

        found: dict[str, ModuleManifest] = {}
        for entry_point in self._entry_points():
            try:
                manifest = entry_point.load()
            except Exception as exc:
                # A broken plugin must not make LEVIX unstartable. The failure is
                # surfaced by `levix plugins list` and `levix doctor`.
                found[entry_point.name] = _broken(entry_point, exc)
                continue
            if not isinstance(manifest, ModuleManifest):
                found[entry_point.name] = _broken(
                    entry_point,
                    TypeError(
                        f"entry point returned {type(manifest).__name__}, not ModuleManifest"
                    ),
                )
                continue
            provider = ""
            try:
                provider = entry_point.dist.name if entry_point.dist else ""
            except Exception:
                provider = ""
            origin = _origin_for(provider, manifest.name)
            found[manifest.name or entry_point.name] = replace(
                manifest,
                origin=origin,
                provider=provider or manifest.provider,
                version=manifest.version or _dist_version(entry_point, origin),
            )

        self._cache = found
        return found

    def _entry_points(self) -> tuple[EntryPoint, ...]:
        return (*entry_points(group=GROUP), *self._extra)

    def get(self, name: str) -> ModuleManifest | None:
        manifests = self.discover()
        if name in manifests:
            return manifests[name]
        for manifest in manifests.values():
            for command in manifest.commands:
                if name in command.aliases:
                    return manifest
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.discover()))

    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self.discover()[name] for name in self.names())

    def build_cli(self, manifest: ModuleManifest) -> typer.Typer:
        """The single deferred-import site for module CLIs."""
        factory = _resolve(manifest.cli_path)
        return factory()


OFFICIAL_NAMES = frozenset({"monitor", "hacker", "files", "tube", "game", "music", "ai"})


def _origin_for(provider: str, name: str) -> Origin:
    """Only the `levix` distribution - or a synthetic test entry point naming an
    official module - counts as official. A third party cannot claim otherwise."""
    if provider == OFFICIAL_DISTRIBUTION:
        return Origin.OFFICIAL
    if provider == "" and name in OFFICIAL_NAMES:
        return Origin.OFFICIAL
    return Origin.THIRD_PARTY


def _resolve(dotted: str) -> Any:
    """Import "levix.modules.tube.cli:build_app"."""
    target, _, attribute = dotted.partition(":")
    module = importlib.import_module(target)
    obj = getattr(module, attribute) if attribute else module
    return obj


def _broken(entry_point: EntryPoint, exc: Exception) -> ModuleManifest:
    provider = getattr(entry_point.dist, "name", "") or ""
    return ModuleManifest(
        name=entry_point.name,
        title=entry_point.name.replace("-", " ").title(),
        summary=f"failed to load: {type(exc).__name__}: {exc}",
        cli_path="",
        origin=_origin_for(provider, entry_point.name),
        provider=provider,
    )


def _dist_version(entry_point: EntryPoint, origin: Origin) -> str:
    """Version shown by `levix plugins list`. Official modules ship with LEVIX, so
    their version is LEVIX's own; a plugin's version comes from its distribution."""
    if origin is Origin.OFFICIAL:
        from . import __version__

        return __version__
    try:
        return entry_point.dist.version if entry_point.dist else ""
    except Exception:
        return ""


def is_broken(manifest: ModuleManifest) -> bool:
    return not manifest.cli_path


# Click instantiates the group class itself, so a registry cannot be threaded through
# the constructor. This accessor is the one piece of process-level state in LEVIX: it
# caches discovered metadata (not user data) and `use()` lets tests inject a fake.
_ACTIVE: ModuleRegistry | None = None


def active() -> ModuleRegistry:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = ModuleRegistry()
    return _ACTIVE


def use(registry: ModuleRegistry | None) -> None:
    global _ACTIVE
    _ACTIVE = registry
    if registry is not None:
        registry.discover()

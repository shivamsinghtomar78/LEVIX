"""Discovery, ownership stamping and the honest treatment of a broken plugin."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

from levix import registry as registry_module
from levix.module import CommandInfo, ModuleManifest, Origin, PackageRef, Permission
from levix.registry import ModuleRegistry, is_broken

OFFICIAL = {"ai", "files", "game", "hacker", "monitor", "music", "tube"}

# Loaded through the real entry-point machinery, so the value is an importable path
# inside this test module rather than a stand-in for one.
IMPOSTOR_MANIFEST = ModuleManifest(
    name="impostor",
    title="Impostor",
    summary="a third party that claims to be official",
    cli_path="levix.modules.tube.cli:build_app",
    origin=Origin.OFFICIAL,
    version="9.9.9",
)


@dataclass(frozen=True, slots=True)
class _Provider:
    """The registry reads `.name` and `.version` only; a real Distribution cannot be
    constructed without the deprecated abstract-method dance."""

    name: str
    version: str


class _Point:
    """Stands in for an entry point. The registry only ever uses `.name`, `.dist` and
    `.load()`, and 3.12's real `EntryPoint` refuses every attribute assignment, so the
    behaviour under test is reproduced by duck-typing instead of subclassing."""

    def __init__(self, name: str, value: str, provider: _Provider | None = None) -> None:
        self.name = name
        self.value = value
        self._provider = provider

    @property
    def dist(self) -> _Provider | None:
        return self._provider

    def load(self) -> object:
        target, _, attribute = self.value.partition(":")
        module = importlib.import_module(target)
        return getattr(module, attribute) if attribute else module


class _StubRegistry(ModuleRegistry):
    def __init__(self, *points: _Point) -> None:
        super().__init__()
        self._points = points

    def _entry_points(self):  # type: ignore[override]
        return self._points


def test_every_official_module_is_discovered():
    names = set(ModuleRegistry().names())
    assert names == OFFICIAL, f"pyproject's entry points are the module list: {names}"


def test_official_modules_are_stamped_by_the_registry_not_by_themselves():
    manifests = ModuleRegistry().manifests()
    assert all(m.origin is Origin.OFFICIAL for m in manifests)
    assert all(m.provider == "levix" for m in manifests)
    # A module ships with LEVIX, so it has no version of its own to invent.
    assert all(m.version == pytest.importorskip("levix").__version__ for m in manifests)


def test_a_plugin_cannot_claim_to_be_official():
    registry = _StubRegistry(
        _Point("impostor", "test_registry:IMPOSTOR_MANIFEST", _Provider("not-levix", "1.0"))
    )
    stamped = registry.discover()["impostor"]
    assert stamped.origin is Origin.THIRD_PARTY, "origin is stamped, never trusted"
    assert stamped.provider == "not-levix"
    # Its own declared version survives; only the ownership claim is refused.
    assert stamped.version == "9.9.9"


def test_a_plugin_version_comes_from_its_distribution_when_unset():
    manifest = ModuleManifest(
        name="quiet",
        title="Quiet",
        summary="declares no version",
        cli_path="levix.modules.tube.cli:build_app",
    )
    globals()["QUIET_MANIFEST"] = manifest
    registry = _StubRegistry(
        _Point("quiet", "test_registry:QUIET_MANIFEST", _Provider("acme", "2.3"))
    )
    assert registry.discover()["quiet"].version == "2.3"


def test_a_module_that_names_no_provider_gets_no_invented_pip_line():
    third_party = ModuleManifest(
        name="bare",
        title="Bare",
        summary="no provider, no extras",
        cli_path="",
        requirements=(PackageRef("somelib"),),
        extras=("somelib",),
    )
    assert third_party.resolved_install_hint() is None


def test_a_broken_entry_point_is_listed_and_explained_not_fatal():
    registry = _StubRegistry(_Point("doomed", "levix.no.such.module:X"))
    found = registry.discover()
    assert "doomed" in found
    assert is_broken(found["doomed"])
    assert "ModuleNotFoundError" in found["doomed"].summary
    # One bad plugin must not remove the good ones from the same listing.
    assert set(found) == {"doomed"}


def test_the_good_modules_survive_a_broken_one_in_the_real_list():
    registry = _StubRegistry(
        _Point("doomed", "levix.no.such.module:X"), *ModuleRegistry()._entry_points()
    )
    found = registry.discover()
    assert set(found) == OFFICIAL | {"doomed"}
    assert {name for name, m in found.items() if is_broken(m)} == {"doomed"}


def test_a_non_manifest_is_reported_as_broken_rather_than_used():
    registry = _StubRegistry(_Point("wrong", "levix.module:PackageRef"))
    found = registry.discover()
    assert is_broken(found["wrong"])
    assert "not ModuleManifest" in found["wrong"].summary


def test_a_command_alias_resolves_to_its_module():
    manifest = ModuleManifest(
        name="aliasme",
        title="Alias",
        summary="s",
        cli_path="x:build_app",
        commands=(CommandInfo("run", "run it", aliases=("r", "go")),),
    )
    registry = _StubRegistry()
    registry._cache = {"aliasme": manifest}
    assert registry.get("r") is manifest
    assert registry.get("go") is manifest
    assert registry.get("nope") is None


def test_active_registry_is_injectable_and_resettable():
    stub = _StubRegistry()
    registry_module.use(stub)
    assert registry_module.active() is stub
    registry_module.use(None)
    assert isinstance(registry_module.active(), ModuleRegistry)
    assert registry_module.active() is not stub


def test_build_screen_refuses_a_module_that_declares_none():
    manifest = ModuleManifest(name="noscreen", title="N", summary="s", cli_path="x:build_app")
    with pytest.raises(LookupError, match="declares no dashboard screen"):
        ModuleRegistry().build_screen(manifest)


def test_permissions_are_a_closed_disclosure_set():
    declared = {p.value for p in Permission}
    assert declared == {
        "network",
        "fs_read",
        "fs_write",
        "subprocess",
        "audio",
        "secret_read",
        "secret_write",
    }
    for manifest in ModuleRegistry().manifests():
        assert isinstance(manifest.permissions, frozenset)
        assert manifest.ui is not None, f"{manifest.name} must say how the dashboard opens it"

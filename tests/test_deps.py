"""The single oracle for "is this installed?" and the exit-3 gate it drives."""

from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from levix import deps
from levix.deps import Availability, PackageStatus, check, ensure_dependencies, missing, resolve
from levix.errors import EXIT_MISSING_DEPENDENCY, DependencyError
from levix.module import ModuleManifest, Origin, PackageRef

ABSENT = "levix_test_package_that_does_not_exist"


def manifest(**overrides) -> ModuleManifest:
    base = {
        "name": "demo",
        "title": "Demo",
        "summary": "for the gate",
        "cli_path": "x:build_app",
        "requirements": (PackageRef(ABSENT, ABSENT),),
    }
    base.update(overrides)
    return ModuleManifest(**base)


def test_an_installed_core_package_reports_its_version():
    status = check(PackageRef("rich", "rich"))
    assert status.availability is Availability.INSTALLED
    assert status.installed_version
    assert status.satisfied


def test_an_absent_package_is_missing_and_not_satisfied():
    status = check(PackageRef(ABSENT, ABSENT))
    assert status.availability is Availability.MISSING
    assert not status.satisfied
    assert status.describe == f"{ABSENT} is not installed"


def test_an_import_name_is_mapped_to_its_distribution_name():
    # yt_dlp is the import name and yt-dlp the distribution; a hint built from the wrong
    # one is a pip command that fails, which is the whole reason PackageRef has two fields.
    assert deps._dist_for("yt_dlp") == "yt-dlp"
    assert PackageRef("yt_dlp").distribution == "yt_dlp"
    assert PackageRef("yt_dlp", "yt-dlp").distribution == "yt-dlp"


def test_a_version_below_the_pin_is_reported_not_masked(monkeypatch):
    monkeypatch.setattr(deps, "distribution", lambda name: _Meta("0.1.0"))
    monkeypatch.setattr(deps, "_dist_for", lambda name: "rich")
    status = check(PackageRef("rich", minimum="999.0"))
    assert status.availability is Availability.TOO_OLD
    assert "older than the required 999.0" in status.describe


def test_an_importable_package_without_metadata_is_uncertain_but_allowed(monkeypatch):
    def not_found(name):
        raise deps.PackageNotFoundError(name)

    monkeypatch.setattr(deps, "distribution", not_found)
    monkeypatch.setattr(deps, "_dist_for", lambda name: "not-a-real-dist")
    status = check(PackageRef("rich"))
    assert status.availability is Availability.UNCERTAIN
    assert status.satisfied, "a vendored or source-tree install must not block the command"
    assert "version unknown" in status.describe


@pytest.mark.parametrize(
    ("have", "want", "satisfied"),
    [("7.2", "7.2", True), ("7.3.1", "7.2", True), ("7.1.9", "7.2", False), ("8", "7.2", True)],
)
def test_version_comparison_covers_only_the_pins_we_use(have, want, satisfied):
    status = PackageStatus(
        PackageRef("rich", "rich", minimum=want),
        Availability.INSTALLED if satisfied else Availability.TOO_OLD,
        have,
    )
    assert status.satisfied is satisfied
    assert (deps._version_tuple(have) >= deps._version_tuple(want)) is satisfied


def test_an_unparseable_installed_version_is_uncertain_not_accepted_silently(monkeypatch):
    monkeypatch.setattr(deps, "distribution", lambda name: _Meta("nightly"))
    status = check(PackageRef("rich", "rich", minimum="7"))
    assert status.availability is Availability.UNCERTAIN
    assert status.installed_version == "nightly"


def test_resolve_and_missing_agree_with_check():
    refs = (PackageRef("rich", "rich"), PackageRef(ABSENT, ABSENT))
    statuses = resolve(refs)
    assert [s.availability for s in statuses] == [Availability.INSTALLED, Availability.MISSING]
    assert [s.ref.import_name for s in missing(refs)] == [ABSENT]


def test_the_gate_raises_with_the_exact_install_line_for_an_official_module():
    official = manifest(origin=Origin.OFFICIAL, provider="levix", extras=("tube",))
    with pytest.raises(DependencyError) as caught:
        ensure_dependencies(official)
    assert caught.value.exit_code == EXIT_MISSING_DEPENDENCY
    assert 'pip install "levix[tube]"' in caught.value.message
    assert caught.value.hint == 'pip install "levix[tube]"'


def test_the_gate_refuses_to_invent_a_pip_line_for_a_provider_less_plugin():
    with pytest.raises(DependencyError) as caught:
        ensure_dependencies(manifest(extras=("thing",)))
    assert "no install hint is declared" in caught.value.message
    assert "pip install" not in caught.value.message


def test_a_module_with_every_requirement_satisfied_passes_the_gate():
    ok = manifest(requirements=(PackageRef("rich", "rich"),))
    ensure_dependencies(ok)


def test_a_multi_extra_hint_names_one_distribution_not_several():
    official = manifest(origin=Origin.OFFICIAL, extras=("ai", "secrets"))
    with pytest.raises(DependencyError) as caught:
        ensure_dependencies(official)
    assert caught.value.hint == 'pip install "levix[ai+secrets]"'


def test_no_availability_check_imports_the_module_it_probes():
    # find_spec does not execute the module. If that ever changed, the gate would drag
    # yt-dlp and psutil into `levix --help` through the very call meant to keep them out.
    before = set(sys.modules)
    check(PackageRef("yt_dlp", "yt-dlp"))
    check(PackageRef("psutil"))
    loaded = {name for name in ("yt_dlp", "psutil") if name in set(sys.modules) - before}
    assert loaded == set()


class _Meta:
    def __init__(self, version: str) -> None:
        self.version = version


def test_package_status_describe_for_installed_reads_distribution_not_import_name():
    status = PackageStatus(PackageRef("yt_dlp", "yt-dlp"), Availability.INSTALLED, "2026.10.26")
    assert status.describe == "yt-dlp 2026.10.26"


def test_the_gate_reads_the_stamped_manifest_not_the_modules_own_copy(monkeypatch):
    """`deps.gate` is what a module's Typer callback calls.

    The module's `MANIFEST` is the un-stamped original: `origin` is `THIRD_PARTY` and
    `provider` is empty, so `resolved_install_hint()` returns None and the user was told
    "no install hint is declared for this module" instead of the pip line that would fix it.
    """
    from dataclasses import replace

    from levix import registry as registry_module

    local = manifest(extras=("music",))
    stamped = replace(local, origin=Origin.OFFICIAL, provider="levix")
    stub = registry_module.ModuleRegistry()
    stub._cache = {"demo": stamped}
    monkeypatch.setattr(registry_module, "_ACTIVE", stub)

    with pytest.raises(DependencyError) as caught:
        deps.gate(local)
    assert caught.value.hint == 'pip install "levix[music]"'
    assert 'install it with: pip install "levix[music]"' in str(caught.value)


def test_the_gate_falls_back_to_the_local_copy_when_nothing_is_registered(monkeypatch):
    # A module CLI exercised on its own, with no registry in front of it, must still refuse
    # to run rather than silently pass.
    from levix import registry as registry_module

    monkeypatch.setattr(registry_module, "_ACTIVE", None)
    with pytest.raises(DependencyError) as caught:
        deps.gate(manifest(extras=("music",)))
    assert "no install hint is declared" in str(caught.value)


def test_a_two_line_refusal_stays_two_lines_on_the_screen():
    """`main._plain()` escapes per line, which is what keeps this readable.

    The gate message is authored with a line break so the pip command starts its own line.
    `encode_safe` rewrites control characters as `\x0a` - right for a status bar, wrong for
    a report - so the error printer splits first. Without that the user reads a literal
    backslash-x-0-a where the remedy should begin.
    """
    from levix.main import _plain

    with pytest.raises(DependencyError) as caught:
        ensure_dependencies(
            replace(manifest(extras=("music",)), origin=Origin.OFFICIAL, provider="levix")
        )
    rendered = _plain(caught.value.message)
    assert "\n" in rendered
    assert "\\x0a" not in rendered
    assert rendered.splitlines()[-1].lstrip().startswith("install it with:")

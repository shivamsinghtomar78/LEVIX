"""The single oracle for "is this installed?".

The gate, `levix doctor` and the dashboard badges are all views of `resolve()`.
Nothing elsewhere may write `try: import x except ImportError` for availability,
because that imports heavy modules just to decide whether to import them.

Version comparison is intentionally tiny: pulling in `packaging` to check "at least
7.2" against a handful of pins is not worth a permanent core dependency. `_version_tuple`
handles the PEP 440 numeric prefixes we actually pin against and is honest about the
rest (an unparseable installed version is reported, not silently accepted).
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, distribution, packages_distributions

from .errors import DependencyError
from .module import ModuleManifest, PackageRef


class Availability(StrEnum):
    INSTALLED = "installed"
    MISSING = "missing"
    TOO_OLD = "too_old"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class PackageStatus:
    ref: PackageRef
    availability: Availability
    installed_version: str | None = None
    provider_dist: str | None = None

    @property
    def satisfied(self) -> bool:
        return self.availability in (Availability.INSTALLED, Availability.UNCERTAIN)

    @property
    def describe(self) -> str:
        if self.availability is Availability.MISSING:
            return f"{self.ref.distribution} is not installed"
        if self.availability is Availability.TOO_OLD:
            return (
                f"{self.ref.distribution} {self.installed_version} is older than the "
                f"required {self.ref.minimum}"
            )
        if self.availability is Availability.UNCERTAIN:
            return f"{self.ref.distribution} importable but version unknown"
        return f"{self.ref.distribution} {self.installed_version}"


_VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _version_tuple(text: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) if part else 0 for part in match.groups())


def _dist_for(import_name: str) -> str | None:
    """Map an import name to its distribution name, e.g. yt_dlp -> yt-dlp."""
    try:
        found = packages_distributions().get(import_name)
    except Exception:
        return None
    return found[0] if found else None


def check(ref: PackageRef) -> PackageStatus:
    spec = None
    try:
        spec = importlib.util.find_spec(ref.import_name)
    except (ImportError, ValueError):
        spec = None

    dist_name = ref.distribution if ref.dist_name else _dist_for(ref.import_name)
    version: str | None = None
    if dist_name is not None:
        try:
            version = distribution(dist_name).version
        except PackageNotFoundError:
            dist_name = None

    if spec is None:
        return PackageStatus(ref, Availability.MISSING, provider_dist=dist_name)

    if ref.minimum is None:
        return PackageStatus(
            ref,
            Availability.INSTALLED if version else Availability.UNCERTAIN,
            installed_version=version,
            provider_dist=dist_name,
        )

    have = _version_tuple(version or "")
    if have is None:
        return PackageStatus(
            ref, Availability.UNCERTAIN, installed_version=version, provider_dist=dist_name
        )
    want = _version_tuple(ref.minimum) or (0,)
    availability = Availability.INSTALLED if have >= want else Availability.TOO_OLD
    return PackageStatus(ref, availability, installed_version=version, provider_dist=dist_name)


def resolve(refs: tuple[PackageRef, ...]) -> tuple[PackageStatus, ...]:
    return tuple(check(ref) for ref in refs)


def missing(refs: tuple[PackageRef, ...]) -> tuple[PackageStatus, ...]:
    return tuple(status for status in resolve(refs) if not status.satisfied)


def ensure_dependencies(manifest: ModuleManifest) -> None:
    """Called from every module's Typer callback. Raises -> exit 3."""
    unsatisfied = missing(manifest.requirements)
    if not unsatisfied:
        return
    detail = "; ".join(status.describe for status in unsatisfied)
    hint = manifest.resolved_install_hint()
    message = f"module {manifest.name!r} needs {detail}"
    if hint:
        message += f"\n  install it with: {hint}"
    else:
        message += "\n  no install hint is declared for this module"
    raise DependencyError(message, hint=hint)


def gate(manifest: ModuleManifest) -> None:
    """The module-side entry to the gate, against the registry's stamped manifest.

    A module's own `MANIFEST` is the un-stamped original. `registry.discover` copies it
    with `dataclasses.replace` to add `origin`, `provider` and `version`, and
    `resolved_install_hint()` needs `origin` to know that `extras=("music",)` means
    `pip install "levix[music]"` rather than a third-party distribution nobody can name.
    Guarding with the local copy made every official module answer "no install hint is
    declared for this module" - technically true, useless to the person reading it.
    """
    from .registry import active

    ensure_dependencies(active().get(manifest.name) or manifest)

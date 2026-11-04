"""`levix doctor` reporting.

One place decides what "healthy" means, so the dashboard, the command and any future
GUI all show the same verdict. Statuses are honest: `UNSUPPORTED` is shown when the
platform cannot provide a thing, rather than reporting a fabricated success.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import capabilities, secrets
from .capabilities import Status
from .context import LevixContext
from .deps import resolve
from .errors import EXIT_MISSING_DEPENDENCY, EXIT_OK
from .registry import ModuleRegistry, is_broken


@dataclass(frozen=True, slots=True)
class Finding:
    area: str
    status: Status
    detail: str
    hint: str | None = None

    @property
    def worst(self) -> int:
        return {
            Status.OK: 0,
            Status.UNSUPPORTED: 1,
            Status.DEGRADED: 2,
            Status.MISSING: 3,
        }[self.status]


def environment(ctx: LevixContext) -> list[Finding]:
    findings = [
        Finding("paths", Status.OK, f"config {ctx.paths.config_dir}"),
        Finding(
            "config",
            Status.OK if ctx.paths.config_file.exists() else Status.DEGRADED,
            "user file present"
            if ctx.paths.config_file.exists()
            else f"no user config yet; running on packaged defaults ({ctx.paths.config_file})",
        ),
    ]
    findings.append(_storage_finding(ctx))
    backend_id, detail = secrets.backend(ctx.paths)
    findings.append(
        Finding(
            "secrets",
            Status.OK if backend_id == "keyring" else Status.DEGRADED,
            detail,
            hint=None if backend_id == "keyring" else 'pip install "levix[secrets]"',
        )
    )
    return findings


def _storage_finding(ctx: LevixContext) -> Finding:
    try:
        applied = ctx.database.apply_migrations(("core",))
    except Exception as exc:
        return Finding("storage", Status.MISSING, f"database unusable: {exc}")
    detail = f"{ctx.paths.database} (migrations applied: {', '.join(applied) or 'none needed'})"
    return Finding("storage", Status.OK, detail)


def modules(registry: ModuleRegistry) -> list[Finding]:
    findings: list[Finding] = []
    for manifest in registry.manifests():
        if is_broken(manifest):
            findings.append(Finding(f"module:{manifest.name}", Status.MISSING, manifest.summary))
            continue
        statuses = resolve(manifest.requirements)
        if not statuses:
            findings.append(
                Finding(f"module:{manifest.name}", Status.OK, "no optional dependencies")
            )
            continue
        unsatisfied = [status for status in statuses if not status.satisfied]
        findings.append(
            Finding(
                f"module:{manifest.name}",
                Status.MISSING if unsatisfied else Status.OK,
                "; ".join(status.describe for status in statuses),
                hint=manifest.resolved_install_hint() if unsatisfied else None,
            )
        )
    return findings


def capabilities_report(ctx: LevixContext) -> list[Finding]:
    return [
        Finding(f"capability:{result.name}", result.status, result.detail, result.hint)
        for result in capabilities.report()
    ]


def build_report(ctx: LevixContext, registry: ModuleRegistry) -> list[Finding]:
    return environment(ctx) + modules(registry) + capabilities_report(ctx)


def worst_status(findings: list[Finding]) -> Status:
    ranking = {
        Status.OK: 0,
        Status.UNSUPPORTED: 1,
        Status.DEGRADED: 2,
        Status.MISSING: 3,
    }
    worst = max((ranking[f.status] for f in findings), default=0)
    return next(status for status, value in ranking.items() if value == worst)


def exit_code_for(findings: list[Finding]) -> int:
    """MISSING dependencies are a hard problem; DEGRADED and UNSUPPORTED are not."""
    blocking = [
        finding
        for finding in findings
        if finding.status is Status.MISSING and finding.area.startswith("module:")
    ]
    return EXIT_MISSING_DEPENDENCY if blocking else EXIT_OK

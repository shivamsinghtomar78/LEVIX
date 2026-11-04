"""`levix doctor`."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from .. import doctor as doctor_core
from ..capabilities import Status
from ..context import LevixContext
from ..errors import ConfigError
from ..registry import active

console = Console()
console_err = Console(stderr=True)

_STYLE = {
    Status.OK: "green",
    Status.DEGRADED: "yellow",
    Status.MISSING: "red",
    Status.UNSUPPORTED: "cyan",
}


def doctor_command(
    typer_ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    only: str = typer.Option("", "--only", help="Restrict to an area: modules, capabilities, env."),
    vacuum: bool = typer.Option(False, "--vacuum", help="Compact the shared database."),
) -> None:
    """Report what is installed, what works and what is honestly unsupported."""
    context = _ctx(typer_ctx)
    if vacuum:
        context.database.vacuum()
        console.print(f"[green]vacuumed[/green] {context.paths.database}")

    findings = doctor_core.build_report(context, active())
    if only:
        prefix = {
            "modules": "module:",
            "capabilities": "capability:",
            "env": "",
        }.get(only)
        if prefix is None:
            msg = f"--only must be modules, capabilities or env, not {only!r}"
            raise ConfigError(msg)
        if only == "env":
            findings = doctor_core.environment(context)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "verdict": doctor_core.worst_status(findings).value,
                    "findings": [
                        {
                            "area": f.area,
                            "status": f.status.value,
                            "detail": f.detail,
                            "hint": f.hint,
                        }
                        for f in findings
                    ],
                },
                indent=2,
            )
        )
        raise typer.Exit(code=doctor_core.exit_code_for(findings))

    table = Table(title="LEVIX doctor", header_style="bold cyan")
    table.add_column("area", style="bold")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    table.add_column("what to do", overflow="fold")
    for finding in findings:
        table.add_row(
            finding.area,
            f"[{_STYLE[finding.status]}]{finding.status.value}[/]",
            finding.detail,
            finding.hint or "",
        )
    console.print(table)

    verdict = doctor_core.worst_status(findings)
    console.print(
        f"verdict: [{_STYLE[verdict]}]{verdict.value}[/] "
        f"({sum(f.status is Status.OK for f in findings)} ok, "
        f"{sum(f.status is not Status.OK for f in findings)} not ok)"
    )
    raise typer.Exit(code=doctor_core.exit_code_for(findings))


def _ctx(typer_ctx: typer.Context) -> LevixContext:
    if not isinstance(typer_ctx.obj, LevixContext):
        msg = "context was not initialised"
        raise ConfigError(msg)
    return typer_ctx.obj

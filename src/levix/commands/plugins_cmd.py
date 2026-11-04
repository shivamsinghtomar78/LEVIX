"""`levix plugins` - list and inspect what is registered.

Discovery is entry-point based, so what this reports is exactly what the Python
environment provides. Installation and removal are deliberately NOT implemented here:
third-party Python code executes with LEVIX's full privileges, and the consent flow
plus the pipx/frozen-environment questions need to be settled before a command that
installs arbitrary code can honestly exist. See docs/plugins/PLUGIN_INSTALLATION.md.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..context import LevixContext
from ..deps import resolve
from ..errors import ConfigError
from ..registry import active, is_broken

console = Console()
plugins_app = typer.Typer(help="Inspect installed modules and plugins.", no_args_is_help=True)


@plugins_app.command("list")
def list_plugins(
    typer_ctx: typer.Context,
    origin: str = typer.Option("all", "--origin", help="all, official or third-party"),
) -> None:
    """Table of every registered module and whether it can run."""
    _ctx(typer_ctx)
    manifests = active().manifests()
    table = Table(title="LEVIX modules", header_style="bold cyan")
    table.add_column("name", style="bold")
    table.add_column("origin")
    table.add_column("version")
    table.add_column("commands")
    table.add_column("state")
    for manifest in manifests:
        if origin != "all":
            wanted = origin.replace("-", "_")
            if manifest.origin.value != wanted:
                continue
        state = "broken" if is_broken(manifest) else _availability(manifest.requirements)
        table.add_row(
            manifest.name,
            manifest.origin.value,
            manifest.version or "-",
            ", ".join(manifest.command_names()) or "-",
            state,
        )
    if not table.rows:
        console.print("[dim]no modules match.[/dim]")
        return
    console.print(table)


@plugins_app.command("info")
def info(typer_ctx: typer.Context, name: str) -> None:
    """Everything known about one module: deps, capabilities, permissions, docs."""
    from ..module import Origin

    _ctx(typer_ctx)
    manifest = active().get(name)
    if manifest is None:
        console.print(f"[red]no module named {name!r}.[/red] Try `levix plugins list`.")
        raise typer.Exit(code=4)

    console.print(f"[bold]{manifest.title}[/bold] ({manifest.name})")
    console.print(f"  summary    : {manifest.summary}")
    console.print(f"  origin     : {manifest.origin.value}")
    console.print(f"  provider   : {manifest.provider or '-'}")
    console.print(f"  version    : {manifest.version or '-'}")
    console.print(f"  cli entry  : {manifest.cli_path or '(unavailable)'}")
    console.print(f"  commands   : {', '.join(manifest.command_names()) or '-'}")
    console.print(f"  dashboard  : {manifest.ui.mode if manifest.ui else 'not offered'}")
    console.print(f"  docs       : {manifest.documentation or '-'}")
    if manifest.permissions:
        console.print(f"  permissions: {', '.join(sorted(p.value for p in manifest.permissions))}")
        if manifest.origin is Origin.THIRD_PARTY:
            console.print(
                "  [yellow]note: declared permissions are a promise by the author, not an "
                "enforced limit. Python plugins can do anything LEVIX can.[/yellow]"
            )
    statuses = resolve(manifest.requirements)
    if statuses:
        console.print("  requires   :")
        for status in statuses:
            mark = "[green]+[/green]" if status.satisfied else "[red]-[/red]"
            console.print(f"    {mark} {status.describe}")
        hint = manifest.resolved_install_hint()
        if hint and not all(status.satisfied for status in statuses):
            console.print(f"  install    : {hint}")
    else:
        console.print("  requires   : nothing beyond the LEVIX core")


def _availability(requirements) -> str:
    if not requirements:
        return "ready"
    statuses = resolve(requirements)
    missing = [status for status in statuses if not status.satisfied]
    if missing:
        return "needs " + ", ".join(status.ref.distribution for status in missing)
    return "ready"


def _ctx(typer_ctx: typer.Context) -> LevixContext:
    if not isinstance(typer_ctx.obj, LevixContext):
        msg = "context was not initialised"
        raise ConfigError(msg)
    return typer_ctx.obj

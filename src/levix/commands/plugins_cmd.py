"""`levix plugins` - list and inspect what is registered.

Discovery is entry-point based, so what this reports is exactly what the Python
environment provides. Installation and removal are deliberately NOT implemented here:
third-party Python code executes with LEVIX's full privileges, and the consent flow
plus the pipx/frozen-environment questions need to be settled before a command that
installs arbitrary code can honestly exist. See
docs/architecture/PLUGIN_ARCHITECTURE.md and docs/roadmap/CURRENT_STATUS.md.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..context import LevixContext
from ..deps import resolve
from ..errors import ConfigError
from ..module import PackageRef
from ..registry import active, is_broken
from ..terminal import markup_safe

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
        # Every one of these cells is text a plugin wrote. A manifest whose name or version
        # contains `[red]` would otherwise restyle this table, and brackets would vanish.
        table.add_row(
            markup_safe(manifest.name),
            markup_safe(manifest.origin.value),
            markup_safe(manifest.version or "-"),
            markup_safe(", ".join(manifest.command_names()) or "-"),
            markup_safe(state),
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
        wanted = markup_safe(repr(name))
        console.print(f"[red]no module named {wanted}.[/red] Try `levix plugins list`.")
        raise typer.Exit(code=4)

    console.print(f"[bold]{markup_safe(manifest.title)}[/bold] ({markup_safe(manifest.name)})")
    console.print(f"  summary    : {markup_safe(manifest.summary)}")
    console.print(f"  origin     : {manifest.origin.value}")
    console.print(f"  provider   : {markup_safe(manifest.provider or '-')}")
    console.print(f"  version    : {markup_safe(manifest.version or '-')}")
    console.print(f"  cli entry  : {markup_safe(manifest.cli_path or '(unavailable)')}")
    console.print(f"  commands   : {markup_safe(', '.join(manifest.command_names()) or '-')}")
    # A manifest with no `UiSpec` is not hidden: the dashboard offers it with the default
    # mode and no argv, so saying "not offered" here would describe the opposite.
    console.print(
        f"  dashboard  : {manifest.ui.mode if manifest.ui else 'suspend (no UiSpec declared)'}"
    )
    console.print(f"  docs       : {markup_safe(manifest.documentation or '-')}")
    if manifest.permissions:
        granted = ", ".join(sorted(p.value for p in manifest.permissions))
        console.print(f"  permissions: {markup_safe(granted)}")
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
            console.print(f"    {mark} {markup_safe(status.describe)}")
        hint = manifest.resolved_install_hint()
        if hint and not all(status.satisfied for status in statuses):
            # The hint is `pip install "levix[tube]"`: unescaped, Rich reads the extra as a
            # style tag and prints an install line that installs nothing.
            console.print(f"  install    : {markup_safe(hint)}")
    else:
        console.print("  requires   : nothing beyond the LEVIX core")


def _availability(requirements: tuple[PackageRef, ...]) -> str:
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

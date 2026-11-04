"""The command surface, imported only when `levix hello ...` actually runs.

Two things worth copying from this file: every command reads its environment off
`ctx.obj` (the same `LevixContext` the core built, so configuration, paths and the
database are the user's, not a second set invented by the plugin), and nothing here is
imported until a command is invoked, which is what keeps `levix --help` cheap.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from levix.sdk import LevixContext

app = typer.Typer(
    name="hello",
    help="Example LEVIX plugin: greet, then show what the host session looks like.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console(highlight=False)


def build_app() -> typer.Typer:
    """The factory the registry calls through `cli_path`."""
    return app


def _context(ctx: typer.Context) -> LevixContext:
    """The core context, or a clear refusal.

    `levix hello` always arrives through the router, which forwards the context it built.
    Running this Typer app on its own - a plugin author's debugger, say - has none, and
    silently reading defaults there would hide the wiring this example is meant to show.
    """
    obj = ctx.obj
    if not isinstance(obj, LevixContext):
        msg = "this command must run as `levix hello ...`, which builds the LEVIX context"
        raise typer.BadParameter(msg)
    return obj


@app.command()
def greet(
    ctx: typer.Context,
    name: str = typer.Argument("world", help="Who to greet."),
    times: int = typer.Option(1, "--times", min=1, max=5, help="Repeat the line N times."),
) -> None:
    obj = _context(ctx)
    arrow = obj.glyph("arrow")
    # Rich reads the `[...]` inside anything a human typed as a style tag and deletes it,
    # so the value is escaped before it reaches markup. The same rule applies to every
    # name, path or title a module prints.
    who = escape(name)
    theme = escape(str(obj.value("general.theme")))
    for _ in range(times):
        console.print(f"[green]hello,[/green] {who}  [dim]{arrow} theme={theme}[/dim]")


@app.command()
def where(ctx: typer.Context) -> None:
    """Report the resolved profile directories and this module's own history."""
    obj = _context(ctx)
    paths = obj.paths
    table = Table(title="Hello / where", header_style="bold cyan", show_header=False)
    table.add_column("directory", style="bold")
    table.add_column("path", overflow="fold")
    table.add_row("config", str(paths.config_dir))
    table.add_row("data", str(paths.data_dir))
    table.add_row("cache", str(paths.cache_dir))
    table.add_row("state", str(paths.state_dir))
    table.add_row("log", str(paths.log_dir))
    console.print(table)

    limit = int(obj.value("general.history_limit"))
    rows = [row for row in obj.database.recent_commands(max(limit, 1)) if row["module"] == "hello"]
    if not rows:
        console.print("[dim]no `levix hello` run in the shared history yet[/dim]")
        return
    console.print(f"[dim]your last {len(rows)} hello run(s), newest first:[/dim]")
    for row in rows[:5]:
        console.print(
            f"  [cyan]{row['ts']}[/cyan]  levix {row['argv']} "
            f"[dim]exit {row['exit_code']} in {row['duration_ms']:.0f} ms[/dim]"
        )

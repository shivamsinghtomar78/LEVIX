"""`levix dashboard` and bare `levix`.

Textual needs a real terminal. When stdout is redirected - a pipe, a capture, CI -
this explains the situation and exits with the usage code instead of letting Textual
emit escape sequences into someone's data.
"""

from __future__ import annotations

import sys

import typer

from ..context import LevixContext
from ..errors import EXIT_USAGE, ConfigError
from ..terminal import new_console

console = new_console()


def dashboard_command(typer_ctx: typer.Context) -> None:
    """Launch the interactive dashboard."""
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        console.print(
            "[yellow]The dashboard needs an interactive terminal.[/yellow]\n"
            "stdout or stdin is redirected, so Textual has nothing to draw on.\n"
            "Run `levix` from a terminal, or use a direct command such as "
            "[bold]levix monitor cpu[/bold]. `levix --help` lists them."
        )
        raise typer.Exit(code=EXIT_USAGE)

    context = _ctx(typer_ctx)
    from ..dashboard.app import LevixDashboard

    # Import is inside the function: `levix tube ...` must not pay for Textual.
    LevixDashboard(context).run()


def _ctx(typer_ctx: typer.Context) -> LevixContext:
    if not isinstance(typer_ctx.obj, LevixContext):
        msg = "context was not initialised"
        raise ConfigError(msg)
    return typer_ctx.obj

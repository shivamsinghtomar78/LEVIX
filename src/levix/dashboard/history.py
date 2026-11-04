"""Recent commands, read from the same table `levix` writes to on every exit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..terminal import markup_safe

if TYPE_CHECKING:
    from ..storage import Database

#: `general.history_limit` is what `levix` keeps; this is only how many rows the panel shows.
DEFAULT_SHOWN = 10

COLOUR = {
    0: "green",
    2: "yellow",
    3: "yellow",
    4: "yellow",
    5: "yellow",
    6: "yellow",
    130: "yellow",
}


def recent_lines(database: Database, *, limit: int = DEFAULT_SHOWN) -> list[str]:
    """Newest first, one markup line each. An empty or unreadable log says so."""
    try:
        database.apply_migrations(("core",))
        rows = database.recent_commands(limit=limit)
    except OSError:
        return ["[dim]history is not readable yet[/dim]"]
    if not rows:
        return ["[dim]no commands recorded yet[/dim]"]
    lines: list[str] = []
    for row in rows:
        code = int(row["exit_code"])
        colour = COLOUR.get(code, "red")
        stamp = str(row["ts"])[11:16]
        # argv is what the user typed. A line containing `[bold]` would otherwise style the
        # rest of the panel instead of showing the brackets.
        argv = markup_safe(row["argv"])
        lines.append(
            f"[dim]{stamp}[/dim] [bold]{argv}[/bold] "
            f"[{colour}]{code}[/{colour}] [dim]{float(row['duration_ms']):.0f}ms[/dim]"
        )
    return lines


def describe_count(shown: int) -> str:
    return f"last {shown} command(s)" if shown else "no history"

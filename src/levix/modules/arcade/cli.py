"""`levix game` command surface: two screens, one auto-player, one score table.

Typer and Rich are imported here because building the app needs them. Textual is
imported *inside* the two screen helpers, so `levix game -h` and `levix game scores`
never construct a widget. The rules (`snake.py`, `tetris.py`) and the store
(`scores.py`) are stdlib-only and imported at module scope: the interactive screen and
`--auto` must run exactly the same functions, which is the whole reason a game can be
proven to work in a session with no TTY.

Exit codes come from `levix.errors` via `ArcadeError` (1, cannot run here) and
`ArcadeUsage` (2, the request itself is wrong). `scores --clear` goes through the
shared `levix.approve` gate with `destructive=True`, so `--yes` cannot authorize it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from ...approve import require_approval
from ...context import LevixContext
from ...deps import ensure_dependencies
from . import MANIFEST
from . import scores as store
from . import snake as snake_rules
from . import tetris as tetris_rules
from .scores import ArcadeUsage

if TYPE_CHECKING:
    from ...storage import Database

console = Console()

#: A board this big is already past what a terminal shows; bigger asks are mistakes.
MAX_COLS = 120
MAX_ROWS = 60
#: Placements/ticks an `--auto` run may take, so a typo cannot hang a session.
MAX_AUTO = 100000


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    ensure_dependencies(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="game",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    application.command("snake", help="Play snake. Arrows or WASD; --auto N plays itself.")(snake)
    application.command("tetris", help="Play tetris. --auto N plays a whole game itself.")(tetris)
    application.command("scores", help="Show stored high scores; --clear removes them.")(scores)
    return application


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------


def _context(typer_ctx: typer.Context) -> LevixContext:
    """The LEVIX context: paths, configuration and the shared database.

    `levix router` forwards a module's argv into a *fresh* click context, so
    `typer_ctx.obj` is None for every module command invoked as `levix game ...`;
    it is only populated when a command runs inside the root context. Rather than
    inventing a second source of truth, the module asks core to build the same
    context it built for the root command - the paths and the config come from the
    identical resolution, so nothing about the user's profile changes.
    """
    obj = getattr(typer_ctx, "obj", None)
    if isinstance(obj, LevixContext):
        return obj
    from ...app import build_context

    context = build_context()
    typer_ctx.obj = context  # one build per invocation: config and paths are re-used
    return context


def _database(typer_ctx: typer.Context) -> "Database":
    """The shared database, with this module's migration applied first.

    `ensure_schema` registers the `arcade` migration and applies it; both are
    idempotent, so an already-migrated profile costs one SELECT and no other
    namespace is touched.
    """
    context = _context(typer_ctx)
    store.ensure_schema(context.database)
    return context.database


def _speed(typer_ctx: typer.Context, override: float) -> float:
    """`--speed` wins over `arcade.speed`; both are clamped to the configured range."""
    value = override if override > 0 else float(_context(typer_ctx).value("arcade.speed"))
    return min(4.0, max(0.25, value))


def _seed_pair(seed: int | None) -> tuple[int, bool]:
    """(seed actually used, was it asked for). An unpinned run still records its seed."""
    if seed is not None:
        return seed, True
    return store.entropy_seed(), False


def _auto_steps(auto: int) -> int:
    if auto < 0:
        msg = f"--auto counts the steps a game may take and cannot be negative, got {auto}"
        raise ArcadeUsage(msg)
    if auto > MAX_AUTO:
        msg = f"--auto is capped at {MAX_AUTO}, got {auto}"
        raise ArcadeUsage(msg)
    return auto


def _check_board(cols: int, rows: int) -> tuple[int, int]:
    if cols < snake_rules.MIN_WIDTH or rows < snake_rules.MIN_HEIGHT:
        msg = (
            f"a snake board needs at least {snake_rules.MIN_WIDTH}x{snake_rules.MIN_HEIGHT}, "
            f"got {cols}x{rows}"
        )
        raise ArcadeUsage(msg)
    if cols > MAX_COLS or rows > MAX_ROWS:
        msg = f"a snake board is capped at {MAX_COLS}x{MAX_ROWS}, got {cols}x{rows}"
        raise ArcadeUsage(msg)
    return cols, rows


def _finish_callback(typer_ctx: typer.Context, *, seeded: bool) -> store.RecordFn:
    """The one function that turns a finished game into a stored row, screen or auto."""
    database = _database(typer_ctx)

    def record(game: str, score: int, detail: int, seed: int) -> store.ScoreRow:
        return store.record_score(
            database, game=game, score=score, detail=detail, seed=seed, seeded=seeded
        )

    return record


# ---------------------------------------------------------------------------
# snake
# ---------------------------------------------------------------------------


def snake(
    typer_ctx: typer.Context,
    seed: int | None = typer.Option(
        None, "--seed", help="Pin the RNG: the same seed and moves replay the same game."
    ),
    auto: int = typer.Option(
        0,
        "--auto",
        help="Play N ticks with the built-in auto-player and exit (0 = interactive screen).",
    ),
    speed: float = typer.Option(
        0.0, "--speed", help="Override arcade.speed (0.25 slow ... 4.0 fast)."
    ),
    cols: int = typer.Option(snake_rules.DEFAULT_COLS, "--cols", help="Board width."),
    rows: int = typer.Option(snake_rules.DEFAULT_ROWS, "--rows", help="Board height."),
) -> None:
    """Play snake: arrows or WASD steer, p pauses, r restarts, q or Esc quits.

    Interactive play needs a real terminal. With --auto N the rules run headlessly for
    up to N ticks (or until the snake dies), the final board is printed, and the score
    is stored like any other run.
    """
    steps = _auto_steps(auto)
    board = _check_board(cols, rows)
    used_seed, seeded = _seed_pair(seed)
    rate = _speed(typer_ctx, speed)
    if steps:
        _snake_auto(typer_ctx, seed=used_seed, seeded=seeded, ticks=steps, board=board)
        return
    _snake_screen(typer_ctx, seed=used_seed, seeded=seeded, speed=rate, board=board)


def _snake_auto(
    typer_ctx: typer.Context,
    *,
    seed: int,
    seeded: bool,
    ticks: int,
    board: tuple[int, int],
) -> None:
    """Drive the pure rules for N ticks with `auto_direction`; proves the loop runs."""
    cols, rows = board
    rng = store.game_rng(seed)
    state = snake_rules.new_game(cols, rows, rng)
    played = 0
    while played < ticks and state.alive:
        state = snake_rules.auto_step(state, rng)
        played += 1
    console.print(snake_rules.render(state))
    stopped = "the snake died" if not state.alive else f"the {ticks} tick cap"
    console.print(
        f"[bold]{played}[/bold] tick(s) played, stopped at {stopped}; "
        f"score {state.score}, length {state.length}"
    )
    finish = _finish_callback(typer_ctx, seeded=seeded)
    row = finish("snake", state.score, state.length, seed)
    _report_row(row)


def _snake_screen(
    typer_ctx: typer.Context,
    *,
    seed: int,
    seeded: bool,
    speed: float,
    board: tuple[int, int],
) -> None:
    from .screens import SnakeApp, require_terminal

    require_terminal("snake")
    cols, rows = board
    app = SnakeApp(
        cols=cols,
        rows=rows,
        seed=seed,
        speed=speed,
        on_finish=_finish_callback(typer_ctx, seeded=seeded),
    )
    raise typer.Exit(code=int(app.run() or 0))


# ---------------------------------------------------------------------------
# tetris
# ---------------------------------------------------------------------------


def tetris(
    typer_ctx: typer.Context,
    seed: int | None = typer.Option(
        None, "--seed", help="Pin the 7-bag order and the auto-player."
    ),
    auto: int = typer.Option(
        0,
        "--auto",
        help="Place N pieces with the built-in auto-player and exit (0 = interactive screen).",
    ),
    speed: float = typer.Option(
        0.0, "--speed", help="Override arcade.speed (0.25 slow ... 4.0 fast)."
    ),
) -> None:
    """Play tetris on the standard 10x20 field: left/right move, up rotates, down
    softens, space hard-drops, p pauses, r restarts, q or Esc quits.

    With --auto N the pieces are placed headlessly by the rule-level auto-player, which
    is how a full game is proven without a terminal.
    """
    steps = _auto_steps(auto)
    used_seed, seeded = _seed_pair(seed)
    rate = _speed(typer_ctx, speed)
    if steps:
        _tetris_auto(typer_ctx, seed=used_seed, seeded=seeded, pieces=steps)
        return
    _tetris_screen(typer_ctx, seed=used_seed, seeded=seeded, speed=rate)


def _tetris_auto(typer_ctx: typer.Context, *, seed: int, seeded: bool, pieces: int) -> None:
    rng = store.game_rng(seed)
    state = tetris_rules.new_game(rng)
    target = state.pieces + pieces
    while state.pieces < target and not state.over:
        state = tetris_rules.auto_step(state, rng)
    console.print(tetris_rules.render(state))
    stopped = "the stack reached the ceiling" if state.over else f"the {pieces} piece cap"
    console.print(
        f"[bold]{state.pieces}[/bold] piece(s) placed, stopped at {stopped}; "
        f"score {state.score}, lines {state.lines}, level {state.level}"
    )
    row = _finish_callback(typer_ctx, seeded=seeded)("tetris", state.score, state.lines, seed)
    _report_row(row)


def _tetris_screen(typer_ctx: typer.Context, *, seed: int, seeded: bool, speed: float) -> None:
    from .screens import TetrisApp, require_terminal

    require_terminal("tetris")
    app = TetrisApp(
        seed=seed,
        speed=speed,
        on_finish=_finish_callback(typer_ctx, seeded=seeded),
    )
    raise typer.Exit(code=int(app.run() or 0))


# ---------------------------------------------------------------------------
# scores
# ---------------------------------------------------------------------------


def scores(
    typer_ctx: typer.Context,
    game: str = typer.Option("", "--game", help="Only snake or only tetris."),
    limit: int = typer.Option(20, "--limit", "-n", help="Rows to show (0 = every row)."),
    clear: bool = typer.Option(
        False, "--clear", help="Delete stored scores; needs a typed confirmation."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accepted and ignored: --yes cannot authorize a delete."
    ),
) -> None:
    """List stored high scores, highest first and newest first inside a tie.

    `--clear` empties the table (or one game's rows with `--game`) through the shared
    LEVIX confirmation gate: you have to type DELETE, `--yes` is refused by design and
    a run without a terminal exits 6 having removed nothing.
    """
    database = _database(typer_ctx)
    wanted = game or None
    if clear:
        _clear_scores(typer_ctx, database, wanted, yes)
        return
    rows = store.top_scores(database, game=wanted, limit=limit)
    if not rows:
        scope = f" for {wanted}" if wanted else ""
        console.print(
            f"[dim]no scores yet{scope}.[/dim] Play [bold]levix game snake[/bold] or "
            f"[bold]levix game tetris[/bold], or run either with "
            f"[bold]--auto 40[/bold] to play one without a terminal."
        )
        return
    console.print(_scores_table(rows, scope=wanted))


def _clear_scores(
    typer_ctx: typer.Context, database: Database, wanted: str | None, yes: bool
) -> None:
    counts = store.counts(database)
    if not counts:
        console.print("[dim]nothing to clear: no scores are stored.[/dim]")
        return
    summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    detail = f"{wanted} scores only" if wanted else f"every arcade score ({summary})"
    require_approval(
        "clear arcade scores", detail, assume_yes=yes, destructive=True, prompt_word="DELETE"
    )
    removed = store.clear_scores(database, game=wanted)
    console.print(f"[red]removed[/red] {removed} score row(s).")
    _context(typer_ctx).logger.warning("arcade: cleared %s score row(s) (%s)", removed, detail)


def _scores_table(rows: list[store.ScoreRow], *, scope: str | None) -> Table:
    table = Table(
        title=f"Arcade high scores{' - ' + scope if scope else ''}",
        header_style="bold cyan",
    )
    table.add_column("#", justify="right")
    table.add_column("game")
    table.add_column("score", justify="right")
    table.add_column("length/lines", justify="right")
    table.add_column("replay with", overflow="fold")
    table.add_column("when")
    for rank, row in enumerate(rows, start=1):
        table.add_row(
            str(rank),
            row.game,
            str(row.score),
            f"{row.detail} ({row.detail_label})",
            f"--seed {row.seed_value}" if row.seed_value else "-",
            row.created_at,
        )
    return table


def _report_row(row: store.ScoreRow) -> None:
    console.print(
        f"[green]stored[/green] row {row.id}: {row.game} score [bold]{row.score}[/bold], "
        f"{row.detail_label} {row.detail}, seed [cyan]{row.seed_value}[/cyan]"
        f"{' (--seed)' if row.seeded else ''}, {row.created_at}"
    )

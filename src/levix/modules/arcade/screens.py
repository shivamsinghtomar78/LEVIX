"""The two Textual screens behind `levix game snake` and `levix game tetris`.

Imported *inside* the command functions of `cli.py`, never at package scope: this is
the only file in the module that touches Textual, so `levix game -h` stays cheap.

The division of labour is absolute. All rules live in `snake.py` and `tetris.py` as
pure functions; a widget callback here never computes anything a rule owns. A screen
does three things: draw `render(state)`, forward a key to a rule function, and hand the
finished score to the callback it was given. That is what makes the games testable in
an environment with no TTY, which is where they were written.

Every glyph is ASCII (`@ o * . + - | [ ] ( )`): on a cp1252 Windows console Textual's
writer raises UnicodeEncodeError on box drawing or block characters.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static

from . import snake as snake_rules
from . import tetris as tetris_rules
from .scores import ArcadeError, entropy_seed, game_rng

if TYPE_CHECKING:
    from textual.timer import Timer

#: (game, score, detail, seed used) -> the caller persists it: `scores.record_score`.
Finish = Callable[[str, int, int, int], object]


class _GameApp(App[None]):
    """Shared plumbing: HUD line, board, timer, pause, restart, quit, game over."""

    GAME = ""
    CSS: ClassVar[str] = """
    Vertical { height: auto; }
    #hud { height: 1; padding: 0 1; }
    #board { height: auto; padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("p", "pause", "Pause", priority=True),
        Binding("r", "again", "Play again", priority=True),
        Binding("q,escape", "quit_app", "Quit", priority=True),
    ]

    def __init__(
        self,
        *,
        seed: int | None = None,
        speed: float = 1.0,
        on_finish: Finish | None = None,
    ) -> None:
        super().__init__()
        #: Always concrete: an unpinned run still gets a recorded, replayable seed.
        self.seed = entropy_seed() if seed is None else seed
        self.speed = max(0.25, float(speed))
        self._on_finish = on_finish
        self._rng = game_rng(self.seed)
        self._timer: Timer | None = None
        self._paused = False
        self._settled = False
        self._interval_seen = 1.0
        #: The pure game state; the subclass owns its type and every mutation of it.
        self.state: Any = None

    # -- subclass contract -------------------------------------------------

    def new_state(self) -> Any:
        raise NotImplementedError

    def draw_state(self) -> None:
        raise NotImplementedError

    def step_state(self) -> None:
        raise NotImplementedError

    def interval_seconds(self) -> float:
        raise NotImplementedError

    def is_over(self) -> bool:
        raise NotImplementedError

    def summary(self) -> tuple[int, int]:
        raise NotImplementedError

    # -- lifecycle ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical():
            yield Static("", id="hud", markup=False)
            yield Static("", id="board", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.GAME
        self.restart_game()

    def restart_game(self) -> None:
        self._settled = False
        self._paused = False
        self.state = self.new_state()
        self._interval_seen = self.interval_seconds()
        self.draw_state()
        self._start_timer()

    def _start_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self._interval_seen, self._tick)

    def _tick(self) -> None:
        if self._paused:
            return
        self.step_state()
        self.draw_state()
        if self.is_over():
            self._settle()
            return
        self.retime()

    def retime(self) -> None:
        """Re-arm the timer when a rule changed the tick length (a tetris level-up).

        Textual keeps a timer's interval private, so the only honest way to change the
        rate is to stop this timer and set a new one.
        """
        interval = self.interval_seconds()
        if abs(interval - self._interval_seen) > 1e-9:
            self._interval_seen = interval
            self._start_timer()

    def _settle(self) -> None:
        """Game over: stop the clock, store the score once, offer another round."""
        if self._settled:
            return
        self._settled = True
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        score, detail = self.summary()
        if self._on_finish is not None:
            self._on_finish(self.GAME, score, detail, self.seed)
        self.notify(
            f"{self.GAME}: score {score} stored (seed {self.seed}). r plays again, q quits",
            markup=False,
        )

    def update_hud(self, text: str) -> None:
        self.query_one("#hud", Static).update(text)

    def update_board(self, text: str) -> None:
        self.query_one("#board", Static).update(text)

    # -- shared actions ----------------------------------------------------

    def action_pause(self) -> None:
        if self.is_over() or self._timer is None:
            return
        self._paused = not self._paused
        if self._paused:
            self._timer.pause()
        else:
            self._timer.resume()
        self.draw_state()

    def action_again(self) -> None:
        self.restart_game()

    def action_quit_app(self) -> None:
        self.exit()


class SnakeApp(_GameApp):
    """`levix game snake`: arrows or WASD steer, `q`/Esc quits, `r` starts a new round."""

    GAME = "snake"
    BINDINGS: ClassVar[list[Binding]] = [
        *_GameApp.BINDINGS,
        Binding("up,w", "steer('up')", "Up", priority=True),
        Binding("down,s", "steer('down')", "Down", priority=True),
        Binding("left,a", "steer('left')", "Left", priority=True),
        Binding("right,d", "steer('right')", "Right", priority=True),
    ]

    def __init__(
        self,
        *,
        cols: int = snake_rules.DEFAULT_COLS,
        rows: int = snake_rules.DEFAULT_ROWS,
        seed: int | None = None,
        speed: float = 1.0,
        interval: float | None = None,
        on_finish: Finish | None = None,
    ) -> None:
        super().__init__(seed=seed, speed=speed, on_finish=on_finish)
        self.cols = cols
        self.rows = rows
        #: A test (or a very fast player) can pin the tick rate instead of the speed.
        self.forced_interval = interval

    def new_state(self) -> snake_rules.Snake:
        return snake_rules.new_game(self.cols, self.rows, self._rng)

    def interval_seconds(self) -> float:
        if self.forced_interval is not None:
            return self.forced_interval
        return snake_rules.tick_seconds(self.speed)

    def step_state(self) -> None:
        self.state = snake_rules.step(self.state, self._rng)

    def is_over(self) -> bool:
        return not self.state.alive

    def summary(self) -> tuple[int, int]:
        return self.state.score, self.state.length

    def draw_state(self) -> None:
        self.update_board(snake_rules.render(self.state))
        if not self.state.alive:
            self.update_hud("GAME OVER  -  r plays again, q quits")
        elif self._paused:
            self.update_hud("paused  -  p resumes")
        else:
            self.update_hud(
                f"arrows or wasd steer  -  score {self.state.score}  length "
                f"{self.state.length}  tick {self.interval_seconds():.2f}s  seed {self.seed}"
            )

    def action_steer(self, direction: str) -> None:
        """Queue a heading; the next tick is what actually moves the snake."""
        if not self._paused and self.state.alive:
            self.state = snake_rules.turn(self.state, direction)
            self.draw_state()


class TetrisApp(_GameApp):
    """`levix game tetris`: left/right move, up rotates, down softens, space drops."""

    GAME = "tetris"
    BINDINGS: ClassVar[list[Binding]] = [
        *_GameApp.BINDINGS,
        Binding("left,a", "slide(-1)", "Left", priority=True),
        Binding("right,d", "slide(1)", "Right", priority=True),
        Binding("up,w,x", "spin", "Rotate", priority=True),
        Binding("down,s", "soften", "Soft", priority=True),
        Binding("space", "slam", "Drop", priority=True),
    ]

    def new_state(self) -> tetris_rules.Tetris:
        return tetris_rules.new_game(self._rng)

    def interval_seconds(self) -> float:
        return tetris_rules.tick_seconds(self.speed, self.state.level)

    def step_state(self) -> None:
        self.state = tetris_rules.step(self.state, self._rng)

    def is_over(self) -> bool:
        return self.state.over

    def summary(self) -> tuple[int, int]:
        return self.state.score, self.state.lines

    def draw_state(self) -> None:
        self.update_board(tetris_rules.render(self.state))
        if self.state.over:
            self.update_hud("GAME OVER  -  r plays again, q quits")
        elif self._paused:
            self.update_hud("paused  -  p resumes")
        else:
            self.update_hud(
                "left/right move   up rotates   down softens   space drops   "
                f"tick {self._interval_seen:.2f}s   seed {self.seed}"
            )

    def action_slide(self, delta: int) -> None:
        self._apply(tetris_rules.move(self.state, int(delta)))

    def action_spin(self) -> None:
        self._apply(tetris_rules.rotate(self.state))

    def action_soften(self) -> None:
        self._apply(tetris_rules.soft_drop(self.state, self._rng))

    def action_slam(self) -> None:
        self._apply(tetris_rules.hard_drop(self.state, self._rng))

    def _apply(self, state: tetris_rules.Tetris) -> None:
        """Accept a player's move, then redraw and re-time. No rules computed here."""
        if self._paused or self.state.over or state is self.state:
            return
        self.state = state
        self.draw_state()
        self.retime()
        if state.over:
            self._settle()


def require_terminal(game: str) -> None:
    """A screen needs a real TTY; on a pipe Textual would be driving nothing."""
    if not sys.stdout.isatty():
        msg = f"{game} needs a real terminal (stdout is not a tty)"
        raise ArcadeError(msg, hint=f"run `levix game {game} --auto N` to play it headlessly")

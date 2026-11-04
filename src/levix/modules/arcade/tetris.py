"""Tetris rules as pure data: a 10x20 playfield, seven pieces, deterministic bag.

Same contract as `snake.py`: functions take a state (plus an explicit `random.Random`)
and return the next state, so a seed replays a game exactly and the rules are testable
without a terminal.

Kept standard:
  * 10 columns x 20 rows, gravity locks a piece when it can no longer fall.
  * the seven tetrominoes I O T S Z J L, a 7-bag randomiser (every piece appears once
    per bag, order from the seeded RNG) and a visible next piece.
  * line clears score 100 / 300 / 500 / 800 x level, level = 1 + lines // 10, and the
    gravity interval shortens with the level.
  * soft drop scores 1 point per cell, hard drop 2 per cell.

Simplified on purpose (also in docs/modules/ARCADE.md):
  * rotation is clockwise only; there is no 180 degree turn and no hold piece.
  * wall kicks are the six offsets (0,0) (-1,0) (1,0) (-2,0) (2,0) (0,-1) instead of
    the SRS tables; if all six collide the rotation is refused.
  * a piece spawns with the top row of its own box at row 0, not in a hidden buffer
    zone above the field, so a blocked spawn is the game-over condition.
  * no lock delay (a piece locks on the tick it lands, so there is no spin window),
    no ghost piece, no T-spin, combo or back-to-back scoring.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, replace
from typing import Literal

Point = tuple[int, int]
Board = tuple[tuple[int, ...], ...]
Action = Literal["left", "right", "rotate", "soft", "hard"]

COLS = 10
ROWS = 20
SPAWN_Y = 0
BASE_TICK_SECONDS = 0.8
MIN_TICK_SECONDS = 0.05
LEVEL_FACTOR = 0.85
LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}
KICKS: tuple[Point, ...] = ((0, 0), (-1, 0), (1, 0), (-2, 0), (2, 0), (0, -1))

#: Every base matrix is square, so clockwise rotation is "column i, read bottom-up".
BASE_MATRIX: dict[str, tuple[tuple[int, ...], ...]] = {
    "I": ((0, 0, 0, 0), (1, 1, 1, 1), (0, 0, 0, 0), (0, 0, 0, 0)),
    "O": ((1, 1), (1, 1)),
    "T": ((0, 1, 0), (1, 1, 1), (0, 0, 0)),
    "S": ((0, 1, 1), (1, 1, 0), (0, 0, 0)),
    "Z": ((1, 1, 0), (0, 1, 1), (0, 0, 0)),
    "J": ((1, 0, 0), (1, 1, 1), (0, 0, 0)),
    "L": ((0, 0, 1), (1, 1, 1), (0, 0, 0)),
}
PIECE_ORDER = ("I", "O", "T", "S", "Z", "J", "L")


def _cells(matrix: tuple[tuple[int, ...], ...]) -> tuple[Point, ...]:
    return tuple(
        (row, col) for row, line in enumerate(matrix) for col, filled in enumerate(line) if filled
    )


def _clockwise(matrix: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    size = len(matrix)
    return tuple(tuple(matrix[row][col] for row in reversed(range(size))) for col in range(size))


def _states(key: str) -> tuple[tuple[Point, ...], ...]:
    """The four rotation states of a piece, built once at import from its base matrix."""
    matrix = BASE_MATRIX[key]
    states = []
    for _ in range(4):
        states.append(_cells(matrix))
        matrix = _clockwise(matrix)
    return tuple(states)


#: SHAPES[key][rotation] holds (row, column) offsets inside the piece's own box.
SHAPES: dict[str, tuple[tuple[Point, ...], ...]] = {key: _states(key) for key in PIECE_ORDER}


@dataclass(frozen=True, slots=True)
class Tetris:
    """One immutable position: the locked board plus the falling piece."""

    board: Board
    key: str
    rotation: int
    x: int
    y: int
    next_key: str
    bag: tuple[str, ...] = ()
    score: int = 0
    lines: int = 0
    pieces: int = 0
    last_clear: int = 0
    over: bool = False

    @property
    def level(self) -> int:
        return self.lines // 10 + 1

    @property
    def cells(self) -> tuple[Point, ...]:
        return tuple((self.y + row, self.x + col) for row, col in SHAPES[self.key][self.rotation])

    @property
    def stack_height(self) -> int:
        """Rows of the locked stack, i.e. how close the ceiling is."""
        for index, row in enumerate(self.board):
            if any(row):
                return ROWS - index
        return 0


def tick_seconds(speed: float, level: int) -> float:
    """Seconds per gravity step: `arcade.speed` scales it, the level decays it."""
    base = BASE_TICK_SECONDS / max(0.25, float(speed))
    return round(max(MIN_TICK_SECONDS, base * LEVEL_FACTOR ** (max(1, level) - 1)), 4)


def empty_board() -> Board:
    return tuple(tuple(0 for _ in range(COLS)) for _ in range(ROWS))


def _draw(bag: tuple[str, ...], rng: random.Random) -> tuple[str, tuple[str, ...]]:
    """Take the next piece from the bag, refilling with a fresh shuffled 7-bag."""
    if not bag:
        bag = tuple(rng.sample(PIECE_ORDER, len(PIECE_ORDER)))
    return bag[0], bag[1:]


def _spawn_x(key: str, rotation: int) -> int:
    width = max(col for _, col in SHAPES[key][rotation]) + 1
    return (COLS - width) // 2


def collides(board: Board, key: str, rotation: int, x: int, y: int) -> bool:
    for row, col in SHAPES[key][rotation]:
        r, c = y + row, x + col
        if c < 0 or c >= COLS or r >= ROWS:
            return True
        if board[r][c]:
            return True
    return False


def new_game(rng: random.Random) -> Tetris:
    key, bag = _draw((), rng)
    next_key, bag = _draw(bag, rng)
    return Tetris(
        board=empty_board(),
        key=key,
        rotation=0,
        x=_spawn_x(key, 0),
        y=SPAWN_Y,
        next_key=next_key,
        bag=bag,
    )


def move(state: Tetris, dx: int) -> Tetris:
    """Shift one column left (-1) or right (+1); a blocked shift changes nothing."""
    if state.over:
        return state
    if not collides(state.board, state.key, state.rotation, state.x + dx, state.y):
        return replace(state, x=state.x + dx)
    return state


def rotate(state: Tetris) -> Tetris:
    """Clockwise one quarter, trying the six simple kick offsets in order."""
    if state.over:
        return state
    attempt = (state.rotation + 1) % 4
    for kick_x, kick_y in KICKS:
        if not collides(state.board, state.key, attempt, state.x + kick_x, state.y + kick_y):
            return replace(state, rotation=attempt, x=state.x + kick_x, y=state.y + kick_y)
    return state


def _merged(state: Tetris) -> Board:
    """Freeze the active piece into the board. Cells are in range: only legal moves run."""
    grid = [list(row) for row in state.board]
    value = PIECE_ORDER.index(state.key) + 1
    for row, col in state.cells:
        grid[row][col] = value
    return tuple(tuple(entry) for entry in grid)


def clear_rows(board: Board) -> tuple[Board, int]:
    """Drop every completely filled row and return how many went."""
    kept = [row for row in board if not all(row)]
    cleared = ROWS - len(kept)
    while len(kept) < ROWS:
        kept.insert(0, tuple(0 for _ in range(COLS)))
    return tuple(tuple(row) for row in kept), cleared


def _spawn_after(state: Tetris, board: Board, cleared: int, rng: random.Random) -> Tetris:
    """Score the clear, then bring in the next piece; a blocked spawn ends the game."""
    gained = LINE_SCORES.get(cleared, 0) * state.level
    key = state.next_key
    next_key, bag = _draw(state.bag, rng)
    placed = Tetris(
        board=board,
        key=key,
        rotation=0,
        x=_spawn_x(key, 0),
        y=SPAWN_Y,
        next_key=next_key,
        bag=bag,
        score=state.score + gained,
        lines=state.lines + cleared,
        pieces=state.pieces + 1,
        last_clear=cleared,
    )
    if collides(board, key, 0, placed.x, placed.y):
        return replace(placed, over=True)
    return placed


def lock(state: Tetris, rng: random.Random) -> Tetris:
    """Freeze, clear, score, spawn: one place where a piece stops being active."""
    board, cleared = clear_rows(_merged(state))
    return _spawn_after(state, board, cleared, rng)


def step(state: Tetris, rng: random.Random) -> Tetris:
    """One gravity tick: fall if possible, otherwise lock."""
    if state.over:
        return state
    if not collides(state.board, state.key, state.rotation, state.x, state.y + 1):
        return replace(state, y=state.y + 1)
    return lock(state, rng)


def soft_drop(state: Tetris, rng: random.Random) -> Tetris:
    """Move down one row for 1 point, or lock when the row below is taken."""
    if state.over:
        return state
    if not collides(state.board, state.key, state.rotation, state.x, state.y + 1):
        return replace(state, y=state.y + 1, score=state.score + 1)
    return lock(state, rng)


def drop_distance(state: Tetris) -> int:
    distance = 0
    while not collides(state.board, state.key, state.rotation, state.x, state.y + distance + 1):
        distance += 1
    return distance


def hard_drop(state: Tetris, rng: random.Random) -> Tetris:
    """Fall to the floor, 2 points per cell, and lock immediately."""
    if state.over:
        return state
    distance = drop_distance(state)
    return lock(replace(state, y=state.y + distance, score=state.score + 2 * distance), rng)


def apply_action(state: Tetris, action: Action, rng: random.Random) -> Tetris:
    """The one place a key name becomes a rule, shared by the screen and the tests."""
    if action == "left":
        return move(state, -1)
    if action == "right":
        return move(state, 1)
    if action == "rotate":
        return rotate(state)
    if action == "soft":
        return soft_drop(state, rng)
    return hard_drop(state, rng)


def landing_y(board: Board, key: str, rotation: int, x: int) -> int:
    """Lowest legal row offset for a piece at column `x`, or -1 when it will not fit."""
    if collides(board, key, rotation, x, SPAWN_Y):
        return -1
    y = SPAWN_Y
    while not collides(board, key, rotation, x, y + 1):
        y += 1
    return y


def _score_board(board: Board, cleared: int) -> float:
    """Lower is better: filled rows, then height, holes and bumpiness."""
    heights = []
    holes = 0
    for col in range(COLS):
        column = [board[row][col] for row in range(ROWS)]
        top = next((index for index, filled in enumerate(column) if filled), None)
        heights.append(ROWS - top if top is not None else 0)
        if top is not None:
            holes += sum(1 for filled in column[top:] if not filled)
    bumpiness = sum(abs(a - b) for a, b in itertools.pairwise(heights))
    return -4.0 * cleared + sum(heights) + holes + 0.4 * bumpiness


def best_placement(state: Tetris) -> tuple[int, int, int]:
    """(rotation, x, y) the auto-player rates highest; the scan order breaks ties.

    A plain height/holes/bumpiness evaluation rather than a search: deterministic and
    readable, which matters more here than playing well.
    """
    best: tuple[int, int, int] | None = None
    best_rating = 0.0
    for rotation in range(4):
        for x in range(COLS):
            y = landing_y(state.board, state.key, rotation, x)
            if y < 0:
                continue
            grid = [list(row) for row in state.board]
            for row, col in SHAPES[state.key][rotation]:
                grid[y + row][x + col] = 1
            board, cleared = clear_rows(tuple(tuple(entry) for entry in grid))
            rating = _score_board(board, cleared)
            if best is None or rating < best_rating:
                best, best_rating = (rotation, x, y), rating
    return best if best is not None else (state.rotation, state.x, state.y)


def auto_step(state: Tetris, rng: random.Random) -> Tetris:
    """Place one whole piece with no input: pick, position, lock."""
    if state.over:
        return state
    rotation, x, y = best_placement(state)
    return lock(replace(state, rotation=rotation, x=x, y=y), rng)


def render(state: Tetris) -> str:
    """ASCII board: `[]` locked, `()` the falling piece, `..` empty, `+ - |` border.

    Every glyph is 7-bit on purpose: a cp1252 Windows console raises UnicodeEncodeError
    inside Rich and inside Textual's writer on U+2588 or box drawing.
    """
    field = [[".."] * COLS for _ in range(ROWS)]
    for row_index, row in enumerate(state.board):
        for col_index, value in enumerate(row):
            if value:
                field[row_index][col_index] = "[]"
    if not state.over:
        for row, col in state.cells:
            field[row][col] = "()"
    edge = "+" + "-" * (COLS * 2) + "+"
    lines = [edge]
    lines.extend("|" + "".join(row) + "|" for row in field)
    lines.append(edge)
    if state.over:
        lines.append(f"GAME OVER  score {state.score}  lines {state.lines}")
    else:
        lines.append(
            f"score {state.score}  lines {state.lines}  level {state.level}  next {state.next_key}"
        )
    return "\n".join(lines)

"""Snake rules as pure data: no terminal, no clock, no widget, no database.

Every function takes the current state plus an explicit `random.Random` and returns a
new state, so a seed plus a sequence of turns replays exactly. That property is the
reason this module is testable at all: the shell used to build LEVIX has no TTY, so
`levix game snake --auto N` drives these functions directly and the Textual screen is
only a driver that draws `render()` and forwards keys.

Rules, including what was simplified (repeated in docs/modules/ARCADE.md):
  * walls kill; the board never wraps.
  * one food at a time, always on a free cell, picked with `rng.choice` over the
    sorted free cells, so placement cannot depend on set iteration order.
  * turning 180 degrees into yourself is ignored rather than fatal.
  * each food is worth FOOD_POINTS and grows the snake by exactly one segment.
  * there is no speed ramp inside a game: `arcade.speed` alone sets the tick rate.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Literal

Point = tuple[int, int]
Direction = Literal["up", "down", "left", "right"]

FOOD_POINTS = 10
START_LENGTH = 3
BASE_TICK_SECONDS = 0.18

VECTORS: dict[Direction, Point] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}
#: arrow keys and WASD both steer, so the screen and the tests speak one vocabulary.
KEY_TO_DIRECTION: dict[str, Direction] = {
    "up": "up",
    "w": "up",
    "down": "down",
    "s": "down",
    "left": "left",
    "a": "left",
    "right": "right",
    "d": "right",
}
MIN_WIDTH = 6
MIN_HEIGHT = 5
#: The board the screen and `--auto` use unless the user asks for another size.
DEFAULT_COLS = 24
DEFAULT_ROWS = 12


@dataclass(frozen=True, slots=True)
class Snake:
    """One immutable board position. `body[0]` is the head, the tail is last."""

    width: int
    height: int
    body: tuple[Point, ...]
    direction: Direction
    food: Point
    score: int = 0
    ticks: int = 0
    alive: bool = True
    full_board: bool = False

    @property
    def head(self) -> Point:
        return self.body[0]

    @property
    def length(self) -> int:
        return len(self.body)


def tick_seconds(speed: float) -> float:
    """Seconds between moves for `arcade.speed` (0.25 slow ... 4.0 fast)."""
    return round(BASE_TICK_SECONDS / max(0.25, float(speed)), 4)


def new_game(width: int, height: int, rng: random.Random) -> Snake:
    """A horizontal snake of START_LENGTH heading right, plus the first food."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        msg = f"a snake board needs at least {MIN_WIDTH}x{MIN_HEIGHT}, got {width}x{height}"
        raise ValueError(msg)
    y = height // 2
    x = width // 2
    body = tuple((x - offset, y) for offset in range(START_LENGTH))
    state = Snake(width=width, height=height, body=body, direction="right", food=(0, 0))
    food = _place_food(state, rng)
    return replace(state, food=food)


def free_cells(state: Snake) -> list[Point]:
    occupied = set(state.body)
    return [
        (x, y) for y in range(state.height) for x in range(state.width) if (x, y) not in occupied
    ]


def _place_food(state: Snake, rng: random.Random) -> Point:
    options = free_cells(state)
    if not options:
        # The snake covers the board: there is nothing left to eat.
        return state.head
    return rng.choice(options)


def is_dead_on(state: Snake, target: Point) -> bool:
    """Is `target` outside the walls?

    The tail tip is not a hazard here because a normal move vacates it; `step` checks
    the body itself, and skips that check on the cell the tail is leaving.
    """
    x, y = target
    return x < 0 or y < 0 or x >= state.width or y >= state.height


def turn(state: Snake, direction: Direction) -> Snake:
    """Queue a new heading. Reversals and repeats are ignored, never fatal."""
    if not state.alive:
        return state
    if VECTORS[direction] == (-VECTORS[state.direction][0], -VECTORS[state.direction][1]):
        return state
    return replace(state, direction=direction)


def step(state: Snake, rng: random.Random) -> Snake:
    """Advance exactly one tick: move, eat, maybe die."""
    if not state.alive:
        return state
    dx, dy = VECTORS[state.direction]
    head = (state.head[0] + dx, state.head[1] + dy)
    eating = head == state.food
    body = state.body if eating else state.body[:-1]
    if is_dead_on(state, head) or head in set(body):
        return replace(state, alive=False, ticks=state.ticks + 1)
    if eating:
        grown = (head, *state.body)
        if len(grown) == state.width * state.height:
            # The board is covered: no free cell is left to put food on.
            return replace(
                state,
                body=grown,
                score=state.score + FOOD_POINTS,
                ticks=state.ticks + 1,
                alive=False,
                full_board=True,
            )
        return replace(
            state,
            body=grown,
            score=state.score + FOOD_POINTS,
            ticks=state.ticks + 1,
            food=_place_food(replace(state, body=grown), rng),
        )
    return replace(state, body=(head, *body), ticks=state.ticks + 1)


def auto_direction(state: Snake, rng: random.Random) -> Direction:
    """The move an autoplaying player makes: safe, not a dead end, then closest to food.

    Used by `--auto` so a game can be proven to run without a keyboard. It is a greedy
    one-ply player, not a solver: it refuses a cell that leaves no way out (which is
    how a naive snake seals itself into a pocket) and otherwise walks towards the
    food. Ties are broken with `rng.shuffle`, so the seed still decides the outcome.
    With no safe move at all the current heading is kept and the snake dies on the next
    tick rather than pretending to be alive.
    """
    blocked = set(state.body[:-1])

    def landing(direction: Direction) -> Point:
        dx, dy = VECTORS[direction]
        return (state.head[0] + dx, state.head[1] + dy)

    def open_exits(cell: Point) -> int:
        return sum(
            1
            for dx, dy in VECTORS.values()
            if not is_dead_on(state, (cell[0] + dx, cell[1] + dy))
            and (cell[0] + dx, cell[1] + dy) not in blocked
        )

    candidates: list[Direction] = []
    for direction in ("up", "down", "left", "right"):
        if VECTORS[direction] == (-VECTORS[state.direction][0], -VECTORS[state.direction][1]):
            continue
        if is_dead_on(state, landing(direction)) or landing(direction) in blocked:
            continue
        candidates.append(direction)
    if not candidates:
        return state.direction
    rng.shuffle(candidates)
    survivors = [direction for direction in candidates if open_exits(landing(direction)) > 0]
    pool = survivors or candidates
    fx, fy = state.food

    def distance(direction: Direction) -> int:
        head_x, head_y = landing(direction)
        return abs(head_x - fx) + abs(head_y - fy)

    return min(pool, key=distance)


def auto_step(state: Snake, rng: random.Random) -> Snake:
    """One autoplayed tick: choose a heading, then apply it."""
    return step(turn(state, auto_direction(state, rng)), rng)


def render(state: Snake) -> str:
    """ASCII-only board text: `@` head, `o` body, `*` food, `.` empty, `+ - |` border.

    Deliberately no box drawing and no blocks. A cp1252 Windows console raises
    UnicodeEncodeError inside Rich and inside Textual's writer on U+2588, so every
    glyph here is 7-bit.
    """
    glyphs: dict[Point, str] = dict.fromkeys(state.body, "o")
    glyphs[state.head] = "@"
    if state.alive and not state.full_board:
        glyphs[state.food] = "*"
    lines = ["+" + "-" * state.width + "+"]
    for y in range(state.height):
        row = "".join(glyphs.get((x, y), ".") for x in range(state.width))
        lines.append(f"|{row}|")
    lines.append("+" + "-" * state.width + "+")
    status = "GAME OVER" if not state.alive else f"score {state.score}  length {state.length}"
    lines.append(status)
    return "\n".join(lines)

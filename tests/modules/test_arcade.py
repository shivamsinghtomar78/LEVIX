"""The Arcade module: pure rules, the score table, and the two Textual screens.

The rules are tested as data, because that is how they are written: a seeded RNG plus
an explicit move must produce the same next state on any machine, in any terminal. The
CLI tests go through `levix.main.main` with the `run_cli` fixture, so exit codes, the
shared database and the approval gate are all real. The screen tests drive Textual with
`App.run_test(headless=True)` - `textual.testing` does not exist in the pinned version
and there is no TTY here, so a "played" game is a seeded auto-player, not a keyboard.
"""

from __future__ import annotations

import asyncio
import os
import random
import subprocess
import sys
from dataclasses import replace

import pytest

from levix import storage
from levix.errors import EXIT_CANCELLED, EXIT_RUNTIME, EXIT_UNKNOWN_MODULE, EXIT_USAGE
from levix.modules.arcade import MANIFEST
from levix.modules.arcade import scores as store
from levix.modules.arcade import snake as snake_rules
from levix.modules.arcade import tetris as tetris_rules
from levix.storage import Database


def both(captured) -> str:
    return captured.out + captured.err


def filled_board(rows: tuple[int, ...], blocked: tuple[tuple[int, int], ...] = ()):
    """A constructed playfield: whole rows filled, plus individual blocked cells."""
    grid = [[0] * tetris_rules.COLS for _ in range(tetris_rules.ROWS)]
    for row in rows:
        grid[row] = [1] * tetris_rules.COLS
    for row, col in blocked:
        grid[row][col] = 1
    return tuple(tuple(entry) for entry in grid)


def fresh_snake(width: int = 20, height: int = 10, seed: int = 7) -> snake_rules.Snake:
    return snake_rules.new_game(width, height, random.Random(seed))


# ---------------------------------------------------------------------------------
# Snake rules
# ---------------------------------------------------------------------------------


def test_a_new_game_is_a_horizontal_snake_with_food_on_a_free_cell():
    state = fresh_snake()
    assert state.direction == "right" and state.alive
    assert state.length == snake_rules.START_LENGTH == 3
    assert state.body[1] == (state.head[0] - 1, state.head[1]), "the tail trails the head"
    assert state.food not in state.body
    assert 0 <= state.food[0] < state.width and 0 <= state.food[1] < state.height
    assert state.score == 0 and state.ticks == 0


def test_a_step_moves_the_head_and_keeps_the_length():
    state = fresh_snake()
    moved = snake_rules.step(state, random.Random(1))
    assert moved.head == (state.head[0] + 1, state.head[1])
    assert moved.length == state.length and moved.ticks == 1
    assert moved.alive and moved.score == 0


def test_eating_grows_the_snake_by_one_and_scores_ten():
    state = fresh_snake()
    in_front = (state.head[0] + 1, state.head[1])
    eaten = snake_rules.step(replace(state, food=in_front), random.Random(1))
    assert eaten.length == state.length + 1
    assert eaten.score == snake_rules.FOOD_POINTS
    assert eaten.food != in_front and eaten.food not in eaten.body
    assert eaten.alive, "food in front of the head must not be fatal"


def test_the_wall_kills_and_the_score_stands():
    row = fresh_snake().head[1]
    at_wall = replace(
        fresh_snake(),
        body=((19, row), (18, row), (17, row)),
    )
    dead = snake_rules.step(at_wall, random.Random(1))
    assert not dead.alive and dead.score == at_wall.score
    assert dead.ticks == 1, "the fatal tick is still counted"
    assert snake_rules.step(dead, random.Random(1)) is dead, "a dead snake moves no more"


def test_biting_the_body_kills_but_the_cell_the_tail_is_leaving_does_not():
    # head (6,5) -> down into (6,6), which is body[1] and stays there: a bite.
    biting = replace(
        fresh_snake(),
        body=((6, 5), (6, 6), (7, 6), (7, 7)),
        direction="down",
        food=(0, 0),
    )
    assert snake_rules.step(biting, random.Random(1)).alive is False

    # head (6,5) -> right into (7,5), which is the tail tip it vacates: safe.
    tail = ((6, 5), (6, 6), (7, 6), (7, 5))
    following = replace(fresh_snake(), body=tail, direction="right", food=(0, 0))
    assert following.head == (6, 5) and (7, 5) in following.body
    assert snake_rules.step(following, random.Random(1)).alive is True


def test_a_reversal_is_ignored_rather_than_fatal():
    state = fresh_snake()
    assert snake_rules.turn(state, "left").direction == "right"
    assert snake_rules.turn(state, "up").direction == "up"
    assert snake_rules.turn(state, "right").direction == "right"
    dead = replace(state, alive=False)
    assert snake_rules.turn(dead, "down").direction == "right"


def test_the_same_seed_places_the_same_food_and_a_different_seed_does_not():
    def sequence(seed: int) -> list[tuple[int, int]]:
        rng = random.Random(seed)
        state = snake_rules.new_game(24, 12, rng)
        seen = []
        for _ in range(30):
            state = snake_rules.auto_step(state, rng)
            seen.append(state.food)
        return seen

    assert sequence(11) == sequence(11), "--seed must replay a game exactly"
    assert sequence(11) != sequence(12)


def test_the_auto_player_eats_and_its_length_matches_its_score():
    rng = random.Random(3)
    state = snake_rules.new_game(24, 12, rng)
    for _ in range(250):
        state = snake_rules.auto_step(state, rng)
    assert state.score >= 3 * snake_rules.FOOD_POINTS, "it must find food"
    assert state.length == snake_rules.START_LENGTH + state.score // snake_rules.FOOD_POINTS
    assert state.full_board is False


def test_the_board_must_be_big_enough_to_hold_a_snake():
    with pytest.raises(ValueError, match="at least"):
        snake_rules.new_game(4, 4, random.Random(1))


def test_the_tick_rate_follows_arcade_speed():
    assert snake_rules.tick_seconds(1.0) == snake_rules.BASE_TICK_SECONDS
    assert snake_rules.tick_seconds(2.0) < snake_rules.tick_seconds(1.0)
    assert snake_rules.tick_seconds(0.1) == snake_rules.tick_seconds(0.25), "clamped slow"


# ---------------------------------------------------------------------------------
# Tetris rules
# ---------------------------------------------------------------------------------


def test_seven_pieces_with_four_states_each_and_a_known_t_rotation():
    assert sorted(tetris_rules.SHAPES) == sorted(tetris_rules.PIECE_ORDER) == sorted("IOTSZJL")
    for key, states in tetris_rules.SHAPES.items():
        assert len(states) == 4, key
        assert all(cells for cells in states), key
        assert all(
            0 <= row < 4 and 0 <= col < 4 for cells in states for row, col in cells
        ), key
    assert tetris_rules.SHAPES["T"][0] == ((0, 1), (1, 0), (1, 1), (1, 2))
    assert tetris_rules.SHAPES["T"][1] == ((0, 1), (1, 1), (1, 2), (2, 1))
    assert len(set(tetris_rules.SHAPES["O"])) == 1, "O is symmetric: its states match"


def test_a_new_game_uses_the_seeded_seven_bag():
    rng = random.Random(7)
    state = tetris_rules.new_game(rng)
    seen = [state.key]
    for _ in range(6):
        state = tetris_rules.auto_step(state, rng)
        seen.append(state.key)
    assert sorted(seen) == sorted(tetris_rules.PIECE_ORDER), "one bag holds each piece once"
    assert tetris_rules.new_game(random.Random(7)).key == seen[0], "the bag belongs to the seed"


def test_a_move_stops_at_the_wall_instead_of_leaving_the_field():
    state = tetris_rules.new_game(random.Random(2))
    offsets = tetris_rules.SHAPES[state.key][state.rotation]
    for _ in range(tetris_rules.COLS + 2):
        state = tetris_rules.move(state, -1)
    assert state.x + min(col for _, col in offsets) == 0
    for _ in range(tetris_rules.COLS + 2):
        state = tetris_rules.move(state, 1)
    assert state.x + max(col for _, col in offsets) == tetris_rules.COLS - 1


def test_a_rotation_never_ends_inside_a_block_even_against_a_filled_field():
    blocked = filled_board((), blocked=tuple((r, c) for r in (1, 3) for c in range(6)))
    base = tetris_rules.new_game(random.Random(5))
    checked = 0
    for key in tetris_rules.PIECE_ORDER:
        for rotation in range(4):
            for y in range(tetris_rules.ROWS):
                for x in range(-2, tetris_rules.COLS):
                    jammed = replace(base, board=blocked, key=key, rotation=rotation, x=x, y=y)
                    if tetris_rules.collides(jammed.board, key, rotation, x, y):
                        continue
                    checked += 1
                    after = tetris_rules.rotate(jammed)
                    assert not tetris_rules.collides(
                        after.board, after.key, after.rotation, after.x, after.y
                    ), "a kick either lands clear or the rotation is refused"
    assert checked > 200, "the sweep must actually cover legal pockets"


def test_line_clears_score_the_classic_table_on_a_constructed_board():
    rng = random.Random(1)
    bottom = tetris_rules.ROWS - 1
    two_rows = filled_board((bottom - 1, bottom))
    grid = [list(row) for row in two_rows]
    for row in (bottom - 1, bottom):
        grid[row][0] = 0
        grid[row][1] = 0
    grid[bottom - 2][0] = 0  # so row `bottom-1` is not already clearable

    cleared = tetris_rules.lock(
        tetris_rules.Tetris(
            board=tuple(tuple(entry) for entry in grid),
            key="O",
            rotation=0,
            x=0,
            y=bottom - 1,
            next_key="T",
        ),
        rng,
    )
    assert cleared.last_clear == 2 and cleared.lines == 2 and cleared.pieces == 1
    assert cleared.score == 300, "two lines score 300 at level 1"
    assert tetris_rules.LINE_SCORES == {1: 100, 2: 300, 3: 500, 4: 800}

    one_row = filled_board((bottom,))
    single = tetris_rules.lock(
        tetris_rules.Tetris(
            board=one_row, key="O", rotation=0, x=0, y=bottom - 1, next_key="T"
        ),
        rng,
    )
    assert single.last_clear == 1 and single.score == 100
    assert tetris_rules.clear_rows(filled_board((16, 17, 18, 19)))[1] == 4


def test_the_level_multiplier_and_the_speed_change_are_both_real():
    rng = random.Random(4)
    bottom = tetris_rules.ROWS - 1
    grid = [list(row) for row in filled_board((bottom,))]
    grid[bottom][0] = 0
    grid[bottom][1] = 0
    state = tetris_rules.Tetris(
        board=tuple(tuple(entry) for entry in grid),
        key="O",
        rotation=0,
        x=0,
        y=bottom - 1,
        next_key="T",
        lines=10,
    )
    assert state.level == 2
    cleared = tetris_rules.lock(state, rng)
    assert cleared.score == 200, "100 x level, not a flat 100"
    assert cleared.lines == 11 and cleared.level == 2
    assert tetris_rules.tick_seconds(1.0, 1) > tetris_rules.tick_seconds(1.0, 5)
    assert tetris_rules.tick_seconds(2.0, 1) < tetris_rules.tick_seconds(1.0, 1)
    assert tetris_rules.tick_seconds(4.0, 99) == tetris_rules.MIN_TICK_SECONDS


def test_the_game_ends_when_the_spawn_area_is_occupied():
    rng = random.Random(9)
    bottom = tetris_rules.ROWS - 1
    blocked_top = filled_board(
        (), blocked=tuple((row, col) for row in (0, 1) for col in range(3, 6))
    )
    state = tetris_rules.Tetris(
        board=blocked_top, key="O", rotation=0, x=0, y=bottom - 1, next_key="T"
    )
    finished = tetris_rules.lock(state, rng)
    assert finished.over is True
    assert "GAME OVER" in tetris_rules.render(finished)
    assert tetris_rules.step(finished, rng) is finished, "an ended game does not advance"
    assert tetris_rules.hard_drop(finished, rng) is finished


def test_a_hard_drop_locks_immediately_and_pays_two_points_per_cell():
    rng = random.Random(6)
    state = tetris_rules.new_game(rng)
    distance = tetris_rules.drop_distance(state)
    dropped = tetris_rules.hard_drop(state, rng)
    assert dropped.pieces == 1
    assert dropped.score == 2 * distance
    assert dropped.key == state.next_key, "the next piece became the active one"
    assert tetris_rules.apply_action(dropped, "left", rng) is not None


# ---------------------------------------------------------------------------------
# Renders must be ASCII (HARD RULE 3)
# ---------------------------------------------------------------------------------


def test_every_rendered_character_is_7_bit():
    texts = (
        snake_rules.render(fresh_snake()),
        tetris_rules.render(tetris_rules.new_game(random.Random(1))),
    )
    for text in texts:
        assert all(ord(char) < 128 for char in text), (
            "no box drawing or blocks: a cp1252 Windows console raises UnicodeEncodeError"
        )
    assert "+--" in texts[0] and "@" in texts[0], "head plus a bordered grid"
    assert "[]" in texts[1] or "()" in texts[1], "the piece cells are drawn"


# ---------------------------------------------------------------------------------
# The score table
# ---------------------------------------------------------------------------------


@pytest.fixture
def database(tmp_path) -> Database:
    db = Database(tmp_path / "levix.db")
    store.ensure_schema(db)
    return db


def _record(db: Database, game: str, score: int, detail: int, seed: int = 1) -> store.ScoreRow:
    return store.record_score(db, game=game, score=score, detail=detail, seed=seed, seeded=True)


def test_the_migration_lives_in_the_arcade_namespace_only():
    store.register_migration()
    assert storage.MIGRATIONS["arcade"] == (store._arcade_v1,)
    assert store._arcade_v1 not in storage.MIGRATIONS["core"]
    assert len(storage.MIGRATIONS["core"]) == 1
    for name in ("tube", "ai", "music", "monitor", "hacker", "files"):
        assert storage.MIGRATIONS[name] == (), f"{name} must stay untouched"


def test_an_empty_table_reads_as_empty_then_round_trips(database):
    assert store.top_scores(database) == []
    row = _record(database, "snake", 120, 15, seed=42)
    assert row.id == 1 and row.game == "snake" and row.score == 120
    assert row.detail == 15 and row.detail_label == "length"
    assert row.seeded is True and row.seed_value == "42"
    assert row.created_at.endswith("+00:00"), "stored in UTC, ISO 8601"
    assert [r.id for r in store.top_scores(database)] == [row.id]


def test_scores_sort_highest_first_and_newest_first_inside_a_tie(database):
    _record(database, "snake", 100, 10)
    _record(database, "snake", 300, 30)
    _record(database, "tetris", 300, 4)
    _record(database, "snake", 200, 20)
    rows = store.top_scores(database)
    assert [row.score for row in rows] == [300, 300, 200, 100]
    assert [row.game for row in rows][:2] == ["tetris", "snake"], "newest first inside a tie"
    assert {row.game for row in store.top_scores(database, game="snake")} == {"snake"}
    assert len(store.top_scores(database, limit=2)) == 2
    assert len(store.top_scores(database, limit=0)) == 4, "0 means every row"
    assert store.best_score(database, "tetris").score == 300


def test_clearing_can_be_scoped_to_one_game(database):
    _record(database, "snake", 10, 3)
    _record(database, "tetris", 20, 1)
    assert store.counts(database) == {"snake": 1, "tetris": 1}
    assert store.clear_scores(database, game="snake") == 1
    assert [row.game for row in store.top_scores(database)] == ["tetris"]
    assert store.clear_scores(database) == 1
    assert store.counts(database) == {}


@pytest.mark.parametrize("bad", ["pong", "Snake", "snake "])
def test_an_unknown_game_name_is_a_usage_error(database, bad):
    with pytest.raises(store.ArcadeUsage) as caught:
        store.top_scores(database, game=bad)
    assert caught.value.exit_code == EXIT_USAGE
    with pytest.raises(store.ArcadeUsage):
        store.record_score(database, game=bad, score=1, detail=1, seed=1, seeded=False)


def test_a_negative_limit_is_refused_before_any_query(database):
    with pytest.raises(store.ArcadeUsage, match="negative"):
        store.top_scores(database, limit=-1)


def test_the_schema_is_idempotent_and_creates_only_our_table(database):
    assert store.ensure_schema(database) == [], "a second call applies nothing"
    with database.connect() as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert store.TABLE in names
    assert "levix_command_log" not in names, "the arcade namespace must not build core's table"


# ---------------------------------------------------------------------------------
# The manifest and lazy loading (HARD RULE 1)
# ---------------------------------------------------------------------------------


def test_manifest_declares_the_packaged_contract():
    assert MANIFEST.name == "game"
    assert MANIFEST.title == "Arcade"
    assert MANIFEST.cli_path == "levix.modules.arcade.cli:build_app"
    assert MANIFEST.command_names() == ("snake", "tetris", "scores")
    assert MANIFEST.requirements == () and MANIFEST.extras == (), "textual is a core dependency"
    assert MANIFEST.permissions == frozenset()
    assert MANIFEST.ui.mode == "suspend" and MANIFEST.ui.argv == ("game", "snake")
    assert MANIFEST.documentation == "docs/modules/ARCADE.md"


def _child(tmp_path, *statements: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "LEVIX_HOME": str(tmp_path / "child-home"),
        "LEVIX_LOGGING_FILE_ENABLED": "false",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", "import sys\n" + "\n".join(statements)],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        env=env,
    )


def test_importing_the_manifest_pulls_in_nothing_heavy(tmp_path):
    completed = _child(
        tmp_path,
        "import levix.modules.arcade as m",
        "heavy = [x for x in ('textual', 'rich', 'typer', 'psutil', 'yt_dlp') if x in sys.modules]",
        "print(len(m.MANIFEST.commands), m.MANIFEST.requirements, heavy)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "3 () []"


@pytest.mark.parametrize(
    ("argv", "statement"),
    [(["game", "-h"], "code = main(['game','-h'])"),
     (["game", "scores"], "code = main(['game','scores'])")],
    ids=["help", "scores"],
)
def test_the_screen_is_not_imported_by_help_or_scores(tmp_path, argv, statement):
    completed = _child(
        tmp_path,
        "from levix.main import main",
        statement,
        "print(code, 'textual' in sys.modules)",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0 False", argv


# ---------------------------------------------------------------------------------
# The command surface, through the real entry point
# ---------------------------------------------------------------------------------


def test_module_help_lists_every_command(run_cli, capsys):
    assert run_cli("game", "-h") == 0
    text = both(capsys.readouterr())
    for name in MANIFEST.command_names():
        assert name in text
    assert "Traceback" not in text


def test_scores_on_an_empty_profile_says_so(run_cli, capsys):
    assert run_cli("game", "scores") == 0
    text = both(capsys.readouterr())
    assert "no scores yet" in text and "levix game" in text


def test_snake_auto_play_writes_a_real_row(run_cli, capsys):
    assert run_cli("game", "snake", "--seed", "7", "--auto", "150") == 0
    text = both(capsys.readouterr())
    assert "stored row" in text and "tick(s) played" in text
    capsys.readouterr()
    assert run_cli("game", "scores") == 0
    listing = both(capsys.readouterr())
    assert "snake" in listing and "--seed 7" in listing


def test_tetris_auto_play_writes_a_real_row(run_cli, capsys):
    assert run_cli("game", "tetris", "--seed", "7", "--auto", "30") == 0
    text = both(capsys.readouterr())
    assert "stored row" in text and "piece(s) placed" in text
    capsys.readouterr()
    assert run_cli("game", "scores", "--game", "tetris") == 0
    listing = both(capsys.readouterr())
    assert "tetris" in listing and "no scores yet" not in listing


def test_an_auto_game_is_reproducible_and_an_unpinned_one_still_records_its_seed(
    run_cli, capsys
):
    def signature() -> str:
        text = both(capsys.readouterr())
        return next(line for line in text.splitlines() if line.startswith("score "))

    assert run_cli("game", "tetris", "--seed", "19", "--auto", "25") == 0
    first = signature()
    assert run_cli("game", "tetris", "--seed", "19", "--auto", "25") == 0
    assert signature() == first, "the same seed must score the same"
    assert run_cli("game", "snake", "--auto", "40") == 0
    assert "seed" in both(capsys.readouterr()), "an unseeded run still stores its seed"


def test_a_clear_needs_the_typed_word_and_yes_cannot_supply_it(run_cli, capsys):
    assert run_cli("game", "snake", "--seed", "5", "--auto", "60") == 0
    capsys.readouterr()
    assert run_cli("game", "scores", "--clear") == EXIT_CANCELLED
    assert "clear arcade scores" in both(capsys.readouterr())
    assert run_cli("game", "scores", "--clear", "--yes") == EXIT_CANCELLED
    assert "--yes cannot authorize" in both(capsys.readouterr())
    capsys.readouterr()
    assert run_cli("game", "scores") == 0
    assert "no scores yet" not in both(capsys.readouterr()), "a refused clear deletes nothing"


@pytest.mark.parametrize("game", ["snake", "tetris"])
def test_a_screen_refuses_a_piped_stdout_and_points_at_auto(run_cli, capsys, game):
    assert run_cli("game", game) == EXIT_RUNTIME
    text = both(capsys.readouterr())
    assert "needs a real terminal" in text and "--auto" in text
    assert "Traceback" not in text


def test_bad_requests_are_usage_errors(run_cli, capsys):
    assert run_cli("game", "scores", "--game", "pong") == EXIT_USAGE
    assert "unknown arcade game" in both(capsys.readouterr())
    assert run_cli("game", "snake", "--auto", "-1") == EXIT_USAGE
    assert run_cli("game", "snake", "--cols", "3") == EXIT_USAGE
    assert "at least" in both(capsys.readouterr())
    assert run_cli("game", "frobnicate") == EXIT_UNKNOWN_MODULE
    assert "unknown command" in both(capsys.readouterr())
    assert "Traceback" not in both(capsys.readouterr())


# ---------------------------------------------------------------------------------
# The screens (integration: Textual needs an event loop)
# ---------------------------------------------------------------------------------


def _drive(app, steps) -> None:
    """Run one Textual scenario in a fresh loop; run_test re-raises app errors."""

    async def main() -> None:
        async with app.run_test(headless=True, size=(60, 30)) as pilot:
            await steps(app, pilot)

    asyncio.run(main())


@pytest.mark.integration
def test_the_snake_screen_steers_on_a_key_redraws_and_settles():
    from textual.widgets import Static

    from levix.modules.arcade.screens import SnakeApp

    stored: list[tuple] = []
    app = SnakeApp(
        cols=12, rows=8, seed=7, interval=0.02, on_finish=lambda *row: stored.append(row)
    )

    async def go(app, pilot):
        def board() -> str:
            return str(app.query_one("#board", Static).content)

        await pilot.pause()
        before = board()
        assert "+------------+" in before, "a bordered grid is on screen"
        assert app.state.direction == "right"

        await pilot.press("up")
        assert app.state.direction == "up", "the key reached the rule"
        for _ in range(80):
            await pilot.pause(0.01)
            if board() != before:
                break
        assert board() != before, "the grid the player sees must change"

        for _ in range(400):
            await pilot.pause(0.01)
            if not app.state.alive:
                break
        assert not app.state.alive, "an unsteered snake reaches the wall"
        assert "GAME OVER" in board()
        assert len(stored) == 1, "a game stores exactly one row"
        game, score, detail, seed = stored[0]
        assert (game, seed) == ("snake", 7), "the screen stores under its own game and seed"
        assert detail == snake_rules.START_LENGTH + score // snake_rules.FOOD_POINTS
        assert score >= 0

        await pilot.press("r")
        await pilot.pause()
        assert app.state.alive and app.state.direction == "right", "r starts a new round"
        await pilot.press("q")
        await pilot.pause()

    _drive(app, go)
    assert app._exception is None


@pytest.mark.integration
def test_the_tetris_screen_places_a_piece_with_space():
    from textual.widgets import Static

    from levix.modules.arcade.screens import TetrisApp

    stored: list[tuple] = []
    app = TetrisApp(seed=3, speed=1.0, on_finish=lambda *row: stored.append(row))

    async def go(app, pilot):
        def board() -> str:
            return str(app.query_one("#board", Static).content)

        await pilot.pause()
        assert "score 0" in board()
        await pilot.press("space")
        await pilot.pause()
        assert app.state.pieces == 1, "one key, one placed piece"
        assert app.state.score > 0, "a hard drop pays for the cells it fell"
        before = board()
        await pilot.press("left")
        await pilot.pause()
        assert board() != before or app.state.x <= 0
        await pilot.press("q")
        await pilot.pause()

    _drive(app, go)
    assert app._exception is None
    assert stored == [], "a game that never ended stores nothing"

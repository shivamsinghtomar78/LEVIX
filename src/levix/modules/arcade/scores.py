"""High scores in LEVIX's shared SQLite database, under the `arcade` migration namespace.

Two things live here and nowhere else: the schema for `levix_arcade_score`, and the
read/write helpers over it. Both games reach the database through `record` only, so
the Textual screen, the `--auto` player and the `scores` command all store exactly the
same shape of row.

The migration is *registered* rather than edited into core: `levix.storage.MIGRATIONS`
already reserves an empty `arcade` slot, and this module fills it at import time
(`register_migration`). `levix.database.apply_migrations(("arcade",))` then creates the
table on first use and nothing after that. No other namespace is touched.

Column meaning, because `detail` is deliberately generic:
  * `snake` stores the final snake length in `detail`.
  * `tetris` stores the number of cleared lines in `detail`.
  * `seeded` is 1 when the run used `--seed`, i.e. when it is reproducible; the seed
    itself is kept as text so a huge or negative value survives exactly.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from levix import storage
from levix.errors import EXIT_USAGE, LevixError

if TYPE_CHECKING:
    from levix.storage import Database

NAMESPACE = "arcade"
TABLE = "levix_arcade_score"
GAMES = ("snake", "tetris")
DETAIL_LABEL = {"snake": "length", "tetris": "lines"}


class ArcadeError(LevixError):
    """The game could not be run here (no terminal, bad board size). Exit 1."""


class ArcadeUsage(LevixError):
    """The request itself was wrong: an unknown game, a negative limit. Exit 2."""

    exit_code = EXIT_USAGE


def _arcade_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id INTEGER PRIMARY KEY,
            game TEXT NOT NULL,
            score INTEGER NOT NULL,
            detail INTEGER NOT NULL DEFAULT 0,
            seeded INTEGER NOT NULL DEFAULT 0,
            seed_value TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_arcade_score_game_score
            ON {TABLE} (game, score DESC, id DESC);
        """
    )


def register_migration() -> None:
    """Put this module's migration into the reserved `arcade` namespace slot."""
    if _arcade_v1 not in storage.MIGRATIONS.get(NAMESPACE, ()):
        storage.MIGRATIONS[NAMESPACE] = (
            *storage.MIGRATIONS.get(NAMESPACE, ()),
            _arcade_v1,
        )


def ensure_schema(database: Database) -> list[str]:
    register_migration()
    return database.apply_migrations((NAMESPACE,))


def check_game(name: str) -> str:
    if name not in GAMES:
        msg = f"unknown arcade game {name!r}; there is only {', '.join(GAMES)}"
        raise ArcadeUsage(msg)
    return name


def entropy_seed() -> int:
    """A seed for a run the user did not pin.

    It is stored with the score, so even an unseeded game can be replayed exactly by
    pasting the number back into `--seed`. Determinism is never lost by default, only
    left up to the player to ask for.
    """
    return random.SystemRandom().randrange(1, 2**31 - 1)


def game_rng(seed: int) -> random.Random:
    """The single place a game builds its RNG.

    Mersenne Twister is exactly right here: the requirement is that a seed replays a
    game, not that the sequence be unpredictable. The S311 warning about cryptography
    is answered by that distinction rather than by hiding it.
    """
    return random.Random(seed)  # noqa: S311


@dataclass(frozen=True, slots=True)
class ScoreRow:
    id: int
    game: str
    score: int
    detail: int
    seeded: bool
    seed_value: str
    created_at: str

    @property
    def detail_label(self) -> str:
        return DETAIL_LABEL.get(self.game, "detail")


#: (game, score, detail, seed) -> ScoreRow. Both drivers of a game hand it this.
RecordFn = Callable[[str, int, int, int], ScoreRow]


def _to_row(record: sqlite3.Row) -> ScoreRow:
    return ScoreRow(
        id=record["id"],
        game=record["game"],
        score=record["score"],
        detail=record["detail"],
        seeded=bool(record["seeded"]),
        seed_value=record["seed_value"] or "",
        created_at=record["created_at"],
    )


def record_score(
    database: Database,
    *,
    game: str,
    score: int,
    detail: int,
    seed: int,
    seeded: bool,
) -> ScoreRow:
    """Store one finished game. The caller decides when a game is finished.

    `seed` is the seed actually used (so any run can be replayed), `seeded` says
    whether the user pinned it with `--seed`.
    """
    check_game(game)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with database.connect() as conn:
        cursor = conn.execute(
            f"INSERT INTO {TABLE} (game, score, detail, seeded, seed_value, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (game, int(score), int(detail), int(seeded), str(seed), now),
        )
        row = conn.execute(
            f"SELECT id, game, score, detail, seeded, seed_value, created_at"
            f" FROM {TABLE} WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _to_row(row)


def top_scores(database: Database, *, game: str | None = None, limit: int = 10) -> list[ScoreRow]:
    """Highest score first, newest first inside a tie. `limit` 0 means every row."""
    wanted = check_game(game) if game is not None else None
    if limit < 0:
        msg = f"--limit cannot be negative, got {limit}"
        raise ArcadeUsage(msg)
    sql = f"SELECT id, game, score, detail, seeded, seed_value, created_at FROM {TABLE}"
    params: list[object] = []
    if wanted is not None:
        sql += " WHERE game = ?"
        params.append(wanted)
    sql += " ORDER BY score DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with database.connect() as conn:
        return [_to_row(row) for row in conn.execute(sql, params)]


def best_score(database: Database, game: str) -> ScoreRow | None:
    rows = top_scores(database, game=check_game(game), limit=1)
    return rows[0] if rows else None


def clear_scores(database: Database, *, game: str | None = None) -> int:
    """Delete rows and return how many went. Confirmation is the caller's job."""
    wanted = check_game(game) if game is not None else None
    sql = f"DELETE FROM {TABLE}"
    params: tuple[object, ...] = ()
    if wanted is not None:
        sql += " WHERE game = ?"
        params = (wanted,)
    with database.connect() as conn:
        return conn.execute(sql, params).rowcount


def counts(database: Database) -> dict[str, int]:
    """Rows per game, so a refusal can say exactly what it is about to destroy."""
    with database.connect() as conn:
        rows = conn.execute(f"SELECT game, COUNT(*) AS n FROM {TABLE} GROUP BY game").fetchall()
    return {row["game"]: int(row["n"]) for row in rows}

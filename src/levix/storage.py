"""One SQLite file for all of LEVIX, with per-module table namespaces.

Why one database: the dashboard and a suspended module subprocess are two processes
that both touch command history. Two files would double the `SQLITE_BUSY` surface and
add another path to every caller. The tradeoff - a badly behaved plugin migration can
lock the shared file - is mitigated by WAL, a busy timeout, and namespaced tables.

Migrations are Python callables rather than bundled `.sql` files: they are
type-checked, importable, and do not turn a standalone build into a
data-files-bundling exercise.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

Migration = Callable[[sqlite3.Connection], None]

SCHEMA_TABLE = "_levix_schema"


def _core_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS levix_command_log (
            id INTEGER PRIMARY KEY,
            argv TEXT NOT NULL,
            module TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_command_log_ts ON levix_command_log (ts DESC);
        """
    )


MIGRATIONS: dict[str, tuple[Migration, ...]] = {
    "core": (_core_v1,),
    "arcade": (),
    "tube": (),
    "ai": (),
    "music": (),
    "monitor": (),
    "hacker": (),
    "files": (),
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        """Short-lived connection per call. Never cached: Textual workers each need
        their own, and sqlite3 forbids sharing across threads by default."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    def apply_migrations(self, namespaces: Iterable[str] = ()) -> list[str]:
        """Idempotent. Returns the (namespace, version) pairs applied this call."""
        wanted = dict.fromkeys(namespaces or MIGRATIONS)
        applied: list[str] = []
        with self.connect() as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
                        module TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        applied_at TEXT NOT NULL,
                        PRIMARY KEY (module, version)
                    )"""
            )
            for namespace in wanted:
                current = {
                    row["version"]
                    for row in conn.execute(
                        f"SELECT version FROM {SCHEMA_TABLE} WHERE module = ?", (namespace,)
                    )
                }
                for index, migrate in enumerate(MIGRATIONS.get(namespace, ()), start=1):
                    if index in current:
                        continue
                    migrate(conn)
                    conn.execute(
                        f"INSERT INTO {SCHEMA_TABLE} (module, version, applied_at) VALUES (?, ?, ?)",
                        (namespace, index, _now()),
                    )
                    applied.append(f"{namespace}:{index}")
        return applied

    def log_command(
        self, argv: tuple[str, ...], module: str, exit_code: int, duration_ms: float
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO levix_command_log (argv, module, exit_code, duration_ms, ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (" ".join(argv), module, exit_code, duration_ms, _now()),
            )

    def recent_commands(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT argv, module, exit_code, duration_ms, ts"
                    " FROM levix_command_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            )

    def prune_history(self, keep: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM levix_command_log WHERE id NOT IN"
                " (SELECT id FROM levix_command_log ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            return cur.rowcount

    def vacuum(self) -> None:
        with self.connect() as conn:
            conn.execute("VACUUM")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

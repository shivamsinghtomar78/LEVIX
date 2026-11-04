"""One shared SQLite file, namespaced migrations, and the history the dashboard reads."""

from __future__ import annotations

from levix import storage
from levix.storage import MIGRATIONS, SCHEMA_TABLE, Database, _core_v1


def test_the_command_log_exists_after_the_core_namespace_applies(tmp_path):
    db = Database(tmp_path / "levix.db")
    assert db.apply_migrations(("core",)) == ["core:1"]
    with db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(levix_command_log)")}
    assert columns == {"id", "argv", "module", "exit_code", "duration_ms", "ts"}


def test_migrations_are_idempotent(tmp_path):
    db = Database(tmp_path / "levix.db")
    db.apply_migrations(("core",))
    assert db.apply_migrations(("core",)) == [], "a second call must not re-run v1"
    assert db.apply_migrations(("core", "core")) == []


def test_an_unknown_namespace_is_not_a_secret_failure(tmp_path):
    db = Database(tmp_path / "levix.db")
    assert db.apply_migrations(("nonesuch",)) == []
    with db.connect() as conn:
        rows = list(conn.execute(f"SELECT * FROM {SCHEMA_TABLE} WHERE module = ?", ("nonesuch",)))
    assert rows == []


def test_every_namespace_is_declared_even_when_it_has_no_migration_yet():
    # A module must be able to add its first migration later without a collision, so the
    # empty tuple is a reserved slot rather than an oversight.
    assert {"core", "arcade", "tube", "ai", "music", "monitor", "hacker", "files"} <= set(
        MIGRATIONS
    )
    assert MIGRATIONS["core"] == (_core_v1,)


def test_a_module_registers_its_migration_into_its_reserved_slot(tmp_path):
    """The `arcade` slot starts empty and the module fills it on first use.

    Owning that hand-off matters: a migration that is written but never registered would
    leave its table missing with no error anywhere, and the game would fail at score time.
    """
    from levix.modules.arcade import scores

    db = Database(tmp_path / "levix.db")
    applied = scores.ensure_schema(db)
    assert storage.MIGRATIONS["arcade"], "the migration must be registered, not just defined"
    assert applied == ["arcade:1"]
    with db.connect() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert scores.TABLE in tables
    scores.register_migration()  # idempotent by design
    assert len(storage.MIGRATIONS["arcade"]) == 1


def test_history_round_trips_in_newest_first_order(tmp_path):
    db = Database(tmp_path / "levix.db")
    db.apply_migrations(("core",))
    for index in range(4):
        db.log_command(("monitor", "cpu", str(index)), "monitor", 0, 12.5 + index)
    rows = db.recent_commands(10)
    assert [row["argv"] for row in rows] == [
        "monitor cpu 3",
        "monitor cpu 2",
        "monitor cpu 1",
        "monitor cpu 0",
    ]
    assert rows[0]["exit_code"] == 0
    assert rows[0]["ts"].endswith(("+00:00", "Z")) or "+" in rows[0]["ts"]


def test_prune_keeps_the_newest_rows_and_reports_what_it_dropped(tmp_path):
    db = Database(tmp_path / "levix.db")
    db.apply_migrations(("core",))
    for index in range(10):
        db.log_command(("files", "ls", f"n{index}"), "files", 0, 1.0)
    assert db.prune_history(3) == 7
    assert len(db.recent_commands(50)) == 3
    assert db.recent_commands(1)[0]["argv"] == "files ls n9"
    assert db.prune_history(99) == 0, "keeping more than exists is not an error"


def test_the_shared_database_uses_wal_and_a_busy_timeout(tmp_path):
    """The dashboard and a suspended module are two processes on one file."""
    db = Database(tmp_path / "levix.db")
    db.apply_migrations(("core",))
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_a_connection_is_not_reused_across_calls(tmp_path):
    """sqlite3 forbids sharing a connection across threads by default, and Textual runs
    workers, so `connect()` must hand out a new one every time."""
    db = Database(tmp_path / "levix.db")
    seen = []
    for _ in range(2):
        with db.connect() as conn:
            seen.append(conn)
    assert seen[0] is not seen[1]


def test_vacuum_runs_on_the_shared_file(tmp_path):
    db = Database(tmp_path / "levix.db")
    db.apply_migrations(("core",))
    db.log_command(("doctor",), "doctor", 0, 3.0)
    db.vacuum()
    assert db.recent_commands(5)

"""LEVIX Arcade - Snake and Tetris in the terminal, with scores in LEVIX's database.

This package is imported by `levix --help` through the `game` entry point, so it must
stay pure data: no Textual, no Rich, no sqlite3. The screens live in `screens.py`
(only imported inside a command body) and the rules in `snake.py` / `tetris.py`, which
are pure functions of a state and an explicit RNG.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, UiSpec

MANIFEST = ModuleManifest(
    name="game",
    title="Arcade",
    summary="Snake and Tetris in a Textual screen, with high scores stored in SQLite.",
    cli_path="levix.modules.arcade.cli:build_app",
    commands=(
        CommandInfo("snake", "Snake: arrows or WASD, --auto N plays itself, --seed N replays."),
        CommandInfo("tetris", "Tetris: 10x20, line clears and levels, --auto N plays itself."),
        CommandInfo("scores", "High scores, highest first; --clear asks before it deletes."),
    ),
    version="",
    requirements=(),
    extras=(),
    capabilities=(),
    permissions=frozenset(),
    ui=UiSpec(mode="suspend", argv=("game", "snake")),
    documentation="docs/modules/ARCADE.md",
)

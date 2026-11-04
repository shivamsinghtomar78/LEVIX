# Arcade

`levix game` is the arcade module: **Snake and Tetris** in a Textual screen,
with high scores in LEVIX's shared SQLite database. Note the naming split: the
package is `src/levix/modules/arcade/`, the manifest name (and therefore the
command and the entry point) is `game`. There is no `core.py` - the rules are
`snake.py` and `tetris.py`, the store is `scores.py`, the Textual drivers are
`screens.py`, and only `cli.py` is the command surface.

Declared requirements and extras are **empty**: everything Arcade needs
(Textual, Rich, sqlite3, stdlib `random`) is already a core dependency, so no
exit-3 gate ever fires here. Permissions: the manifest declares none; the module
writes only to the shared database and reads only its own tables.

Framing: these are two classic block-and-pixel games. Nothing about the module
is cyber-offensive; the "cyber" aesthetic lives in the separate hacker module.
Arcade is entertainment and a worked example of a Textual-backed module.

## Architecture in one paragraph

All rules are pure functions of an immutable state plus an explicit
`random.Random`, so a seed plus a move sequence replays exactly; the interactive
screen and `--auto` run **the identical functions**, which is what lets a full
game be proven on a machine with no TTY (the shell this module was written in).
`screens.py` is imported only inside the two screen helpers, so `levix game -h`
and `levix game scores` never construct a widget, and every rendered glyph is
7-bit ASCII (`test_every_rendered_character_is_7_bit`) because Textual's writer
crashes on box-drawing characters on a cp1252 Windows console.

## Commands

### `levix game snake [--seed N] [--auto N] [--speed X] [--cols C] [--rows R]`

Snake: arrows or WASD steer, `p` pauses, `r` restarts, `q`/Esc quits.

| Flag | Default | Meaning |
|---|---|---|
| `--seed N` | unset | Pin the RNG: the same seed and moves replay the same game. Unpinned runs still draw a seed from `random.SystemRandom()` and **store it**, so any run can be replayed by pasting it back |
| `--auto N` | `0` | Play N ticks headlessly with the built-in auto-player and exit (0 = interactive screen). Capped at 100000; negative is exit 2 |
| `--speed X` | `arcade.speed` (default 1.0) | Tick-rate multiplier, clamped 0.25 (slow) to 4.0 (fast); tick seconds = 0.18 / speed |
| `--cols`, `--rows` | 24 x 12 | Board size; minimum 6x5, maximum 120x60, violations exit 2 |

Rules kept: walls kill (no wrap), one food at a time on a sorted free cell via
seeded `rng.choice` (placement never depends on set iteration order), each food
is worth 10 points and grows the snake by one, a 180-degree turn is ignored
rather than fatal, and there is no speed ramp inside a game.

### `levix game tetris [--seed N] [--auto N] [--speed X]`

Tetris on the standard 10x20 field: left/right move, up (or x) rotates, down
softens, space hard-drops, `p`/`r`/`q` as in snake. `--auto N` places N pieces
headlessly with the rule-level auto-player. `--seed` pins the 7-bag order and
the auto-player. No board-size flags - the field is fixed.

Scoring kept classic: line clears 100/300/500/800 x level, level = 1 + lines
// 10, gravity interval = 0.8 s / speed x 0.85^(level-1), floor 0.05 s, soft
drop 1 point per cell, hard drop 2. Simplified on purpose (also declared in the
module docstring): clockwise-only rotation, no hold, no ghost piece, no lock
delay, no T-spin/combo/back-to-back, six plain wall-kick offsets instead of SRS
tables, and a blocked spawn at row 0 is the game-over condition.

### `levix game scores [--game snake|tetris] [--limit N] [--clear] [--yes]`

High scores, highest first and newest first inside a tie. `--limit` defaults to
20 (0 = every row); negative exits 2. Columns: rank, game, score, detail
(length for snake, lines for tetris), "replay with" (`--seed N` for every
stored run), when (UTC). Empty table prints the suggestion to play, interactively
or with `--auto 40`. An unknown `--game` name is exit 2 ("unknown arcade game
...; there is only snake, tetris").

**`--clear`**: destructive, so it goes through the shared
`levix.approve.require_approval` gate with `prompt_word="DELETE"`. You must type
DELETE at the prompt. `--yes`/`-y` is accepted and *ignored by design* - it
prints "--yes cannot authorize a destructive action; confirming interactive."
and prompts anyway; nothing in the refusal ever suggests using `--yes` to
bypass it. With no terminal to confirm in (piped stdin) it refuses at exit **6**
having removed nothing. The summary shown before confirming names exactly what
will be destroyed (row counts per game), and `--game snake --clear` scopes the
deletion. A cleared deletion is logged at warning level.

## Data written

One table, `levix_arcade_score` (`id, game, score, detail, seeded, seed_value,
created_at`), in the shared database `levix.db`. `detail` is deliberately
generic: snake stores final length, tetris stores cleared lines. The seed is
stored as text so huge or negative values survive exactly; `seeded` marks runs
the user pinned.

The `arcade` namespace in `storage.MIGRATIONS` **ships empty** (`"arcade": ()`)
and is filled at runtime by `scores.register_migration()` - the same
register-then-apply pattern as music, keeping `_levix_schema` truthful without
core knowing about module tables. `ensure_schema` runs through
`apply_migrations(("arcade",))`, is idempotent, and touches no other namespace.
Beyond the score rows and the universal command-history log, Arcade writes
nothing.

## Non-TTY behaviour

A screen with piped stdout exits **1** (`ArcadeError`, "needs a real terminal
(stdout is not a tty)") with the hint to use `--auto N` - never a traceback.
`--auto` exists precisely so the games are fully exercisable headlessly, and the
dashboard entry (`UiSpec(mode="suspend", argv=("game","snake"))`) suspends the
dashboard and re-enters `levix game snake` in a child process, because one TTY
cannot host two Textual apps.

## Exit codes

| Code | Meaning here |
|---|---|
| 1 | Screen refused (no TTY) or unhandled runtime error |
| 2 | Usage: negative/too-large `--auto`, board outside 6x5..120x60, unknown `--game`, negative `--limit` |
| 4 | Unknown command (`levix game frobnicate`) |
| 6 | `--clear` declined, or no terminal to confirm in |
| 130 | Ctrl+C |

## Tests

`tests/modules/test_arcade.py` - 39 test functions, 43 collected cases on Windows.
Covered: snake rules (start state,
step, eating +10/+1 length, wall and self death with the tail-vacation
exception, ignored reversal, same-seed-same-food determinism, auto-player
length matching score, minimum board, tick rate follows speed); tetris rules
(seven pieces x four states, seeded 7-bag, wall clamp, rotation never inside a
block, the classic line-score table on constructed boards, level multiplier and
speed change, spawn-blocked game over, hard-drop 2/cell); every rendered
character 7-bit; the scores store (arcade-namespace-only migration, idempotent
schema creating only its table, round trips, ordering, scoped clear, unknown
game, negative limit); the CLI (`scores` empty message, snake/tetris `--auto`
writing real rows, seed reproducibility and unpinned runs recording their seed,
`--clear` needing the typed word with `--yes` refused and deleting nothing on
refusal, piped-stdout screen refusal pointing at `--auto`, usage errors,
unknown module); manifest contract; subprocess proofs that importing the
manifest pulls in nothing heavy and that help/scores never import `screens`.
Two `@pytest.mark.integration` tests drive the real Textual apps headlessly
(`run_test`, steer/redraw/settle for snake, space-places-a-piece for tetris).
Not covered by tests: play on a physical terminal with real keypress timing, and
the dashboard's suspend launch path end-to-end (it is covered only as far as the
manifest's `UiSpec`).

## Known gaps

1. **Nobody has played these games with real keys.** Every assertion about the screens comes
   from Textual's Pilot (`run_test(headless=True)`), which delivers key events without a
   terminal, a keyboard repeat rate or a renderer. `require_terminal` refuses piped stdout at
   exit 1, so the interactive path is deliberately the least-tested one, and the ASCII-only
   glyph rule (`test_every_rendered_character_is_7_bit`) exists because Textual's writer
   crashed on box-drawing characters on this machine's cp1252 console - a real terminal with a
   different font has not been checked.
2. **The dashboard handoff is unproven.** `UiSpec(mode="suspend", argv=("game","snake"))` is
   asserted as data; the actual release-and-relaunch of the terminal has never been watched.
3. **Tetris is simplified on purpose, and the simplifications are user-visible.** Per
   `src/levix/modules/arcade/tetris.py:16-22`: rotation is clockwise only (no 180), there is
   no hold piece and no ghost piece, no lock delay, six plain wall-kick offsets
   `(0,0) (-1,0) (1,0) (-2,0) (2,0) (0,-1)` instead of SRS tables, and no T-spin, combo or
   back-to-back scoring. A player used to the modern guideline will feel all of it.
4. **`--speed` outside the schema range is clamped, not questioned.** `_speed`
   (`src/levix/modules/arcade/cli.py:103-107`) returns `min(4.0, max(0.25, value))`, so
   `--speed 10` runs at 4.0 and `--speed 0.05` at 0.25 with no note; `arcade.speed` in
   `config.SCHEMA` carries the same bounds (`config.py:110`), so the config file *does*
   reject an out-of-range value while the flag quietly adjusts it.
5. **Scores are local, anonymous and unverified.** `levix_arcade_score` has no player column
   and no integrity check; `--clear` is the only bulk operation and there is no export,
   import or per-seed replay command - `scores` prints `--seed N` so a run *can* be replayed
   by hand, but nothing does it for you.
6. **`--auto` is bounded to 100000 steps and the board to 120x60** (`MAX_AUTO` at
   `src/levix/modules/arcade/cli.py:41`, `MAX_COLS`/`MAX_ROWS` at `cli.py:38-39`; the refusals
   are at `cli.py:120-121` and `cli.py:133-134`), so Arcade cannot be used as a long-run
   benchmark harness; the caps exist so a typo cannot hang a session.

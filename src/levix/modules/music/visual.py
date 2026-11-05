"""The rules behind the spectrum, with no device, terminal or audio stream in them.

`band_edges`, `band_bins`, `levels_from`, `spectrum`, `apply_caps` and `frame_due` answer
"how tall is each column, and is it time to draw again". Every one of them is
numbers-in, numbers-out, which is what lets the suite assert that a 440 Hz tone lights the
band that contains 440 Hz on a machine with no sound card and no terminal - the same reason
`arcade` keeps `snake_rules` apart from its screens. Only `spectrum` asks for numpy.

`render` shapes levels into text and returns a `Text`; it never touches a `Console`, so the
only code that writes to a screen stays in `cli.py`.

numpy is imported inside `spectrum` alone, for the reason `core.py` gives in its header:
`levix music -h` has to work on a machine where `levix[music]` is not installed, so the
dependency gate reports exit 3 with the pip line instead of meeting an ImportError at
module scope.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from rich.text import Text

#: The two values `--visual` and `music.visual` accept. `off` keeps the one-line progress.
MODES = ("bar", "off")
DEFAULT_MODE = "bar"

#: Widest layout the renderer draws. A narrower terminal gets fewer, wider-spaced columns.
MAX_BANDS = 24
#: Rows of blocks per column. Seven leaves the source line and the frame count readable on a
#: 24-row terminal instead of letting the animation scroll them away.
HEIGHT = 7

#: Analysis window in frames: ~46 ms at 44.1 kHz, which is short enough that a drum still
#: reads as one hit and long enough that 40 Hz has more than a single period inside it.
WINDOW_FRAMES = 2048
LOW_HZ = 40.0
HIGH_HZ = 15000.0

#: Levels are mapped from dBFS onto 0.0-1.0 between these two bounds. The top of a column
#: is 0 dBFS, so full scale reaches the ceiling and nothing above it is invented; -54 dBFS
#: is the floor, which spends the seven rows on the range real program material moves in.
#: A wider floor (-80) measured every band of a full mix between 0.75 and 1.0, which is a
#: solid block, not a meter.
FLOOR_DB = -54.0
CEIL_DB = 0.0

#: Redraws per second, and how far a peak falls per redraw when nothing louder replaces it.
FPS = 24.0
CAP_DECAY = 0.05


def band_edges(bands: int, *, low: float = LOW_HZ, high: float = HIGH_HZ) -> tuple[float, ...]:
    """`bands + 1` log-spaced edges, so an octave costs the same width everywhere.

    Linear edges would spend a third of the columns above 10 kHz, where music has almost
    nothing, and give the kick drum one fat column. Log spacing is what makes the picture
    read the way a hardware EQ meter does.

    The exponent is `index / bands` on the whole ratio rather than a per-band step raised
    to `index`: the latter loses the last few femto-Hz to rounding, so the top edge is not
    the value that was asked for.
    """
    if bands < 1:
        msg = f"need at least one band, got {bands}"
        raise ValueError(msg)
    if not 0 < low < high <= 20000.0:
        msg = f"band range must satisfy 0 < low < high, got {low}-{high}"
        raise ValueError(msg)
    ratio = high / low
    return tuple(low * ratio ** (index / bands) for index in range(bands + 1))


def band_count(columns: int) -> int:
    """How many columns fit in `columns` characters: one glyph each, never wider."""
    return max(1, min(MAX_BANDS, columns))


def levels_from(
    peaks: Sequence[float],
    *,
    floor_db: float = FLOOR_DB,
    ceil_db: float = CEIL_DB,
) -> tuple[float, ...]:
    """Each band's loudest bin, mapped from dBFS onto 0.0-1.0.

    The peak of a band rather than its mean keeps a tonal source visible: averaged, a single
    440 Hz tone spreads across a wide top band and reads as nothing. A bin with no energy is
    clamped at the floor instead of reported as -inf.
    """
    span = ceil_db - floor_db
    if span <= 0:
        raise ValueError(f"ceil_db {ceil_db} must exceed floor_db {floor_db}")
    levels: list[float] = []
    for peak in peaks:
        db = 20.0 * math.log10(max(peak, 1e-12))
        levels.append(min(1.0, max(0.0, (db - floor_db) / span)))
    return tuple(levels)


@lru_cache(maxsize=8)
def band_bins(bands: int, frames: int, samplerate: int) -> tuple[tuple[int, int], ...]:
    """The half-open bin range each band reads, for a window of `frames` at `samplerate`.

    A band narrower than one FFT bin contains no bin *centre* at all, and with 24 columns
    over the 2048-frame window that is exactly what happens at the bottom end: 40-51 Hz and
    65-84 Hz each hold one bin or none, and 65.5-83.9 Hz holds none. That column would stay
    dark through a whole bass line, which looks broken and is. So a band reads every bin
    that comes within half a bin width of it - a bin can be seen by two or three low bands
    at once, the way an analogue filter with a slope would.

    Cached because it depends on nothing but these three numbers, and the alternative is a
    Python scan of ~1000 bins inside the audio callback for every drawn frame.
    """
    if frames < 1 or samplerate <= 0:
        return ()
    step = samplerate / frames
    edges = band_edges(bands, high=min(HIGH_HZ, samplerate / 2.0))
    count = frames // 2 + 1
    plan: list[tuple[int, int]] = []
    start = 0
    for index in range(bands):
        low = edges[index] - step / 2.0
        high = edges[index + 1] + step / 2.0
        while start < count and start * step < low:
            start += 1
        stop = start
        while stop < count and stop * step < high:
            stop += 1
        plan.append((start, stop))
    return tuple(plan)


def spectrum(
    window: np.ndarray,
    samplerate: int,
    *,
    bands: int,
    floor_db: float = FLOOR_DB,
    ceil_db: float = CEIL_DB,
) -> tuple[float, ...]:
    """Band levels for the window of samples that is about to be heard.

    Channels are averaged before the transform: the picture is one meter, not two, so a
    file with the same part in both channels cannot look twice as loud as a mono one.
    Averaging is also what makes a phase-inverted channel pair read as silence - the
    trade is one stable meter for a per-channel one. The top edge never claims a frequency
    the rate cannot carry, so an 8 kHz source gets its whole span inside the bands it
    actually has.
    """
    import numpy as np

    data = np.asarray(window, dtype=np.float64)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if data.ndim != 1 or data.size == 0 or samplerate <= 0:
        return (0.0,) * bands
    nyquist = samplerate / 2.0
    if nyquist <= LOW_HZ:
        return (0.0,) * bands
    plan = band_bins(bands, data.size, samplerate)
    magnitudes = np.abs(np.fft.rfft(data)) / (data.size / 2.0)
    peaks = [float(magnitudes[start:stop].max()) if stop > start else 0.0 for start, stop in plan]
    return levels_from(peaks, floor_db=floor_db, ceil_db=ceil_db)


def apply_caps(
    levels: Sequence[float], caps: Sequence[float], *, decay: float = CAP_DECAY
) -> tuple[float, ...]:
    """Peak-hold: a column's cap rises at once and falls `decay` per redraw.

    The result stays inside 0.0-1.0, so a column that has decayed past silence reads as
    empty rather than as a negative number the row maths has to forgive.
    """
    if len(levels) != len(caps):
        msg = f"{len(levels)} levels cannot update {len(caps)} caps"
        raise ValueError(msg)
    return tuple(
        min(1.0, max(0.0, max(level, cap - decay))) for level, cap in zip(levels, caps, strict=True)
    )


def bar_rows(level: float, height: int = HEIGHT) -> int:
    """Filled rows for one column; 0.0 is empty and 1.0 is the whole height."""
    return max(0, min(height, round(level * height)))


def frame_due(now: float, last: float, *, fps: float = FPS) -> bool:
    """Whether a redraw belongs at `now`, given the last one happened at `last`.

    The first frame always draws (`last == 0.0` is "never"), and the comparison is written
    so a clock that has not moved produces exactly one frame rather than a busy loop.
    """
    if last <= 0.0:
        return True
    return (now - last) * fps >= 1.0


def render(
    levels: Sequence[float],
    caps: Sequence[float],
    *,
    glyphs: dict[str, str],
    height: int = HEIGHT,
) -> Text:
    """The meter as `height` lines of text, top line first.

    Blocks come from `terminal.active_glyphs()` because a cp1252 Windows console raises
    `UnicodeEncodeError` inside Rich's writer on U+2588, and the whole point of this frame
    is to survive the console it is drawn on. Colour is per row, not per column: that is
    what makes a bar look like it is reaching for the top. `NO_COLOR` is not this function's
    business - the styles are markup, and the `Console` that prints them decides.
    """
    from rich.text import Text

    rows: list[Text] = []
    for row in range(height):  # row 0 is the top of the meter
        line = Text()
        filled_above = height - row - 1  # rows a column of that height would fill
        for index, level in enumerate(levels):
            body = bar_rows(level, height)
            cap = bar_rows(caps[index], height)
            if body > filled_above:
                line.append(glyphs["block"], style=_row_style(filled_above, height))
            elif cap - 1 == filled_above:
                line.append(glyphs["shade"], style="dim")
            else:
                line.append(" ")
        rows.append(line)
    return Text("\n").join(rows)


def _row_style(from_top: int, height: int) -> str:
    """Green near the bottom, yellow in the middle, red at the top."""
    position = from_top / max(1, height - 1)
    if position >= 0.85:
        return "bold red"
    if position >= 0.55:
        return "yellow"
    return "green"

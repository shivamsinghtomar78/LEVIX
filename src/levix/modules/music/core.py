"""Native audio: decode with libsndfile, play through PortAudio, never via ffmpeg.

Two rules shape the file. `play_samples` is the only function that opens a stream and
the only one that imports `sounddevice`, so a test can replace that single name and
drive every command without touching hardware. Decoding is libsndfile's job: it ships
inside `soundfile`, and 1.2 reads WAV, FLAC, OGG and MP3 by itself, so nothing here
shells out to ffmpeg - a codec it does not carry is reported as missing, never faked.
"""

from __future__ import annotations

import math
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ... import storage as levix_storage
from ...errors import EXIT_TOOL_FAILED, EXIT_USAGE, ConfigError, LevixError
from ...storage import Database

if TYPE_CHECKING:
    import sqlite3

    # numpy is part of `levix[music]`. It is imported inside the four functions that
    # actually move samples, so that `levix music -h` works on a machine without the
    # extra and the gate can report exit 3 with the pip line rather than crashing.
    import numpy as np

NAMESPACE = "music"
TABLE = "music_playlist"
MIN_RATE = 8000
MAX_RATE = 192000
#: Suffixes `library` scans. Each decoded on the machine recorded in docs/modules/MUSIC.md.
SCAN_SUFFIXES = frozenset({".wav", ".flac", ".ogg", ".opus", ".mp3", ".aiff", ".aif", ".au"})
#: Containers whose codec the bundled libsndfile does not carry, named for the message.
MISSING_CODECS = {
    ".m4a": "MPEG-4 AAC",
    ".mp4": "MPEG-4",
    ".aac": "ADTS AAC",
    ".wma": "Windows Media Audio",
    ".mka": "Matroska audio",
    ".mkv": "Matroska",
    ".ape": "Monkey's Audio",
    ".mid": "MIDI",
    ".midi": "MIDI",
}
#: Subtypes that are compressed: worth saying out loud, since they still decode fine.
LOSSY_SUBTYPES = frozenset(
    {
        "ULAW",
        "ALAW",
        "IMA_ADPCM",
        "MS_ADPCM",
        "GSM610",
        "G721_32",
        "NMS_ADPCM_16",
        "NMS_ADPCM_24",
        "NMS_ADPCM_32",
        "MPEG_LAYER_I",
        "MPEG_LAYER_II",
        "MPEG_LAYER_III",
        "VORBIS",
        "OPUS",
    }
)
PCM_SUBTYPES = frozenset({"PCM_16", "PCM_24", "PCM_32", "PCM_S8", "PCM_U8", "FLOAT", "DOUBLE"})


class MusicError(LevixError):
    """A real failure that is nobody's bug: exit 1, one clean message."""


class RequestError(LevixError):
    """The file, directory or flag the user named cannot be used: exit 2."""

    exit_code = EXIT_USAGE


class BackendError(LevixError):
    """libsndfile or PortAudio refused the job: exit 7, the code for a failed tool."""

    exit_code = EXIT_TOOL_FAILED


class UnsupportedFormatError(BackendError):
    """The bundled decoder has no codec for this file.

    `detail` keeps libsndfile's own one-line reason, so a library scan can report the
    cause without repeating the whole sentence for every file.
    """

    def __init__(self, message: str, *, hint: str | None = None, detail: str = "") -> None:
        super().__init__(message, hint=hint)
        self.detail = detail


class AudioDeviceError(BackendError):
    """PortAudio could not open or drive an output stream."""


# ----------------------------------------------------------------------------------
# plain data
# ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AudioInfo:
    path: Path
    samplerate: int
    channels: int
    frames: int
    duration: float
    format: str
    subtype: str

    @property
    def codec_note(self) -> str:
        """One plain-language sentence about how this file decodes."""
        if self.subtype in PCM_SUBTYPES:
            return "uncompressed samples, decoded natively by libsndfile"
        if self.subtype in LOSSY_SUBTYPES:
            return (
                f"{self.subtype} is a compressed codec: libsndfile decodes it in this "
                "process, no external tool is called"
            )
        return f"{self.format}/{self.subtype or 'no subtype'} decoded by libsndfile as above"


@dataclass(frozen=True, slots=True)
class DeviceRow:
    index: int
    name: str
    host_api: str
    max_input: int
    max_output: int
    default_samplerate: float

    @property
    def role(self) -> str:
        if self.max_input and self.max_output:
            return "in+out"
        return "output" if self.max_output else ("input" if self.max_input else "unusable")


@dataclass(frozen=True, slots=True)
class DeviceTable:
    rows: tuple[DeviceRow, ...]
    default_input: int | None
    default_output: int | None

    def mark(self, row: DeviceRow) -> str:
        marks = [
            kind
            for kind, index in (("in", self.default_input), ("out", self.default_output))
            if row.index == index
        ]
        return "+".join(marks)

    def name_of(self, index: int | None) -> str:
        if index is None:
            return "none reported"
        return next(
            (f"{row.index} {safe_text(row.name)}" for row in self.rows if row.index == index),
            str(index),
        )

    def note(self) -> str:
        if not any(row.max_output for row in self.rows):
            return "no device with output channels: playback cannot start on this machine"
        if self.default_output is None:
            return "PortAudio reports no default output device; pass --device N from the list"
        return ""


@dataclass(frozen=True, slots=True)
class TrackRow:
    path: Path
    size_bytes: int
    samplerate: int
    channels: int
    duration: float
    format: str
    subtype: str


@dataclass(slots=True)
class ScanResult:
    root: Path
    tracks: list[TrackRow] = field(default_factory=list)
    unreadable: list[tuple[Path, str]] = field(default_factory=list)
    directories: int = 0
    files_examined: int = 0
    skipped_suffix: int = 0
    skipped_hidden: int = 0

    @property
    def total_duration(self) -> float:
        return sum(track.duration for track in self.tracks)

    def display(self, path: Path) -> str:
        """Relative to the scanned root, so a long shared prefix is not repeated."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def by_directory(self) -> list[tuple[Path, int, float]]:
        """(folder, track count, seconds), folders in path order, for the totals table."""
        grouped: dict[Path, list[TrackRow]] = {}
        for track in self.tracks:
            grouped.setdefault(track.path.parent, []).append(track)
        return [
            (folder, len(rows), sum(row.duration for row in rows))
            for folder, rows in sorted(grouped.items(), key=lambda item: str(item[0]).casefold())
        ]


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    id: int
    path: Path
    added_at: str

    @property
    def exists(self) -> bool:
        return self.path.is_file()


@dataclass(frozen=True, slots=True)
class AddResult:
    added: tuple[PlaylistEntry, ...]
    duplicate: tuple[str, ...]


# ----------------------------------------------------------------------------------
# decoding
# ----------------------------------------------------------------------------------


def decoder_version() -> str:
    """What is really doing the decoding, for the honesty line in `info`."""
    import soundfile as sf

    return f"soundfile {sf.__version__} / libsndfile {sf.__libsndfile_version__}"


def require_file(path: Path | str, *, label: str = "audio file") -> Path:
    resolved = Path(path).expanduser()
    if not resolved.exists():
        msg = f"{label} does not exist: {safe_name(resolved)}"
        raise RequestError(msg, hint="or run `levix music library` to list candidates")
    if resolved.is_dir():
        msg = f"{label} is a directory: {safe_name(resolved)}"
        raise RequestError(msg, hint="name one file, or use `levix music library` to find them")
    return resolved.resolve(strict=False)


def inspect_file(path: Path | str) -> AudioInfo:
    import soundfile as sf

    resolved = require_file(path)
    try:
        probe = sf.info(str(resolved))
    except sf.SoundFileError as exc:
        raise _refused(resolved, str(exc)) from exc
    return AudioInfo(
        path=resolved,
        samplerate=int(probe.samplerate),
        channels=int(probe.channels),
        frames=int(probe.frames),
        duration=duration_for(int(probe.frames), int(probe.samplerate)),
        format=probe.format or "?",
        subtype=probe.subtype or "",
    )


def _refused(path: Path, detail: str) -> UnsupportedFormatError:
    codec = MISSING_CODECS.get(path.suffix.lower())
    reason = (
        f"{safe_name(path)} is {codec}, which the bundled libsndfile does not carry"
        if codec
        else f"{safe_name(path)} is not audio libsndfile can read"
    )
    return UnsupportedFormatError(
        f"{reason}: {detail}",
        hint="re-encode to WAV, FLAC, OGG or MP3, which decode in-process; LEVIX never "
        "calls ffmpeg, so there is no fallback to enable",
        detail=detail,
    )


def load(path: Path | str, *, volume: float = 1.0) -> tuple[np.ndarray, int, AudioInfo]:
    """Decode to (frames, channels) float32 in [-1, 1] with `volume` already applied."""
    import soundfile as sf

    info = inspect_file(path)
    try:
        frames, rate = sf.read(str(info.path), dtype="float32", always_2d=True)
    except sf.SoundFileError as exc:
        raise _refused(info.path, str(exc)) from exc
    return apply_gain(frames, volume), int(rate), info


def apply_gain(frames: np.ndarray, volume: float) -> np.ndarray:
    """Scale, then clamp: 0.0 is silence, 1.0 passes through, and nothing wraps around."""
    import numpy as np

    scaled = np.asarray(frames, dtype=np.float64) * validate_volume(volume)
    return np.clip(scaled, -1.0, 1.0).astype(np.float32)


def validate_volume(raw: object) -> float:
    """music.volume and --volume share this gate, so a config value cannot shout past 1.0."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        msg = f"volume must be a number between 0.0 and 1.0, got {raw!r}"
        raise ConfigError(msg) from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        msg = f"volume must be between 0.0 and 1.0, got {value:g}"
        raise ConfigError(msg, hint="levix config set music.volume 0.8, or pass --volume 0.8")
    return value


def validate_rate(rate: object) -> int:
    try:
        value = int(float(rate))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        msg = f"sample rate must be a whole number of Hz, got {rate!r}"
        raise RequestError(msg) from exc
    if not MIN_RATE <= value <= MAX_RATE:
        msg = f"sample rate must be between {MIN_RATE} and {MAX_RATE} Hz, got {value}"
        raise RequestError(msg, hint="common rates: 8000, 22050, 32000, 44100, 48000, 96000")
    return value


def resample(frames: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Linear interpolation onto `target_rate`.

    Honest about the method: per-sample interpolation, not windowed sinc - transparent
    for playback, not for analysis. It exists because PortAudio does not resample what
    you hand it, so `--rate` would otherwise change the pitch instead of the speed.
    """
    source, target = int(source_rate), validate_rate(target_rate)
    if target == source:
        return frames
    import numpy as np

    data = np.asarray(frames, dtype=np.float64)
    if data.ndim != 2 or data.shape[0] == 0 or source <= 0:
        raise RequestError(f"cannot resample audio of shape {data.shape} from {source} Hz")
    length = max(1, round(data.shape[0] * target / source))
    grid = np.arange(data.shape[0], dtype=np.float64)
    positions = np.linspace(0.0, grid[-1], length, dtype=np.float64)
    columns = [np.interp(positions, grid, data[:, channel]) for channel in range(data.shape[1])]
    return np.asarray(columns, dtype=np.float32).T


def duration_for(frames: int, samplerate: int) -> float:
    return float(frames) / float(samplerate) if samplerate > 0 else float("nan")


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "unknown (no sample rate reported)"
    if seconds < 60:
        return f"{max(0.0, seconds):.1f}s"
    hours, rest = divmod(max(0, round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def progress_percent(written: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return max(0.0, min(100.0, 100.0 * written / total))


def safe_text(text: str) -> str:
    """Text this console can encode.

    Windows terminals are commonly cp1252, where a non-Latin name raises
    UnicodeEncodeError inside Rich's writer - a crash, not cosmetic damage. No path
    semantics are applied: a PortAudio device name holds backslashes that are content.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, "backslashreplace").decode(encoding)


def safe_name(path: Path | str) -> str:
    return safe_text(str(path))


# ----------------------------------------------------------------------------------
# the one hardware seam
# ----------------------------------------------------------------------------------


def play_samples(
    frames: np.ndarray,
    samplerate: int,
    *,
    device: int | None = None,
    blocksize: int = 0,
    on_block: Callable[[int, int], None] | None = None,
) -> int:
    """Play float frames on an output device and return how many were delivered.

    Every byte of sound in LEVIX leaves through here. The callback asks for however many
    frames PortAudio wants, so the arithmetic holds at any blocksize, and raising
    `CallbackStop` after the last sample ends the stream. The `with` block closes it on
    every path including Ctrl+C: an interrupted playback must not leave the device busy.
    """
    import numpy as np
    import sounddevice as sd

    data = np.ascontiguousarray(np.asarray(frames, dtype=np.float32))
    if data.ndim != 2 or data.shape[0] == 0 or data.shape[1] == 0:
        return 0
    rate = int(samplerate)
    if rate <= 0:
        raise RequestError(f"cannot play at {rate} Hz: the file reported no sample rate")
    total = data.shape[0]
    state = {"frames": 0, "done": False, "underflow": 0}

    def callback(outdata: np.ndarray, frames: int, time_info: object, status: object) -> None:
        if status is not None and getattr(status, "output_underflow", False):
            state["underflow"] += 1
        take = min(int(frames), total - state["frames"])
        if take > 0:
            outdata[:take] = data[state["frames"] : state["frames"] + take]
            state["frames"] += take
        if take < frames:
            outdata[take:] = 0.0
        if on_block is not None:
            on_block(state["frames"], total)
        if state["frames"] >= total:
            state["done"] = True
            raise sd.CallbackStop from None

    label = "the default output device" if device is None or device < 0 else f"device {device}"
    try:
        with sd.OutputStream(
            samplerate=rate,
            channels=data.shape[1],
            device=None if device is None or device < 0 else int(device),
            blocksize=max(0, int(blocksize)),
            dtype="float32",
            callback=callback,
        ) as stream:
            deadline = total / rate + 2.0
            started = time.perf_counter()
            while stream.active and not state["done"]:
                time.sleep(0.01)
                if time.perf_counter() - started > deadline:
                    raise AudioDeviceError(
                        f"the output stream stopped answering after {state['frames']} "
                        f"of {total} frames"
                    )
    except (KeyboardInterrupt, AudioDeviceError):
        raise
    except Exception as exc:
        raise AudioDeviceError(
            f"PortAudio could not play on {label}: {type(exc).__name__}: {exc}",
            hint="run `levix music devices` and pass a listed index with --device",
        ) from exc
    return int(state["frames"])


def list_devices() -> DeviceTable:
    """Every device PortAudio reports, including the ones it cannot use."""
    import sounddevice as sd

    try:
        raw = list(sd.query_devices())
        host_apis = tuple(str(api["name"]) for api in sd.query_hostapis())
        default = list(sd.default.device)
    except Exception as exc:
        raise AudioDeviceError(
            f"PortAudio could not list devices ({type(exc).__name__}: {exc})",
            hint="is another application holding the audio device exclusively?",
        ) from exc

    def slot(position: int) -> int | None:
        try:
            index = int(default[position])
        except (IndexError, TypeError, ValueError):
            return None
        return index if 0 <= index < len(raw) else None

    return DeviceTable(
        rows=tuple(
            DeviceRow(
                index=index,
                name=str(row["name"]),
                host_api=host_apis[row["hostapi"]] if row["hostapi"] < len(host_apis) else "?",
                max_input=int(row["max_input_channels"]),
                max_output=int(row["max_output_channels"]),
                default_samplerate=float(row["default_samplerate"]),
            )
            for index, row in enumerate(raw)
        ),
        default_input=slot(0),
        default_output=slot(1),
    )


# ----------------------------------------------------------------------------------
# library
# ----------------------------------------------------------------------------------


def library_root(configured: str, override: Path | None) -> Path | None:
    """Resolve the scan directory. None means "not configured", which is said out loud."""
    if override is not None:
        resolved = Path(override).expanduser()
        if not resolved.exists():
            raise RequestError(f"--root does not exist: {safe_name(resolved)}")
        if not resolved.is_dir():
            raise RequestError(
                f"--root is not a directory: {safe_name(resolved)}",
                hint="point --root at a folder of audio files",
            )
        return resolved.resolve(strict=False)
    text = (configured or "").strip()
    if not text:
        return None
    resolved = Path(text).expanduser()
    if not resolved.is_dir():
        msg = f"music.library_dir is not a readable directory: {safe_name(resolved)}"
        raise ConfigError(msg, hint="levix config set music.library_dir PATH, or pass --root DIR")
    return resolved.resolve(strict=False)


def scan_library(
    root: Path | str,
    *,
    suffixes: Iterable[str] | None = None,
    include_hidden: bool = False,
) -> ScanResult:
    """Walk `root` and ask libsndfile about every plausible audio file.

    Unreadable files are counted and named, never dropped silently: a truncated FLAC is
    information about the library, not a reason to stop scanning.
    """
    wanted = SCAN_SUFFIXES if suffixes is None else {f".{item.lstrip('.')}" for item in suffixes}
    base = Path(root).expanduser().resolve(strict=False)
    result = ScanResult(root=base)
    for folder, dirnames, filenames in os.walk(base):
        result.directories += 1
        dirnames[:] = sorted(dirnames)
        hidden_dirs = [name for name in dirnames if name.startswith(".")]
        result.skipped_hidden += len(hidden_dirs)
        if not include_hidden:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        here = Path(folder)
        for name in sorted(filenames):
            path = here / name
            hidden = name.startswith(".")
            result.skipped_hidden += int(hidden and not include_hidden)
            if hidden and not include_hidden:
                continue
            result.files_examined += 1
            if path.suffix.lower() not in wanted:
                result.skipped_suffix += 1
                continue
            try:
                info = inspect_file(path)
                size = path.stat().st_size
            except (LevixError, OSError) as exc:
                reason = getattr(exc, "detail", "") or (
                    exc.message if isinstance(exc, LevixError) else str(exc)
                )
                result.unreadable.append((path, reason))
                continue
            result.tracks.append(
                TrackRow(
                    path=info.path,
                    size_bytes=size,
                    samplerate=info.samplerate,
                    channels=info.channels,
                    duration=info.duration,
                    format=info.format,
                    subtype=info.subtype,
                )
            )
    return result


def human_bytes(value: int) -> str:
    """Binary units, the same reading as `levix monitor` and `levix files`."""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


# ----------------------------------------------------------------------------------
# playlist: the shared SQLite, in the "music" namespace
# ----------------------------------------------------------------------------------


def playlist_migration_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_{TABLE}_added ON {TABLE} (added_at);
        """
    )


def ensure_schema(database: Database) -> list[str]:
    """Register this module's migration, then apply it through the shared engine.

    `storage.MIGRATIONS` carries an empty `music` slot for exactly this: going through
    `apply_migrations` keeps `_levix_schema` truthful for `levix doctor` instead of
    letting a module run unrecorded DDL against the shared file. Idempotent.
    """
    registered = levix_storage.MIGRATIONS.get(NAMESPACE, ())
    if playlist_migration_v1 not in registered:
        levix_storage.MIGRATIONS[NAMESPACE] = (*registered, playlist_migration_v1)
    return database.apply_migrations((NAMESPACE,))


def _entry(row: sqlite3.Row) -> PlaylistEntry:
    return PlaylistEntry(id=int(row["id"]), path=Path(row["path"]), added_at=str(row["added_at"]))


def list_playlist(database: Database) -> tuple[PlaylistEntry, ...]:
    ensure_schema(database)
    with database.connect() as conn:
        return tuple(
            _entry(row)
            for row in conn.execute(f"SELECT id, path, added_at FROM {TABLE} ORDER BY id")
        )


def add_to_playlist(database: Database, paths: Sequence[Path | str]) -> AddResult:
    """Resolve every name first, then insert: a refused batch queues nothing at all."""
    ensure_schema(database)
    resolved = [require_file(path) for path in paths]
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    added: list[PlaylistEntry] = []
    duplicate: list[str] = []
    with database.connect() as conn:
        for path in resolved:
            known = conn.execute(f"SELECT id FROM {TABLE} WHERE path = ?", (str(path),)).fetchone()
            if known is not None:
                duplicate.append(safe_name(path))
                continue
            cursor = conn.execute(
                f"INSERT INTO {TABLE} (path, added_at) VALUES (?, ?)", (str(path), stamp)
            )
            added.append(PlaylistEntry(id=int(cursor.lastrowid or 0), path=path, added_at=stamp))
    return AddResult(added=tuple(added), duplicate=tuple(duplicate))


def remove_from_playlist(
    database: Database, ids: Sequence[int]
) -> tuple[tuple[PlaylistEntry, ...], tuple[int, ...]]:
    """Returns (removed rows, ids that were not in the queue) - a stale id is not fatal."""
    ensure_schema(database)
    removed: list[PlaylistEntry] = []
    missing: list[int] = []
    with database.connect() as conn:
        for wanted in ids:
            row = conn.execute(
                f"SELECT id, path, added_at FROM {TABLE} WHERE id = ?", (int(wanted),)
            ).fetchone()
            if row is None:
                missing.append(int(wanted))
                continue
            conn.execute(f"DELETE FROM {TABLE} WHERE id = ?", (int(wanted),))
            removed.append(_entry(row))
    return tuple(removed), tuple(missing)


def count_playlist(database: Database) -> int:
    ensure_schema(database)
    with database.connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])


def clear_playlist(database: Database) -> int:
    ensure_schema(database)
    with database.connect() as conn:
        return int(conn.execute(f"DELETE FROM {TABLE}").rowcount)

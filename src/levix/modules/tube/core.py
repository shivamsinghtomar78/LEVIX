"""Tube's media logic: every yt-dlp call, and the gates that keep failure honest.

Three rules shape this file.

1. `yt_dlp` is imported inside `_make_ydl` only, so `levix tube -h` never pays for it
   and the package stays importable when the extra is not installed.
2. Every yt-dlp object comes from that one seam, so tests substitute a stub instead of
   reaching for the network and the CLI above it stays the real one.
3. Unknown is reported as unknown. A field a site does not provide renders as "-",
   never as 0 and never as a guess.

Tube implements yt-dlp's own policy and nothing beyond it: no DRM or download-protection
circumvention, no cookie extraction, no account abuse.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import terminal
from ...errors import ConfigError, ExternalToolError, LevixError, ProviderError

CONVERTIBLE = ("mp3", "m4a", "opus", "vorbis", "ogg", "wav", "aac", "flac")
# `capabilities._player` probes this same order; the core cannot import a module to read
# this tuple, so the two lists stay in step by agreement, recorded in both places.
PLAYER_CANDIDATES = ("mpv", "ffplay", "vlc", "mplayer")

# A named format is expanded here, so the alias a user types and the selector yt-dlp
# receives are both ours to reason about. Without ffmpeg the alias resolves to the best
# *single file* the site offers: that download genuinely works, it is just not always
# the highest quality available.
ALIASES_WITH_FFMPEG = {"best": "bv*+ba/b", "video": "bv*+ba/b", "audio": "ba/b"}
ALIASES_SINGLE_FILE = {"best": "b", "video": "bv/b", "audio": "ba/b"}

# `bv*` / `ba*` mean "any video format, including ones that need merging".
_MERGE_STAR = re.compile(r"\b(?:bv|ba|b|v|a|w)\*")

FFMPEG_INSTALL_COMMANDS = {
    "win32": "winget install Gyan.FFmpeg",
    "darwin": "brew install ffmpeg",
    "cygwin": "winget install Gyan.FFmpeg",
}
FFMPEG_INSTALL_FALLBACK = "sudo apt install ffmpeg"


@dataclass(frozen=True, slots=True)
class FormatPlan:
    """What we will ask yt-dlp for, and whether that ask needs ffmpeg."""

    spec: str
    requires_ffmpeg: bool
    convert_to: str | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ProgressState:
    status: str
    downloaded_bytes: int
    total_bytes: int | None
    percent: float
    speed: float | None
    eta: float | None
    filename: str


@dataclass(frozen=True, slots=True)
class FormatRow:
    format_id: str
    extension: str
    resolution: str
    fps: str
    vcodec: str
    acodec: str
    bitrate: str
    size: str
    note: str


@dataclass(frozen=True, slots=True)
class MediaSummary:
    title: str
    media_id: str
    extractor: str
    webpage_url: str
    duration: float | None
    uploader: str
    resolution: str
    smallest: int | None
    largest: int | None
    entry_count: int | None
    rows: tuple[FormatRow, ...]


# ----------------------------------------------------------------------------------
# gates: ffmpeg and the player
# ----------------------------------------------------------------------------------


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def install_command_for(platform: str | None = None) -> str:
    return FFMPEG_INSTALL_COMMANDS.get(platform or sys.platform, FFMPEG_INSTALL_FALLBACK)


def plan_format(requested: str, *, has_ffmpeg: bool, convert_to: str | None = None) -> FormatPlan:
    wanted = (requested or "best").strip()
    alias = wanted.lower()
    if alias in ALIASES_WITH_FFMPEG:
        if has_ffmpeg:
            spec, note = ALIASES_WITH_FFMPEG[alias], ""
        else:
            spec = ALIASES_SINGLE_FILE[alias]
            note = (
                f"ffmpeg is not installed, so {alias!r} resolves to {spec!r}: the best "
                "single file this site offers instead of merged streams"
            )
            if alias == "video":
                note += " (video-only formats can carry no audio track)"
    else:
        # An explicit selector is taken literally. Rewriting a user's spec silently
        # would be worse than refusing it.
        spec, note = wanted, ""
    merging = "+" in spec or _MERGE_STAR.search(spec) is not None
    return FormatPlan(
        spec=spec, requires_ffmpeg=bool(merging or convert_to), convert_to=convert_to, note=note
    )


def single_file_plan() -> FormatPlan:
    """A player receives exactly one URL, so merging is never on the table for `play`."""
    return FormatPlan(spec="b", requires_ffmpeg=False)


def ensure_ffmpeg(plan: FormatPlan, *, has_ffmpeg: bool | None = None) -> None:
    """Refuse an ffmpeg-dependent request up front, with the command that fixes it."""
    available = bool(ffmpeg_path()) if has_ffmpeg is None else has_ffmpeg
    if not plan.requires_ffmpeg or available:
        return
    verb = (
        f"convert the audio to {plan.convert_to}"
        if plan.convert_to
        else "merge the separate video and audio streams"
    )
    install = install_command_for()
    raise ExternalToolError(
        f"this request needs ffmpeg to {verb}, and ffmpeg is not installed.\n"
        f"  install it with: {install}\n"
        "  then re-run the same command, or drop the requirement with a single-file "
        "format such as --format best",
        hint=install,
    )


def find_player(explicit: str = "") -> tuple[str | None, tuple[str, ...]]:
    """(path, names tried). Never guesses a location it did not find on PATH."""
    names = tuple(n for n in ((explicit,) if explicit else PLAYER_CANDIDATES) if n)
    for name in names:
        found = shutil.which(name)
        if found:
            return found, names
    return None, names


def player_command(player: str, url: str) -> list[str]:
    """An argument list, run with shell=False: no command string is ever re-parsed."""
    return [player, url]


def launch(argv: list[str]) -> int:
    try:
        return subprocess.run(list(argv), shell=False, check=False).returncode
    except OSError as exc:
        raise ExternalToolError(f"could not start {argv[0]}: {exc}") from exc


# ----------------------------------------------------------------------------------
# output directory
# ----------------------------------------------------------------------------------


def resolve_output_dir(flag_value: str, configured: str) -> tuple[Path, str]:
    """(directory, which layer chose it). `~` and %VARS% expand; blank falls back."""
    for raw, source in ((flag_value, "--output"), (configured, "tube.output_dir")):
        text = (raw or "").strip()
        if text:
            return Path(os.path.expandvars(text)).expanduser(), source
    return Path.home() / "Downloads", f"the built-in fallback ({Path.home()})"


def ensure_output_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"cannot use output directory {path}: {exc}") from exc
    return path


# ----------------------------------------------------------------------------------
# yt-dlp: the seam and the two calls that go through it
# ----------------------------------------------------------------------------------


def build_options(
    plan: FormatPlan,
    *,
    output_dir: Path | None = None,
    playlist: bool = False,
    allow_file_url: bool = False,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "format": plan.spec,
        "noplaylist": not playlist,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        # Existing files keep their bytes: yt-dlp reports "already downloaded" rather
        # than re-fetching, and `download` tells the user when that happened.
        "overwrites": False,
        "progress_hooks": [],
    }
    if output_dir is not None:
        options["paths"] = {"home": str(output_dir)}
        options["outtmpl"] = "%(title)s [%(id)s].%(ext)s"
    if plan.convert_to:
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": plan.convert_to,
                "preferredquality": "0",
            }
        ]
    if allow_file_url:
        # yt-dlp disables file:// by default. It stays opt-in here for the same reason
        # it is opt-in there: a URL from somewhere else should not read this disk.
        options["enable_file_urls"] = True
    return options


def _make_ydl(options: dict[str, Any]) -> Any:
    """The only place yt-dlp is imported or instantiated."""
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


def _run(url: str, options: dict[str, Any], invoke: Callable[[Any], Any]) -> dict[str, Any]:
    ydl = _make_ydl(options)
    try:
        result = invoke(ydl)
    except LevixError:
        raise
    except Exception as exc:  # yt-dlp's own failures are mapped, never re-raised raw
        # KeyboardInterrupt and SystemExit are BaseException, so Ctrl+C still leaves
        # main.py's exit-130 path untouched.
        detail = str(exc).strip() or type(exc).__name__
        hint = (
            "pass --allow-file-url to let yt-dlp read a file on this disk"
            if "file:// URLs are disabled" in detail
            else None
        )
        raise ProviderError(f"yt-dlp could not handle {url}: {detail}", hint=hint) from exc
    return dict(result or {})


def probe(url: str, options: dict[str, Any]) -> dict[str, Any]:
    """Metadata only: nothing is written, nothing is merged."""
    return _run(url, options, lambda ydl: ydl.extract_info(url, download=False))


def fetch(url: str, options: dict[str, Any]) -> dict[str, Any]:
    """The real download.

    `extract_info(download=True)` is used instead of `download()` because the latter
    returns a count, and the info dict is what the summary line is built from.
    """
    return _run(url, options, lambda ydl: ydl.extract_info(url, download=True))


def stream_url(info: dict[str, Any]) -> str | None:
    """The one URL a player can be handed, or None when the site gave us none."""
    direct = info.get("url")
    if direct:
        return str(direct)
    wanted = info.get("format_id")
    for row in info.get("formats") or ():
        if row.get("format_id") == wanted and row.get("url"):
            return str(row["url"])
    return None


# ----------------------------------------------------------------------------------
# reading the info dict
# ----------------------------------------------------------------------------------


def is_playlist(info: dict[str, Any]) -> bool:
    return info.get("_type") == "playlist" or "entries" in info


def _size(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def summarize(info: dict[str, Any]) -> MediaSummary:
    entries = info.get("entries")
    entry_list = list(entries) if isinstance(entries, (list, tuple)) else None
    formats = [] if entry_list else list(info.get("formats") or ())
    sizes = [
        size
        for size in (
            _size(row.get("filesize")) or _size(row.get("filesize_approx")) for row in formats
        )
        if size
    ]
    requested = _size(info.get("filesize"))
    if requested:
        sizes = [*sizes, requested]
    duration = info.get("duration")
    return MediaSummary(
        title=str(info.get("title") or "untitled"),
        media_id=str(info.get("id") or "-"),
        extractor=str(info.get("extractor") or info.get("extractor_key") or "not reported"),
        webpage_url=str(info.get("webpage_url") or info.get("url") or ""),
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        uploader=str(info.get("uploader") or info.get("channel") or info.get("artist") or ""),
        resolution=str(info.get("resolution") or ""),
        smallest=min(sizes) if sizes else None,
        largest=max(sizes) if sizes else None,
        entry_count=len(entry_list) if entry_list is not None else None,
        rows=tuple(_format_row(row) for row in formats),
    )


def _format_row(row: dict[str, Any]) -> FormatRow:
    width, height = row.get("width"), row.get("height")
    if width and height:
        resolution = f"{int(width)}x{int(height)}"
    elif row.get("resolution"):
        resolution = str(row["resolution"])
    else:
        resolution = "not reported"
    size = _size(row.get("filesize")) or _size(row.get("filesize_approx"))
    fps, tbr = row.get("fps"), row.get("tbr")
    return FormatRow(
        format_id=str(row.get("format_id") or "-"),
        extension=str(row.get("ext") or "-"),
        resolution=resolution,
        fps="-" if not fps else f"{fps:g}",
        vcodec=str(row.get("vcodec") or "-"),
        acodec=str(row.get("acodec") or "-"),
        bitrate="-" if not tbr else f"{tbr:.0f} kbit/s",
        size="-" if size is None else human_bytes(size),
        note=str(row.get("format_note") or ""),
    )


def final_path(info: dict[str, Any]) -> str | None:
    for key in ("filepath", "_filename"):
        value = info.get(key)
        if value:
            return str(value)
    return None


def hook_path(states: tuple[ProgressState, ...] | list[ProgressState]) -> str | None:
    """The filename yt-dlp last reported - the destination, bytes moved or not.

    The info dict does not always carry a path, but every hook fires with `filename`,
    including the one that says "has already been downloaded".
    """
    for state in reversed(list(states)):
        if state.filename:
            return state.filename
    return None


def transferred(states: tuple[ProgressState, ...] | list[ProgressState]) -> bool:
    """False means the skip path ran: no `downloading` hook, so no bytes crossed."""
    return any(state.status == "downloading" for state in states)


# ----------------------------------------------------------------------------------
# progress
# ----------------------------------------------------------------------------------


def progress_from_hook(raw: dict[str, Any]) -> ProgressState:
    """One yt-dlp hook dict -> numbers. Bytes win when both are known."""
    status = str(raw.get("status") or "")
    downloaded = _size(raw.get("downloaded_bytes")) or 0
    total = _size(raw.get("total_bytes")) or _size(raw.get("total_bytes_estimate"))
    if total:
        percent = min(100.0, max(0.0, 100.0 * downloaded / total))
    elif raw.get("percent") is not None:
        percent = min(100.0, max(0.0, float(raw["percent"])))
    else:
        percent = 0.0
    if status == "finished":
        percent = 100.0
        total = total or downloaded
    speed = raw.get("speed")
    eta = raw.get("eta")
    return ProgressState(
        status=status,
        downloaded_bytes=downloaded,
        total_bytes=total,
        percent=percent,
        speed=float(speed) if isinstance(speed, (int, float)) and speed else None,
        eta=float(eta) if isinstance(eta, (int, float)) else None,
        filename=str(raw.get("filename") or ""),
    )


def progress_text(state: ProgressState, *, width: int = 24) -> str:
    """One Rich-markup line. `terminal.bar` keeps it safe on a cp1252 console."""
    seen = human_bytes(state.downloaded_bytes)
    total = "unknown size" if state.total_bytes is None else human_bytes(state.total_bytes)
    parts = [terminal.bar(state.percent, width), f"{seen} / {total}"]
    if state.speed:
        parts.append(f"{human_bytes(state.speed)}/s")
    if state.eta is not None:
        parts.append(f"eta {human_clock(state.eta)}")
    return "  ".join(parts)


# ----------------------------------------------------------------------------------
# formatting helpers
# ----------------------------------------------------------------------------------


def human_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


def human_clock(seconds: float | None) -> str:
    """Wall-clock length of a clip, or an eta - both are seconds."""
    if seconds is None:
        return "not reported"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

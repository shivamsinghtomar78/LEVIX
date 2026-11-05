"""Runtime capability probes: what this machine can actually do right now.

Distinct from `deps.py`, which answers "is the package installed". A package can be
installed and the capability still unavailable (psutil present but the sensor is not
exposed by the Windows driver). Probes are cheap, never raise, and are the only
place that distinction is encoded.

`UNSUPPORTED` is a real answer here. LEVIX does not fabricate a zero to stand in for
a metric it cannot read.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from . import terminal

if TYPE_CHECKING:
    from .paths import Paths


class Status(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    status: Status
    detail: str
    hint: str | None = None

    @property
    def token(self) -> str:
        return {
            Status.OK: "OK",
            Status.DEGRADED: "DEGRADED",
            Status.MISSING: "MISSING",
            Status.UNSUPPORTED: "UNSUPPORTED",
        }[self.status]


PROBES: dict[str, Callable[[], ProbeResult]] = {}


def register(name: str) -> Callable[[Callable[[], ProbeResult]], Callable[[], ProbeResult]]:
    def decorator(fn: Callable[[], ProbeResult]) -> Callable[[], ProbeResult]:
        PROBES[name] = fn
        return fn

    return decorator


def probe(name: str) -> ProbeResult:
    fn = PROBES.get(name)
    if fn is None:
        return ProbeResult(name, Status.UNSUPPORTED, f"no probe registered for {name!r}")
    try:
        return fn()
    except Exception as exc:  # a probe must never take the CLI down
        return ProbeResult(name, Status.DEGRADED, f"probe raised {type(exc).__name__}: {exc}")


def report(names: tuple[str, ...] | None = None) -> list[ProbeResult]:
    wanted = names or tuple(PROBES)
    return [probe(name) for name in wanted]


def _package_present(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


@register("ffmpeg")
def _ffmpeg() -> ProbeResult:
    path = shutil.which("ffmpeg")
    if path:
        return ProbeResult("ffmpeg", Status.OK, path)
    return ProbeResult(
        "ffmpeg",
        Status.MISSING,
        "not on PATH",
        hint=(
            "single-file downloads still work; merging separate video+audio streams and "
            "audio conversion need ffmpeg. Windows: winget install Gyan.FFmpeg"
        ),
    )


@register("media_player")
def _player() -> ProbeResult:
    # The same order Tube searches (see `modules/tube/core.PLAYER_CANDIDATES`); core may
    # not import a module to read it, so the two lists are kept in step by this comment.
    candidates = ("mpv", "ffplay", "vlc", "mplayer")
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return ProbeResult("media_player", Status.OK, f"{candidate} at {path}")
    return ProbeResult(
        "media_player",
        Status.MISSING,
        f"none of {', '.join(candidates)} is on PATH",
        hint="`levix tube play` hands a stream URL to a player process; nothing is downloaded",
    )


@register("audio_output")
def _audio() -> ProbeResult:
    if not (_package_present("sounddevice") and _package_present("soundfile")):
        return ProbeResult(
            "audio_output",
            Status.MISSING,
            "sounddevice/soundfile not installed",
            hint='pip install "levix[music]"',
        )
    return ProbeResult(
        "audio_output",
        Status.OK,
        "sounddevice (PortAudio) + soundfile (libsndfile) bundled; a file on disk needs no ffmpeg",
    )


@register("psutil")
def _psutil() -> ProbeResult:
    if _package_present("psutil"):
        return ProbeResult("psutil", Status.OK, "installed")
    return ProbeResult(
        "psutil", Status.MISSING, "not installed", hint='pip install "levix[monitor]"'
    )


@register("temperature")
def _temperature() -> ProbeResult:
    if not _package_present("psutil"):
        return ProbeResult(
            "temperature",
            Status.MISSING,
            "psutil not installed",
            hint='pip install "levix[monitor]"',
        )
    try:
        import psutil

        sensors = psutil.sensors_temperatures()
    except Exception as exc:
        return ProbeResult("temperature", Status.DEGRADED, f"probe failed: {exc}")
    if not sensors:
        return ProbeResult(
            "temperature",
            Status.UNSUPPORTED,
            "the OS exposes no temperature sensors through psutil on this platform",
            hint=(
                "common on Windows and cloud VMs; `levix monitor` omits the panel rather "
                "than showing a fake value"
            ),
        )
    return ProbeResult("temperature", Status.OK, ", ".join(sorted(sensors)))


@register("battery")
def _battery() -> ProbeResult:
    if not _package_present("psutil"):
        return ProbeResult("battery", Status.MISSING, "psutil not installed")
    try:
        import psutil

        life = psutil.sensors_battery()
    except Exception as exc:
        return ProbeResult("battery", Status.DEGRADED, f"probe failed: {exc}")
    if life is None:
        return ProbeResult("battery", Status.UNSUPPORTED, "no battery present or reported")
    return ProbeResult(
        "battery",
        Status.OK,
        f"{life.percent:.0f}% ({'plugged in' if life.power_plugged else 'on battery'})",
    )


@register("gpu")
def _gpu() -> ProbeResult:
    return ProbeResult(
        "gpu",
        Status.UNSUPPORTED,
        "psutil provides no GPU utilisation API on any platform",
        hint=(
            "read GPU stats from vendor tooling (nvidia-smi, intel_gpu_top, powermetrics) "
            "and run those directly; LEVIX will not guess a value"
        ),
    )


@register("keyring")
def _keyring() -> ProbeResult:
    from . import secrets

    backend_id, detail = secrets.backend(_lazy_paths())
    if backend_id == "keyring":
        return ProbeResult("keyring", Status.OK, detail)
    return ProbeResult("keyring", Status.DEGRADED, detail, hint='pip install "levix[secrets]"')


def _lazy_paths() -> Paths:
    from .paths import resolve_paths

    return resolve_paths()


@register("terminal")
def _terminal() -> ProbeResult:
    profile = terminal.detect()
    if not profile.is_tty:
        return ProbeResult("terminal", Status.DEGRADED, "stdout is not a TTY (piped or captured)")
    if profile.supports_colour and profile.protocol_enabled:
        return ProbeResult(
            "terminal", Status.OK, f"{profile.columns}x{profile.rows}, ANSI colour on"
        )
    return ProbeResult(
        "terminal",
        Status.DEGRADED,
        f"{profile.columns}x{profile.rows}, colour disabled",
        hint=(
            "legacy Windows consoles need ENABLE_VIRTUAL_TERMINAL_PROCESSING, "
            "or set TERM=xterm-256color"
        ),
    )


@register("platform")
def _platform() -> ProbeResult:
    import platform as std_platform

    return ProbeResult(
        "platform",
        Status.OK,
        f"{std_platform.system()} {std_platform.release()} "
        f"({std_platform.machine()}), Python {sys.version.split()[0]}",
    )

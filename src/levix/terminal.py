"""Terminal capability handling: colour, glyph and Windows VT bootstrap.

Textual configures the console itself. The non-Textual paths (`levix hacker matrix`,
plain progress bars, fallback output when `NO_COLOR` is set) do not, so they call
`ensure_ansi()` before emitting raw escape sequences.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True, slots=True)
class TerminalProfile:
    is_tty: bool
    supports_colour: bool
    supports_unicode: bool
    columns: int
    rows: int
    term: str
    protocol_enabled: bool


def _windows_vt_enabled() -> bool:
    """Ask the console for ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004).

    Legacy conhost renders ANSI as garbage without this. Returns whether it worked,
    and never raises: a failure simply means we degrade to plain text.
    """
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def detect(*, force_no_unicode: bool | None = None) -> TerminalProfile:
    tty = bool(sys.stdout.isatty())
    no_color = bool(os.environ.get("NO_COLOR"))
    term = os.environ.get("TERM", "")
    force_no_color = os.environ.get("LEVIX_NO_COLOR") == "1"
    colour = tty and not no_color and not force_no_color and term != "dumb"

    if force_no_unicode is None:
        encoding = getattr(sys.stdout, "encoding", "") or ""
        force_no_unicode = "utf" not in encoding.lower()
    unicode_ok = not force_no_unicode and term != "dumb"

    size = shutil.get_terminal_size(fallback=(80, 24))
    return TerminalProfile(
        is_tty=tty,
        supports_colour=colour,
        supports_unicode=unicode_ok,
        columns=size.columns,
        rows=size.lines,
        term=term,
        protocol_enabled=_windows_vt_enabled() if (tty and colour) else False,
    )


def glyphs(profile: TerminalProfile) -> dict[str, str]:
    """ASCII-safe alternatives for terminals that cannot render box drawing."""
    if profile.supports_unicode:
        return {
            "block": "█",
            "shade": "▓",
            "dot": "·",
            "arrow": "→",
            "tick": "✓",
            "cross": "✗",
            "dash": "─",
            "spinner": "⠋⠙⠸⠴⠦⠇",
        }
    return {
        "block": "#",
        "shade": "+",
        "dot": ".",
        "arrow": "->",
        "tick": "OK",
        "cross": "!!",
        "dash": "-",
        "spinner": r"\|/-",
    }


@lru_cache(maxsize=1)
def active_glyphs() -> dict[str, str]:
    """Glyph set for the current stream.

    On a Windows console whose Python encoding is cp1252, writing U+2588 raises
    UnicodeEncodeError inside Rich's win32 writer - a crash, not cosmetic damage.
    Every renderer therefore asks this instead of embedding box-drawing characters.
    """
    return glyphs(detect())


def bar(
    percent: float, width: int = 20, *, low: str = "green", mid: str = "yellow", high: str = "red"
) -> str:
    """A Rich-markup usage bar that is safe on any codepage."""
    set_ = active_glyphs()
    filled = max(0, min(width, round(percent / 100 * width)))
    colour = low if percent < 60 else (mid if percent < 85 else high)
    return (
        f"[{colour}]{set_['block'] * filled}{set_['dash'] * (width - filled)}[/{colour}] "
        f"{percent:5.1f}%"
    )


def encode_safe(text: str) -> str:
    """`text` rewritten so this stream can carry it, on one line.

    The same win32 writer that rejects U+2588 also rejects the emoji and non-Latin
    names a remote site puts in a title, so text that arrives from outside the
    terminal has to be adapted before it is handed to Rich. Unencodable characters
    come back as `\\uXXXX` escapes and control characters as `\\xNN`: the value stays
    readable and comparable instead of crashing the command that prints it.
    """
    one_line = "".join(
        char if (char.isprintable() and char != "\x7f") else f"\\x{ord(char):02x}" for char in text
    )
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        one_line.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        one_line = one_line.encode(encoding, "backslashreplace").decode(encoding, "replace")
    return one_line


def markup_safe(value: object) -> str:
    """`value` ready to interpolate into a Rich markup string.

    Rich parses `[...]` as a style tag and silently deletes it along with what is inside,
    so the pip extra in an install hint (`levix[tube]`) prints as `levix`, a bracketed
    filename loses its bracket, and a plugin's own summary loses whatever it wrote in
    brackets. This bites every string the core did not author: manifests, hints, package
    statuses, command history. Line breaks are left alone - tables fold them - because
    only `encode_safe` is about what the stream can carry.
    """
    from rich.markup import escape

    return escape(str(value))


def new_console(*, stderr: bool = False, highlight: bool = True) -> Console:
    """The Rich console every LEVIX command prints through, minus the str rewrites.

    `emoji=False` is why this is a function and not a bare `Console()` at each site. Rich
    runs two parsers over a `str` handed to `print`: markup for `[...]`, which
    `markup_safe` closes, and emoji shortcodes for `:name:`, which no escaping of the
    string closes - there is no way to write a colon that means itself. Command-line text
    is exactly the text that carries colons, so before this existed `levix music play
    magnet:abc` reported the link it refused as `magnet` + U+1F524 + ` only http and
    https are played from a URL`: the error named a thing with a colon eaten and an emoji
    pasted in, and the punctuation that separated it from the sentence went with it.
    LEVIX authors no emoji shortcodes anywhere, so the only code path that could need one
    is the path quoting something it did not write.
    """
    from rich.console import Console

    return Console(stderr=stderr, highlight=highlight, emoji=False)

"""The console-capability layer: what this terminal can be handed, and what it cannot.

Windows consoles are commonly cp1252, and Rich's win32 writer raises UnicodeEncodeError
on a box-drawing character. That is a crash inside a progress bar, so the glyph set and
the encoding guard are both load-bearing, not cosmetic.
"""

from __future__ import annotations

import sys

import pytest

from levix import terminal
from levix.terminal import TerminalProfile, bar, detect, encode_safe, glyphs


def profile(**overrides) -> TerminalProfile:
    base = {
        "is_tty": True,
        "supports_colour": True,
        "supports_unicode": True,
        "columns": 100,
        "rows": 30,
        "term": "xterm-256color",
        "protocol_enabled": True,
    }
    base.update(overrides)
    return TerminalProfile(**base)


@pytest.fixture(autouse=True)
def _clear_glyph_cache():
    """`active_glyphs()` is lru_cached, so a patched `detect` only takes effect once the
    cache is emptied. Left dirty, one test would decide the glyph set for the next."""
    terminal.active_glyphs.cache_clear()
    yield
    terminal.active_glyphs.cache_clear()


def test_a_unicode_terminal_gets_the_block_glyphs():
    set_ = glyphs(profile(supports_unicode=True))
    assert set_["block"] == "█"
    assert set_["arrow"] == "→"


def test_a_codepage_terminal_gets_ascii_and_never_a_box_character():
    set_ = glyphs(profile(supports_unicode=False))
    for glyph in set_.values():
        assert glyph.isascii(), f"{glyph!r} would crash a cp1252 console"
    assert set_["block"] == "#"
    assert set_["tick"] == "OK"


def test_the_glyph_choice_follows_the_streams_encoding(monkeypatch):
    # The rule is `"utf" in encoding`, because that is what the writer can actually carry.
    monkeypatch.setattr(terminal, "detect", lambda **kw: profile(supports_unicode=False))
    assert bar(50).count("#") > 0
    monkeypatch.setattr(terminal, "detect", lambda **kw: profile(supports_unicode=True))
    # `active_glyphs` is keyed on nothing, so the ASCII set the first call cached survives
    # the patch change until it is emptied. The autouse fixture only brackets the test.
    terminal.active_glyphs.cache_clear()
    assert "█" in bar(50)


def test_a_forced_ascii_profile_writes_only_bytes_a_cp1252_console_can_encode(monkeypatch):
    monkeypatch.setattr(terminal, "detect", lambda **kw: profile(supports_unicode=False))
    rendered = bar(37.5)
    assert rendered.encode("cp1252")
    assert "37.5%" in rendered


@pytest.mark.parametrize(
    ("percent", "expected_filled", "expected_colour"),
    [(0.0, 0, "green"), (10.0, 2, "green"), (70.0, 14, "yellow"), (95.0, 19, "red")],
)
def test_the_bar_scales_and_names_the_band_that_colours_it(
    percent, expected_filled, expected_colour, monkeypatch
):
    monkeypatch.setattr(terminal, "detect", lambda **kw: profile(supports_unicode=False))
    rendered = bar(percent, width=20)
    assert rendered.startswith(f"[{expected_colour}]")
    assert rendered.count("#") == expected_filled
    assert rendered.count("-") == 20 - expected_filled


@pytest.mark.parametrize(("percent", "filled"), [(-40.0, 0), (140.0, 20)])
def test_an_out_of_range_percentage_is_clamped_not_wrapped(percent, filled, monkeypatch):
    monkeypatch.setattr(terminal, "detect", lambda **kw: profile(supports_unicode=False))
    assert bar(percent, width=20).count("#") == filled


def test_encode_safe_leaves_a_plain_line_alone():
    assert encode_safe("Midnight Set [abcdef].mp4") == "Midnight Set [abcdef].mp4"


def test_encode_safe_escapes_what_the_console_carry_cannot():
    text = encode_safe("bad\x00char\u2588here")
    assert "\x00" not in text
    assert "\\x00" in text
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    # Whatever the guard produces must survive the stream it is destined for.
    text.encode(encoding)
    assert "\u2588" not in text or encoding.lower().replace("-", "") in ("utf8", "utf16", "utf32")


def test_encode_safe_keeps_a_line_on_one_line():
    assert "\n" not in encode_safe("first\nsecond")
    assert "\\x0a" in encode_safe("first\nsecond")


def test_encode_safe_reports_a_missing_encoding_as_utf8(monkeypatch):
    class NoEncoding:
        encoding = None

    monkeypatch.setattr(sys, "stdout", NoEncoding())
    assert encode_safe("plain") == "plain"


def test_detect_uses_the_environment_it_is_given(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    assert detect().supports_colour is False, "NO_COLOR is a promise, not a suggestion"


def test_dumb_term_loses_colour_and_glyphs(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    found = detect()
    assert found.supports_colour is False
    assert found.supports_unicode is False
    assert glyphs(found)["block"] == "#"


def test_a_captured_stream_is_not_a_terminal_and_gets_no_vt_bootstrap(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    found = detect()
    assert found.is_tty is False
    assert found.supports_colour is False
    assert found.protocol_enabled is False


def test_columns_come_from_the_terminal_size(monkeypatch):
    monkeypatch.setenv("COLUMNS", "133")
    monkeypatch.setenv("LINES", "41")
    found = detect()
    assert found.columns == 133
    assert found.rows == 41


def test_active_glyphs_is_cached_and_clearable():
    first = terminal.active_glyphs()
    assert terminal.active_glyphs() is first
    terminal.active_glyphs.cache_clear()
    assert terminal.active_glyphs() is not first

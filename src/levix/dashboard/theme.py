"""LEVIX's own themes, and the handshake with `general.theme`.

Textual ships two themes; the four here exist so `levix` looks like itself and so every
value the config layer documents as legal maps onto something real. A name the app does
not know is reported, not silently ignored: a user who set `general.theme` in a file
deserves to learn that they typed it wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.theme import Theme

if TYPE_CHECKING:
    from textual.app import App

THEMES: tuple[Theme, ...] = (
    Theme(
        name="levix-dark",
        primary="#00a35f",
        secondary="#0080a0",
        warning="#ffb000",
        error="#ff3b30",
        success="#00d68f",
        accent="#00a35f",
        foreground="#d8e2dc",
        background="#0d1117",
        surface="#151b23",
        panel="#1b232e",
        dark=True,
    ),
    Theme(
        name="levix-green",
        primary="#00ff6c",
        secondary="#00c853",
        warning="#ffd600",
        error="#ff1744",
        success="#00ff6c",
        accent="#00ff6c",
        foreground="#00e676",
        background="#000000",
        surface="#04120a",
        panel="#071c11",
        dark=True,
    ),
    Theme(
        name="levix-light",
        primary="#0a7d43",
        secondary="#00668a",
        warning="#a06000",
        error="#b3261e",
        success="#0a7d43",
        accent="#00668a",
        foreground="#1c1f21",
        background="#f4f6f5",
        surface="#e7ebe9",
        panel="#dfe4e1",
        dark=False,
    ),
    Theme(
        name="levix-contrast",
        primary="#ffffff",
        secondary="#00ffff",
        warning="#ffff00",
        error="#ff8080",
        success="#00ff00",
        accent="#ffff00",
        foreground="#ffffff",
        background="#000000",
        surface="#000000",
        panel="#1a1a1a",
        dark=True,
    ),
)

#: `general.theme` ships as "default"; the rest of the table maps prose to a real theme.
#: Every name in `config.SCHEMA`'s `general.theme` choices has to appear here, or the
#: dashboard rejects a value the config layer accepted - which is `apply()`'s honesty
#: path (it reports the refusal in the footer) but still a promise the pair breaks.
#: `tests/test_dashboard.py::test_every_documented_theme_name_resolves` pins that down.
ALIASES = {
    "default": "levix-dark",
    "dark": "levix-dark",
    "hacker": "levix-green",
    "green": "levix-green",
    "matrix": "levix-green",
    "minimal": "levix-light",
    "light": "levix-light",
    "high-contrast": "levix-contrast",
}


class ThemeResult:
    """What `apply` decided, so the caller can say it back in the footer."""

    def __init__(self, applied: str, note: str = "") -> None:
        self.applied = applied
        self.note = note


def register(app: App) -> None:
    for theme in THEMES:
        app.register_theme(theme)


def available(app: App) -> list[str]:
    return sorted(app.available_themes)


def _current(app: App) -> str:
    """`App.theme` is the theme *name* (a str), not a Theme - introspected against 8.2.8."""
    return app.theme or "textual-dark"


def apply(app: App, requested: str | None) -> ThemeResult:
    """Set `requested` (or its alias) when the app knows it; otherwise say why not."""
    name = (requested or "default").strip()
    target = ALIASES.get(name.casefold(), name)
    if target in available(app):
        app.theme = target
        return ThemeResult(target)
    note = f"unknown theme {name!r}; using {_current(app)}"
    return ThemeResult(_current(app), note=note)


def cycle(app: App) -> ThemeResult:
    """Step to the next LEVIX theme - the `t` binding."""
    known = available(app)
    options = [theme.name for theme in THEMES if theme.name in known]
    if not options:
        return ThemeResult(_current(app), note="no LEVIX themes registered")
    current = _current(app)
    nxt = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
    app.theme = nxt
    return ThemeResult(nxt)

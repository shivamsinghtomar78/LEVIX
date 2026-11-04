"""The dashboard application: list, filter, launch, report.

Kept deliberately thin. Everything here is presentation and dispatch; the decision about
whether a module can run lives in the registry and the dependency gate, so the dashboard
and the keyboard path can never disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from .. import registry as registry_module
from .. import spawn
from ..module import ModuleManifest
from ..registry import active as active_registry
from ..terminal import markup_safe
from . import module_list
from . import theme as theme_module
from .history import recent_lines

if TYPE_CHECKING:
    from ..context import LevixContext
    from .module_list import ModuleRow

CSS = """
#filter {
    dock: top;
    margin: 0 1;
}

#body {
    height: 1fr;
}

#modules {
    width: 2fr;
    border: round $primary;
    padding: 0 1;
}

#side {
    width: 3fr;
    padding: 0 1;
}

#detail {
    height: 1fr;
    border: round $secondary;
    padding: 0 1;
}

#history {
    height: auto;
    max-height: 12;
    border: round $panel;
    padding: 0 1;
}

ListItem {
    padding: 0 1;
}
"""


class LevixDashboard(App[None]):
    """`levix` with no arguments, and `levix dashboard`."""

    TITLE = "LEVIX"
    CSS = CSS
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "launch", "run"),
        Binding("space", "describe", "details"),
        Binding("f", "focus_filter", "filter"),
        Binding("r", "reload", "reload"),
        Binding("t", "cycle_theme", "theme"),
        Binding("h", "toggle_history", "history"),
        Binding("q", "quit", "quit"),
        Binding("escape", "clear_filter", "clear", show=False),
        Binding("ctrl+c", "quit", "quit", priority=True, show=False),
    ]

    def __init__(self, context: LevixContext | None = None) -> None:
        super().__init__()
        self.context = context
        self.rows: list[module_list.ModuleRow] = []
        self._needle = ""
        self._show_history = True

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="filter modules - type to narrow, enter to launch", id="filter")
        with Horizontal(id="body"):
            yield ListView(id="modules")
            with Vertical(id="side"):
                yield Static("", id="detail")
                yield Static("", id="history")
        yield Footer()

    def on_mount(self) -> None:
        theme_module.register(self)
        applied = theme_module.apply(self, self._config_theme())
        if applied.note:
            self.notify(applied.note, severity="warning", timeout=6)
        self.refresh_modules()
        self.refresh_history()

    # ------------------------------------------------------------- rendering
    def refresh_modules(self) -> None:
        """Re-read the registry, so a plugin installed into this environment appears."""
        registry = active_registry()
        all_rows = module_list.build_rows(registry)
        self.rows = module_list.filter_rows(all_rows, self._needle)
        list_view = self.query_one("#modules", ListView)
        list_view.clear()
        for row in self.rows:
            list_view.append(ListItem(Static(row.label()), name=row.name))
        if not self.rows:
            self.query_one("#detail", Static).update(
                f"[yellow]nothing matches {self._needle!r}[/yellow]"
            )
            return
        list_view.index = 0
        self.show_detail()

    def refresh_history(self) -> None:
        panel = self.query_one("#history", Static)
        if not self._show_history:
            panel.update("")
            return
        limit = self._value("dashboard.recent_commands", 10)
        database = self.context.database if self.context is not None else None
        if database is None:
            panel.update("[dim]history needs a levix context[/dim]")
            return
        lines = recent_lines(database, limit=int(limit))
        panel.update("recent\n" + "\n".join(lines))

    def show_detail(self) -> None:
        row = self._selected()
        if row is None:
            return
        manifest = active_registry().get(row.name)
        panel = self.query_one("#detail", Static)
        if manifest is None:  # pruned between refreshes
            panel.update(markup_safe(row.summary))
            return
        panel.update(_describe(manifest, row))

    # -------------------------------------------------------------- actions
    def action_launch(self) -> None:
        row = self._selected()
        if row is None:
            return
        if not row.runnable:
            self.notify(_why_not(row), severity="warning", timeout=8)
            self.show_detail()
            return
        self._run(row)

    def _run(self, row: ModuleRow) -> None:
        argv = _argv_for(active_registry().get(row.name), row)
        # The child owns the terminal outright. Two Textual apps cannot share one TTY,
        # and `suspend()` is what gives the child the real screen and the parent back.
        with self.suspend():
            code = spawn.run(*argv)
        self.refresh_history()
        shown = markup_safe(" ".join(argv))
        if code:
            self.notify(f"levix {shown} exited {code}", severity="warning", timeout=5)
        else:
            self.notify(f"levix {shown} finished", timeout=3)

    def action_describe(self) -> None:
        self.show_detail()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#filter", Input)
        if self._needle or field.value:
            field.value = ""
            self._needle = ""
            self.refresh_modules()
        else:
            self.exit()

    def action_reload(self) -> None:
        # Discovery caches on purpose (it reads package metadata), so a reload has to
        # install a fresh registry rather than re-asking the cached one.
        registry_module.use(registry_module.ModuleRegistry())
        self.refresh_modules()
        self.refresh_history()
        self.notify("re-read the registry", timeout=3)

    def action_cycle_theme(self) -> None:
        result = theme_module.cycle(self)
        self.notify(
            result.note or f"theme: {result.applied}",
            severity="warning" if result.note else "information",
            timeout=4,
        )

    def action_toggle_history(self) -> None:
        self._show_history = not self._show_history
        self.refresh_history()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter":
            return
        self._needle = event.value
        self.refresh_modules()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            event.input.value = ""
            self._needle = ""
            self.refresh_modules()
            self.query_one("#modules", ListView).focus()
            self.action_launch()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        del event
        self.action_launch()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        del event
        self.show_detail()

    # ---------------------------------------------------------------- plumbing
    def _selected(self) -> ModuleRow | None:
        index = self.query_one("#modules", ListView).index
        if index is None or not (0 <= index < len(self.rows)):
            return None
        return self.rows[index]

    def _value(self, dotted: str, fallback: Any) -> Any:
        if self.context is None:
            return fallback
        try:
            return self.context.value(dotted)
        except Exception:
            return fallback

    def _config_theme(self) -> str:
        return str(self._value("general.theme", "default"))


def _argv_for(manifest: ModuleManifest | None, row: ModuleRow) -> tuple[str, ...]:
    """The command line this row actually runs.

    A module that declares a dashboard screen with its own argv (Snake, the file browser,
    the live monitor) gets it; everything else opens the module's own help, which beats
    dropping the user into a command that expects arguments.
    """
    if manifest is not None and manifest.ui is not None and manifest.ui.argv:
        return tuple(manifest.ui.argv)
    return (row.name, "-h")


def _describe(manifest: ModuleManifest, row: ModuleRow) -> str:
    """The detail panel. Every manifest-authored field is escaped on the way in."""
    lines = [f"[bold]{markup_safe(manifest.title)}[/bold]  [dim]{markup_safe(manifest.name)}[/dim]"]
    lines.append(markup_safe(manifest.summary))
    if manifest.commands:
        lines.append("")
        for command in manifest.commands:
            lines.append(
                f"  [cyan]{markup_safe(command.name):<12}[/cyan]{markup_safe(command.help)}"
            )
    if manifest.requirements:
        lines.append("")
        lines.append("[bold]packages[/bold]")
        for ref in manifest.requirements:
            name = markup_safe(ref.import_name)
            minimum = f" (>= {markup_safe(ref.minimum)})" if ref.minimum else ""
            lines.append(f"  {name}{minimum}")
    if manifest.permissions:
        granted = ", ".join(sorted(str(permission.value) for permission in manifest.permissions))
        lines.append(f"[bold]permissions[/bold] {markup_safe(granted)}")
    if manifest.documentation:
        lines.append(f"[bold]docs[/bold] {markup_safe(manifest.documentation)}")
    if not row.runnable:
        lines.append(f"[yellow]{_why_not(row)}[/yellow]")
    return "\n".join(lines)


def _why_not(row: module_list.ModuleRow) -> str:
    title = markup_safe(row.title)
    detail = markup_safe(row.detail)
    if row.state == "broken":
        return f"{title} failed to load: {detail}"
    return f"{title} needs an install: {detail}"

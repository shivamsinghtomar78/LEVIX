"""The full-screen browser behind `levix files browse`.

Imported *inside* the `browse` command body, never at module scope: nothing here is
needed for `levix files -h`, and Textual apps are the heaviest thing in the module.

Only widgets that exist in the pinned core dependency (textual>=8.2,<9) are used:
`Header`, `Footer`, `DirectoryTree`, `Static`, `Input`, `Button` plus `ModalScreen` and
`Binding`. Every operation is confined to the directory the user opened - the same
`core` functions the plain CLI calls, so the wall and the confirmation rules are
identical in both interfaces.

Keyboard: `enter`/`o` open, `space` expand, `p` preview, `c` copy, `d` delete, `r`
reload, `?` help, `q` quit, `ctrl+q` quit (Textual's own binding).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import ClassVar

from rich.markup import escape
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, Static

from ...errors import LevixError
from . import core
from .core import RequestError

PREVIEW_ROWS = 60
PREVIEW_CHARS = 6000


def show(value: object) -> str:
    """Console- and markup-safe text for one dynamic value.

    Two hazards at once: a cp1252 console cannot encode a fancy file name, and Rich
    would read `[bold]` inside a file name as markup. Both are handled here, so every
    string that reaches the screen can be printed exactly once.
    """
    return escape(core.printable(value))


class PromptScreen(ModalScreen[str | None]):
    """One-line question whose answer is a path fragment relative to the browser root."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]
    DEFAULT_CSS = """
    PromptScreen { layout: vertical; align: center middle; }
    PromptScreen > Vertical {
        width: auto; max_width: 90%; padding: 1 2;
        border: round $primary; background: $surface;
    }
    PromptScreen Input { margin-top: 1; }
    """

    def __init__(self, question: str, placeholder: str = "") -> None:
        super().__init__()
        self._question = question
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._question, id="prompt-question", markup=False)
            yield Input(placeholder=self._placeholder, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def _finish(self, value: str | None) -> None:
        self.dismiss(value)

    def on_input_submitted(self, message: Input.Submitted) -> None:
        self._finish(message.value)

    def action_cancel(self) -> None:
        self._finish(None)


class ConfirmScreen(ModalScreen[bool]):
    """Typed confirmation inside the terminal, mirroring `levix.approve`.

    Textual owns the screen while it runs, so the shared stdin gate cannot be used
    here; the rule is reproduced instead: type the word `DELETE` exactly, or nothing
    happens. Clicking `cancel`, pressing `escape` or closing the dialog all resolve to
    `False`.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { layout: vertical; align: center middle; }
    ConfirmScreen > Vertical {
        width: auto; max_width: 90%; padding: 1 2;
        border: round $error; background: $surface;
    }
    ConfirmScreen Horizontal { height: auto; }
    """

    def __init__(self, detail: str) -> None:
        super().__init__()
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"delete: {self._detail}", id="confirm-detail", markup=False)
            yield Static("type DELETE to continue - anything else aborts", id="confirm-hint")
            yield Input(id="confirm-input")
            with Horizontal():
                # textual 8 accepts only default/error/primary/success/warning here
                yield Button("cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.value.strip().casefold() == "delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_button_pressed(self, message: Button.Pressed) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    """The key list, on screen, without leaving the app."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,enter,q,question_mark", "close", "Close", priority=True),
    ]
    DEFAULT_CSS = """
    HelpScreen { layout: vertical; align: center middle; }
    HelpScreen > Vertical {
        width: auto; max_width: 90%; padding: 1 2;
        border: round $primary; background: $surface;
    }
    """

    def __init__(self, lines: tuple[str, ...]) -> None:
        super().__init__()
        self._lines = lines

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("keys", id="help-title")
            yield Static("\n".join(self._lines), id="help-body", markup=False)

    def on_key(self, message: events.Key) -> None:
        message.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class BrowseApp(App[None]):
    """`levix files browse PATH` - a DirectoryTree with the module's rules behind it."""

    TITLE = "LEVIX files"
    CSS: ClassVar[str] = """
    Horizontal { height: 1fr; }
    #tree { width: 2fr; border: round $primary; }
    #side { width: 3fr; }
    #details { height: 1fr; padding: 1 2; overflow-y: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("o", "open", "Open"),
        Binding("p", "preview", "Preview"),
        Binding("c", "copy", "Copy to..."),
        Binding("d", "delete", "Delete"),
        Binding("r", "reload", "Reload"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._dialog_open = False

    # -- lifecycle ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield DirectoryTree(self._root, id="tree")
            with Vertical(id="side"):
                yield Static(self._welcome(), id="details")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = core.printable(self._root.name) or core.printable(self._root)
        self.query_one(DirectoryTree).focus()

    def _welcome(self) -> str:
        return (
            f"[bold]root[/bold] [cyan]{show(self._root)}[/cyan]\n\n"
            "Cursor keys move, [b]space[/b] expands, [b]enter[/b] or [b]o[/b] opens.\n"
            "[b]p[/b] preview  [b]c[/b] copy  [b]d[/b] delete  [b]r[/b] reload\n"
            "[b]?[/b] this help   [b]q[/b] quit\n\n"
            "Everything is confined to the root above, and a delete asks you to type "
            "the word DELETE first."
        )

    # -- selection ---------------------------------------------------------

    @property
    def _tree(self) -> DirectoryTree:
        return self.query_one(DirectoryTree)

    def _selected(self) -> Path | None:
        node = self._tree.cursor_node
        if node is None or node.data is None:
            return None
        return node.data.path

    # -- messages ----------------------------------------------------------

    def on_directory_tree_file_selected(self, message: DirectoryTree.FileSelected) -> None:
        self._show_preview(message.path)

    def on_directory_tree_directory_selected(
        self, message: DirectoryTree.DirectorySelected
    ) -> None:
        node = message.node
        if node.allow_expand:
            node.toggle()

    # -- actions -----------------------------------------------------------

    def action_open(self) -> None:
        path = self._selected()
        if path is None:
            self.notify("nothing selected", severity="warning", markup=False)
            return
        if path.is_dir():
            self._tree.action_toggle_node()
        else:
            self._show_preview(path)

    def action_preview(self) -> None:
        path = self._selected()
        if path is None:
            self.notify("nothing selected", severity="warning", markup=False)
            return
        self._show_preview(path)

    def action_reload(self) -> None:
        self._tree.reload()
        self.notify("tree reloaded", markup=False)

    def action_help(self) -> None:
        lines = tuple(
            f"{key:<14}{label}"
            for key, label in (
                ("enter / o", "open a file, expand or collapse a directory"),
                ("space", "expand or collapse the selected directory"),
                ("up / down", "move the cursor"),
                ("shift+left", "jump to the parent directory"),
                ("p", "preview: head of a text file, else metadata"),
                ("c", "copy the selection under a destination inside the root"),
                ("d", "delete the selected file (type DELETE to confirm)"),
                ("r", "reload the tree from disk"),
                ("?", "this panel"),
                ("q / ctrl+q", "quit"),
            )
        )
        self._dialog_open = True
        self.push_screen(HelpScreen(lines), self._dialog_closed)

    async def action_quit(self) -> None:
        """`async` to match `App.action_quit`, whose signature Textual's dispatcher awaits."""
        self.exit()

    def _dialog_closed(self, _result: object) -> None:
        self._dialog_open = False

    # -- copy --------------------------------------------------------------

    def action_copy(self) -> None:
        if self._dialog_open:
            return
        path = self._selected()
        if path is None:
            self.notify("nothing selected", severity="warning", markup=False)
            return
        self._dialog_open = True
        prompt = PromptScreen(
            f"copy {core.printable(path.name)} into, relative to {core.printable(self._root)}",
            "destination directory or new file name",
        )
        self.push_screen(prompt, lambda dest: self._do_copy(path, dest))

    def _do_copy(self, source: Path, dest: str | None) -> None:
        self._dialog_open = False
        if not dest:
            return
        target = core.to_path(dest)
        if not target.is_absolute():
            target = self._root / target
        try:
            result = core.copy_entry(source, target, root=self._root)
        except LevixError as exc:
            self._report(exc)
            return
        self.notify(
            f"copied {core.human_bytes(result.bytes_moved)} to "
            f"{core.printable(result.destination)}",
            markup=False,
        )
        self._tree.reload()

    # -- delete ------------------------------------------------------------

    def action_delete(self) -> None:
        if self._dialog_open:
            return
        path = self._selected()
        if path is None:
            self.notify("nothing selected", severity="warning", markup=False)
            return
        if path.is_dir() and not os.path.islink(path) and core.entries_in(path):
            self._report(
                RequestError(
                    f"{path} is a directory with entries inside",
                    hint=(
                        "the browser deletes files and empty directories only; re-run "
                        "`levix files delete --recursive` in a terminal for a whole tree"
                    ),
                )
            )
            return
        try:
            plan = core.plan_delete([str(path)], root=self._root, recursive=False)
        except LevixError as exc:
            self._report(exc)
            return
        self._dialog_open = True
        detail = f"{core.printable(path)} ({plan.describe()})"
        self.push_screen(ConfirmScreen(detail), lambda ok: self._do_delete(path, ok))

    def _do_delete(self, path: Path, approved: bool) -> None:
        self._dialog_open = False
        if not approved:
            self.notify("delete cancelled - nothing removed", markup=False)
            return
        try:
            plan = core.plan_delete([str(path)], root=self._root, recursive=False)
            removed, reclaimed, failures = core.execute_delete(plan)
        except LevixError as exc:
            self._report(exc)
            return
        for message in failures:
            self.notify(f"not removed: {message}", severity="error", markup=False)
        self.notify(
            f"deleted {len(removed)} entry(ies), {core.human_bytes(reclaimed)} reclaimed",
            severity="warning" if failures else "information",
            markup=False,
        )
        self._tree.reload()

    # -- rendering ---------------------------------------------------------

    def _show_preview(self, path: Path) -> None:
        try:
            result = core.preview(path, lines=PREVIEW_ROWS, count_line_total=True)
        except LevixError as exc:
            self._report(exc)
            return
        body = [
            f"[bold]{show(path.name)}[/bold]  [dim]{show(path.parent)}[/dim]",
            f"type: {result.entry.kind}   size: {core.human_bytes(result.entry.size_bytes)}",
            f"modified: {result.entry.modified_text}",
        ]
        if result.kind == "text":
            lines = list(result.lines)
            if result.counted and result.line_count is not None:
                body.append(f"lines: {result.line_count}   encoding: {show(result.encoding)}")
            else:
                body.append(f"encoding: {show(result.encoding)}   lines: not counted")
            text = "\n".join(core.printable(line) for line in lines)
            if len(text) > PREVIEW_CHARS:
                text = text[:PREVIEW_CHARS] + "\n... truncated ..."
            body.append("")
            body.append(text if text.strip() else "[dim](empty file)[/dim]")
            if result.truncated:
                body.append("[dim]... more lines on disk - use `levix files preview -n BIG`[/dim]")
        elif result.kind == "binary":
            body.append("")
            body.append(
                "[dim]binary content (a NUL byte in the first "
                f"{core.SNIFF_BYTES} bytes) - not shown. Metadata only.[/dim]"
            )
        elif result.kind == "symlink":
            body.append(f"link target: {show(result.entry.link_target)}")
        elif result.kind == "directory":
            names = core.entries_in(path)
            body.append(f"entries: {len(names)}")
            body.append("")
            body.append("\n".join(show(name) for name in names[:40]) or "[dim](empty)[/dim]")
        self.query_one("#details", Static).update("\n".join(body))

    def _report(self, exc: LevixError) -> None:
        message = core.printable(exc.message)
        if exc.hint and exc.hint not in message:
            message = f"{message}  [{core.printable(exc.hint)}]"
        self.notify(message, severity="error", markup=False)


def run_browse(root: Path) -> int:
    """Enter the screen. Refuses a non-terminal stdout instead of crashing in a driver."""
    if not sys.stdout.isatty():
        raise core.FilesError(
            "browse needs a real terminal (stdout is not a tty)",
            hint="use `levix files search` / `preview` for pipe-friendly output",
        )
    return int(BrowseApp(root).run() or 0)

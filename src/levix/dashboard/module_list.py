"""What the dashboard lists, and what it says about each entry.

The rows are built from manifests only. A module that needs an extra, and a module whose
entry point failed to load, are two different facts and are labelled differently: "type
`pip install \"levix[tube]\"`" is actionable, "failed to load: ImportError(...)" is a bug
report. Collapsing both into "unavailable" would hide the difference from the user.

One manifest field decides membership rather than wording: `UiSpec(mode="hidden")`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..deps import missing
from ..registry import is_broken
from ..terminal import markup_safe

if TYPE_CHECKING:
    from ..module import ModuleManifest
    from ..registry import ModuleRegistry

State = Literal["ready", "extra", "broken"]

STATE_MARK = {"ready": "ready", "extra": "needs install", "broken": "broken"}


@dataclass(frozen=True, slots=True)
class ModuleRow:
    name: str
    title: str
    summary: str
    state: State
    detail: str
    argv: tuple[str, ...]

    @property
    def runnable(self) -> bool:
        return self.state == "ready"

    def label(self) -> str:
        """One line for the list: name, summary, and the state word in colour.

        Name and summary come from a manifest someone else wrote, so they are escaped on
        the way into the markup - a plugin cannot restyle the dashboard or hide text in
        brackets that the core then silently deletes.
        """
        colour = {"ready": "green", "extra": "yellow", "broken": "red"}[self.state]
        width = max(len(self.name), 1)
        return (
            f"[bold]{markup_safe(self.name):<{width}}[/bold]  {markup_safe(self.summary)}  "
            f"[{colour}]{STATE_MARK[self.state]}[/{colour}]"
        )


def row_for(manifest: ModuleManifest) -> ModuleRow:
    if is_broken(manifest):
        return ModuleRow(
            name=manifest.name,
            title=manifest.title,
            summary=manifest.summary,
            state="broken",
            detail=manifest.summary,
            argv=(),
        )
    unmet = missing(manifest.requirements)
    if unmet:
        hint = manifest.resolved_install_hint() or "this module needs an extra installed"
        names = ", ".join(status.describe for status in unmet)
        return ModuleRow(
            name=manifest.name,
            title=manifest.title,
            summary=manifest.summary,
            state="extra",
            detail=f"{names}\n{hint}",
            argv=(manifest.name,),
        )
    return ModuleRow(
        name=manifest.name,
        title=manifest.title,
        summary=manifest.summary,
        state="ready",
        detail="\n".join(part for part in (manifest.summary, _command_note(manifest)) if part),
        argv=(manifest.name,),
    )


def _command_note(manifest: ModuleManifest) -> str:
    names = ", ".join(command.name for command in manifest.commands)
    return f"commands: {names}" if names else ""


def build_rows(registry: ModuleRegistry) -> list[ModuleRow]:
    """Every module the dashboard offers, in name order.

    `UiSpec(mode="hidden")` is the only declaration that changes this list: a module that
    asks not to be offered still runs as `levix <name>`, it just gets no row here. The
    filter lives with the rows rather than in the app so that the list, the filter and the
    "nothing matches" message answer the same question.
    """
    return [
        row_for(manifest)
        for manifest in registry.manifests()
        if manifest.ui is None or manifest.ui.mode != "hidden"
    ]


def filter_rows(rows: list[ModuleRow], needle: str) -> list[ModuleRow]:
    """Case-insensitive substring over name, title and summary; empty needle is a no-op."""
    text = needle.strip().casefold()
    if not text:
        return rows
    return [row for row in rows if text in " ".join((row.name, row.title, row.summary)).casefold()]

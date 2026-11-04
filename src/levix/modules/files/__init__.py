"""LEVIX Files - a fast, honest terminal file manager.

This module is imported by `levix --help`, through the entry point below, so it must
stay pure data: no `typer`, no `textual`, no `shutil`. Everything heavy lives in
`cli.py` (command surface) and `browse.py` (the Textual screen), which the registry
only touches when the user actually runs `levix files ...`.

Safety framing: this module operates on the user's real disk. Read operations are
free, writes refuse silent overwrites, and deletions require a typed confirmation
that `--yes` cannot bypass.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="files",
    title="Files",
    summary="Terminal file manager: browse, search, preview, copy, move, rename, delete.",
    cli_path="levix.modules.files.cli:build_app",
    commands=(
        CommandInfo("browse", "Interactive directory browser (full screen)."),
        CommandInfo("search", "Find files by name, extension or line content."),
        CommandInfo("preview", "Show the head of a text file, or honest metadata."),
        CommandInfo("copy", "Copy a file into a destination, never overwriting silently."),
        CommandInfo("move", "Move a file or directory, never overwriting silently."),
        CommandInfo("rename", "Rename an entry inside its own directory."),
        CommandInfo("delete", "Remove entries; typed confirmation, --recursive for trees."),
    ),
    requirements=(),
    extras=(),
    capabilities=(),
    permissions=frozenset({Permission.FS_READ, Permission.FS_WRITE}),
    ui=UiSpec(mode="suspend", argv=("files", "browse")),
    documentation="docs/modules/FILES.md",
)

"""`levix files` command surface.

Textual is imported *inside* `browse`, and `browse.py` is the only place it appears, so
`levix files -h`, `search`, `preview`, `copy`, `move`, `rename` and `delete` never pay
for it. Every printed dynamic string goes through `show()`: a cp1252 console cannot
encode a fancy file name, and Rich would read `[bold]` inside a file name as markup.

Exit codes come from `levix.errors` only. Failures a user can cause are
`RequestError`/`UnsafePathError` (2, a bad request for this command) and `FilesError`
(1, the filesystem said no); a refused or impossible confirmation is
`UserCancelledError` (6).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from ... import terminal
from ...approve import require_approval
from ...deps import gate
from ...errors import EXIT_INTERRUPTED
from . import MANIFEST, core

console = terminal.new_console()

app = typer.Typer()

#: How many deleted entries we list before switching to "... and N more".
LIST_ITEMS = 25
#: Longest printed line for a `--grep` hit; a minified bundle is not a report.
MAX_LINE_CHARS = 220


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    gate(MANIFEST)


def show(value: object) -> str:
    """Console-safe *and* markup-safe rendering of anything dynamic."""
    return escape(core.printable(value))


def clip(text: str, width: int = MAX_LINE_CHARS) -> str:
    return text if len(text) <= width else f"{text[:width]}..."


def relpath(path: Path, wall: Path) -> str:
    """Path as seen from the wall, so a long root cannot eat the whole table.

    An absolute Windows path inside a temp directory overflows a 79-column table and
    Rich starts eliding exactly the part the user needs to check before a delete.
    """
    try:
        return show(path.relative_to(wall))
    except ValueError:
        return show(path)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="files",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    application.command("browse", help="Interactive directory browser (full screen).")(browse)
    application.command("search", help="Find files by name, extension or line content.")(search)
    application.command("preview", help="Show a text file's head, or honest metadata.")(preview)
    application.command("copy", help="Copy an entry; never overwrites silently.")(copy)
    application.command("move", help="Move an entry; never overwrites silently.")(move)
    application.command("rename", help="Rename inside the entry's own directory.")(rename)
    application.command("delete", help="Remove entries with a typed confirmation.")(delete)
    return application


# ---------------------------------------------------------------------------
# browse


def browse(
    path: str = typer.Argument(
        ".",
        help="Directory to open. Copy and delete inside the browser are confined to it.",
    ),
) -> None:
    """Open the full-screen browser. Keys: enter/o open, p preview, c copy, d delete,
    r reload, ? help, q quit. Refuses to start when stdout is not a terminal."""
    from .browse import run_browse

    root = core.resolve(path)
    core.require_exists(root, label="browse root")
    if not root.is_dir():
        raise core.RequestError(f"browse needs a directory, not a file: {root}")
    run_browse(root)


# ---------------------------------------------------------------------------
# search


def _search_progress() -> Progress:
    """A Rich progress display that also behaves when stdout is a pipe."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("files {task.fields[scanned]}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def search(
    root: str = typer.Argument(".", help="Directory to walk, recursively."),
    pattern: str = typer.Argument(
        "", help="Name substring (or a glob with --glob). Empty lists everything."
    ),
    glob: bool = typer.Option(False, "--glob", "-g", help="Match PATTERN as a glob, e.g. '*.log'."),
    case_sensitive: bool = typer.Option(
        False, "--case-sensitive", help="Distinguish case in names and in content."
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden", help="Include dot-files and Windows hidden entries."
    ),
    ext: Annotated[
        list[str] | None,
        typer.Option("--ext", help="Only this extension; repeatable, or 'py,md'."),
    ] = None,
    limit: int = typer.Option(0, "--limit", "-n", help="Stop after N matches (0 = unlimited)."),
    max_depth: int = typer.Option(
        0, "--max-depth", help="Descend at most this many levels below ROOT (0 = unlimited)."
    ),
    grep: str = typer.Option(
        "", "--grep", help="Search file CONTENT for this text instead of names."
    ),
    grep_regex: bool = typer.Option(
        False, "--grep-regex", help="Treat --grep as a regular expression."
    ),
    max_bytes: int = typer.Option(
        core.DEFAULT_GREP_MAX_BYTES,
        "--max-bytes",
        help="Skip files bigger than this for --grep (0 = no cap).",
    ),
) -> None:
    """Walk a tree and print matches as they are found.

    Symlinked directories are listed but never descended into (os.walk with
    followlinks=False), so a link cycle cannot hang the walk and no file outside ROOT is
    reached through a link. With --grep, a file whose head contains NUL is counted as
    binary and skipped, and so is any file above --max-bytes; neither is silent - both
    appear in the summary. Ctrl+C stops cleanly, keeps what was already printed and
    reports the partial count and elapsed time.
    """
    wall = core.resolve(root)
    if not wall.is_dir():
        raise core.RequestError(f"search needs a directory, not a file: {wall}")

    stats = core.ScanStats()
    limit_value = limit if limit > 0 else None
    depth = max_depth if max_depth > 0 else None
    extensions = tuple(ext or ())

    hits: Iterator[core.Hit]
    if grep:
        hits = core.search_contents(
            wall,
            grep,
            use_regex=grep_regex,
            ignore_case=not case_sensitive,
            include_hidden=include_hidden,
            extensions=extensions,
            max_depth=depth,
            # `0 = no cap` is what the option's own help promises, and `search_contents`
            # honours it (`if max_bytes and …`). A negative value is a typo, not a request
            # to read the disk unbounded, so it falls back to the packaged default.
            max_bytes=max_bytes if max_bytes >= 0 else core.DEFAULT_GREP_MAX_BYTES,
            limit=limit_value,
            stats=stats,
        )
        describe = f"grep {show(grep)} in {show(wall)}"
    else:
        hits = core.search_names(
            wall,
            pattern,
            use_glob=glob,
            ignore_case=not case_sensitive,
            include_hidden=include_hidden,
            extensions=extensions,
            max_depth=depth,
            limit=limit_value,
            stats=stats,
        )
        describe = f"names matching {show(pattern or '(any)')} in {show(wall)}"

    started = time.perf_counter()
    try:
        with _search_progress() as progress:
            task = progress.add_task(describe, total=None, scanned=0)
            for index, hit in enumerate(hits, start=1):
                console.print(_render_hit(hit, wall=wall))
                if index % 32 == 0:
                    progress.update(task, scanned=stats.files_examined)
                # no break here on purpose: the generator stops itself at the limit and
                # records "match limit reached" on the way out. Breaking first would
                # silence the one line that tells the user the count is not the whole
                # answer.
    except KeyboardInterrupt:
        stats.stopped_early = "interrupted by Ctrl+C"
    finally:
        stats.elapsed_seconds = time.perf_counter() - started

    _report_search(stats, describe=describe)
    if stats.stopped_early.startswith("interrupted"):
        raise typer.Exit(code=EXIT_INTERRUPTED)


def _render_hit(hit: core.Hit, *, wall: Path) -> str:
    if isinstance(hit, core.ContentHit):
        return (
            f"[cyan]{show(hit.path.relative_to(wall))}[/cyan]:[yellow]{hit.line_number}[/yellow]: "
            f"{show(clip(core.printable(hit.text)))}"
        )
    label = show(hit.path.relative_to(wall))
    if hit.is_dir:
        return f"[bold blue]{label}/[/bold blue]"
    link = " [dim](link)[/dim]" if hit.is_symlink else ""
    return f"{label} [dim]{core.human_bytes(hit.size_bytes)}[/dim]{link}"


def _report_search(stats: core.ScanStats, *, describe: str) -> None:
    """Count and elapsed, plus every category that was deliberately not searched."""
    console.print(
        f"[bold]{stats.matches} match(es)[/bold] for {describe} in {stats.elapsed_seconds:.2f}s\n"
        f"[dim]{stats.files_examined} file(s) read, {stats.directories_visited} "
        f"directory(ies) walked[/dim]"
    )
    skipped = []
    if stats.skipped_binary:
        skipped.append(f"{stats.skipped_binary} binary (NUL in head)")
    if stats.skipped_too_large:
        skipped.append(f"{stats.skipped_too_large} over the size cap")
    if stats.skipped_hidden:
        skipped.append(f"{stats.skipped_hidden} hidden (use --include-hidden)")
    if stats.skipped_symlink:
        skipped.append(f"{stats.skipped_symlink} symlink(s) not read")
    if skipped:
        console.print("[yellow]skipped:[/yellow] " + ", ".join(skipped))
    if stats.unreadable:
        console.print(f"[yellow]{stats.unreadable} unreadable location(s)[/yellow]")
    for note in stats.errors[:3]:
        console.print(f"[red]! {show(note)}[/red]")
    if stats.stopped_early:
        console.print(f"[yellow]stopped early:[/yellow] {show(stats.stopped_early)}")


# ---------------------------------------------------------------------------
# preview


def preview(
    path: str = typer.Argument(..., help="File (or directory) to describe."),
    lines: int = typer.Option(
        20, "--lines", "-n", help="Head lines to print (0 = as much as the 256 KiB budget holds)."
    ),
    no_line_count: bool = typer.Option(
        False, "--no-line-count", help="Do not read the whole file to count its lines."
    ),
) -> None:
    """Print the head of a text file, or a metadata table for anything else.

    Decoding is attempted as utf-8, then cp1252, then latin-1 with replacement, and the
    encoding actually used is printed - a latin-1 result is flagged as lossy instead of
    presented as truth. Binary files, directories and symlinks are described, never
    dumped.
    """
    target = core.resolve(path)
    core.require_exists(target, label="preview target")
    result = core.preview(target, lines=lines, count_line_total=not no_line_count)

    entry = result.entry
    table = Table(title=f"preview {show(target)}", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("kind", show(entry.kind))
    table.add_row("size", f"{core.human_bytes(entry.size_bytes)} ({entry.size_bytes} bytes)")
    table.add_row("modified", show(entry.modified_text))
    table.add_row("accessed", show(entry.accessed_text))
    table.add_row("created", show(entry.created_text))
    table.add_row("permissions", show(entry.mode))
    if entry.is_symlink:
        table.add_row("link target", show(entry.link_target or "unreadable"))
    if result.kind == "text":
        table.add_row("encoding", show(result.encoding))
        table.add_row(
            "lines", show(f"{result.line_count} counted" if result.counted else "not counted")
        )
    elif result.kind == "binary":
        table.add_row(
            "content", show(f"binary - NUL byte within the first {core.SNIFF_BYTES} bytes")
        )
    elif result.kind == "directory":
        table.add_row("entries", str(len(core.entries_in(target))))
    console.print(table)

    if result.kind != "text":
        console.print(
            "[dim]no text shown: this is not a readable text file. "
            "The table above is all the filesystem will honestly tell us.[/dim]"
        )
        return

    console.print()
    if not result.lines:
        console.print("[dim]    (no lines within the head budget)[/dim]")
    for row in result.lines:
        console.print(f"    {show(clip(core.printable(row), 400))}")
    if result.truncated:
        wider = lines * 4 if lines else 200
        console.print(
            f"[dim]    ... head only; try -n {wider}, or `levix files search --grep`[/dim]"
        )


# ---------------------------------------------------------------------------
# copy / move / rename


def _confirm_overwrite(verb: str, target: Path, *, label: str, yes: bool) -> None:
    """Replacing an existing entry destroys data, so the shared gate decides.

    `destructive=True` is what makes `--yes` useless here: `require_approval` says so
    out loud and falls back to the typed prompt, which a pipe cannot answer.
    """
    require_approval(
        f"overwrite during {verb}",
        f"{label} would be replaced by {core.printable(target)}",
        assume_yes=yes,
        destructive=True,
        prompt_word="OVERWRITE",
    )


def _prepare_write(
    verb: str,
    source_raw: str,
    dest_raw: str,
    *,
    root: str,
    force: bool,
    yes: bool,
) -> tuple[Path, Path | None]:
    """Resolve, apply the wall, and run the confirmation gate when a name collides.

    Without `--force` a collision is refused by `core` (exit 2, "pass --force"); with
    `--force` the user must still type OVERWRITE.
    """
    src = core.resolve(source_raw)
    core.require_exists(src, label="source")
    wall = core.resolve(root) if root else None
    target = core.plan_destination(src, dest_raw, root=wall)
    if force and os.path.lexists(target):
        _confirm_overwrite(verb, target, label=f"{verb} destination", yes=yes)
    return src, wall


def copy(
    source: str = typer.Argument(..., help="File or directory to copy."),
    destination: str = typer.Argument(..., help="Destination path, or a directory to copy into."),
    root: str = typer.Option(
        "", "--root", help="Refuse a destination outside this directory (no wall by default)."
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Replace an existing destination; still asks you to confirm."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Cannot authorize an overwrite."),
) -> None:
    """Copy with `shutil.copy2` (times preserved), or `copytree(symlinks=True)` for a tree.

    An existing destination is refused unless --force is given, and --force then runs the
    shared confirmation gate: a run without a terminal is a refusal, not a consent.
    Relative paths resolve against the current directory; --root only moves the wall.
    """
    src, wall = _prepare_write("copy", source, destination, root=root, force=force, yes=yes)
    result = core.copy_entry(src, destination, root=wall, force=force)
    console.print(
        f"[green]{result.verb}[/green] {show(result.source)} -> {show(result.destination)} "
        f"({core.human_bytes(result.bytes_moved)})"
    )


def move(
    source: str = typer.Argument(..., help="File or directory to move."),
    destination: str = typer.Argument(..., help="Destination path, or a directory to move into."),
    root: str = typer.Option("", "--root", help="Refuse a destination outside this directory."),
    force: bool = typer.Option(
        False, "--force", "-f", help="Replace an existing destination; still asks you to confirm."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Cannot authorize an overwrite."),
) -> None:
    """Move with `shutil.move`, which copies across filesystems and renames within one.

    Same overwrite rule as `copy`: no silent replacement, and --force still confirms.
    """
    src, wall = _prepare_write("move", source, destination, root=root, force=force, yes=yes)
    result = core.move_entry(src, destination, root=wall, force=force)
    console.print(
        f"[green]{result.verb}[/green] {show(result.source)} -> {show(result.destination)} "
        f"({core.human_bytes(result.bytes_moved)})"
    )


def rename(
    path: str = typer.Argument(..., help="The entry to rename."),
    new_name: str = typer.Argument(..., help="Bare new name - no separators, no drive letter."),
    root: str = typer.Option(
        "", "--root", help="Extra wall; the entry's own directory already is one by default."
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Replace an existing name; still asks you to confirm."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Cannot authorize an overwrite."),
) -> None:
    """Rename in place with `os.rename`.

    The name is validated before anything is touched: empty, `.`, `..`, a path
    separator, a drive or UNC prefix, a trailing dot or space, a reserved Windows device
    name and an over-long name are all refused - which is what makes it impossible to
    turn a rename into a move or into an escape from the directory.
    """
    source = core.to_path(path).resolve(strict=False)
    core.require_exists(source, label="path")
    wall = core.resolve(root) if root else None
    landing = source.parent / core.validate_new_name(new_name)
    if force and os.path.lexists(landing):
        _confirm_overwrite("rename", landing, label="existing entry", yes=yes)
    result = core.rename_entry(path, new_name, root=wall, force=force)
    console.print(
        f"[green]{result.verb}[/green] {show(result.source.name)} -> "
        f"[bold]{show(result.destination.name)}[/bold]  in {show(result.destination.parent)}"
    )


# ---------------------------------------------------------------------------
# delete


def delete(
    typer_ctx: typer.Context,
    paths: Annotated[
        list[str],
        typer.Argument(metavar="PATH...", help="Entries to remove."),
    ],
    root: str = typer.Option(
        ".", "--root", help="Wall: nothing outside this directory may be deleted."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="Required to remove a directory that has entries."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accepted and ignored: --yes cannot authorize a delete."
    ),
) -> None:
    """Remove entries, but only after a typed confirmation in a real terminal.

    The plan is measured and printed first (file count, directory count, bytes), then
    `levix.approve.require_approval` runs with destructive=True: you must type DELETE,
    --yes is refused by design, and a run without a terminal exits 6 having removed
    nothing. Symlinks are removed as links, never as their targets.
    """
    wall = core.resolve(root)
    plan = core.plan_delete(paths, root=wall, recursive=recursive)
    for extra in plan.covered:
        console.print(
            f"[yellow]note:[/yellow] {show(extra)} is inside another listed path, "
            "so it is covered by that deletion"
        )
    console.print(_plan_table(plan))
    require_approval("delete", plan.describe(), assume_yes=yes, destructive=True)

    removed, reclaimed, failures = core.execute_delete(plan)
    for item in removed[:LIST_ITEMS]:
        marker = "/" if item.is_dir else ""
        console.print(f"[red]removed[/red] {show(relpath(item.path, plan.wall))}{marker}")
    if len(removed) > LIST_ITEMS:
        console.print(f"[dim]... and {len(removed) - LIST_ITEMS} more[/dim]")
    console.print(
        f"[bold]{len(removed)}[/bold] entry(ies) removed, {core.human_bytes(reclaimed)} "
        f"reclaimed ({reclaimed} bytes)"
    )
    obj = getattr(typer_ctx, "obj", None)
    if obj is not None:
        obj.logger.warning(
            "files delete: %s entries removed, %s bytes reclaimed under %s",
            len(removed),
            reclaimed,
            plan.wall,
        )
    for note in failures:
        console.print(f"[yellow]not removed:[/yellow] {show(note)}")
    if failures:
        raise core.FilesError(
            f"{len(failures)} of {len(plan.items)} entries could not be removed",
            hint=(
                "on Windows a file in use, a read-only entry or a locked folder is the usual cause"
            ),
        )


def _plan_table(plan: core.DeletePlan) -> Table:
    table = Table(
        title=f"about to delete {show(plan.describe())}",
        header_style="bold cyan",
        title_style="bold red",
    )
    table.add_column("kind", width=9)
    table.add_column("size", justify="right")
    table.add_column("entry", overflow="ellipsis")
    for item in plan.items[:LIST_ITEMS]:
        table.add_row(
            "dir" if item.is_dir else "file",
            core.human_bytes(item.size_bytes),
            show(relpath(item.path, plan.wall)),
        )
    if len(plan.items) > LIST_ITEMS:
        table.add_row("...", "-", f"[dim]and {len(plan.items) - LIST_ITEMS} more[/dim]")
    return table

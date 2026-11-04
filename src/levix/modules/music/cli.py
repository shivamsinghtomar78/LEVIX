"""`levix music` command surface.

Nothing here imports `sounddevice` or `soundfile` - both are reached only through
`core`, and the decoder through the two commands that need it - so `levix music -h` costs
no PortAudio. Windows consoles are cp1252, so bars come from `terminal.bar()` and every
name passes through `core.safe_text()`; `levix.main` turns a `LevixError` into one clean
message and the exit code documented in `docs/modules/MUSIC.md`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ... import terminal
from ...approve import require_approval
from ...context import LevixContext
from ...deps import gate
from ...errors import EXIT_INTERRUPTED, LevixError
from . import MANIFEST, core

if TYPE_CHECKING:
    import numpy as np

console = Console()

playlist_app = typer.Typer(
    name="playlist",
    help="Queue held in LEVIX's shared database: list, add, remove, clear, play.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    gate(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="music",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    surface: dict[str, object] = {
        "play": play,
        "info": info,
        "devices": devices,
        "library": library,
        "playlist": playlist_app,
    }
    # Registering from the manifest keeps `levix music -h`, the dashboard and
    # `levix plugins list` reading one list of commands.
    for command in MANIFEST.commands:
        target = surface[command.name]
        if isinstance(target, typer.Typer):
            application.add_typer(target, name=command.name, help=command.help)
        else:
            # Typer's stub types `command()` only for the literal decorator form; a
            # manifest-driven lookup is the same object at runtime.
            application.command(command.name, help=command.help)(target)  # type: ignore[type-var]
    return application


# ----------------------------------------------------------------------------------
# plumbing
# ----------------------------------------------------------------------------------


def _ctx(typer_ctx: typer.Context) -> LevixContext:
    obj = getattr(typer_ctx, "obj", None)
    if isinstance(obj, LevixContext):
        return obj
    # The router forwards `obj=ctx.obj`, so a real `levix music ...` takes the branch
    # above. This one is for a test or a debugger that runs the sub-app with no parent:
    # building the context here is what still honours music.volume/library_dir instead of
    # silently reading built-in defaults.
    from ...app import build_context

    return build_context()


def _volume(context: LevixContext, requested: float) -> float:
    """--volume wins; music.volume otherwise, and both through the same validator."""
    return core.validate_volume(requested if requested >= 0 else context.value("music.volume"))


def _prepare(file: Path, *, gain: float, rate: int) -> tuple[np.ndarray, int, core.AudioInfo]:
    frames, samplerate, info = core.load(file, volume=gain)
    if rate:
        target = core.validate_rate(rate)
        frames = core.resample(frames, samplerate, target)
        samplerate = target
    return frames, samplerate, info


def _show(value: object) -> str:
    """A name from disk or PortAudio, printed as written.

    Rich reads the `[live]` inside a real file name as a style tag and deletes it, and
    `core.safe_text` covers the encoding half. Both belong to every dynamic value below.
    """
    return escape(core.safe_text(value if isinstance(value, str) else str(value)))


def _line(info: core.AudioInfo, samplerate: int, gain: float) -> str:
    return (
        f"[bold]{_show(info.path.name)}[/bold]  {info.format}/{info.subtype or '-'}  "
        f"{samplerate} Hz  {info.channels} ch  {core.format_duration(info.duration)}  "
        f"gain {gain:.2f}"
    )


def _clip(text: str, width: int) -> str:
    """Truncate with ASCII, never Rich's U+2026: a cp1252 console cannot encode it."""
    safe = _show(text)
    return safe if len(safe) <= width else safe[: width - 1] + "+"


class _Progress:
    """One redrawn line while sound is streaming, and nothing when the stream is captured.

    A pipe cannot show a moving bar, and a bar per callback would bury the caller, so
    updates are throttled to a tenth of a second and skipped off a terminal.
    """

    def __init__(self) -> None:
        self._last = 0.0

    def __call__(self, written: int, total: int) -> None:
        if not console.is_terminal:
            return
        percent = core.progress_percent(written, total)
        now = time.perf_counter()
        if percent < 100.0 and now - self._last < 0.1:
            return
        self._last = now
        console.print(
            f"\rplaying {terminal.bar(percent, 24)} {written}/{total} frames",
            end="",
            highlight=False,
        )

    def finish(self) -> None:
        if console.is_terminal:
            console.print()


def _deliver(
    frames: np.ndarray, *, samplerate: int, device: int, blocksize: int, progress: _Progress
) -> int:
    """Hand the frames to the one hardware seam; Ctrl+C becomes a clean exit 130."""
    try:
        written = core.play_samples(
            frames,
            samplerate,
            device=None if device < 0 else device,
            blocksize=blocksize,
            on_block=progress,
        )
    except KeyboardInterrupt:
        progress.finish()
        console.print("[yellow]interrupted: the stream closed, so the device is free[/yellow]")
        raise typer.Exit(code=EXIT_INTERRUPTED) from None
    progress.finish()
    return written


# ----------------------------------------------------------------------------------
# play / info
# ----------------------------------------------------------------------------------


def play(
    typer_ctx: typer.Context,
    file: Path = typer.Argument(..., help="One audio file."),
    device: int = typer.Option(-1, "--device", "-d", help="Output device index, -1 = default."),
    rate: int = typer.Option(0, "--rate", "-r", help="Resample to this Hz, 0 = the file's."),
    volume: float = typer.Option(-1.0, "--volume", "-v", help="0.0-1.0, default music.volume."),
    blocksize: int = typer.Option(0, "--block", help="Frames per callback, 0 = the device's."),
) -> None:
    """Decode a file with libsndfile and play it on this machine's audio output."""
    gain = _volume(_ctx(typer_ctx), volume)
    frames, samplerate, report = _prepare(file, gain=gain, rate=rate)
    console.print(_line(report, samplerate, gain))
    where = "the default output device" if device < 0 else f"device {device}"
    console.print(f"[dim]{report.codec_note}; output: {where}[/dim]")
    written = _deliver(
        frames, samplerate=samplerate, device=device, blocksize=blocksize, progress=_Progress()
    )
    console.print(
        f"[green]done[/green] {written:,} frames "
        f"({core.format_duration(core.duration_for(written, samplerate))}) at {samplerate} Hz"
    )


def info(file: Path = typer.Argument(..., help="One audio file.")) -> None:
    """What libsndfile says about the file, and whether it can be played here."""
    report = core.inspect_file(file)
    table = Table(title="Audio file", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("path", _show(report.path))
    table.add_row("format", f"{report.format} / {report.subtype or '-'}")
    table.add_row("samplerate", f"{report.samplerate:,} Hz")
    table.add_row("channels", str(report.channels))
    table.add_row("frames", f"{report.frames:,} frames")
    table.add_row("duration", core.format_duration(report.duration))
    table.add_row("size", core.human_bytes(report.path.stat().st_size))
    table.add_row("decoder", core.decoder_version())
    console.print(table)
    console.print(f"[dim]{report.codec_note}[/dim]")


# ----------------------------------------------------------------------------------
# devices
# ----------------------------------------------------------------------------------


def devices(
    kind: str = typer.Option("all", "--kind", help="all, output or input."),
) -> None:
    """List the devices PortAudio reports, including the ones it cannot use."""
    wanted = kind.strip().lower()
    if wanted not in ("all", "output", "input"):
        raise core.RequestError(
            f"--kind must be all, output or input, got {kind!r}",
            hint="`--kind output` is what you want before choosing a --device number",
        )
    listing = core.list_devices()
    rows = [
        row
        for row in listing.rows
        if wanted == "all" or (row.max_output if wanted == "output" else row.max_input)
    ]
    table = Table(title=f"Audio devices ({wanted})", header_style="bold cyan")
    table.add_column("idx", justify="right")
    table.add_column("name")
    table.add_column("host API")
    table.add_column("in", justify="right")
    table.add_column("out", justify="right")
    table.add_column("default Hz", justify="right")
    table.add_column("role")
    table.add_column("default")
    for row in rows:
        table.add_row(
            str(row.index),
            _clip(row.name, 44),
            _show(row.host_api),
            str(row.max_input),
            str(row.max_output),
            f"{row.default_samplerate:,.0f}",
            row.role,
            listing.mark(row) or "-",
        )
    if not rows:
        table.add_row(
            "-",
            f"[cyan]no {wanted} device reported by PortAudio[/cyan]",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
        )
    console.print(table)
    console.print(
        f"[dim]{len(rows)} of {len(listing.rows)} device(s) shown; "
        f"default output: {_show(listing.name_of(listing.default_output))}; "
        f"default input: {_show(listing.name_of(listing.default_input))}[/dim]"
    )
    note = listing.note()
    if note:
        console.print(f"[yellow]note:[/yellow] {note}")


# ----------------------------------------------------------------------------------
# library
# ----------------------------------------------------------------------------------


def library(
    typer_ctx: typer.Context,
    root: Path = typer.Option(None, "--root", help="Scan this instead of music.library_dir."),
    suffix: list[str] = typer.Option([], "--suffix", help="Only these extensions, repeatable."),
    limit: int = typer.Option(25, "--limit", "-n", help="Track rows to print, 0 = all."),
    include_hidden: bool = typer.Option(False, "--include-hidden", help="Scan dot entries too."),
) -> None:
    """Walk the library folder and print what can actually be played."""
    configured = str(_ctx(typer_ctx).value("music.library_dir") or "")
    base = core.library_root(configured, root)
    if base is None:
        console.print("[yellow]music.library_dir is not set, so there is nothing to scan.[/yellow]")
        console.print(
            "[dim]set it with `levix config set music.library_dir PATH`, or pass --root DIR "
            "for a one-off listing[/dim]"
        )
        return
    wanted = {item.lstrip(".").lower() for item in suffix if item.strip()} or None
    found = core.scan_library(base, suffixes=wanted, include_hidden=include_hidden)

    shown = found.tracks if limit <= 0 else found.tracks[:limit]
    table = Table(title=f"Library: {core.safe_name(base)}", header_style="bold cyan")
    table.add_column("file")
    table.add_column("format")
    table.add_column("Hz", justify="right")
    table.add_column("ch", justify="right")
    table.add_column("length", justify="right")
    table.add_column("size", justify="right")
    for track in shown:
        table.add_row(
            _clip(found.display(track.path), 52),
            f"{track.format}/{track.subtype or '-'}",
            f"{track.samplerate:,}",
            str(track.channels),
            core.format_duration(track.duration),
            core.human_bytes(track.size_bytes),
        )
    if not found.tracks:
        table.add_row(f"[cyan]no playable file under {_show(base)}[/cyan]", "-", "-", "-", "-", "-")
    console.print(table)

    folders = found.by_directory()
    if folders:
        totals = Table(title="Per directory", header_style="bold cyan")
        totals.add_column("directory")
        totals.add_column("tracks", justify="right")
        totals.add_column("length", justify="right")
        for folder, count, seconds in folders:
            label = found.display(folder) if folder != base else "."
            totals.add_row(
                _clip(core.safe_text(label), 60), str(count), core.format_duration(seconds)
            )
        console.print(totals)

    if len(found.tracks) > len(shown):
        console.print(f"[dim]... {len(found.tracks) - len(shown)} more; --limit 0 shows all[/dim]")
    console.print(
        f"[dim]{len(found.tracks)} track(s), {core.format_duration(found.total_duration)} total; "
        f"{found.directories} folder(s) walked, {found.files_examined} file(s) examined, "
        f"{found.skipped_suffix} of another type[/dim]"
    )
    if found.unreadable:
        console.print(
            f"[yellow]{len(found.unreadable)} file(s) looked like audio "
            "but did not decode:[/yellow]"
        )
        for path, reason in found.unreadable[:8]:
            console.print(f"  [red]x[/red] {_clip(found.display(path), 52)}: {_show(reason)}")
        if len(found.unreadable) > 8:
            console.print(f"  [dim]... {len(found.unreadable) - 8} more[/dim]")
    if found.skipped_hidden and not include_hidden:
        console.print("[dim]hidden entries were skipped; add --include-hidden to see them[/dim]")


# ----------------------------------------------------------------------------------
# playlist
# ----------------------------------------------------------------------------------


@playlist_app.command("list")
def playlist_list(typer_ctx: typer.Context) -> None:
    """Show the queue in the order `play` will use it."""
    queue = core.list_playlist(_ctx(typer_ctx).database)
    table = Table(title="Playlist", header_style="bold cyan")
    table.add_column("id", justify="right")
    table.add_column("file")
    table.add_column("added")
    table.add_column("state")
    for entry in queue:
        # Clipping an absolute path from the left keeps its directories and cuts off the
        # part that names the file, which on a Windows temp path is everything after
        # character 40. The name carries the row; the folder is the disambiguating detail.
        table.add_row(
            str(entry.id),
            f"{_clip(entry.path.name, 40)}\n[dim]{_clip(str(entry.path.parent), 40)}[/dim]",
            entry.added_at,
            "ok" if entry.exists else "[red]missing[/red]",
        )
    if not queue:
        table.add_row("-", "[cyan]empty: levix music playlist add FILE[/cyan]", "-", "-")
    console.print(table)
    console.print(f"[dim]{len(queue)} entry(ies) in the shared LEVIX database[/dim]")


@playlist_app.command("add")
def playlist_add(
    typer_ctx: typer.Context,
    files: list[Path] = typer.Argument(..., help="One or more audio files to queue."),
) -> None:
    """Queue files, rejecting names that are not real files before anything is stored."""
    result = core.add_to_playlist(_ctx(typer_ctx).database, files)
    for entry in result.added:
        console.print(f"[green]+[/green] {entry.id}  {_show(entry.path)}")
    for name in result.duplicate:
        console.print(f"[yellow]=[/yellow] already queued: {_show(name)}")
    console.print(f"[dim]added {len(result.added)}, already queued {len(result.duplicate)}[/dim]")


@playlist_app.command("remove")
def playlist_remove(
    typer_ctx: typer.Context,
    ids: list[int] = typer.Argument(..., help="Row ids, as shown by `playlist list`."),
) -> None:
    """Drop rows by id."""
    removed, missing = core.remove_from_playlist(_ctx(typer_ctx).database, ids)
    for entry in removed:
        console.print(f"[red]-[/red] {entry.id}  {_show(entry.path)}")
    for wanted in missing:
        console.print(f"[yellow]![/yellow] no playlist row with id {wanted}")
    console.print(f"[dim]{len(removed)} removed, {len(missing)} not found[/dim]")


@playlist_app.command("clear")
def playlist_clear(
    typer_ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Cannot bypass a destructive prompt."),
) -> None:
    """Forget the whole queue. The files themselves are never touched."""
    database = _ctx(typer_ctx).database
    count = core.count_playlist(database)
    if count == 0:
        console.print("[dim]the playlist is already empty; nothing was changed[/dim]")
        return
    require_approval(
        "clear the playlist",
        f"{count} queued entry(ies) will be forgotten (the files stay on disk)",
        assume_yes=yes,
        destructive=True,
    )
    console.print(f"[red]-[/red] playlist cleared: {core.clear_playlist(database)} entry(ies)")


@playlist_app.command("play")
def playlist_play(
    typer_ctx: typer.Context,
    device: int = typer.Option(-1, "--device", "-d", help="Output device index, -1 = default."),
    rate: int = typer.Option(0, "--rate", "-r", help="Resample to this Hz, 0 = each file's."),
    volume: float = typer.Option(-1.0, "--volume", "-v", help="0.0-1.0, default music.volume."),
    blocksize: int = typer.Option(0, "--block", help="Frames per callback, 0 = the device's."),
) -> None:
    """Play the queue in order; a file that cannot be decoded is skipped with a warning."""
    context = _ctx(typer_ctx)
    gain = _volume(context, volume)
    queue = core.list_playlist(context.database)
    if not queue:
        console.print(
            "[yellow]the playlist is empty.[/yellow] Add to it with "
            "`levix music playlist add FILE`."
        )
        return
    console.print(f"[dim]{len(queue)} queued entry(ies), gain {gain:.2f}[/dim]")
    played = skipped = 0
    for entry in queue:
        if not entry.exists:
            console.print(f"[yellow]skipped[/yellow] {_show(entry.path)}: gone from disk")
            skipped += 1
            continue
        try:
            frames, samplerate, report = _prepare(entry.path, gain=gain, rate=rate)
        except LevixError as exc:
            console.print(f"[yellow]skipped[/yellow] {_show(entry.path)}: {_show(exc.message)}")
            skipped += 1
            continue
        console.print(_line(report, samplerate, gain))
        _deliver(
            frames,
            samplerate=samplerate,
            device=device,
            blocksize=blocksize,
            progress=_Progress(),
        )
        played += 1
    console.print(f"[green]done[/green] {played} played, {skipped} skipped of {len(queue)}")

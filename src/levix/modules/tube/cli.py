"""`levix tube` command surface.

`core` is imported at module level but contains no yt-dlp import, so `levix tube -h`
still costs nothing: yt-dlp is only touched once a command actually reaches `_make_ydl`.

Windows consoles are cp1252 and Rich's win32 writer raises UnicodeEncodeError on a
box-drawing character, so the progress bar comes from `terminal.bar` and nothing here
prints a non-ASCII glyph.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from ... import terminal
from ...deps import gate
from ...errors import ConfigError, ExternalToolError, ProviderError
from . import MANIFEST, core

console = Console()

PLAYLIST_WARNING = (
    "[yellow]--playlist:[/yellow] one playlist is many requests - the listing plus a "
    "request per entry, and a download per file. Use it only for material you are "
    "allowed to fetch, and expect the site to rate-limit a run like this."
)


def _show(value: object) -> str:
    """Text that came from the site or the filesystem, made safe to print.

    Two crashes are closed here. Rich reads the `[abcdef]` inside a real file name as a
    style tag and silently eats it, so the report no longer matches the file on disk;
    and a cp1252 console raises UnicodeEncodeError on the emoji a title carries. Every
    dynamic value below goes through this, and nothing else is printed raw.
    """
    return escape(terminal.encode_safe(value if isinstance(value, str) else str(value)))


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    gate(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="tube",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    surface = {"info": info, "download": download, "play": play}
    for command in MANIFEST.commands:
        # Registering from the manifest keeps `levix tube -h` and the dashboard's view
        # of this module from ever disagreeing. Typer's command() has no alias
        # parameter, so a shorthand would have to be registered twice and drift.
        # Typer's stub types `command()` only for the literal decorator form; a
        # manifest-driven lookup is the same object at runtime.
        application.command(command.name, help=command.help)(surface[command.name])  # type: ignore[type-var]
    return application


# ----------------------------------------------------------------------------------
# info
# ----------------------------------------------------------------------------------


def info(
    typer_ctx: typer.Context,
    url: str = typer.Argument(help="The page or media URL to inspect."),
    formats: bool = typer.Option(False, "--formats", help="Also show every format reported."),
    playlist: bool = typer.Option(False, "--playlist", help="Let a playlist URL stay a list."),
    allow_file_url: bool = typer.Option(
        False,
        "--allow-file-url",
        help="Permit a file:// URL, which yt-dlp disables by default.",
    ),
) -> None:
    """What a URL is, before spending any bandwidth on it."""
    options = core.build_options(_plan(typer_ctx), playlist=playlist, allow_file_url=allow_file_url)
    summary = core.summarize(core.probe(url, options))
    console.print(_media_table(summary))
    if summary.entry_count is not None:
        console.print(
            f"[yellow]this is a playlist of {summary.entry_count} entries[/yellow] - "
            "metadata only; run info on one entry, or pass --playlist to download"
        )
    elif formats:
        console.print(_formats_table(summary))
    _ffmpeg_note()


def _media_table(summary: core.MediaSummary) -> Table:
    # Both ends of the range are optional: a site that reports no filesize reports none
    # for every format, and `human_bytes` has no answer for "unknown".
    if summary.smallest is None or summary.largest is None:
        size = "not reported by this site"
    elif summary.smallest == summary.largest:
        size = core.human_bytes(summary.largest)
    else:
        size = f"{core.human_bytes(summary.smallest)} - {core.human_bytes(summary.largest)}"
    table = Table(title="Tube / media", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("title", _show(summary.title))
    table.add_row("id", _show(summary.media_id))
    table.add_row("extractor", _show(summary.extractor))
    table.add_row("url", _show(summary.webpage_url or "not reported"))
    table.add_row("duration", _show(core.human_clock(summary.duration)))
    table.add_row("uploader", _show(summary.uploader or "not reported"))
    table.add_row("resolution", _show(summary.resolution or "not reported"))
    table.add_row("size range", _show(size))
    if summary.entry_count is not None:
        table.add_row("entries", str(summary.entry_count))
    return table


def _formats_table(summary: core.MediaSummary) -> Table:
    table = Table(
        title=f"Formats for {_show(summary.title)} ({len(summary.rows)} reported)",
        header_style="bold cyan",
    )
    for column, width in (
        ("id", 12),
        ("ext", 8),
        ("res", 12),
        ("fps", 7),
        ("vcodec", 12),
        ("acodec", 12),
        ("bitrate", 13),
        ("size", 11),
    ):
        table.add_column(column, overflow="ellipsis", max_width=width)
    table.add_column("note", overflow="fold")
    for row in summary.rows:
        table.add_row(
            _show(row.format_id),
            _show(row.extension),
            _show(row.resolution),
            _show(row.fps),
            _show(row.vcodec),
            _show(row.acodec),
            _show(row.bitrate),
            _show(row.size),
            _show(row.note),
        )
    if not summary.rows:
        table.add_row("-", "-", "no format reported", "-", "-", "-", "-", "-", "-")
    return table


# ----------------------------------------------------------------------------------
# download
# ----------------------------------------------------------------------------------


def download(
    typer_ctx: typer.Context,
    url: str = typer.Argument(help="The page or media URL to download."),
    output: str = typer.Option(
        "",
        "-o",
        "--output",
        help="Directory to write to (default: tube.output_dir, else ~/Downloads).",
    ),
    format_spec: str = typer.Option(
        "",
        "--format",
        "-f",
        help="best | video | audio, or an explicit yt-dlp selector (default: tube.default_format).",
    ),
    playlist: bool = typer.Option(
        False, "--playlist", help="Opt in to fetching every entry of a playlist URL."
    ),
    convert_to: str = typer.Option(
        "", "--convert-to", help=f"Audio codec to extract: {', '.join(core.CONVERTIBLE)}."
    ),
    allow_file_url: bool = typer.Option(
        False,
        "--allow-file-url",
        help="Permit a file:// URL, which yt-dlp disables by default.",
    ),
) -> None:
    """Fetch one video (or an opted-in playlist) into a local directory."""
    convert = _validate_convert(convert_to)
    requested = format_spec or _configured(typer_ctx, "tube.default_format", "best")
    if convert and not format_spec:
        # Asking for a converted audio file means the audio is what is wanted; picking
        # it here beats letting a merged video format be downloaded and then stripped.
        requested = "audio"
    has_ffmpeg = core.ffmpeg_path() is not None
    plan = core.plan_format(requested, has_ffmpeg=has_ffmpeg, convert_to=convert)
    core.ensure_ffmpeg(plan, has_ffmpeg=has_ffmpeg)

    directory, source = core.resolve_output_dir(
        output, _configured(typer_ctx, "tube.output_dir", "")
    )
    core.ensure_output_dir(directory)
    if plan.note:
        console.print(f"[yellow]note:[/yellow] {_show(plan.note)}")
    console.print(f"[dim]writing to {_show(directory)} (from {_show(source)})[/dim]")
    if playlist:
        console.print(PLAYLIST_WARNING)

    options = core.build_options(
        plan, output_dir=directory, playlist=playlist, allow_file_url=allow_file_url
    )
    states: list[core.ProgressState] = []
    live = Live(console=console, auto_refresh=False, transient=False)
    options["progress_hooks"].append(_progress_hook(live, states))
    with live:
        result = core.fetch(url, options)
    if not console.is_terminal and states:
        # A captured stream receives the final frame without a line break of its own,
        # so the summary must not start on the same line as the bar.
        console.print()

    _report_download(result, states, directory)


def _progress_hook(
    live: Live, states: list[core.ProgressState]
) -> Callable[[dict[str, Any]], None]:
    def hook(raw: dict[str, Any]) -> None:
        state = core.progress_from_hook(raw)
        states.append(state)
        # A captured stream cannot show an animation, so only a real terminal repaints;
        # Live prints the final frame once when the block ends.
        live.update(Text.from_markup(core.progress_text(state)), refresh=console.is_terminal)

    return hook


def _report_download(result: dict, states: list[core.ProgressState], directory: Path) -> None:
    # The info dict carries a destination path only on some branches, while every
    # progress hook reports one - including "has already been downloaded". Falling back
    # to the directory would print a folder in the "file" row and imply it was fetched.
    path = core.final_path(result) or core.hook_path(states) or ""
    moved = core.transferred(states)
    destination = Path(path) if path else None
    if destination is not None and not moved and destination.is_file():
        console.print(
            f"[yellow]already present, nothing was fetched:[/yellow] {_show(path)}\n"
            "[dim]yt-dlp does not overwrite a file it already has; delete it to refetch.[/dim]"
        )
    size = destination.stat().st_size if destination is not None and destination.is_file() else None
    summary = core.summarize(result)
    table = Table(title="Tube / downloaded", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("title", _show(summary.title))
    table.add_row("file", _show(path) or f"{_show(directory)} (no destination reported)")
    table.add_row("on disk", _show(core.human_bytes(size) if size is not None else "not reported"))
    table.add_row("format", _show(result.get("format") or result.get("format_id") or "-"))
    table.add_row(
        "bytes moved",
        "yes" if moved else "no - the file was already there" if states else "not reported",
    )
    table.add_row("progress hook calls", str(len(states)))
    console.print(table)


def _validate_convert(value: str) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text not in core.CONVERTIBLE:
        raise typer.BadParameter(
            f"--convert-to must be one of: {', '.join(core.CONVERTIBLE)}"
        ) from None
    return text


# ----------------------------------------------------------------------------------
# play
# ----------------------------------------------------------------------------------


def play(
    typer_ctx: typer.Context,
    url: str = typer.Argument(help="The page or media URL to play."),
    player: str = typer.Option(
        "", "--player", help="Player command to use instead of searching PATH."
    ),
) -> None:
    """Resolve the stream and hand its URL to a player process. Nothing is written."""
    found, searched = core.find_player(player)
    if found is None:
        raise ExternalToolError(
            f"no media player found on PATH: looked for {', '.join(searched)}.\n"
            "  install one of them (mpv suits a terminal best), or run\n"
            f"  `levix tube download {url}` and open the file with any player",
            hint=f"levix tube download {url}",
        )
    options = core.build_options(core.single_file_plan())
    info_dict = core.probe(url, options)
    target = core.stream_url(info_dict)
    if target is None:
        raise ProviderError(
            f"{core.summarize(info_dict).title}: no single-file stream URL was reported, "
            "so there is nothing to hand a player. Use `levix tube download` instead."
        )
    argv = core.player_command(found, target)
    console.print(
        f"[dim]player:[/dim] {_show(found)}  [dim]format:[/dim] {_show(options['format'])}"
    )
    console.print("[dim]running:[/dim] " + _show(" ".join(repr(part) for part in argv)))
    code = core.launch(argv)
    if code != 0:
        raise ExternalToolError(f"{found} exited with code {code}")


# ----------------------------------------------------------------------------------
# configuration plumbing
# ----------------------------------------------------------------------------------


def _plan(typer_ctx: typer.Context) -> core.FormatPlan:
    has_ffmpeg = core.ffmpeg_path() is not None
    return core.plan_format(
        _configured(typer_ctx, "tube.default_format", "best"), has_ffmpeg=has_ffmpeg
    )


def _ffmpeg_note() -> None:
    """Say what is unavailable here, with the command that would fix it. Never a guess."""
    if core.ffmpeg_path():
        return
    console.print(
        "[yellow]note:[/yellow] ffmpeg is not installed, so merging separate video and "
        "audio streams and converting audio are both unavailable here.\n"
        f"  install it with: {core.install_command_for()}\n"
        "[dim]single-file downloads work without it.[/dim]"
    )


def _configured(typer_ctx: typer.Context, dotted: str, fallback: str) -> str:
    obj = getattr(typer_ctx, "obj", None)
    if obj is None:
        return fallback
    try:
        value = obj.value(dotted)
    except (ConfigError, TypeError, ValueError):
        # The engine validates configuration; a bad value must not stop a download.
        return fallback
    return str(value) if value else fallback

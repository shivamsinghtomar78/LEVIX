"""`levix hacker` command surface.

Three commands, all read-only. `core` is standard library only, so importing it here
costs nothing, and this whole file stays unreachable until someone actually types
`levix hacker`: the manifest in `__init__.py` is all that `levix --help` reads.

Windows consoles are cp1252 and Rich's win32 writer raises UnicodeEncodeError on a
box-drawing character, so every glyph here comes from `terminal.active_glyphs()` or is
plain ASCII. Nothing prints a credential and nothing opens a socket.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Sequence

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from ... import terminal
from ...deps import ensure_dependencies
from ...errors import ConfigError
from . import MANIFEST, core

console = Console()

FPS_MIN = 1
FPS_MAX = 120
DENSITY_MIN = 0.001
DENSITY_MAX = 0.5

_LEVEL_STYLES: dict[int, str] = {
    core.HEAD: "bold bright_green",
    core.NEAR: "bright_green",
    core.TAIL: "green",
    core.FAINT: "dim green",
}


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    ensure_dependencies(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="hacker",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    surface = {"matrix": matrix, "info": info, "network": network}
    for command in MANIFEST.commands:
        # Registering from the manifest is what keeps `levix hacker -h` and the
        # dashboard's list of this module from ever disagreeing.
        application.command(command.name, help=command.help)(surface[command.name])
    return application


# ----------------------------------------------------------------------------------
# matrix
# ----------------------------------------------------------------------------------


def matrix(
    typer_ctx: typer.Context,
    duration: float = typer.Option(
        0.0, "--duration", help="Stop after this many seconds (0 = no time limit)."
    ),
    iterations: int = typer.Option(
        0, "--iterations", help="Stop after this many frames (0 = no frame limit)."
    ),
    density: float = typer.Option(
        0.0, "--density", help="Per-column spawn chance (0 uses hacker.matrix_density)."
    ),
    fps: int = typer.Option(0, "--fps", help="Frames per second (0 uses hacker.matrix_fps)."),
    seed: int = typer.Option(
        -1, "--seed", help="Reproducible rain for one seed (-1 = different each run)."
    ),
    width: int = typer.Option(0, "--width", help="Columns to draw (0 = terminal width)."),
    height: int = typer.Option(0, "--height", help="Rows to draw (0 = terminal height - 2)."),
) -> None:
    """The Matrix rain, rendered with Rich Live. q or Ctrl+C stops it."""
    fps_value = _validate_fps(fps or _configured(typer_ctx, "hacker.matrix_fps", 30.0))
    density_value = _validate_density(
        density or _configured(typer_ctx, "hacker.matrix_density", 0.02)
    )
    if duration < 0:
        raise typer.BadParameter("--duration must be 0 or a positive number of seconds")
    if iterations < 0:
        raise typer.BadParameter("--iterations must be 0 or a positive frame count")
    if iterations == 0 and duration <= 0 and not sys.stdout.isatty():
        raise typer.BadParameter(
            "stdout is not a terminal, so the rain needs a bound: pass --iterations N or "
            "--duration SECONDS, otherwise nothing would ever stop it"
        )

    columns, rows = _grid_size(width, height)
    set_ = terminal.active_glyphs()
    scene = core.MatrixScene(
        columns=columns,
        rows=rows,
        density=density_value,
        head_char=set_["block"],
        near_char=set_["shade"],
        seed=None if seed < 0 else seed,
    )
    scene.prime()
    frames, reason = _rain(scene, fps=fps_value, duration=duration, iterations=iterations)
    if not console.is_terminal:
        # Live only writes a trailing newline when it owns a terminal; on a captured
        # stream the last frame would otherwise run into this summary.
        console.print()
    glyph_mode = "block glyphs" if set_["block"] != "#" else "ASCII fallback for this stream"
    console.print(
        f"[dim]{frames} frame{'s' if frames != 1 else ''} at {fps_value} fps across "
        f"{columns}x{rows}, stopped by {reason}, {glyph_mode}[/dim]"
    )


def _grid_size(width: int, height: int) -> tuple[int, int]:
    facts = core.terminal_facts()
    columns = width or facts.columns
    # Two rows are held back: one for the status line inside Live, one so the shell
    # prompt is not swallowed when the effect ends.
    rows = height or max(3, facts.lines - 2)
    # Rich clips a line wider than the console instead of wrapping it, so never exceed it.
    limit = console.width or columns
    return max(1, min(columns, limit)), max(1, rows)


def _rain(
    scene: core.MatrixScene,
    *,
    fps: int,
    duration: float,
    iterations: int,
) -> tuple[int, str]:
    """Draw frames until a limit, a key or Ctrl+C says stop; returns (frames, reason).

    Live is driven by hand (`auto_refresh=False`) instead of by its refresh thread: this
    loop owns the clock, so the rate is exactly `--fps` and the run always terminates.
    A redirected stream cannot show animation, so Rich writes the final frame there and
    the summary line states how many were produced.
    """
    delay = 1.0 / fps
    started = time.perf_counter()
    frames = 1
    reason = "a limit"
    live = Live(
        _frame_group(scene.tick(), fps=fps, frames=frames),
        console=console,
        auto_refresh=False,
        transient=False,
    )
    with live:
        try:
            while True:
                if iterations and frames >= iterations:
                    reason = "--iterations"
                    break
                if duration and time.perf_counter() - started >= duration:
                    reason = "--duration"
                    break
                if _quit_requested():
                    reason = "the q key"
                    break
                time.sleep(delay)
                frames += 1
                live.update(_frame_group(scene.tick(), fps=fps, frames=frames), refresh=True)
        except KeyboardInterrupt:
            reason = "Ctrl+C"
    return frames, reason


def _frame_group(frame: core.Frame, *, fps: int, frames: int) -> Group:
    status = Text(
        f"levix hacker matrix   {fps} fps   frame {frames}   q or Ctrl+C to stop",
        style="dim green",
    )
    rows = (
        _row_text(chars, levels) for chars, levels in zip(frame.rows, frame.levels, strict=True)
    )
    return Group(*rows, status)


def _row_text(chars: str, levels: Sequence[int]) -> Text:
    """One grid row of Rich text.

    Consecutive cells of equal brightness become a single styled span; one span per
    character would multiply the work of every frame for no visual gain.
    """
    text = Text()
    start = 0
    for index in range(1, len(chars) + 1):
        if index < len(chars) and levels[index] == levels[start]:
            continue
        style = _LEVEL_STYLES.get(levels[start])
        chunk = chars[start:index]
        if style:
            text.append(chunk, style=style)
        else:
            text.append(chunk)
        start = index
    return text


def _quit_requested() -> bool:
    """Poll for `q` without blocking.

    A POSIX terminal is only put into raw mode when it really is a terminal, and the
    saved settings are restored on every path. Under a captured stream (tests, pipes)
    this returns False immediately and never touches the tty.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if sys.platform.startswith("win"):
        try:
            import msvcrt
        except ImportError:
            return False
        if msvcrt.kbhit():
            return msvcrt.getwche() in {"q", "Q", "\x03"}
        return False
    try:
        import select
        import termios
        import tty
    except ImportError:
        return False
    try:
        readable, _, _ = select.select([sys.stdin], [], [], 0)
    except (OSError, ValueError):
        return False
    if not readable:
        return False
    descriptor = getattr(sys.stdin, "fileno", None)
    if descriptor is None:
        return False
    handle = descriptor()
    try:
        saved = termios.tcgetattr(handle)
    except (termios.error, OSError, ValueError):
        return False
    try:
        tty.setraw(handle)
        keystroke = os.read(handle, 1)
    except OSError:
        keystroke = b""
    finally:
        termios.tcsetattr(handle, termios.TCSADRAIN, saved)
    return keystroke in {b"q", b"Q", b"\x03", b"\x04"}


def _configured(typer_ctx: typer.Context, dotted: str, fallback: float) -> float:
    obj = getattr(typer_ctx, "obj", None)
    if obj is None:
        return fallback
    try:
        return float(obj.value(dotted))
    except (ConfigError, TypeError, ValueError):
        # The engine validates configuration; a bad value here must not kill the effect,
        # so the packaged default is used and nothing is invented.
        return fallback


def _validate_fps(value: float) -> int:
    if not FPS_MIN <= value <= FPS_MAX:
        raise typer.BadParameter(f"--fps must be between {FPS_MIN} and {FPS_MAX}, got {value:g}")
    return int(value)


def _validate_density(value: float) -> float:
    if not DENSITY_MIN <= value <= DENSITY_MAX:
        raise typer.BadParameter(
            f"--density must be between {DENSITY_MIN} and {DENSITY_MAX}, got {value:g}"
        )
    return float(value)


# ----------------------------------------------------------------------------------
# info
# ----------------------------------------------------------------------------------


def info() -> None:
    """Facts about this machine, read locally. Contacts nothing."""
    facts = core.host_facts()
    view = core.collect_network()
    console.print(_host_table(facts))
    console.print(_python_table(facts))
    console.print(_terminal_table(facts, view))
    console.print(_interface_table(view))
    _report_sources(view)
    _report_notes(view)
    console.print(
        "[dim]every value above came from this machine: the OS, the interpreter and its "
        "own reporting tools. No packet left it.[/dim]"
    )


def _host_table(facts: core.HostFacts) -> Table:
    table = Table(title="Hacker / this machine", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("hostname", f"{facts.hostname} [dim]({facts.hostname_source})[/dim]")
    table.add_row("system", facts.system or "not reported")
    table.add_row("release", facts.release or "not reported")
    table.add_row("version", facts.version or "not reported")
    table.add_row("machine", facts.machine or "not reported")
    table.add_row("processor", facts.processor or "not reported")
    table.add_row("process id", str(facts.pid))
    table.add_row("user", f"{facts.user} [dim]({facts.user_source})[/dim]")
    table.add_row(
        "cpu count",
        f"{facts.cpu_count} logical" if facts.cpu_count else "not reported by os.cpu_count()",
    )
    table.add_row(
        "cpu detail",
        "[dim]physical cores and load averages need psutil, which this module "
        "deliberately does not use; `levix monitor` has them[/dim]",
    )
    return table


def _python_table(facts: core.HostFacts) -> Table:
    table = Table(title="Interpreter", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("python", facts.python_version)
    table.add_row("implementation", facts.python_implementation)
    table.add_row("executable", facts.executable)
    return table


def _terminal_table(facts: core.HostFacts, view: core.NetworkView) -> Table:
    set_ = terminal.active_glyphs()
    term = facts.terminal
    table = Table(title="Terminal", header_style="bold cyan", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("size", f"{term.columns} x {term.lines}")
    table.add_row("stream", "tty" if term.isatty else "not a tty (captured or redirected)")
    table.add_row("encoding", term.encoding)
    table.add_row("TERM", term.term)
    table.add_row(
        "glyph mode",
        f"{set_['block']} block glyphs available"
        if set_["block"] != "#"
        else "# ASCII fallback (this stream cannot encode block glyphs)",
    )
    table.add_row("interface source", view.interface_source or "not available on this platform")
    return table


def _interface_table(view: core.NetworkView) -> Table:
    table = Table(
        title=f"Local interfaces ({view.interface_source or 'no source available'})",
        header_style="bold cyan",
    )
    table.add_column("name", overflow="fold", max_width=34)
    table.add_column("state")
    table.add_column("mac", overflow="fold")
    table.add_column("addresses", overflow="fold")
    table.add_column("dhcp")
    for interface in view.interfaces:
        table.add_row(
            interface.name,
            interface.reported_state,
            interface.reported_mac,
            interface.addresses_text,
            "-" if interface.dhcp is None else ("yes" if interface.dhcp else "no"),
        )
    if not view.interfaces:
        table.add_row(
            "[cyan]no interface could be read by any available tool[/cyan]", "-", "-", "-", "-"
        )
    return table


# ----------------------------------------------------------------------------------
# network
# ----------------------------------------------------------------------------------


def network() -> None:
    """This machine's own network configuration, naming the source of every field."""
    view = core.collect_network()
    console.print(_interface_table(view))
    console.print(_gateway_table(view))
    console.print(_dns_table(view))
    console.print(_resolution_table(view))
    console.print(_route_table(view))
    _report_sources(view)
    _report_notes(view)
    console.print(
        "[dim]read-only: this command runs the OS reporting tools and reads configuration "
        "files. It does not probe, scan or connect to anything.[/dim]"
    )


def _gateway_table(view: core.NetworkView) -> Table:
    table = Table(title="Default gateway", header_style="bold cyan")
    table.add_column("gateway", overflow="fold")
    table.add_column("via", overflow="fold")
    table.add_column("metric", justify="right")
    table.add_column("source", overflow="fold")
    for gateway in view.gateways:
        if gateway.on_link:
            shown = "(directly connected, no gateway hop)"
        else:
            shown = gateway.address or "not available on this platform"
        table.add_row(
            shown,
            gateway.interface or "-",
            "-" if gateway.metric is None else str(gateway.metric),
            gateway.source,
        )
    if not view.gateways:
        table.add_row(
            "[cyan]not available on this platform[/cyan]", "-", "-", "no source reported one"
        )
    return table


def _dns_table(view: core.NetworkView) -> Table:
    table = Table(title="DNS servers", header_style="bold cyan")
    table.add_column("order", justify="right")
    table.add_column("server", overflow="fold")
    table.add_column("source", overflow="fold")
    for position, server in enumerate(view.dns, start=1):
        table.add_row(str(position), server.address, server.source)
    if not view.dns:
        table.add_row("-", "[cyan]not available on this platform[/cyan]", "no source listed one")
    if view.suffixes:
        table.add_row("", "search suffixes", ", ".join(view.suffixes))
    return table


def _resolution_table(view: core.NetworkView) -> Table:
    table = Table(title="Hostname resolution order", header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("source")
    table.add_column("detail", overflow="fold")
    table.add_column("evidence", overflow="fold")
    for step in view.resolution:
        table.add_row(str(step.position), step.label, step.detail, step.evidence)
    if not view.resolution:
        table.add_row("-", "[cyan]not available on this platform[/cyan]", "-", "-")
    return table


def _route_table(view: core.NetworkView) -> Table:
    table = Table(title=f"Route table ({len(view.routes)} entries read)", header_style="bold cyan")
    # Short header words on purpose: when a header does not fit its column Rich clips it
    # with a U+2026 ellipsis, and that character is exactly what a cp1252 console cannot
    # encode.
    table.add_column("dest", overflow="fold")
    table.add_column("prefix")
    table.add_column("gateway", overflow="fold")
    table.add_column("iface", overflow="fold")
    table.add_column("metric", justify="right")
    table.add_column("source")
    for route in view.routes:
        table.add_row(
            route.destination,
            route.prefix or "-",
            route.gateway or "directly connected",
            route.interface or "-",
            "-" if route.metric is None else str(route.metric),
            route.source,
        )
    if not view.routes:
        table.add_row(
            "[cyan]no route table could be read on this platform[/cyan]",
            "-",
            "-",
            "-",
            "-",
            "-",
        )
    return table


def _report_sources(view: core.NetworkView) -> None:
    if not view.tools:
        return
    table = Table(title="Where the data came from", header_style="bold cyan")
    table.add_column("program", overflow="fold")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for result in view.tools:
        if result.usable:
            colour, status = "green", "ran"
        elif result.available:
            colour, status = "yellow", "no data"
        else:
            colour, status = "red", "missing"
        table.add_row(
            " ".join(result.argv),
            f"[{colour}]{status}[/{colour}]",
            core.describe_tool(result),
        )
    console.print(table)


def _report_notes(view: core.NetworkView) -> None:
    for note in view.missing_data_notes():
        console.print(f"[yellow]note:[/yellow] {note}")

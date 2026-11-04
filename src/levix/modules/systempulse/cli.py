"""`levix monitor` command surface.

psutil is imported only through `core`, and only inside the collector functions that need
it, so `levix monitor -h` imports this file without paying for psutil or answering exit 1
before the dependency gate can answer exit 3.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence

import typer
from rich.console import Console
from rich.table import Table

from ... import terminal
from ...deps import gate
from . import MANIFEST, core

console = Console()

app = typer.Typer()


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    gate(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="monitor",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    application.command("overview", help="Every panel on one screen.")(overview)
    application.command("cpu", help="Processor load and per-core usage.")(cpu)
    application.command("memory", help="RAM and swap.")(memory)
    application.command("disk", help="Mounted filesystem usage.")(disk)
    application.command("network", help="Interface counters.")(network)
    application.command("processes", help="Top processes by CPU.")(processes)
    application.command("live", help="Refreshing view; Ctrl+C to stop.")(live)
    return application


def _bar(percent: float, width: int = 20) -> str:
    return terminal.bar(percent, width)


def overview(
    typer_ctx: typer.Context,
    limit: int = typer.Option(8, "--limit", help="Rows of processes to show."),
) -> None:
    """Print every panel once."""
    _render_overview(limit)


def _render_overview(limit: int) -> None:
    cpu_sample = core.cpu(interval=0.15)
    mem = core.memory()
    table = Table(title="SystemPulse", header_style="bold cyan", show_header=False)
    table.add_column("metric", style="bold")
    table.add_column("value", overflow="fold")
    table.add_row("uptime", _format_uptime(core.uptime()))
    physical = f"/{cpu_sample.count_physical} physical" if cpu_sample.count_physical else ""
    table.add_row(
        "cpu",
        f"{_bar(cpu_sample.percent)}  {cpu_sample.count_logical} logical{physical}",
    )
    if cpu_sample.frequency_mhz:
        table.add_row("cpu freq", f"{cpu_sample.frequency_mhz:.0f} MHz")
    if cpu_sample.load_average:
        table.add_row("load avg", ", ".join(f"{value:.2f}" for value in cpu_sample.load_average))
    table.add_row(
        "memory",
        f"{_bar(mem.percent)}  {core.human_bytes(mem.used_bytes)} / "
        f"{core.human_bytes(mem.total_bytes)}",
    )
    if mem.swap_total_bytes:
        swap_percent = 100.0 * mem.swap_used_bytes / mem.swap_total_bytes
        table.add_row(
            "swap",
            f"{core.human_bytes(mem.swap_used_bytes)} / "
            f"{core.human_bytes(mem.swap_total_bytes)} ({swap_percent:.1f}%)",
        )
    else:
        table.add_row("swap", "none reported by the OS")

    battery = core.battery()
    table.add_row(
        "battery",
        "not reported by this platform"
        if battery is None
        else f"{battery.percent:.0f}% ({'plugged in' if battery.power_plugged else 'discharging'})",
    )
    temps = core.temperatures()
    if temps:
        for chip, entries in sorted(temps.items()):
            readable = ", ".join(f"{label} {current:.0f}C" for label, current, _, _ in entries[:4])
            table.add_row(terminal.markup_safe(f"temp [{chip}]"), readable)
    else:
        table.add_row("temp", "[cyan]unsupported here - no sensors exposed through psutil[/cyan]")
    table.add_row("gpu", "[cyan]unsupported - psutil exposes no GPU API[/cyan]")
    console.print(table)

    console.print(_disk_table(core.disks()))
    console.print(_process_table(core.processes(limit=limit), limit))


def cpu() -> None:
    """Per-core utilisation."""
    sample = core.cpu(interval=0.3)
    table = Table(title="CPU", header_style="bold cyan")
    table.add_column("core", justify="right")
    table.add_column("usage")
    for index, percent in enumerate(sample.per_core):
        table.add_row(str(index), _bar(percent, width=28))
    console.print(table)
    console.print(
        f"logical cores [bold]{sample.count_logical}[/bold]"
        + (
            f", physical [bold]{sample.count_physical}[/bold]"
            if sample.count_physical
            else ", physical count not reported by this platform"
        )
        + (
            f", frequency [bold]{sample.frequency_mhz:.0f} MHz[/bold]"
            if sample.frequency_mhz
            else ""
        )
    )
    if sample.load_average is None:
        console.print("[dim]load averages are not available on this platform.[/dim]")


def memory() -> None:
    """RAM and swap."""
    sample = core.memory()
    table = Table(title="Memory", header_style="bold cyan")
    table.add_column("pool")
    table.add_column("used", justify="right")
    table.add_column("total", justify="right")
    table.add_column("usage")
    table.add_row(
        "RAM",
        core.human_bytes(sample.used_bytes),
        core.human_bytes(sample.total_bytes),
        _bar(sample.percent),
    )
    if sample.swap_total_bytes:
        swap_percent = 100.0 * sample.swap_used_bytes / sample.swap_total_bytes
        table.add_row(
            "swap",
            core.human_bytes(sample.swap_used_bytes),
            core.human_bytes(sample.swap_total_bytes),
            _bar(swap_percent),
        )
    else:
        table.add_row("swap", "-", "-", "[cyan]none reported[/cyan]")
    console.print(table)
    console.print(f"available to start new work: {core.human_bytes(sample.available_bytes)}")


def disk() -> None:
    """Mounted filesystem usage."""
    console.print(_disk_table(core.disks()))


def network(
    watch: float = typer.Option(0.0, "--watch", help="Seconds to sample rates over."),
) -> None:
    """Per-interface byte counters, or rates when `--watch` is used."""
    rows = core.network(interval=watch if watch > 0 else None)
    scope = f" rates over {watch}s" if watch else " (cumulative since boot)"
    console.print(_network_table(rows.values(), scope))


def _network_table(rows: Iterable[core.NetRow], scope: str) -> Table:
    table = Table(title=f"Network{scope}", header_style="bold cyan")
    table.add_column("interface")
    table.add_column("sent", justify="right")
    table.add_column("received", justify="right")
    table.add_column("packets tx", justify="right")
    table.add_column("packets rx", justify="right")
    table.add_column("errors", justify="right")
    for row in rows:
        # The name comes from the OS, like every other cell in this file: a Windows
        # adapter description or a Linux interface alias is data, not markup.
        table.add_row(
            terminal.markup_safe(row.interface),
            core.human_bytes(row.bytes_sent),
            core.human_bytes(row.bytes_recv),
            f"{row.packets_sent:,}",
            f"{row.packets_recv:,}",
            f"{row.errin + row.dropin:,}",
        )
    return table


def processes(
    typer_ctx: typer.Context,
    limit: int = typer.Option(0, "--limit", "-n", help="Rows to show (0 uses configuration)."),
    by: str = typer.Option("cpu", "--by", help="cpu or memory."),
) -> None:
    """Top processes."""
    count = limit or int(_configured_limit(typer_ctx))
    rows = core.processes(limit=count)
    if by == "memory":
        rows.sort(key=lambda row: row.memory_percent, reverse=True)
    console.print(_process_table(rows, count, order=by))


def live(
    typer_ctx: typer.Context,
    iterations: int = typer.Option(0, "--iterations", help="Stop after N frames (0 = forever)."),
    interval: float = typer.Option(0.0, "--interval", help="Seconds (0 uses configuration)."),
) -> None:
    """Refreshing overview. Ctrl+C exits cleanly with code 0."""
    delay = interval or float(_configured_interval(typer_ctx))
    frames = 0
    try:
        while iterations == 0 or frames < iterations:
            console.clear()
            _render_overview(6)
            console.print(
                f"[dim]refresh every {delay:.1f}s - Ctrl+C to stop (frame {frames + 1})[/dim]"
            )
            time.sleep(delay)
            frames += 1
    except KeyboardInterrupt:
        console.print("\n[dim]stopped.[/dim]")


def _disk_table(rows: Sequence[core.DiskRow]) -> Table:
    table = Table(title="Disks", header_style="bold cyan")
    table.add_column("mount")
    table.add_column("device")
    table.add_column("fs")
    table.add_column("used", justify="right")
    table.add_column("free", justify="right")
    table.add_column("usage")
    for row in rows:
        table.add_row(
            terminal.markup_safe(row.mountpoint),
            terminal.markup_safe(row.device),
            terminal.markup_safe(row.fstype),
            core.human_bytes(row.used_bytes),
            core.human_bytes(row.total_bytes - row.used_bytes),
            _bar(row.percent, width=12),
        )
    if not rows:
        table.add_row("[cyan]no mounted filesystems reported[/cyan]", "-", "-", "-", "-", "-")
    return table


def _process_table(rows: Sequence[core.ProcessRow], limit: int, *, order: str = "cpu") -> Table:
    table = Table(
        title=f"Top processes by {terminal.markup_safe(order)} (n={len(rows)} of limit {limit})",
        header_style="bold cyan",
    )
    table.add_column("pid", justify="right")
    table.add_column("name", overflow="ellipsis", max_width=28)
    table.add_column("cpu %", justify="right")
    table.add_column("mem %", justify="right")
    table.add_column("rss", justify="right")
    table.add_column("state")
    table.add_column("user", overflow="ellipsis")
    for row in rows:
        # Every field here comes from the machine, not from this file. On Linux the kernel
        # threads are named `[kthreadd]`, `[migration/0]`: unescaped, Rich eats the name and
        # the row shows a pid with nothing next to it.
        table.add_row(
            str(row.pid),
            terminal.markup_safe(row.name),
            f"{row.cpu_percent:.1f}",
            f"{row.memory_percent:.1f}",
            core.human_bytes(row.memory_bytes),
            terminal.markup_safe(row.status),
            terminal.markup_safe(row.username),
        )
    return table


def _configured_limit(typer_ctx: typer.Context) -> int:
    obj = getattr(typer_ctx, "obj", None)
    return int(obj.value("monitor.process_limit")) if obj is not None else 15


def _configured_interval(typer_ctx: typer.Context) -> float:
    obj = getattr(typer_ctx, "obj", None)
    return float(obj.value("monitor.interval_seconds")) if obj is not None else 1.0


def _format_uptime(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

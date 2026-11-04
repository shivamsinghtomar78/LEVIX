"""Sampling logic for SystemPulse.

Returns plain data structures. Rendering lives in `cli.py`, which keeps every number
unit-testable without a console and lets `--live` reuse the same collectors.

Honesty rule: when the platform does not expose a metric, this module returns None or
an empty mapping and the renderer says so. Zero is never substituted for unknown.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CpuSample:
    percent: float
    per_core: list[float]
    count_logical: int
    count_physical: int | None
    frequency_mhz: float | None
    load_average: tuple[float, float, float] | None


@dataclass(frozen=True, slots=True)
class MemorySample:
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float
    swap_total_bytes: int
    swap_used_bytes: int


@dataclass(frozen=True, slots=True)
class DiskRow:
    device: str
    mountpoint: str
    fstype: str
    total_bytes: int
    used_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class NetRow:
    interface: str
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errin: int
    dropin: int


@dataclass(frozen=True, slots=True)
class ProcessRow:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_bytes: int
    status: str
    username: str


def cpu(interval: float | None = None) -> CpuSample:
    import psutil

    per_core = psutil.cpu_percent(interval=interval, percpu=True)
    physical = psutil.cpu_count(logical=False)
    try:
        current = psutil.cpu_freq()
        frequency = current.current if current else None
    except Exception:
        frequency = None
    try:
        load = psutil.getloadavg()
    except (AttributeError, OSError):
        # Not exposed on stock Windows; os.getloadavg does not exist there.
        load = None
    return CpuSample(
        percent=sum(per_core) / len(per_core) if per_core else 0.0,
        per_core=list(per_core),
        count_logical=psutil.cpu_count(logical=True) or 0,
        count_physical=physical,
        frequency_mhz=frequency,
        load_average=load,
    )


def memory() -> MemorySample:
    import psutil

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return MemorySample(
        total_bytes=vm.total,
        used_bytes=vm.used,
        available_bytes=vm.available,
        percent=vm.percent,
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
    )


def disks() -> list[DiskRow]:
    import psutil

    rows: list[DiskRow] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            # A read-only or protected mount on Windows is normal, not an error.
            continue
        rows.append(
            DiskRow(
                device=part.device or part.mountpoint,
                mountpoint=part.mountpoint,
                fstype=part.fstype or "-",
                total_bytes=usage.total,
                used_bytes=usage.used,
                percent=usage.percent,
            )
        )
    return rows


def network(interval: float | None = None) -> dict[str, NetRow]:
    import psutil

    counters = psutil.net_io_counters(pernic=True)
    if interval:
        import time

        first = dict(counters)
        time.sleep(interval)
        second = psutil.net_io_counters(pernic=True)
        counters = {}
        for name, after in second.items():
            before = first.get(name)
            if before is None:
                counters[name] = after
                continue
            counters[name] = _DeltaNet(
                bytes_sent=after.bytes_sent - before.bytes_sent,
                bytes_recv=after.bytes_recv - before.bytes_recv,
                packets_sent=after.packets_sent - before.packets_sent,
                packets_recv=after.packets_recv - before.packets_recv,
                errin=after.errin - before.errin,
                errout=after.errout - before.errout,
                dropin=after.dropin - before.dropin,
                dropout=after.dropout - before.dropout,
            )
    return {
        name: NetRow(
            interface=name,
            bytes_sent=row.bytes_sent,
            bytes_recv=row.bytes_recv,
            packets_sent=row.packets_sent,
            packets_recv=row.packets_recv,
            errin=row.errin,
            dropin=row.dropin,
        )
        for name, row in counters.items()
    }


class _DeltaNet:
    """Duck-typed stand-in matching psutil's counter interface for a delta window."""

    def __init__(self, **kwargs: int) -> None:
        self.__dict__.update(kwargs)


def processes(limit: int = 15) -> list[ProcessRow]:
    import psutil

    rows: list[ProcessRow] = []
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "username", "status"]):
        try:
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # Prime the CPU counters, then sample: the first call always returns 0.0.
    for proc in candidates:
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    import time

    time.sleep(0.15)
    for proc in candidates:
        try:
            cpu_percent = proc.cpu_percent(None)
            info = proc.as_dict(attrs=["pid", "name", "username", "status", "memory_percent"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        memory_bytes = 0
        try:
            memory_bytes = proc.memory_info().rss or 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        rows.append(
            ProcessRow(
                pid=info["pid"],
                name=(info.get("name") or "?"),
                cpu_percent=cpu_percent,
                memory_percent=info.get("memory_percent") or 0.0,
                memory_bytes=memory_bytes,
                status=info.get("status") or "?",
                username=info.get("username") or "-",
            )
        )
    rows.sort(key=lambda row: row.cpu_percent, reverse=True)
    return rows[:limit]


def temperatures() -> dict[str, list[tuple[str, float, float | None, float | None]]]:
    """Empty dict means the platform exposes no sensors - reported, not faked."""
    import psutil

    getter = getattr(psutil, "sensors_temperatures", None)
    if getter is None:
        return {}
    try:
        raw = getter()
    except Exception:
        return {}
    return {
        chip: [
            (label or chip, current, high or None, critical or None)
            for label, current, high, critical in entries
            if current is not None
        ]
        for chip, entries in (raw or {}).items()
    }


def battery():
    import psutil

    getter = getattr(psutil, "sensors_battery", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def human_bytes(value: float) -> str:
    """Binary units, matching how operating systems report capacity."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} PiB"


def uptime() -> float:
    import psutil
    import time

    return max(0.0, time.time() - psutil.boot_time())

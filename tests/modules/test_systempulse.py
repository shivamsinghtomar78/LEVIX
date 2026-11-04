"""SystemPulse: the sampling layer against a fake psutil, the surface against the real machine.

`core.py` imports psutil *inside* every function, which is what makes this file possible:
a stand-in can be put in `sys.modules` and the sampling code is then tested against numbers
that are known-correct by construction, instead of against whatever this machine happens to
be doing. The CLI tests at the bottom run for real, because a monitor command is a claim
about the machine - and those assert only properties that hold on every platform.
"""

from __future__ import annotations

import re
import sys
import types

import pytest
from rich.console import Console
from rich.table import Table

from levix.errors import EXIT_USAGE
from levix.module import Permission
from levix.modules.systempulse import MANIFEST, cli, core

# ----------------------------------------------------------------------------------
# the stand-in
# ----------------------------------------------------------------------------------


class Counter:
    """psutil returns lightweight namedtuple-ish objects; attribute access is all core uses."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def install(
    monkeypatch,
    *,
    per_core: tuple[float, ...] = (10.0, 30.0, 50.0, 70.0),
    threads: int = 8,
    cores: int | None = 4,
    freq: float | None = 2400.0,
    loadavg: tuple[float, float, float] | None = None,
    partitions=(),
    disk_usage=None,
    net_samples=(),
    procs=(),
    sensors=None,
    battery=None,
    boot_time: float = 1_000_000.0,
) -> types.ModuleType:
    """Install a psutil stand-in.

    Whether `getloadavg`, `sensors_temperatures` and `sensors_battery` exist at all is
    configurable, because that is exactly what differs between platforms and what the
    honest-unsupported rule turns on.
    """
    module = types.ModuleType("psutil")
    module.cpu_percent = lambda interval=None, percpu=False: list(per_core)
    module.cpu_count = lambda logical=True: threads if logical else cores
    module.cpu_freq = lambda: Counter(current=freq) if freq is not None else None
    module.virtual_memory = lambda: Counter(
        total=16 * 1024**3, used=9 * 1024**3, available=7 * 1024**3, percent=56.3
    )
    module.swap_memory = lambda: Counter(total=0, used=0, percent=0.0)
    module.disk_partitions = lambda all=False: list(partitions)
    module.disk_usage = lambda path: (
        disk_usage(path) if disk_usage else Counter(total=0, used=0, percent=0.0)
    )
    samples = list(net_samples)
    calls = {"n": 0}

    def net_io_counters(pernic=False):
        row = samples[calls["n"]] if calls["n"] < len(samples) else {}
        calls["n"] += 1
        return {name: Counter(**counters) for name, counters in row.items()}

    module.net_io_counters = net_io_counters
    module.net_io_calls = calls
    module.process_iter = lambda attrs=None: iter(list(procs))
    module.boot_time = lambda: boot_time
    module.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    module.AccessDenied = type("AccessDenied", (Exception,), {})

    if loadavg is not None:
        module.getloadavg = lambda: loadavg
    if sensors is not None:
        module.sensors_temperatures = lambda: sensors
    if battery is not None:
        module.sensors_battery = lambda: battery
    monkeypatch.setitem(sys.modules, "psutil", module)
    return module


class Partition:
    def __init__(self, device: str, mountpoint: str, fstype: str) -> None:
        self.device, self.mountpoint, self.fstype = device, mountpoint, fstype


class Proc:
    """The subset of `psutil.Process` that `core.processes` touches."""

    def __init__(self, pid: int, name: str, cpu: float, mem_percent: float, rss: int = 0) -> None:
        self.pid, self.name, self._cpu, self._mem, self._rss = pid, name, cpu, mem_percent, rss
        self.seen = 0

    def cpu_percent(self, interval):
        # A real psutil Process returns 0.0 on its first call; core primes and re-reads.
        self.seen += 1
        return 0.0 if self.seen == 1 else self._cpu

    def as_dict(self, attrs=None):
        return {
            "pid": self.pid,
            "name": self.name,
            "username": "tester",
            "status": "running",
            "memory_percent": self._mem,
        }

    def memory_info(self):
        return Counter(rss=self._rss)


# ----------------------------------------------------------------------------------
# cpu
# ----------------------------------------------------------------------------------


def test_cpu_averages_the_cores_rather_than_reporting_the_first_one(monkeypatch):
    install(monkeypatch, per_core=(0.0, 0.0, 100.0, 100.0))
    sample = core.cpu()
    assert sample.percent == 50.0
    assert sample.per_core == [0.0, 0.0, 100.0, 100.0], "the per-core detail is the point"


def test_a_platform_without_load_average_reports_none_not_zero(monkeypatch):
    # Stock Windows: no getloadavg at all. A 0.0 here would be a fabricated metric.
    install(monkeypatch)
    assert core.cpu().load_average is None


def test_a_platform_with_load_average_reports_the_three_numbers(monkeypatch):
    install(monkeypatch, loadavg=(1.5, 2.0, 2.5))
    assert core.cpu().load_average == (1.5, 2.0, 2.5)


def test_a_missing_frequency_is_none(monkeypatch):
    install(monkeypatch, freq=None)
    assert core.cpu().frequency_mhz is None


def test_thread_count_is_kept_separate_from_core_count(monkeypatch):
    install(monkeypatch, threads=8, cores=4)
    sample = core.cpu()
    assert sample.count_logical == 8
    assert sample.count_physical == 4


def test_a_platform_that_reports_no_physical_cores_is_left_unknown(monkeypatch):
    install(monkeypatch, cores=None)
    assert core.cpu().count_physical is None


def test_no_cores_at_all_does_not_divide_by_zero(monkeypatch):
    install(monkeypatch, per_core=())
    sample = core.cpu()
    assert sample.percent == 0.0
    assert sample.per_core == []


# ----------------------------------------------------------------------------------
# memory
# ----------------------------------------------------------------------------------


def test_memory_passes_the_pools_through(monkeypatch):
    install(monkeypatch)
    sample = core.memory()
    assert sample.total_bytes == 16 * 1024**3
    assert sample.percent == 56.3


def test_a_machine_with_no_swap_reports_zero_rather_than_guessing(monkeypatch):
    install(monkeypatch)
    sample = core.memory()
    assert sample.swap_total_bytes == 0
    assert sample.swap_used_bytes == 0


# ----------------------------------------------------------------------------------
# disks
# ----------------------------------------------------------------------------------


def test_a_protected_mount_is_skipped_and_the_rest_still_reports(monkeypatch):
    def usage(path):
        if path == "D:\\":
            raise PermissionError(13, "denied")
        return Counter(total=500 * 1024**3, used=250 * 1024**3, percent=50.0)

    install(
        monkeypatch,
        partitions=[Partition("C:", "C:\\", "NTFS"), Partition("D:", "D:\\", "CDFS")],
        disk_usage=usage,
    )
    rows = core.disks()
    assert [row.mountpoint for row in rows] == ["C:\\"]
    assert rows[0].fstype == "NTFS"


def test_an_unnamed_filesystem_is_shown_as_a_dash_not_an_empty_cell(monkeypatch):
    install(
        monkeypatch,
        partitions=[Partition("", "mnt/odd", "")],
        disk_usage=lambda path: Counter(total=1024, used=512, percent=50.0),
    )
    row = core.disks()[0]
    assert row.device == "mnt/odd", "an empty device falls back to the mountpoint"
    assert row.fstype == "-"


# ----------------------------------------------------------------------------------
# network
# ----------------------------------------------------------------------------------


def counters(
    sent: int, recv: int, tx: int = 0, rx: int = 0, err: int = 0, drop: int = 0
) -> dict[str, int]:
    """psutil's per-interface attribute set, spelled once. `core.network` reads all eight."""
    return {
        "bytes_sent": sent,
        "bytes_recv": recv,
        "packets_sent": tx,
        "packets_recv": rx,
        "errin": err,
        "errout": err,
        "dropin": drop,
        "dropout": drop,
    }


CUMULATIVE = {"eth0": counters(100, 200, 3, 4)}


def test_cumulative_counters_are_reported_untouched(monkeypatch):
    install(monkeypatch, net_samples=[CUMULATIVE])
    rows = core.network()
    assert rows["eth0"].bytes_sent == 100
    assert rows["eth0"].bytes_recv == 200


def test_a_watch_window_reports_the_difference_not_the_total(monkeypatch):
    install(
        monkeypatch,
        net_samples=[
            CUMULATIVE,
            {"eth0": counters(600, 450, 13, 24, drop=1)},
        ],
    )
    rows = core.network(interval=0.001)
    assert rows["eth0"].bytes_sent == 500
    assert rows["eth0"].bytes_recv == 250
    assert rows["eth0"].packets_sent == 10
    assert rows["eth0"].dropin == 1, "drops are deltas too: one packet dropped inside the window"


def test_two_samples_are_taken_only_when_a_window_is_asked_for(monkeypatch):
    cumulative = install(monkeypatch, net_samples=[CUMULATIVE])
    core.network()
    assert cumulative.net_io_calls["n"] == 1, "a cumulative read needs one sample, not two"

    windowed = install(monkeypatch, net_samples=[CUMULATIVE, CUMULATIVE])
    core.network(interval=0.001)
    assert windowed.net_io_calls["n"] == 2


def test_an_interface_that_appears_mid_window_is_kept(monkeypatch):
    install(
        monkeypatch,
        net_samples=[
            CUMULATIVE,
            {"eth0": counters(101, 201, 3, 4), "wlan0": counters(9, 9, 9, 9)},
        ],
    )
    assert set(core.network(interval=0.001)) == {"eth0", "wlan0"}


# ----------------------------------------------------------------------------------
# processes
# ----------------------------------------------------------------------------------


def test_vanishing_processes_are_skipped_and_the_others_survive(monkeypatch):
    module = install(monkeypatch)
    healthy = Proc(1, "a.exe", 5.0, 1.0)
    doomed = Proc(2, "b.exe", 40.0, 2.0)

    def cpu_percent(interval):
        raise module.NoSuchProcess(2)

    doomed.cpu_percent = cpu_percent
    module.process_iter = lambda attrs=None: iter([healthy, doomed])
    rows = core.processes(limit=10)
    assert [row.name for row in rows] == ["a.exe"]


def test_the_cpu_counters_are_primed_before_they_are_read(monkeypatch):
    install(monkeypatch, procs=[Proc(1, "a.exe", 12.0, 1.0)])
    rows = core.processes(limit=10)
    assert rows[0].cpu_percent == 12.0, "an unprimed psutil counter reads 0.0 forever"


def test_rows_are_ordered_by_the_busiest_process_first(monkeypatch):
    install(
        monkeypatch,
        procs=[Proc(1, "idle", 0.5, 90.0), Proc(2, "hot", 77.0, 1.0), Proc(3, "mid", 20.0, 5.0)],
    )
    assert [row.name for row in core.processes(limit=10)] == ["hot", "mid", "idle"]


def test_the_limit_caps_the_rows_not_the_work(monkeypatch):
    install(monkeypatch, procs=[Proc(n, f"p{n}", float(n), 1.0) for n in range(40)])
    rows = core.processes(limit=5)
    assert len(rows) == 5
    assert [row.cpu_percent for row in rows] == [39.0, 38.0, 37.0, 36.0, 35.0]


def test_a_process_naming_itself_as_nothing_still_gets_a_row(monkeypatch):
    install(monkeypatch, procs=[Proc(7, "", 1.0, 1.0)])
    assert core.processes(limit=2)[0].name == "?", "an unnameable process is shown, not hidden"


# ----------------------------------------------------------------------------------
# sensors: the honest-unsupported requirement
# ----------------------------------------------------------------------------------


def test_no_sensor_getter_means_no_sensors(monkeypatch):
    install(monkeypatch)  # Windows psutil: the attribute does not exist
    assert core.temperatures() == {}


def test_a_sensor_backend_that_raises_is_reported_as_absent(monkeypatch):
    module = install(monkeypatch)
    module.sensors_temperatures = lambda: (_ for _ in ()).throw(OSError("ioctl failed"))
    assert core.temperatures() == {}


def test_a_reading_of_none_is_dropped_rather_than_printed_as_zero(monkeypatch):
    install(
        monkeypatch,
        sensors={"k10temp": [("Tdie", 45.0, 90.0, None), ("Tctl", None, None, None)]},
    )
    assert core.temperatures() == {"k10temp": [("Tdie", 45.0, 90.0, None)]}


def test_an_unlabelled_sensor_is_named_after_its_chip(monkeypatch):
    install(monkeypatch, sensors={"cpu_thermal": [("", 51.0, None, None)]})
    assert core.temperatures() == {"cpu_thermal": [("cpu_thermal", 51.0, None, None)]}


def test_no_battery_means_none(monkeypatch):
    install(monkeypatch)
    assert core.battery() is None


def test_a_battery_is_passed_through(monkeypatch):
    module = install(monkeypatch)
    module.sensors_battery = lambda: Counter(percent=71.0, power_plugged=False)
    assert core.battery().percent == 71.0


# ----------------------------------------------------------------------------------
# units and uptime
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1024**2, "1.0 MiB"),
        (1024**3, "1.0 GiB"),
        (1024**4, "1.0 TiB"),
        (int(2.5 * 1024**5), "2.5 PiB"),
    ],
)
def test_bytes_are_binary_units_because_capacity_is_reported_that_way(value, expected):
    assert core.human_bytes(value) == expected


def test_a_clock_that_jumps_backwards_cannot_produce_a_negative_uptime(monkeypatch):
    install(monkeypatch, boot_time=sys.float_info.max)
    assert core.uptime() == 0.0


def test_uptime_is_the_wall_clock_difference(monkeypatch):
    install(monkeypatch, boot_time=1_000.0)
    assert core.uptime() > 1_000.0


# ----------------------------------------------------------------------------------
# manifest honesty
# ----------------------------------------------------------------------------------


def test_the_manifest_claims_only_disk_reads():
    # Monitoring reads kernel counters; it opens no socket and runs no helper. A broader
    # claim here would contradict the permission table in docs/security/PERMISSIONS.md.
    assert MANIFEST.permissions == frozenset({Permission.FS_READ})
    assert MANIFEST.requirements[0].distribution == "psutil"
    assert MANIFEST.extras == ("monitor",)


def test_the_gpu_is_declared_as_a_capability_so_it_can_be_reported_unsupported():
    assert "gpu" in MANIFEST.capabilities


# ----------------------------------------------------------------------------------
# markup: a name the machine chose is not a style tag
# ----------------------------------------------------------------------------------


def _rendered(table: Table) -> str:
    console = Console(record=True, width=200, color_system=None)
    console.print(table)
    return " ".join(console.export_text().split())


def test_a_kernel_thread_name_survives_the_markup_parser():
    """Linux reports kernel threads as `[kthreadd]`, `[migration/0]`.

    Rich reads a bare `[...]` as a style tag and deletes it, so an unescaped name column
    prints an empty cell next to a pid - the process list quietly loses every kernel thread.
    """
    row = core.ProcessRow(
        pid=2,
        name="[kthreadd]",
        cpu_percent=0.0,
        memory_percent=0.0,
        memory_bytes=0,
        status="sleeping",
        username="root",
    )
    printed = _rendered(cli._process_table([row], 8))
    assert "[kthreadd]" in printed, "the name was consumed as markup"
    assert "root" in printed


def test_a_mount_with_brackets_in_its_name_is_still_shown():
    row = core.DiskRow(
        device="/dev/sr0[cdrw]",
        mountpoint="/mnt/[data]",
        fstype="",
        total_bytes=1024,
        used_bytes=512,
        percent=50.0,
    )
    printed = _rendered(cli._disk_table([row]))
    assert "/mnt/[data]" in printed
    assert "/dev/sr0[cdrw]" in printed


def test_an_interface_name_with_brackets_is_still_shown():
    row = core.NetRow(
        interface="veth[0abc]",
        bytes_sent=1024,
        bytes_recv=2048,
        packets_sent=3,
        packets_recv=4,
        errin=0,
        dropin=1,
    )
    printed = _rendered(cli._network_table([row], " (cumulative since boot)"))
    assert "veth[0abc]" in printed, "the interface was consumed as markup"
    assert "1.0 KiB" in printed


def test_the_temperature_row_names_the_chip_it_is_reading(monkeypatch, capsys):
    # `temp [k10temp]` is the label; unescaped the chip name is the tag and vanishes, which
    # would leave several platforms reporting a bare `temp` row with no idea of its source.
    install(monkeypatch, sensors={"k10temp": [("Tdie", 45.0, 90.0, None)]})
    cli._render_overview(2)
    printed = " ".join(capsys.readouterr().out.split())
    assert "temp [k10temp]" in printed


# ----------------------------------------------------------------------------------
# the real surface, on the real machine
# ----------------------------------------------------------------------------------


def _summary_cell(printed: str, metric: str) -> str:
    """The value cell of the `metric` row, read back out of the rendered table.

    Cells are separated by box-drawing characters, so a flat "gpu unsupported" substring
    never exists even when the row says exactly that; this reads the row as the user does.
    """
    for line in printed.splitlines():
        cells = [cell.strip() for cell in re.split(r"[|│]", line)]
        if len(cells) >= 3 and cells[1].lower() == metric:
            return cells[2]
    return ""


def test_monitor_commands_run_and_exit_zero(run_cli):
    for argv in (
        ("monitor", "overview"),
        ("monitor", "cpu"),
        ("monitor", "memory"),
        ("monitor", "disk"),
        ("monitor", "network"),
        ("monitor", "processes", "--limit", "3"),
    ):
        assert run_cli(*argv) == 0, argv


def test_the_live_view_terminates_on_its_own(run_cli):
    # A non-zero --interval: `0` falls through to the configured refresh delay, which would
    # make the test sleep for however long the user's config says.
    assert run_cli("monitor", "live", "--iterations", "1", "--interval", "0.05") == 0


def test_a_platform_without_sensors_says_so_in_words(run_cli, capsys):
    run_cli("monitor", "overview")
    printed = " ".join(capsys.readouterr().out.split())
    if core.temperatures():
        pytest.skip("this machine exposes sensors; the unsupported branch cannot be asserted")
    assert "unsupported here" in printed


def test_the_gpu_is_never_shown_as_a_number(run_cli, capsys):
    run_cli("monitor", "overview")
    value = _summary_cell(capsys.readouterr().out, "gpu")
    assert "unsupported" in value.lower(), value
    assert not any(character.isdigit() for character in value), (
        "a GPU percentage here would be invented: psutil exposes no GPU API on any platform"
    )


def test_an_unknown_option_is_a_usage_error(run_cli):
    assert run_cli("monitor", "cpu", "--nonsense") == EXIT_USAGE

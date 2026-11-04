"""LEVIX SystemPulse - cross-platform system monitoring.

Command name is `monitor` (short, verb-like); the package keeps the product name.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, PackageRef, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="monitor",
    title="SystemPulse",
    summary="CPU, memory, disk, network and process monitoring.",
    cli_path="levix.modules.systempulse.cli:build_app",
    commands=(
        CommandInfo("overview", "One screen with every panel."),
        CommandInfo("cpu", "Processor load and per-core usage."),
        CommandInfo("memory", "RAM and swap."),
        CommandInfo("disk", "Mounted filesystem usage."),
        CommandInfo("network", "Interface counters."),
        CommandInfo("processes", "Top processes by CPU."),
        CommandInfo("live", "Refreshing dashboard (Ctrl+C to stop)."),
    ),
    requirements=(PackageRef("psutil", "psutil", minimum="7.2"),),
    extras=("monitor",),
    capabilities=("psutil", "temperature", "battery", "gpu"),
    permissions=frozenset({Permission.FS_READ}),
    ui=UiSpec(mode="suspend", argv=("monitor", "live")),
    documentation="docs/modules/SYSTEMPULSE.md",
)

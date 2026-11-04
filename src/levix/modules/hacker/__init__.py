"""LEVIX Hacker - terminal-cool, but honest and safe by design.

`levix --help` imports this file for every registered module, so it stays pure data:
no Rich, no subprocess, no parser code. All of that lives in `core.py` and `cli.py`,
which are only reached when a `levix hacker` command actually runs.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="hacker",
    title="Hacker",
    summary="Matrix rain plus a read-only tour of this machine's own network setup.",
    cli_path="levix.modules.hacker.cli:build_app",
    commands=(
        CommandInfo(
            "matrix",
            "Matrix rain in your own terminal; ASCII-safe, Ctrl+C or q to stop.",
        ),
        CommandInfo(
            "info",
            "Facts about this machine: host, platform, Python, terminal, interfaces.",
        ),
        CommandInfo(
            "network",
            "This machine's own network setup: MACs, gateway, DNS, resolution order.",
        ),
    ),
    requirements=(),
    extras=(),
    capabilities=(
        "rich-live",
        "ipconfig",
        "getadapterconfig",
        "route",
        "ip",
        "ifconfig",
        "resolv-conf",
        "hosts-file",
    ),
    permissions=frozenset({Permission.SUBPROCESS, Permission.FS_READ}),
    ui=UiSpec(mode="suspend", argv=("hacker", "matrix")),
    install_hint=(
        "nothing to install - `hacker` uses the Python standard library and the "
        "network tools already shipped with your OS"
    ),
    documentation="docs/modules/HACKER.md",
)

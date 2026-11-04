"""Hello: the reference third-party LEVIX module.

`levix --help` imports this file for every registered module, so it stays pure data:
no Typer, no Rich, no filesystem. What LEVIX needs to list, gate and launch the module
is in `MANIFEST`; everything that needs an import lives in `cli.py`, which the registry
only touches once `levix hello ...` is actually run.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="hello",
    title="Hello",
    summary="Example plugin: greets a name, and reports the paths LEVIX resolved.",
    cli_path="levix_hello.cli:build_app",
    commands=(
        CommandInfo("greet", "Say hello. --times N repeats it on N lines.", aliases=("hi",)),
        CommandInfo("where", "Show the profile directories this LEVIX run is using."),
    ),
    requirements=(),
    permissions=frozenset({Permission.FS_READ}),
    # `hidden` keeps an example out of the dashboard. A module with a real interactive
    # surface declares `mode="suspend"` (its own full-screen CLI) or `mode="screen"` with
    # `screen_path="my_module.screens:MyScreen"` to be pushed inside the dashboard.
    ui=UiSpec(mode="hidden"),
    documentation="plugin-examples/hello/README.md",
)

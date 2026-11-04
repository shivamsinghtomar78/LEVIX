"""Module registration by forwarding, not by subclassing click.

`levix --help` must not import yt-dlp, psutil or sounddevice. The obvious trick -
overriding `click.Group.get_command` - is unavailable here: Typer 0.27 runs on its own
vendored click fork (`typer._click`), whose `TyperGroup` does not derive from
`click.Group`, so overriding those methods would target a class hierarchy that does
not exist at runtime.

Instead each module is registered as a thin command carrying only manifest text, with
`add_help_option=False` and `ignore_unknown_options`, so the module's own argv -
including `--help` - is forwarded to the sub-app built on demand. Lazy loading then
needs no private API, and `levix tube --help` shows Typer's real help for Tube rather
than a copy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from .errors import DependencyError
from .module import ModuleManifest

if TYPE_CHECKING:
    from .registry import ModuleRegistry


def register_modules(app: typer.Typer, registry: ModuleRegistry) -> None:
    for manifest in registry.manifests():
        _attach(app, manifest, registry)
        for command in manifest.commands:
            for alias in command.aliases:
                _attach(app, manifest, registry, name=alias)


def _attach(
    app: typer.Typer,
    manifest: ModuleManifest,
    registry: ModuleRegistry,
    *,
    name: str | None = None,
) -> None:
    command_name = name or manifest.name

    def dispatch(ctx: typer.Context) -> int:
        return _forward(ctx, manifest, registry)

    app.command(
        command_name,
        help=manifest.summary,
        add_help_option=False,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
        },
    )(dispatch)


def _forward(ctx: typer.Context, manifest: ModuleManifest, registry) -> int:
    if not manifest.cli_path:
        hint = manifest.resolved_install_hint() or "no install hint declared"
        msg = f"module {manifest.title!r} is not loadable: {manifest.summary}"
        raise DependencyError(msg, hint=hint)

    sub_app = registry.build_cli(manifest)  # the single deferred-import site
    from typer import main as typer_main

    command = typer_main.get_command(sub_app)
    # Always the module's canonical name, never the alias, and never bare "levix":
    # click appends the subcommand it is reporting, so a prog_name of "levix" made
    # `levix monitor cpu --json` blame a command called "levix cpu".
    result = command.main(
        args=list(ctx.args),
        prog_name=f"levix {manifest.name}",
        standalone_mode=False,
    )
    return int(result) if isinstance(result, int) else 0

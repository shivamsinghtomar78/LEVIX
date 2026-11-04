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
                _attach(
                    app,
                    manifest,
                    registry,
                    name=alias,
                    subcommand=command.name,
                    help_text=command.help or manifest.summary,
                )


def _attach(
    app: typer.Typer,
    manifest: ModuleManifest,
    registry: ModuleRegistry,
    *,
    name: str | None = None,
    subcommand: str | None = None,
    help_text: str | None = None,
) -> None:
    command_name = name or manifest.name
    # An alias IS the command it names, not a second way to reach the module's group:
    # `levix q hello` has to arrive as `levix ai ask hello`. Prepending the canonical name
    # here is what makes that true, and it is why the help line is the command's own rather
    # than the module summary.
    prefix = () if subcommand is None else (subcommand,)

    def dispatch(ctx: typer.Context) -> int:
        return _forward(ctx, manifest, registry, prefix=prefix)

    app.command(
        command_name,
        help=help_text or manifest.summary,
        add_help_option=False,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
        },
    )(dispatch)


def _forward(
    ctx: typer.Context,
    manifest: ModuleManifest,
    registry: ModuleRegistry,
    *,
    prefix: tuple[str, ...] = (),
) -> int:
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
    #
    # `obj` is not decoration: `command.main()` starts a brand-new click context with no
    # parent, so without it the LevixContext built by the root callback stops at the
    # forwarding command and every module reads its `tube.*`/`music.*` configuration as
    # the built-in fallback. click forwards **extra to Context(...), where obj is a
    # documented parameter.
    result = command.main(
        args=[*prefix, *ctx.args],
        prog_name=f"levix {manifest.name}",
        standalone_mode=False,
        obj=ctx.obj,
    )
    return int(result) if isinstance(result, int) else 0

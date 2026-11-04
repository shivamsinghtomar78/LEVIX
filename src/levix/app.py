"""Root Typer application: eager platform commands, lazily forwarded modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from . import __version__
from .config import Config
from .context import LevixContext
from .logging_setup import setup as setup_logging
from .paths import resolve_paths
from .router import register_modules
from .storage import Database
from .terminal import detect

if TYPE_CHECKING:
    from .registry import ModuleRegistry

APP_HELP = "One CLI. Multiple applications. Unlimited extensibility."


def build_context(*, create_user_file: bool = False) -> LevixContext:
    """Resolve paths, load config, attach logging and storage.

    Help is an eager option that exits before this runs, so `levix --help` touches no
    files at all.
    """
    paths = resolve_paths()
    profile = detect()
    config = Config.load(paths, create_user_file=create_user_file)
    logger = setup_logging(
        paths.log_dir,
        level=str(config.get("logging.level")),
        file_enabled=bool(config.get("logging.file_enabled")),
    )
    return LevixContext(
        paths=paths,
        config=config,
        database=Database(paths.database),
        profile=profile,
        logger=logger,
    )


def build_app(*, registry: ModuleRegistry | None = None) -> typer.Typer:
    from . import registry as registry_module
    from .commands import (
        config_app,
        create_module,
        dashboard_command,
        doctor_command,
        plugins_app,
        update_command,
    )

    if registry is not None:
        # Click instantiates the group itself, so injection goes through the
        # documented process accessor rather than a constructor argument.
        registry_module.use(registry)

    app = typer.Typer(
        name="levix",
        help=APP_HELP,
        add_completion=False,
        no_args_is_help=False,
        pretty_exceptions_show_locals=False,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )

    @app.callback(invoke_without_command=True)
    def root(
        ctx: typer.Context,
        version: bool = typer.Option(
            False, "--version", "-V", help="Show the LEVIX version and exit.", is_eager=True
        ),
    ) -> None:
        if version:
            typer.echo(f"levix {__version__}")
            raise typer.Exit(code=0)
        if not isinstance(ctx.obj, LevixContext):
            ctx.obj = build_context()
        if ctx.invoked_subcommand is None:
            dashboard_command(ctx)

    app.command("dashboard", help="Open the interactive terminal dashboard.")(
        dashboard_command
    )
    app.command("doctor", help="Report dependencies, capabilities and configuration health.")(
        doctor_command
    )
    app.command("update", help="Check whether a newer LEVIX is available.")(update_command)
    app.command(
        "create-module", help="Scaffold a new module/plugin you can develop and install."
    )(create_module)
    app.add_typer(config_app, name="config", help="Read and write LEVIX configuration.")
    app.add_typer(plugins_app, name="plugins", help="Inspect installed modules and plugins.")

    register_modules(app, registry_module.active())
    return app

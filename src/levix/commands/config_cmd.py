"""`levix config` - inspect and change configuration."""

from __future__ import annotations

import os
import subprocess
import sys

import typer
from rich.console import Console
from rich.table import Table

from ..config import (
    is_secret_key,
    remove_user_value,
    write_user_value,
)
from ..context import LevixContext
from ..errors import ConfigError

config_app = typer.Typer(help="Read and write LEVIX configuration.", no_args_is_help=True)
console = Console()

_MASK = "[set, hidden]"


def _ctx(typer_ctx: typer.Context) -> LevixContext:
    if not isinstance(typer_ctx.obj, LevixContext):
        msg = "configuration context was not initialised"
        raise ConfigError(msg)
    return typer_ctx.obj


@config_app.command("show")
def show(typer_ctx: typer.Context) -> None:
    """Print every resolved value and where it came from."""
    context = _ctx(typer_ctx)
    table = Table(title="LEVIX configuration", header_style="bold cyan")
    table.add_column("key", style="white")
    table.add_column("value", overflow="fold")
    table.add_column("source")
    table.add_column("file", justify="left")
    for row in context.config.resolved():
        value = _MASK if (is_secret_key(row.dotted) and row.value not in (None, "")) else row.value
        source = row.source
        table.add_row(row.dotted, str(value), source, str(context.paths.config_file))
    console.print(table)


@config_app.command("list")
def list_keys(typer_ctx: typer.Context, section: str = typer.Argument("")) -> None:
    """Machine-readable `key = value` lines (safe to pipe)."""
    context = _ctx(typer_ctx)
    for row in context.config.resolved():
        if section and not row.dotted.startswith(f"{section}."):
            continue
        value = _MASK if (is_secret_key(row.dotted) and row.value not in (None, "")) else row.value
        typer.echo(f"{row.dotted}={value}")


@config_app.command("get")
def get(typer_ctx: typer.Context, dotted: str) -> None:
    """Print one value."""
    context = _ctx(typer_ctx)
    value = context.value(dotted)
    if is_secret_key(dotted) and value:
        console.print(f"[yellow]{dotted} is secret-shaped; use the secrets store.[/yellow]")
    typer.echo(value)


@config_app.command("set")
def set_value(
    typer_ctx: typer.Context,
    dotted: str,
    value: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not prompt."),
) -> None:
    """Persist one override into config.toml, preserving comments and ordering."""
    context = _ctx(typer_ctx)
    if is_secret_key(dotted):
        msg = (
            f"{dotted} looks like a credential. Configuration files are plain text; "
            "store it with `levix ai key set` or the LEVIX_AI_API_KEY environment variable."
        )
        raise ConfigError(msg)
    stored = write_user_value(context.paths, dotted, value)
    typer.echo(f"{dotted} = {stored!r} written to {context.paths.config_file}")


@config_app.command("unset")
def unset(typer_ctx: typer.Context, dotted: str) -> None:
    """Remove an override so the value falls back to defaults or environment."""
    context = _ctx(typer_ctx)
    if remove_user_value(context.paths, dotted):
        typer.echo(f"removed {dotted} from {context.paths.config_file}")
    else:
        typer.echo(f"{dotted} was not set in your config file")


@config_app.command("reset")
def reset(
    typer_ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete config.toml, returning to packaged defaults."""
    context = _ctx(typer_ctx)
    path = context.paths.config_file
    if not path.exists():
        typer.echo(f"nothing to reset: {path} does not exist")
        raise typer.Exit(code=0)
    if not yes:
        from ..approve import require_approval

        require_approval(
            "delete your configuration file",
            str(path),
            destructive=True,
        )
    backup = path.with_suffix(".toml.bak")
    backup.write_bytes(path.read_bytes())
    path.unlink()
    typer.echo(f"removed {path} (backup kept at {backup})")


@config_app.command("path")
def path(typer_ctx: typer.Context, which: str = typer.Argument("config")) -> None:
    """Print a LEVIX directory: config, data, cache, state, log or database."""
    context = _ctx(typer_ctx)
    mapping = {
        "config": context.paths.config_dir,
        "file": context.paths.config_file,
        "data": context.paths.data_dir,
        "cache": context.paths.cache_dir,
        "state": context.paths.state_dir,
        "log": context.paths.log_dir,
        "database": context.paths.database,
    }
    if which not in mapping:
        msg = f"unknown location {which!r}; choose from {', '.join(sorted(mapping))}"
        raise ConfigError(msg)
    typer.echo(mapping[which])


@config_app.command("edit")
def edit(typer_ctx: typer.Context) -> None:
    """Open config.toml in $EDITOR, creating a commented stub if there is none."""
    context = _ctx(typer_ctx)
    context.paths.ensure()
    config_file = context.paths.config_file
    if not config_file.exists():
        config_file.write_text(
            "# LEVIX user configuration. Values here override packaged defaults.\n"
            "# Every supported key is listed by `levix config show`.\n"
            "# Remove a line to stop overriding it.\n\n"
            "[general]\n"
            '# theme = "default"\n',
            encoding="utf-8",
        )
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        editor = "notepad" if sys.platform.startswith("win") else "vi"
    try:
        subprocess.run([editor, str(config_file)], check=False)  # noqa: S603
    except OSError as exc:
        msg = f"could not start editor {editor!r}: {exc}"
        raise ConfigError(msg) from exc
    typer.echo(f"configuration will be re-read from {config_file}")

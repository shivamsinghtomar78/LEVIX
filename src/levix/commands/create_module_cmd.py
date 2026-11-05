"""`levix create-module NAME` - scaffold an installable plugin project.

The generated package is the same shape the seven official modules use, and it is
exercised by tests: scaffolding a module and loading its manifest through the real
registry is the only way to know the SDK is not fiction.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import typer
from rich.console import Console

from ..approve import require_approval
from ..errors import ConfigError
from ..terminal import markup_safe

console = Console()
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,29}$")


def create_module(
    name: str = typer.Argument(help="Lower-case module id, e.g. weather"),
    directory: Path = typer.Option(
        Path("."), "--directory", "-d", help="Where to create the project."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing project."),
    title: str = typer.Option("", "--title", help="Display name (defaults to a title-case id)."),
) -> None:
    """Write a plugin skeleton you can install with `pip install -e .`."""
    if not _NAME_RE.match(name):
        msg = (
            f"module name {name!r} must be 2-30 characters of lower-case letters, "
            "digits, '-' or '_'"
        )
        raise ConfigError(msg)

    target_root = directory / name
    package = "levix_" + name.replace("-", "_")
    if target_root.exists() and any(target_root.iterdir()):
        if not force:
            msg = (
                f"{target_root} already exists and is not empty. Refusing to overwrite. "
                "Re-run with --force after confirming."
            )
            raise ConfigError(msg)
        require_approval(
            "delete and recreate the scaffolded project",
            str(target_root),
            destructive=True,
        )
        shutil.rmtree(target_root)

    display = title or name.replace("-", " ").replace("_", " ").title()
    files = _template(name=name, package=package, display=display)
    for relative, content in files.items():
        path = target_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    console.print(
        f"[green]created[/green] {markup_safe(target_root)}\n"
        f"  package [bold]{markup_safe(package)}[/bold] exporting MANIFEST and build_app()\n\n"
        "Next steps:\n"
        f"  1. cd {markup_safe(target_root)}\n"
        "  2. python -m venv .venv && activate it\n"
        "  3. pip install -e .   (registers the levix.plugins entry point)\n"
        f"  4. levix plugins list  -> you should see [bold]{markup_safe(name)}[/bold]\n"
        f"  5. levix {markup_safe(name)}\n"
        "  6. pytest\n"
        "[dim]Third-party plugins run with LEVIX's full privileges. See "
        "docs/security/PERMISSIONS.md and docs/architecture/PLUGIN_ARCHITECTURE.md.[/dim]"
    )


def _template(*, name: str, package: str, display: str) -> dict[str, str]:
    entry = f"{package}:MANIFEST"
    return {
        "pyproject.toml": f"""[build-system]
requires = ["hatchling>=1.33"]
build-backend = "hatchling.build"

[project]
name = "levix-{name}"
version = "0.1.0"
description = "A LEVIX module."
requires-python = ">=3.12"
license = "MIT"
dependencies = ["levix>=0.4"]

[project.entry-points."levix.plugins"]
{name} = "{entry}"

[project.optional-dependencies]
dev = ["pytest>=9", "ruff>=0.17"]

[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]
""",
        f"src/{package}/__init__.py": f'''"""{display} - a LEVIX module."""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, Permission

__all__ = ["MANIFEST", "build_app"]

MANIFEST = ModuleManifest(
    name="{name}",
    title="{display}",
    summary="Say what this module does in one line.",
    cli_path="{package}.cli:build_app",
    version="0.1.0",
    commands=(CommandInfo(name="hello", help="Print a greeting."),),
    requirements=(),
    permissions=frozenset({{Permission.FS_READ}}),
    documentation="README.md",
)


def build_app():
    """Deferred import keeps `levix --help` cheap."""
    from {package}.cli import build_app as _build

    return _build()
''',
        f"src/{package}/cli.py": f'''"""Command surface for {display}."""

from __future__ import annotations

import typer
from rich.console import Console

from {package} import MANIFEST

console = Console()


def build_app() -> typer.Typer:
    app = typer.Typer(name="{name}", help=MANIFEST.summary, no_args_is_help=True)

    @app.command("hello")
    def hello(
        who: str = typer.Argument("world", help="Who to greet."),
    ) -> None:
        """Greet someone."""
        # `markup=False` because `who` is the caller's text: Rich would otherwise read a
        # `[/bold]` typed at the prompt as a style tag. The SDK exposes no escaping helper
        # yet, so the scaffold models the safe form rather than the handy one.
        console.print(f"{{MANIFEST.title}} says hello, {{who}}", markup=False, style="bold cyan")

    return app
''',
        "README.md": f"""# levix-{name}

A module for [LEVIX](https://github.com/shivamsinghtomar78/LEVIX).

## Install (development)

```bash
python -m venv .venv
. .venv/bin/activate    # Windows: .venv\\Scripts\\activate
pip install -e .
levix plugins list      # {name} should appear
levix {name}            # Typer mounts a one-command module directly, so there is no
levix {name} you        # `hello` subcommand to type: the argument is the greeting target
```

## How it works

`src/{package}/__init__.py` exports a `ModuleManifest` (pure data, imported by
`levix --help`) and `src/{package}/cli.py` builds the Typer app lazily. Heavy imports
belong inside command functions, never at module scope.
""",
        "tests/test_manifest.py": f"""from {package} import MANIFEST
from {package}.cli import build_app


def test_manifest_shape() -> None:
    assert MANIFEST.name == "{name}"
    assert MANIFEST.cli_path.endswith(":build_app")
    assert MANIFEST.command_names() == ("hello",)


def test_app_builds() -> None:
    assert build_app().info.name == "{name}"
""",
    }

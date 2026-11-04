"""`levix update` - report a newer release, never install it.

Talking to PyPI is the one place LEVIX reaches the network by default, so it is disclosed
in the output and in docs/security/THREAT_MODEL.md. Silently upgrading a running tool is a
supply-chain surprise; LEVIX prints the command and lets you run it, which also keeps the
behaviour identical under pip, pipx and a frozen build.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import typer
from rich.console import Console

from .. import __version__
from ..deps import _version_tuple
from ..errors import ProviderError

console = Console()
INDEX_URL = "https://pypi.org/pypi/levix/json"


def update_command(
    check_only: bool = typer.Option(
        True, "--check/--install-nothing", help="Always checks; LEVIX never self-updates."
    ),
    timeout: float = typer.Option(6.0, "--timeout", min=1.0, max=60.0),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Check PyPI for a newer LEVIX."""
    del check_only
    try:
        latest, error = _fetch_latest(timeout)
    except urllib.error.HTTPError as exc:
        error = f"PyPI returned {exc.code}"
        latest = None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"no response from PyPI ({exc.__class__.__name__})"
        latest = None

    if latest is None:
        if as_json:
            typer.echo(json.dumps({"installed": __version__, "available": None, "error": error}))
        else:
            console.print(
                f"[yellow]could not check for updates:[/yellow] {error}\n"
                "[dim]this is a network limitation, not an indication that you are up to date."
                "[/dim]"
            )
        raise ProviderError(
            f"update check failed: {error}",
            hint="check connectivity, or run `pip index versions levix` yourself",
        )

    installed_newer = (_version_tuple(__version__) or (0,)) >= (_version_tuple(latest) or (0,))
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "installed": __version__,
                    "available": latest,
                    "up_to_date": installed_newer,
                    "command": 'pip install --upgrade "levix"',
                }
            )
        )
        return

    if installed_newer:
        console.print(f"[green]LEVIX {__version__} is the latest release[/green] (PyPI: {latest})")
        return
    console.print(
        f"[cyan]LEVIX {latest} is available[/cyan] (you have {__version__}).\n"
        "LEVIX does not modify its own installation. Upgrade with:\n"
        "    pip install --upgrade levix\n"
        "    pipx upgrade levix\n"
        f"    standalone: download {latest} from the GitHub Releases page"
    )


def _fetch_latest(timeout: float) -> tuple[str | None, str | None]:
    request = urllib.request.Request(
        INDEX_URL, headers={"Accept": "application/json", "User-Agent": f"levix/{__version__}"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    version = payload.get("info", {}).get("version")
    return (str(version), None) if version else (None, "PyPI response had no version")

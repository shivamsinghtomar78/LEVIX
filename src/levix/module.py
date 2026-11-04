"""The registration contract shared by official modules and third-party plugins.

A module is *data* plus two factories. Keeping the manifest free of imports is what
makes lazy `levix --help` possible: the registry can list every module without
importing a single heavy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class Origin(StrEnum):
    """Who provided a module. Stamped by the registry, never trusted from a plugin."""

    OFFICIAL = "official"
    THIRD_PARTY = "third_party"


class Permission(StrEnum):
    NETWORK = "network"
    FS_READ = "fs_read"
    FS_WRITE = "fs_write"
    SUBPROCESS = "subprocess"
    AUDIO = "audio"
    # A permission name, not a credential: S105 reads the `SECRET` prefix as an assignment.
    SECRET_READ = "secret_read"  # noqa: S105
    # Kept separate from SECRET_READ on purpose: "this module can read your keys" and
    # "this module can replace them" are different things to a user deciding to install it.
    SECRET_WRITE = "secret_write"  # noqa: S105


@dataclass(frozen=True, slots=True)
class PackageRef:
    """A pip-installable requirement.

    `import_name` is probed for availability, `dist_name` is what we report and
    suggest installing. They differ often enough (`yt_dlp` vs `yt-dlp`) that
    keeping one field would produce wrong hints.
    """

    import_name: str
    dist_name: str | None = None
    minimum: str | None = None

    @property
    def distribution(self) -> str:
        return self.dist_name or self.import_name


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """One line of help text per subcommand.

    Deliberately does NOT model parameters: Typer's type hints are the single
    source of truth for arguments. Duplicating them here creates a second
    contract that drifts from the first.
    """

    name: str
    help: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UiSpec:
    """How the dashboard launches this module.

    `screen`  -> push a Textual screen inside the running dashboard (widget-only work).
    `suspend` -> release the terminal and re-enter `levix <cmd>` in a subprocess.
    `hidden`  -> not offered by the dashboard.

    One TTY cannot host two Textual apps, so full-screen modules MUST use `suspend`.
    """

    mode: Literal["screen", "suspend", "hidden"] = "suspend"
    screen_path: str | None = None
    argv: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    """Everything LEVIX needs to know about a module without importing it."""

    name: str
    title: str
    summary: str
    cli_path: str
    commands: tuple[CommandInfo, ...] = ()
    version: str = ""
    requirements: tuple[PackageRef, ...] = ()
    extras: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    ui: UiSpec | None = None
    install_hint: str | None = None
    documentation: str | None = None
    origin: Origin = Origin.THIRD_PARTY
    provider: str = ""

    def command_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.commands)

    def resolved_install_hint(self) -> str | None:
        """How to install whatever this module is missing.

        A third-party module that declares no provider distribution cannot yield a valid
        line: `pip install "[tube]"` names no package. Returning None here makes the
        caller say "no install hint is declared" rather than print something that fails.
        """
        if self.install_hint:
            return self.install_hint
        extra = "+".join(self.extras)
        if self.origin is Origin.OFFICIAL:
            return f'pip install "levix[{extra}]"' if extra else None
        if not self.provider:
            return None
        return (
            f'pip install "{self.provider}[{extra}]"' if extra else f"pip install {self.provider}"
        )

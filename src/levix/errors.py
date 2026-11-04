"""Exception hierarchy and the single exit-code table.

Every command's behaviour under failure is defined here, in one place, so that
scripts wrapping LEVIX can rely on codes rather than on parsing prose.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_UNKNOWN_MODULE = 4
EXIT_CONFIG = 5
EXIT_CANCELLED = 6
EXIT_TOOL_FAILED = 7
EXIT_PROVIDER = 8
EXIT_INTERRUPTED = 130

EXIT_CODE_MEANINGS: dict[int, str] = {
    EXIT_OK: "success",
    EXIT_RUNTIME: "unhandled runtime error",
    EXIT_USAGE: "bad command line usage (click default)",
    EXIT_MISSING_DEPENDENCY: "an optional dependency or extra is not installed",
    EXIT_UNKNOWN_MODULE: "no module or command with that name",
    EXIT_CONFIG: "configuration file or value is invalid",
    EXIT_CANCELLED: "the user declined the confirmation prompt",
    EXIT_TOOL_FAILED: "an external tool ran and failed (ffmpeg, mpv, ...)",
    EXIT_PROVIDER: "a network or model-provider call failed",
    EXIT_INTERRUPTED: "interrupted (Ctrl+C)",
}


class LevixError(Exception):
    """Base class. Renders a clean message and exits with `exit_code`."""

    exit_code = EXIT_RUNTIME
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint

    @property
    def message(self) -> str:
        return str(self)


class DependencyError(LevixError):
    exit_code = EXIT_MISSING_DEPENDENCY


class UnknownModuleError(LevixError):
    exit_code = EXIT_UNKNOWN_MODULE


class ConfigError(LevixError):
    exit_code = EXIT_CONFIG


class UserCancelledError(LevixError):
    exit_code = EXIT_CANCELLED


class ExternalToolError(LevixError):
    exit_code = EXIT_TOOL_FAILED


class ProviderError(LevixError):
    exit_code = EXIT_PROVIDER

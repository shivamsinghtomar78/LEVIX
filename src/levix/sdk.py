"""Public plugin SDK: a stable name over the internal contract.

This module intentionally contains no logic. A façade with re-exports gives plugin
authors an API we can promise not to break, without a parallel implementation that
could drift from the real one.
"""

from __future__ import annotations

from .context import LevixContext
from .errors import (
    ConfigError,
    DependencyError,
    ExternalToolError,
    LevixError,
    ProviderError,
    UnknownModuleError,
    UserCancelledError,
)
from .module import (
    CommandInfo,
    LevixModuleProtocol,
    ModuleManifest,
    Origin,
    PackageRef,
    Permission,
    UiSpec,
)

__all__ = [
    "CommandInfo",
    "ConfigError",
    "DependencyError",
    "ExternalToolError",
    "LevixContext",
    "LevixError",
    "LevixModuleProtocol",
    "ModuleManifest",
    "Origin",
    "PackageRef",
    "Permission",
    "ProviderError",
    "UiSpec",
    "UnknownModuleError",
    "UserCancelledError",
]

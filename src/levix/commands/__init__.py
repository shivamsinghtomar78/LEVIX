"""Platform-level commands: the parts of LEVIX that are not modules.

Named `commands` rather than `platform` to avoid shadowing the stdlib `platform`
module in a project whose whole promise is cross-platform behaviour.
"""

from __future__ import annotations

from .config_cmd import config_app
from .create_module_cmd import create_module
from .dashboard_cmd import dashboard_command
from .doctor_cmd import doctor_command
from .plugins_cmd import plugins_app
from .update_cmd import update_command

__all__ = [
    "config_app",
    "create_module",
    "dashboard_command",
    "doctor_command",
    "plugins_app",
    "update_command",
]

"""Secret resolution: environment -> OS keyring -> restricted local file.

Config files are deliberately NOT consulted for secrets, and `levix config list`
masks anything that looks like one. The fallback file is *access-controlled
plaintext*, not encryption; `levix doctor` reports that as DEGRADED rather than
pretending the user's API key is encrypted at rest.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from .paths import Paths

SERVICE = "levix"
_ENV_PREFIX = "LEVIX_"


def env_var_for(name: str) -> str:
    return f"{_ENV_PREFIX}{name.upper()}"


def _keyring():
    """Return the keyring module if importable, else None. Never imports it blindly."""
    import importlib.util

    if importlib.util.find_spec("keyring") is None:
        return None
    try:
        import keyring

        return keyring
    except Exception:
        return None


def backend(paths: Paths) -> tuple[str, str]:
    """(backend_id, honest description) for the store that *would* be used."""
    kr = _keyring()
    if kr is not None:
        try:
            name = type(kr.get_current_keyring()).__name__
            return "keyring", f"OS keyring via keyring backend {name}"
        except Exception:
            return "keyring", "OS keyring (backend probe failed; falls back per call)"
    if os.environ.get("LEVIX_DISABLE_FILE_SECRETS") == "1":
        return "none", "no keyring installed and file store disabled"
    return "file", (
        f"plaintext file at {paths.secrets_file} with owner-only permissions "
        "(access control, not encryption)"
    )


def get_secret(name: str, *, paths: Paths) -> tuple[str | None, str]:
    """Returns (value, source) where source is env|keyring|file|none."""
    from_env = os.environ.get(env_var_for(name))
    if from_env:
        return from_env, "env"

    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, name)
        except Exception:
            value = None
        if value:
            return value, "keyring"

    stored = _read_file(paths.secrets_file).get(name)
    if stored:
        return str(stored), "file"
    return None, "none"


def set_secret(name: str, value: str, *, paths: Paths) -> str:
    """Store a secret, preferring the OS keyring. Returns the store actually used."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            # If a previous run fell back to the file, do not leave a stale copy.
            _file_delete(paths.secrets_file, name)
            return "keyring"
        except Exception:
            pass

    if os.environ.get("LEVIX_DISABLE_FILE_SECRETS") == "1":
        msg = (
            "cannot store secrets: no OS keyring available and the plaintext file "
            "store is disabled. Set " + env_var_for(name) + " instead."
        )
        raise RuntimeError(msg)

    paths.ensure()
    data = _read_file(paths.secrets_file)
    data[name] = value
    _write_file(paths.secrets_file, data)
    return "file"


def delete_secret(name: str, *, paths: Paths) -> bool:
    removed = False
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
            removed = True
        except Exception:
            pass
    removed = _file_delete(paths.secrets_file, name) or removed
    return removed


def _read_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_file(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    _harden(path)


def _harden(path: Path) -> None:
    """Owner-only access. POSIX chmod plus a Windows ACL reset."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if os.name == "nt":
        try:
            user = os.environ.get("USERNAME") or os.environ.get("USER")
            if user:
                subprocess.run(  # noqa: S603 - fixed argv, no shell
                    [
                        "icacls",
                        str(path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{user}:F",
                    ],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
        except (OSError, subprocess.SubprocessError):
            pass


def _file_delete(path: Path, name: str) -> bool:
    data = _read_file(path)
    if name not in data:
        return False
    del data[name]
    if data:
        _write_file(path, data)
    else:
        try:
            path.unlink()
        except OSError:
            return False
    return True

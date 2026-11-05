"""The permissions of the file that holds a key, asserted on that file.

`secrets._harden` swallows `OSError` from its `chmod`, so a store that never became
owner-only still describes itself as the plaintext file backend and `levix doctor` still
says `degraded` and nothing more specific. Reading `_harden` proves it contains a `chmod`;
these cases prove the file is not readable by anyone else - which is the only thing the
description promises the user.

The Windows case asserts what Windows actually enforces (an explicit ACL, read back with
`icacls`), because `st_mode` there is derived from the file attributes and reports `0o666`
for every ordinary file whether or not anything protected it.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from levix import secrets
from levix.paths import Paths

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="the mode bits are not what Windows enforces"
)
windows_only = pytest.mark.skipif(os.name != "nt", reason="icacls is the Windows ACL tool")


@pytest.fixture
def file_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """A real `Paths` under `tmp_path` with no keyring, so every write reaches secrets.json."""
    monkeypatch.setattr(secrets, "_keyring", lambda: None)
    monkeypatch.delenv("LEVIX_DISABLE_FILE_SECRETS", raising=False)
    return Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        log_dir=tmp_path / "log",
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _store_one_key(paths: Paths) -> Path:
    secrets.set_secret("AI_API_KEY", "sk-live-1a2b3c4d5e6f", paths=paths)
    path = paths.secrets_file
    assert path.exists(), "with no keyring the file backend is the documented route"
    return path


@posix_only
def test_a_stored_key_lands_in_a_file_only_the_owner_can_read(file_store: Paths) -> None:
    path = _store_one_key(file_store)
    assert _mode(path) == 0o600, f"secrets.json is mode {oct(_mode(path))}, not owner-only"


@posix_only
def test_a_chmod_that_fails_leaves_no_more_access_than_the_open_gave(
    file_store: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why the file is created at 0600 instead of written at the default mode and hardened after.

    `_harden`'s `suppress(OSError)` is deliberate - a key already on disk must not crash the
    command that stored it - so on a filesystem that refuses the chmod the mode the file was
    *born* with is the only protection it gets.
    """

    attempted: list[Path] = []

    def refuse_chmod(self: Path, *_args: object, **_kwargs: object) -> None:
        attempted.append(self)
        msg = "this filesystem refused the chmod"
        raise PermissionError(msg)

    monkeypatch.setattr(Path, "chmod", refuse_chmod)
    path = _store_one_key(file_store)
    assert attempted == [path], (
        "the fake chmod never ran, so this case would prove nothing about a failing one"
    )
    assert not _mode(path) & 0o077, "group or other can read a provider key"


@posix_only
def test_rewriting_an_existing_store_does_not_widen_its_access(file_store: Paths) -> None:
    path = file_store.secrets_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)
    assert _mode(path) == 0o644, "O_CREAT ignores the mode of a file that already exists"
    _store_one_key(file_store)
    assert _mode(path) == 0o600, "only the chmod can bring an overwritten store back to 0600"


@windows_only
def test_the_acl_holds_one_explicit_grant_and_no_inherited_read(file_store: Paths) -> None:
    if shutil.which("icacls") is None:
        pytest.skip("icacls is not on this machine, so the ACL cannot be read back")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    assert user, "_harden needs a username to grant to"
    path = _store_one_key(file_store)

    probe = subprocess.run(
        ["icacls", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert probe.returncode == 0, (
        f"icacls could not read the store back: {probe.stdout}{probe.stderr}"
    )

    # One line per file: "<path> <principal>:(<permission>) ..." - the filename is the safest
    # split, because a temporary directory may contain spaces and the path is not quoted.
    lines = [line for line in probe.stdout.splitlines() if path.name in line]
    assert len(lines) == 1, f"expected one ACL line for {path}, got {probe.stdout!r}"
    _, _, grants = lines[0].partition(path.name)
    entries = [ace for ace in grants.split() if ace]
    assert entries, f"the file carries no explicit grant at all: {lines[0]!r}"
    for ace in entries:
        principal = ace.rsplit(":", 1)[0]
        expected = user.lower()
        assert principal.lower() == expected or principal.lower().endswith(f"\\{expected}"), (
            f"{principal!r} still has access to the key store, and it is not the owner"
        )

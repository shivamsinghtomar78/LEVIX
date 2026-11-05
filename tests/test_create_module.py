"""`levix create-module` - the scaffold is installed and run, not merely generated.

The generator's own docstring claims the tree it writes "is exercised by tests". Before
this file that was not true: `tests/test_plugin_example.py` proves the shape of the checked-in
example, not of what `_template` emits, so a drift in the template - a wrong entry point, a
manifest that imports its CLI, a package name that does not match its directory - would have
passed the suite. Every case here starts from the real command writing into a temporary
directory, then registers what appeared the way `pip install -e .` would and drives it through
the real router.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys

import pytest

from levix import registry as registry_module
from levix.errors import EXIT_CANCELLED, EXIT_CONFIG
from levix.module import Origin, Permission
from levix.registry import ModuleRegistry

FILES = (
    "pyproject.toml",
    "README.md",
    "src/levix_weather/__init__.py",
    "src/levix_weather/cli.py",
    "tests/test_manifest.py",
)


@pytest.fixture
def scaffolded(run_cli, tmp_path, monkeypatch, capsys):
    """Create the project with the real command, then register it as a distribution would."""
    work = tmp_path / "work"
    assert run_cli("create-module", "weather", "--directory", str(work)) == 0
    capsys.readouterr()
    root = work / "weather"

    meta = tmp_path / "meta"
    info = meta / "levix_weather-0.1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: levix-weather\nVersion: 0.1.0\nSummary: scaffold\n",
        encoding="utf-8",
    )
    (info / "entry_points.txt").write_text(
        "[levix.plugins]\nweather = levix_weather:MANIFEST\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(meta))
    monkeypatch.syspath_prepend(str(root / "src"))
    _forget_weather()
    importlib.invalidate_caches()
    # The create-module call above already built the process-wide registry, and a registry
    # caches what it found. Dropping it is what `levix` does between processes: without this
    # the CLI in the cases below still answers with the discovery that ran before the plugin
    # existed, and `weather` is an unknown command.
    registry_module.use(None)
    yield root
    _forget_weather()
    registry_module.use(None)


def _forget_weather() -> None:
    """The package may already be imported by an earlier case in this process."""
    for name in [key for key in sys.modules if key.startswith("levix_weather")]:
        del sys.modules[name]


def flat(text: str) -> str:
    """Match a sentence the way it was written, not the way the terminal folded it.

    These messages quote a temp path, and the width a report gets is not the point of the
    assertion; joining the runs of whitespace is what lets the same case pass on an 80-column
    capture and on a CI runner that wraps somewhere else.
    """
    return " ".join(text.split())


def test_the_scaffold_writes_every_file_the_contract_needs(run_cli, tmp_path, capsys):
    work = tmp_path / "work"
    assert run_cli("create-module", "weather", "--directory", str(work)) == 0
    root = work / "weather"
    for relative in FILES:
        assert (root / relative).is_file(), f"{relative} is part of the contract"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'weather = "levix_weather:MANIFEST"' in pyproject, "the entry point names the package"
    assert 'name = "levix-weather"' in pyproject
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "levix weather hello" not in readme, "there is no `hello` subcommand to document"
    out = capsys.readouterr().out
    assert "created" in out and "levix_weather" in out


def test_the_generated_manifest_loads_through_the_real_registry(scaffolded):
    manifest = ModuleRegistry().discover()["weather"]
    assert manifest.title == "Weather", "the default title is the title-cased id"
    assert manifest.cli_path == "levix_weather.cli:build_app"
    assert manifest.command_names() == ("hello",)
    assert manifest.provider == "levix-weather"
    assert manifest.origin is Origin.THIRD_PARTY, "a scaffold is never stamped official"
    assert manifest.permissions == frozenset({Permission.FS_READ}), "what the template discloses"
    assert all(isinstance(p, Permission) for p in manifest.permissions), (
        "a quoted name is a string that only looks like a permission"
    )


def test_the_disclosure_report_reads_the_generated_permissions(scaffolded, run_cli, capsys):
    """`plugins info` asks every declared permission for `.value`, so members are required.

    A string that merely looks like `Permission.FS_READ` survives discovery and the router,
    and raises inside the report - which is how the quoted name the template used to emit
    stayed invisible to a suite that never installed the scaffold it writes.
    """
    assert run_cli("plugins", "info", "weather") == 0
    out = capsys.readouterr().out
    assert "fs_read" in out, "the disclosure prints the value, not the attribute name"
    assert "not an enforced limit" in flat(out), "the disclosure says what it is not"
    assert "Traceback" not in out and "unexpected error" not in out


def test_the_generated_command_runs_through_the_real_router(scaffolded, run_cli, capsys):
    """A one-command Typer app mounts as the command itself, so `weather hello` is wrong.

    `hello` is the name of the function inside the module, not a subcommand on the command
    line; the argument is `who`. The scaffold's own README used to tell the reader to type
    `levix weather hello`, which click refused as an extra argument.
    """
    assert run_cli("weather", "plugin") == 0
    assert "Weather says hello, plugin" in capsys.readouterr().out
    assert run_cli("weather") == 0
    assert "Weather says hello, world" in capsys.readouterr().out


def test_the_generated_manifest_imports_no_cli_module(scaffolded):
    """`levix --help` loads every manifest, so the package root has to stay pure data."""
    registry = ModuleRegistry()
    assert "weather" in registry.discover()
    assert "levix_weather.cli" not in sys.modules, "reading MANIFEST must not build the CLI"
    registry.build_cli(registry.discover()["weather"])
    assert "levix_weather.cli" in sys.modules, "the CLI arrives when the module is used"


def test_the_generated_project_passes_its_own_test_suite(scaffolded):
    """A new author runs `pytest` on the scaffold before they write anything, so it passes.

    A child interpreter, with `src/` on the path the way an editable install would put it
    there; the argument list never goes through a shell.
    """
    env = dict(os.environ, PYTHONPATH=str(scaffolded / "src"))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=scaffolded,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@pytest.mark.parametrize("name", ["Weather", "w", "has space", "9lives", "x" * 31])
def test_a_name_that_is_not_a_module_id_is_refused_and_creates_nothing(
    run_cli, capsys, tmp_path, name
):
    assert run_cli("create-module", name, "--directory", str(tmp_path)) == EXIT_CONFIG
    assert "must be 2-30 characters" in flat(capsys.readouterr().err)
    assert not (tmp_path / name).exists(), "a refusal must leave no project behind"


def test_an_existing_project_is_never_overwritten_unasked(scaffolded, run_cli, capsys):
    marker = scaffolded / "work_done_here.txt"
    marker.write_text("keep me", encoding="utf-8")
    assert run_cli("create-module", "weather", "--directory", str(scaffolded.parent)) == EXIT_CONFIG
    assert "Refusing to overwrite" in flat(capsys.readouterr().err)
    assert marker.read_text(encoding="utf-8") == "keep me"


def test_force_without_a_terminal_refuses_and_deletes_nothing(scaffolded, run_cli, capsys):
    """`--force` is a flag, not a consent: a captured stdin has to stop the rmtree."""
    marker = scaffolded / "work_done_here.txt"
    marker.write_text("keep me", encoding="utf-8")
    capsys.readouterr()
    code = run_cli("create-module", "weather", "--directory", str(scaffolded.parent), "--force")
    assert code == EXIT_CANCELLED
    captured = capsys.readouterr()
    assert "without a terminal to confirm in" in flat(captured.err)
    assert marker.read_text(encoding="utf-8") == "keep me", "a refusal deleted someone's work"
    assert (scaffolded / "pyproject.toml").is_file()

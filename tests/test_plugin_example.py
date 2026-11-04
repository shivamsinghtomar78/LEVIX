"""The example plugin, installed and run for real.

Registration is a distribution metadata lookup, so the honest way to test it without
touching the project's environment is to build the `.dist-info` in a temp directory and
put that directory on `sys.path`. The package it points at is the actual
`plugin-examples/hello` source, so nothing about this is a mock: a real entry point, a
real manifest, a real forwarded context, a real command run through the real router.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from levix.module import Origin
from levix.registry import ModuleRegistry

EXAMPLE = Path(__file__).resolve().parents[1] / "plugin-examples" / "hello"
METADATA = """\
Metadata-Version: 2.1
Name: levix-hello
Version: 0.1.0
Summary: Example LEVIX plugin: greet, then show what the host session looks like.
Author: LEVIX
License: MIT
"""
ENTRY_POINTS = "[levix.plugins]\nhello = levix_hello:MANIFEST\n"


@pytest.fixture
def hello_installed(tmp_path, monkeypatch):
    """Put the example on the import path with a distribution that registers it."""
    dist = tmp_path / "levix_hello-0.1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(METADATA, encoding="utf-8")
    (dist / "entry_points.txt").write_text(ENTRY_POINTS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.syspath_prepend(str(EXAMPLE / "src"))
    # FileFinder caches directory listings, and `levix_hello` may already be imported by
    # an earlier test in the same process.
    for name in [key for key in sys.modules if key.startswith("levix_hello")]:
        del sys.modules[name]
    importlib.invalidate_caches()
    yield dist
    for name in [key for key in sys.modules if key.startswith("levix_hello")]:
        del sys.modules[name]


def test_the_entry_point_is_discovered_as_a_third_party_module(hello_installed):
    manifest = ModuleRegistry().discover()["hello"]
    assert manifest.title == "Hello"
    assert manifest.cli_path == "levix_hello.cli:build_app"
    assert manifest.version == "0.1.0", "the version comes from the distribution"
    assert manifest.provider == "levix-hello", "the provider is the installing distribution"


def test_a_plugin_cannot_claim_to_be_official(hello_installed):
    """`origin` is stamped by the registry from the provider, not read from the manifest."""
    manifest = ModuleRegistry().discover()["hello"]
    assert manifest.origin is Origin.THIRD_PARTY


def test_a_third_party_command_runs_through_the_router(run_cli, hello_installed, capsys):
    assert run_cli("hello", "greet", "levix") == 0
    out = capsys.readouterr().out
    assert "hello, levix" in out
    assert "theme=default" in out, "the config the core resolved reached the plugin"


def test_a_plugin_alias_is_registered_the_same_way(run_cli, hello_installed, capsys):
    """`hi` is an alias of the plugin's `greet` command, so it is that command.

    The name after it is the `name` argument, not a second subcommand: forwarding `hi`
    to the module's group made `levix hi greet alias` parse `alias` as an extra argument
    (exit 2) while `levix hi -h` still advertised `greet`.
    """
    assert run_cli("hi", "alias", "--times", "3") == 0
    assert capsys.readouterr().out.count("hello, alias") == 3


def test_a_plugin_sees_the_paths_and_history_of_the_run_it_is_in(
    run_cli, hello_installed, capsys, levix_home, monkeypatch
):
    """The point of `ctx.obj`: a plugin reads the same profile the command line does."""
    # 200 columns keeps the table from folding a 100-character temp path across lines, so
    # the assertion below compares against the path as written.
    monkeypatch.setenv("COLUMNS", "200")
    assert run_cli("hello", "greet", "profile") == 0
    assert run_cli("hello", "where") == 0
    out = capsys.readouterr().out
    assert str(levix_home) in out, "the plugin printed the profile this test created"
    assert "levix hello greet profile" in out, "the shared history recorded the earlier run"


def test_the_plugin_is_listed_with_the_modules_the_core_ships(run_cli, hello_installed, capsys):
    assert run_cli("plugins", "list") == 0
    out = capsys.readouterr().out
    assert "hello" in out
    assert "third_party" in out or "third-party" in out


def test_the_example_itself_imports_nothing_heavy_at_manifest_time(hello_installed):
    """`levix --help` imports every manifest, so the package root must stay pure data.

    Asserting on the plugin's own modules is what makes this a test of the example and
    not of the parent process, which has imported Typer and Rich for other reasons.
    """
    registry = ModuleRegistry()
    assert "hello" in registry.discover()
    assert "levix_hello.cli" not in sys.modules, "loading MANIFEST must not pull in the CLI"
    registry.build_cli(registry.discover()["hello"])
    assert "levix_hello.cli" in sys.modules, "the CLI arrives when the module is actually used"

"""The lazy router: forwarding, the lightweight-core invariant, and exit codes.

These are core tests, so they use a stub module rather than a real one: the behaviour
under test is the forwarding itself, and a stub keeps the heavy dependencies out of it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import typer

from levix import registry as registry_module
from levix.context import LevixContext
from levix.deps import ensure_dependencies
from levix.errors import (
    EXIT_CONFIG,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PROVIDER,
    EXIT_UNKNOWN_MODULE,
    EXIT_USAGE,
    ProviderError,
)
from levix.module import CommandInfo, ModuleManifest, PackageRef
from levix.registry import ModuleRegistry

HEAVY = ("psutil", "yt_dlp", "sounddevice", "soundfile", "numpy", "textual")


def stub_manifest(**overrides) -> ModuleManifest:
    base = {
        "name": "stub",
        "title": "Stub",
        "summary": "a module used only by these tests",
        "cli_path": "test_router:build_stub_app",
        "commands": (CommandInfo("note", "write a note", aliases=("nt",)),),
        "requirements": (),
    }
    base.update(overrides)
    return ModuleManifest(**base)


CURRENT_MANIFEST = stub_manifest()


def build_stub_app() -> typer.Typer:
    app = typer.Typer(
        name="stub",
        help="a module used only by these tests",
        no_args_is_help=True,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @app.callback()
    def gate(ctx: typer.Context) -> None:
        # Every official module does exactly this in its own Typer callback: the gate is
        # what turns a missing extra into exit 3 instead of an ImportError.
        if ctx.invoked_subcommand is not None:
            ensure_dependencies(CURRENT_MANIFEST)

    @app.command()
    def note(
        ctx: typer.Context,
        message: str = typer.Argument("nothing"),
        loud: bool = typer.Option(False, "--loud"),
        proof: str = typer.Option("", "--proof"),
        code: int = typer.Option(0, "--code"),
        boom: bool = typer.Option(False, "--boom"),
    ) -> None:
        """Record MESSAGE so the test can read back what arrived."""
        if boom:
            raise ProviderError("the stub provider said no")
        obj = ctx.obj
        recorded = (
            f"{type(obj).__name__}|{obj.value('general.history_limit')}|{message}|{loud}"
            if isinstance(obj, LevixContext)
            else f"NO_CONTEXT|{obj!r}|{message}|{loud}"
        )
        if proof:
            Path(proof).write_text(recorded, encoding="utf-8")
        else:
            typer.echo(recorded)
        if code:
            raise typer.Exit(code=code)

    return app


class StubRegistry(ModuleRegistry):
    def __init__(self, manifest: ModuleManifest) -> None:
        super().__init__()
        self._manifest = manifest

    def discover(self) -> dict[str, ModuleManifest]:
        return {self._manifest.name: self._manifest}

    def build_cli(self, manifest: ModuleManifest):
        return build_stub_app()


def install(manifest: ModuleManifest) -> ModuleManifest:
    """Put one stub module in front of the router.

    The stub CLI is reached through `registry.build_cli`, which returns the app built
    from CURRENT_MANIFEST, because a Typer factory takes no arguments - the same
    constraint an entry point puts on a real module.
    """
    global CURRENT_MANIFEST
    CURRENT_MANIFEST = manifest
    registry_module.use(StubRegistry(manifest))
    return manifest


@pytest.fixture
def stub(run_cli):
    """One stub module in the active registry, with its requirements met."""
    return install(stub_manifest())


def test_help_forwarding_does_not_import_a_heavy_dependency():
    loaded = _child_heavy_loads(["--help"])
    assert loaded == [], f"`levix --help` must stay cheap; it imported {loaded}"


def test_an_official_module_help_does_not_import_its_own_dependency():
    # The same invariant from the other side: asking a module for help must not import the
    # package its extra provides. `ai` and `music` failed this until their cores imported
    # httpx / numpy at module scope, which turned a missing extra into exit 1 plus a
    # traceback instead of exit 3 plus the pip line.
    for name in ("tube", "music", "ai", "monitor", "hacker", "files", "game"):
        loaded = _child_heavy_loads([name, "-h"])
        assert loaded == [], f"`levix {name} -h` must not import {loaded}"


def test_a_module_command_receives_the_context_built_by_the_root(run_cli, stub, tmp_path):
    """Regression: the forwarded sub-app starts a fresh click context.

    Without `obj=ctx.obj` in router._forward, every module read its configuration as the
    built-in fallback, because the LevixContext stopped at the forwarding command.
    """
    proof = tmp_path / "ctx.txt"
    assert run_cli("stub", "note", "hello", "--proof", str(proof)) == 0
    body = proof.read_text(encoding="utf-8")
    assert body.startswith("LevixContext|"), body
    assert "|hello|False" in body


def test_module_arguments_and_flags_survive_the_forwarding(run_cli, stub, tmp_path):
    proof = tmp_path / "args.txt"
    assert run_cli("stub", "note", "loud-and-clear", "--loud", "--proof", str(proof)) == 0
    assert proof.read_text(encoding="utf-8").endswith("|loud-and-clear|True")


def test_a_module_can_exit_with_its_own_code(run_cli, stub):
    assert run_cli("stub", "note", "x", "--code", "7") == 7


def test_a_levix_error_raised_inside_a_module_keeps_its_exit_code(run_cli, stub, capsys):
    assert run_cli("stub", "note", "--boom") == EXIT_PROVIDER
    assert "the stub provider said no" in capsys.readouterr().err


def test_a_bad_flag_inside_a_module_is_usage_error_not_a_crash(run_cli, stub, capsys):
    assert run_cli("stub", "note", "--no-such-flag") == EXIT_USAGE
    assert "levix stub" in capsys.readouterr().err


def test_a_command_alias_reaches_the_command_it_names(run_cli, stub, tmp_path, capsys):
    """`levix nt` is `levix stub note`, not a second way to open the module's group.

    The alias forwarded the argv untouched, so "via-alias" arrived as a subcommand name and
    `levix nt via-alias` exited 4 with `unknown command: via-alias` - a documented alias that
    could never be used.
    """
    proof = tmp_path / "alias.txt"
    assert run_cli("nt", "via-alias", "--proof", str(proof)) == 0
    assert "via-alias" in proof.read_text(encoding="utf-8")


def test_the_alias_help_shows_the_page_of_the_command_it_aliases(run_cli, stub, capsys):
    """`levix nt -h` is `note`'s own help page, not the module group's.

    The docstring on the stub's `note` command is what Typer renders as that page's
    description, so seeing it proves `-h` travelled through the forward and reached the
    subcommand the alias names.
    """
    assert run_cli("nt", "-h") == 0
    printed = capsys_text(capsys)
    assert "Usage: levix stub note" in printed, printed
    assert "Record MESSAGE" in printed, printed


def test_the_alias_is_listed_with_the_help_the_manifest_declares(run_cli, stub, capsys):
    """The root listing is built from CommandInfo, so it stays cheap and still explains itself."""
    assert run_cli("-h") == 0
    printed = capsys.readouterr().out
    assert "write a note" in printed, printed


def test_an_unknown_command_is_reported_with_the_modules_that_do_exist(run_cli, stub, capsys):
    assert run_cli("nostalgia") == EXIT_UNKNOWN_MODULE
    err = capsys.readouterr().err
    assert "unknown command: nostalgia" in err
    assert "stub" in err, "the listing is the registry's, so a plugin shows up in it too"


def test_a_module_that_is_missing_its_package_refuses_with_the_gate_message(run_cli, capsys):
    """The gate lives in the module's own Typer callback, which is also what keeps `-h`
    cheap: click handles the eager help option before any callback runs."""
    install(stub_manifest(requirements=(PackageRef("levix_no_such_package"),)))
    assert run_cli("stub", "note", "hello") == EXIT_MISSING_DEPENDENCY
    err = capsys_text(capsys)
    assert "levix_no_such_package is not installed" in err
    # Rich folds at 80 columns, so match the fragment that survives a line break.
    assert "install hint is declared" in err
    assert "pip install" not in err, "a hint that cannot work must not be printed"


def test_help_is_still_available_when_a_dependency_is_missing(run_cli, capsys):
    install(stub_manifest(requirements=(PackageRef("levix_no_such_package"),)))
    assert run_cli("stub", "-h") == 0
    assert "a module used only by these tests" in capsys_text(capsys)


def test_a_group_called_with_no_arguments_shows_its_help_and_calls_it_a_usage_error(
    run_cli, stub, capsys
):
    """click 8.5 raises NoArgsIsHelpError (a UsageError) rather than exiting 0, so a bare
    module name is reported as incomplete usage while still printing the help."""
    assert run_cli("stub") == EXIT_USAGE
    combined = capsys_text(capsys)
    assert "Usage: levix stub" in combined
    assert "note" in combined


def test_a_run_command_is_written_to_the_shared_history(run_cli, stub, tmp_path):
    proof = tmp_path / "history.txt"
    assert run_cli("stub", "note", "remember-me", "--proof", str(proof)) == 0
    from levix.app import build_context

    rows = build_context().database.recent_commands(20)
    logged = [row["argv"] for row in rows if "remember-me" in row["argv"]]
    assert logged, f"the command log never saw the run: {[r['argv'] for r in rows]}"
    assert logged[0].startswith("stub note")


def test_a_bad_configuration_value_is_reported_as_a_config_error(run_cli, stub, monkeypatch):
    monkeypatch.setenv("LEVIX_GENERAL_HISTORY_LIMIT", "not-a-number")
    assert run_cli("stub", "note", "hello") == EXIT_CONFIG


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def capsys_text(capsys) -> str:
    """stdout and stderr together, with escape sequences removed.

    click 8.5 sends a group's no-args help to stderr. The escape sequences matter because
    Typer forces a terminal whenever `GITHUB_ACTIONS` is set (`typer/rich_utils.py:77-82`),
    so a runner renders `Usage:` in bold and the style splits the literal these tests look
    for. Colour is not what forwarding is about; the text is.
    """
    captured = capsys.readouterr()
    return _ANSI.sub("", captured.out + captured.err)


def _child_heavy_loads(argv: list[str]) -> list[str]:
    """Run the real entry point in a fresh interpreter and report which heavy names it
    imported. Asserting on `sys.modules` of a child is the only way to test this, because
    the parent test process has already imported psutil and friends."""
    home = os.environ.get("LEVIX_HOME") or os.getcwd()
    script = (
        "import io, sys, contextlib\n"
        "from levix.main import main\n"
        f"argv = {argv!r}\n"
        "buf = io.StringIO()\n"
        "with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):\n"
        "    code = main(argv)\n"
        f"heavy = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "print('CODE=%d HEAVY=%s' % (code, ','.join(heavy)))\n"
    )
    env = dict(os.environ)
    env.update({"LEVIX_HOME": home, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"})
    finished = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    assert finished.returncode == 0, finished.stderr[-800:]
    tail = finished.stdout.strip().splitlines()[-1]
    assert tail.startswith("CODE=0"), f"the child exited oddly: {tail} {finished.stderr[-400:]}"
    return [name for name in tail.split("HEAVY=", 1)[1].split(",") if name]

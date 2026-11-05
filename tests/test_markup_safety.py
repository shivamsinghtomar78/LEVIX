"""Rich parses `[...]` as a style tag, so text the core did not author must be escaped.

This is one defect with many faces: an install hint (`pip install "levix[tube]"`), a
plugin's own summary, a filename with brackets, a line of command history. Unescaped, the
bracketed part does not raise - it disappears, so the user reads a different command or a
different claim than the one shipped. Each test renders through the real Rich console and
asserts the literal comes back.

Rich's console has a second parser over a printed `str`, and it takes a colon instead of a
bracket: `:abc:` is the emoji whose shortcode that is. That one is closed on the console
(`terminal.new_console`), not on the string, so the last three tests here go through the
console the commands build.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from levix.dashboard import module_list
from levix.dashboard.app import _describe
from levix.dashboard.history import recent_lines
from levix.module import CommandInfo, ModuleManifest, PackageRef, Permission, UiSpec
from levix.terminal import markup_safe

HINT = 'pip install "levix[tube]"'


def _render(text: str) -> str:
    """What a user with this terminal would actually read."""
    console = Console(record=True, width=200, color_system=None)
    console.print(text)
    return " ".join(console.export_text().split())


def test_an_unescaped_extra_loses_its_extra():
    # The failure this file exists to prevent, stated once so the fix is not a guess.
    assert _render(HINT) == 'pip install "levix"'


def test_the_config_mask_reaches_the_screen_as_words():
    """`_MASK` was `"[set, hidden]"`, which Rich read as a style tag: the masked value
    column rendered empty instead of saying a secret was there."""
    from levix.commands.config_cmd import _MASK

    assert _render(markup_safe(_MASK)) == _MASK
    assert not _MASK.startswith("["), "a mask that begins with a bracket is a style tag"


def test_markup_safe_round_trips_through_the_renderer():
    assert _render(markup_safe(HINT)) == HINT


def test_an_unbalanced_tag_raises_rather_than_being_deleted():
    """The other half of this defect: `[x]` disappears, but `[/x]` aborts the render.

    A stray close tag in a name the program did not choose is not a cosmetic loss - Rich
    raises while drawing the table, so the command fails. That is why escaping happens at
    every render site rather than only where the text looked likely to contain a bracket.
    """
    from rich.markup import MarkupError
    from rich.text import Text

    with pytest.raises(MarkupError):
        Text.from_markup("read from /etc/[/weird]")
    assert _render(markup_safe("read from /etc/[/weird]")) == "read from /etc/[/weird]"


def test_a_doctor_hint_keeps_its_extra(run_cli, capsys, monkeypatch):
    """The real table, with a finding whose hint names an extra."""
    from levix import doctor as doctor_core

    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(
        doctor_core.secrets,
        "backend",
        lambda paths: ("file", 'owner-only file. Install a keyring: pip install "levix[secrets]"'),
    )
    run_cli("doctor", "--only", "env")
    printed = " ".join(capsys.readouterr().out.split())
    assert 'pip install "levix[secrets]"' in printed


def test_a_plugins_info_install_line_keeps_the_extra(levix_home, capsys):
    """`levix plugins info` prints the hint for a module whose extra is absent."""
    from levix.main import main
    from levix.module import Origin

    manifest = ModuleManifest(
        name="brackets",
        title="Brackets",
        summary="a module with [square] in its prose",
        cli_path="levix.modules.tube.cli:build_app",
        commands=(CommandInfo("note", "write a [note]"),),
        requirements=(PackageRef("levix_no_such_package"),),
        extras=("tube",),
        origin=Origin.OFFICIAL,
        documentation="docs/modules/[TUBE].md",
        ui=UiSpec(),
        permissions=frozenset({Permission.FS_READ}),
    )
    _install(manifest)
    assert main(["plugins", "info", "brackets"]) == 0
    printed = " ".join(capsys.readouterr().out.split())
    assert HINT in printed
    assert "a module with [square] in its prose" in printed
    assert "docs/modules/[TUBE].md" in printed
    assert "note" in printed


def test_the_dashboard_list_keeps_a_plugins_own_brackets():
    manifest = ModuleManifest(
        name="brackets",
        title="Brackets",
        summary="needs [care] in the list",
        cli_path="levix.modules.tube.cli:build_app",
        ui=UiSpec(),
    )
    row = module_list.row_for(manifest)
    assert "[care]" in _render(row.label())
    assert "[care]" in _render(markup_safe(row.summary))


def test_the_detail_panel_escapes_every_manifest_field():
    manifest = ModuleManifest(
        name="brackets",
        title="Br[a]ckets",
        summary="the [summary]",
        cli_path="x:build_app",
        commands=(CommandInfo("note", "the [help]"),),
        requirements=(PackageRef("pkg[name]", minimum="1.0"),),
        documentation="docs/[x].md",
        permissions=frozenset({Permission.FS_READ}),
        ui=UiSpec(),
    )
    row = module_list.row_for(manifest)
    rendered = _render(_describe(manifest, row))
    for fragment in ("Br[a]ckets", "the [summary]", "the [help]", "pkg[name]", "docs/[x].md"):
        assert fragment in rendered, f"{fragment} was consumed as markup"


def test_history_lines_survive_the_markup_parser(levix_home):
    from levix.app import build_context

    context = build_context()
    context.database.apply_migrations(("core",))
    context.database.log_command(("[vid]movie", "download", "[vid]movie"), "[vid]movie", 0, 1.0)
    lines = recent_lines(context.database, limit=5)
    assert "[vid]movie" in _render("\n".join(lines))


def test_an_emoji_shortcode_reaches_the_screen_as_colons(capsys):
    """Rich's *second* parser over a printed `str`: `:name:` becomes that emoji.

    `markup_safe` cannot close this one, because there is no way to write a colon that
    means itself - the fix has to be on the console. `abc` is a real shortcode (U+1F524),
    which is why the fixture is a link whose scheme is followed by a word and not a
    made-up string.
    """
    from levix import terminal

    terminal.new_console().print("cannot fetch the magnet: link magnet:abc: only http")
    printed = capsys.readouterr().out
    assert "magnet:abc:" in printed
    assert "\U0001f524" not in printed


def test_the_console_that_refuses_emoji_still_renders_the_markup_levix_authors(capsys):
    """The fix is a switched-off parser, not a switched-off renderer."""
    from levix import terminal
    from levix.terminal import markup_safe

    terminal.new_console().print(
        f"[bold red]error:[/bold red] {markup_safe('pip install "levix[tube]"')}"
    )
    assert 'error: pip install "levix[tube]"' in capsys.readouterr().out


def test_a_refused_link_is_quoted_back_as_it_was_typed(run_cli, capsys):
    """The way a user reaches this defect: a link on the command line, named in its own
    refusal. Everything after the eaten colon used to be pulled up with it."""
    assert run_cli("music", "play", "magnet:abc") == 2
    printed = " ".join(capsys.readouterr().err.split())
    assert "magnet:abc" in printed


def _install(manifest: ModuleManifest) -> None:
    from levix import registry as registry_module
    from levix.registry import ModuleRegistry

    class _One(ModuleRegistry):
        def discover(self) -> dict[str, ModuleManifest]:
            return {manifest.name: manifest}

    registry_module.use(_One())

"""The dashboard: rows, filters, refusal states, and launching the same argv a human types.

The app is driven with Textual's Pilot under `run_test(headless=True)`, because this
suite runs where there is no terminal at all - a pipe, CI, or an agent shell.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest
from textual.widgets import Input, ListItem, ListView, Static

from levix import registry as registry_module
from levix.dashboard import module_list
from levix.dashboard import theme as theme_module
from levix.dashboard.app import LevixDashboard, _argv_for
from levix.errors import EXIT_USAGE
from levix.module import CommandInfo, ModuleManifest, Origin, PackageRef, Permission, UiSpec
from levix.registry import ModuleRegistry

READY = ModuleManifest(
    name="monitor",
    title="SystemPulse",
    summary="CPU, memory, disk, network and process monitoring.",
    cli_path="levix.modules.systempulse.cli:build_app",
    commands=(CommandInfo("cpu", "Processor load."), CommandInfo("live", "Refreshing view.")),
    requirements=(PackageRef("psutil", "psutil", minimum="7.2"),),
    extras=("monitor",),
    permissions=frozenset({Permission.FS_READ}),
    ui=UiSpec(mode="suspend", argv=("monitor", "live")),
    documentation="docs/modules/SYSTEMPULSE.md",
    origin=Origin.OFFICIAL,
    provider="levix",
)
NEEDS_INSTALL = ModuleManifest(
    name="music",
    title="Music",
    summary="Play audio without ffmpeg.",
    cli_path="levix.modules.music.cli:build_app",
    requirements=(PackageRef("not_installed_for_test", "not-installed-for-test"),),
    extras=("music",),
    origin=Origin.OFFICIAL,
    provider="levix",
)
BROKEN = ModuleManifest(
    name="ghost",
    title="Ghost",
    summary="failed to load: ModuleNotFoundError: there is no ghost",
    cli_path="",
)


class _StubRegistry(ModuleRegistry):
    """A registry whose contents are fixed, so the UI is tested against known rows."""

    def __init__(self) -> None:
        super().__init__()
        self._manifests = {m.name: m for m in (READY, NEEDS_INSTALL, BROKEN)}

    def discover(self) -> dict[str, ModuleManifest]:
        return dict(self._manifests)

    def get(self, name: str) -> ModuleManifest | None:
        return self._manifests.get(name)

    def manifests(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._manifests[name] for name in sorted(self._manifests))


def _drive(app, steps):
    async def main() -> None:
        async with app.run_test(headless=True, size=(100, 30)) as pilot:
            await steps(pilot)

    asyncio.run(main())


# ----------------------------------------------------------------------------------
# rows, without a UI at all
# ----------------------------------------------------------------------------------


def test_rows_carry_the_state_that_the_gate_actually_reports():
    rows = {row.name: row for row in module_list.build_rows(_StubRegistry())}
    assert rows["monitor"].state == "ready"
    assert rows["music"].state == "extra"
    assert rows["ghost"].state == "broken"
    # "needs an extra" and "failed to load" are both refusals to run, for different reasons.
    assert not rows["music"].runnable and not rows["ghost"].runnable
    assert rows["monitor"].runnable


def test_a_needs_install_row_names_the_extra_to_install():
    row = module_list.row_for(NEEDS_INSTALL)
    assert 'pip install "levix[music]"' in row.detail


def test_filtering_matches_name_title_and_summary():
    rows = module_list.build_rows(_StubRegistry())
    assert [row.name for row in module_list.filter_rows(rows, "MUSIC")] == ["music"]
    assert [row.name for row in module_list.filter_rows(rows, "ffmpeg")] == ["music"]
    assert module_list.filter_rows(rows, "   ") == rows
    assert module_list.filter_rows(rows, "nothing like this") == []


def test_launching_a_declared_screen_reuses_its_argv():
    assert _argv_for(READY, module_list.row_for(READY)) == ("monitor", "live")


def test_a_module_with_no_declared_screen_opens_its_help():
    row = module_list.row_for(NEEDS_INSTALL)
    assert _argv_for(NEEDS_INSTALL, row) == ("music", "-h")


def test_a_plugin_that_names_no_provider_does_not_invent_a_pip_line():
    """`pip install "[tube]"` is not a command; saying nothing is the honest answer."""
    anonymous = ModuleManifest(
        name="mystery",
        title="Mystery",
        summary="A third-party module that declared nothing installable.",
        cli_path="mystery.cli:build_app",
        requirements=(PackageRef("not_installed_for_test", "not-installed-for-test"),),
        extras=("cool",),
    )
    detail = module_list.row_for(anonymous).detail
    assert "pip install" not in detail
    assert "not-installed-for-test is not installed" in detail
    assert "needs an extra installed" in detail


# ----------------------------------------------------------------------------------
# the application itself
# ----------------------------------------------------------------------------------


@pytest.fixture
def stub_registry():
    """The app reads the *active* registry, so pin it to the three known rows.

    Without this the suite would list whatever is really installed and its assertions
    would depend on which extras happen to be in the environment.
    """
    stub = _StubRegistry()
    registry_module.use(stub)
    return stub


async def _focus_list(app: LevixDashboard, pilot) -> None:
    """Keys are for the list, not the filter: an Input swallows printable characters.

    The pause comes first because the rows mount on the event loop; setting an index on a
    list that has not mounted yet selects nothing, and the key press that follows is lost.
    """
    await pilot.pause()
    app.query_one("#modules", ListView).focus()


def test_dashboard_lists_every_module_and_reflects_the_filter(levix_home, stub_registry):
    app = LevixDashboard()

    async def steps(pilot):
        # `ListView.append` mounts its children on the event loop, so the count is only
        # stable once a pause has drained that. Without it this assert races the mount and
        # fails roughly once in a full-suite run.
        await pilot.pause()
        list_view = app.query_one("#modules", ListView)
        assert len(list_view.children) == 3
        labels = [str(child.children[0].render()) for child in list_view.children]
        assert any("needs install" in label for label in labels)
        assert any("broken" in label for label in labels)

        field = app.query_one("#filter", Input)
        field.value = "monitor"
        await pilot.pause()
        assert len(app.rows) == 1
        assert app.rows[0].name == "monitor"
        await pilot.pause()
        assert len(app.query_one("#modules", ListView).children) == 1

    _drive(app, steps)


def test_enter_on_a_ready_row_runs_the_same_command_line(levix_home, stub_registry, monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("levix.dashboard.app.spawn.run", lambda *argv: calls.append(argv) or 0)
    monkeypatch.setattr(LevixDashboard, "suspend", lambda self: nullcontext())

    app = LevixDashboard()

    async def steps(pilot):
        await _focus_list(app, pilot)
        # Not index 0: `ghost` sorts first, and it is the row that must refuse to run.
        app.query_one("#modules", ListView).index = [r.name for r in app.rows].index("monitor")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    _drive(app, steps)
    assert calls == [("monitor", "live")]


def test_enter_on_an_unavailable_row_says_why_instead_of_running_it(
    levix_home, stub_registry, monkeypatch
):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("levix.dashboard.app.spawn.run", lambda *argv: calls.append(argv) or 0)
    monkeypatch.setattr(LevixDashboard, "suspend", lambda self: nullcontext())

    app = LevixDashboard()

    async def steps(pilot):
        await _focus_list(app, pilot)
        index = [row.name for row in app.rows].index("ghost")
        app.query_one("#modules", ListView).index = index
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert calls == []
        assert "failed to load" in str(app.query_one("#detail", Static).render())

    _drive(app, steps)


def test_every_documented_theme_name_resolves():
    """`config.SCHEMA` and `dashboard.theme` must describe the same vocabulary.

    The config layer validates against its own choices list and the dashboard validates
    against its registered themes; nothing joined them, so `general.theme = "hacker"` was
    accepted by `levix config set` and then refused by the app.
    """
    from levix.config import SCHEMA

    known = {t.name for t in theme_module.THEMES}
    choices = SCHEMA["general"]["theme"].choices
    assert choices is not None
    mapped = {theme_module.ALIASES.get(name, name) for name in choices}
    missing = sorted(mapped - known)
    assert not missing, f"config offers themes the dashboard cannot apply: {missing}"


def test_theme_binding_cycles_only_through_registered_themes(levix_home, stub_registry):
    app = LevixDashboard()
    seen: list[str] = []

    async def steps(pilot):
        await _focus_list(app, pilot)
        for _ in range(4):
            await pilot.press("t")
            await pilot.pause()
            seen.append(str(app.theme))

    _drive(app, steps)
    assert set(seen) <= {t.name for t in theme_module.THEMES}
    assert len(set(seen)) > 1, "the binding must actually change something"


def test_history_panel_shows_the_commands_that_were_logged(context, stub_registry):
    context.database.apply_migrations(("core",))
    context.database.log_command(("monitor", "cpu"), "monitor", 0, 12.5)
    app = LevixDashboard(context)

    async def steps(pilot):
        del pilot
        text = str(app.query_one("#history", Static).render())
        assert "monitor cpu" in text

    _drive(app, steps)


def test_history_can_be_hidden_without_touching_the_log(context, stub_registry):
    context.database.apply_migrations(("core",))
    context.database.log_command(("monitor", "cpu"), "monitor", 0, 12.5)
    app = LevixDashboard(context)

    async def steps(pilot):
        await _focus_list(app, pilot)
        await pilot.press("h")
        await pilot.pause()
        assert str(app.query_one("#history", Static).render()) == ""
        await pilot.press("h")
        await pilot.pause()
        assert "monitor cpu" in str(app.query_one("#history", Static).render())

    _drive(app, steps)


def test_dashboard_refuses_a_redirected_terminal_with_the_usage_code(run_cli, capsys):
    """Textual drawing into a pipe would corrupt somebody's data, so it says no instead."""
    assert run_cli("dashboard") == EXIT_USAGE
    out = capsys.readouterr()
    assert "interactive terminal" in out.out + out.err
    assert "Traceback" not in out.out + out.err


def test_rows_render_as_list_items(levix_home, stub_registry):
    app = LevixDashboard()

    async def steps(pilot):
        await pilot.pause()
        children = list(app.query_one("#modules", ListView).children)
        assert len(children) == 3, "an empty list would make the assertion below vacuous"
        assert all(isinstance(child, ListItem) for child in children)

    _drive(app, steps)

"""`levix doctor` areas: the `--only` switch must actually narrow the report.

The filter is asserted on `--json` output rather than on the table, because the table
wraps at the terminal width and a substring test would pass on a wrapped neighbour.
"""

from __future__ import annotations

import json

from levix import doctor as doctor_core
from levix.errors import EXIT_CONFIG


def _areas(run_cli, capsys, *argv):
    code = run_cli("doctor", "--json", *argv)
    assert code == 0, f"doctor exited {code}"
    return [row["area"] for row in json.loads(capsys.readouterr().out)["findings"]]


def test_the_full_report_carries_all_three_areas(run_cli, capsys):
    areas = _areas(run_cli, capsys)
    assert any(a.startswith("module:") for a in areas)
    assert any(a.startswith("capability:") for a in areas)
    assert "storage" in areas, "the database finding belongs to the env area"


def test_only_modules_hides_capabilities_and_env(run_cli, capsys):
    areas = _areas(run_cli, capsys, "--only", "modules")
    assert areas, "a filtered report must not be empty"
    assert all(a.startswith("module:") for a in areas), areas


def test_only_capabilities_hides_modules(run_cli, capsys):
    areas = _areas(run_cli, capsys, "--only", "capabilities")
    assert areas
    assert all(a.startswith("capability:") for a in areas), areas


def test_only_env_is_the_environment_slice(run_cli, capsys):
    areas = _areas(run_cli, capsys, "--only", "env")
    assert "storage" in areas
    assert not any(a.startswith(("module:", "capability:")) for a in areas), areas


def test_an_unknown_area_is_a_configuration_error(run_cli, capsys):
    assert run_cli("doctor", "--only", "network") == EXIT_CONFIG
    assert "must be modules, capabilities or env" in capsys.readouterr().err


def test_a_filtered_report_states_its_own_verdict(run_cli, capsys):
    """`verdict` is computed from the rows that are printed, so a filtered report says
    something true about those rows instead of inheriting a failure from an area it hid."""
    code = run_cli("doctor", "--json", "--only", "modules")
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    rows = [
        doctor_core.Finding(
            row["area"], doctor_core.Status(row["status"]), row["detail"], row["hint"]
        )
        for row in payload["findings"]
    ]
    assert payload["verdict"] == doctor_core.worst_status(rows).value
    assert all(row.area.startswith("module:") for row in rows)

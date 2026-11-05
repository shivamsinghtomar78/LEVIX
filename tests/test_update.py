"""`levix update` - the one network call the tool makes by default, tested without a network.

Nothing here reaches PyPI. `urllib.request.urlopen` is replaced for the duration of each
case, so the code under test stays the real one: the request that gets built, the JSON that
gets parsed, the version comparison, and which of the answers the user is given. The two
properties worth pinning are that a newer release is reported without the installation being
touched, and that a failed check is reported as a failed check - never as good news.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from levix.commands import update_cmd
from levix.errors import EXIT_PROVIDER, EXIT_USAGE

NEWER = "999.0.0"
OLDER = "0.0.1"


class _Response:
    """The piece of `urlopen`'s contract that `_fetch_latest` actually uses."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def serve(monkeypatch, result):
    """Answer every request with `result`: bytes as the body, an exception to raise."""
    seen: list = []

    def fake_urlopen(request, timeout=None):
        seen.append((request, timeout))
        if isinstance(result, Exception):
            raise result
        return _Response(result)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def body(version):
    info = {} if version is None else {"version": version}
    return json.dumps({"info": info}).encode("utf-8")


def test_a_newer_release_is_named_and_the_upgrade_left_to_the_user(run_cli, capsys, monkeypatch):
    serve(monkeypatch, body(NEWER))
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert f"LEVIX {NEWER} is available" in out
    assert "does not modify its own installation" in out
    assert "pip install --upgrade levix" in out, "the answer has to be a command the user can run"


def test_a_release_that_is_not_newer_says_so(run_cli, capsys, monkeypatch):
    serve(monkeypatch, body(OLDER))
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "is the latest release" in out
    assert f"PyPI: {OLDER}" in out


def test_the_json_answer_carries_both_versions_and_the_verdict(run_cli, capsys, monkeypatch):
    serve(monkeypatch, body(NEWER))
    assert run_cli("update", "--json") == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available"] == NEWER
    assert payload["up_to_date"] is False
    assert payload["installed"] == update_cmd.__version__
    assert "levix" in payload["command"]


def test_the_installed_version_is_what_the_comparison_uses(run_cli, capsys, monkeypatch):
    """Equal is up to date: a released version must not be told to upgrade to itself."""
    monkeypatch.setattr(update_cmd, "__version__", NEWER)
    serve(monkeypatch, body(NEWER))
    assert run_cli("update", "--json") == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["installed"] == NEWER
    assert payload["up_to_date"] is True, "the comparison is >=, not >"


def test_a_pypi_http_status_is_a_provider_failure_not_a_quiet_zero(run_cli, capsys, monkeypatch):
    serve(
        monkeypatch,
        urllib.error.HTTPError("https://pypi.org", 503, "Service Unavailable", {}, None),
    )
    assert run_cli("update") == EXIT_PROVIDER
    captured = capsys.readouterr()
    assert "PyPI returned 503" in captured.out
    assert "update check failed: PyPI returned 503" in captured.err
    assert "pip index versions levix" in captured.err, "the hint says what to do instead"
    assert "latest release" not in captured.out


def test_no_response_is_reported_as_a_limitation_and_not_as_being_up_to_date(
    run_cli, capsys, monkeypatch
):
    serve(monkeypatch, urllib.error.URLError("no route to host"))
    assert run_cli("update") == EXIT_PROVIDER
    captured = capsys.readouterr()
    assert "no response from PyPI (URLError)" in captured.out
    assert "not an indication that you are up to date" in captured.out
    assert "latest release" not in captured.out, "a failed check must not read as good news"


def test_the_json_answer_still_reports_the_failure(run_cli, capsys, monkeypatch):
    serve(monkeypatch, urllib.error.URLError("no route to host"))
    assert run_cli("update", "--json") == EXIT_PROVIDER
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["available"] is None
    assert "no response from PyPI" in payload["error"]
    assert "up_to_date" not in payload, "there is no verdict to hand out without an answer"


def test_a_response_without_a_version_is_an_error_rather_than_a_guess(run_cli, capsys, monkeypatch):
    serve(monkeypatch, body(None))
    assert run_cli("update") == EXIT_PROVIDER
    assert "PyPI response had no version" in capsys.readouterr().out


def test_the_request_is_the_documented_endpoint_with_the_levix_user_agent(run_cli, monkeypatch):
    seen = serve(monkeypatch, body(NEWER))
    assert run_cli("update", "--timeout", "7") == 0
    assert len(seen) == 1, "one check is one request"
    request, timeout = seen[0]
    assert request.full_url == update_cmd.INDEX_URL
    assert request.full_url == "https://pypi.org/pypi/levix/json"
    assert request.get_header("User-agent") == f"levix/{update_cmd.__version__}"
    assert request.get_header("Accept") == "application/json"
    assert timeout == 7.0, "the flag has to reach the socket, not just the help text"


def test_an_absurd_timeout_is_refused_before_any_request(run_cli, monkeypatch):
    seen = serve(monkeypatch, body(NEWER))
    assert run_cli("update", "--timeout", "0.5") == EXIT_USAGE
    assert run_cli("update", "--timeout", "600") == EXIT_USAGE
    assert not seen, "validation happens on the way in, not over the wire"

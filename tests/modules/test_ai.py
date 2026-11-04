"""The AI module: providers, prompts, stream parsing, the key chain and the gate.

Two kinds of test live here. The pure ones assert on what `core` builds and parses, so a
wire-format regression is a failing test rather than a broken install. The CLI ones drive
`levix_main` exactly as a user does, with `httpx` pointed at a `MockTransport`: no socket
is opened and api.openai.com is never contacted. Nothing in this file exercises a real
network path, which is the point - a provider outage must not be able to fail the suite.

Stdin note: pytest replaces `sys.stdin` with an object that refuses to be read, so
`_piped_stdin()` returns None and the approval gate always takes the "no terminal" path.
Tests that need a specific stdin set one explicitly.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import typer

from levix import secrets as secrets_module
from levix.errors import (
    EXIT_CANCELLED,
    EXIT_CONFIG,
    EXIT_MISSING_DEPENDENCY,
    EXIT_PROVIDER,
    EXIT_TOOL_FAILED,
    EXIT_USAGE,
    ConfigError,
    ExternalToolError,
    LevixError,
    ProviderError,
)
from levix.module import Permission
from levix.modules.ai import MANIFEST, core
from levix.modules.ai.core import AIConfig, ApiKey, Message

OPENAI_REPLY = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "the answer"}}],
    "model": "fake-1",
    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
}

OLLAMA_CHAT_REPLY = {
    "model": "llama3:8b",
    "message": {"role": "assistant", "content": "local answer"},
    "done": True,
    "prompt_eval_count": 21,
    "eval_count": 4,
}

OLLAMA_GENERATE_REPLY = {
    "model": "llama3:8b",
    "response": "touch /tmp/x\ncreates the file",
    "done": True,
    "prompt_eval_count": 12,
    "eval_count": 5,
}


# A short, fixed name: the whole point of the command tests is to assert this file is
# STILL ABSENT afterwards, so nothing may create it. Short enough to stay on one line in
# the proposal panel, which keeps the assertions about the printed text honest.
MARKER = "/tmp/levix-ai-must-not-exist"  # noqa: S108 - never created, only asserted absent


def config(provider: str = core.PROVIDER_OPENAI, **overrides: object) -> AIConfig:
    base = {
        "provider": provider,
        "model": "fake-1",
        "base_url": "https://provider.test/v1",
        "ollama_url": "http://127.0.0.1:11434",
        "temperature": 0.3,
        "max_tokens": 64,
        "require_approval": True,
    }
    base.update(overrides)
    return AIConfig(**base)  # type: ignore[arg-type]


def _install_transport(monkeypatch, handler) -> list[httpx.Request]:
    """Make `core.build_client` return a client whose transport answers in-process."""
    seen: list[httpx.Request] = []

    def probe(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(probe))
    monkeypatch.setattr(core, "build_client", lambda **kwargs: client)
    return seen


def _json_response(payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# ---------------------------------------------------------------------------------
# the manifest contract
# ---------------------------------------------------------------------------------


def test_manifest_declares_the_real_contract():
    assert MANIFEST.name == "ai"
    assert MANIFEST.cli_path == "levix.modules.ai.cli:build_app"
    assert [ref.import_name for ref in MANIFEST.requirements] == ["httpx"]
    assert MANIFEST.extras == ("ai",)
    assert MANIFEST.documentation == "docs/modules/AI.md"
    assert MANIFEST.origin is not None
    names = set(MANIFEST.command_names())
    assert {"ask", "explain", "command", "models", "check", "key"} == names
    assert all(info.help for info in MANIFEST.commands)
    assert MANIFEST.permissions <= frozenset(Permission)
    assert {
        Permission.NETWORK,
        Permission.SECRET_READ,
        Permission.SECRET_WRITE,
        Permission.SUBPROCESS,
    } <= MANIFEST.permissions


# ---------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------


DEFAULT_CONFIG = {
    "ai.provider": "openai-compatible",
    "ai.model": "gpt-4o-mini",
    "ai.base_url": "https://api.openai.com/v1",
    "ai.ollama_url": "http://127.0.0.1:11434",
    "ai.temperature": 0.2,
    "ai.max_tokens": 1024,
    "ai.require_approval": True,
}


def _values(overrides: dict[str, object] | None = None):
    """A stand-in for `LevixContext.value` over a chosen set of configuration keys."""
    merged = {**DEFAULT_CONFIG, **(overrides or {})}

    def value_of(dotted: str):
        if dotted not in merged:
            raise ConfigError(f"unknown key {dotted}")
        return merged[dotted]

    return value_of


def test_flags_beat_configuration():
    resolved = core.resolve_config(_values(), provider="ollama", model="llama3", temperature=0.9)
    assert resolved.provider == "ollama"
    assert resolved.model == "llama3"
    assert resolved.temperature == 0.9
    assert resolved.max_tokens == 1024
    assert resolved.root == "http://127.0.0.1:11434"


def test_configuration_is_used_when_no_flag():
    resolved = core.resolve_config(_values({"ai.model": "from-config"}))
    assert resolved.model == "from-config"
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.timeout == core.DEFAULT_TIMEOUT


def test_unknown_provider_is_a_config_error():
    with pytest.raises(ConfigError) as exc:
        core.resolve_config(_values({"ai.provider": "anthropic"}))
    assert exc.value.exit_code == EXIT_CONFIG


def test_blank_url_is_a_config_error():
    with pytest.raises(ConfigError):
        core.resolve_config(_values({"ai.base_url": ""}))


def test_zero_timeout_is_refused():
    with pytest.raises(ConfigError):
        core.resolve_config(_values(), timeout=0)


# ---------------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------------


def test_ask_prompt_has_a_system_message_and_the_request():
    messages = core.build_ask_messages("what does this do?")
    assert [m.role for m in messages] == ["system", "user"]
    assert "what does this do?" in messages[1].content


def test_ask_prompt_injects_piped_context():
    messages = core.build_ask_messages("summarise", context="alpha\nbeta")
    assert "alpha\nbeta" in messages[1].content
    assert "Request: summarise" in messages[1].content


def test_system_flag_replaces_the_default_system_message():
    messages = core.build_ask_messages("hi", system="be terse")
    assert messages[0].content == "be terse"


def test_command_prompt_names_the_platform_and_the_single_line_rule():
    messages = core.build_command_messages("free 5 GB of disk")
    system = messages[0].content
    assert "ONE shell command" in system
    assert "no pipe" in system
    assert ("Windows" in system) if os.name == "nt" else ("POSIX" in system)
    assert messages[1].content == "free 5 GB of disk"


def test_raw_prompt_flattens_roles_for_ollama_generate():
    rendered = core.render_raw_prompt([Message("system", "sys"), Message("user", "ask")])
    assert rendered.startswith("SYSTEM: sys")
    assert rendered.endswith("ASSISTANT:")


# ---------------------------------------------------------------------------------
# explain: the size cap
# ---------------------------------------------------------------------------------


def test_read_snippet_caps_and_reports_truncation(tmp_path: Path):
    path = tmp_path / "big.txt"
    path.write_bytes(b"a" * 5000)
    snippet = core.read_snippet(path, max_bytes=100)
    assert snippet.read_bytes == 100
    assert snippet.size_bytes == 5000
    assert snippet.truncated
    assert "showing the first 100 of 5000 bytes" in snippet.notice()
    assert "--max-bytes" in snippet.notice()
    assert "[truncated" in snippet.for_prompt()


def test_read_snippet_whole_file_is_not_truncated(tmp_path: Path):
    path = tmp_path / "small.txt"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    snippet = core.read_snippet(path, max_bytes=4096)
    assert not snippet.truncated
    assert snippet.notice() == ""


def test_read_snippet_survives_undecodable_bytes(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"caf\xe9 latin-1 bytes\n")
    snippet = core.read_snippet(path, max_bytes=4096)
    assert "caf" in snippet.text


def test_read_snippet_missing_file_raises(tmp_path: Path):
    with pytest.raises(LevixError):
        core.read_snippet(tmp_path / "nope.txt", max_bytes=10)


def test_explain_prompt_carries_every_file(tmp_path: Path):
    one = core.read_snippet(_write(tmp_path / "a.py", "print(1)"), max_bytes=100)
    two = core.read_snippet(_write(tmp_path / "b.py", "print(2)"), max_bytes=100)
    prompt = core.build_explain_messages([one, two], focus="the bug")[1].content
    assert "a.py" in prompt and "b.py" in prompt
    assert "the bug" in prompt


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------
# proposal extraction
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("git status", "git status"),
        ("```sh\ngit status\n```", "git status"),
        ("```sh\ngit status\n```done", "git status"),
        ("$ git status", "git status"),
        ("ASSISTANT: git status", "git status"),
        ("  git status  ", "git status"),
    ],
)
def test_extract_proposal_accepts_a_plain_command(reply: str, expected: str):
    proposal = core.extract_proposal(reply)
    assert proposal.rejected is None
    assert proposal.raw == expected
    assert proposal.argv[0] == "git"


@pytest.mark.parametrize(
    "reply",
    [
        "ls | wc -l",
        "git add . && git push",
        "echo hi > out.txt",
        "rm -rf / ; echo done",
        "cat $(whoami)",
        "none: that needs two commands",
    ],
)
def test_extract_proposal_refuses_what_a_shell_would_interpret(reply: str):
    proposal = core.extract_proposal(reply)
    assert proposal.rejected
    assert proposal.argv == ()


def test_extract_proposal_keeps_the_caveat_separate():
    proposal = core.extract_proposal("git switch -c work\nCreates a branch; undo with -d.")
    assert proposal.explanation == "Creates a branch; undo with -d."


def test_extract_proposal_of_nothing_is_rejected():
    assert core.extract_proposal("").rejected
    assert core.extract_proposal("   \n  ").rejected


def test_split_argv_keeps_a_quoted_windows_path_together():
    if os.name != "nt":
        pytest.skip("cmd-style quoting is a Windows concern")
    argv = core.split_argv(r'"C:\Program Files\x.exe" --flag "two words"')
    assert argv[0] == r"C:\Program Files\x.exe"
    assert argv[2] == "two words"


# ---------------------------------------------------------------------------------
# stream parsing
# ---------------------------------------------------------------------------------


def test_iter_sse_text_follows_deltas_and_stops_at_done():
    frames = [
        'data: {"choices":[{"delta":{"content":"he"}}]}',
        "",
        ": keep-alive comment",
        'data: {"choices":[{"delta":{"content":"llo"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"IGNORED"}}]}',
    ]
    assert "".join(core.iter_sse_text(frames)) == "hello"


def test_iter_sse_text_reports_a_malformed_chunk():
    with pytest.raises(ProviderError) as exc:
        list(core.iter_sse_text(["data: {not json"]))
    assert exc.value.exit_code == EXIT_PROVIDER
    assert "SSE" in exc.value.message


def test_iter_ndjson_text_collects_ollama_messages():
    frames = [
        '{"message":{"role":"assistant","content":"one "},"done":false}',
        '{"message":{"role":"assistant","content":"two"},"done":true}',
    ]
    assert "".join(core.iter_ndjson_text(frames)) == "one two"


def test_iter_ndjson_text_handles_generate_frames():
    frames = ['{"response":"part ","done":false}', '{"response":"rest","done":true}']
    assert "".join(core.iter_ndjson_text(frames)) == "part rest"


def test_iter_ndjson_text_reports_a_malformed_frame():
    with pytest.raises(ProviderError):
        list(core.iter_ndjson_text(["{oops"]))


# ---------------------------------------------------------------------------------
# request shapes
# ---------------------------------------------------------------------------------


def test_openai_chat_request_shape():
    spec = core.OpenAIProvider(config(), ApiKey(None, "none")).completion_spec(
        [Message("system", "s"), Message("user", "u")], stream=False
    )
    assert spec.method == "POST"
    assert spec.url == "https://provider.test/v1/chat/completions"
    assert spec.payload["model"] == "fake-1"
    assert spec.payload["max_tokens"] == 64
    assert spec.payload["stream"] is False
    assert spec.payload["messages"][0] == {"role": "system", "content": "s"}
    assert "Authorization" not in spec.headers


def test_openai_chat_request_sends_the_bearer_key_and_sse_accept():
    spec = core.OpenAIProvider(config(), ApiKey("sekret-value", "env")).completion_spec(
        [Message("user", "u")], stream=True
    )
    assert spec.headers["Authorization"] == "Bearer sekret-value"
    assert spec.headers["Accept"] == "text/event-stream"
    assert spec.payload["stream"] is True


def test_ollama_non_streaming_chat_request_shape():
    spec = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).completion_spec(
        [Message("system", "s"), Message("user", "u")], stream=False
    )
    assert spec.url == "http://127.0.0.1:11434/api/chat"
    assert spec.payload["stream"] is False
    assert spec.payload["options"]["num_predict"] == 64
    assert "Authorization" not in spec.headers


def test_ollama_raw_request_uses_generate_with_a_flat_prompt():
    spec = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).completion_spec(
        [Message("system", "s"), Message("user", "u")], stream=False, raw=True
    )
    assert spec.url == "http://127.0.0.1:11434/api/generate"
    assert spec.payload["raw"] is True
    assert spec.payload["prompt"].startswith("SYSTEM: s")
    assert "messages" not in spec.payload


def test_ollama_streams_through_api_chat():
    spec = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).completion_spec(
        [Message("user", "u")], stream=True, raw=True
    )
    assert spec.url == "http://127.0.0.1:11434/api/chat"
    assert spec.payload["stream"] is True


def test_models_endpoints_per_provider():
    assert core.OpenAIProvider(config(), ApiKey(None, "none")).models_spec().url == (
        "https://provider.test/v1/models"
    )
    assert core.OllamaProvider(config("ollama"), ApiKey(None, "none")).models_spec().url == (
        "http://127.0.0.1:11434/api/tags"
    )


def test_parse_completion_reads_openai_usage():
    result = core.OpenAIProvider(config(), ApiKey(None, "none")).parse_completion(OPENAI_REPLY)
    assert result.text == "the answer"
    assert result.usage is not None
    assert result.usage.total_tokens == 10


def test_parse_completion_reads_ollama_chat_counts():
    result = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).parse_completion(
        OLLAMA_CHAT_REPLY
    )
    assert result.text == "local answer"
    assert result.usage.describe() == "prompt 21  completion 4  total 25"


def test_parse_completion_reads_ollama_generate_response():
    result = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).parse_completion(
        OLLAMA_GENERATE_REPLY
    )
    assert result.text.startswith("touch /tmp/x")
    assert result.usage.completion_tokens == 5


def test_parse_completion_of_an_unusable_body_is_a_provider_error():
    with pytest.raises(ProviderError):
        core.OpenAIProvider(config(), ApiKey(None, "none")).parse_completion({"unexpected": 1})
    with pytest.raises(ProviderError):
        core.OllamaProvider(config("ollama"), ApiKey(None, "none")).parse_completion({})


def test_parse_models_reads_both_shapes():
    openai = core.OpenAIProvider(config(), ApiKey(None, "none")).parse_models(
        {"data": [{"id": "a", "owned_by": "org"}, {"nope": 1}]}
    )
    assert [m.name for m in openai] == ["a"]
    ollama = core.OllamaProvider(config("ollama"), ApiKey(None, "none")).parse_models(
        {"models": [{"name": "llama3:8b", "size": 4_000_000_000, "details": {"family": "llama"}}]}
    )
    assert ollama[0].name == "llama3:8b"
    assert ollama[0].detail.startswith("llama")


def test_openai_body_without_choices_names_the_provider_not_the_key():
    provider = core.OpenAIProvider(config(), ApiKey("sekret-value", "env"))
    with pytest.raises(ProviderError) as exc:
        provider.parse_completion({"choices": []})
    assert "openai-compatible" in exc.value.message
    assert "sekret-value" not in str(exc.value)


# ---------------------------------------------------------------------------------
# error mapping over the transport
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "rejected our credentials"),
        (403, "rejected our credentials"),
        (404, "HTTP 404"),
        (429, "rate limited"),
        (500, "failed the request"),
        (400, "answered HTTP 400"),
    ],
)
def test_non_2xx_maps_to_provider_error(monkeypatch, status, needle):
    _install_transport(monkeypatch, lambda request: httpx.Response(status, text="server said no"))
    provider = core.OpenAIProvider(config(), ApiKey("sekret-value", "env"))
    with pytest.raises(ProviderError) as exc:
        core.post_completion(core.build_client(timeout=5), provider, [Message("user", "hi")])
    assert exc.value.exit_code == EXIT_PROVIDER
    assert needle in exc.value.message
    assert "provider.test" in exc.value.message
    assert "sekret-value" not in exc.value.message


def test_connection_failure_names_the_provider_and_url(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("target refused")

    _install_transport(monkeypatch, refuse)
    provider = core.OpenAIProvider(config(), ApiKey("sekret-value", "env"))
    with pytest.raises(ProviderError) as exc:
        core.post_completion(core.build_client(timeout=5), provider, [Message("user", "hi")])
    assert "cannot reach openai-compatible at https://provider.test/v1/chat/completions" in (
        exc.value.message
    )
    assert "sekret-value" not in exc.value.message


def test_timeout_maps_to_provider_error(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("too slow", request=request)

    _install_transport(monkeypatch, slow)
    provider = core.OpenAIProvider(config(timeout=7.5), ApiKey(None, "none"))
    with pytest.raises(ProviderError) as exc:
        core.post_completion(core.build_client(timeout=7.5), provider, [Message("user", "hi")])
    assert "within 7.5s" in exc.value.message


def test_non_json_success_body_maps_to_provider_error(monkeypatch):
    _install_transport(
        monkeypatch, lambda request: httpx.Response(200, text="<html>not json</html>")
    )
    provider = core.OpenAIProvider(config(), ApiKey(None, "none"))
    with pytest.raises(ProviderError) as exc:
        core.post_completion(core.build_client(timeout=5), provider, [Message("user", "hi")])
    assert "non-JSON" in exc.value.message


def test_streamed_failure_is_a_provider_error(monkeypatch):
    _install_transport(monkeypatch, lambda request: httpx.Response(503, text="busy"))
    provider = core.OpenAIProvider(config(), ApiKey(None, "none"))
    with pytest.raises(ProviderError):
        core.stream_completion(core.build_client(timeout=5), provider, [Message("user", "hi")])


# ---------------------------------------------------------------------------------
# the secret chain
# ---------------------------------------------------------------------------------


def test_key_from_the_environment_wins(context, monkeypatch):
    monkeypatch.setenv("LEVIX_AI_API_KEY", "from-env")
    value, source = context.secret(core.SECRET_NAME)
    assert (value, source) == ("from-env", "env")


def test_key_from_the_keyring_when_env_is_silent(context, monkeypatch):
    class FakeKeyring:
        def get_password(self, service, name):
            assert (service, name) == ("levix", core.SECRET_NAME)
            return "from-keyring"

    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: FakeKeyring())
    value, source = context.secret(core.SECRET_NAME)
    assert (value, source) == ("from-keyring", "keyring")


def test_key_from_the_owner_only_file_when_no_keyring(context, monkeypatch):
    class NoKeyring:
        def get_password(self, service, name):
            return None

    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: NoKeyring())
    secrets_module.set_secret(core.SECRET_NAME, "from-file", paths=context.paths)
    value, source = context.secret(core.SECRET_NAME)
    assert (value, source) == ("from-file", "file")
    assert context.paths.secrets_file.exists()


def test_no_key_anywhere_reports_none(context, monkeypatch):
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: None)
    assert context.secret(core.SECRET_NAME) == (None, "none")


def test_resolve_key_refuses_a_remote_host_without_a_key():
    secret_of = lambda name: (None, "none")  # noqa: E731 - a two-line stand-in for ctx.secret
    with pytest.raises(ProviderError) as exc:
        core.resolve_key(config(), secret_of)
    error = exc.value
    assert "needs an API key" in error.message
    assert "\n" not in error.message, "the message is one line; the remedy is the hint"
    assert "LEVIX_AI_API_KEY" in error.hint
    assert "levix ai key set" in error.hint
    assert error.exit_code == EXIT_PROVIDER


def test_resolve_key_allows_a_loopback_server_without_a_key():
    local = config(base_url="http://127.0.0.1:8080/v1")
    key = core.resolve_key(local, lambda name: (None, "none"))
    assert key.value is None and key.source == "none"


def test_resolve_key_never_asks_ollama_for_a_key():
    key = core.resolve_key(config("ollama"), lambda name: (None, "none"))
    assert not key.present


# ---------------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------------


def test_run_proposal_uses_an_argument_list_and_no_shell(monkeypatch):
    calls = {}

    class FakeCompleted:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls.update(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    monkeypatch.setattr(core.shutil, "which", lambda name: f"/usr/bin/{name}")
    core.run_proposal(["git", "status", "-s"], timeout=5)
    assert calls["argv"] == ["/usr/bin/git", "status", "-s"]
    assert calls["shell"] is False
    assert calls["timeout"] == 5


def test_run_proposal_actually_runs_a_real_process(capfd):
    """The child's own stdout, at the file-descriptor level: captured, never hidden."""
    rc = core.run_proposal([sys.executable, "-c", "print('ran for real')"], timeout=30)
    assert rc == 0
    assert "ran for real" in capfd.readouterr().out


def test_missing_executable_is_an_external_tool_error():
    with pytest.raises(ExternalToolError) as exc:
        core.run_proposal(["definitely-not-a-real-binary-42"], timeout=5)
    assert exc.value.exit_code == EXIT_TOOL_FAILED


def test_a_failing_child_is_an_external_tool_error():
    with pytest.raises(ExternalToolError) as exc:
        core.run_proposal([sys.executable, "-c", "raise SystemExit(3)"], timeout=30)
    assert "exited with code 3" in exc.value.message


# ---------------------------------------------------------------------------------
# command surface, through the real entry point
# ---------------------------------------------------------------------------------


def test_help_lists_every_command(run_cli, capsys):
    assert run_cli("ai", "-h") == 0
    out = capsys.readouterr().out
    for name in MANIFEST.command_names():
        assert name in out


def test_check_runs_offline_and_reports_no_key(run_cli, capsys, monkeypatch):
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    code = run_cli("ai", "check")
    out = capsys.readouterr().out
    assert code == 0
    assert "openai-compatible" in out
    assert "no request was sent" in out


def test_check_degrades_when_no_key_is_configured(run_cli, capsys, monkeypatch):
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    assert run_cli("ai", "check") == 0
    assert "warning" in capsys.readouterr().out


def test_ask_prints_the_reply_and_usage(run_cli, capsys, monkeypatch):
    seen = _install_transport(monkeypatch, lambda request: _json_response(OPENAI_REPLY))
    code = run_cli("ai", "ask", "hi", "--base-url", "http://127.0.0.1:9/v1", "--show-usage")
    out = capsys.readouterr().out
    assert code == 0
    assert "the answer" in out
    assert "prompt 7" in out and "total 10" in out
    assert seen[0].url.path == "/v1/chat/completions"


def test_ask_streams_sse_frames(run_cli, capsys, monkeypatch):
    body = (
        b'data: {"choices":[{"delta":{"content":"str"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"eam"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        ),
    )
    code = run_cli("ai", "ask", "hi", "--base-url", "http://127.0.0.1:9/v1", "--stream")
    assert code == 0
    assert "stream" in capsys.readouterr().out


def test_ask_without_a_prompt_and_without_stdin_is_a_usage_error(run_cli, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert run_cli("ai", "ask") == EXIT_USAGE


def test_ask_uses_piped_stdin_as_the_prompt(run_cli, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("prompt from the pipe"))
    seen = _install_transport(monkeypatch, lambda request: _json_response(OPENAI_REPLY))
    assert run_cli("ai", "ask", "--base-url", "http://127.0.0.1:9/v1") == 0
    sent = json.loads(seen[0].content.decode())
    assert "prompt from the pipe" in sent["messages"][1]["content"]


def test_explain_sends_only_the_capped_prefix(run_cli, capsys, monkeypatch, tmp_path):
    path = tmp_path / "code.py"
    path.write_text("x" * 400, encoding="utf-8")
    seen = _install_transport(monkeypatch, lambda request: _json_response(OPENAI_REPLY))
    code = run_cli(
        "ai", "explain", str(path), "--max-bytes", "120", "--base-url", "http://127.0.0.1:9/v1"
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "showing the first 120 of 400 bytes" in out
    sent = json.loads(seen[0].content.decode())
    assert "x" * 120 in sent["messages"][1]["content"]
    assert "x" * 121 not in sent["messages"][1]["content"]


def test_models_lists_what_the_provider_reports(run_cli, capsys, monkeypatch):
    _install_transport(
        monkeypatch, lambda request: _json_response({"data": [{"id": "listed-model"}]})
    )
    code = run_cli("ai", "models", "--base-url", "http://127.0.0.1:9/v1")
    assert code == 0
    assert "listed-model" in capsys.readouterr().out


def test_a_model_name_the_server_named_with_brackets_is_printed_whole(run_cli, capsys, monkeypatch):
    """The models table is the one place this module prints text a remote server chose.

    Unescaped, Rich read `[4]` as a style tag and printed `gpt-mini` for a model named
    `gpt-[4]mini`, so the command used to discover model names silently rewrote one; a
    name containing `[/x]` did worse - it raised MarkupError and `levix ai models` died
    with exit 1 on a server that was answering perfectly.
    """
    _install_transport(
        monkeypatch,
        lambda request: _json_response(
            {
                "data": [
                    {"id": "gpt-[4]mini", "owned_by": "org[/weird]"},
                    {"id": "plain-model"},
                ]
            }
        ),
    )
    code = run_cli("ai", "models", "--base-url", "http://127.0.0.1:9/v1")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "gpt-[4]mini" in out, out
    assert "org[/weird]" in out, out
    assert "plain-model" in out, out


def test_models_degrades_honestly_on_404(run_cli, capsys, monkeypatch):
    _install_transport(monkeypatch, lambda request: httpx.Response(404, text="not found"))
    code = run_cli("ai", "models", "--base-url", "http://127.0.0.1:9/v1")
    out = " ".join(capsys.readouterr().out.split())
    assert code == 0
    assert "HTTP 404" in out
    assert "nothing is guessed" in out
    assert "configured model: gpt-4o-mini" in out


def test_models_404_for_ollama_also_degrades(run_cli, capsys, monkeypatch):
    _install_transport(monkeypatch, lambda request: httpx.Response(404, text="no tags"))
    code = run_cli("ai", "models", "--provider", "ollama")
    assert code == 0
    assert "api/tags" in capsys.readouterr().out


def test_provider_failure_exits_8(run_cli, capsys, monkeypatch):
    _install_transport(monkeypatch, lambda request: httpx.Response(401, text="bad key"))
    monkeypatch.setenv("LEVIX_AI_API_KEY", "sekret-value")
    code = run_cli("ai", "ask", "hi", "--base-url", "http://127.0.0.1:9/v1")
    captured = capsys.readouterr()
    assert code == EXIT_PROVIDER
    assert "sekret-value" not in captured.out + captured.err


def test_command_prints_the_proposal_and_runs_nothing(run_cli, capsys, monkeypatch):
    marker = MARKER
    reply = {"choices": [{"message": {"content": f"touch {marker}\njust a test"}}]}
    _install_transport(monkeypatch, lambda request: _json_response(reply))
    code = run_cli("ai", "command", "make a marker", "--base-url", "http://127.0.0.1:9/v1")
    out = capsys.readouterr().out
    assert code == 0
    assert "PROPOSED COMMAND" in out
    assert f"touch {marker}" in out
    assert "just a test" in out
    assert "nothing ran" in out
    assert not Path(marker).exists()


def test_command_with_run_refuses_without_a_terminal(run_cli, capsys, monkeypatch):
    marker = MARKER
    reply = {"choices": [{"message": {"content": f"touch {marker}\njust a test"}}]}
    _install_transport(monkeypatch, lambda request: _json_response(reply))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code = run_cli("ai", "command", "make a marker", "--base-url", "http://127.0.0.1:9/v1", "--run")
    captured = capsys.readouterr()
    assert code == EXIT_CANCELLED
    assert "without a terminal" in captured.err or "no input available" in captured.err
    assert not Path(marker).exists()


def test_command_yes_cannot_authorize_a_run(run_cli, capsys, monkeypatch):
    marker = MARKER
    reply = {"choices": [{"message": {"content": f"touch {marker}\njust a test"}}]}
    _install_transport(monkeypatch, lambda request: _json_response(reply))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code = run_cli(
        "ai", "command", "make a marker", "--base-url", "http://127.0.0.1:9/v1", "--run", "--yes"
    )
    captured = capsys.readouterr()
    assert code == EXIT_CANCELLED
    assert "--yes cannot authorize a destructive action" in captured.err
    assert not Path(marker).exists()


def test_command_refuses_a_pipeline_proposal_before_any_approval(run_cli, capsys, monkeypatch):
    reply = {"choices": [{"message": {"content": "ls | wc -l\npipes the list"}}]}
    _install_transport(monkeypatch, lambda request: _json_response(reply))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code = run_cli("ai", "command", "count files", "--base-url", "http://127.0.0.1:9/v1", "--run")
    out = capsys.readouterr().out
    assert code == 0
    assert "no command offered" in out
    assert "nothing has run" in out


def test_command_sends_the_two_line_instruction_prompt(run_cli, capsys, monkeypatch):
    seen = _install_transport(monkeypatch, lambda request: _json_response(OPENAI_REPLY))
    run_cli("ai", "command", "list files", "--base-url", "http://127.0.0.1:9/v1")
    sent = json.loads(seen[0].content.decode())
    assert "ONE shell command" in sent["messages"][0]["content"]
    assert sent["messages"][1]["content"] == "list files"


def test_ollama_provider_answers_through_the_same_surface(run_cli, capsys, monkeypatch):
    seen = _install_transport(
        monkeypatch, lambda request: _json_response({"message": {"content": "local answer"}})
    )
    code = run_cli("ai", "ask", "hi", "--provider", "ollama", "--model", "llama3")
    out = capsys.readouterr().out
    assert code == 0
    assert "local answer" in out
    assert seen[0].url.path == "/api/chat"


def test_ollama_command_uses_generate(run_cli, capsys, monkeypatch):
    seen = _install_transport(
        monkeypatch, lambda request: _json_response({"response": "git status"})
    )
    code = run_cli("ai", "command", "show status", "--provider", "ollama", "--model", "llama3")
    assert code == 0
    assert seen[0].url.path == "/api/generate"
    assert json.loads(seen[0].content.decode())["raw"] is True
    assert "git status" in capsys.readouterr().out


# ---------------------------------------------------------------------------------
# `levix ai key` - the write side of the secret store
# ---------------------------------------------------------------------------------


class RecordingKeyring:
    """The part of the keyring API `levix ai key` uses, with the calls kept."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def get_password(self, service, name):
        for saved_service, saved_name, value in self.saved:
            if (saved_service, saved_name) == (service, name):
                return value
        return None

    def set_password(self, service, name, value):
        self.saved.append((service, name, value))

    def delete_password(self, service, name):
        self.deleted.append((service, name))
        self.saved = [row for row in self.saved if (row[0], row[1]) != (service, name)]
        if not self.saved:
            raise LookupError("not found")


def test_key_set_writes_the_keyring_and_never_prints_the_value(run_cli, capsys, monkeypatch):
    ring = RecordingKeyring()
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: ring)
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: "sekret-value")
    assert run_cli("ai", "key", "set") == 0
    assert ring.saved == [("levix", core.SECRET_NAME, "sekret-value")]
    printed = capsys.readouterr().out
    assert "sekret" not in printed, "the value must not appear, not even masked"
    assert "keyring" in printed


def test_key_set_falls_back_to_the_owner_only_file(run_cli, capsys, monkeypatch, context):
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: None)
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: "from-file")
    assert run_cli("ai", "key", "set") == 0
    out = capsys.readouterr().out
    assert "plaintext" in out, "the fallback has to be named as what it is"
    assert "levix[secrets]" in out
    assert context.paths.secrets_file.exists()
    assert context.secret(core.SECRET_NAME) == ("from-file", "file")


def test_key_set_refuses_an_empty_entry_without_touching_the_store(run_cli, capsys, monkeypatch):
    ring = RecordingKeyring()
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: ring)
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: "   ")
    assert run_cli("ai", "key", "set") == EXIT_CONFIG
    assert ring.saved == []


def test_key_set_without_a_terminal_names_the_environment_variable(run_cli, capsys, monkeypatch):
    def no_terminal(*args, **kwargs):
        raise OSError("no console")

    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(typer, "prompt", no_terminal)
    assert run_cli("ai", "key", "set") == EXIT_CONFIG
    assert "LEVIX_AI_API_KEY" in capsys.readouterr().err


def test_key_set_with_the_file_store_disabled_is_a_dependency_error(run_cli, capsys, monkeypatch):
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setenv("LEVIX_DISABLE_FILE_SECRETS", "1")
    monkeypatch.setattr(secrets_module, "_keyring", lambda: None)
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: "would-have-been-stored")
    assert run_cli("ai", "key", "set") == EXIT_MISSING_DEPENDENCY
    err = capsys.readouterr().err
    assert "levix[secrets]" in err
    assert "would-have-been-stored" not in err


def test_key_clear_removes_what_key_set_wrote(run_cli, capsys, monkeypatch, context):
    ring = RecordingKeyring()
    monkeypatch.delenv("LEVIX_AI_API_KEY", raising=False)
    monkeypatch.setattr(secrets_module, "_keyring", lambda: ring)
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: "to-be-forgotten")
    assert run_cli("ai", "key", "set") == 0
    assert context.secret(core.SECRET_NAME)[0] == "to-be-forgotten"
    assert run_cli("ai", "key", "clear") == 0
    assert ring.deleted == [("levix", core.SECRET_NAME)]
    assert "removed" in capsys.readouterr().out


def test_key_clear_says_the_environment_still_holds_a_key(run_cli, capsys, monkeypatch):
    monkeypatch.setenv("LEVIX_AI_API_KEY", "from-env")
    monkeypatch.setattr(secrets_module, "_keyring", lambda: None)
    assert run_cli("ai", "key", "clear") == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "LEVIX_AI_API_KEY" in out
    assert "still in use" in out


def test_bare_key_group_shows_its_help_as_usage(run_cli, capsys):
    assert run_cli("ai", "key") == EXIT_USAGE
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "set" in combined and "clear" in combined

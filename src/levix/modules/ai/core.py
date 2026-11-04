"""Providers, transport, prompt building and the guarded run path for `levix ai`.

Two API families are supported, both described by their public wire formats:

* OpenAI-compatible chat completion servers (`POST {base_url}/chat/completions`,
  `GET {base_url}/models`, streaming as `data:` SSE lines terminated by
  `data: [DONE]`).
* Ollama (`POST {ollama_url}/api/chat`, `POST {ollama_url}/api/generate`,
  `GET {ollama_url}/api/tags`, streaming as newline-delimited JSON objects).

Everything that touches the network goes through one `httpx.Client` built by
`build_client`, so a test can hand it a `MockTransport` and still exercise the real
request construction. Nothing here logs a key, uses `shell=True`, or contacts a host
other than the one the user configured.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

PROVIDER_OPENAI = "openai-compatible"
PROVIDER_OLLAMA = "ollama"
PROVIDERS = (PROVIDER_OPENAI, PROVIDER_OLLAMA)

#: `levix secrets` / env name; `LEVIX_AI_API_KEY` resolves through secrets.py.
SECRET_NAME = "AI_API_KEY"  # noqa: S105 - a lookup key name, not a credential
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_FILE_BYTES = 32_000
#: How much of a server error body we echo back; enough to debug, short enough to read.
ERROR_BODY_CHARS = 240

_STREAM_UNSAFE = (";", "&&", "||", "|", ">", "<", "`", "$(", "${", "\n", "\r")

DEFAULT_SYSTEM = (
    "You are LEVIX ai, a concise assistant running in a terminal. Reply in plain text. "
    "The terminal may not render markdown, colour or non-ASCII glyphs, so do not use them."
)

COMMAND_SYSTEM = (
    "You propose exactly ONE shell command for {platform} ({shell_kind}). "
    "Answer with at most two parts and nothing else. "
    "Line 1 is the command by itself: no markdown fence, no leading $ or > prompt, no pipe, "
    "no ';', no redirection, no command substitution, and it must be a single line. "
    "From line 2 onward, one short sentence saying what it does and how to undo it. "
    "If the request cannot be met by one command, line 1 must be exactly "
    "'NONE' followed by the reason, and give no command."
)


# ---------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str
    model: str
    base_url: str
    ollama_url: str
    temperature: float
    max_tokens: int
    require_approval: bool
    timeout: float = DEFAULT_TIMEOUT

    @property
    def root(self) -> str:
        return self.ollama_url if self.provider == PROVIDER_OLLAMA else self.base_url

    def url(self, path: str) -> str:
        return f"{self.root.rstrip('/')}/{path.lstrip('/')}"

    @property
    def is_loopback(self) -> bool:
        host = (urlsplit(self.root).hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1", "[::1]"}

    def describe(self) -> str:
        return f"{self.provider} model={self.model or '(unset)'} at {self.root}"


def resolve_config(
    value_of: Callable[[str], Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    ollama_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> AIConfig:
    """Flags win over config; nothing is invented when both are silent."""
    from ...errors import ConfigError

    chosen = (provider or str(value_of("ai.provider"))).strip()
    if chosen not in PROVIDERS:
        msg = f"ai.provider must be one of {', '.join(PROVIDERS)}, got {chosen!r}"
        raise ConfigError(msg)

    resolved = AIConfig(
        provider=chosen,
        model=(model if model else None) or str(value_of("ai.model") or "").strip(),
        base_url=(base_url or str(value_of("ai.base_url") or "")).rstrip("/"),
        ollama_url=(ollama_url or str(value_of("ai.ollama_url") or "")).rstrip("/"),
        temperature=(
            float(value_of("ai.temperature")) if temperature is None else float(temperature)
        ),
        max_tokens=int(value_of("ai.max_tokens")) if max_tokens is None else int(max_tokens),
        require_approval=bool(value_of("ai.require_approval")),
        timeout=DEFAULT_TIMEOUT if timeout is None else float(timeout),
    )
    if not resolved.root:
        key = "ai.ollama_url" if chosen == PROVIDER_OLLAMA else "ai.base_url"
        msg = f"{key} is empty, so there is no provider to talk to"
        raise ConfigError(msg, hint=f"set {key} with `levix config set` or pass the matching flag")
    if resolved.timeout <= 0:
        msg = f"--timeout must be a positive number of seconds, got {resolved.timeout:g}"
        raise ConfigError(msg)
    return resolved


@dataclass(frozen=True, slots=True)
class ApiKey:
    value: str | None
    source: str

    @property
    def present(self) -> bool:
        return bool(self.value)

    def needs_key_error(self, config: AIConfig) -> Exception:
        from ...errors import ProviderError
        from ...secrets import env_var_for

        return ProviderError(
            f"{config.provider} at {config.root} needs an API key and none was found.\n"
            f"  set the {env_var_for(SECRET_NAME)} environment variable, or store the key in "
            f"the OS keyring (service 'levix', user '{SECRET_NAME}') or the file store.",
            hint="resolution order is env -> keyring -> owner-only file; `levix ai check` shows "
            "which one answered without revealing the value",
        )


def resolve_key(
    config: AIConfig,
    secret_of: Callable[[str], tuple[str | None, str]],
) -> ApiKey:
    """Look the key up without ever returning it to a log line or an error message."""
    value, source = secret_of(SECRET_NAME)
    key = ApiKey(value=value, source=source)
    if key.present or config.provider == PROVIDER_OLLAMA or config.is_loopback:
        return key
    raise key.needs_key_error(config)


# ---------------------------------------------------------------------------------
# messages and results
# ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def describe(self) -> str:
        total = self.total_tokens
        if total is None and self.prompt_tokens is not None and self.completion_tokens is not None:
            total = self.prompt_tokens + self.completion_tokens
        return (
            f"prompt {dash(self.prompt_tokens)}  completion {dash(self.completion_tokens)}  "
            f"total {dash(total)}"
        )


def dash(value: object) -> str:
    """A value the provider did not report is printed as `-`, never as a guess."""
    return "-" if value is None else str(value)


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    model: str = ""
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class ModelEntry:
    name: str
    detail: str = ""


def build_ask_messages(
    prompt: str,
    *,
    system: str | None = None,
    context: str | None = None,
) -> list[Message]:
    """One turn, plus piped stdin as context when the caller supplied a stream."""
    messages = [Message("system", (system or DEFAULT_SYSTEM).strip())]
    content = prompt.strip()
    if context:
        content = f"Context from stdin:\n{context.strip()}\n\nRequest: {content}"
    messages.append(Message("user", content))
    return messages


# ---------------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Snippet:
    path: Path
    text: str
    size_bytes: int
    read_bytes: int

    @property
    def truncated(self) -> bool:
        return self.read_bytes < self.size_bytes

    def notice(self) -> str:
        if not self.truncated:
            return ""
        return (
            f"{self.path}: showing the first {self.read_bytes} of {self.size_bytes} bytes; "
            f"the rest was NOT sent to the provider (raise it with --max-bytes)"
        )

    def for_prompt(self) -> str:
        tail = "\n[truncated: only the bytes above were read]" if self.truncated else ""
        return f"--- {self.path} ({self.size_bytes} bytes) ---\n{self.text}{tail}"


def read_snippet(path: Path, *, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> Snippet:
    """Read a capped prefix of a text file; decoding never fails, but says what it did."""
    from ...errors import LevixError

    if not path.exists():
        msg = f"no such file: {path}"
        raise LevixError(msg)
    if path.is_dir():
        msg = f"{path} is a directory; `levix ai explain` takes files"
        raise LevixError(msg)
    size_bytes = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(max_bytes)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return Snippet(path=path, text=text, size_bytes=size_bytes, read_bytes=len(raw))


def build_explain_messages(
    snippets: Sequence[Snippet], *, focus: str | None = None
) -> list[Message]:
    body = "\n\n".join(s.for_prompt() for s in snippets)
    ask = f"Explain what this code or text does{f': {focus}' if focus else ''}."
    return [
        Message("system", DEFAULT_SYSTEM),
        Message("user", f"{ask}\n\n{body}"),
    ]


# ---------------------------------------------------------------------------------
# command proposals
# ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandProposal:
    raw: str
    explanation: str
    argv: tuple[str, ...]
    rejected: str | None = None

    @property
    def runnable(self) -> bool:
        return self.rejected is None and bool(self.argv)

    def argv_text(self) -> str:
        return " ".join(repr(part) for part in self.argv)


def render_raw_prompt(messages: Sequence[Message]) -> str:
    """Flatten a conversation into one prompt string for a raw `/api/generate` call.

    Ollama's `raw` mode skips its chat template, so the role labels are ours to write;
    the trailing `ASSISTANT:` is where the model carries on from.
    """
    body = "\n\n".join(f"{m.role.upper()}: {m.content}" for m in messages)
    return f"{body}\n\nASSISTANT:"


def platform_hint() -> tuple[str, str]:
    if os.name == "nt":
        return "Windows", "cmd.exe style (a single executable with its own arguments)"
    return "POSIX", "/bin/sh style"


def build_command_messages(request: str) -> list[Message]:
    platform, shell_kind = platform_hint()
    return [
        Message("system", COMMAND_SYSTEM.format(platform=platform, shell_kind=shell_kind)),
        Message("user", request.strip()),
    ]


def _unfence(text: str) -> str:
    """Drop markdown fences, closed or not: models wrap the command in them constantly."""
    body = (text or "").strip()
    if not body.startswith(("```", "~~~")):
        return body
    lines = body.splitlines()[1:]
    if lines and lines[-1].strip().startswith(("```", "~~~")):
        lines = lines[:-1]
    return "\n".join(lines)


def split_argv(line: str) -> tuple[str, ...]:
    """One command line to an argument list, without a shell anywhere in the process."""
    if os.name == "nt":
        # cmd-style quoting: keep the quotes we need to strip, so "C:\My Dir\x.exe" stays one arg.
        parts = shlex.split(line, posix=False, comments=False)
        return tuple(
            part[1:-1] if len(part) > 1 and part[0] == part[-1] in "\"'" else part for part in parts
        )
    return tuple(shlex.split(line, comments=False, posix=True))


_LABEL_ONLY = re.compile(r"^(?:assistant|output)\s*:?\s*$", re.IGNORECASE)
_FENCE_ONLY = re.compile(r"^(?:`{3,}|~{3,})[A-Za-z0-9_+.-]*$")


def extract_proposal(text: str) -> CommandProposal:
    """Take the model's first content line as a command, everything after it as the caveat."""
    body = _unfence(text)
    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
        and not _LABEL_ONLY.match(line.strip())
        and not _FENCE_ONLY.match(line.strip())
    ]
    if not lines:
        return CommandProposal(
            raw="", explanation="", argv=(), rejected="the model returned nothing usable"
        )
    line = re.sub(r"^\s*assistant\s*:\s*", "", lines[0], flags=re.IGNORECASE).strip()
    # A copied shell prompt is not part of the command.
    line = re.sub(r"^[$>]\s*", "", line).strip()
    explanation = " ".join(lines[1:]).strip()

    if not line:
        return CommandProposal(
            raw=line, explanation=explanation, argv=(), rejected="empty command line"
        )
    if line.upper().startswith("NONE"):
        return CommandProposal(
            raw=line, explanation=explanation, argv=(), rejected=line[4:].strip() or "declined"
        )
    for token in _STREAM_UNSAFE:
        if token in line:
            return CommandProposal(
                raw=line,
                explanation=explanation,
                argv=(),
                rejected=(
                    f"it contains {token.strip()!r}; LEVIX runs an argument list, not a shell, "
                    "so pipelines, chains and redirection are refused"
                ),
            )
    try:
        argv = split_argv(line)
    except ValueError as exc:
        return CommandProposal(
            raw=line, explanation=explanation, argv=(), rejected=f"cannot parse: {exc}"
        )
    if not argv:
        return CommandProposal(
            raw=line, explanation=explanation, argv=(), rejected="no executable named"
        )
    return CommandProposal(raw=line, explanation=explanation, argv=argv)


def run_proposal(argv: Sequence[str], *, timeout: float) -> int:
    """Execute the approved argument list with its output on the user's terminal."""
    from ...errors import ExternalToolError

    program = argv[0]
    resolved = shutil.which(program)
    if resolved is None:
        msg = f"cannot run {program!r}: it is not on PATH"
        raise ExternalToolError(
            msg, hint="install the tool, or copy the command and run it yourself"
        )
    try:
        # shell=False, an argument list, no pipe chain; streams stay with the terminal.
        # argv was approved by a human one line above; S603 is satisfied in spirit.
        completed = subprocess.run(
            [resolved, *argv[1:]],
            shell=False,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ExternalToolError(
            f"{program!r} did not finish within {timeout:g}s",
            hint="the process may still be running; check your task manager",
        ) from None
    except OSError as exc:
        msg = f"{program!r} could not be started: {type(exc).__name__}"
        raise ExternalToolError(msg) from exc
    if completed.returncode != 0:
        msg = f"{program!r} ran and exited with code {completed.returncode}"
        raise ExternalToolError(msg)
    return completed.returncode


# ---------------------------------------------------------------------------------
# stream parsing (pure: a list of lines in, text out)
# ---------------------------------------------------------------------------------


def iter_sse_text(lines: Iterable[str]) -> Iterator[str]:
    """OpenAI-compatible `data:` SSE frames; stops at `[DONE]`."""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        chunk = _load_chunk(payload, flavour="SSE")
        yield from _delta_texts(chunk)


def iter_ndjson_text(lines: Iterable[str], *, key: str = "message") -> Iterator[str]:
    """Ollama's newline-delimited JSON objects; a `done: true` frame ends the stream.

    The final frame still carries the last piece of text (and, for `/api/generate`, often
    the whole answer), so its content is yielded before the stream is closed.
    """
    from ...errors import ProviderError

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        chunk = _load_chunk(line, flavour="ndjson")
        error = chunk.get("error")
        if isinstance(error, str) and error:
            msg = f"ollama reported an error mid-stream: {error[:ERROR_BODY_CHARS]}"
            raise ProviderError(msg)
        value = _dig(chunk, key, "content") or _dig(chunk, "response")
        if isinstance(value, str) and value:
            yield value
        if chunk.get("done") is True:
            return


def _load_chunk(payload: str, *, flavour: str) -> dict[str, Any]:
    from ...errors import ProviderError

    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError as exc:
        msg = f"malformed {flavour} chunk from the provider: {exc.msg} at offset {exc.pos}"
        raise ProviderError(msg) from exc
    if not isinstance(chunk, dict):
        msg = f"malformed {flavour} chunk: expected a JSON object, got {type(chunk).__name__}"
        raise ProviderError(msg)
    return chunk


def _dig(data: Any, *path: str) -> Any:
    node = data
    for step in path:
        if not isinstance(node, dict):
            return None
        node = node.get(step)
    return node


def _delta_texts(chunk: dict[str, Any]) -> Iterator[str]:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return
    first = choices[0]
    if not isinstance(first, dict):
        return
    delta = first.get("delta")
    if isinstance(delta, dict):
        text = delta.get("content")
        if isinstance(text, str) and text:
            yield text
    message = first.get("message")
    if isinstance(message, dict):
        text = message.get("content")
        if isinstance(text, str) and text:
            yield text


# ---------------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HttpSpec:
    method: str
    url: str
    headers: dict[str, str]
    payload: dict[str, Any] | None = None


class Provider:
    """One provider adapter: builds request specs and decodes responses."""

    name: str = ""

    def __init__(self, config: AIConfig, key: ApiKey) -> None:
        self.config = config
        self.key = key

    def headers(self, *, streaming: bool, accept_json: bool = True) -> dict[str, str]:
        headers = {"Accept": "text/event-stream" if streaming else "application/json"}
        if accept_json and not streaming:
            headers["Content-Type"] = "application/json"
        if self.key.present and self.name == PROVIDER_OPENAI:
            headers["Authorization"] = f"Bearer {self.key.value}"
        return headers

    def _options(self) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": self.config.temperature}
        if self.config.max_tokens > 0:
            options["num_predict"] = self.config.max_tokens
        return options

    def completion_spec(
        self, messages: Sequence[Message], *, stream: bool, raw: bool = False
    ) -> HttpSpec:
        raise NotImplementedError

    def parse_completion(self, body: Any) -> ChatResult:
        raise NotImplementedError

    def parse_stream(self, lines: Iterable[str]) -> str:
        raise NotImplementedError

    def models_spec(self) -> HttpSpec:
        raise NotImplementedError

    def parse_models(self, body: Any) -> list[ModelEntry]:
        raise NotImplementedError


class OpenAIProvider(Provider):
    """`/chat/completions` plus `/models`, per the OpenAI-compatible server contract."""

    name = PROVIDER_OPENAI

    def completion_spec(
        self, messages: Sequence[Message], *, stream: bool, raw: bool = False
    ) -> HttpSpec:
        # `raw` is an Ollama concept: a chat-completions server always gets the message list.
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.config.temperature,
            "stream": stream,
        }
        if self.config.max_tokens > 0:
            payload["max_tokens"] = self.config.max_tokens
        return HttpSpec(
            "POST",
            self.config.url("chat/completions"),
            self.headers(streaming=stream),
            payload,
        )

    def parse_completion(self, body: Any) -> ChatResult:
        from ...errors import ProviderError

        if not isinstance(body, dict):
            msg = f"{self.name} returned {type(body).__name__}, expected a JSON object"
            raise ProviderError(msg)
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            msg = f"{self.name} response has no choices: keys {sorted(body)!s}"
            raise ProviderError(msg, hint="check ai.model against the models the server lists")
        first = choices[0]
        text = _dig(first, "message", "content")
        if text is None:
            text = _dig(first, "text")
        if not isinstance(text, str):
            msg = f"{self.name} choice 0 carries no textual content"
            raise ProviderError(msg)
        return ChatResult(
            text=text,
            model=str(body.get("model") or self.config.model),
            usage=_openai_usage(body.get("usage")),
        )

    def parse_stream(self, lines: Iterable[str]) -> str:
        return "".join(iter_sse_text(lines))

    def models_spec(self) -> HttpSpec:
        return HttpSpec("GET", self.config.url("models"), self.headers(streaming=False))

    def parse_models(self, body: Any) -> list[ModelEntry]:
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return []
        entries = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                owner = _dig(item, "owned_by")
                entries.append(ModelEntry(item["id"], str(owner) if owner else ""))
        return entries


def _openai_usage(raw: Any) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    return Usage(
        prompt_tokens=_int(raw.get("prompt_tokens")),
        completion_tokens=_int(raw.get("completion_tokens")),
        total_tokens=_int(raw.get("total_tokens")),
    )


def _int(raw: Any) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


class OllamaProvider(Provider):
    """/api/chat for a conversation, /api/generate for the single-command raw prompt."""

    name = PROVIDER_OLLAMA

    def completion_spec(
        self, messages: Sequence[Message], *, stream: bool, raw: bool = False
    ) -> HttpSpec:
        if stream:
            return HttpSpec(
                "POST",
                self.config.url("api/chat"),
                self.headers(streaming=True),
                {
                    "model": self.config.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "stream": True,
                    "options": self._options(),
                },
            )
        if raw:
            # /api/generate with raw=True sends our text verbatim: no chat template gets to
            # reformat the strict two-line answer `command` has to parse back out.
            prompt = render_raw_prompt(messages)
            return HttpSpec(
                "POST",
                self.config.url("api/generate"),
                self.headers(streaming=False),
                {
                    "model": self.config.model,
                    "prompt": prompt,
                    "raw": True,
                    "stream": False,
                    "options": self._options(),
                },
            )
        return HttpSpec(
            "POST",
            self.config.url("api/chat"),
            self.headers(streaming=False),
            {
                "model": self.config.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "options": self._options(),
            },
        )

    def parse_completion(self, body: Any) -> ChatResult:
        from ...errors import ProviderError

        if not isinstance(body, dict):
            msg = f"{self.name} returned {type(body).__name__}, expected a JSON object"
            raise ProviderError(msg)
        text = _dig(body, "message", "content")
        if text is None:
            text = body.get("response")
        if not isinstance(text, str):
            msg = (
                f"{self.name} response carries neither message.content nor response: "
                f"keys {sorted(body)!s}"
            )
            raise ProviderError(msg)
        error = body.get("error")
        if isinstance(error, str) and error:
            msg = f"{self.name} reported an error: {error[:ERROR_BODY_CHARS]}"
            raise ProviderError(msg)
        return ChatResult(
            text=text,
            model=str(body.get("model") or self.config.model),
            usage=_ollama_usage(body),
        )

    def parse_stream(self, lines: Iterable[str]) -> str:
        return "".join(iter_ndjson_text(lines))

    def models_spec(self) -> HttpSpec:
        return HttpSpec("GET", self.config.url("api/tags"), self.headers(streaming=False))

    def parse_models(self, body: Any) -> list[ModelEntry]:
        raw = body.get("models") if isinstance(body, dict) else None
        if not isinstance(raw, list):
            return []
        entries = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if not isinstance(name, str):
                continue
            size = _int(item.get("size"))
            family = _dig(item, "details", "family")
            detail = f"{family or 'unknown'}" + (f" {human_size(size)}" if size else "")
            entries.append(ModelEntry(name, detail.strip()))
        return entries


def _ollama_usage(body: dict[str, Any]) -> Usage | None:
    prompt = _int(body.get("prompt_eval_count"))
    completion = _int(body.get("eval_count"))
    if prompt is None and completion is None:
        return None
    total = prompt + completion if None not in (prompt, completion) else None
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def human_size(num_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def provider_for(config: AIConfig, key: ApiKey) -> Provider:
    return (
        OllamaProvider(config, key)
        if config.provider == PROVIDER_OLLAMA
        else OpenAIProvider(config, key)
    )


def completion_url(config: AIConfig) -> str:
    """Where a completion request would go, for `check` to print without sending it."""
    if config.provider == PROVIDER_OLLAMA:
        return config.url("api/chat")
    return config.url("chat/completions")


def models_url(config: AIConfig) -> str:
    """The model-list endpoint for this provider, printed without being called."""
    if config.provider == PROVIDER_OLLAMA:
        return config.url("api/tags")
    return config.url("models")


def httpx_version() -> str:
    return str(getattr(httpx, "__version__", "unknown"))


# ---------------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------------


def build_client(*, timeout: float) -> httpx.Client:
    """The only place an httpx.Client is made, so tests can swap in a MockTransport."""
    return httpx.Client(timeout=timeout)


def _describe_status(status: int, body_text: str, *, provider_name: str, url: str) -> Exception:
    from ...errors import ProviderError

    excerpt = body_text.strip()[:ERROR_BODY_CHARS]
    tail = f" - {excerpt}" if excerpt else ""
    if status in (401, 403):
        return ProviderError(
            f"{provider_name} rejected our credentials with HTTP {status} for {url}.{tail}",
            hint="check the key with `levix ai check` (env -> OS keyring -> owner-only file)",
        )
    if status == 404:
        return ProviderError(
            f"{provider_name} answered HTTP 404 for {url}.{tail}",
            hint="the path or the model name is wrong; `levix ai models` lists what is available",
        )
    if status == 429:
        return ProviderError(
            f"{provider_name} rate limited this request (HTTP 429) at {url}.{tail}",
            hint="wait before retrying, or ask for a shorter reply with --max-tokens",
        )
    if status >= 500:
        return ProviderError(
            f"{provider_name} failed the request at {url} with HTTP {status}.{tail}"
        )
    return ProviderError(
        f"{provider_name} answered HTTP {status} for {url}.{tail}",
    )


def _checked(response: httpx.Response, *, provider_name: str, spec: HttpSpec) -> httpx.Response:
    if response.status_code < 300:
        return response
    try:
        # An unreadable body must never hide the status code we are about to report.
        body_text = response.text
    except Exception:
        body_text = ""
    raise _describe_status(
        response.status_code, body_text, provider_name=provider_name, url=spec.url
    )


def post_completion(
    client: httpx.Client,
    provider: Provider,
    messages: Sequence[Message],
    *,
    raw: bool = False,
) -> ChatResult:
    """One non-streaming completion: the reply text plus its usage, if it carried any."""
    from ...errors import ProviderError

    spec = provider.completion_spec(messages, stream=False, raw=raw)
    try:
        response = client.request(spec.method, spec.url, headers=spec.headers, json=spec.payload)
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"{provider.name} did not answer {spec.url} within {provider.config.timeout:g}s "
            f"(change --timeout): {type(exc).__name__}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"cannot reach {provider.name} at {spec.url}: {type(exc).__name__}",
            hint="is the server running and the URL right? `levix ai check --live` tests it",
        ) from exc
    _checked(response, provider_name=provider.name, spec=spec)
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderError(f"{provider.name} sent a non-JSON body for {spec.url}: {exc}") from exc
    return provider.parse_completion(body)


def stream_completion(
    client: httpx.Client,
    provider: Provider,
    messages: Sequence[Message],
    *,
    sink: Callable[[str], None] | None = None,
) -> str:
    """Streamed completion; each chunk is handed to `sink` as it arrives."""
    from ...errors import ProviderError

    spec = provider.completion_spec(messages, stream=True)
    collected: list[str] = []
    try:
        with client.stream(
            spec.method, spec.url, headers=spec.headers, json=spec.payload
        ) as response:
            _checked(response, provider_name=provider.name, spec=spec)
            for text in provider.parse_stream(response.iter_lines()):
                collected.append(text)
                if sink is not None:
                    sink(text)
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"{provider.name} stalled mid-stream at {spec.url} after "
            f"{provider.config.timeout:g}s: {type(exc).__name__}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"stream from {provider.name} at {spec.url} failed: {type(exc).__name__}"
        ) from exc
    return "".join(collected)


def fetch_models(
    client: httpx.Client,
    provider: Provider,
) -> list[ModelEntry] | None:
    """None means "this server does not offer a model list" (HTTP 404), which is normal."""
    from ...errors import ProviderError

    spec = provider.models_spec()
    try:
        response = client.request(spec.method, spec.url, headers=spec.headers)
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"{provider.name} did not answer {spec.url} within {provider.config.timeout:g}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"cannot reach {provider.name} at {spec.url}: {type(exc).__name__}",
            hint="start the server or point --base-url / --ollama-url at the right host",
        ) from exc
    if response.status_code == 404:
        return None
    _checked(response, provider_name=provider.name, spec=spec)
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderError(
            f"{provider.name} sent a non-JSON model list for {spec.url}: {exc}"
        ) from exc
    return provider.parse_models(body)


def ping(client: httpx.Client, provider: Provider) -> str:
    """Connectivity probe using the model-list endpoint: it proves reachability and auth."""
    models = fetch_models(client, provider)
    if models is None:
        return f"{provider.name} answered {provider.models_spec().url} with 404: reachable."
    return f"{provider.name} answered with {len(models)} model(s)."

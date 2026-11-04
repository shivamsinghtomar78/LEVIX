"""LEVIX AI - a chat assistant over an OpenAI-compatible or Ollama server.

`levix --help` imports this file for every registered module, so it is pure data: no
httpx, no typer, no subprocess. Those live in `core.py` and `cli.py`, which the registry
only reaches when someone actually types `levix ai ...`.

The security posture this module promises: a model-proposed command is never executed
without a typed confirmation in a real terminal, `--yes` cannot buy that confirmation,
and the API key is read through `levix.secrets` and never printed, logged or echoed.
"""

from __future__ import annotations

from levix.sdk import CommandInfo, ModuleManifest, PackageRef, Permission, UiSpec

MANIFEST = ModuleManifest(
    name="ai",
    title="AI Assistant",
    summary="Ask, explain and propose commands against your own model server.",
    cli_path="levix.modules.ai.cli:build_app",
    commands=(
        CommandInfo(
            "ask",
            "Send a prompt (argument or stdin) and print the reply; --stream to follow tokens.",
            aliases=("q",),
        ),
        CommandInfo(
            "explain",
            "Explain files: reads a capped prefix of each and says what it left out.",
        ),
        CommandInfo(
            "command",
            "Propose one shell command; runs it only after you type RUN (--run).",
            aliases=("cmd",),
        ),
        CommandInfo("models", "List the models this provider reports, or say it cannot."),
        CommandInfo(
            "check",
            "Provider, URL, key source and options; --live adds one read-only request.",
        ),
    ),
    requirements=(
        PackageRef(
            "httpx",
        ),
    ),
    extras=("ai",),
    capabilities=("openai-compatible", "ollama", "sse-streaming", "ndjson-streaming"),
    permissions=frozenset(
        {
            Permission.NETWORK,
            Permission.SECRET_READ,
            Permission.FS_READ,
            Permission.SUBPROCESS,
        }
    ),
    # `check`, not `ask`: the dashboard cannot type a prompt, and `ask` with no argument
    # waits on stdin. `check` prints provider, base URL, key source and options and exits.
    ui=UiSpec(mode="suspend", argv=("ai", "check")),
    documentation="docs/modules/AI.md",
)

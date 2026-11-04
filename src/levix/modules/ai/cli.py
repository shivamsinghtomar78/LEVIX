"""`levix ai` command surface.

httpx is only reached through `core`, and `ensure_dependencies` has proved it exists
before Typer calls in here. Nothing in this file prints a key, and nothing runs a command
without putting it through `levix.approve.require_approval` first.

Windows consoles are cp1252, so every glyph comes from `terminal.active_glyphs()` or from
`rich.box.ASCII`; model text is printed with markup and highlighting off, because a reply
containing `[bold]` is data, not a style directive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.box import ASCII
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ... import terminal
from ...approve import require_approval
from ...context import LevixContext
from ...deps import ensure_dependencies
from ...secrets import env_var_for
from . import MANIFEST, core

console = Console()

PROVIDER_HELP = "Which API speaks: openai-compatible or ollama."

# The provider flags mean the same thing on every command, so the OptionInfo objects are
# shared instead of retyped: one help string, five commands, no chance they drift apart.
_PROVIDER = typer.Option(None, "--provider", help=PROVIDER_HELP)
_MODEL = typer.Option(None, "--model", "-m", help="Overrides ai.model.")
_BASE_URL = typer.Option(None, "--base-url", help="Overrides ai.base_url.")
_OLLAMA_URL = typer.Option(None, "--ollama-url", help="Overrides ai.ollama_url.")
_TEMPERATURE = typer.Option(None, "--temperature", help="Overrides ai.temperature.")
_MAX_TOKENS = typer.Option(None, "--max-tokens", help="Overrides ai.max_tokens.")
_TIMEOUT = typer.Option(None, "--timeout", help="Seconds per request; default 60.")
_SHOW_USAGE = typer.Option(False, "--show-usage", help="Print token counts if reported.")


def _gate(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        return
    ensure_dependencies(MANIFEST)


def build_app() -> typer.Typer:
    application = typer.Typer(
        name="ai",
        help=MANIFEST.summary,
        no_args_is_help=True,
        callback=_gate,
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    )
    surface = {"ask": ask, "explain": explain, "command": command, "models": models, "check": check}
    for info in MANIFEST.commands:
        # Registering from the manifest keeps `levix ai -h` and the dashboard's list of
        # this module unable to disagree.
        function = surface[info.name]
        application.command(info.name, help=info.help)(function)
        for alias in info.aliases:
            application.command(alias, help=info.help, hidden=True)(function)
    return application


# ---------------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------------


def _obj(typer_ctx: typer.Context) -> LevixContext:
    """The shared LevixContext: the parent's when click passes one, else build it.

    `levix <module>` forwards argv into a fresh click invocation (see levix.router), so a
    module command normally arrives with `ctx.obj is None`. `ai` cannot run on guessed
    defaults - provider, URL and key all come from the user's configuration - so it builds
    the same context the root callback builds. Nothing is cached: a cached context would
    pin the paths and config of whichever command ran first.
    """
    obj = getattr(typer_ctx, "obj", None)
    if isinstance(obj, LevixContext):
        return obj
    from ...app import build_context

    return build_context()


def _provider(
    typer_ctx: typer.Context,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    ollama_url: str | None,
    temperature: float | None,
    max_tokens: int | None,
    timeout: float | None,
) -> tuple[core.AIConfig, core.Provider]:
    """Config plus flags -> an AIConfig, a key lookup and the matching provider adapter."""
    obj = _obj(typer_ctx)
    config = core.resolve_config(
        obj.value,
        provider=provider,
        model=model,
        base_url=base_url,
        ollama_url=ollama_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    key = core.resolve_key(config, obj.secret)
    obj.logger.debug("ai request to %s (key source: %s)", config.describe(), key.source)
    return config, core.provider_for(config, key)


def _piped_stdin() -> str | None:
    """Stdin content when it is a pipe or a file, else None. Never blocks on a TTY."""
    try:
        if sys.stdin.isatty():
            return None
        data = sys.stdin.read()
    except (OSError, ValueError):
        return None
    return data or None


def _say(text: str) -> None:
    """Model output: markup off, so brackets in an answer stay characters."""
    console.print(text, markup=False, highlight=False)


def _report_usage(result: core.ChatResult, show_usage: bool) -> None:
    if not show_usage:
        return
    if result.usage is None:
        console.print(
            "[dim]usage: this reply carried no token counts "
            "(streamed responses do not include them)[/dim]"
        )
        return
    model = f"  model {escape(result.model)}" if result.model else ""
    console.print(f"[dim]usage: {escape(result.usage.describe())}{model}[/dim]")


# ---------------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------------


def ask(
    typer_ctx: typer.Context,
    prompt: str = typer.Argument(
        "", help="The question. Omit it to read the whole prompt from stdin."
    ),
    provider: str | None = _PROVIDER,
    model: str | None = _MODEL,
    base_url: str | None = _BASE_URL,
    ollama_url: str | None = _OLLAMA_URL,
    system: str | None = typer.Option(None, "--system", "-s", help="Replace the system message."),
    temperature: float | None = _TEMPERATURE,
    max_tokens: int | None = _MAX_TOKENS,
    timeout: float | None = _TIMEOUT,
    stream: bool = typer.Option(False, "--stream", help="Print tokens as they arrive."),
    show_usage: bool = _SHOW_USAGE,
) -> None:
    """Ask the model something and print the answer.

    With a PROMPT argument and piped stdin the pipe becomes context for the request; with
    no PROMPT, stdin is the prompt. Only the configured provider is ever contacted.
    """
    piped = _piped_stdin()
    text = prompt
    context: str | None = piped
    if not text.strip():
        if not piped:
            msg = "no prompt given: pass one as an argument or pipe it in"
            raise typer.BadParameter(msg)
        text, context = piped, None
    elif context:
        console.print(f"[dim]adding {len(context)} bytes of stdin as context[/dim]")

    config, prov = _provider(
        typer_ctx, provider, model, base_url, ollama_url, temperature, max_tokens, timeout
    )
    messages = core.build_ask_messages(text, system=system, context=context)

    def emit(chunk: str) -> None:
        console.print(chunk, end="", markup=False, highlight=False)

    with core.build_client(timeout=config.timeout) as client:
        if stream:
            answer = core.stream_completion(client, prov, messages, sink=emit)
            console.print()
            result = core.ChatResult(text=answer, model=config.model)
        else:
            result = core.post_completion(client, prov, messages)
            _say(result.text)
    if not result.text.strip():
        console.print("[yellow]the provider returned an empty answer[/yellow]")
    _report_usage(result, show_usage)


# ---------------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------------


def explain(
    typer_ctx: typer.Context,
    files: list[Path] = typer.Argument(..., help="Files to explain, one after another."),
    focus: str | None = typer.Option(None, "--focus", help="What to look at specifically."),
    max_bytes: int | None = typer.Option(
        None,
        "--max-bytes",
        help=f"Read at most this many bytes per file (default {core.DEFAULT_MAX_FILE_BYTES}).",
    ),
    provider: str | None = _PROVIDER,
    model: str | None = _MODEL,
    base_url: str | None = _BASE_URL,
    ollama_url: str | None = _OLLAMA_URL,
    temperature: float | None = _TEMPERATURE,
    max_tokens: int | None = _MAX_TOKENS,
    timeout: float | None = _TIMEOUT,
    show_usage: bool = _SHOW_USAGE,
) -> None:
    """Explain files: only the capped prefix that was read is sent, and we say so."""
    if not files:
        msg = "name at least one file to explain"
        raise typer.BadParameter(msg)
    cap = core.DEFAULT_MAX_FILE_BYTES if max_bytes is None else max_bytes
    if cap <= 0:
        raise typer.BadParameter("--max-bytes must be a positive number of bytes")
    snippets = [core.read_snippet(path, max_bytes=cap) for path in files]
    for snippet in snippets:
        notice = snippet.notice()
        if notice:
            console.print(f"[yellow]{escape(notice)}[/yellow]")

    config, prov = _provider(
        typer_ctx, provider, model, base_url, ollama_url, temperature, max_tokens, timeout
    )
    messages = core.build_explain_messages(snippets, focus=focus)
    with core.build_client(timeout=config.timeout) as client:
        result = core.post_completion(client, prov, messages)
    _say(result.text)
    _report_usage(result, show_usage)


# ---------------------------------------------------------------------------------
# command
# ---------------------------------------------------------------------------------


def command(
    typer_ctx: typer.Context,
    request: str = typer.Argument(..., help="What you want the shell to do."),
    run: bool = typer.Option(False, "--run", help="Offer to execute the proposal."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accepted and ignored: only a typed RUN runs a command."
    ),
    provider: str | None = _PROVIDER,
    model: str | None = _MODEL,
    base_url: str | None = _BASE_URL,
    ollama_url: str | None = _OLLAMA_URL,
    temperature: float | None = _TEMPERATURE,
    max_tokens: int | None = _MAX_TOKENS,
    timeout: float | None = _TIMEOUT,
    show_usage: bool = _SHOW_USAGE,
) -> None:
    """Propose ONE shell command, print it, and run it only after you approve by hand.

    The gate is `levix.approve.require_approval(destructive=True)`: `--yes` is refused by
    design, and with no terminal to read from the command exits 6 having run nothing.
    Execution is an argument list with shell=False, so a pipeline or a `;` chain coming
    from the model is rejected before it reaches a process.
    """
    config, prov = _provider(
        typer_ctx, provider, model, base_url, ollama_url, temperature, max_tokens, timeout
    )
    messages = core.build_command_messages(request)
    with core.build_client(timeout=config.timeout) as client:
        # raw=True for Ollama: /api/generate with no chat template, so the strict two-line
        # answer arrives as written. OpenAI-compatible servers ignore the flag.
        result = core.post_completion(client, prov, messages, raw=True)
    proposal = core.extract_proposal(result.text)
    console.print(_proposal_panel(proposal, config))
    _report_usage(result, show_usage)

    if proposal.rejected:
        console.print(f"[yellow]no command offered:[/yellow] {escape(proposal.rejected)}")
        console.print("nothing has run.")
        return

    if not run:
        console.print(
            "[dim]print-only (the default): nothing ran. Add --run to be asked whether to "
            "execute it.[/dim]"
        )
        return

    detail = f"{proposal.raw}  (argv: {proposal.argv_text()})"
    if config.require_approval:
        require_approval(
            "run the model-proposed command",
            detail,
            assume_yes=yes,
            destructive=True,
            prompt_word="RUN",
        )
    else:
        console.print(
            "[bold yellow]ai.require_approval is false: running the proposal without asking, "
            "because your configuration opted out of the gate.[/bold yellow]"
        )
    console.print(f"[cyan]running:[/cyan] {escape(detail)}")
    core.run_proposal(proposal.argv, timeout=config.timeout)
    console.print("[green]the command finished with exit code 0[/green]")


def _proposal_panel(proposal: core.CommandProposal, config: core.AIConfig) -> Panel:
    set_ = terminal.active_glyphs()
    lines = Text()
    if proposal.raw:
        lines.append(f"{set_['arrow']} ")
        lines.append(proposal.raw, style="bold bright_cyan")
    else:
        lines.append("(the model gave no command line)", style="yellow")
    if proposal.explanation:
        lines.append(f"\n{proposal.explanation}")
    lines.append(
        f"\nprovider {config.provider} model {config.model or '(unset)'} - "
        "this text came from a model, not from you",
        style="dim",
    )
    return Panel(
        lines,
        box=ASCII,
        border_style="cyan",
        title="PROPOSED COMMAND",
        title_align="left",
        padding=(0, 1),
    )


# ---------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------


def models(
    typer_ctx: typer.Context,
    provider: str | None = _PROVIDER,
    base_url: str | None = _BASE_URL,
    ollama_url: str | None = _OLLAMA_URL,
    timeout: float | None = _TIMEOUT,
) -> None:
    """List what the provider reports. A server without a model endpoint is not an error."""
    config, prov = _provider(typer_ctx, provider, None, base_url, ollama_url, None, None, timeout)
    with core.build_client(timeout=config.timeout) as client:
        listed = core.fetch_models(client, prov)

    if listed is None:
        console.print(
            f"[yellow]{escape(prov.models_spec().url)} answered HTTP 404.[/yellow] This server "
            "does not implement a model list, which is common for OpenAI-compatible gateways; "
            "nothing is guessed."
        )
        console.print(
            f"configured model: [bold]{escape(config.model or '(unset)')}[/bold] at "
            f"{escape(config.root)}"
        )
        return

    table = Table(title=f"{config.provider} models", header_style="bold cyan", box=ASCII)
    table.add_column("model", overflow="fold")
    table.add_column("detail", overflow="fold")
    for entry in listed:
        table.add_row(entry.name, entry.detail or "-")
    if not listed:
        table.add_row("[cyan]the provider answered with an empty list[/cyan]", "-")
    console.print(table)
    if config.model and all(entry.name != config.model for entry in listed):
        console.print(
            f"[yellow]note:[/yellow] configured model {escape(config.model)!r} is not in this "
            "list; check `levix ai check`."
        )


# ---------------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------------


def check(
    typer_ctx: typer.Context,
    live: bool = typer.Option(
        False, "--live", help="Send one read-only request to the model list endpoint."
    ),
    provider: str | None = _PROVIDER,
    model: str | None = _MODEL,
    base_url: str | None = _BASE_URL,
    ollama_url: str | None = _OLLAMA_URL,
    timeout: float | None = _TIMEOUT,
) -> None:
    """Report the setup honestly. Offline by default: without --live no socket is opened."""
    obj = _obj(typer_ctx)
    config = core.resolve_config(
        obj.value,
        provider=provider,
        model=model,
        base_url=base_url,
        ollama_url=ollama_url,
        timeout=timeout,
    )
    key_value, key_source = obj.secret(core.SECRET_NAME)

    table = Table(title="levix ai check", header_style="bold cyan", box=ASCII, show_header=False)
    table.add_column("setting", style="bold")
    table.add_column("value", overflow="fold")
    source = "command line flag" if provider else obj.config.source("ai.provider")
    table.add_row("provider", f"{config.provider} [dim](ai.provider source: {source})[/dim]")
    table.add_row("model", config.model or "[yellow](unset)[/yellow]")
    table.add_row("base url", config.base_url or "[yellow](unset)[/yellow]")
    table.add_row("ollama url", config.ollama_url or "[yellow](unset)[/yellow]")
    table.add_row("completion url", core.completion_url(config))
    table.add_row("models url", core.models_url(config))
    table.add_row("temperature", f"{config.temperature}")
    table.add_row("max tokens", f"{config.max_tokens}")
    table.add_row("timeout", f"{config.timeout:g}s")
    table.add_row(
        "approval gate",
        "on - a typed confirmation is required to run a proposed command"
        if config.require_approval
        else "[bold red]OFF in your configuration - commands run without asking[/bold red]",
    )
    table.add_row("httpx", core.httpx_version())
    console.print(table)

    console.print(
        f"key: [bold]{key_source}[/bold] [dim](stored as {core.SECRET_NAME}; the value is "
        "never printed, logged or echoed)[/dim]"
    )
    if config.provider == core.PROVIDER_OLLAMA:
        console.print(
            "[dim]Ollama needs no API key; its /api endpoints are unauthenticated by default, "
            "so keep it on localhost.[/dim]"
        )
    elif key_value is None and not config.is_loopback:
        console.print(
            f"[yellow]warning:[/yellow] no key found for {core.SECRET_NAME} - looked in "
            f"{env_var_for(core.SECRET_NAME)}, then the OS keyring, then the owner-only file. "
            "A request to this non-local host would fail with exit 8."
        )

    if not live:
        console.print("[dim]no request was sent; pass --live for one read-only probe.[/dim]")
        return

    provider = core.provider_for(config, core.resolve_key(config, obj.secret))
    with core.build_client(timeout=config.timeout) as client:
        report = core.ping(client, provider)
    console.print(f"[green]live:[/green] {escape(report)}")

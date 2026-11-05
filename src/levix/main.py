"""Process entry point: drives the click context and owns the exit-code mapping.

Click objects are matched by class name rather than by `isinstance`. Typer 0.27 runs on
its own vendored click fork, so `isinstance(exc, click.UsageError)` is False for the
exceptions it actually raises - and a silent fall-through to "unexpected error" is
exactly how a CLI ends up printing a traceback instead of a usage message.
"""

from __future__ import annotations

import contextlib
import re
import sys
import time
from typing import Any

from .app import build_app
from .errors import (
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_RUNTIME,
    EXIT_UNKNOWN_MODULE,
    EXIT_USAGE,
    LevixError,
)
from .logging_setup import get_logger


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    started = time.perf_counter()

    from typer import main as typer_main

    app = build_app()
    click_app = typer_main.get_command(app)

    exit_code = EXIT_OK
    ctx = None
    try:
        ctx = click_app.make_context("levix", args)
        result = click_app.invoke(ctx)
        if isinstance(result, int):
            exit_code = result
    except BaseException as exc:
        handled = _classify(exc)
        exit_code = _report_unexpected(exc, args) if handled is None else handled
    finally:
        if ctx is not None:
            with contextlib.suppress(Exception):
                ctx.close()
        duration_ms = (time.perf_counter() - started) * 1000.0
        # The context object is read here, not before `invoke`: the root callback is what
        # builds it, and that runs during invoke. Capturing it early handed `_record` a
        # None every time, so the command history the dashboard shows stayed empty.
        _record(getattr(ctx, "obj", None), tuple(args), exit_code, duration_ms)

    return exit_code


def _classify(exc: BaseException) -> int | None:
    """Map an exception to an exit code, or None when it is a genuine bug."""
    if isinstance(exc, LevixError):
        _render_error(exc)
        return exc.exit_code

    if isinstance(exc, KeyboardInterrupt):
        sys.stderr.write("\ninterrupted\n")
        return EXIT_INTERRUPTED

    if isinstance(exc, SystemExit):
        code = exc.code
        if code is None:
            return EXIT_OK
        if isinstance(code, int):
            return code
        sys.stderr.write(str(code))
        return EXIT_USAGE

    names = {klass.__name__ for klass in type(exc).__mro__}

    if "Abort" in names:
        return EXIT_INTERRUPTED
    if "Exit" in names:
        return int(getattr(exc, "exit_code", 0) or 0)
    if "UsageError" in names or "BadParameter" in names:
        unknown = _unknown_command(exc)
        if unknown is not None:
            _show_alternatives(unknown)
            return EXIT_UNKNOWN_MODULE
        _show_click(exc)
        return int(getattr(exc, "exit_code", EXIT_USAGE) or EXIT_USAGE)
    if "ClickException" in names:
        _show_click(exc)
        return int(getattr(exc, "exit_code", EXIT_RUNTIME) or EXIT_RUNTIME)
    return None


_NO_SUCH_COMMAND = re.compile(r"No such command (['\"])(?P<name>.+?)\1")


def _unknown_command(exc: BaseException) -> str | None:
    """The token click refused, when the refusal means "no such module"."""
    match = _NO_SUCH_COMMAND.search(str(exc))
    return match.group("name") if match else None


def _plain(value: object) -> str:
    """Dynamic text destined for the console, printed as written.

    An error message quotes what the user typed - a URL, a path, a module name. Rich
    reads the `[...]` inside those as style tags and deletes them, and a cp1252 console
    raises UnicodeEncodeError on a name it cannot encode, so the report would no longer
    match the thing that failed. Both are closed here.

    Line by line, because `encode_safe` is a one-line function on purpose: a message we
    authored with a line break in it (`module 'x' needs psutil\n install it with: ...`)
    would otherwise reach the screen as literal `\x0a` text.
    """
    from rich.markup import escape

    from .terminal import encode_safe

    return "\n".join(escape(encode_safe(line)) for line in str(value).splitlines())


def _show_alternatives(name: str) -> None:
    from . import registry as registry_module
    from .terminal import new_console

    try:
        names = sorted(m.name for m in registry_module.active().manifests())
    except Exception:
        return
    console = new_console(stderr=True, highlight=False)
    console.print(f"[bold red]unknown command:[/bold red] {_plain(name)}")
    console.print("available: " + ", ".join(f"[cyan]{_plain(n)}[/cyan]" for n in names))
    console.print("[dim]`levix -h` lists every command and option.[/dim]")


def _show_click(exc: BaseException) -> None:
    try:
        exc.show()  # type: ignore[attr-defined]
    except Exception:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")


def _report_unexpected(exc: BaseException, args: list[str]) -> int:
    import traceback

    from .terminal import new_console

    # Logging is a courtesy here. If the logger itself raises, the user still has to get
    # the report on stderr, which is the only reason this function exists.
    with contextlib.suppress(Exception):
        get_logger().error(
            "command %s failed: %s: %s",
            " ".join(args),
            type(exc).__name__,
            exc,
            exc_info=True,
        )

    console = new_console(stderr=True, highlight=False)
    console.print(
        f"[bold red]unexpected error:[/bold red] {_plain(type(exc).__name__)}: {_plain(exc)}"
    )
    console.print(
        "[dim]This is a LEVIX bug. `levix doctor` reports the environment; the traceback "
        "tail is below.[/dim]"
    )
    console.print(_plain("".join(traceback.format_exception(exc))[-1500:]), style="dim red", end="")
    return EXIT_RUNTIME


def _render_error(exc: LevixError) -> None:
    from .terminal import new_console

    console = new_console(stderr=True, highlight=False)
    console.print(f"[bold red]error:[/bold red] {_plain(exc.message)}")
    if exc.hint and exc.hint not in exc.message:
        console.print(f"[dim]hint:[/dim] {_plain(exc.hint)}")


def _record(obj: Any, argv: tuple[str, ...], exit_code: int, duration_ms: float) -> None:
    """Best-effort history. Failing to record must never fail the user's command."""
    if obj is None or not argv or argv[0].startswith("-"):
        return
    try:
        limit = int(obj.value("general.history_limit"))
        obj.database.apply_migrations(("core",))
        obj.database.log_command(argv, argv[0], exit_code, duration_ms)
        obj.database.prune_history(limit)
    except Exception:
        with contextlib.suppress(Exception):
            obj.logger.debug("command history not recorded", exc_info=True)

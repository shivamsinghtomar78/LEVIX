"""The one confirmation gate, used by `levix files` deletes and AI command proposals.

Both cases need the same property: nothing destructive or externally-influenced
happens unless a human said so. Sharing it means the AI module cannot accidentally
invent a weaker prompt than the file module.

Non-interactive stdin is treated as a refusal, not as consent.
"""

from __future__ import annotations

import sys

from rich.console import Console

from .errors import UserCancelledError

_ERR = Console(stderr=True)


def require_approval(
    action: str,
    detail: str,
    *,
    assume_yes: bool = False,
    destructive: bool = False,
    prompt_word: str | None = None,
) -> None:
    """Raise UserCancelledError (exit 6) unless the user agrees.

    `assume_yes` is only honoured for non-destructive actions; a `--yes` flag must
    never silently authorize a delete.
    """
    if destructive and assume_yes:
        _ERR.print(
            "[yellow]--yes cannot authorize a destructive action; confirming interactively."
            "[/yellow]"
        )
        assume_yes = False

    if assume_yes:
        return

    if not sys.stdin.isatty():
        msg = (
            f"refusing to {action} without a terminal to confirm in: {detail}\n"
            "  pass --yes for a non-destructive action, or run this interactively"
        )
        raise UserCancelledError(msg)

    expected = prompt_word or ("DELETE" if destructive else "yes")
    _ERR.print(f"[bold cyan]?[/bold cyan] {action}: [white]{detail}[/white]")
    try:
        answer = input(f"  type '{expected}' to continue (anything else aborts) > ").strip()
    except EOFError as exc:
        raise UserCancelledError(f"no input available; {action} aborted") from exc

    if answer.casefold() != expected.casefold():
        raise UserCancelledError(f"{action} cancelled by user")

"""Redaction: the one security promise that lives in a log line.

`logging_setup`'s module docstring says a log file that captures an API key is a security
bug, not a formatting bug, and that putting the redaction in a filter means a module cannot
walk around it by logging a formatted exception. Until now the only evidence for that was
the reading of it. These tests are the difference between a design that says it hides
credentials and one that has been shown to.

The file-handler test closes its handlers itself, because an open handle is what makes Windows
fail to delete the temporary directory (`tests/conftest.py` therefore turns file logging off
for the whole suite). The penultimate test attaches a handler with no filter on purpose,
because the promise being tested is the one attached to the *logger*. The last one is NFR-5.4
rather than NFR-5.3: stdout belongs to Rich and Textual, so the only handler allowed to reach a
terminal is a stderr one.
"""

from __future__ import annotations

import io
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from levix import logging_setup
from levix.logging_setup import RedactFilter

BEARER = "Authorization: Bearer sk-proj-3nK9d8s7a6f5g4h3j2k1"
API_KEY = "levix ai called with api_key=sk-live-9f8e7d6c5b4a"
# S105 reads the assignment as a password in source. These are invented strings whose only
# job is to be unmistakable in a failure message.
GH_TOKEN = "pull request used ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"  # noqa: S105


@pytest.fixture
def clean_logger() -> Iterator[logging.Logger]:
    """Hand back the shared `levix` logger with no handlers left open afterwards."""
    logger = logging_setup.get_logger()
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.filters.clear()


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        (BEARER, "sk-proj-3nK9d8s7a6f5g4h3j2k1"),
        (API_KEY, "sk-live-9f8e7d6c5b4a"),
        (GH_TOKEN, "ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"),
        ("retrying, password=hunter2! again", "hunter2!"),
        ("provider refused refresh_token=rt-4411-9933-x as expired", "rt-4411-9933-x"),
        ("saved client_secret: csec-77aa33bb99cc for the webhook", "csec-77aa33bb99cc"),
    ],
)
def test_each_shape_a_credential_takes_is_removed(line: str, secret: str) -> None:
    redacted = RedactFilter.redact(line)
    assert secret not in redacted, f"{secret!r} survived redaction"
    assert "***" in redacted, "redaction must be visible, not silent deletion"


def test_ordinary_text_survives_untouched() -> None:
    """The filter is a redactor, not a scrub-all: a message that loses its words is useless."""
    plain = "files delete: removed 3 entries from C:\\Users\\me\\project, reclaiming 1.2 KiB"
    assert RedactFilter.redact(plain) == plain


def test_the_filter_keeps_the_record_and_rewrites_the_formatted_message() -> None:
    """`filter()` always returns True - suppression would hide the fact that a command ran."""
    record = logging.LogRecord(
        name="levix",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="%s",
        args=(BEARER,),
        exc_info=None,
    )
    filter_ = RedactFilter()
    assert filter_.filter(record) is True
    printed = record.getMessage()
    assert "sk-proj-3nK9d8s7a6f5g4h3j2k1" not in printed
    assert "Authorization: Bearer ***" in printed, "the shape of the retry must stay readable"


def test_a_key_never_reaches_the_log_file(tmp_path: Path, clean_logger: logging.Logger) -> None:
    """The promise in one line: what the command logged is not what the file holds."""
    log_dir = tmp_path / "logs"
    logger = logging_setup.setup(log_dir, level="info", file_enabled=True, quiet=True)
    try:
        logger.warning("retrying the provider: %s", BEARER)
        logger.error(API_KEY)
        logger.info("looking for %s in the manifest", GH_TOKEN)
        for handler in logger.handlers:
            handler.flush()
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    written = (log_dir / "levix.log").read_text(encoding="utf-8")
    for secret in ("sk-proj-3nK9d8s7a6f5g4h3j2k1", "sk-live-9f8e7d6c5b4a", "ghp_a1b2c3d4e5f6"):
        assert secret not in written, f"the log file holds {secret!r}"
    assert written.count("***") == 3, f"three redactions expected, got:\n{written}"
    assert "retrying the provider" in written, "the event must still be diagnosable"


def test_a_handler_without_a_filter_still_gets_redacted(
    tmp_path: Path, clean_logger: logging.Logger
) -> None:
    """A module that adds its own handler cannot bypass the redaction.

    This is the claim in the module docstring, and it holds only because `setup()` attaches
    the filter to the logger as well as to the handlers it makes. A handler built here has no
    filter at all.
    """
    sink = io.StringIO()
    logger = logging_setup.setup(tmp_path, level="info", file_enabled=False, quiet=True)
    bare = logging.StreamHandler(sink)
    bare.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(bare)
    logger.warning("falling back to %s", API_KEY)
    emitted = sink.getvalue()
    assert "sk-live-9f8e7d6c5b4a" not in emitted
    assert "api_key=***" in emitted


def test_the_only_console_handler_writes_to_stderr(
    tmp_path: Path, clean_logger: logging.Logger
) -> None:
    """NFR-5.4: stdout belongs to Rich and Textual, so a log line must never land there."""
    logger = logging_setup.setup(tmp_path, level="info", file_enabled=False, quiet=False)
    assert len(logger.handlers) == 1, "the fallback handler is added only when there is none"
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert handler.level == logging.WARNING, "info and debug stay off the terminal"

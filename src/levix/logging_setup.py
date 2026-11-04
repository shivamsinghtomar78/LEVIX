"""Structured logging with redaction.

A log file that captures an API key is a security bug, not a formatting one, so
redaction happens in a filter attached to the logger - it cannot be bypassed by a
module that logs a formatted exception containing a bearer token.

Nothing is written to stdout: LEVIX renders human output through Rich and Textual,
and interleaved log lines would corrupt both.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "levix"

_PATTERNS = (
    # bearer / api keys that look like tokens
    re.compile(r"(?i)\b(authorization\s*[:=]\s*bearer\s+)[a-z0-9._\-]+"),
    re.compile(r"(?i)\b(sk-[a-z0-9_\-]{6,})\b"),
    re.compile(r"(?i)\b(ghp_|gho_|github_pat_)[a-z0-9_\-]{8,}"),
    # key=value pairs where the key smells secret
    re.compile(r"(?i)\b([a-z_]*(?:api[_-]?key|token|secret|password)[a-z_]*)\s*[:=]\s*\S+"),
)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True

    @staticmethod
    def redact(text: str) -> str:
        out = text
        out = _PATTERNS[0].sub(r"\1***", out)
        out = _PATTERNS[1].sub("***", out)
        out = _PATTERNS[2].sub("***", out)
        out = _PATTERNS[3].sub(r"\1=***", out)
        return out


def setup(
    log_dir: Path,
    *,
    level: str = "info",
    file_enabled: bool = True,
    quiet: bool = False,
) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    redactor = RedactFilter()
    if file_enabled:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_dir / "levix.log", maxBytes=512_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-8s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"
                )
            )
            handler.addFilter(redactor)
            logger.addHandler(handler)
        except OSError:
            # A machine we cannot write logs to must still run the command.
            if not quiet:
                logger.warning("could not open log file in %s", log_dir)

    if not logger.handlers and not quiet:
        stream = logging.StreamHandler()
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        stream.addFilter(redactor)
        logger.addHandler(stream)

    logger.addFilter(redactor)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)

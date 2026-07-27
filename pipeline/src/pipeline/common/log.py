"""Secret-redacting logger.

Every workflow log is public on a public repo, so a leaked key is leaked to
everyone. Redaction happens at the sink rather than at each call site, because
relying on every future caller to remember is how keys escape.
"""

from __future__ import annotations

import logging
import os
import re
import sys

# Values registered here are masked anywhere they appear in a log record.
_SECRETS: set[str] = set()

_PATTERNS = [
    re.compile(r"\bapikey=[^&\s]+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
]

_ENV_KEYS_TO_REDACT = ("TICKETMASTER_API_KEY",)


def register_secret(value: str | None) -> None:
    # Short values would mask harmless substrings across unrelated output.
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    for secret in _SECRETS:
        text = text.replace(secret, "«redacted»")
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split("=")[0] + "=«redacted»" if "=" in m.group(0) else "«redacted»", text)
    return text


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure(level: int = logging.INFO) -> None:
    for key in _ENV_KEYS_TO_REDACT:
        register_secret(os.environ.get(key))

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_RedactingFormatter("%(levelname)-7s %(name)s  %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

"""Logging filter that redacts the QR-code auth password from log records.

The startup banner advertises a URL of the form ``http://host:port/?auth=<pw>``
so phones can scan a QR code and authenticate without typing. uvicorn's
access logger writes the request line verbatim, which means the password
ends up in stdout and in any file/journal handler the operator wires up.
This filter rewrites ``auth=<value>`` to ``auth=<redacted>`` on the way out.
"""

from __future__ import annotations

import logging
import re

_AUTH_PATTERN = re.compile(r"(auth=)([^\s&\"'`<>]+)", re.IGNORECASE)
_REDACTED = r"\1<redacted>"


def redact(text: str) -> str:
    """Return ``text`` with any ``auth=<value>`` parameter redacted."""
    return _AUTH_PATTERN.sub(_REDACTED, text)


def _redact_arg(value: object) -> object:
    """Recursively redact ``auth=`` occurrences inside log args.

    uvicorn's ``AccessFormatter`` expects ``record.args`` to retain its
    original tuple/dict shape, so we mutate the contents in place rather
    than collapsing the record down to a pre-formatted string.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, tuple):
        return tuple(_redact_arg(v) for v in value)
    if isinstance(value, list):
        return [_redact_arg(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_arg(v) for k, v in value.items()}
    return value


class RedactAuthFilter(logging.Filter):
    """Strip the ``auth=`` query parameter from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = _redact_arg(record.args)  # type: ignore[assignment]
        return True

"""
A logging filter that redacts credentials from log records.

Belt and braces. `SensitiveDataRedactionService` sanitises ticket content on the way in,
but a stray `logger.debug(payload)` added during a late-night fix is exactly how a token
ends up in a log aggregator. This filter runs on every record on every handler, so a
mistake of that kind is contained by default rather than by discipline.

It is intentionally cheap and pattern-based — it cannot catch everything, and it is not a
substitute for not logging secrets in the first place.
"""

from __future__ import annotations

import logging
import re

_REPLACEMENT = "[REDACTED]"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # key=value / "key": "value" for anything named like a secret
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|pwd|authorization|"
            r"auth|credential|private[_-]?key|access[_-]?key|secret[_-]?key|bearer)"
            r"(\"?\s*[:=]\s*\"?)([^\s,;\"'}\)]{4,})"
        ),
        r"\1\2" + _REPLACEMENT,
    ),
    # Authorization: Bearer <jwt-ish>
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer " + _REPLACEMENT),
    # AWS access key ids and long AWS-ish secrets
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), _REPLACEMENT),
    # PEM private key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        _REPLACEMENT,
    ),
    # Credentials embedded in a URL: scheme://user:pass@host
    (re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^:/\s]+:)[^@/\s]+(@)"), r"\1" + _REPLACEMENT + r"\2"),
    # JWTs appearing bare
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), _REPLACEMENT),
)


def redact(text: str) -> str:
    """Apply every redaction pattern to `text`."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites `record.msg` and `record.args` through `redact()`."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        redact(a) if isinstance(a, str) else a for a in record.args
                    )
        except Exception:  # pragma: no cover - a filter must never break logging
            return True
        return True

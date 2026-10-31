"""
SensitiveDataRedactionService.

Runs **before** ticket text is stored, before it is embedded, and before it is sent to any
LLM provider. There is no "raw" column anywhere in this product: the original submission is
redacted in memory and the original is discarded.

Why this is the first service in the pipeline: customers paste logs. Logs contain
`AWS_SECRET_ACCESS_KEY`, bearer tokens, JDBC URLs with passwords, and private keys. Once
such a value is persisted it is in backups, in read replicas, in the embedding, and
potentially in a third-party model provider's request log. The only reliable fix is to
never accept it.

Design choices worth defending:

* **Pattern-based, not model-based.** Redaction must be deterministic, auditable and
  offline. Sending text to a model *in order to decide what to hide from the model* is
  circular.
* **Reports what it did.** `RedactionResult.summary` is surfaced to the submitter, so
  redaction is visible rather than silent. A user who sees "2 access keys removed" learns
  something; a user whose text is quietly altered loses trust.
* **Preserves diagnostic value.** Placeholders keep the shape of the data
  (`[REDACTED:AWS_ACCESS_KEY]`, `[REDACTED:IPV4]`) so the surrounding error remains
  readable and still matches other tickets. Replacing everything with `***` would destroy
  the retrieval signal this whole product depends on.
* **Conservative on entropy.** The high-entropy catch-all only fires on long
  mixed-character tokens that are not recognisable identifiers, because over-redaction of
  stack traces and table names would be its own failure.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from re import Pattern


@dataclass
class RedactionResult:
    text: str
    summary: dict[str, int] = field(default_factory=dict)

    @property
    def redaction_count(self) -> int:
        return sum(self.summary.values())

    @property
    def was_redacted(self) -> bool:
        return self.redaction_count > 0

    def describe(self) -> str:
        """Human-readable sentence for the UI."""
        if not self.was_redacted:
            return "No sensitive values were detected."
        parts = [
            f"{count} {_LABELS.get(kind, kind.lower().replace('_', ' '))}"
            + ("s" if count != 1 and not _LABELS.get(kind, "").endswith("s") else "")
            for kind, count in sorted(self.summary.items(), key=lambda kv: -kv[1])
        ]
        return "Redacted before storage: " + ", ".join(parts) + "."


_LABELS = {
    "AWS_ACCESS_KEY": "AWS access key",
    "AWS_SECRET": "AWS secret",
    "AZURE_STORAGE_KEY": "Azure storage key",
    "GCP_SERVICE_ACCOUNT_KEY": "GCP service-account key",
    "PRIVATE_KEY_BLOCK": "private key block",
    "JWT": "JSON web token",
    "BEARER_TOKEN": "bearer token",
    "BASIC_AUTH": "basic-auth header",
    "URL_CREDENTIALS": "credential embedded in a URL",
    "JDBC_PASSWORD": "JDBC password",
    "ASSIGNED_SECRET": "assigned secret value",
    "K8S_SECRET_DATA": "Kubernetes secret value",
    "EMAIL": "email address",
    "IPV4": "IPv4 address",
    "IPV6": "IPv6 address",
    "SLACK_TOKEN": "Slack token",
    "GITHUB_TOKEN": "GitHub token",
    "HIGH_ENTROPY_TOKEN": "high-entropy token",
}


def _placeholder(kind: str) -> str:
    return f"[REDACTED:{kind}]"


# Order matters: the most specific, highest-confidence patterns run first so that a value
# is attributed to the right category (and so a JWT is not first mangled by the generic
# key=value rule).
_RULES: tuple[tuple[str, Pattern[str]], ...] = (
    # --- Structured secrets, unambiguous -------------------------------------------
    (
        "PRIVATE_KEY_BLOCK",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
            r".*?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----",
            re.S,
        ),
    ),
    ("AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    (
        "AWS_SECRET",
        re.compile(
            r"(?i)\baws_?secret_?access_?key\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?"
        ),
    ),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "GCP_SERVICE_ACCOUNT_KEY",
        re.compile(r"(?i)\"private_key_id\"\s*:\s*\"[a-f0-9]{20,}\""),
    ),
    (
        "AZURE_STORAGE_KEY",
        re.compile(r"(?i)\baccountkey\s*=\s*[A-Za-z0-9/+=]{40,}"),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\b")),
    (
        "BEARER_TOKEN",
        re.compile(r"(?i)\b(?:authorization\s*[:=]\s*)?bearer\s+([A-Za-z0-9._\-~+/]{12,}=*)"),
    ),
    ("BASIC_AUTH", re.compile(r"(?i)\bauthorization\s*[:=]\s*basic\s+([A-Za-z0-9+/]{12,}=*)")),
    # --- Credentials in connection strings -----------------------------------------
    # scheme://user:password@host — keeps the user and host, drops the password, because
    # "connecting as iomete_app to postgres.internal" is diagnostically useful.
    (
        "URL_CREDENTIALS",
        re.compile(r"(?P<pre>\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:)(?P<secret>[^\s@/]{1,200})(?P<post>@)"),
    ),
    (
        "JDBC_PASSWORD",
        re.compile(r"(?i)\b(?:password|pwd|passwd)\s*=\s*(?P<secret>[^;,\s&\"']{1,200})"),
    ),
    # --- Kubernetes secret payloads -------------------------------------------------
    # `kubectl get secret -o yaml` output: base64 values under `data:`.
    (
        "K8S_SECRET_DATA",
        re.compile(
            r"(?m)^(?P<pre>\s{2,}[A-Za-z0-9._\-]+:\s*)(?P<secret>[A-Za-z0-9+/]{24,}={0,2})\s*$"
        ),
    ),
    # --- Generic assignment of anything named like a secret -------------------------
    (
        "ASSIGNED_SECRET",
        re.compile(
            r"(?i)\b(?P<key>api[_-]?key|apikey|access[_-]?key|secret[_-]?key|secret|token|"
            r"credential|client[_-]?secret|auth[_-]?token|private[_-]?key|sas[_-]?token|"
            r"connection[_-]?string)\b"
            r"(?P<sep>\"?\s*[:=]\s*\"?)"
            r"(?P<secret>[^\s,;\"'}\)\]]{6,200})"
        ),
    ),
    # --- Personal / network identifiers ---------------------------------------------
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (
        "IPV4",
        # Excludes loopback and the unspecified address, which carry no PII and are often
        # the diagnostically important part ("binding to 0.0.0.0 failed").
        re.compile(
            r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)"
            r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
        ),
    ),
    ("IPV6", re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){4,7}[A-Fa-f0-9]{1,4}\b")),
)

# Tokens that look high-entropy but must survive: they are the retrieval signal.
_ENTROPY_ALLOWLIST = re.compile(
    r"(?i)^(?:"
    r"[a-z0-9_.\-]*(?:exception|error|failure|warning|timeout|denied|killed|backoff)[a-z0-9_.\-]*"
    r"|(?:org|com|java|io|scala|net|sun)\..*"
    r"|[a-f0-9]{7,40}"              # git sha / short hash — useful, not secret
    r"|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"  # UUID — identifier, not credential
    r"|v?\d+(?:\.\d+)*(?:[-_][a-z0-9]+)?"           # version strings
    r")$"
)

_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _looks_like_secret(token: str) -> bool:
    """
    Heuristic for the catch-all pass.

    Requires high entropy *and* mixed character classes *and* absence from the allowlist.
    Three conditions rather than one because the cost of over-redaction here is a
    destroyed stack trace, which breaks retrieval — the thing this pipeline exists to make
    work.
    """
    if _ENTROPY_ALLOWLIST.match(token):
        return False
    if _shannon_entropy(token) < 3.6:
        return False
    classes = sum(
        bool(re.search(pattern, token))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[+/=_\-]")
    )
    return classes >= 3


def redact(text: str | None, *, redact_emails: bool = True,
           redact_ips: bool = True) -> RedactionResult:
    """
    Redact `text`, returning the cleaned text and a summary of what was removed.

    `redact_emails` / `redact_ips` exist because an internal FDE note may legitimately need
    to name a colleague, while customer-submitted content never should. Callers that handle
    customer input must leave both at their defaults.
    """
    if not text:
        return RedactionResult(text="", summary={})

    summary: Counter[str] = Counter()
    out = text

    for kind, pattern in _RULES:
        if kind == "EMAIL" and not redact_emails:
            continue
        if kind in {"IPV4", "IPV6"} and not redact_ips:
            continue

        def _sub(match: re.Match[str], _kind: str = kind) -> str:
            groups = match.groupdict()

            # Redaction must be idempotent. Several patterns match on structure around the
            # secret (`user:SECRET@host`, `key=SECRET`), so a placeholder left by an earlier
            # pass sits exactly where a secret would and matches again. Without this guard,
            # re-scanning redacted text reports phantom findings — which would make
            # `assert_redacted()` and the DEBUG guard in the LLM layer cry wolf on text that
            # is already clean.
            if "[REDACTED:" in match.group(0):
                return match.group(0)

            summary[_kind] += 1
            if "secret" in groups and groups["secret"] is not None:
                # Rebuild the match, replacing only the secret group so surrounding
                # context (the key name, the username, the host) stays readable.
                prefix = match.group(0)[: match.start("secret") - match.start(0)]
                suffix = match.group(0)[match.end("secret") - match.start(0):]
                return f"{prefix}{_placeholder(_kind)}{suffix}"
            if _kind in {"BEARER_TOKEN", "BASIC_AUTH"} and match.lastindex:
                whole = match.group(0)
                token = match.group(match.lastindex)
                return whole.replace(token, _placeholder(_kind))
            if _kind == "AWS_SECRET" and match.lastindex:
                return match.group(0).replace(
                    match.group(match.lastindex), _placeholder(_kind)
                )
            return _placeholder(_kind)

        out = pattern.sub(_sub, out)

    # Catch-all entropy pass, last, over whatever survived.
    def _entropy_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("[REDACTED:"):
            return token
        if _looks_like_secret(token):
            summary["HIGH_ENTROPY_TOKEN"] += 1
            return _placeholder("HIGH_ENTROPY_TOKEN")
        return token

    out = _HIGH_ENTROPY.sub(_entropy_sub, out)

    return RedactionResult(text=out, summary=dict(summary))


def redact_many(values: Iterable[str | None], **kwargs) -> tuple[list[str], dict[str, int]]:
    """Redact several fields, returning the cleaned values and one combined summary."""
    cleaned: list[str] = []
    combined: Counter[str] = Counter()
    for value in values:
        result = redact(value, **kwargs)
        cleaned.append(result.text)
        combined.update(result.summary)
    return cleaned, dict(combined)


def assert_redacted(text: str) -> None:
    """
    Test/assert helper: raise if `text` still contains anything we know how to detect.

    Used by `aiengine/tests/test_redaction.py` and by the embedding service as a
    development-time guard, so a new code path that forgets to redact fails loudly instead
    of silently shipping a secret into a vector store.
    """
    result = redact(text)
    if result.was_redacted:
        raise AssertionError(
            "Text was not redacted before use. Detected: "
            + ", ".join(f"{k}×{v}" for k, v in result.summary.items())
        )

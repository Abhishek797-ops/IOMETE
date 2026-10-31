"""
ErrorFingerprintService.

An error fingerprint is a stable hash of *what went wrong*, with everything
customer-specific stripped out. It is the strongest retrieval channel in COMPASS, because
two tickets sharing a fingerprint are reporting the same error — which is far better
evidence than two tickets whose prose happens to read alike.

The art is in the templating. These two lines must produce the same fingerprint::

    Executor 7 on 10.4.19.22 killed: OOMKilled (exit 137) after 1h14m
    Executor 23 on 10.4.19.81 killed: OOMKilled (exit 137) after 42m

and must *not* collide with::

    Executor 7 killed: Evicted (DiskPressure)

So numbers, pod names, UUIDs, timestamps, paths and quoted literals are masked; the error
tokens and the structural words are kept.

What a fingerprint is **not**: proof of a shared root cause. `OOMKilled` has at least four
distinct causes (executor memory too low, skewed partition, a memory leak in a UDF, a
node-level limit). That is why the fingerprint feeds `similarity` strongly but
`diagnosis_confidence` only partially, and why an `IssueCluster` built on fingerprints is
explicitly a hypothesis until an FDE confirms it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from tickets.models import ErrorFingerprint, TicketComponent

FINGERPRINT_VERSION = "v1"

# ---------------------------------------------------------------------------------------
# Templating: mask the variable, keep the structural.
# ---------------------------------------------------------------------------------------

_MASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Already-redacted placeholders collapse to one token so they do not fragment hashes.
    (re.compile(r"\[REDACTED:[A-Z_0-9]+\]"), "<R>"),
    # ISO timestamps and common log timestamps
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+\-]\d{2}:?\d{2})?"), "<TS>"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<TS>"),
    # Durations, including compound forms. `1h14m` and `42m` must collapse to the same
    # token, so the unit is allowed to be followed immediately by another number — a
    # simple `\b`-terminated pattern silently fails on `1h14m` and lets the duration
    # leak into the digest, which makes two reports of the same error hash differently.
    (
        re.compile(
            r"\b(?:\d+(?:\.\d+)?\s*(?:ms|us|ns|sec(?:s|onds)?|min(?:s|utes)?|hr(?:s)?|"
            r"hours?|days?|[smhdw])\s*)+",
            re.I,
        ),
        "<DUR> ",
    ),
    # Byte sizes: 4.2GiB, 512Mi, 1024MB, 12g
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:[KMGTP]i?[Bb]?|bytes)\b", re.I), "<SIZE>"),
    # UUIDs
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
    # Long hex blobs / shas
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<HEX>"),
    # Kubernetes resource names with generated suffixes:
    # spark-app-7f9c4d-exec-12, iom-core-5d8b7c9f4-xk2mp
    (re.compile(r"\b([a-z][a-z0-9\-]*?)-(?:[a-z0-9]{5,10})-(?:[a-z0-9]{4,6})\b"), r"\1-<POD>"),
    (re.compile(r"\b([a-z][a-z0-9\-]*?)-exec(?:utor)?-\d+\b"), r"\1-exec-<N>"),
    # Object storage URIs: keep the scheme, drop bucket and path
    (re.compile(r"\b(s3a?|gs|wasbs?|abfss?|hdfs|file)://[^\s\"',)]+", re.I), r"\1://<PATH>"),
    # Filesystem paths
    (re.compile(r"(?:/[\w.\-]+){2,}/?"), "<PATH>"),
    # Quoted literals — table names, column names, user names
    (re.compile(r"'[^']{1,120}'"), "<LIT>"),
    (re.compile(r"\"[^\"]{1,120}\""), "<LIT>"),
    (re.compile(r"`[^`]{1,120}`"), "<LIT>"),
    # Hostnames and ports
    (re.compile(r"\b[\w\-.]+\.(?:svc|cluster|local|internal|com|net|io)\b(?::\d+)?"), "<HOST>"),
    (re.compile(r":\d{2,5}\b"), ":<PORT>"),
    # Bare numbers last, so the patterns above get first refusal
    (re.compile(r"\b\d+\b"), "<N>"),
)

_COLLAPSE_WS = re.compile(r"\s+")
_STRIP_PUNCT = re.compile(r"[^\w<>:./\-\s]")


def templatize(text: str, *, max_chars: int = 600) -> str:
    """
    Reduce an error string to its invariant template.

    Truncated because a 400-line stack trace's tail is mostly framework frames that differ
    between runs; the first few hundred characters carry the identity.
    """
    if not text:
        return ""
    out = text
    for pattern, replacement in _MASKS:
        out = pattern.sub(replacement, out)
    out = _STRIP_PUNCT.sub(" ", out)
    out = _COLLAPSE_WS.sub(" ", out).strip().lower()
    return out[:max_chars]


@dataclass(frozen=True)
class Fingerprint:
    digest: str
    signature: str
    error_codes: list[str]
    key_phrases: list[str]
    component: str
    #: Low-signal fingerprints (no error codes at all) are flagged so ranking can discount
    #: them. Without this, every vague "my query is slow" ticket fingerprints alike and the
    #: strongest channel starts producing the weakest matches.
    is_low_signal: bool


def compute(
    *,
    error_codes: list[str] | None,
    error_message: str = "",
    title: str = "",
    component: str = TicketComponent.OTHER,
    key_phrases: list[str] | None = None,
) -> Fingerprint:
    """
    Compute a fingerprint from normalised ticket features.

    The signature is `version | component | sorted error codes | templated error text`.
    Component is included because `HTTP:403` from the Iceberg REST catalog and `HTTP:403`
    from object storage are different problems with different fixes.
    """
    codes = sorted(set(error_codes or []))
    # Prefer the error message for templating; fall back to the title when a submitter
    # pasted no error at all.
    body = templatize(error_message or title)

    signature = " | ".join(
        [
            FINGERPRINT_VERSION,
            component or TicketComponent.OTHER,
            ",".join(codes) or "no-codes",
            body or "no-body",
        ]
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()

    return Fingerprint(
        digest=digest,
        signature=signature,
        error_codes=codes,
        key_phrases=list(key_phrases or [])[:12],
        component=component or TicketComponent.OTHER,
        is_low_signal=not codes,
    )


def digest_prefix(digest: str, length: int = 16) -> str:
    """
    Prefix used for near-match lookups.

    Exact digests are brittle: a ticket whose error line is phrased slightly differently
    hashes to something completely different. The prefix alone would not help (hashing
    destroys locality), so prefix matching is only used to group *identical* signatures
    recorded under different versions. Fuzzy matching is the vector and lexical channels'
    job — the fingerprint channel is deliberately exact, which is what makes it
    high-precision.
    """
    return digest[:length]


@transaction.atomic
def record(fingerprint: Fingerprint, *, organization_id=None) -> ErrorFingerprint:
    """
    Persist or update the `ErrorFingerprint` row and bump its counters.

    `distinct_organization_count` is maintained as an aggregate only. We deliberately do
    not store *which* organizations hit a fingerprint on this global row: the count is what
    makes a cluster interesting ("six tenants, not one"), and the identities would be a
    cross-tenant leak sitting in a table with no tenant scoping.
    """
    row, _created = ErrorFingerprint.objects.select_for_update().get_or_create(
        digest=fingerprint.digest,
        defaults={
            "signature": fingerprint.signature,
            "error_codes": fingerprint.error_codes,
            "key_phrases": fingerprint.key_phrases,
            "component": fingerprint.component,
            "occurrence_count": 0,
            "distinct_organization_count": 0,
        },
    )
    ErrorFingerprint.objects.filter(pk=row.pk).update(
        occurrence_count=F("occurrence_count") + 1,
        last_seen_at=timezone.now(),
    )
    if organization_id is not None:
        # Recomputed from tickets rather than incremented, so a second ticket from the
        # same tenant does not inflate the figure.
        from tickets.models import Ticket

        distinct = (
            Ticket.objects.filter(fingerprint=row)
            .values("organization_id")
            .distinct()
            .count()
        )
        # +1 for the ticket currently being created, which is not yet linked.
        already_counted = Ticket.objects.filter(
            fingerprint=row, organization_id=organization_id
        ).exists()
        ErrorFingerprint.objects.filter(pk=row.pk).update(
            distinct_organization_count=distinct + (0 if already_counted else 1)
        )
    row.refresh_from_db()
    return row


def overlap_score(left: Fingerprint | ErrorFingerprint, right: ErrorFingerprint) -> float:
    """
    Graded similarity between two fingerprints, 0.0–1.0.

    Exact digest match is 1.0. Otherwise it is the Jaccard overlap of error codes, with a
    component agreement bonus — so `NoSuchTableException` in two Iceberg tickets scores
    well even when the surrounding text differs, while the same code in different
    components is discounted.
    """
    if left.digest == right.digest:
        return 1.0
    left_codes = set(left.error_codes or [])
    right_codes = set(right.error_codes or [])
    if not left_codes or not right_codes:
        return 0.0
    intersection = left_codes & right_codes
    if not intersection:
        return 0.0
    jaccard = len(intersection) / len(left_codes | right_codes)
    component_bonus = 0.15 if left.component == right.component else -0.10
    return max(0.0, min(0.95, jaccard + component_bonus))

"""
HybridRetrievalService.

Four recall channels, fused with weighted Reciprocal Rank Fusion:

| Channel     | Mechanism                                                     | Weight |
| ----------- | ------------------------------------------------------------- | ------ |
| vector      | pgvector `<=>` cosine on Postgres, numpy cosine otherwise      | 1.0    |
| lexical     | `websearch_to_tsquery` + `ts_rank` on Postgres, BM25-ish else  | 0.9    |
| fingerprint | exact digest match, then error-code Jaccard                    | 1.4    |
| metadata    | component / category / environment / symptom structured match  | 0.6    |

Why fusion rather than one score: the channels fail in different directions. Vector search
finds paraphrases but is fooled by surface similarity. Lexical search nails exact error
strings but misses "pods keep dying" vs "executors terminating". Fingerprints are
high-precision and low-recall. Metadata is low-precision and high-recall. RRF combines
*ranks*, not scores, so one channel's badly-scaled score cannot swamp the others — which
is exactly the failure mode of a naive weighted-sum of raw similarities.

The fingerprint channel carries the highest weight because an exact shared error code is
the strongest evidence available in support search, and the thing a human engineer would
look for first.

**Tenant scoping happens inside every channel, including the raw SQL ones.** This is the
highest-severity risk in the module: a retrieval query that forgets the organization
predicate leaks one customer's incident history to another. `Ticket.objects.for_user()` is
applied first and its primary keys constrain every channel, so there is one place to audit.
Note what that means for a customer: their similar-ticket search returns *their own*
history. Cross-customer learning reaches them through approved, FDE-redacted playbooks —
which is the only sanctioned path across the boundary.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q

from tickets.models import ErrorFingerprint, Ticket

from . import embedding as embedding_service
from . import fingerprint as fingerprint_service

logger = logging.getLogger("compass.retrieval")

VECTOR_TABLE = "aiengine_vector_index"


# =======================================================================================
# Vector backend detection
# =======================================================================================


@lru_cache(maxsize=1)
def _pgvector_available() -> tuple[bool, str]:
    """
    Is the pgvector-backed index actually usable right now?

    Checked at runtime rather than assumed from settings, because every step can fail
    independently: the database may not be Postgres, the extension may not be installed
    (it needs privileges the app user may not have), or the migration may have skipped.
    Reporting "pgvector" when the query will actually run in numpy would be exactly the
    kind of quiet dishonesty this product is built to avoid.
    """
    if not settings.USE_PGVECTOR:
        return False, "USE_PGVECTOR is disabled; using the portable numpy backend."
    if connection.vendor != "postgresql":
        return False, (
            f"Database vendor is {connection.vendor!r}, not PostgreSQL. Vector search runs "
            "in numpy, which is correct and fast at demo scale."
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            if cursor.fetchone() is None:
                return False, (
                    "The pgvector extension is not installed in this database. Run "
                    "`CREATE EXTENSION vector;` as a superuser, then `manage.py reembed`."
                )
            cursor.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
                [VECTOR_TABLE],
            )
            if cursor.fetchone() is None:
                return False, (
                    f"The {VECTOR_TABLE} table is missing. Run `manage.py migrate`."
                )
    except Exception as exc:
        logger.warning("pgvector availability check failed: %s", exc)
        return False, f"pgvector availability check failed: {exc}"
    return True, "pgvector with an HNSW index over cosine distance."


def reset_backend_cache() -> None:
    """Clear the cached detection. Used by tests and by `reembed`."""
    _pgvector_available.cache_clear()


def describe_vector_backend() -> dict[str, object]:
    """Reported verbatim by `/api/v1/system/status/`."""
    available, reason = _pgvector_available()
    return {
        "vector_backend": "pgvector" if available else "numpy",
        "vector_backend_reason": reason,
        "embedding": embedding_service.describe_provider(),
    }


# =======================================================================================
# Query and result types
# =======================================================================================


@dataclass
class RetrievalQuery:
    """Everything the channels need. Built from a normalised, redacted ticket."""

    text: str = ""
    error_codes: list[str] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    component: str = ""
    category: str = ""
    iomete_version: str = ""
    environment: str = ""
    deployment_model: str = ""
    cloud_provider: str = ""
    embedding: list[float] | None = None
    fingerprint_digest: str = ""
    exclude_ticket_ids: list = field(default_factory=list)
    limit: int = 10

    def cache_key(self) -> str:
        payload = "|".join(
            [
                self.text[:2000],
                ",".join(sorted(self.error_codes)),
                ",".join(sorted(self.symptoms)),
                self.component,
                self.category,
                self.iomete_version,
                self.environment,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Candidate:
    object_id: str
    channel_scores: dict[str, float] = field(default_factory=dict)
    channel_ranks: dict[str, int] = field(default_factory=dict)
    fused_score: float = 0.0

    @property
    def channels_hit(self) -> list[str]:
        return sorted(self.channel_scores.keys())


@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    vector_backend: str
    vector_backend_reason: str
    channel_counts: dict[str, int]
    channel_weights: dict[str, float]
    candidate_count: int
    duration_ms: int
    tenant_scope_applied: bool
    scoped_pool_size: int
    embedding_provider: str
    embedding_model: str
    notes: list[str] = field(default_factory=list)


# =======================================================================================
# Channel implementations
# =======================================================================================


def _scoped_ticket_ids(user, *, exclude: Iterable = ()) -> list:
    """
    The tenant-scoped candidate pool.

    Every channel is constrained to these ids. Resolved once, here, so there is a single
    place to audit — and so the raw-SQL channels cannot drift from the ORM ones.

    Only *resolved* tickets are retrievable as historical precedent: an open ticket has no
    verified outcome to offer, and surfacing one as a "related solved issue" would be
    misleading. Escalated-but-unresolved tickets are excluded for the same reason.
    """
    queryset = (
        Ticket.objects.for_user(user)
        .filter(status__in=["resolved", "closed"])
        .exclude(resolution_summary="")
    )
    exclude_ids = [i for i in exclude if i]
    if exclude_ids:
        queryset = queryset.exclude(id__in=exclude_ids)
    return list(queryset.values_list("id", flat=True))


def _vector_channel(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """Cosine-similarity recall. pgvector when available, numpy otherwise."""
    if not query.embedding or not allowed_ids:
        return []

    available, _ = _pgvector_available()
    if available:
        try:
            return _vector_channel_pgvector(query, allowed_ids, limit=limit)
        except Exception:
            logger.exception(
                "pgvector query failed; falling back to numpy for this request so the "
                "search still returns results."
            )
            reset_backend_cache()
    return _vector_channel_numpy(query, allowed_ids, limit=limit)


def _vector_channel_pgvector(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    ANN search via pgvector.

    The organization predicate is applied *inside* the SQL through the `allowed_ids`
    parameter rather than by filtering the result set afterwards. Filtering after an ANN
    limit would both leak (the server computed over other tenants' rows) and silently
    return fewer results than asked for.
    """
    vector_literal = "[" + ",".join(f"{v:.6f}" for v in query.embedding) + "]"
    sql = f"""
        SELECT object_id::text, 1 - (embedding <=> %s::vector) AS similarity
        FROM {VECTOR_TABLE}
        WHERE object_type = 'ticket'
          AND object_id = ANY(%s::uuid[])
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [vector_literal, [str(i) for i in allowed_ids], vector_literal, limit],
        )
        rows = cursor.fetchall()
    return [(object_id, max(0.0, min(1.0, float(similarity)))) for object_id, similarity in rows]


def _vector_channel_numpy(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    Exact cosine over the scoped pool, in process.

    This is a full scan. At COMPASS's realistic scale — a support history of hundreds to a
    few thousand resolved tickets per tenant — it is both exact and faster than a network
    round trip to an ANN index. The pgvector path exists for the scale where that stops
    being true, and the API reports which one ran.
    """
    rows = (
        Ticket.objects.filter(id__in=allowed_ids)
        .exclude(embedding=None)
        .values_list("id", "embedding")
    )
    scored: list[tuple[str, float]] = []
    for ticket_id, vector in rows.iterator(chunk_size=500):
        score = embedding_service.cosine_similarity(query.embedding, vector)
        if score > 0:
            scored.append((str(ticket_id), score))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:limit]


_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.\-]{1,}")


def _lexical_channel(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    if not allowed_ids:
        return []
    terms = _lexical_terms(query)
    if not terms:
        return []
    if connection.vendor == "postgresql":
        try:
            return _lexical_channel_postgres(terms, allowed_ids, limit=limit)
        except Exception:
            logger.exception("Full-text query failed; falling back to portable scoring.")
    return _lexical_channel_portable(terms, allowed_ids, limit=limit)


def _lexical_terms(query: RetrievalQuery) -> list[str]:
    """
    Build the lexical query.

    Error codes come first and are repeated, because an exact error token is the single
    most discriminative term available. Key phrases follow. Raw description text is
    deliberately *not* included wholesale: a 400-line log paste would dominate the term
    vector with framework noise.
    """
    terms: list[str] = []
    for code in query.error_codes[:8]:
        terms.extend([code, code])
    terms.extend(query.key_phrases[:14])
    if not terms:
        terms = [t for t in _TOKEN.findall((query.text or "").lower())[:40] if len(t) > 2]
    return terms


def _lexical_channel_postgres(
    terms: list[str], allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    `websearch_to_tsquery` + `ts_rank`.

    `websearch_to_tsquery` is used rather than `to_tsquery` because it never raises on
    user-shaped input — no escaping of `&`, `|` or `!` required, so a pasted error string
    containing operators cannot produce a 500 or a syntax-error-shaped injection surface.
    Terms are passed as a single bound parameter; no SQL is built by string formatting.
    """
    search_query = " or ".join(dict.fromkeys(term.replace("'", " ") for term in terms))
    sql = """
        SELECT id::text,
               ts_rank(
                   to_tsvector('english', coalesce(search_text, '')),
                   websearch_to_tsquery('english', %s)
               ) AS rank
        FROM tickets_ticket
        WHERE id = ANY(%s::uuid[])
          AND to_tsvector('english', coalesce(search_text, ''))
              @@ websearch_to_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql, [search_query, [str(i) for i in allowed_ids], search_query, limit]
        )
        rows = cursor.fetchall()
    if not rows:
        return []
    top = max(rank for _, rank in rows) or 1.0
    return [(object_id, float(rank) / float(top)) for object_id, rank in rows]


def _lexical_channel_portable(
    terms: list[str], allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    BM25-style scoring in Python, for SQLite and as the Postgres fallback.

    Real IDF weighting matters here: without it, `cluster` (in every ticket) would score
    the same as `CommitStateUnknownException` (in one), and the channel would rank by
    verbosity instead of relevance.
    """
    rows = list(
        Ticket.objects.filter(id__in=allowed_ids)
        .exclude(search_text="")
        .values_list("id", "search_text")
    )
    if not rows:
        return []

    k1, b = 1.5, 0.75
    documents: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    document_frequency: defaultdict[str, int] = defaultdict(int)

    for ticket_id, text in rows:
        tokens = _TOKEN.findall((text or "").lower())
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        key = str(ticket_id)
        documents[key] = counts
        lengths[key] = max(1, len(tokens))
        for token in counts:
            document_frequency[token] += 1

    total_documents = len(documents)
    average_length = sum(lengths.values()) / total_documents

    query_terms = [term.lower() for term in terms]
    scored: list[tuple[str, float]] = []
    for key, counts in documents.items():
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            df = document_frequency.get(term, 0) or 1
            idf = math.log(1 + (total_documents - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * lengths[key] / average_length)
            score += idf * (frequency * (k1 + 1)) / denominator
        if score > 0:
            scored.append((key, score))

    if not scored:
        return []
    top = max(score for _, score in scored)
    scored.sort(key=lambda pair: -pair[1])
    return [(key, score / top) for key, score in scored[:limit]]


def _fingerprint_channel(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    Exact-then-graded error identity matching.

    Deliberately exact-first: an identical digest is near-proof that the same error
    occurred, which no amount of textual similarity establishes. Where digests differ, the
    error-code Jaccard overlap still gives a graded signal.
    """
    if not allowed_ids or (not query.fingerprint_digest and not query.error_codes):
        return []

    scored: dict[str, float] = {}

    if query.fingerprint_digest:
        exact = Ticket.objects.filter(
            id__in=allowed_ids, fingerprint__digest=query.fingerprint_digest
        ).values_list("id", flat=True)
        for ticket_id in exact:
            scored[str(ticket_id)] = 1.0

    if query.error_codes:
        probe = fingerprint_service.Fingerprint(
            digest=query.fingerprint_digest or "",
            signature="",
            error_codes=sorted(set(query.error_codes)),
            key_phrases=[],
            component=query.component or "other",
            is_low_signal=not query.error_codes,
        )
        # Narrow to fingerprints sharing at least one error code. JSONField containment is
        # not portable across SQLite and Postgres, so overlap is computed in Python over a
        # pre-narrowed set — the fingerprint table is small (one row per distinct error
        # shape), which makes this cheap.
        code_filter = Q()
        for code in probe.error_codes[:10]:
            code_filter |= Q(signature__icontains=code)
        related = ErrorFingerprint.objects.filter(code_filter) if code_filter else []

        if related:
            related_ids = [row.id for row in related]
            by_fingerprint: defaultdict = defaultdict(list)
            for ticket_id, fingerprint_id in Ticket.objects.filter(
                id__in=allowed_ids, fingerprint_id__in=related_ids
            ).values_list("id", "fingerprint_id"):
                by_fingerprint[fingerprint_id].append(str(ticket_id))

            for row in related:
                score = fingerprint_service.overlap_score(probe, row)
                if score <= 0:
                    continue
                for ticket_id in by_fingerprint.get(row.id, []):
                    if scored.get(ticket_id, 0.0) < score:
                        scored[ticket_id] = score

    ranked = sorted(scored.items(), key=lambda pair: -pair[1])
    return ranked[:limit]


def _metadata_channel(
    query: RetrievalQuery, allowed_ids: Sequence, *, limit: int
) -> list[tuple[str, float]]:
    """
    Structured-attribute recall.

    High recall, low precision — which is its job. It surfaces the ticket that describes
    the same situation in entirely different words, the case the vector channel misses when
    the embedding provider is the lexical hashing one. It carries the lowest weight
    precisely because "same component" is weak evidence on its own.
    """
    if not allowed_ids:
        return []

    filters = Q()
    if query.component:
        filters |= Q(component=query.component)
    if query.category and query.category != "unknown":
        filters |= Q(category=query.category)
    if not filters:
        return []

    rows = (
        Ticket.objects.filter(id__in=allowed_ids)
        .filter(filters)
        .values_list(
            "id", "component", "category", "environment", "normalized",
            "deployment_model", "cloud_provider",
        )[: settings.RETRIEVAL_CANDIDATE_LIMIT * 3]
    )

    query_symptoms = set(query.symptoms)
    scored: list[tuple[str, float]] = []
    for ticket_id, component, category, environment, normalized, deployment, cloud in rows:
        score = 0.0
        if query.component and component == query.component:
            score += 0.40
        if query.category and category == query.category and category != "unknown":
            score += 0.30
        if query.environment and environment == query.environment:
            score += 0.10
        if query.deployment_model and deployment == query.deployment_model:
            score += 0.05
        if query.cloud_provider and cloud == query.cloud_provider:
            score += 0.05
        if query_symptoms:
            other = set((normalized or {}).get("symptoms") or [])
            if other:
                overlap = len(query_symptoms & other) / len(query_symptoms | other)
                score += 0.35 * overlap
        if score > 0:
            scored.append((str(ticket_id), min(1.0, score)))

    scored.sort(key=lambda pair: -pair[1])
    return scored[:limit]


# =======================================================================================
# Fusion
# =======================================================================================


def _fuse(channel_results: dict[str, list[tuple[str, float]]]) -> list[Candidate]:
    """
    Weighted Reciprocal Rank Fusion.

    ``score = Σ_channels weight_c / (k + rank_c)``

    RRF operates on ranks, so a channel whose raw scores happen to live in [0, 0.02]
    contributes as much as one in [0, 1]. That robustness is the reason to prefer it over a
    weighted sum of heterogeneous similarity scores, which requires per-channel calibration
    that drifts the moment a provider changes.

    `k` (default 60, the value from the original RRF paper) flattens the curve so a
    second-place hit in two channels can outrank a first-place hit in one — which is the
    behaviour we want: agreement across independent signals is stronger evidence than one
    channel's confidence.
    """
    weights = settings.RETRIEVAL_WEIGHTS
    k = settings.RETRIEVAL_RRF_K
    merged: dict[str, Candidate] = {}

    for channel, results in channel_results.items():
        weight = weights.get(channel, 1.0)
        for index, (object_id, raw_score) in enumerate(results):
            rank = index + 1
            candidate = merged.setdefault(object_id, Candidate(object_id=object_id))
            candidate.channel_scores[channel] = round(raw_score, 4)
            candidate.channel_ranks[channel] = rank
            candidate.fused_score += weight / (k + rank)

    ordered = sorted(
        merged.values(),
        # Tie-break on channel agreement: a candidate found by three channels is a better
        # bet than one found by a single channel at the same fused score.
        key=lambda c: (-c.fused_score, -len(c.channel_scores), c.object_id),
    )
    return ordered


def _normalise_fused_scores(candidates: list[Candidate]) -> None:
    """
    Scale fused scores into [0, 1] for presentation.

    Scaled against the theoretical maximum (every channel ranking it first), not against
    the best candidate in this result set. Normalising to the local best would make the top
    result score 1.0 every time — including when it is a poor match and the only one — which
    is precisely the false confidence this product is designed not to project.
    """
    weights = settings.RETRIEVAL_WEIGHTS
    k = settings.RETRIEVAL_RRF_K
    theoretical_max = sum(weight / (k + 1) for weight in weights.values())
    if theoretical_max <= 0:
        return
    for candidate in candidates:
        candidate.fused_score = round(min(1.0, candidate.fused_score / theoretical_max), 4)


# =======================================================================================
# Service entry point
# =======================================================================================


def search_tickets(query: RetrievalQuery, *, user) -> RetrievalResult:
    """
    Run hybrid retrieval over the historical tickets `user` may legitimately see.

    Returns fused candidates. Scoring into the three separate confidences, and the
    compatibility gate, happen in `ranking.py` — retrieval's job is recall.
    """
    started = time.perf_counter()

    allowed_ids = _scoped_ticket_ids(user, exclude=query.exclude_ticket_ids)
    pool_limit = settings.RETRIEVAL_CANDIDATE_LIMIT

    notes: list[str] = []
    if not allowed_ids:
        notes.append(
            "There is no resolved ticket history available to you yet, so no historical "
            "matches could be searched. Verified resolution playbooks are still available."
        )

    channel_results: dict[str, list[tuple[str, float]]] = {}
    if allowed_ids:
        channel_results = {
            "vector": _vector_channel(query, allowed_ids, limit=pool_limit),
            "lexical": _lexical_channel(query, allowed_ids, limit=pool_limit),
            "fingerprint": _fingerprint_channel(query, allowed_ids, limit=pool_limit),
            "metadata": _metadata_channel(query, allowed_ids, limit=pool_limit),
        }

    candidates = _fuse(channel_results)
    _normalise_fused_scores(candidates)

    if not query.embedding:
        notes.append("No embedding was supplied, so the vector channel did not contribute.")
    if not query.error_codes:
        notes.append(
            "No exact error code was extracted, so the fingerprint channel — normally the "
            "strongest signal — contributed little. Adding the verbatim error line would "
            "improve these matches."
        )

    available, reason = _pgvector_available()
    provider = embedding_service.describe_provider()

    return RetrievalResult(
        candidates=candidates,
        vector_backend="pgvector" if available else "numpy",
        vector_backend_reason=reason,
        channel_counts={channel: len(results) for channel, results in channel_results.items()},
        channel_weights=dict(settings.RETRIEVAL_WEIGHTS),
        candidate_count=len(candidates),
        duration_ms=int((time.perf_counter() - started) * 1000),
        tenant_scope_applied=True,
        scoped_pool_size=len(allowed_ids),
        embedding_provider=str(provider["provider"]),
        embedding_model=str(provider["model"]),
        notes=notes,
    )


def search_playbooks(query: RetrievalQuery, *, user, trusted_only: bool = True) -> list[Candidate]:
    """
    Retrieve candidate resolution playbooks.

    `trusted_only` is the gate for acceptance tests 5 and 10: when True — which is always
    the case for a recommendation — only `approved` and `is_shared` playbooks are
    considered. A draft, rejected or deprecated playbook cannot enter trusted retrieval no
    matter how well it would have scored.

    Playbooks legitimately cross the tenant boundary, because an FDE has reviewed and
    redacted them for exactly that purpose. Unapproved drafts do not: `visible_to()` limits
    those to the organization whose ticket produced them.
    """
    from playbooks.models import ResolutionPlaybook

    queryset = ResolutionPlaybook.objects.visible_to(user)
    if trusted_only:
        queryset = queryset.trusted()

    if query.component:
        queryset = queryset.filter(
            Q(component=query.component) | Q(category=query.category or "unknown")
        )

    rows = list(
        queryset.values_list(
            "id", "embedding", "search_text", "component", "category", "symptoms"
        )[:200]
    )
    if not rows:
        return []

    channel_results: dict[str, list[tuple[str, float]]] = {
        "vector": [],
        "lexical": [],
        "metadata": [],
    }

    if query.embedding:
        vector_scores = [
            (str(pk), embedding_service.cosine_similarity(query.embedding, vector))
            for pk, vector, *_ in rows
            if vector
        ]
        vector_scores = [(pk, score) for pk, score in vector_scores if score > 0]
        vector_scores.sort(key=lambda pair: -pair[1])
        channel_results["vector"] = vector_scores[: settings.RETRIEVAL_CANDIDATE_LIMIT]

    terms = {term.lower() for term in (query.error_codes + query.key_phrases)}
    if terms:
        lexical_scores: list[tuple[str, float]] = []
        for pk, _vector, search_text, *_ in rows:
            tokens = set(_TOKEN.findall((search_text or "").lower()))
            if not tokens:
                continue
            overlap = len(terms & tokens)
            if overlap:
                lexical_scores.append((str(pk), overlap / len(terms)))
        lexical_scores.sort(key=lambda pair: -pair[1])
        channel_results["lexical"] = lexical_scores[: settings.RETRIEVAL_CANDIDATE_LIMIT]

    query_symptoms = set(query.symptoms)
    metadata_scores: list[tuple[str, float]] = []
    for pk, _vector, _text, component, category, symptoms in rows:
        score = 0.0
        if query.component and component == query.component:
            score += 0.45
        if query.category and category == query.category and category != "unknown":
            score += 0.30
        if query_symptoms and symptoms:
            other = set(symptoms)
            score += 0.35 * (len(query_symptoms & other) / len(query_symptoms | other))
        if score > 0:
            metadata_scores.append((str(pk), min(1.0, score)))
    metadata_scores.sort(key=lambda pair: -pair[1])
    channel_results["metadata"] = metadata_scores[: settings.RETRIEVAL_CANDIDATE_LIMIT]

    candidates = _fuse(channel_results)
    _normalise_fused_scores(candidates)
    return candidates


# =======================================================================================
# pgvector index maintenance
# =======================================================================================


def upsert_vector(object_type: str, object_id, organization_id, vector: Sequence[float]) -> bool:
    """
    Mirror an embedding into the pgvector index.

    The `JSONField` on the model remains the source of truth; this table is a derived
    index. That means a pgvector outage, a missing extension or a dimension change degrades
    retrieval to numpy rather than losing data — and `reembed --rebuild-index` can always
    reconstruct it.

    Returns True when the index was updated, False when there is no pgvector to update.
    """
    available, _ = _pgvector_available()
    if not available or not vector:
        return False
    if len(vector) != settings.EMBEDDING_DIM:
        logger.error(
            "Refusing to index a %d-dimension vector into a vector(%d) column.",
            len(vector), settings.EMBEDDING_DIM,
        )
        return False

    literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
    sql = f"""
        INSERT INTO {VECTOR_TABLE} (object_type, object_id, organization_id, embedding, updated_at)
        VALUES (%s, %s::uuid, %s, %s::vector, NOW())
        ON CONFLICT (object_type, object_id)
        DO UPDATE SET embedding = EXCLUDED.embedding,
                      organization_id = EXCLUDED.organization_id,
                      updated_at = NOW()
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [
                    object_type,
                    str(object_id),
                    str(organization_id) if organization_id else None,
                    literal,
                ],
            )
        return True
    except Exception:
        logger.exception("Failed to upsert into %s; retrieval will use numpy.", VECTOR_TABLE)
        return False


def delete_vector(object_type: str, object_id) -> None:
    available, _ = _pgvector_available()
    if not available:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {VECTOR_TABLE} WHERE object_type = %s AND object_id = %s::uuid",
                [object_type, str(object_id)],
            )
    except Exception:
        logger.exception("Failed to delete from %s.", VECTOR_TABLE)


@transaction.atomic
def rebuild_vector_index() -> dict[str, int]:
    """Rebuild the pgvector index from the JSONField source of truth."""
    available, reason = _pgvector_available()
    if not available:
        return {"indexed": 0, "skipped": 0, "available": 0, "reason": reason}  # type: ignore[dict-item]

    from playbooks.models import ResolutionPlaybook

    indexed = skipped = 0
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {VECTOR_TABLE}")

    for ticket_id, organization_id, vector in (
        Ticket.objects.exclude(embedding=None).values_list("id", "organization_id", "embedding")
    ):
        if upsert_vector("ticket", ticket_id, organization_id, vector):
            indexed += 1
        else:
            skipped += 1

    for playbook_id, organization_id, vector in (
        ResolutionPlaybook.objects.exclude(embedding=None).values_list(
            "id", "origin_organization_id", "embedding"
        )
    ):
        if upsert_vector("playbook", playbook_id, organization_id, vector):
            indexed += 1
        else:
            skipped += 1

    return {"indexed": indexed, "skipped": skipped, "available": 1}

"""
Access layer for the source-backed IOMETE product knowledge base.

The file at `settings.PRODUCT_KNOWLEDGE_PATH` is the single source of truth for every
product fact COMPASS states. This module loads it, validates it, and exposes query helpers.
It also enforces the rule the whole thing exists for: **a claim with no resolvable source
is a bug, not a warning.**

Validation runs at load time rather than only in the management command, so a malformed
knowledge base fails fast with a clear message instead of silently serving a page with
missing citations.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from django.conf import settings

logger = logging.getLogger("compass.knowledge")

VALID_STATUSES = {"verified", "vendor_claim", "needs_confirmation", "industry_concept"}

# Entries in these collections must carry a `status` and resolvable `sources`.
_SOURCED_COLLECTIONS = ("capabilities", "technologies", "integrations", "storage_backends",
                        "deployment_models")


class KnowledgeBaseError(RuntimeError):
    """The knowledge base is missing, malformed, or internally inconsistent."""


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_raw() -> dict[str, Any]:
    path = settings.PRODUCT_KNOWLEDGE_PATH
    if not path.exists():
        raise KnowledgeBaseError(
            f"Product knowledge base not found at {path}. COMPASS refuses to serve product "
            "claims without it. Set PRODUCT_KNOWLEDGE_PATH or restore "
            "docs/product-knowledge/knowledge.json."
        )
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise KnowledgeBaseError(f"{path} must contain a JSON object at the top level.")
    return data


def validate(data: dict[str, Any]) -> ValidationReport:
    """
    Check structural integrity and citation resolvability.

    Errors (fail the build): a missing required top-level key, an unknown `status`, a
    `sources` reference that does not resolve to a declared source id, an empty
    `do_not_claim`.

    Warnings (visible, non-fatal): a `verified` entry with no sources at all — which is
    almost always an authoring slip.
    """
    report = ValidationReport()

    for key in ("meta", "sources", "positioning", "capabilities", "technologies",
                "architecture", "integrations", "personas", "explainer_questions",
                "do_not_claim"):
        if key not in data:
            report.errors.append(f"Missing required top-level key: {key!r}")
    if report.errors:
        return report

    source_ids = {entry.get("id") for entry in data["sources"] if isinstance(entry, dict)}
    if not source_ids:
        report.errors.append("`sources` is empty; nothing can be cited.")
    for entry in data["sources"]:
        for required in ("id", "title", "url", "fetched_at"):
            if not entry.get(required):
                report.errors.append(f"Source {entry.get('id', '?')} is missing {required!r}.")

    if not data.get("do_not_claim"):
        report.errors.append(
            "`do_not_claim` is empty. It is a required guardrail: the AI grounding prompt "
            "and the knowledge API both publish it."
        )

    def check_entry(collection: str, entry: dict[str, Any]) -> None:
        label = entry.get("id") or entry.get("name") or "<unnamed>"
        status = entry.get("status")
        if status is None:
            report.errors.append(f"{collection}/{label}: missing `status`.")
        elif status not in VALID_STATUSES:
            report.errors.append(
                f"{collection}/{label}: unknown status {status!r}. "
                f"Expected one of {sorted(VALID_STATUSES)}."
            )
        refs = entry.get("sources") or []
        unknown = [ref for ref in refs if ref not in source_ids]
        if unknown:
            report.errors.append(
                f"{collection}/{label}: unresolvable source reference(s) {unknown}."
            )
        if status == "verified" and not refs:
            report.warnings.append(
                f"{collection}/{label}: marked `verified` but cites no source."
            )

    for collection in _SOURCED_COLLECTIONS:
        for entry in data.get(collection, []):
            if isinstance(entry, dict):
                check_entry(collection, entry)

    for service in data.get("architecture", {}).get("services", []):
        refs = service.get("sources") or []
        unknown = [ref for ref in refs if ref not in source_ids]
        if unknown:
            report.errors.append(
                f"architecture/services/{service.get('id')}: unresolvable sources {unknown}."
            )

    for persona in data.get("personas", []):
        for point in persona.get("key_points", []):
            unknown = [ref for ref in (point.get("sources") or []) if ref not in source_ids]
            if unknown:
                report.errors.append(
                    f"personas/{persona.get('id')}/'{point.get('title')}': "
                    f"unresolvable sources {unknown}."
                )

    for question in data.get("explainer_questions", []):
        unknown = [ref for ref in (question.get("sources") or []) if ref not in source_ids]
        if unknown:
            report.errors.append(
                f"explainer_questions/{question.get('id')}: unresolvable sources {unknown}."
            )

    return report


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """
    Load, validate and cache the knowledge base.

    Cached for the process lifetime: the file is static at runtime and read on nearly every
    public page request. `reload()` clears it (used by tests and the refresh command).
    """
    data = _read_raw()
    report = validate(data)
    if not report.ok:
        raise KnowledgeBaseError(
            "Product knowledge base failed validation:\n  - " + "\n  - ".join(report.errors)
        )
    for warning in report.warnings:
        logger.warning("Knowledge base: %s", warning)

    # Denormalise source lookups once so every API response can embed resolved citations
    # without re-scanning the sources list.
    data["_source_index"] = {entry["id"]: entry for entry in data["sources"]}
    return data


def reload() -> dict[str, Any]:
    load.cache_clear()
    return load()


# --- Query helpers ---------------------------------------------------------------------


def resolve_sources(refs: Iterable[str] | None) -> list[dict[str, str]]:
    """Turn `["S1", "S4"]` into full source records for rendering citation links."""
    index = load()["_source_index"]
    return [index[ref] for ref in (refs or []) if ref in index]


def _with_sources(entry: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in entry.items() if k != "sources"}
    out["sources"] = resolve_sources(entry.get("sources"))
    return out


def knowledge_meta() -> dict[str, Any]:
    """Compact metadata for `/api/v1/system/status/`."""
    try:
        data = load()
    except KnowledgeBaseError as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "last_verified": data["meta"].get("last_verified"),
        "schema_version": data["meta"].get("schema_version"),
        "source_count": len(data["sources"]),
        "capability_count": len(data["capabilities"]),
        "verified_capability_count": sum(
            1 for c in data["capabilities"] if c.get("status") == "verified"
        ),
        "needs_confirmation_count": sum(
            1 for c in data["capabilities"] if c.get("status") == "needs_confirmation"
        ),
        "do_not_claim_count": len(data["do_not_claim"]),
    }


def full_knowledge() -> dict[str, Any]:
    """The whole knowledge base with citations resolved, for the explainer experience."""
    data = load()
    architecture = dict(data["architecture"])
    architecture["services"] = [_with_sources(s) for s in architecture.get("services", [])]
    architecture["sources"] = resolve_sources(data["architecture"].get("sources"))
    return {
        "meta": data["meta"],
        "sources": data["sources"],
        "positioning": _with_sources(data["positioning"]),
        "concepts": [_with_sources(c) for c in data["concepts"]],
        "technologies": [_with_sources(t) for t in data["technologies"]],
        "capabilities": [_with_sources(c) for c in data["capabilities"]],
        "architecture": architecture,
        "storage_backends": [_with_sources(s) for s in data["storage_backends"]],
        "integrations": [_with_sources(i) for i in data["integrations"]],
        "deployment_models": [_with_sources(d) for d in data["deployment_models"]],
        "explainer_questions": [_with_sources(q) for q in data["explainer_questions"]],
        "personas": [persona_payload(p) for p in data["personas"]],
        "do_not_claim": data["do_not_claim"],
        "status_legend": status_legend(),
    }


def persona_payload(persona: dict[str, Any]) -> dict[str, Any]:
    out = dict(persona)
    out["key_points"] = [_with_sources(point) for point in persona.get("key_points", [])]
    return out


def get_persona(persona_id: str) -> dict[str, Any] | None:
    for persona in load()["personas"]:
        if persona["id"] == persona_id:
            return persona_payload(persona)
    return None


def personas() -> list[dict[str, Any]]:
    return [
        {"id": p["id"], "label": p["label"], "short": p["short"]} for p in load()["personas"]
    ]


def capabilities(*, status: str | None = None, category: str | None = None) -> list[dict]:
    items = load()["capabilities"]
    if status:
        items = [c for c in items if c.get("status") == status]
    if category:
        items = [c for c in items if c.get("category") == category]
    return [_with_sources(c) for c in items]


def capability_categories() -> list[str]:
    return sorted({c.get("category", "") for c in load()["capabilities"] if c.get("category")})


def integrations(*, category: str | None = None) -> list[dict]:
    items = load()["integrations"]
    if category:
        items = [i for i in items if i.get("category") == category]
    return [_with_sources(i) for i in items]


def verified_integration_names() -> set[str]:
    """
    Names COMPASS may legitimately present as documented integrations.

    Used by the fit-finder so a generated recommendation cannot name an integration that
    is not actually documented.
    """
    return {
        i["name"] for i in load()["integrations"] if i.get("status") == "verified"
    }


def storage_backends(*, verified_only: bool = False) -> list[dict]:
    items = load()["storage_backends"]
    if verified_only:
        items = [s for s in items if s.get("status") == "verified"]
    return [_with_sources(s) for s in items]


def deployment_models() -> list[dict]:
    return [_with_sources(d) for d in load()["deployment_models"]]


def architecture() -> dict[str, Any]:
    return full_knowledge()["architecture"]


def do_not_claim() -> list[str]:
    return list(load()["do_not_claim"])


def status_legend() -> dict[str, str]:
    """
    How the UI must render each status. Served with the data so the frontend cannot drift
    from the policy in `docs/product-knowledge/README.md`.
    """
    return {
        "verified": "Read directly from official IOMETE documentation. Shown with a source link.",
        "vendor_claim": (
            "Published by IOMETE but not independently verifiable. Always attributed to "
            "IOMETE, never presented as a COMPASS finding."
        ),
        "needs_confirmation": (
            "Referenced in official material but not documented in enough detail to rely "
            "on. Confirm with IOMETE before depending on it."
        ),
        "industry_concept": "General industry background, not a claim about IOMETE.",
    }


def search(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """
    Keyword search across the knowledge base.

    Deliberately simple and transparent — substring and token matching with field
    weighting — rather than embedding-based. This is a small, curated, static corpus of a
    few hundred entries; a user searching "iceberg" wants the Iceberg entry at the top,
    and lexical matching does that reliably and explainably. Semantic retrieval is used
    where it earns its keep: historical ticket search.
    """
    needle = (query or "").strip().lower()
    if not needle:
        return []
    tokens = [t for t in needle.replace("-", " ").split() if len(t) > 1]
    data = load()
    results: list[tuple[float, dict[str, Any]]] = []

    def consider(kind: str, identifier: str, title: str, body: str, payload: dict) -> None:
        haystack_title = title.lower()
        haystack_body = body.lower()
        score = 0.0
        if needle in haystack_title:
            score += 10.0
        if needle in haystack_body:
            score += 3.0
        for token in tokens:
            if token in haystack_title:
                score += 3.0
            if token in haystack_body:
                score += 1.0
        if score <= 0:
            return
        results.append(
            (score, {"kind": kind, "id": identifier, "title": title,
                     "excerpt": _excerpt(body, tokens), "entry": payload})
        )

    for item in data["capabilities"]:
        consider("capability", item["id"], item["name"],
                 f"{item.get('description', '')} {item.get('business_benefit', '')} "
                 f"{item.get('limitations') or ''}", _with_sources(item))
    for item in data["technologies"]:
        consider("technology", item["id"], item["name"],
                 f"{item.get('role', '')} {item.get('plain_english', '')} "
                 f"{item.get('iomete_usage', '')}", _with_sources(item))
    for item in data["concepts"]:
        consider("concept", item["id"], item["title"],
                 f"{item.get('plain_english', '')} {item.get('analogy', '')}",
                 _with_sources(item))
    for item in data["architecture"].get("services", []):
        consider("architecture_component", item["id"], item["name"],
                 f"{item.get('what_it_does', '')} {item.get('why_needed', '')} "
                 f"{item.get('customer_gain', '')}", _with_sources(item))
    for item in data["explainer_questions"]:
        consider("question", item["id"], item["question"], item.get("answer", ""),
                 _with_sources(item))
    for item in data["integrations"]:
        consider("integration", item["name"], item["name"], item.get("category", ""),
                 _with_sources(item))

    results.sort(key=lambda pair: (-pair[0], pair[1]["title"]))
    return [payload for _, payload in results[:limit]]


def _excerpt(body: str, tokens: list[str], width: int = 220) -> str:
    text = " ".join(body.split())
    if not text:
        return ""
    lowered = text.lower()
    position = next((lowered.find(t) for t in tokens if lowered.find(t) >= 0), 0)
    start = max(0, position - width // 3)
    snippet = text[start:start + width]
    return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(text) else "")

"""
The resolution engine: find related history and the best applicable playbook.

This is module five of the brief end to end — steps 3 through 5 of the customer workflow.
It orchestrates the pieces rather than implementing them, which keeps each piece
independently testable:

    normalised ticket
      → HybridRetrievalService.search_tickets()     (recall)
      → SimilarityRankingService.score_ticket_match (three confidences + gate)
      → persist SimilarityMatch rows                 (auditable: what did we show?)
      → HybridRetrievalService.search_playbooks()    (trusted-only recall)
      → score_playbook_match                         (strict gate)
      → LLMProviderService                           (grounded explanation)
      → recommendation: run_playbook | investigate | escalate

The recommendation is computed from evidence, not from a single score. There are exactly
three outcomes and each has an explicit precondition, so "escalate" is a first-class
answer rather than a fallback for when nothing matched.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.db import transaction

from aiengine.models import GenerationPurpose, RetrievalRun
from aiengine.services import embedding as embedding_service
from aiengine.services import llm, ranking, retrieval
from aiengine.services.normalization import symptom_label
from common.audit import record_audit
from playbooks.models import PlaybookMatch, ResolutionPlaybook

from ..models import GateStatus, SimilarityMatch, Ticket

logger = logging.getLogger("compass.resolution")

#: Below this resolution confidence we do not offer a playbook as "the fix", even when the
#: gate is clean. Offering a weak playbook with a confident UI is how a support tool gets
#: an engineer to change a production cluster for no reason.
PLAYBOOK_OFFER_THRESHOLD = 0.35


@dataclass
class ScoredTicketMatch:
    ticket: Ticket
    score: ranking.MatchScore
    rank: int
    offerable: bool


@dataclass
class ScoredPlaybookMatch:
    playbook: ResolutionPlaybook
    score: ranking.MatchScore
    rank: int


@dataclass
class ResolutionAnalysis:
    ticket: Ticket
    ticket_matches: list[ScoredTicketMatch]
    playbook_matches: list[ScoredPlaybookMatch]
    recommendation: str                # run_playbook | investigate | escalate
    recommendation_reason: str
    recommended_playbook: ResolutionPlaybook | None
    explanation: dict
    provider: str
    provider_is_live: bool
    provider_notice: str
    retrieval_run: RetrievalRun
    retrieval_notes: list[str] = field(default_factory=list)
    diagnostic_questions: list[str] = field(default_factory=list)


def build_query(ticket: Ticket, *, limit: int = 10) -> retrieval.RetrievalQuery:
    """Build a retrieval query from a persisted ticket's stored normalisation."""
    normalized = ticket.normalized or {}
    embedding = ticket.embedding
    if not embedding:
        # A ticket can exist without a vector if embedding failed at intake; compute one
        # on demand rather than silently dropping the strongest recall channel.
        try:
            embedding = embedding_service.embed_text(
                ticket.search_text or f"{ticket.title}\n{ticket.description}"
            ).vector
        except Exception:
            logger.warning("Could not embed %s on demand.", ticket.reference)
            embedding = None

    return retrieval.RetrievalQuery(
        text=ticket.search_text or ticket.description,
        error_codes=list(normalized.get("error_codes") or []),
        key_phrases=list(normalized.get("key_phrases") or []),
        symptoms=list(normalized.get("symptoms") or []),
        component=ticket.component,
        category=ticket.category,
        iomete_version=ticket.iomete_version,
        environment=ticket.environment,
        deployment_model=ticket.deployment_model,
        cloud_provider=ticket.cloud_provider,
        embedding=embedding,
        fingerprint_digest=ticket.fingerprint.digest if ticket.fingerprint_id else "",
        exclude_ticket_ids=[ticket.id],
        limit=limit,
    )


@transaction.atomic
def analyse(
    *, ticket: Ticket, user, limit: int = 8, persist: bool = True
) -> ResolutionAnalysis:
    """
    Run the full analysis for `ticket` as seen by `user`.

    `user` is load-bearing: retrieval is scoped to what that user may legitimately see, so
    the same ticket analysed by its customer and by an FDE correctly produces different
    historical matches. The FDE sees cross-customer history; the customer sees their own,
    plus approved playbooks.
    """
    query = build_query(ticket, limit=limit)
    result = retrieval.search_tickets(query, user=user)

    run = RetrievalRun.objects.create(
        ticket=ticket,
        organization=ticket.organization,
        requested_by=user if getattr(user, "pk", None) else None,
        query_hash=query.cache_key(),
        vector_backend=result.vector_backend,
        embedding_provider=result.embedding_provider,
        embedding_model=result.embedding_model,
        channel_counts=result.channel_counts,
        channel_weights=result.channel_weights,
        candidate_count=result.candidate_count,
        duration_ms=result.duration_ms,
        tenant_scope_applied=result.tenant_scope_applied,
    )

    # --- Score historical tickets ---------------------------------------------------
    candidate_ids = [candidate.object_id for candidate in result.candidates[: limit * 2]]
    tickets_by_id = {
        str(t.id): t
        for t in Ticket.objects.filter(id__in=candidate_ids)
        .select_related("organization", "resolved_via_playbook", "fingerprint")
    }

    scored_tickets: list[ScoredTicketMatch] = []
    gated_count = 0
    for candidate in result.candidates:
        matched = tickets_by_id.get(candidate.object_id)
        if matched is None:
            continue
        score = ranking.score_ticket_match(query=query, ticket=matched, candidate=candidate)
        offerable = ranking.is_offerable(score)
        if score.gate_status == GateStatus.GATED:
            gated_count += 1
        scored_tickets.append(
            ScoredTicketMatch(
                ticket=matched, score=score, rank=len(scored_tickets) + 1, offerable=offerable
            )
        )
        if len(scored_tickets) >= limit:
            break

    # --- Score playbooks ------------------------------------------------------------
    playbook_candidates = retrieval.search_playbooks(query, user=user, trusted_only=True)
    playbooks_by_id = {
        str(p.id): p
        for p in ResolutionPlaybook.objects.filter(
            id__in=[c.object_id for c in playbook_candidates[:10]]
        )
        .select_related("approved_by")
        .prefetch_related("steps")
    }
    scored_playbooks: list[ScoredPlaybookMatch] = []
    for candidate in playbook_candidates:
        playbook = playbooks_by_id.get(candidate.object_id)
        if playbook is None:
            continue
        score = ranking.score_playbook_match(
            query=query, playbook=playbook, candidate=candidate
        )
        scored_playbooks.append(
            ScoredPlaybookMatch(
                playbook=playbook, score=score, rank=len(scored_playbooks) + 1
            )
        )
        if len(scored_playbooks) >= 5:
            break

    RetrievalRun.objects.filter(pk=run.pk).update(
        returned_count=len(scored_tickets), gated_count=gated_count
    )

    # --- Decide the recommendation --------------------------------------------------
    recommendation, reason, recommended = _decide(scored_tickets, scored_playbooks)

    # --- Persist what we showed -----------------------------------------------------
    if persist:
        _persist_matches(ticket, scored_tickets, scored_playbooks, run, result.vector_backend)

    # --- Grounded explanation -------------------------------------------------------
    explanation, provider, is_live, notice = _explain(
        ticket=ticket,
        scored_tickets=scored_tickets,
        recommended=recommended,
        recommendation=recommendation,
        user=user,
    )

    questions = _diagnostic_questions(ticket, scored_tickets, recommendation)

    if persist:
        record_audit(
            action="ticket.similar_search",
            actor=user if getattr(user, "pk", None) else None,
            organization=ticket.organization,
            target_type="ticket",
            target_id=str(ticket.id),
            summary=(
                f"{ticket.reference}: {len(scored_tickets)} related case(s), "
                f"{len(scored_playbooks)} playbook(s), recommendation={recommendation}"
            ),
            metadata={
                "vector_backend": result.vector_backend,
                "channel_counts": result.channel_counts,
                "gated": gated_count,
                "scoped_pool_size": result.scoped_pool_size,
            },
        )

    return ResolutionAnalysis(
        ticket=ticket,
        ticket_matches=scored_tickets,
        playbook_matches=scored_playbooks,
        recommendation=recommendation,
        recommendation_reason=reason,
        recommended_playbook=recommended,
        explanation=explanation,
        provider=provider,
        provider_is_live=is_live,
        provider_notice=notice,
        retrieval_run=run,
        retrieval_notes=result.notes,
        diagnostic_questions=questions,
    )


def _decide(
    scored_tickets: list[ScoredTicketMatch], scored_playbooks: list[ScoredPlaybookMatch]
) -> tuple[str, str, ResolutionPlaybook | None]:
    """
    Choose between running a playbook, investigating, or escalating.

    Explicit preconditions, in priority order. Note that a gated playbook does *not* fall
    through to "investigate": if the only known fix for this error is inapplicable here,
    that is an escalation, because the customer is in a situation no verified resolution
    covers. Quietly degrading to "have a look around" would be worse than saying so.
    """
    offerable_playbooks = [
        match
        for match in scored_playbooks
        if match.score.gate_status != GateStatus.GATED
        and match.score.resolution_confidence >= PLAYBOOK_OFFER_THRESHOLD
    ]
    if offerable_playbooks:
        best = offerable_playbooks[0]
        return (
            "run_playbook",
            (
                f"The approved playbook “{best.playbook.title}” applies to your version and "
                f"environment, and matches this error's symptom profile. Resolution "
                f"confidence {best.score.resolution_confidence:.0%}."
            ),
            best.playbook,
        )

    gated_playbooks = [
        match for match in scored_playbooks if match.score.gate_status == GateStatus.GATED
    ]
    if gated_playbooks:
        best = gated_playbooks[0]
        return (
            "escalate",
            (
                f"A verified playbook exists for this error (“{best.playbook.title}”) but it "
                f"is not applicable here — {best.score.gate_reason.lower()} Rather than "
                "offer steps that were verified elsewhere, this should go to an FDE."
            ),
            None,
        )

    strong_leads = [
        match
        for match in scored_tickets
        if match.offerable and match.score.diagnosis_confidence >= 0.45
    ]
    if strong_leads:
        best = strong_leads[0]
        return (
            "investigate",
            (
                f"No approved playbook covers this yet, but {best.ticket.reference} is a "
                f"strong lead (diagnosis confidence {best.score.diagnosis_confidence:.0%}). "
                "Review it before escalating — the evidence may be enough to resolve this "
                "without an FDE."
            ),
            None,
        )

    if scored_tickets:
        return (
            "escalate",
            (
                f"{len(scored_tickets)} loosely related case(s) were found, but none carries "
                "enough diagnostic confidence to act on and no approved playbook applies. "
                "An FDE should take this."
            ),
            None,
        )

    return (
        "escalate",
        (
            "No related history and no applicable playbook. This looks like a new problem, "
            "which is exactly the case an FDE should investigate — and the investigation "
            "will become a playbook for the next customer who hits it."
        ),
        None,
    )


def _persist_matches(
    ticket: Ticket,
    scored_tickets: list[ScoredTicketMatch],
    scored_playbooks: list[ScoredPlaybookMatch],
    run: RetrievalRun,
    backend: str,
) -> None:
    """
    Store the match set for this run.

    Previous runs' rows are *not* deleted: a support decision is audited months later and
    "what did the system show the engineer that day?" has to be answerable. `retrieval_run`
    distinguishes the runs, and the API returns the latest.
    """
    SimilarityMatch.objects.bulk_create(
        [
            SimilarityMatch(
                ticket=ticket,
                matched_ticket=match.ticket,
                rank=match.rank,
                similarity_score=match.score.similarity,
                diagnosis_confidence=match.score.diagnosis_confidence,
                resolution_confidence=match.score.resolution_confidence,
                channel_scores=match.score.channel_scores,
                evidence=match.score.evidence_dicts(),
                matched_symptoms=match.score.matched_symptoms,
                gate_status=match.score.gate_status,
                gate_reason=match.score.gate_reason[:300],
                retrieval_backend=backend,
                retrieval_run=run,
            )
            for match in scored_tickets
        ],
        ignore_conflicts=True,
    )
    PlaybookMatch.objects.bulk_create(
        [
            PlaybookMatch(
                ticket=ticket,
                playbook=match.playbook,
                rank=match.rank,
                similarity_score=match.score.similarity,
                resolution_confidence=match.score.resolution_confidence,
                gate_status=match.score.gate_status,
                gate_reason=match.score.gate_reason[:300],
                evidence=match.score.evidence_dicts(),
                channel_scores=match.score.channel_scores,
                retrieval_run=run,
            )
            for match in scored_playbooks
        ],
        ignore_conflicts=True,
    )


def _explain(
    *,
    ticket: Ticket,
    scored_tickets: list[ScoredTicketMatch],
    recommended: ResolutionPlaybook | None,
    recommendation: str,
    user,
) -> tuple[dict, str, bool, str]:
    """
    Generate the grounded narrative.

    Facts are assembled here and passed as the instruction payload, so the demo provider
    restates them deterministically and the live provider has a well-specified, bounded
    task. Either way the model is never the source of a fact — only of its phrasing.
    """
    sources: list[llm.Source] = []
    match_facts = []

    for match in scored_tickets[:4]:
        matched = match.ticket
        sources.append(
            llm.Source(
                id=matched.reference,
                kind="ticket",
                title=matched.title,
                body=(
                    f"component: {matched.get_component_display()}\n"
                    f"category: {matched.get_category_display()}\n"
                    f"version: {matched.iomete_version or 'unspecified'}\n"
                    f"environment: {matched.get_environment_display()}\n"
                    f"resolution_verified: {matched.resolution_verified}\n"
                    f"resolution: {matched.resolution_summary[:1200]}"
                ),
            )
        )
        normalized = matched.normalized or {}
        match_facts.append(
            {
                "reference": matched.reference,
                "similarity": match.score.similarity,
                "diagnosis_confidence": match.score.diagnosis_confidence,
                "resolution_confidence": match.score.resolution_confidence,
                "gate_status": match.score.gate_status,
                "gate_reason": match.score.gate_reason,
                "resolution_verified": matched.resolution_verified,
                "confirmed_root_cause": (
                    matched.resolution_summary[:400] if matched.resolution_verified else ""
                ),
                "component_label": matched.get_component_display(),
                "category_label": matched.get_category_display(),
                "matched_symptoms_labels": [
                    symptom_label(s) for s in match.score.matched_symptoms
                ],
                "shared_error_codes": sorted(
                    set((ticket.normalized or {}).get("error_codes") or [])
                    & set(normalized.get("error_codes") or [])
                ),
            }
        )

    playbook_facts = None
    if recommended:
        sources.append(
            llm.Source(
                id=recommended.playbook_id,
                kind="playbook",
                title=recommended.title,
                body=(
                    f"root_cause: {recommended.confirmed_root_cause[:800]}\n"
                    f"applicable_versions: {recommended.applicable_versions or 'any'}\n"
                    f"risk_level: {recommended.risk_level}\n"
                    f"resolution: {recommended.resolution_instructions[:1200]}"
                ),
            )
        )
        playbook_facts = {
            "title": recommended.title,
            "component_label": recommended.get_component_display(),
            "resolution_instructions": recommended.resolution_instructions[:1200],
        }

    purpose = (
        GenerationPurpose.RESOLUTION_GUIDANCE
        if recommended
        else GenerationPurpose.MATCH_EXPLANATION
    )
    schema = (
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "recommended_resolution": {"type": "string"},
                "safety_notes": {"type": "array", "items": {"type": "string"}},
                "recommendation": {"type": "string"},
                "injection_noted": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "recommendation"],
        }
        if recommended
        else {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "diagnosis": {"type": "string"},
                "root_cause": {"type": "string"},
                "confidence_statement": {"type": "string"},
                "next_questions": {"type": "array", "items": {"type": "string"}},
                "recommendation": {"type": "string"},
                "injection_noted": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "confidence_statement", "recommendation"],
        }
    )

    instruction = json.dumps(
        {
            "matches": match_facts,
            "playbook": playbook_facts,
            "recommendation": recommendation,
            "query_ticket": {
                "reference": ticket.reference,
                "title": ticket.title,
                "component_label": ticket.get_component_display(),
                "error_codes": (ticket.normalized or {}).get("error_codes", [])[:6],
            },
        }
    )

    response = llm.generate(
        llm.GenerationRequest(
            purpose=purpose,
            instruction=instruction,
            sources=sources,
            schema=schema,
            schema_name=purpose,
            ticket=ticket,
            organization=ticket.organization,
            user=user,
        )
    )
    return response.data, response.provider, response.is_live, response.notice


def _diagnostic_questions(
    ticket: Ticket, scored_tickets: list[ScoredTicketMatch], recommendation: str
) -> list[str]:
    """
    What would most improve the answer.

    Asking the right question is a legitimate output of a diagnostic system, and these are
    derived from actual gaps in the record rather than generated — so they are always
    actionable and never hallucinated.
    """
    questions: list[str] = []
    normalized = ticket.normalized or {}

    if not normalized.get("error_codes"):
        questions.append(
            "Can you paste the verbatim error line, including the exception class name? "
            "Exact error matching is the strongest signal available and is currently unused."
        )
    if not ticket.iomete_version:
        questions.append(
            "Which IOMETE version is this cluster running? Without it, resolutions cannot "
            "be checked for applicability and will be gated out."
        )
    if ticket.environment in {"", "unknown"}:
        questions.append(
            "Is this production, staging or development? Environment affects which verified "
            "resolutions apply."
        )
    if not ticket.diagnostics:
        questions.append(
            "Can you attach sanitised output from the relevant component — for a Spark "
            "issue, `kubectl describe pod <driver-pod>` and the executor log tail?"
        )
    if recommendation == "escalate" and not scored_tickets:
        questions.append(
            "Did anything change shortly before this started — an upgrade, a configuration "
            "edit, a change in data volume, or a new workload?"
        )
    return questions[:4]


def latest_matches(ticket: Ticket) -> list[SimilarityMatch]:
    """
    The most recent run's match set.

    Historic runs are retained, so "latest" is resolved by run rather than by ordering on
    rank — otherwise a newer run with fewer results would interleave with an older one.
    """
    latest_run_id = (
        SimilarityMatch.objects.filter(ticket=ticket)
        .order_by("-created_at")
        .values_list("retrieval_run_id", flat=True)
        .first()
    )
    queryset = SimilarityMatch.objects.filter(ticket=ticket).select_related(
        "matched_ticket", "matched_ticket__organization"
    )
    if latest_run_id:
        queryset = queryset.filter(retrieval_run_id=latest_run_id)
    return list(queryset.order_by("rank"))


def latest_playbook_matches(ticket: Ticket) -> list[PlaybookMatch]:
    latest_run_id = (
        PlaybookMatch.objects.filter(ticket=ticket)
        .order_by("-created_at")
        .values_list("retrieval_run_id", flat=True)
        .first()
    )
    queryset = PlaybookMatch.objects.filter(ticket=ticket).select_related(
        "playbook", "playbook__approved_by"
    )
    if latest_run_id:
        queryset = queryset.filter(retrieval_run_id=latest_run_id)
    return list(queryset.order_by("rank"))

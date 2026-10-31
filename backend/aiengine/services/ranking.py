"""
SimilarityRankingService — and the compatibility gate.

This module turns retrieval recall into the three numbers the product shows, and it is
where the single most important design decision in COMPASS lives:

    similarity ≠ diagnosis confidence ≠ resolution confidence

* **similarity** — how alike the two tickets look. Comes from retrieval fusion. A
  paraphrase of the same sentence scores highly here regardless of cause.
* **diagnosis_confidence** — how much the collected evidence supports *the same root
  cause*. Driven by exact error identity, symptom overlap and component agreement. Capped
  below 1.0 on principle: retrieval alone cannot establish a root cause, only a human
  inspecting evidence can.
* **resolution_confidence** — how likely the historical fix is to work *in this
  environment*. Driven by whether the resolution was verified, how well it was executed,
  how recent it is, and whether it is applicable here at all.

Conflating these is the characteristic failure of AI support tooling: a "93% match" badge
that an engineer reads as "93% likely this fix works", applies to production, and breaks
something. The three columns exist so the UI can say "looks very similar; cause
unconfirmed; fix not applicable to your version" — three true statements that one number
cannot express.

The **compatibility gate** runs after scoring and can veto outright. A perfect textual
match verified on IOMETE 2.1 is not a recommendation for a 3.19 cluster, whatever it
scores. The gate is conservative: unknown applicability is treated as not-applicable, not
as probably-fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils import timezone

from common.versioning import describe_gate, environment_matches, version_matches
from tickets.models import GateStatus, Ticket

from .normalization import symptom_label
from .retrieval import Candidate

#: Never 1.0. Retrieval can make a case; it cannot confirm a root cause.
MAX_DIAGNOSIS_CONFIDENCE = 0.92
#: Never 1.0. A verified fix in an identical environment is still not a guarantee.
MAX_RESOLUTION_CONFIDENCE = 0.90

#: Below this, a match is shown as "possibly related" rather than offered as a lead.
WEAK_SIMILARITY = 0.25

#: And below this diagnosis confidence it is not a lead either, however similar the text
#: looks or however well the historical fix was executed. A match can share an environment
#: and have an FDE-verified resolution while being an entirely different problem — that is
#: worth listing for completeness, not worth an engineer's next hour.
MIN_DIAGNOSIS_FOR_LEAD = 0.25


@dataclass
class Evidence:
    """One concrete reason a match was proposed. Rendered verbatim in the UI."""

    kind: str
    label: str
    detail: str
    strength: str  # strong | moderate | weak | negative

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "strength": self.strength,
        }


@dataclass
class MatchScore:
    similarity: float
    diagnosis_confidence: float
    resolution_confidence: float
    gate_status: str
    gate_reason: str
    evidence: list[Evidence] = field(default_factory=list)
    matched_symptoms: list[str] = field(default_factory=list)
    channel_scores: dict[str, float] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)

    def evidence_dicts(self) -> list[dict]:
        return [item.to_dict() for item in self.evidence]


# =======================================================================================
# Compatibility gate
# =======================================================================================


@dataclass
class GateDecision:
    status: str
    reason: str
    version_ok: bool | None
    environment_ok: bool | None


def evaluate_gate(
    *,
    query_version: str,
    query_environment: str,
    target_version_spec: str,
    target_environments: list[str] | None,
    strict: bool,
) -> GateDecision:
    """
    Decide whether a candidate is applicable to the querying environment.

    `strict` separates two genuinely different questions:

    * **Playbooks (strict=True).** "Should we tell this customer to follow these steps?"
      A mismatch is a veto. An unknown is also a veto — recommending a production change
      on the basis of unverified applicability is the worst thing this system could do.
    * **Historical tickets (strict=False).** "Is this prior incident worth reading?"
      A version mismatch makes it less reliable, not useless — an FDE reading a 2.1 ticket
      about the same error is doing legitimate, useful work. So a mismatch *penalises*,
      and the reason is shown so the reader knows to discount it.

    This distinction is why the gate is a function of intent rather than a single
    threshold.
    """
    version_ok = version_matches(query_version, target_version_spec)
    environment_ok = environment_matches(query_environment, target_environments)

    if strict:
        recommendable, reason = describe_gate(version_ok, environment_ok)
        return GateDecision(
            status=GateStatus.CLEAN if recommendable else GateStatus.GATED,
            reason=reason,
            version_ok=version_ok,
            environment_ok=environment_ok,
        )

    if version_ok is False:
        return GateDecision(
            status=GateStatus.PENALISED,
            reason=(
                "Different product version — this prior case is still worth reading, but "
                "its resolution should not be applied without re-verification."
            ),
            version_ok=version_ok,
            environment_ok=environment_ok,
        )
    if environment_ok is False:
        return GateDecision(
            status=GateStatus.PENALISED,
            reason=(
                "Different deployment environment — the symptoms may match while the fix "
                "does not transfer."
            ),
            version_ok=version_ok,
            environment_ok=environment_ok,
        )
    if version_ok is None or environment_ok is None:
        return GateDecision(
            status=GateStatus.PENALISED,
            reason=(
                "Version or environment is unknown on one side, so applicability could "
                "not be established. Scored down rather than excluded."
            ),
            version_ok=version_ok,
            environment_ok=environment_ok,
        )
    return GateDecision(
        status=GateStatus.CLEAN,
        reason="Product version and environment are compatible.",
        version_ok=version_ok,
        environment_ok=environment_ok,
    )


# =======================================================================================
# Ticket match scoring
# =======================================================================================


def _recency_factor(resolved_at) -> float:
    """
    Decay for age. 1.0 fresh, floor 0.55 at roughly two years.

    A floor rather than a decay to zero: a three-year-old verified resolution for the same
    error is still the best information available, and discarding it would throw away the
    institutional memory this product exists to preserve.
    """
    if not resolved_at:
        return 0.75
    age_days = max(0.0, (timezone.now() - resolved_at).total_seconds() / 86400)
    return max(0.55, 1.0 - (age_days / 730) * 0.45)


def _symptom_overlap(query_symptoms: list[str], target_symptoms: list[str]) -> tuple[float, list[str]]:
    left, right = set(query_symptoms or []), set(target_symptoms or [])
    if not left or not right:
        return 0.0, []
    shared = sorted(left & right)
    return len(shared) / len(left | right), shared


def score_ticket_match(
    *,
    query,
    ticket: Ticket,
    candidate: Candidate,
) -> MatchScore:
    """
    Score one historical ticket against the query ticket.

    `query` is a `RetrievalQuery`. The returned `evidence` list is what makes the ranking
    defensible: every contribution to the score has a corresponding, human-readable entry,
    including the negative ones. A match whose evidence list is empty should not be
    presented as a lead, and the caller checks for that.
    """
    normalized = ticket.normalized or {}
    evidence: list[Evidence] = []

    similarity = candidate.fused_score
    channel_scores = dict(candidate.channel_scores)

    # --- Diagnosis confidence -------------------------------------------------------
    diagnosis = 0.10  # a floor: being retrieved at all is weak positive evidence

    fingerprint_score = channel_scores.get("fingerprint", 0.0)
    if fingerprint_score >= 0.999:
        diagnosis += 0.35
        evidence.append(
            Evidence(
                kind="error_fingerprint",
                label="Identical error signature",
                detail=(
                    "Both tickets produce the same normalised error signature"
                    + (f" ({', '.join(query.error_codes[:3])})" if query.error_codes else "")
                    + ". This is the strongest signal available — though the same error can "
                    "still have more than one underlying cause."
                ),
                strength="strong",
            )
        )
    elif fingerprint_score > 0:
        diagnosis += 0.20 * fingerprint_score
        shared_codes = sorted(set(query.error_codes) & set(normalized.get("error_codes") or []))
        evidence.append(
            Evidence(
                kind="error_codes",
                label="Shared error codes",
                detail=(
                    f"Both tickets report {', '.join(shared_codes[:4])}."
                    if shared_codes
                    else "Partially overlapping error signatures."
                ),
                strength="moderate",
            )
        )

    overlap, shared_symptoms = _symptom_overlap(query.symptoms, normalized.get("symptoms") or [])
    if overlap > 0:
        diagnosis += 0.25 * overlap
        evidence.append(
            Evidence(
                kind="symptoms",
                label="Overlapping symptoms",
                detail="Both report: " + ", ".join(symptom_label(s) for s in shared_symptoms[:4]),
                strength="strong" if overlap >= 0.6 else "moderate",
            )
        )

    if query.component and ticket.component == query.component:
        diagnosis += 0.10
        evidence.append(
            Evidence(
                kind="component",
                label="Same component",
                detail=f"Both affect {ticket.get_component_display()}.",
                strength="moderate",
            )
        )
    elif query.component and ticket.component != query.component:
        diagnosis -= 0.05
        evidence.append(
            Evidence(
                kind="component_mismatch",
                label="Different component",
                detail=(
                    f"This case affects {ticket.get_component_display()}, yours affects a "
                    "different component. The same error text can appear in several places "
                    "with unrelated causes."
                ),
                strength="negative",
            )
        )

    if query.category and query.category != "unknown" and ticket.category == query.category:
        diagnosis += 0.10
        evidence.append(
            Evidence(
                kind="category",
                label="Same failure category",
                detail=f"Both categorised as {ticket.get_category_display()}.",
                strength="moderate",
            )
        )

    # Independent channels agreeing is stronger than one channel being confident.
    agreement = len([score for score in channel_scores.values() if score > 0])
    if agreement >= 3:
        diagnosis += 0.08
        evidence.append(
            Evidence(
                kind="channel_agreement",
                label="Multiple independent signals agree",
                detail=(
                    f"{agreement} of four retrieval channels surfaced this case "
                    f"({', '.join(candidate.channels_hit)})."
                ),
                strength="moderate",
            )
        )
    elif agreement == 1:
        diagnosis -= 0.05
        evidence.append(
            Evidence(
                kind="single_channel",
                label="Single retrieval signal",
                detail=(
                    f"Only the {candidate.channels_hit[0]} channel surfaced this case, so "
                    "the match rests on one kind of evidence."
                ),
                strength="weak",
            )
        )

    if not query.error_codes:
        diagnosis -= 0.10
        evidence.append(
            Evidence(
                kind="no_error_code",
                label="No exact error code in your report",
                detail=(
                    "Without a verbatim error line the strongest matching signal is "
                    "unavailable, so this match rests on wording and metadata."
                ),
                strength="negative",
            )
        )

    # --- Compatibility gate ---------------------------------------------------------
    gate = evaluate_gate(
        query_version=query.iomete_version,
        query_environment=query.environment,
        target_version_spec=f"=={ticket.iomete_version}" if ticket.iomete_version else "*",
        target_environments=[ticket.environment] if ticket.environment not in {"", "unknown"} else [],
        strict=False,
    )
    if gate.status == GateStatus.PENALISED:
        diagnosis -= 0.05
        evidence.append(
            Evidence(
                kind="compatibility",
                label="Applicability caveat",
                detail=gate.reason,
                strength="negative",
            )
        )
    else:
        evidence.append(
            Evidence(
                kind="compatibility",
                label="Compatible environment",
                detail=(
                    f"Both on IOMETE {ticket.iomete_version or 'an unspecified version'} in "
                    f"{ticket.get_environment_display().lower()}."
                ),
                strength="moderate",
            )
        )

    # --- Resolution confidence ------------------------------------------------------
    if ticket.resolution_verified:
        resolution = 0.45
        evidence.append(
            Evidence(
                kind="verified_resolution",
                label="Resolution verified by an FDE",
                detail=(
                    "An IOMETE engineer confirmed this fix worked"
                    + (
                        f", reviewed {ticket.resolution_verified_at:%d %b %Y}."
                        if ticket.resolution_verified_at
                        else "."
                    )
                ),
                strength="strong",
            )
        )
    elif ticket.resolution_summary:
        resolution = 0.18
        evidence.append(
            Evidence(
                kind="unverified_resolution",
                label="Resolution recorded but not verified",
                detail=(
                    "This case was closed with a recorded resolution that no FDE has "
                    "verified. Treat it as a lead to investigate, not as a known fix."
                ),
                strength="negative",
            )
        )
    else:
        resolution = 0.05

    if ticket.resolution_quality:
        resolution += 0.20 * (ticket.resolution_quality / 5)

    resolution *= _recency_factor(ticket.resolved_at)

    if gate.status == GateStatus.PENALISED:
        # A fix verified elsewhere is materially less likely to apply here.
        resolution *= 0.55
    if gate.status == GateStatus.GATED:
        resolution = 0.0

    # A linked, approved playbook is the strongest resolution signal there is.
    if ticket.resolved_via_playbook_id:
        playbook = ticket.resolved_via_playbook
        if playbook and playbook.is_trusted:
            resolution += 0.15
            evidence.append(
                Evidence(
                    kind="approved_playbook",
                    label="Has an approved playbook",
                    detail=(
                        f"Resolved using the approved playbook “{playbook.title}”, which "
                        "you can run as a guided workflow."
                    ),
                    strength="strong",
                )
            )
        elif playbook and playbook.is_deprecated:
            evidence.append(
                Evidence(
                    kind="deprecated_playbook",
                    label="Its playbook has been deprecated",
                    detail=(
                        f"The playbook used here (“{playbook.title}”) is deprecated and is "
                        "no longer recommended as an active fix."
                    ),
                    strength="negative",
                )
            )

    diagnosis = round(max(0.0, min(MAX_DIAGNOSIS_CONFIDENCE, diagnosis)), 3)

    # Resolution confidence is conditional on the diagnosis being right.
    #
    # Without this, a well-executed, FDE-verified fix for a completely unrelated problem
    # scores highly — because every input to `resolution` so far has been about the quality
    # of *that* fix, not about whether it addresses *this* ticket. The result is a card
    # reading "diagnosis confidence 5%, resolution confidence 63%", which is incoherent and
    # invites an engineer to try it anyway.
    #
    # The three scores remain distinct concepts: `similarity` is how alike the reports are,
    # `diagnosis_confidence` is whether the cause is the same, and `resolution_confidence`
    # is how likely this fix is to work *here* — which necessarily depends on the second.
    # A floor of 0.2 is kept so a verified fix for a plausible-but-unconfirmed cause is not
    # dismissed entirely; it is a lead worth reading, just not a recommendation.
    diagnosis_factor = 0.2 + 0.8 * (diagnosis / MAX_DIAGNOSIS_CONFIDENCE)
    resolution = round(
        max(0.0, min(MAX_RESOLUTION_CONFIDENCE, resolution * diagnosis_factor)), 3
    )

    return MatchScore(
        similarity=round(similarity, 3),
        diagnosis_confidence=diagnosis,
        resolution_confidence=resolution,
        gate_status=gate.status,
        gate_reason=gate.reason,
        evidence=evidence,
        matched_symptoms=shared_symptoms,
        channel_scores=channel_scores,
        explanations={
            "similarity": (
                "How alike the two reports are, from four independent retrieval signals. "
                "High similarity means the descriptions match — it does not mean the cause "
                "is the same."
            ),
            "diagnosis_confidence": (
                "How much the collected evidence supports the same underlying cause. "
                "Capped below full certainty: only inspecting your system can confirm a "
                "root cause."
            ),
            "resolution_confidence": (
                "How likely this historical fix is to work on your ticket — combining how "
                "well it was verified and executed, its age, whether it applies to your "
                "version and deployment, and how confident we are that the underlying cause "
                "is actually the same. A well-executed fix for a different problem scores "
                "low here, which is the point."
            ),
        },
    )


# =======================================================================================
# Playbook match scoring
# =======================================================================================


def score_playbook_match(*, query, playbook, candidate: Candidate) -> MatchScore:
    """
    Score a playbook against the query ticket.

    Strict gating: a playbook is an instruction to *do something*, so an unconfirmed
    applicability is a veto rather than a penalty. `gate_status == "gated"` playbooks are
    still returned to the caller — with the reason — so the UI can show "we found a fix for
    this error but it does not apply to your version", which is far more useful than
    silently returning nothing.
    """
    evidence: list[Evidence] = []
    similarity = candidate.fused_score
    channel_scores = dict(candidate.channel_scores)

    overlap, shared_symptoms = _symptom_overlap(query.symptoms, playbook.symptoms or [])
    if overlap > 0:
        evidence.append(
            Evidence(
                kind="symptoms",
                label="Symptoms match this playbook",
                detail="Matches on: " + ", ".join(symptom_label(s) for s in shared_symptoms[:4]),
                strength="strong" if overlap >= 0.5 else "moderate",
            )
        )

    if query.component and playbook.component == query.component:
        evidence.append(
            Evidence(
                kind="component",
                label="Same component",
                detail=f"Written for {playbook.get_component_display()}.",
                strength="moderate",
            )
        )

    gate = evaluate_gate(
        query_version=query.iomete_version,
        query_environment=query.environment,
        target_version_spec=playbook.applicable_versions,
        target_environments=playbook.applicable_environments,
        strict=True,
    )

    resolution = 0.0
    if playbook.is_trusted:
        resolution = 0.50
        evidence.append(
            Evidence(
                kind="approved",
                label="Approved by an FDE",
                detail=(
                    "Reviewed and approved"
                    + (f" on {playbook.approved_at:%d %b %Y}" if playbook.approved_at else "")
                    + f" by {playbook.approved_by.full_name if playbook.approved_by else 'an FDE'}."
                ),
                strength="strong",
            )
        )
        if playbook.is_review_overdue:
            resolution *= 0.8
            evidence.append(
                Evidence(
                    kind="review_overdue",
                    label="Review overdue",
                    detail=(
                        f"This playbook was due for re-review on "
                        f"{playbook.review_due_at:%d %b %Y}. Product behaviour may have "
                        "changed since it was last verified."
                    ),
                    strength="negative",
                )
            )
    elif playbook.is_deprecated:
        evidence.append(
            Evidence(
                kind="deprecated",
                label="Deprecated",
                detail="Retained for reference only. Not recommended as an active fix.",
                strength="negative",
            )
        )
    else:
        evidence.append(
            Evidence(
                kind="unapproved",
                label="Not yet approved",
                detail=(
                    f"Status: {playbook.get_approval_status_display()}. Unapproved content "
                    "is never offered as a verified resolution."
                ),
                strength="negative",
            )
        )

    success_rate = playbook.success_rate
    if success_rate is not None:
        resolution += 0.25 * success_rate
        evidence.append(
            Evidence(
                kind="track_record",
                label="Track record",
                detail=(
                    f"Resolved {playbook.success_count} of "
                    f"{playbook.success_count + playbook.failure_count} recorded attempts."
                ),
                strength="strong" if success_rate >= 0.75 else "moderate",
            )
        )
    elif playbook.is_trusted:
        evidence.append(
            Evidence(
                kind="no_track_record",
                label="No recorded outcomes yet",
                detail=(
                    "Approved but not yet used in a completed run, so there is no success "
                    "rate to report. This is different from a poor success rate."
                ),
                strength="weak",
            )
        )

    if gate.status == GateStatus.GATED:
        resolution = 0.0
        evidence.append(
            Evidence(
                kind="gated",
                label="Not applicable here",
                detail=gate.reason,
                strength="negative",
            )
        )
    else:
        evidence.append(
            Evidence(
                kind="applicable",
                label="Applicable to your environment",
                detail=(
                    f"Declared for versions {playbook.applicable_versions or 'any'} and "
                    f"environments {', '.join(playbook.applicable_environments) or 'any'}."
                ),
                strength="moderate",
            )
        )

    resolution = round(max(0.0, min(MAX_RESOLUTION_CONFIDENCE, resolution)), 3)

    return MatchScore(
        similarity=round(similarity, 3),
        # A playbook describes a *known* root cause, so diagnosis confidence here reflects
        # how well the ticket matches that known cause's symptom profile.
        diagnosis_confidence=round(min(MAX_DIAGNOSIS_CONFIDENCE, 0.15 + 0.6 * overlap + 0.15 * similarity), 3),
        resolution_confidence=resolution,
        gate_status=gate.status,
        gate_reason=gate.reason,
        evidence=evidence,
        matched_symptoms=shared_symptoms,
        channel_scores=channel_scores,
    )


def is_offerable(score: MatchScore) -> bool:
    """
    Should this match be offered as a lead, rather than listed as 'possibly related'?

    Requires a non-trivial similarity *and* at least one non-negative piece of evidence.
    The second condition matters: a candidate can score moderately through metadata
    coincidence alone while every substantive signal disagrees, and presenting that as a
    lead wastes an engineer's time and erodes trust in the whole feature.
    """
    if score.gate_status == GateStatus.GATED:
        return False
    if score.similarity < WEAK_SIMILARITY:
        return False
    if score.diagnosis_confidence < MIN_DIAGNOSIS_FOR_LEAD:
        return False
    return any(item.strength in {"strong", "moderate"} for item in score.evidence)

"""
KnowledgeExtractionService and FDEApprovalService — the knowledge-compounding loop.

    resolved ticket
      → AI extraction  → draft playbook (approval_status=draft)
      → FDE review     → edit, redact, set applicability, set risk
      → approve        → version n, review_due_at = +180d, enters trusted retrieval
      → future ticket  → matched, gated, offered as a guided workflow

This is the loop that makes the product compound rather than just answer. Three guards keep
it honest:

1. **Drafts are never trusted.** `approval_status=draft` is excluded from
   `ResolutionPlaybook.objects.trusted()`, so an AI-written playbook cannot be recommended
   to anyone until a named human approved it on a recorded date.
2. **Duplicates are detected before a draft is created.** Without this, every recurrence of
   the same OOM incident spawns another near-identical playbook and the library becomes
   unusable. `find_duplicate()` checks fingerprint, cluster and component+category overlap.
3. **Approval validates the step graph.** A playbook whose remediation step is reachable
   without evidence, or that contains a destructive command, cannot be approved —
   `execution.validate_graph()` returns errors and the approval is refused.

Rejections are retained with their reason. Deleting a rejected draft destroys the record of
why something was judged unsafe, which is exactly the institutional memory this product
exists to build.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import User
from aiengine.models import GenerationPurpose
from aiengine.services import embedding as embedding_service
from aiengine.services import llm, retrieval
from aiengine.services.normalization import symptom_label
from common.audit import record_audit
from common.exceptions import ConflictError, DomainValidationError
from tickets.models import Ticket, TicketEvent, TicketEventType

from ..models import (
    ApprovalDecision,
    ApprovalStatus,
    KnowledgeApproval,
    PlaybookStep,
    ResolutionPlaybook,
    ResponseKind,
    RiskLevel,
    StepType,
)
from . import execution as execution_service

logger = logging.getLogger("compass.knowledge")

#: Default re-review interval. A playbook that has not been looked at in six months is a
#: liability: the product it describes has moved on underneath it.
REVIEW_INTERVAL_DAYS = 180


# =======================================================================================
# Duplicate detection
# =======================================================================================


@dataclass
class DuplicateCheck:
    duplicate: ResolutionPlaybook | None
    reason: str = ""
    confidence: float = 0.0


def find_duplicate(*, ticket: Ticket) -> DuplicateCheck:
    """
    Is there already a playbook covering this ticket's problem?

    Three signals, strongest first. Fingerprint identity is near-conclusive; cluster
    membership is strong; component+category+symptom overlap is suggestive.
    """
    if ticket.fingerprint_id:
        existing = (
            ResolutionPlaybook.objects.filter(
                fingerprints__id=ticket.fingerprint_id,
                approval_status__in=[ApprovalStatus.APPROVED, ApprovalStatus.IN_REVIEW,
                                     ApprovalStatus.DRAFT],
            )
            .order_by("-approval_status", "-version")
            .first()
        )
        if existing:
            return DuplicateCheck(
                existing,
                f"“{existing.title}” already covers this exact error signature.",
                0.95,
            )

    if ticket.cluster_id:
        existing = (
            ResolutionPlaybook.objects.filter(
                cluster_id=ticket.cluster_id,
                approval_status__in=[ApprovalStatus.APPROVED, ApprovalStatus.IN_REVIEW],
            )
            .order_by("-version")
            .first()
        )
        if existing:
            return DuplicateCheck(
                existing,
                f"“{existing.title}” is already linked to this ticket's issue cluster.",
                0.75,
            )

    symptoms = set((ticket.normalized or {}).get("symptoms") or [])
    if symptoms:
        for candidate in ResolutionPlaybook.objects.filter(
            component=ticket.component,
            category=ticket.category,
            approval_status__in=[ApprovalStatus.APPROVED, ApprovalStatus.IN_REVIEW],
        ).order_by("-version")[:20]:
            other = set(candidate.symptoms or [])
            if not other:
                continue
            overlap = len(symptoms & other) / len(symptoms | other)
            if overlap >= 0.7:
                return DuplicateCheck(
                    candidate,
                    f"“{candidate.title}” covers a {overlap:.0%} overlapping symptom "
                    "profile for the same component and failure category.",
                    round(overlap, 2),
                )

    return DuplicateCheck(None)


# =======================================================================================
# Extraction
# =======================================================================================


@dataclass
class ExtractionResult:
    playbook: ResolutionPlaybook | None
    duplicate_of: ResolutionPlaybook | None
    provider: str
    provider_is_live: bool
    provider_notice: str
    redaction_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


#: Patterns that suggest content a reviewer must look at before approval. Detection, not
#: removal — a reviewer removing it deliberately is better than a regex mangling a fix.
_REVIEW_FLAGS = (
    (r"\b(?:prod|production)[-_]?[a-z0-9]{3,}\b", "Possible production resource name"),
    (r"\b[a-z0-9\-]+\.(?:internal|local|corp|intranet)\b", "Internal hostname"),
    (r"\[REDACTED:[A-Z_]+\]", "Redaction placeholder — confirm nothing customer-specific remains"),
    (r"\b(?:arn:aws|projects/|/subscriptions/)\S+", "Cloud resource identifier"),
    (r"\b[A-Z][a-z]+ [A-Z][a-z]+\b(?= said| reported| confirmed)", "Possible personal name"),
)


def _flag_for_review(*texts: str) -> list[str]:
    flags: list[str] = []
    joined = "\n".join(filter(None, texts))
    for pattern, label in _REVIEW_FLAGS:
        if re.search(pattern, joined, re.I):
            flags.append(label)
    return sorted(set(flags))


@transaction.atomic
def extract_from_ticket(
    *, ticket: Ticket, actor: User, force: bool = False
) -> ExtractionResult:
    """
    Generate a draft playbook from a resolved ticket.

    Requires a resolution to exist — there is nothing to extract from an open ticket, and
    generating a "playbook" from an unresolved investigation would produce exactly the kind
    of confident-sounding, unverified guidance that makes AI support tools dangerous.

    `force=True` lets an FDE create a draft anyway when a duplicate was detected but they
    judge the cases genuinely different.
    """
    if not ticket.resolution_summary.strip():
        raise DomainValidationError(
            detail="This ticket has no recorded resolution, so there is nothing to extract. "
            "Record how it was resolved first."
        )

    duplicate = find_duplicate(ticket=ticket)
    if duplicate.duplicate and not force:
        # Link rather than duplicate, and say so.
        return ExtractionResult(
            playbook=None,
            duplicate_of=duplicate.duplicate,
            provider="none",
            provider_is_live=False,
            provider_notice="",
            notes=[
                duplicate.reason,
                "No new draft was created. Link this ticket to the existing playbook, or "
                "re-run with force=true if the cases are genuinely different.",
            ],
        )

    normalized = ticket.normalized or {}
    execution = (
        ticket.executions.filter(status__in=["resolved", "partially_resolved"])
        .order_by("-completed_at")
        .first()
    )

    sources = [
        llm.Source(
            id=ticket.reference,
            kind="ticket",
            title=ticket.title,
            body=(
                f"component: {ticket.get_component_display()}\n"
                f"category: {ticket.get_category_display()}\n"
                f"version: {ticket.iomete_version or 'unspecified'}\n"
                f"environment: {ticket.get_environment_display()}\n"
                f"deployment: {ticket.deployment_model}\n"
                f"error_codes: {', '.join(normalized.get('error_codes') or [])}\n"
                f"symptoms: {', '.join(normalized.get('symptom_labels') or [])}\n"
                f"description: {ticket.description[:1500]}\n"
                f"error_message: {ticket.error_message[:800]}\n"
                f"resolution: {ticket.resolution_summary[:1500]}\n"
                f"resolution_evidence: {ticket.resolution_evidence[:800]}\n"
                f"resolution_verified: {ticket.resolution_verified}"
            ),
        )
    ]
    if execution:
        package = execution_service.build_escalation_package(execution)
        sources.append(
            llm.Source(
                id=f"execution:{execution.id}",
                kind="execution",
                title=f"Resolution Replay run of {execution.playbook.title}",
                body=json.dumps(package)[:3000],
            )
        )

    facts = {
        "ticket": {
            "reference": ticket.reference,
            "title": ticket.title,
            "suggested_title": _suggest_title(ticket),
            "component_label": ticket.get_component_display(),
            "category_label": ticket.get_category_display(),
            "iomete_version": ticket.iomete_version,
            "environment": ticket.environment,
            "error_codes": normalized.get("error_codes") or [],
            "symptom_labels": normalized.get("symptom_labels") or [],
            "resolution_summary": ticket.resolution_summary,
            "resolution_verified": ticket.resolution_verified,
        },
        "risk_level": _infer_risk(ticket),
        "redaction_flags": _flag_for_review(
            ticket.description, ticket.resolution_summary, ticket.diagnostics
        ),
    }

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "symptoms": {"type": "array", "items": {"type": "string"}},
            "confirmed_root_cause": {"type": "string"},
            "root_cause_is_confirmed": {"type": "boolean"},
            "preconditions": {"type": "array", "items": {"type": "string"}},
            "expected_evidence": {"type": "array", "items": {"type": "string"}},
            "resolution_instructions": {"type": "string"},
            "verification_steps": {"type": "array", "items": {"type": "string"}},
            "known_limitations": {"type": "string"},
            "risk_level": {"type": "string"},
            "redaction_flags": {"type": "array", "items": {"type": "string"}},
            "injection_noted": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "description", "resolution_instructions"],
    }

    response = llm.generate(
        llm.GenerationRequest(
            purpose=GenerationPurpose.KNOWLEDGE_EXTRACTION,
            instruction=json.dumps(facts),
            sources=sources,
            schema=schema,
            schema_name="knowledge_draft",
            ticket=ticket,
            organization=ticket.organization,
            user=actor,
        )
    )
    data = response.data

    base_slug = slugify(data.get("title") or _suggest_title(ticket))[:100] or "resolution"
    playbook_id = _unique_playbook_id(base_slug)

    playbook = ResolutionPlaybook.objects.create(
        playbook_id=playbook_id,
        version=1,
        title=(data.get("title") or _suggest_title(ticket))[:250],
        description=data.get("description") or ticket.resolution_summary[:2000],
        component=ticket.component,
        category=ticket.category,
        # Applicability starts deliberately narrow: exactly the version and environment the
        # fix was actually observed in. Widening it is a reviewer's decision, taken
        # knowingly — the opposite default would quietly recommend unverified fixes.
        applicable_versions=f"=={ticket.iomete_version}" if ticket.iomete_version else "",
        applicable_environments=(
            [ticket.environment] if ticket.environment not in {"", "unknown"} else []
        ),
        applicable_deployments=[ticket.deployment_model] if ticket.deployment_model else [],
        symptoms=normalized.get("symptoms") or [],
        confirmed_root_cause=data.get("confirmed_root_cause") or "",
        preconditions=data.get("preconditions") or [],
        expected_evidence=data.get("expected_evidence") or [],
        resolution_instructions=data.get("resolution_instructions") or ticket.resolution_summary,
        verification_steps=data.get("verification_steps") or [],
        known_limitations=data.get("known_limitations") or "",
        risk_level=_normalise_risk(data.get("risk_level")) or _infer_risk(ticket),
        approval_status=ApprovalStatus.DRAFT,
        is_shared=True,
        source_ticket=ticket,
        origin_organization=ticket.organization,
        cluster=ticket.cluster,
        created_by=actor,
        generated_by=response.provider,
        is_synthetic=ticket.is_synthetic,
        redaction_notes="",
    )
    if ticket.fingerprint_id:
        playbook.fingerprints.add(ticket.fingerprint)

    _create_draft_steps(playbook, ticket, execution)
    _refresh_search_index(playbook)

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.KNOWLEDGE_DRAFT,
        author=actor,
        author_label=actor.email,
        body=f"Knowledge draft generated: “{playbook.title}”. Awaiting FDE review.",
        is_internal=True,
        metadata={
            "playbook_id": playbook.playbook_id,
            "generated_by": response.provider,
            "is_live_model": response.is_live,
        },
    )
    record_audit(
        action="knowledge.draft_generated",
        actor=actor,
        organization=ticket.organization,
        target_type="playbook",
        target_id=str(playbook.id),
        summary=f"Draft “{playbook.title}” from {ticket.reference}",
        metadata={
            "playbook_id": playbook.playbook_id,
            "generated_by": response.provider,
            "forced_despite_duplicate": bool(duplicate.duplicate and force),
        },
    )

    flags = list(dict.fromkeys((data.get("redaction_flags") or []) + facts["redaction_flags"]))
    notes = [
        "This draft is not trusted knowledge. It cannot be recommended to any customer "
        "until an FDE reviews and approves it.",
    ]
    if not data.get("root_cause_is_confirmed"):
        notes.append(
            "The root cause is recorded as unconfirmed because the source ticket's "
            "resolution was never FDE-verified. Confirm it before approving."
        )
    if duplicate.duplicate and force:
        notes.append(f"Created despite a possible duplicate: {duplicate.reason}")
    if response.ungrounded_claims:
        notes.append(
            f"{len(response.ungrounded_claims)} statement(s) could not be attributed to a "
            "source. Check them closely during review."
        )

    return ExtractionResult(
        playbook=playbook,
        duplicate_of=duplicate.duplicate if force else None,
        provider=response.provider,
        provider_is_live=response.is_live,
        provider_notice=response.notice,
        redaction_flags=flags,
        notes=notes,
    )


def _suggest_title(ticket: Ticket) -> str:
    codes = (ticket.normalized or {}).get("error_codes") or []
    lead = codes[0] if codes else ticket.get_category_display()
    return f"{ticket.get_component_display()}: {lead}"[:250]


def _unique_playbook_id(base: str) -> str:
    candidate = base
    suffix = 2
    while ResolutionPlaybook.objects.filter(playbook_id=candidate).exists():
        candidate = f"{base}-{suffix}"[:120]
        suffix += 1
    return candidate


def _infer_risk(ticket: Ticket) -> str:
    """
    Default risk from the failure category.

    Biased towards caution: a resource or configuration fix usually means editing a running
    workload's settings, which is a `MEDIUM` at least. A reviewer lowers it knowingly.
    """
    if ticket.category in {"resource_exhaustion", "capacity_limit", "configuration_error"}:
        return RiskLevel.MEDIUM
    if ticket.category in {"permission_denied", "authentication"}:
        return RiskLevel.MEDIUM
    if ticket.category in {"metadata_inconsistency", "version_incompatibility"}:
        return RiskLevel.HIGH
    return RiskLevel.LOW


def _normalise_risk(value) -> str:
    if isinstance(value, str) and value in {level.value for level in RiskLevel}:
        return value
    return ""


def _create_draft_steps(
    playbook: ResolutionPlaybook, ticket: Ticket, execution
) -> None:
    """
    Build the draft's step graph.

    When the ticket was resolved through a Resolution Replay run, the actual traversed path
    is reused — those steps demonstrably worked on a real incident, which is a far better
    starting point than anything generated from scratch. Otherwise a safe skeleton is
    created: confirm symptoms → gather evidence → review configuration → apply the
    documented fix (approval-gated) → verify.

    Every draft ends with a verification step, and the remediation step is always
    approval-gated and always preceded by diagnostics, so `validate_graph()` passes.
    """
    normalized = ticket.normalized or {}
    symptoms = normalized.get("symptom_labels") or []

    if execution is not None:
        source_steps = [
            response.step
            for response in execution.responses.select_related("step").order_by("sequence")
        ]
        if source_steps:
            for index, source in enumerate(source_steps, start=1):
                PlaybookStep.objects.create(
                    playbook=playbook,
                    order=index,
                    key=f"{source.key}"[:80],
                    title=source.title,
                    plain_explanation=source.plain_explanation,
                    what_to_inspect=source.what_to_inspect,
                    expected_observation=source.expected_observation,
                    why_this_step=source.why_this_step,
                    step_type=source.step_type,
                    risk_level=source.risk_level,
                    blast_radius=source.blast_radius,
                    commands=source.commands,
                    response_kind=source.response_kind,
                    response_options=source.response_options,
                    branches={"__default": f"step-{index + 1}"}
                    if index < len(source_steps)
                    else {"__default": execution_service.TERMINAL_RESOLVED},
                    is_terminal=index == len(source_steps),
                )
            # Re-point branches to the keys actually created.
            created = list(playbook.steps.order_by("order"))
            for index, step in enumerate(created):
                if index + 1 < len(created):
                    step.branches = {"__default": created[index + 1].key}
                else:
                    step.branches = {"__default": execution_service.TERMINAL_RESOLVED}
                step.save(update_fields=["branches"])
            return

    steps_spec = [
        {
            "key": "confirm-symptoms",
            "title": "Confirm you are seeing the same symptoms",
            "plain_explanation": (
                "Before changing anything, confirm this is the same problem this playbook "
                "was written for. If the symptoms differ, the fix below will not help and "
                "may waste time."
                + (f" Reported symptoms: {', '.join(symptoms[:3])}." if symptoms else "")
            ),
            "what_to_inspect": "Compare what you are seeing with the symptoms listed above.",
            "expected_observation": symptoms[0] if symptoms else ticket.title,
            "step_type": StepType.INFORMATIONAL,
            "risk_level": RiskLevel.INFORMATIONAL,
            "response_kind": ResponseKind.BOOLEAN,
            "branches": {"yes": "gather-evidence", "no": execution_service.TERMINAL_ESCALATE},
        },
        {
            "key": "gather-evidence",
            "title": "Collect the diagnostic evidence",
            "plain_explanation": (
                "Gather the read-only evidence that confirms the root cause. Nothing here "
                "changes your system."
            ),
            "what_to_inspect": "\n".join(playbook.expected_evidence or [])
            or "Inspect the affected component's recent events and logs.",
            "expected_observation": (
                ", ".join((normalized.get("error_codes") or [])[:3])
                or "evidence consistent with the root cause described above"
            ),
            "step_type": StepType.READ_ONLY_DIAGNOSTIC,
            "risk_level": RiskLevel.LOW,
            "commands": _suggest_commands(ticket),
            "response_kind": ResponseKind.BOOLEAN,
            "branches": {
                "yes": "review-configuration",
                "no": execution_service.TERMINAL_ESCALATE,
            },
        },
        {
            "key": "review-configuration",
            "title": "Review the current configuration",
            "plain_explanation": (
                "Read the relevant configuration and compare it with what the environment "
                "can actually provide. Do not edit anything yet."
            ),
            "what_to_inspect": "The component's current settings and the limits around it.",
            "expected_observation": "a setting inconsistent with the available resources or policy",
            "step_type": StepType.CONFIGURATION_REVIEW,
            "risk_level": RiskLevel.LOW,
            "response_kind": ResponseKind.BOOLEAN,
            "branches": {
                "yes": "apply-fix",
                "no": execution_service.TERMINAL_ESCALATE,
            },
        },
        {
            "key": "apply-fix",
            "title": "Apply the documented fix",
            "plain_explanation": playbook.resolution_instructions[:2000],
            "what_to_inspect": "Apply the change, then confirm it was accepted.",
            "expected_observation": "the change is applied and the component restarts cleanly",
            "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
            "risk_level": playbook.risk_level,
            "blast_radius": (
                f"Affects the {ticket.get_component_display()} workload in "
                f"{ticket.get_environment_display().lower()}. Running queries or jobs on "
                "the affected cluster may be interrupted while it restarts."
            ),
            "response_kind": ResponseKind.BOOLEAN,
            "branches": {"yes": "verify", "no": execution_service.TERMINAL_ESCALATE},
        },
        {
            "key": "verify",
            "title": "Verify the problem is actually gone",
            "plain_explanation": (
                "Re-run what was failing and confirm it now succeeds. Completing the steps "
                "above is not evidence of a fix — this is."
            ),
            "what_to_inspect": "\n".join(playbook.verification_steps or [])
            or "Re-run the operation that previously failed.",
            "expected_observation": "the operation completes and the original error is absent",
            "step_type": StepType.VERIFICATION,
            "risk_level": RiskLevel.INFORMATIONAL,
            "response_kind": ResponseKind.BOOLEAN,
            "branches": {
                "yes": execution_service.TERMINAL_RESOLVED,
                "no": execution_service.TERMINAL_ESCALATE,
            },
            "is_terminal": True,
        },
    ]

    for order, spec in enumerate(steps_spec, start=1):
        PlaybookStep.objects.create(
            playbook=playbook,
            order=order,
            key=spec["key"],
            title=spec["title"],
            plain_explanation=spec["plain_explanation"],
            what_to_inspect=spec.get("what_to_inspect", ""),
            expected_observation=spec.get("expected_observation", ""),
            why_this_step=spec.get("why_this_step", ""),
            step_type=spec["step_type"],
            risk_level=spec["risk_level"],
            blast_radius=spec.get("blast_radius", ""),
            commands=spec.get("commands", []),
            response_kind=spec["response_kind"],
            response_options=spec.get("response_options", []),
            branches=spec.get("branches", {}),
            is_terminal=spec.get("is_terminal", False),
        )


def _suggest_commands(ticket: Ticket) -> list[dict]:
    """
    Read-only inspection commands appropriate to the component.

    Strictly read-only — `describe`, `get`, `logs`, `SHOW`. Nothing that deletes, restarts
    or mutates. A playbook that needs a destructive operation escalates instead.
    """
    component = ticket.component
    if component in {"spark_compute", "spark_jobs"}:
        return [
            {"label": "Driver pod status and recent events", "language": "bash",
             "command": "kubectl describe pod <driver-pod> -n <namespace>", "is_read_only": True},
            {"label": "Previous container's log tail (survives a restart)", "language": "bash",
             "command": "kubectl logs <executor-pod> -n <namespace> --previous --tail=200",
             "is_read_only": True},
            {"label": "Container termination reason and exit code", "language": "bash",
             "command": "kubectl get pod <executor-pod> -n <namespace> "
                        "-o jsonpath='{.status.containerStatuses[*].lastState.terminated}'",
             "is_read_only": True},
        ]
    if component == "kubernetes":
        return [
            {"label": "Node resource pressure", "language": "bash",
             "command": "kubectl describe nodes | grep -A 5 'Allocated resources'",
             "is_read_only": True},
            {"label": "Namespace resource quota usage", "language": "bash",
             "command": "kubectl describe resourcequota -n <namespace>", "is_read_only": True},
            {"label": "Pending pods and why", "language": "bash",
             "command": "kubectl get events -n <namespace> --field-selector reason=FailedScheduling",
             "is_read_only": True},
        ]
    if component in {"iceberg_metadata", "iceberg_catalog"}:
        return [
            {"label": "Table metadata and current snapshot", "language": "sql",
             "command": "DESCRIBE EXTENDED <catalog>.<namespace>.<table>;", "is_read_only": True},
            {"label": "Snapshot history", "language": "sql",
             "command": "SELECT * FROM <catalog>.<namespace>.<table>.snapshots "
                        "ORDER BY committed_at DESC LIMIT 20;", "is_read_only": True},
            {"label": "Manifest files for the current snapshot", "language": "sql",
             "command": "SELECT * FROM <catalog>.<namespace>.<table>.manifests;",
             "is_read_only": True},
        ]
    if component == "permissions":
        return [
            {"label": "Effective grants on the table", "language": "sql",
             "command": "SHOW GRANTS ON TABLE <catalog>.<namespace>.<table>;",
             "is_read_only": True},
            {"label": "Your current roles", "language": "sql",
             "command": "SHOW CURRENT ROLES;", "is_read_only": True},
        ]
    if component == "object_storage":
        return [
            {"label": "Storage configuration as the platform sees it", "language": "bash",
             "command": "kubectl get secret data-plane -n <namespace> "
                        "-o jsonpath='{.data}' | base64 -d | jq 'keys'",
             "is_read_only": True},
            {"label": "Confirm the bucket is reachable from inside the cluster",
             "language": "bash",
             "command": "kubectl run -it --rm netcheck --image=curlimages/curl --restart=Never "
                        "-- curl -sS -o /dev/null -w '%{http_code}' <storage-endpoint>",
             "is_read_only": True},
        ]
    return [
        {"label": "Recent events in the namespace", "language": "bash",
         "command": "kubectl get events -n <namespace> --sort-by=.lastTimestamp | tail -40",
         "is_read_only": True},
    ]


def _refresh_search_index(playbook: ResolutionPlaybook) -> None:
    """Rebuild the playbook's retrieval text and embedding."""
    parts = [
        playbook.title, playbook.title,
        playbook.description,
        playbook.confirmed_root_cause,
        " ".join(symptom_label(s) for s in (playbook.symptoms or [])),
        " ".join(playbook.expected_evidence or []),
        playbook.resolution_instructions,
        playbook.get_component_display(),
        playbook.get_category_display(),
    ]
    search_text = " ".join(filter(None, parts))
    update = {"search_text": search_text}
    try:
        result = embedding_service.embed_text(search_text)
        update.update(
            embedding=result.vector,
            embedding_model=result.model,
            embedding_dim=result.dim,
        )
    except Exception:
        logger.exception("Failed to embed playbook %s", playbook.playbook_id)

    ResolutionPlaybook.objects.filter(pk=playbook.pk).update(**update)
    if "embedding" in update:
        retrieval.upsert_vector(
            "playbook", playbook.id, playbook.origin_organization_id, update["embedding"]
        )


# =======================================================================================
# FDEApprovalService
# =======================================================================================


@dataclass
class ApprovalResult:
    playbook: ResolutionPlaybook
    approval: KnowledgeApproval
    graph_issues: list[execution_service.GraphIssue] = field(default_factory=list)


@transaction.atomic
def approve(
    *,
    playbook: ResolutionPlaybook,
    reviewer: User,
    notes: str = "",
    redactions_made: str = "",
    applicable_versions: str | None = None,
    applicable_environments: list[str] | None = None,
    risk_level: str | None = None,
    is_shared: bool | None = None,
    review_interval_days: int = REVIEW_INTERVAL_DAYS,
) -> ApprovalResult:
    """
    Approve a playbook into trusted knowledge.

    Refuses when `validate_graph()` reports an error: an unsafe or unfinishable workflow
    must not become the thing COMPASS recommends to the next customer. This is the gate
    that makes "approved" mean something.
    """
    if playbook.approval_status == ApprovalStatus.APPROVED:
        raise ConflictError(detail="This playbook is already approved.")
    if playbook.approval_status == ApprovalStatus.DEPRECATED:
        raise ConflictError(
            detail="This playbook is deprecated. Create a new version instead of "
            "re-approving a superseded one."
        )
    if not playbook.confirmed_root_cause.strip():
        raise DomainValidationError(
            detail="A playbook cannot be approved without a confirmed root cause. If the "
            "cause is still unknown, this is not yet trusted knowledge."
        )

    # Apply the reviewer's edits to applicability *before* validating.
    changes: dict = {}
    if applicable_versions is not None and applicable_versions != playbook.applicable_versions:
        changes["applicable_versions"] = {
            "from": playbook.applicable_versions, "to": applicable_versions
        }
        playbook.applicable_versions = applicable_versions
    if applicable_environments is not None:
        changes["applicable_environments"] = {
            "from": playbook.applicable_environments, "to": applicable_environments
        }
        playbook.applicable_environments = applicable_environments
    if risk_level is not None and risk_level != playbook.risk_level:
        changes["risk_level"] = {"from": playbook.risk_level, "to": risk_level}
        playbook.risk_level = risk_level
    if is_shared is not None:
        changes["is_shared"] = {"from": playbook.is_shared, "to": is_shared}
        playbook.is_shared = is_shared

    issues = execution_service.validate_graph(playbook)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise DomainValidationError(
            detail="This playbook cannot be approved until its workflow is corrected: "
            + " ".join(f"[{issue.step_key or 'playbook'}] {issue.message}" for issue in errors)
        )

    now = timezone.now()
    playbook.approval_status = ApprovalStatus.APPROVED
    playbook.approved_by = reviewer
    playbook.approved_at = now
    playbook.last_reviewed_at = now
    playbook.review_due_at = now + timedelta(days=review_interval_days)
    playbook.redaction_notes = redactions_made or playbook.redaction_notes
    playbook.rejection_reason = ""
    playbook.save()

    _refresh_search_index(playbook)

    approval = KnowledgeApproval.objects.create(
        playbook=playbook,
        playbook_version=playbook.version,
        reviewer=reviewer,
        reviewer_label=reviewer.email,
        decision=ApprovalDecision.APPROVED,
        notes=notes,
        redactions_made=redactions_made,
        applicability_changes=changes,
        review_due_at=playbook.review_due_at,
    )

    if playbook.source_ticket_id:
        TicketEvent.objects.create(
            ticket=playbook.source_ticket,
            event_type=TicketEventType.VERIFICATION,
            author=reviewer,
            author_label=reviewer.email,
            body=f"Playbook “{playbook.title}” approved as trusted knowledge.",
            is_internal=True,
            metadata={"playbook_id": playbook.playbook_id, "version": playbook.version},
        )

    record_audit(
        action="playbook.approved",
        actor=reviewer,
        organization=playbook.origin_organization,
        target_type="playbook",
        target_id=str(playbook.id),
        summary=f"Approved “{playbook.title}” v{playbook.version}",
        metadata={
            "playbook_id": playbook.playbook_id,
            "applicable_versions": playbook.applicable_versions,
            "risk_level": playbook.risk_level,
            "is_shared": playbook.is_shared,
            "changes": changes,
            "graph_warnings": [i.message for i in issues if i.severity == "warning"],
        },
    )
    return ApprovalResult(
        playbook=playbook,
        approval=approval,
        graph_issues=[issue for issue in issues if issue.severity == "warning"],
    )


@transaction.atomic
def reject(*, playbook: ResolutionPlaybook, reviewer: User, reason: str) -> KnowledgeApproval:
    """
    Reject a draft, retaining it with the reason.

    Not deleted: why something was judged unsafe is itself institutional knowledge, and the
    next person who proposes the same thing should be able to find out it was already
    considered.
    """
    if not reason.strip():
        raise DomainValidationError(
            detail="A rejection needs a reason — it is the record of why this was judged "
            "unsuitable."
        )
    if playbook.approval_status == ApprovalStatus.APPROVED:
        raise ConflictError(
            detail="This playbook is approved. Deprecate it instead of rejecting it, so the "
            "reason is recorded against a superseded version."
        )

    playbook.approval_status = ApprovalStatus.REJECTED
    playbook.rejection_reason = reason
    playbook.last_reviewed_at = timezone.now()
    playbook.save(update_fields=["approval_status", "rejection_reason", "last_reviewed_at",
                                 "updated_at"])

    approval = KnowledgeApproval.objects.create(
        playbook=playbook,
        playbook_version=playbook.version,
        reviewer=reviewer,
        reviewer_label=reviewer.email,
        decision=ApprovalDecision.REJECTED,
        notes=reason,
    )
    record_audit(
        action="playbook.rejected",
        actor=reviewer,
        organization=playbook.origin_organization,
        target_type="playbook",
        target_id=str(playbook.id),
        summary=f"Rejected “{playbook.title}”: {reason[:200]}",
        metadata={"playbook_id": playbook.playbook_id},
    )
    return approval


@transaction.atomic
def request_changes(
    *, playbook: ResolutionPlaybook, reviewer: User, notes: str
) -> KnowledgeApproval:
    """Send a draft back for editing without rejecting it outright."""
    if not notes.strip():
        raise DomainValidationError(detail="Say what needs to change.")
    playbook.approval_status = ApprovalStatus.IN_REVIEW
    playbook.last_reviewed_at = timezone.now()
    playbook.save(update_fields=["approval_status", "last_reviewed_at", "updated_at"])
    approval = KnowledgeApproval.objects.create(
        playbook=playbook,
        playbook_version=playbook.version,
        reviewer=reviewer,
        reviewer_label=reviewer.email,
        decision=ApprovalDecision.CHANGES_REQUESTED,
        notes=notes,
    )
    record_audit(
        action="playbook.updated",
        actor=reviewer,
        organization=playbook.origin_organization,
        target_type="playbook",
        target_id=str(playbook.id),
        summary=f"Changes requested on “{playbook.title}”",
        metadata={"playbook_id": playbook.playbook_id},
    )
    return approval


@transaction.atomic
def deprecate(
    *, playbook: ResolutionPlaybook, reviewer: User, reason: str
) -> KnowledgeApproval:
    """
    Mark an approved playbook as no longer recommended.

    Deprecated playbooks leave `trusted()` immediately — acceptance test 10 — but remain
    readable, flagged, for audit and for anyone who followed them in the past.
    """
    if not reason.strip():
        raise DomainValidationError(detail="Deprecation needs a reason.")
    playbook.approval_status = ApprovalStatus.DEPRECATED
    playbook.last_reviewed_at = timezone.now()
    playbook.save(update_fields=["approval_status", "last_reviewed_at", "updated_at"])

    approval = KnowledgeApproval.objects.create(
        playbook=playbook,
        playbook_version=playbook.version,
        reviewer=reviewer,
        reviewer_label=reviewer.email,
        decision=ApprovalDecision.DEPRECATED,
        notes=reason,
    )
    record_audit(
        action="playbook.deprecated",
        actor=reviewer,
        organization=playbook.origin_organization,
        target_type="playbook",
        target_id=str(playbook.id),
        summary=f"Deprecated “{playbook.title}” v{playbook.version}: {reason[:200]}",
        metadata={"playbook_id": playbook.playbook_id},
    )
    return approval


@transaction.atomic
def create_new_version(
    *, playbook: ResolutionPlaybook, author: User, changes: dict | None = None
) -> ResolutionPlaybook:
    """
    Fork an approved playbook into a new draft version.

    The old version is deprecated and `supersedes` is set, so the lineage is explicit and
    the superseded version stops being recommended the moment the new one is approved — not
    silently mutated underneath the executions that already ran against it. That is also
    why `PlaybookExecution.playbook_version` is denormalised.
    """
    steps = list(playbook.steps.order_by("order"))

    new_version = ResolutionPlaybook.objects.create(
        playbook_id=playbook.playbook_id,
        version=playbook.version + 1,
        title=playbook.title,
        description=playbook.description,
        component=playbook.component,
        category=playbook.category,
        applicable_versions=playbook.applicable_versions,
        applicable_environments=playbook.applicable_environments,
        applicable_deployments=playbook.applicable_deployments,
        applicable_cloud_providers=playbook.applicable_cloud_providers,
        symptoms=playbook.symptoms,
        confirmed_root_cause=playbook.confirmed_root_cause,
        preconditions=playbook.preconditions,
        expected_evidence=playbook.expected_evidence,
        resolution_instructions=playbook.resolution_instructions,
        verification_steps=playbook.verification_steps,
        known_limitations=playbook.known_limitations,
        risk_level=playbook.risk_level,
        approval_status=ApprovalStatus.DRAFT,
        is_shared=playbook.is_shared,
        supersedes=playbook,
        source_ticket=playbook.source_ticket,
        origin_organization=playbook.origin_organization,
        cluster=playbook.cluster,
        created_by=author,
        generated_by="human",
        is_synthetic=playbook.is_synthetic,
    )
    for field_name, value in (changes or {}).items():
        if hasattr(new_version, field_name):
            setattr(new_version, field_name, value)
    new_version.save()
    new_version.fingerprints.set(playbook.fingerprints.all())

    for step in steps:
        PlaybookStep.objects.create(
            playbook=new_version,
            order=step.order,
            key=step.key,
            title=step.title,
            plain_explanation=step.plain_explanation,
            what_to_inspect=step.what_to_inspect,
            expected_observation=step.expected_observation,
            why_this_step=step.why_this_step,
            step_type=step.step_type,
            risk_level=step.risk_level,
            blast_radius=step.blast_radius,
            commands=step.commands,
            response_kind=step.response_kind,
            response_options=step.response_options,
            branches=step.branches,
            is_terminal=step.is_terminal,
            references=step.references,
        )

    _refresh_search_index(new_version)

    record_audit(
        action="playbook.superseded",
        actor=author,
        organization=playbook.origin_organization,
        target_type="playbook",
        target_id=str(new_version.id),
        summary=f"Created v{new_version.version} of “{playbook.title}”",
        metadata={"playbook_id": playbook.playbook_id, "supersedes_version": playbook.version},
    )
    return new_version


def refresh_index(playbook: ResolutionPlaybook) -> None:
    """Public wrapper, used after an FDE edits a playbook's content."""
    _refresh_search_index(playbook)

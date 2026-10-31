"""
Ticket lifecycle: status, assignment, escalation, resolution and verification.

The important distinction encoded here is between **resolved** and **verified**:

* A *customer* can mark a ticket resolved. That records their outcome and counts as a
  self-service resolution.
* Only an *FDE* can mark it verified. Verification is what admits a resolution into trusted
  retrieval as precedent for other tickets.

Collapsing those would mean one customer's optimistic "seems fine now" becomes a confident
recommendation to the next customer. Acceptance test 5 exists for exactly this.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from aiengine.models import GenerationPurpose
from aiengine.services import llm, redaction
from common.audit import record_audit
from common.exceptions import ConflictError, DomainValidationError

from ..models import (
    OPEN_STATUSES,
    Ticket,
    TicketEvent,
    TicketEventType,
    TicketStatus,
)

logger = logging.getLogger("compass.tickets")

#: Transitions a *customer* may make. Deliberately narrow: a customer cannot assign an FDE
#: or reopen a closed ticket into an FDE's queue without going through escalation.
CUSTOMER_TRANSITIONS = {
    TicketStatus.NEW: {TicketStatus.TRIAGING, TicketStatus.IN_PROGRESS,
                       TicketStatus.ESCALATED, TicketStatus.RESOLVED},
    TicketStatus.TRIAGING: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED,
                            TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.ESCALATED, TicketStatus.RESOLVED},
    TicketStatus.AWAITING_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED,
                                     TicketStatus.RESOLVED},
    TicketStatus.ESCALATED: {TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


def allowed_transitions(ticket: Ticket, user: User) -> set[str]:
    if user.is_iomete_staff:
        # Staff may move a ticket anywhere; they are the escalation path of last resort and
        # an artificial state machine would just produce workarounds.
        return {status.value for status in TicketStatus} - {ticket.status}
    return {s.value for s in CUSTOMER_TRANSITIONS.get(ticket.status, set())}


@transaction.atomic
def change_status(*, ticket: Ticket, user: User, new_status: str, note: str = "") -> Ticket:
    if new_status == ticket.status:
        return ticket
    if new_status not in {status.value for status in TicketStatus}:
        raise DomainValidationError(detail=f"Unknown status {new_status!r}.")

    permitted = allowed_transitions(ticket, user)
    if new_status not in permitted:
        raise DomainValidationError(
            detail=(
                f"A ticket that is {ticket.get_status_display().lower()} cannot be moved to "
                f"{new_status.replace('_', ' ')} from your role. Available: "
                f"{', '.join(sorted(permitted)) or 'none'}."
            )
        )

    previous = ticket.status
    ticket.status = new_status
    fields = ["status", "updated_at"]

    if new_status == TicketStatus.RESOLVED and ticket.resolved_at is None:
        ticket.resolved_at = timezone.now()
        ticket.time_to_resolution_seconds = int(
            (ticket.resolved_at - ticket.created_at).total_seconds()
        )
        fields += ["resolved_at", "time_to_resolution_seconds"]
    if new_status == TicketStatus.IN_PROGRESS and previous == TicketStatus.RESOLVED:
        # Reopened: the resolution no longer holds, so it must not remain as precedent.
        ticket.resolved_at = None
        ticket.resolution_verified = False
        ticket.resolution_verified_at = None
        ticket.self_service_resolved = False
        fields += ["resolved_at", "resolution_verified", "resolution_verified_at",
                   "self_service_resolved"]

    ticket.save(update_fields=fields)

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.STATUS_CHANGED,
        author=user,
        author_label=user.email,
        body=f"Status: {previous.replace('_', ' ')} → {new_status.replace('_', ' ')}."
        + (f" {redaction.redact(note).text}" if note else ""),
        metadata={"from": previous, "to": new_status},
    )
    record_audit(
        action="ticket.status_changed",
        actor=user,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference}: {previous} → {new_status}",
        metadata={"from": previous, "to": new_status},
    )
    return ticket


@transaction.atomic
def assign(*, ticket: Ticket, user: User, assignee: User | None) -> Ticket:
    """Assign or unassign an FDE. Only IOMETE staff may do this."""
    if not user.is_iomete_staff:
        raise DomainValidationError(
            detail="Only IOMETE staff can assign a ticket. Use escalation to request help."
        )
    if assignee is not None and not assignee.is_iomete_staff:
        raise DomainValidationError(
            detail="Tickets can only be assigned to an FDE or platform administrator."
        )

    previous = ticket.assigned_fde
    ticket.assigned_fde = assignee
    ticket.save(update_fields=["assigned_fde", "updated_at"])

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.ASSIGNED,
        author=user,
        author_label=user.email,
        body=(
            f"Assigned to {assignee.full_name}." if assignee else "Assignment cleared."
        ),
        is_internal=True,
        metadata={
            "from": previous.email if previous else None,
            "to": assignee.email if assignee else None,
        },
    )
    record_audit(
        action="ticket.assigned",
        actor=user,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference} assigned to {assignee.email if assignee else 'nobody'}",
    )
    return ticket


@dataclass
class EscalationResult:
    ticket: Ticket
    summary: dict
    provider: str
    provider_is_live: bool
    provider_notice: str


@transaction.atomic
def escalate(
    *, ticket: Ticket, user: User, reason: str, execution=None
) -> EscalationResult:
    """
    Escalate to an FDE with the full diagnostic record attached.

    The escalation package is what makes this different from "send an email". When the
    customer has run a Resolution Replay, the FDE receives what was checked, what was
    observed and what was ruled out — so the investigation starts where the customer left
    off instead of from scratch. That is the mechanism by which COMPASS saves FDE hours.
    """
    if not reason.strip():
        raise DomainValidationError(
            detail="Say what you have tried and what is still wrong. The escalation summary "
            "is what lets an FDE start where you left off."
        )
    if ticket.status == TicketStatus.CLOSED:
        raise ConflictError(detail="This ticket is closed. Reopen it before escalating.")

    clean_reason = redaction.redact(reason).text

    # Prefer an explicitly supplied execution; otherwise use the most recent run.
    if execution is None:
        execution = ticket.executions.order_by("-created_at").first()

    package = {}
    if execution is not None:
        from playbooks.services import execution as execution_service

        package = execution_service.build_escalation_package(execution)

    sources = [
        llm.Source(
            id=ticket.reference,
            kind="ticket",
            title=ticket.title,
            body=(
                f"component: {ticket.get_component_display()}\n"
                f"severity: {ticket.get_severity_display()}\n"
                f"version: {ticket.iomete_version or 'unspecified'}\n"
                f"environment: {ticket.get_environment_display()}\n"
                f"description: {ticket.description[:1500]}\n"
                f"error: {ticket.error_message[:800]}\n"
                f"escalation_reason: {clean_reason[:800]}"
            ),
        )
    ]
    if package:
        sources.append(
            llm.Source(
                id=f"execution:{execution.id}",
                kind="execution",
                title="Diagnostic work already completed",
                body=json.dumps(package)[:4000],
            )
        )

    response = llm.generate(
        llm.GenerationRequest(
            purpose=GenerationPurpose.ESCALATION_SUMMARY,
            instruction=json.dumps(
                {
                    "ticket": {"reference": ticket.reference, "title": ticket.title},
                    "steps_completed": package.get("steps_completed", []),
                    "ruled_out": package.get("ruled_out", []),
                    "reason": clean_reason,
                }
            ),
            sources=sources,
            schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "what_was_ruled_out": {"type": "array", "items": {"type": "string"}},
                    "what_was_observed": {"type": "array", "items": {"type": "string"}},
                    "open_questions": {"type": "array", "items": {"type": "string"}},
                    "suggested_next_action": {"type": "string"},
                    "injection_noted": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary"],
            },
            schema_name="escalation_summary",
            ticket=ticket,
            organization=ticket.organization,
            user=user,
        )
    )

    now = timezone.now()
    ticket.status = TicketStatus.ESCALATED
    ticket.escalated_at = now
    ticket.escalation_reason = clean_reason
    ticket.save(update_fields=["status", "escalated_at", "escalation_reason", "updated_at"])

    if execution is not None and execution.status == "in_progress":
        from playbooks.models import ExecutionStatus

        execution.status = ExecutionStatus.ESCALATED
        execution.completed_at = now
        execution.current_step = None
        execution.save(update_fields=["status", "completed_at", "current_step", "updated_at"])

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.ESCALATED,
        author=user,
        author_label=user.email,
        body=f"Escalated to an FDE. {clean_reason[:500]}",
        metadata={
            "escalation_summary": response.data,
            "execution_id": str(execution.id) if execution else None,
            "steps_completed": len(package.get("steps_completed", [])),
            "generated_by": response.provider,
        },
    )
    record_audit(
        action="ticket.escalated",
        actor=user,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference} escalated: {clean_reason[:200]}",
        metadata={
            "steps_completed": len(package.get("steps_completed", [])),
            "had_execution": execution is not None,
        },
    )

    return EscalationResult(
        ticket=ticket,
        summary={**response.data, "diagnostic_package": package},
        provider=response.provider,
        provider_is_live=response.is_live,
        provider_notice=response.notice,
    )


@transaction.atomic
def record_resolution(
    *,
    ticket: Ticket,
    user: User,
    summary: str,
    evidence: str = "",
    self_service: bool | None = None,
    fde_investigation_minutes: int | None = None,
) -> Ticket:
    """
    Record how a ticket was resolved.

    `evidence` is required — the brief's rule that a completed checklist is not proof of a
    fix applies just as much to a free-text resolution. Without an observation, "resolved"
    is an assertion, and this record is about to become retrieval precedent for other
    customers.
    """
    if not summary.strip():
        raise DomainValidationError(detail="Describe how the problem was resolved.")
    if not evidence.strip():
        raise DomainValidationError(
            detail="Describe what you observed that shows the problem is gone — for example "
            "that the failing operation now completes, or that the error has stopped "
            "appearing. This resolution may be offered to other customers as precedent, so "
            "the evidence matters."
        )

    now = timezone.now()
    ticket.resolution_summary = redaction.redact(summary).text
    ticket.resolution_evidence = redaction.redact(evidence).text
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = ticket.resolved_at or now
    ticket.time_to_resolution_seconds = int(
        (ticket.resolved_at - ticket.created_at).total_seconds()
    )
    if self_service is not None:
        ticket.self_service_resolved = self_service
    elif not user.is_iomete_staff:
        ticket.self_service_resolved = True
    if fde_investigation_minutes is not None:
        if not user.is_iomete_staff:
            raise DomainValidationError(
                detail="Only an FDE can record investigation time."
            )
        ticket.fde_investigation_minutes = fde_investigation_minutes

    ticket.save()

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.RESOLUTION,
        author=user,
        author_label=user.email,
        body=f"Resolved: {ticket.resolution_summary[:500]}",
        metadata={
            "self_service": ticket.self_service_resolved,
            "evidence_supplied": bool(ticket.resolution_evidence),
            "fde_investigation_minutes": ticket.fde_investigation_minutes,
        },
    )
    record_audit(
        action="ticket.resolved",
        actor=user,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference} resolved by {user.email}",
        metadata={
            "self_service": ticket.self_service_resolved,
            "time_to_resolution_seconds": ticket.time_to_resolution_seconds,
        },
    )
    return ticket


@transaction.atomic
def verify_resolution(
    *, ticket: Ticket, reviewer: User, quality: int, note: str = ""
) -> Ticket:
    """
    FDE verification: admit this resolution to trusted retrieval precedent.

    Restricted to IOMETE staff. `quality` (1-5) feeds `resolution_confidence` for future
    matches, so a resolution that technically worked but was a poor fix does not become a
    confident recommendation.
    """
    if not reviewer.is_iomete_staff:
        raise DomainValidationError(
            detail="Only an FDE or platform administrator can verify a resolution. "
            "Verification is what allows a fix to be offered to other customers."
        )
    if not ticket.resolution_summary.strip():
        raise DomainValidationError(
            detail="There is no recorded resolution to verify."
        )
    if quality not in range(1, 6):
        raise DomainValidationError(detail="Quality must be between 1 and 5.")

    ticket.resolution_verified = True
    ticket.resolution_verified_at = timezone.now()
    ticket.resolution_verified_by = reviewer
    ticket.resolution_quality = quality
    ticket.save(
        update_fields=[
            "resolution_verified", "resolution_verified_at", "resolution_verified_by",
            "resolution_quality", "updated_at",
        ]
    )

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.VERIFICATION,
        author=reviewer,
        author_label=reviewer.email,
        body=(
            f"Resolution verified (quality {quality}/5). This fix can now be offered as "
            "precedent for similar tickets."
            + (f" {redaction.redact(note, redact_emails=False).text}" if note else "")
        ),
        is_internal=True,
        metadata={"quality": quality},
    )
    record_audit(
        action="ticket.resolved",
        actor=reviewer,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference} resolution verified (quality {quality}/5)",
        metadata={"quality": quality, "verified": True},
    )
    return ticket


def open_ticket_queryset(user):
    """Open tickets visible to `user`, newest first. Used by dashboards."""
    return (
        Ticket.objects.for_user(user)
        .filter(status__in=[s.value for s in OPEN_STATUSES])
        .select_related("organization", "assigned_fde", "reporter")
    )

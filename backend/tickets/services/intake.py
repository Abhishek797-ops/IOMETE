"""
Ticket intake.

The order of operations here is a security property, not a style choice:

    redact → normalise → fingerprint → persist → embed → index

Redaction happens first and on every text field, so nothing un-redacted is ever written to
a row, an embedding, a vector index, or an LLM request. Normalisation and fingerprinting
then run on the *redacted* text — which is why `redaction.py` preserves the shape of what
it removes (`[REDACTED:IPV4]` rather than `***`): the error structure survives, so the
retrieval signal survives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import Organization, User
from aiengine.services import embedding as embedding_service
from aiengine.services import fingerprint as fingerprint_service
from aiengine.services import normalization, redaction, retrieval
from common.audit import record_audit
from common.exceptions import DomainValidationError

from ..models import (
    Environment,
    Severity,
    Ticket,
    TicketComponent,
    TicketEvent,
    TicketEventType,
    TicketStatus,
)

logger = logging.getLogger("compass.tickets")


@dataclass
class IntakeResult:
    ticket: Ticket
    redaction_summary: dict[str, int]
    redaction_notice: str
    normalization: normalization.NormalizedTicket
    fingerprint_digest: str
    embedding_provider: str
    embedding_indexed: bool


def generate_reference() -> str:
    """
    Human-readable ticket reference, `COMPASS-NNNN`.

    Sequential and derived from the current maximum rather than random, because engineers
    read these out loud and paste them into chat. Collisions are prevented by the unique
    constraint plus the retry in `create_ticket`.
    """
    last = (
        Ticket.objects.filter(reference__startswith="COMPASS-")
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    if last:
        try:
            return f"COMPASS-{int(last.split('-')[1]) + 1:04d}"
        except (IndexError, ValueError):
            pass
    return "COMPASS-1001"


@transaction.atomic
def create_ticket(
    *,
    organization: Organization,
    reporter: User | None,
    title: str,
    description: str,
    component: str = TicketComponent.OTHER,
    severity: str = Severity.MEDIUM,
    iomete_version: str = "",
    environment: str = Environment.UNKNOWN,
    deployment_model: str = "",
    cloud_provider: str = "",
    kubernetes_distribution: str = "",
    error_message: str = "",
    diagnostics: str = "",
    is_synthetic: bool = False,
    external_provider: str = "",
    external_reference: str = "",
    external_url: str = "",
    created_at_override=None,
) -> IntakeResult:
    """
    Create a ticket from a customer submission.

    `created_at_override` exists only for the seed command, which needs a realistic spread
    of historical dates so that recency weighting and analytics windows have something
    meaningful to work with.
    """
    if not title.strip():
        raise DomainValidationError(detail="A ticket needs a title.")
    if not description.strip():
        raise DomainValidationError(detail="A ticket needs a description of the problem.")

    # --- 1. Redact everything, before anything else touches it ---------------------
    (clean_title, clean_description, clean_error, clean_diagnostics), summary = (
        redaction.redact_many([title, description, error_message, diagnostics])
    )
    redaction_notice = redaction.redact(description).describe() if summary else ""
    if summary:
        # Rebuild the notice from the combined summary so it reflects all four fields.
        combined = redaction.RedactionResult(text="", summary=summary)
        redaction_notice = combined.describe()

    # --- 2. Normalise ---------------------------------------------------------------
    normalized = normalization.normalize(
        title=clean_title,
        description=clean_description,
        error_message=clean_error,
        diagnostics=clean_diagnostics,
        declared_component=component,
        declared_version=iomete_version or organization.iomete_version,
        declared_environment=environment,
    )

    # --- 3. Fingerprint -------------------------------------------------------------
    computed = fingerprint_service.compute(
        error_codes=normalized.error_codes,
        error_message=clean_error or clean_description,
        title=clean_title,
        component=normalized.component,
        key_phrases=normalized.key_phrases,
    )
    fingerprint_row = fingerprint_service.record(
        computed, organization_id=organization.id
    )

    # --- 4. Persist -----------------------------------------------------------------
    ticket = Ticket(
        organization=organization,
        reference=generate_reference(),
        title=clean_title[:250],
        description=clean_description,
        error_message=clean_error,
        diagnostics=clean_diagnostics,
        redaction_summary=summary,
        component=normalized.component,
        category=normalized.category,
        severity=severity,
        status=TicketStatus.NEW,
        iomete_version=normalized.extracted_version or organization.iomete_version,
        environment=environment,
        deployment_model=deployment_model or organization.deployment_model,
        cloud_provider=cloud_provider or organization.cloud_provider,
        kubernetes_distribution=kubernetes_distribution or organization.kubernetes_distribution,
        normalized=normalized.to_dict(),
        fingerprint=fingerprint_row,
        search_text=normalized.search_text,
        reporter=reporter,
        reporter_label=(reporter.email if reporter else "system"),
        is_synthetic=is_synthetic,
        external_provider=external_provider,
        external_reference=external_reference,
        external_url=external_url,
    )
    try:
        ticket.save()
    except Exception:
        # The reference is unique; a concurrent create can lose the race. Retry once with
        # a freshly computed reference rather than failing the user's submission.
        ticket.reference = generate_reference()
        ticket.save()

    if created_at_override is not None:
        Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at_override)
        ticket.created_at = created_at_override

    # --- 5. Embed and index ---------------------------------------------------------
    embedded = embed_ticket(ticket)

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.CREATED,
        author=reporter,
        author_label=(reporter.email if reporter else "system"),
        body=f"Ticket created with severity {ticket.get_severity_display()}.",
        metadata={
            "component": ticket.component,
            "category": ticket.category,
            "error_codes": normalized.error_codes[:10],
            "symptoms": normalized.symptoms,
            "redactions": summary,
            "fingerprint": computed.digest[:16],
        },
    )

    record_audit(
        action="ticket.created",
        actor=reporter,
        organization=organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference}: {ticket.title[:120]}",
        metadata={
            "component": ticket.component,
            "severity": ticket.severity,
            "redaction_count": sum(summary.values()),
            "is_synthetic": is_synthetic,
        },
    )

    return IntakeResult(
        ticket=ticket,
        redaction_summary=summary,
        redaction_notice=redaction_notice,
        normalization=normalized,
        fingerprint_digest=computed.digest,
        embedding_provider=embedded[0],
        embedding_indexed=embedded[1],
    )


def embed_ticket(ticket: Ticket) -> tuple[str, bool]:
    """
    Compute and store the ticket's embedding, mirroring it into pgvector when available.

    Returns `(provider_name, was_indexed_in_pgvector)`. Embedding failure is logged but not
    fatal: a ticket without a vector still participates in the lexical, fingerprint and
    metadata channels, so the product degrades rather than breaks.
    """
    text = ticket.search_text or f"{ticket.title}\n{ticket.description}"
    try:
        result = embedding_service.embed_text(text)
    except Exception:
        logger.exception(
            "Failed to embed %s. It will still be retrievable through the lexical, "
            "fingerprint and metadata channels.",
            ticket.reference,
        )
        return ("none", False)

    Ticket.objects.filter(pk=ticket.pk).update(
        embedding=result.vector,
        embedding_model=result.model,
        embedding_dim=result.dim,
        embedded_at=timezone.now(),
    )
    ticket.embedding = result.vector
    ticket.embedding_model = result.model
    ticket.embedding_dim = result.dim

    indexed = retrieval.upsert_vector(
        "ticket", ticket.id, ticket.organization_id, result.vector
    )
    return (result.provider, indexed)


@transaction.atomic
def add_comment(
    *, ticket: Ticket, author: User, body: str, is_internal: bool = False
) -> TicketEvent:
    """
    Add a comment or internal note.

    `is_internal=True` produces an FDE-only note and is rejected for customer roles — a
    customer writing an "internal" note would create a record they believe is private but
    which is labelled for a different audience entirely.

    Internal notes keep email addresses and IP addresses: an FDE writing "spoke to
    alex@customer.example about the 10.0.3.4 node" is recording legitimate operational
    context, and redacting it would make the note useless. Customer-authored comments are
    redacted in full.
    """
    if is_internal and not author.is_iomete_staff:
        raise DomainValidationError(
            detail="Only IOMETE staff can add an internal note. Your comment would be "
            "visible to a different audience than you expect."
        )
    if not body.strip():
        raise DomainValidationError(detail="A comment needs some content.")

    result = redaction.redact(
        body,
        redact_emails=not is_internal,
        redact_ips=not is_internal,
    )

    event = TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.INTERNAL_NOTE if is_internal else TicketEventType.COMMENT,
        author=author,
        author_label=author.email,
        body=result.text,
        is_internal=is_internal,
        metadata={"redactions": result.summary} if result.was_redacted else {},
    )

    if ticket.first_response_at is None and author.is_iomete_staff and not is_internal:
        Ticket.objects.filter(pk=ticket.pk).update(first_response_at=timezone.now())

    record_audit(
        action="ticket.note_added" if is_internal else "ticket.updated",
        actor=author,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=f"{ticket.reference}: {'internal note' if is_internal else 'comment'} added",
        metadata={"is_internal": is_internal, "redaction_count": result.redaction_count},
    )
    return event


def reembed_all(*, batch_size: int = 100) -> dict[str, int]:
    """
    Re-embed every ticket and playbook. Used by `manage.py reembed`.

    Needed after changing `EMBEDDING_PROVIDER` or `EMBEDDING_DIM`: mixing vectors from two
    providers in one index produces cosine scores that are arithmetically valid and
    semantically meaningless, which is worse than no vector channel at all.
    """
    from playbooks.models import ResolutionPlaybook

    counts = {"tickets": 0, "playbooks": 0, "failed": 0}

    tickets = list(Ticket.objects.all().only("id", "search_text", "title", "description",
                                             "organization_id"))
    for index in range(0, len(tickets), batch_size):
        for ticket in tickets[index:index + batch_size]:
            provider, _ = embed_ticket(ticket)
            if provider == "none":
                counts["failed"] += 1
            else:
                counts["tickets"] += 1

    for playbook in ResolutionPlaybook.objects.all():
        text = playbook.search_text or f"{playbook.title}\n{playbook.description}"
        try:
            result = embedding_service.embed_text(text)
        except Exception:
            logger.exception("Failed to embed playbook %s", playbook.playbook_id)
            counts["failed"] += 1
            continue
        ResolutionPlaybook.objects.filter(pk=playbook.pk).update(
            embedding=result.vector,
            embedding_model=result.model,
            embedding_dim=result.dim,
        )
        retrieval.upsert_vector(
            "playbook", playbook.id, playbook.origin_organization_id, result.vector
        )
        counts["playbooks"] += 1

    return counts

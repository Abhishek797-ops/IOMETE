"""
Issue clustering.

Groups tickets that share a symptom signature so an FDE can see "eighteen tickets look like
this" instead of working through eighteen tickets.

The discipline that matters: **a cluster is a hypothesis.** Grouping tickets by shared
symptoms is useful triage and terrible epistemology — `OOMKilled` has at least four
distinct causes. So:

* `hypothesised_root_cause` is free text, always rendered as a working theory.
* `is_root_cause_confirmed` is set only by an FDE, explicitly, after investigating.
* The API returns both separately and the UI renders them differently. Nothing in the
  product presents a cluster as a confirmed shared cause on the strength of grouping alone.

Clusters are cross-tenant by nature, so they are FDE-only. The customer-facing API never
exposes cluster membership, and a cluster only ever reports an *affected organization
count*, never which organizations.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction
from django.utils.text import slugify

from accounts.models import User
from aiengine.models import GenerationPurpose
from aiengine.services import llm
from aiengine.services.normalization import symptom_label
from common.audit import record_audit
from common.exceptions import DomainValidationError

from ..models import ClusterStatus, IssueCluster, Ticket

logger = logging.getLogger("compass.clustering")

#: How much of a cluster's *core* signature a ticket must exhibit to join it.
#:
#: Measured as containment of the core in the ticket's symptoms, not Jaccard similarity
#: between the two sets. That distinction matters: one person writes "executors keep
#: restarting, the job fails, out of memory" and another writes only "out of memory". Those
#: are the same incident, but their Jaccard similarity is 0.33 and they would never group.
#: Containment asks the right question — "does this ticket show what characterises the
#: cluster?" — rather than "are these two descriptions equally detailed?".
JOIN_THRESHOLD = 0.6

#: Minimum tickets before a cluster is worth surfacing.
#:
#: Two is enough to be worth an FDE's attention when the symptoms are specific ("this has
#: happened twice"), and the UI always shows the size so nobody mistakes a pair for a
#: pattern. Requiring three would hide genuine early signals, which is the opposite of what
#: a recurrence detector is for.
MIN_CLUSTER_SIZE = 2


def _signature(ticket: Ticket) -> set[str]:
    return set((ticket.normalized or {}).get("symptoms") or [])


def _containment(core: set[str], candidate: set[str]) -> float:
    """
    How much of `core` is present in `candidate`, 0.0–1.0.

    Asymmetric on purpose. A terse ticket that exhibits every characteristic symptom of a
    cluster scores 1.0, which is correct — brevity is not dissimilarity.
    """
    if not core or not candidate:
        return 0.0
    return len(core & candidate) / len(core)


@transaction.atomic
def assign_cluster(ticket: Ticket) -> IssueCluster | None:
    """
    Find or create the cluster this ticket belongs to.

    Matching is by fingerprint first (strongest), then by component + category + symptom
    overlap. A ticket with no extracted symptoms and no fingerprint is left unclustered
    rather than placed in a catch-all — an unclustered ticket is honest; a wrongly clustered
    one actively misleads an FDE.
    """
    signature = _signature(ticket)

    if ticket.fingerprint_id:
        existing = (
            IssueCluster.objects.filter(fingerprints__id=ticket.fingerprint_id)
            .order_by("-updated_at")
            .first()
        )
        if existing:
            return _attach(ticket, existing)

    if not signature:
        return None

    # Component must match; category is *not* required to. Category is a hypothesis from
    # the same keyword extraction, and a ticket whose error text was terse often lands on
    # `unknown` while describing exactly the same problem. Requiring both would split a
    # genuine cluster in two on the basis of how much detail someone pasted.
    best: tuple[float, IssueCluster] | None = None
    for candidate in (
        IssueCluster.objects.filter(component=ticket.component)
        .exclude(status=ClusterStatus.CLOSED)
        .order_by("-updated_at")[:50]
    ):
        score = _containment(set(candidate.symptom_signature or []), signature)
        if score >= JOIN_THRESHOLD and (best is None or score > best[0]):
            best = (score, candidate)
    if best is not None:
        return _attach(ticket, best[1])

    # No match: start a new cluster.
    labels = [symptom_label(s) for s in sorted(signature)][:2]
    title = f"{ticket.get_component_display()}: {' + '.join(labels)}" if labels else (
        f"{ticket.get_component_display()}: {ticket.get_category_display()}"
    )
    base = slugify(title)[:100] or "issue-cluster"
    key = base
    suffix = 2
    while IssueCluster.objects.filter(key=key).exists():
        key = f"{base}-{suffix}"[:120]
        suffix += 1

    cluster = IssueCluster.objects.create(
        key=key,
        title=title[:250],
        description=(
            "Automatically grouped by shared symptom signature. This grouping is a triage "
            "hypothesis, not a confirmed shared root cause."
        ),
        component=ticket.component,
        category=ticket.category,
        symptom_signature=sorted(signature),
        common_error_codes=list((ticket.normalized or {}).get("error_codes") or [])[:10],
        status=ClusterStatus.OPEN,
        is_synthetic=ticket.is_synthetic,
    )
    return _attach(ticket, cluster)


def _attach(ticket: Ticket, cluster: IssueCluster) -> IssueCluster:
    Ticket.objects.filter(pk=ticket.pk).update(cluster=cluster)
    ticket.cluster = cluster
    if ticket.fingerprint_id:
        cluster.fingerprints.add(ticket.fingerprint)

    # Recompute the core signature as the *intersection* of its members' symptoms — the
    # symptoms that actually characterise the cluster.
    #
    # Widening to the union would be the obvious move and is wrong: the core is the
    # denominator in `_containment`, so a growing union makes the cluster progressively
    # harder to join, and a cluster that stops accepting its own kind of ticket is worse
    # than no cluster at all. Narrowing to the intersection makes the cluster converge on
    # what its members genuinely share.
    symptom_sets = [
        set((normalized or {}).get("symptoms") or [])
        for normalized in Ticket.objects.filter(cluster=cluster).values_list(
            "normalized", flat=True
        )
    ]
    symptom_sets = [symptoms for symptoms in symptom_sets if symptoms]
    if symptom_sets:
        core = set.intersection(*symptom_sets)
        if not core:
            # No symptom is universal. Fall back to those shared by most members, so the
            # cluster keeps a usable core rather than an empty one.
            counts: dict[str, int] = {}
            for symptoms in symptom_sets:
                for symptom in symptoms:
                    counts[symptom] = counts.get(symptom, 0) + 1
            peak = max(counts.values())
            core = {symptom for symptom, count in counts.items() if count == peak}
        cluster.symptom_signature = sorted(core)

    code_sets = [
        set((normalized or {}).get("error_codes") or [])
        for normalized in Ticket.objects.filter(cluster=cluster).values_list(
            "normalized", flat=True
        )
    ]
    code_sets = [codes for codes in code_sets if codes]
    if code_sets:
        shared = set.intersection(*code_sets) if len(code_sets) > 1 else code_sets[0]
        cluster.common_error_codes = sorted(shared)[:10]

    cluster.save(update_fields=["symptom_signature", "common_error_codes", "updated_at"])
    return cluster


def generate_hypothesis(*, cluster: IssueCluster, actor: User) -> dict:
    """
    Produce a grounded hypothesis and suggested investigation for a cluster.

    The output schema forces `is_confirmed: false` and a `confidence_statement` — the model
    is not permitted to express a cluster as a confirmed finding, because the data does not
    support that and a confident-sounding cluster summary is how an FDE gets sent down the
    wrong path for a day.
    """
    tickets = list(
        cluster.tickets.select_related("organization").order_by("-created_at")[:15]
    )
    sources = [
        llm.Source(
            id=ticket.reference,
            kind="ticket",
            title=ticket.title,
            body=(
                f"version: {ticket.iomete_version or 'unspecified'}\n"
                f"environment: {ticket.get_environment_display()}\n"
                f"deployment: {ticket.deployment_model}\n"
                f"cloud: {ticket.cloud_provider}\n"
                f"error_codes: {', '.join((ticket.normalized or {}).get('error_codes') or [])}\n"
                f"resolution_verified: {ticket.resolution_verified}\n"
                f"resolution: {ticket.resolution_summary[:500]}"
            ),
        )
        for ticket in tickets
    ]

    response = llm.generate(
        llm.GenerationRequest(
            purpose=GenerationPurpose.CLUSTER_HYPOTHESIS,
            instruction=json.dumps(
                {
                    "cluster": {
                        "title": cluster.title,
                        "ticket_count": cluster.ticket_count,
                        "component_label": cluster.get_component_display(),
                        "category_label": cluster.get_category_display(),
                        "symptom_labels": [
                            symptom_label(s) for s in (cluster.symptom_signature or [])
                        ],
                        "common_error_codes": cluster.common_error_codes,
                        "verified_resolution_count": cluster.verified_resolution_count,
                        "affected_organization_count": cluster.affected_organization_count,
                    }
                }
            ),
            sources=sources,
            schema={
                "type": "object",
                "properties": {
                    "hypothesis": {"type": "string"},
                    "is_confirmed": {"type": "boolean"},
                    "confidence_statement": {"type": "string"},
                    "suggested_investigation": {"type": "array", "items": {"type": "string"}},
                    "injection_noted": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["hypothesis", "confidence_statement"],
            },
            schema_name="cluster_hypothesis",
            organization=None,
            user=actor,
        )
    )

    data = response.data
    # Belt and braces: whatever a provider returns, a generated hypothesis is never
    # confirmed. Confirmation is a human act recorded by confirm_root_cause().
    data["is_confirmed"] = False

    IssueCluster.objects.filter(pk=cluster.pk).update(
        hypothesised_root_cause=data.get("hypothesis", "")[:4000]
    )
    return {
        **data,
        "provider": response.provider,
        "provider_is_live": response.is_live,
        "provider_notice": response.notice,
    }


@transaction.atomic
def confirm_root_cause(
    *, cluster: IssueCluster, reviewer: User, root_cause: str, notes: str = ""
) -> IssueCluster:
    """
    Record an FDE's confirmed root cause for a cluster.

    This is the only path that sets `is_root_cause_confirmed`. Restricted to IOMETE staff,
    and it requires the cause in writing — flipping a boolean without saying what the cause
    *is* would make the flag meaningless.
    """
    if not reviewer.is_iomete_staff:
        raise DomainValidationError(
            detail="Only an FDE or platform administrator can confirm a cluster's root cause."
        )
    if not root_cause.strip():
        raise DomainValidationError(
            detail="State the confirmed root cause. A confirmation flag without the cause "
            "recorded is not useful to the next engineer."
        )

    cluster.confirmed_root_cause = root_cause
    cluster.is_root_cause_confirmed = True
    cluster.status = ClusterStatus.ROOT_CAUSE_CONFIRMED
    if notes:
        cluster.investigation_notes = (
            f"{cluster.investigation_notes}\n\n{reviewer.email}: {notes}".strip()
        )
    cluster.owner = cluster.owner or reviewer
    cluster.save()

    record_audit(
        action="playbook.updated",
        actor=reviewer,
        target_type="issue_cluster",
        target_id=str(cluster.id),
        summary=f"Confirmed root cause for cluster “{cluster.title}”",
        metadata={"cluster_key": cluster.key, "ticket_count": cluster.ticket_count},
    )
    return cluster


@transaction.atomic
def update_status(
    *, cluster: IssueCluster, reviewer: User, status: str, notes: str = ""
) -> IssueCluster:
    if not reviewer.is_iomete_staff:
        raise DomainValidationError(detail="Only IOMETE staff can update a cluster.")
    if status not in {choice.value for choice in ClusterStatus}:
        raise DomainValidationError(detail=f"Unknown cluster status {status!r}.")
    if status == ClusterStatus.ROOT_CAUSE_CONFIRMED and not cluster.is_root_cause_confirmed:
        raise DomainValidationError(
            detail="Use the confirm-root-cause action, which requires the cause to be "
            "recorded, rather than setting this status directly."
        )

    cluster.status = status
    if notes:
        cluster.investigation_notes = (
            f"{cluster.investigation_notes}\n\n{reviewer.email}: {notes}".strip()
        )
    cluster.owner = cluster.owner or reviewer
    cluster.save(update_fields=["status", "investigation_notes", "owner", "updated_at"])
    return cluster


def significant_clusters(*, min_size: int = MIN_CLUSTER_SIZE):
    """
    Clusters worth an FDE's attention.

    Annotated rather than filtered in Python so the ordering happens in the database.
    """
    from django.db.models import Count, Q

    return (
        IssueCluster.objects.annotate(
            size=Count("tickets", distinct=True),
            open_count=Count(
                "tickets",
                filter=~Q(tickets__status__in=["resolved", "closed"]),
                distinct=True,
            ),
            verified_count=Count(
                "tickets", filter=Q(tickets__resolution_verified=True), distinct=True
            ),
            organization_count=Count("tickets__organization", distinct=True),
        )
        .filter(size__gte=min_size)
        .order_by("-size", "-updated_at")
    )


def recompute_all() -> dict[str, int]:
    """
    Re-cluster every ticket from scratch. Used by the seed command and after a bulk import.

    Clears existing assignments first so that changing `JOIN_THRESHOLD` actually takes
    effect rather than leaving historical groupings frozen at the old value.
    """
    Ticket.objects.update(cluster=None)
    IssueCluster.objects.filter(is_root_cause_confirmed=False).delete()

    assigned = 0
    for ticket in Ticket.objects.order_by("created_at").iterator(chunk_size=200):
        if assign_cluster(ticket) is not None:
            assigned += 1

    # Drop clusters that ended up too small to be meaningful, unless an FDE has invested
    # in them by confirming a cause. Counted before the delete so the figures reported are
    # the ones a reader expects.
    from django.db.models import Count

    too_small = IssueCluster.objects.annotate(size=Count("tickets")).filter(
        size__lt=MIN_CLUSTER_SIZE, is_root_cause_confirmed=False
    )
    pruned_count = too_small.count()
    too_small.delete()

    remaining = IssueCluster.objects.annotate(size=Count("tickets"))
    return {
        "tickets_assigned": assigned,
        "clusters": remaining.count(),
        "pruned": pruned_count,
        "largest_cluster_size": (
            remaining.order_by("-size").values_list("size", flat=True).first() or 0
        ),
    }

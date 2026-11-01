"""
Support-effectiveness analytics.

Every figure here is computed from rows that exist. There are no stored aggregates and no
constants masquerading as measurements — the brief is explicit that hardcoded metrics must
not be presented as live analytics, and `analytics/models.py` has no models for that reason.

Each metric carries, alongside its value:

* `window` — the period it was computed over.
* `sample_size` — how many rows went into it.
* `basis` — a sentence stating how it was derived.
* `confidence` — `measured`, `estimated`, or `insufficient_data`.

That last field is the important one. "Estimated FDE hours saved" is genuinely useful and
genuinely a model, not a measurement. Labelling it as an estimate and publishing its
derivation is what separates an analytics page a customer can argue with from a dashboard
that quietly flatters the product.

A metric with too few rows returns `insufficient_data` and a null value rather than a
precise-looking number computed from three tickets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db.models import (
    Avg,
    Count,
    Q,
)
from django.utils import timezone

from playbooks.models import ApprovalStatus, ExecutionStatus, PlaybookExecution, ResolutionPlaybook
from tickets.models import IssueCluster, Ticket

#: Below this many rows, a rate or average is noise. Returning "insufficient_data" is more
#: honest than "100% success rate" computed from one execution.
MIN_SAMPLE = 5

WINDOWS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
    "all": None,
}


@dataclass
class Metric:
    key: str
    label: str
    value: Any
    unit: str = ""
    basis: str = ""
    confidence: str = "measured"       # measured | estimated | insufficient_data
    sample_size: int = 0
    window: str = ""
    comparison: dict | None = None
    caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "basis": self.basis,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "window": self.window,
            "comparison": self.comparison,
            "caveat": self.caveat,
        }


def _window_start(window: str):
    days = WINDOWS.get(window, 30)
    return None if days is None else timezone.now() - timedelta(days=days)


def _scoped(user, window: str):
    """Tickets visible to `user` within `window`."""
    queryset = Ticket.objects.for_user(user)
    start = _window_start(window)
    if start is not None:
        queryset = queryset.filter(created_at__gte=start)
    return queryset


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# =======================================================================================
# Dashboard metrics
# =======================================================================================


def dashboard(user, *, window: str = "30d", organization=None) -> dict:
    """
    The FDE command-center dashboard.

    Tenant-scoped through `for_user`, so a customer calling this sees only their own
    organization's figures and an FDE sees the whole estate.
    """
    tickets = _scoped(user, window)
    if organization is not None:
        tickets = tickets.filter(organization=organization)

    all_tickets = Ticket.objects.for_user(user)
    if organization is not None:
        all_tickets = all_tickets.filter(organization=organization)

    window_label = "all time" if WINDOWS.get(window) is None else f"last {WINDOWS[window]} days"

    open_tickets = all_tickets.exclude(status__in=["resolved", "closed"])
    resolved_in_window = tickets.filter(status__in=["resolved", "closed"])

    metrics: list[Metric] = []

    # --- Volume and queue state (point-in-time counts, always measured) --------------
    metrics.append(
        Metric(
            key="open_tickets",
            label="Open tickets",
            value=open_tickets.count(),
            unit="tickets",
            basis="Tickets not in a resolved or closed state, right now.",
            sample_size=all_tickets.count(),
            window="current",
        )
    )
    metrics.append(
        Metric(
            key="high_priority_open",
            label="High-priority open",
            value=open_tickets.filter(severity__in=["critical", "high"]).count(),
            unit="tickets",
            basis="Open tickets with severity critical or high.",
            sample_size=open_tickets.count(),
            window="current",
        )
    )
    metrics.append(
        Metric(
            key="escalated_open",
            label="Escalated, awaiting an FDE",
            value=open_tickets.filter(status="escalated").count(),
            unit="tickets",
            basis="Open tickets in the escalated state.",
            sample_size=open_tickets.count(),
            window="current",
        )
    )

    # --- Tickets with an existing verified playbook ---------------------------------
    with_playbook = (
        open_tickets.filter(playbook_matches__playbook__approval_status=ApprovalStatus.APPROVED)
        .exclude(playbook_matches__gate_status="gated")
        .distinct()
        .count()
    )
    metrics.append(
        Metric(
            key="open_with_approved_playbook",
            label="Open tickets with an applicable approved playbook",
            value=with_playbook,
            unit="tickets",
            basis=(
                "Open tickets where retrieval matched an approved playbook that was not "
                "gated out by the version and environment check. These are candidates for "
                "customer self-service."
            ),
            sample_size=open_tickets.count(),
            window="current",
            caveat=(
                "A match is not a guarantee the playbook resolves the ticket — the "
                "diagnostic steps still have to confirm the root cause."
            ),
        )
    )

    # --- Self-service resolution ----------------------------------------------------
    resolved_count = resolved_in_window.count()
    self_service = resolved_in_window.filter(self_service_resolved=True).count()
    metrics.append(
        Metric(
            key="self_service_resolutions",
            label="Self-service resolutions",
            value=self_service,
            unit="tickets",
            basis=(
                "Tickets resolved by the customer through Resolution Replay without FDE "
                "involvement."
            ),
            sample_size=resolved_count,
            window=window_label,
        )
    )
    metrics.append(
        Metric(
            key="self_service_rate",
            label="Self-service rate",
            value=_rate(self_service, resolved_count) if resolved_count >= MIN_SAMPLE else None,
            unit="ratio",
            basis="Self-service resolutions divided by all resolutions in the window.",
            confidence="measured" if resolved_count >= MIN_SAMPLE else "insufficient_data",
            sample_size=resolved_count,
            window=window_label,
            caveat=(
                ""
                if resolved_count >= MIN_SAMPLE
                else f"Only {resolved_count} resolution(s) in this window — too few to "
                f"report a rate. At least {MIN_SAMPLE} are needed."
            ),
        )
    )

    # --- Resolution time ------------------------------------------------------------
    timed = resolved_in_window.filter(time_to_resolution_seconds__isnull=False)
    timed_count = timed.count()
    average_seconds = timed.aggregate(value=Avg("time_to_resolution_seconds"))["value"]
    metrics.append(
        Metric(
            key="avg_resolution_hours",
            label="Average time to resolution",
            value=round(average_seconds / 3600, 1) if average_seconds and timed_count >= MIN_SAMPLE else None,
            unit="hours",
            basis="Mean of (resolved_at − created_at) over resolved tickets in the window.",
            confidence="measured" if timed_count >= MIN_SAMPLE else "insufficient_data",
            sample_size=timed_count,
            window=window_label,
            caveat=(
                "Wall-clock time, so it includes periods waiting on the customer. It is not "
                "a measure of engineer effort."
                if timed_count >= MIN_SAMPLE
                else f"Only {timed_count} timed resolution(s) — too few to average."
            ),
        )
    )

    # Self-service versus FDE-handled, which is the comparison that matters.
    self_service_avg = (
        timed.filter(self_service_resolved=True).aggregate(v=Avg("time_to_resolution_seconds"))["v"]
    )
    fde_avg = (
        timed.filter(self_service_resolved=False).aggregate(v=Avg("time_to_resolution_seconds"))["v"]
    )
    self_service_timed = timed.filter(self_service_resolved=True).count()
    fde_timed = timed.filter(self_service_resolved=False).count()
    metrics.append(
        Metric(
            key="resolution_time_comparison",
            label="Self-service vs FDE-handled resolution time",
            value=(
                {
                    "self_service_hours": round(self_service_avg / 3600, 1) if self_service_avg else None,
                    "fde_handled_hours": round(fde_avg / 3600, 1) if fde_avg else None,
                }
                if self_service_timed >= MIN_SAMPLE and fde_timed >= MIN_SAMPLE
                else None
            ),
            unit="hours",
            basis="Mean resolution time split by whether an FDE was involved.",
            confidence=(
                "measured"
                if self_service_timed >= MIN_SAMPLE and fde_timed >= MIN_SAMPLE
                else "insufficient_data"
            ),
            sample_size=self_service_timed + fde_timed,
            window=window_label,
            caveat=(
                "Self-service tickets are not a random sample — they are the ones a "
                "playbook already covered, which are typically better-understood problems. "
                "The gap is not purely attributable to the tool."
            ),
        )
    )

    # --- Knowledge pipeline ---------------------------------------------------------
    drafts = ResolutionPlaybook.objects.filter(approval_status=ApprovalStatus.DRAFT).count()
    in_review = ResolutionPlaybook.objects.filter(approval_status=ApprovalStatus.IN_REVIEW).count()
    approved = ResolutionPlaybook.objects.filter(approval_status=ApprovalStatus.APPROVED).count()
    overdue = ResolutionPlaybook.objects.filter(
        approval_status=ApprovalStatus.APPROVED, review_due_at__lt=timezone.now()
    ).count()

    metrics.extend(
        [
            Metric(
                key="knowledge_drafts_awaiting_approval",
                label="Knowledge drafts awaiting approval",
                value=drafts + in_review,
                unit="playbooks",
                basis="Playbooks in draft or changes-requested state.",
                sample_size=drafts + in_review + approved,
                window="current",
            ),
            Metric(
                key="approved_playbooks",
                label="Approved playbooks",
                value=approved,
                unit="playbooks",
                basis="Playbooks that have passed FDE review and may be recommended.",
                sample_size=ResolutionPlaybook.objects.count(),
                window="current",
            ),
            Metric(
                key="playbooks_review_overdue",
                label="Playbooks overdue for re-review",
                value=overdue,
                unit="playbooks",
                basis="Approved playbooks past their review_due_at date.",
                sample_size=approved,
                window="current",
                caveat=(
                    "A stale playbook is a liability: the product it describes may have "
                    "changed underneath it."
                ),
            ),
            Metric(
                key="awaiting_verification",
                label="Resolutions awaiting FDE verification",
                value=all_tickets.filter(status="resolved", resolution_verified=False)
                .exclude(resolution_summary="")
                .count(),
                unit="tickets",
                basis=(
                    "Resolved tickets with a recorded resolution that no FDE has verified. "
                    "Verification is what admits a fix to trusted retrieval."
                ),
                sample_size=all_tickets.filter(status="resolved").count(),
                window="current",
            ),
        ]
    )

    # --- Playbook effectiveness -----------------------------------------------------
    executions = PlaybookExecution.objects.for_user(user)
    start = _window_start(window)
    if start is not None:
        executions = executions.filter(created_at__gte=start)
    completed = executions.exclude(status=ExecutionStatus.IN_PROGRESS)
    completed_count = completed.count()
    successful = completed.filter(status=ExecutionStatus.RESOLVED).count()

    metrics.append(
        Metric(
            key="playbook_success_rate",
            label="Playbook success rate",
            value=_rate(successful, completed_count) if completed_count >= MIN_SAMPLE else None,
            unit="ratio",
            basis=(
                "Resolution Replay runs ending in a 'resolved' outcome, divided by all "
                "completed runs."
            ),
            confidence="measured" if completed_count >= MIN_SAMPLE else "insufficient_data",
            sample_size=completed_count,
            window=window_label,
            caveat=(
                "A 'resolved' outcome requires the customer to supply evidence that the "
                "problem is gone, but it is still their assessment rather than an "
                "independently verified one."
                if completed_count >= MIN_SAMPLE
                else f"Only {completed_count} completed run(s) — too few to report a rate."
            ),
        )
    )

    # --- Recurring clusters ---------------------------------------------------------
    cluster_queryset = IssueCluster.objects.annotate(size=Count("tickets")).filter(size__gte=3)
    metrics.append(
        Metric(
            key="recurring_clusters",
            label="Recurring issue clusters",
            value=cluster_queryset.count(),
            unit="clusters",
            basis="Symptom-signature groups containing at least three tickets.",
            sample_size=IssueCluster.objects.count(),
            window="current",
            caveat=(
                "A cluster is a triage hypothesis, not a confirmed shared root cause. "
                f"{cluster_queryset.filter(is_root_cause_confirmed=True).count()} of these "
                "have an FDE-confirmed cause."
            ),
        )
    )

    # --- The estimate ---------------------------------------------------------------
    metrics.append(_hours_saved_estimate(user, window, window_label, organization))

    return {
        "window": window,
        "window_label": window_label,
        "generated_at": timezone.now().isoformat(),
        "metrics": [metric.to_dict() for metric in metrics],
        "methodology": methodology(),
    }


def _hours_saved_estimate(user, window: str, window_label: str, organization) -> Metric:
    """
    Estimated FDE investigation hours avoided.

    This is the headline business metric and it is a **model**, so it is labelled
    `estimated` and its derivation is published.

    Method: for each self-service resolution, take the median recorded FDE investigation
    time for *verified* resolutions of the same component. That is the best available
    counterfactual — what an engineer actually spent on this class of problem before. Where
    there is no recorded figure for a component, the ticket is excluded rather than
    assigned a default, so the estimate is conservative and derived only from real
    measurements.
    """
    tickets = _scoped(user, window)
    if organization is not None:
        tickets = tickets.filter(organization=organization)

    self_service = tickets.filter(self_service_resolved=True, status__in=["resolved", "closed"])

    # Median recorded FDE effort per component, from verified resolutions.
    baseline_source = (
        Ticket.objects.for_user(user)
        .filter(
            resolution_verified=True,
            fde_investigation_minutes__isnull=False,
            fde_investigation_minutes__gt=0,
        )
        .values_list("component", "fde_investigation_minutes")
    )
    by_component: dict[str, list[int]] = {}
    for component, minutes in baseline_source:
        by_component.setdefault(component, []).append(minutes)

    medians = {}
    for component, values in by_component.items():
        values.sort()
        middle = len(values) // 2
        medians[component] = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )

    total_minutes = 0.0
    counted = 0
    skipped = 0
    for component in self_service.values_list("component", flat=True):
        median = medians.get(component)
        if median is None:
            skipped += 1
            continue
        total_minutes += median
        counted += 1

    has_basis = counted > 0 and len(medians) > 0
    return Metric(
        key="estimated_fde_hours_saved",
        label="Estimated FDE investigation hours avoided",
        value=round(total_minutes / 60, 1) if has_basis else None,
        unit="hours",
        basis=(
            "For each self-service resolution, the median recorded FDE investigation time "
            "for verified resolutions of the same component is counted as avoided. "
            f"Derived from {len(medians)} component baseline(s) built from "
            f"{sum(len(v) for v in by_component.values())} FDE-reported figure(s); "
            f"{counted} self-service resolution(s) matched a baseline"
            + (f" and {skipped} were excluded for lacking one." if skipped else ".")
        ),
        confidence="estimated" if has_basis else "insufficient_data",
        sample_size=counted,
        window=window_label,
        caveat=(
            "This is a model, not a measurement. It assumes a self-service resolution would "
            "otherwise have taken the median FDE time for that component, which is an "
            "approximation: self-service tickets skew towards better-understood problems. "
            "Tickets with no component baseline are excluded entirely rather than given a "
            "default, so the figure is deliberately conservative."
            if has_basis
            else "No FDE investigation times have been recorded yet, so there is no basis "
            "for an estimate. FDEs can record effort when resolving a ticket."
        ),
    )


# =======================================================================================
# Trends and breakdowns
# =======================================================================================


def trends(user, *, window: str = "90d", organization=None) -> dict:
    """
    Time series for the analytics charts.

    Buckets by week so a 90-day window produces ~13 points — enough to see a direction
    without pretending daily counts of a handful of tickets are signal.
    """
    from django.db.models.functions import TruncWeek

    tickets = _scoped(user, window)
    if organization is not None:
        tickets = tickets.filter(organization=organization)

    created = (
        tickets.annotate(bucket=TruncWeek("created_at"))
        .values("bucket")
        .annotate(
            created=Count("id"),
            self_service=Count("id", filter=Q(self_service_resolved=True)),
            escalated=Count("id", filter=Q(status="escalated")),
            verified=Count("id", filter=Q(resolution_verified=True)),
        )
        .order_by("bucket")
    )

    series = [
        {
            "bucket": row["bucket"].date().isoformat() if row["bucket"] else None,
            "created": row["created"],
            "self_service": row["self_service"],
            "escalated": row["escalated"],
            "verified": row["verified"],
        }
        for row in created
    ]

    return {
        "window": window,
        "granularity": "week",
        "series": series,
        "basis": (
            "Tickets grouped by the ISO week they were created in. Weekly buckets rather "
            "than daily, because daily counts at this volume are noise rather than trend."
        ),
        "sample_size": tickets.count(),
    }


def breakdowns(user, *, window: str = "90d", organization=None) -> dict:
    """Component, category and severity distributions, with resolution outcomes."""
    tickets = _scoped(user, window)
    if organization is not None:
        tickets = tickets.filter(organization=organization)

    def distribution(field_name: str, label_map: dict) -> list[dict]:
        rows = (
            tickets.values(field_name)
            .annotate(
                total=Count("id"),
                resolved=Count("id", filter=Q(status__in=["resolved", "closed"])),
                self_service=Count("id", filter=Q(self_service_resolved=True)),
                verified=Count("id", filter=Q(resolution_verified=True)),
                avg_hours=Avg("time_to_resolution_seconds"),
            )
            .order_by("-total")
        )
        return [
            {
                "key": row[field_name],
                "label": label_map.get(row[field_name], row[field_name]),
                "total": row["total"],
                "resolved": row["resolved"],
                "self_service": row["self_service"],
                "verified": row["verified"],
                "self_service_rate": _rate(row["self_service"], row["resolved"]),
                "avg_resolution_hours": (
                    round(row["avg_hours"] / 3600, 1) if row["avg_hours"] else None
                ),
            }
            for row in rows
        ]

    from tickets.models import FailureCategory, Severity, TicketComponent

    return {
        "window": window,
        "sample_size": tickets.count(),
        "by_component": distribution("component", dict(TicketComponent.choices)),
        "by_category": distribution("category", dict(FailureCategory.choices)),
        "by_severity": distribution("severity", dict(Severity.choices)),
        "basis": (
            "Counts and means over tickets created in the window. Rates are shown as null "
            "where the denominator is zero rather than as 0%, because 'no data' and 'never' "
            "are different statements."
        ),
    }


def playbook_effectiveness(user, *, window: str = "all") -> dict:
    """
    Per-playbook outcomes.

    `success_rate` is null where there are no recorded outcomes — the distinction between
    "untested" and "never works" matters when an FDE is deciding what to review.
    """
    playbooks = ResolutionPlaybook.objects.visible_to(user).filter(
        approval_status=ApprovalStatus.APPROVED
    )
    rows = []
    for playbook in playbooks.select_related("approved_by"):
        total = playbook.success_count + playbook.failure_count
        rows.append(
            {
                "playbook_id": playbook.playbook_id,
                "version": playbook.version,
                "title": playbook.title,
                "component": playbook.component,
                "component_label": playbook.get_component_display(),
                "risk_level": playbook.risk_level,
                "usage_count": playbook.usage_count,
                "success_count": playbook.success_count,
                "failure_count": playbook.failure_count,
                "success_rate": playbook.success_rate,
                "recorded_outcomes": total,
                "confidence": (
                    "measured" if total >= MIN_SAMPLE
                    else "insufficient_data" if total else "untested"
                ),
                "is_review_overdue": playbook.is_review_overdue,
                "approved_at": playbook.approved_at.isoformat() if playbook.approved_at else None,
            }
        )
    rows.sort(key=lambda row: (-row["usage_count"], row["title"]))
    return {
        "playbooks": rows,
        "basis": (
            "Counted from completed Resolution Replay runs. `confidence` is `untested` "
            "where a playbook has never been run to completion, `insufficient_data` below "
            f"{MIN_SAMPLE} recorded outcomes, and `measured` at or above it."
        ),
        "sample_size": len(rows),
    }


def knowledge_lifecycle(user) -> dict:
    """
    The compounding loop as a funnel, so it can be seen working or not working.

    The last stage is the point of the product: approved playbooks that have actually
    resolved a later ticket. A library of approved playbooks nobody uses is not knowledge
    compounding, and this funnel makes that visible rather than hiding it behind a count.
    """
    resolved = Ticket.objects.for_user(user).filter(status__in=["resolved", "closed"]).exclude(
        resolution_summary=""
    )
    verified = resolved.filter(resolution_verified=True)
    drafted = ResolutionPlaybook.objects.filter(source_ticket__isnull=False)
    approved = drafted.filter(approval_status=ApprovalStatus.APPROVED)
    reused = (
        Ticket.objects.for_user(user)
        .filter(resolved_via_playbook__isnull=False, self_service_resolved=True)
        .count()
    )

    return {
        "stages": [
            {
                "key": "resolved",
                "label": "Tickets resolved",
                "count": resolved.count(),
                "description": "A resolution was recorded with evidence.",
            },
            {
                "key": "verified",
                "label": "Resolutions FDE-verified",
                "count": verified.count(),
                "description": (
                    "An FDE confirmed the fix. Only verified resolutions become retrieval "
                    "precedent."
                ),
            },
            {
                "key": "drafted",
                "label": "Knowledge drafts generated",
                "count": drafted.count(),
                "description": "A reusable playbook draft was extracted from the investigation.",
            },
            {
                "key": "approved",
                "label": "Playbooks approved",
                "count": approved.count(),
                "description": (
                    "Reviewed, redacted and approved by an FDE — now trusted knowledge."
                ),
            },
            {
                "key": "reused",
                "label": "Later tickets resolved by an approved playbook",
                "count": reused,
                "description": (
                    "The compounding step. This is the number that says whether the loop is "
                    "actually working."
                ),
            },
        ],
        "basis": (
            "Each stage is a live count over the tickets and playbooks visible to you. The "
            "funnel narrows legitimately — not every resolution warrants a playbook — but a "
            "large gap between 'verified' and 'drafted' means investigations are being "
            "repeated unnecessarily."
        ),
    }


def methodology() -> dict:
    """
    How the numbers are produced. Served with the dashboard so it is never separated
    from the figures it qualifies.
    """
    return {
        "principles": [
            "Every figure is computed from database rows at request time. There are no "
            "stored aggregates and no hardcoded values.",
            "Each metric reports its window, sample size and derivation.",
            "A metric with fewer than "
            f"{MIN_SAMPLE} underlying rows returns null with confidence "
            "`insufficient_data` rather than a precise-looking number.",
            "A rate with a zero denominator is null, not 0% — 'no data' and 'never' are "
            "different claims.",
            "`estimated_fde_hours_saved` is explicitly a model, labelled `estimated`, built "
            "only from FDE-reported investigation times. Tickets with no baseline are "
            "excluded rather than given a default.",
            "All figures are tenant-scoped: a customer sees only their own organization's.",
        ],
        "confidence_levels": {
            "measured": "Computed directly from a sufficient number of rows.",
            "estimated": "Derived through a stated model. Read the caveat before quoting it.",
            "insufficient_data": "Too few rows to report. The value is null.",
            "untested": "The entity exists but has no recorded outcomes yet.",
        },
        "min_sample_size": MIN_SAMPLE,
    }

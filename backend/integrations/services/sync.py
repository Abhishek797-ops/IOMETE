"""
Ticket synchronisation and connection testing.

The sync service is provider-agnostic: it depends on the `TicketProvider` protocol, so the
same code path runs against live Jira and against the mock provider. That is what makes the
demo honest — the field mapping, deduplication, retry and audit logic being demonstrated is
the real implementation, with only the transport simulated.

Every run produces an `IntegrationSyncRun` row carrying `was_simulated`, so a simulated
sync can never be presented as a real one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from accounts.models import Organization, User
from common.audit import record_audit
from common.exceptions import DomainValidationError
from tickets.models import Severity, Ticket, TicketComponent, TicketEvent, TicketEventType
from tickets.services import clustering, intake

from ..models import (
    IntegrationConfiguration,
    IntegrationMode,
    IntegrationSyncRun,
    SyncStatus,
)
from .base import ConnectionResult
from .registry import adapter_for, ticket_provider

logger = logging.getLogger("compass.integrations.sync")

#: How many times to retry a *read*. Reads are idempotent so retrying is safe; writes are
#: not retried automatically because a repeated issue creation produces duplicates.
READ_RETRIES = 2
RETRY_BACKOFF_SECONDS = (0.5, 1.5)


# =======================================================================================
# Connection testing — the only path that can set CONNECTED
# =======================================================================================


@transaction.atomic
def test_connection(
    *, configuration: IntegrationConfiguration, actor: User | None = None
) -> ConnectionResult:
    """
    Run a real connection test and derive the configuration's mode from the outcome.

    This is the **only** function in the codebase that can produce
    `IntegrationMode.CONNECTED`, and it can only do so when an adapter's real request
    succeeded. `mark_connection_result()` then recomputes the mode from facts, so a failure
    demotes a previously-connected integration back to `configured` rather than leaving a
    stale green light.
    """
    adapter = adapter_for(configuration)
    result = adapter.test_connection()

    configuration.mark_connection_result(
        ok=result.ok, message=result.message, detail=result.evidence
    )
    if configuration.pk:
        configuration.save(
            update_fields=[
                "last_connection_test_at", "last_connection_ok",
                "last_connection_message", "connection_detail", "mode", "updated_at",
            ]
        )

    record_audit(
        action="integration.connection_tested",
        actor=actor,
        organization=configuration.organization,
        target_type="integration",
        target_id=str(configuration.pk or configuration.provider),
        summary=(
            f"{configuration.provider}: connection test "
            f"{'succeeded' if result.ok else 'failed'} — {result.message[:200]}"
        ),
        metadata={
            "provider": configuration.provider,
            "ok": result.ok,
            "resulting_mode": configuration.mode,
            "error_code": result.error_code,
            # `evidence` is non-secret by construction (see base.ConnectionResult), and
            # record_audit redacts anything key-like as a second line of defence.
            "evidence": result.evidence,
        },
    )
    return result


# =======================================================================================
# Inbound synchronisation
# =======================================================================================


@dataclass
class SyncResult:
    run: IntegrationSyncRun
    created: list[Ticket] = field(default_factory=list)
    updated: list[Ticket] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    was_simulated: bool = False
    message: str = ""


#: Jira component / label hints → COMPASS component. Deliberately conservative: anything
#: unrecognised becomes `OTHER` and the normalisation service infers from the text instead,
#: which is more reliable than a guessy keyword table.
_COMPONENT_HINTS = {
    "compute": TicketComponent.SPARK_COMPUTE,
    "spark": TicketComponent.SPARK_COMPUTE,
    "jobs": TicketComponent.SPARK_JOBS,
    "kubernetes": TicketComponent.KUBERNETES,
    "infrastructure": TicketComponent.KUBERNETES,
    "catalog": TicketComponent.ICEBERG_CATALOG,
    "iceberg": TicketComponent.ICEBERG_METADATA,
    "metadata": TicketComponent.ICEBERG_METADATA,
    "sql": TicketComponent.SQL_SERVICE,
    "governance": TicketComponent.PERMISSIONS,
    "permissions": TicketComponent.PERMISSIONS,
    "ranger": TicketComponent.PERMISSIONS,
    "identity": TicketComponent.IDENTITY_SSO,
    "sso": TicketComponent.IDENTITY_SSO,
    "ingestion": TicketComponent.DATA_INGESTION,
    "event-streams": TicketComponent.DATA_INGESTION,
    "storage": TicketComponent.OBJECT_STORAGE,
    "gateway": TicketComponent.GATEWAY_NETWORK,
    "network": TicketComponent.GATEWAY_NETWORK,
    "jupyter": TicketComponent.JUPYTER,
    "notebook": TicketComponent.JUPYTER,
    "upgrade": TicketComponent.UPGRADE,
}

_PRIORITY_TO_SEVERITY = {
    "highest": Severity.CRITICAL,
    "blocker": Severity.CRITICAL,
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "major": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "normal": Severity.MEDIUM,
    "low": Severity.LOW,
    "minor": Severity.LOW,
    "lowest": Severity.LOW,
    "trivial": Severity.LOW,
}


def _map_component(issue: dict) -> str:
    haystack = " ".join(
        [*(issue.get("components") or []), *(issue.get("labels") or [])]
    ).lower()
    for hint, component in _COMPONENT_HINTS.items():
        if hint in haystack:
            return component
    return TicketComponent.OTHER


def _map_severity(issue: dict) -> str:
    return _PRIORITY_TO_SEVERITY.get(
        str(issue.get("priority") or "").strip().lower(), Severity.MEDIUM
    )


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.get_current_timezone())
    return parsed


def _fetch_with_retry(provider, *, since, limit: int) -> list[dict]:
    """
    Fetch issues, retrying on failure.

    Only reads are retried. The backoff is short and bounded — a sync that cannot read
    after three attempts should fail visibly and be recorded, not hammer the remote system.
    """
    last_error: Exception | None = None
    for attempt in range(READ_RETRIES + 1):
        try:
            return provider.fetch_issues(since=since, limit=limit)
        except Exception as exc:
            last_error = exc
            if attempt < READ_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
                logger.warning(
                    "Issue fetch attempt %d failed (%s); retrying.", attempt + 1,
                    exc.__class__.__name__,
                )
    raise last_error if last_error else RuntimeError("Issue fetch failed.")


def sync_inbound(
    *,
    organization: Organization,
    actor: User | None = None,
    limit: int = 25,
    since=None,
    configuration: IntegrationConfiguration | None = None,
) -> SyncResult:
    """
    Import issues from the ticket provider into COMPASS tickets.

    Deduplicated on `external_reference`, so re-running is safe and idempotent — an
    existing ticket is updated rather than duplicated.

    Imported descriptions go through the full intake pipeline (redact → normalise →
    fingerprint → embed), because an issue pasted into Jira is exactly as likely to contain
    a credential as one submitted through COMPASS.
    """
    provider = (
        adapter_for(configuration) if configuration is not None
        else ticket_provider(organization=organization)
    )
    description = provider.describe()
    simulated = description.is_simulated

    if configuration is None:
        configuration = _ensure_run_target(provider, organization)

    run = IntegrationSyncRun.objects.create(
        integration=configuration,
        direction="inbound",
        status=SyncStatus.SUCCESS,
        started_at=timezone.now(),
        was_simulated=simulated,
    )

    result = SyncResult(run=run, was_simulated=simulated)

    try:
        issues = _fetch_with_retry(provider, since=since, limit=limit)
    except Exception as exc:
        run.status = SyncStatus.FAILED
        run.finished_at = timezone.now()
        run.error_code = exc.__class__.__name__
        # The exception *message* is kept (it is our own formatted text from
        # `request_json`, never a remote response body), so an operator can diagnose.
        run.error_message = str(exc)[:2000]
        run.save()
        record_audit(
            action="integration.sync_run",
            actor=actor,
            organization=organization,
            target_type="integration_sync_run",
            target_id=str(run.id),
            summary=f"Inbound sync failed: {exc.__class__.__name__}",
            metadata={"simulated": simulated, "error": str(exc)[:400]},
        )
        result.message = f"Synchronisation failed: {exc}"
        return result

    run.records_seen = len(issues)

    for issue in issues:
        key = issue.get("external_key") or issue.get("external_id") or ""
        if not key:
            result.failed.append({"issue": issue, "reason": "No external key or id."})
            continue
        try:
            with transaction.atomic():
                existing = Ticket.objects.filter(
                    organization=organization, external_reference=key
                ).first()
                if existing is not None:
                    _update_from_issue(existing, issue, actor=actor)
                    result.updated.append(existing)
                else:
                    created = _create_from_issue(
                        issue, organization=organization, actor=actor, simulated=simulated
                    )
                    result.created.append(created)
        except Exception as exc:
            logger.exception("Failed to import issue %s", key)
            result.failed.append({"key": key, "reason": f"{exc.__class__.__name__}: {exc}"})

    run.records_created = len(result.created)
    run.records_updated = len(result.updated)
    run.records_failed = len(result.failed)
    run.finished_at = timezone.now()
    run.status = (
        SyncStatus.SUCCESS
        if not result.failed
        else SyncStatus.PARTIAL if (result.created or result.updated) else SyncStatus.FAILED
    )
    run.detail = {
        "created": [ticket.reference for ticket in result.created],
        "updated": [ticket.reference for ticket in result.updated],
        "failed": result.failed[:10],
        "provider_mode": description.mode,
    }
    run.save()

    if configuration.pk:
        configuration.last_sync_at = run.finished_at
        configuration.last_sync_status = run.status
        configuration.save(update_fields=["last_sync_at", "last_sync_status", "updated_at"])

    record_audit(
        action="integration.sync_run",
        actor=actor,
        organization=organization,
        target_type="integration_sync_run",
        target_id=str(run.id),
        summary=(
            f"Inbound sync {run.status}: {run.records_created} created, "
            f"{run.records_updated} updated, {run.records_failed} failed"
            + (" (simulated)" if simulated else "")
        ),
        metadata={
            "simulated": simulated,
            "provider": description.provider,
            "mode": description.mode,
        },
    )

    result.message = (
        f"{run.records_created} ticket(s) created, {run.records_updated} updated"
        + (f", {run.records_failed} failed" if run.records_failed else "")
        + (
            ". This was a simulated synchronisation: no external system was contacted."
            if simulated
            else "."
        )
    )
    return result


def _ensure_run_target(provider, organization: Organization) -> IntegrationConfiguration:
    """
    A persisted configuration to attach the run to.

    An env-configured or demo provider has no database row, but the run history still has
    to be recorded somewhere auditable — so a demo-mode row is created on first use rather
    than losing the record.
    """
    from ..models import IntegrationProvider

    configuration, _created = IntegrationConfiguration.objects.get_or_create(
        provider=IntegrationProvider.JIRA,
        organization=organization,
        defaults={
            "display_name": "Jira (demo provider)",
            "config": {"source": "auto-created-for-sync-history"},
            "credentials": {},
            "is_enabled": True,
            "mode": IntegrationMode.DEMO,
        },
    )
    return configuration


def _create_from_issue(
    issue: dict, *, organization: Organization, actor: User | None, simulated: bool
) -> Ticket:
    body = issue.get("description") or issue.get("summary") or ""
    # The intake service redacts, normalises, fingerprints and embeds — imported content
    # gets exactly the same treatment as a direct submission.
    intake_result = intake.create_ticket(
        organization=organization,
        reporter=actor,
        title=(issue.get("summary") or "Imported issue")[:250],
        description=body if len(body) >= 20 else f"{body}\n\n(Imported from {issue.get('external_key')})",
        component=_map_component(issue),
        severity=_map_severity(issue),
        environment="unknown",
        error_message=_extract_error_line(body),
        external_provider="jira" if not simulated else "jira-demo",
        external_reference=issue.get("external_key") or issue.get("external_id") or "",
        external_url=issue.get("external_url") or "",
        created_at_override=_parse_timestamp(issue.get("created_at")),
        is_synthetic=simulated,
    )
    ticket = intake_result.ticket
    Ticket.objects.filter(pk=ticket.pk).update(external_synced_at=timezone.now())
    clustering.assign_cluster(ticket)

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.EXTERNAL_SYNC,
        author=actor,
        author_label=actor.email if actor else "system",
        body=(
            f"Imported from {issue.get('external_key')}"
            + (" (simulated provider — no external system was contacted)." if simulated else ".")
        ),
        is_internal=True,
        metadata={
            "external_key": issue.get("external_key"),
            "external_status": issue.get("status"),
            "external_priority": issue.get("priority"),
            "simulated": simulated,
        },
    )
    return ticket


def _update_from_issue(ticket: Ticket, issue: dict, *, actor: User | None) -> Ticket:
    """
    Update an already-imported ticket.

    Only external metadata is refreshed. The ticket's own `status` is *not* overwritten
    from Jira: COMPASS's status reflects where the resolution workflow has got to, and
    letting an external system reset it would discard a Resolution Replay in progress.
    """
    changed: list[str] = []
    external_url = issue.get("external_url") or ""
    if external_url and ticket.external_url != external_url:
        ticket.external_url = external_url
        changed.append("external_url")

    ticket.external_synced_at = timezone.now()
    changed.append("external_synced_at")
    ticket.save(update_fields=[*changed, "updated_at"])

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.EXTERNAL_SYNC,
        author=actor,
        author_label=actor.email if actor else "system",
        body=(
            f"Re-synchronised with {issue.get('external_key')}. External status: "
            f"{issue.get('status') or 'unknown'}. COMPASS status left unchanged so the "
            "resolution workflow is not disturbed."
        ),
        is_internal=True,
        metadata={
            "external_status": issue.get("status"),
            "external_priority": issue.get("priority"),
        },
    )
    return ticket


def _extract_error_line(body: str) -> str:
    """
    Pull the most error-looking line out of an imported description.

    Worth doing because the error line is the strongest retrieval signal, and in Jira it is
    usually buried in a prose description rather than in its own field.
    """
    import re

    pattern = re.compile(
        r"(?:Exception|Error|Failure|FAILED|Caused by|OOMKilled|CrashLoopBackOff|"
        r"Permission denied|Timed out|timeout)",
        re.I,
    )
    candidates = [line.strip() for line in (body or "").splitlines() if pattern.search(line)]
    return candidates[0][:2000] if candidates else ""


# =======================================================================================
# Outbound
# =======================================================================================


def push_escalation(
    *, ticket: Ticket, actor: User, summary_text: str = ""
) -> dict:
    """
    Create an issue in the external ticketing system for an escalated ticket.

    Writes are *not* retried automatically: a retried create produces a duplicate issue,
    and a duplicate in a support queue costs an engineer's attention. A failure returns an
    actionable message and the caller can retry deliberately.
    """
    provider = ticket_provider(organization=ticket.organization)
    description = provider.describe()

    body = summary_text or (
        f"Escalated from IOMETE COMPASS.\n\n"
        f"Reference: {ticket.reference}\n"
        f"Component: {ticket.get_component_display()}\n"
        f"Severity: {ticket.get_severity_display()}\n"
        f"IOMETE version: {ticket.iomete_version or 'unspecified'}\n"
        f"Environment: {ticket.get_environment_display()}\n\n"
        f"{ticket.description[:4000]}\n\n"
        f"Escalation reason:\n{ticket.escalation_reason[:2000]}"
    )

    created = provider.create_issue(
        summary=f"[{ticket.reference}] {ticket.title}"[:255],
        description=body,
        labels=["compass", ticket.component],
    )

    if created.get("key"):
        Ticket.objects.filter(pk=ticket.pk).update(
            external_provider=description.provider if not created.get("simulated") else "jira-demo",
            external_reference=created["key"],
            external_url=created.get("url", ""),
            external_synced_at=timezone.now(),
        )

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.EXTERNAL_SYNC,
        author=actor,
        author_label=actor.email,
        body=(
            f"Created {created.get('key')} in the ticketing system."
            if not created.get("simulated")
            else (
                f"Simulated creation of {created.get('key')}. No external system was "
                "contacted — configure and verify a Jira integration to create real issues."
            )
        ),
        is_internal=True,
        metadata={"external_key": created.get("key"), "simulated": created.get("simulated", True)},
    )
    record_audit(
        action="integration.sync_run",
        actor=actor,
        organization=ticket.organization,
        target_type="ticket",
        target_id=str(ticket.id),
        summary=(
            f"{ticket.reference}: pushed to {created.get('key')}"
            + (" (simulated)" if created.get("simulated") else "")
        ),
        metadata={"simulated": created.get("simulated", True)},
    )
    return {
        **created,
        "mode": description.mode,
        "is_simulated": bool(created.get("simulated")),
    }


def configure_webhook_secret(*, configuration: IntegrationConfiguration, secret: str) -> None:
    """
    Store a webhook shared secret.

    Webhook handling is only enabled once a secret is configured *and* the integration has
    verified connectivity — an unauthenticated webhook endpoint that creates tickets is an
    open door, so `webhook_configured` gates it.
    """
    if not secret or len(secret) < 16:
        raise DomainValidationError(
            detail="A webhook secret must be at least 16 characters. It is the only thing "
            "authenticating inbound webhook calls."
        )
    credentials = dict(configuration.credentials or {})
    credentials["webhook_secret"] = secret
    configuration.credentials = credentials
    configuration.webhook_configured = True
    configuration.save(update_fields=["credentials", "webhook_configured", "updated_at"])
    record_audit(
        action="integration.credentials_updated",
        organization=configuration.organization,
        target_type="integration",
        target_id=str(configuration.id),
        summary=f"{configuration.provider}: webhook secret configured",
    )

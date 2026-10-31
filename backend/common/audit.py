"""
Audit logging helper.

The rule in `CLAUDE.md` is that an `AuditLog` write belongs inside the same
`transaction.atomic()` block as the action it records — an action that was not audited did
not happen, and an audit row for an action that rolled back is a lie. `record_audit()` is
therefore a plain function with no error swallowing: if the audit write fails, the whole
operation fails.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps

from .middleware import get_request_context

# Actions worth auditing. Kept as an explicit vocabulary rather than free text so the
# audit view can filter reliably and so a typo does not create a phantom action type.
ACTIONS = {
    "user.login",
    "user.login_failed",
    "user.logout",
    "user.created",
    "user.role_changed",
    "user.deactivated",
    "organization.created",
    "organization.updated",
    "membership.created",
    "membership.role_changed",
    "membership.removed",
    "ticket.created",
    "ticket.updated",
    "ticket.status_changed",
    "ticket.escalated",
    "ticket.assigned",
    "ticket.resolved",
    "ticket.note_added",
    "ticket.attachment_added",
    "ticket.similar_search",
    "playbook.created",
    "playbook.updated",
    "playbook.approved",
    "playbook.rejected",
    "playbook.deprecated",
    "playbook.superseded",
    "knowledge.draft_generated",
    "execution.started",
    "execution.step_completed",
    "execution.step_approval_granted",
    "execution.completed",
    "execution.abandoned",
    "integration.configured",
    "integration.credentials_updated",
    "integration.connection_tested",
    "integration.sync_run",
    "fit_assessment.created",
    "demo_request.created",
    "lakehouse.query_run",
    "knowledge.refreshed",
}


def record_audit(
    *,
    action: str,
    actor=None,
    organization=None,
    target_type: str = "",
    target_id: str = "",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
):
    """
    Write an `AuditLog` row.

    `metadata` must not contain credentials or full diagnostic payloads — pass identifiers
    and decisions, not content. Keys are shallow-filtered against an obvious denylist as a
    safety net, but the caller is responsible for what it passes.
    """
    if action not in ACTIONS:
        raise ValueError(
            f"Unknown audit action {action!r}. Add it to common.audit.ACTIONS deliberately."
        )

    AuditLog = apps.get_model("accounts", "AuditLog")
    context = get_request_context()

    safe_metadata = _strip_sensitive(metadata or {})

    return AuditLog.objects.create(
        action=action,
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        actor_label=_actor_label(actor),
        organization=organization,
        target_type=target_type[:100],
        target_id=str(target_id)[:100],
        summary=summary[:500],
        metadata=safe_metadata,
        request_id=context.get("request_id", ""),
        ip_address=context.get("ip_address") or None,
        user_agent=context.get("user_agent", ""),
    )


_DENY_SUBSTRINGS = (
    "password", "token", "secret", "api_key", "apikey", "credential",
    "authorization", "private_key", "access_key",
)


def _strip_sensitive(metadata: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(bad in lowered for bad in _DENY_SUBSTRINGS):
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = _strip_sensitive(value)
        elif isinstance(value, str) and len(value) > 2000:
            out[key] = value[:2000] + "…[truncated]"
        else:
            out[key] = value
    return out


def _actor_label(actor) -> str:
    """
    A durable textual label for the actor.

    `actor` is SET_NULL on user deletion, so without this the audit trail loses who did
    what the moment an account is removed.
    """
    if actor is None:
        return "system"
    email = getattr(actor, "email", None)
    if email:
        return str(email)[:255]
    return str(actor)[:255]

"""
PlaybookExecutionService — the Resolution Replay engine.

A guided, branching troubleshooting workflow. Think of it as turn-by-turn navigation for a
technical investigation: the user is told what to look at, they report what they saw, and
the route recalculates.

Three rules are enforced here and nowhere else, so they cannot be bypassed by a new
endpoint or a UI change:

1. **A step that can change a running system cannot complete without recorded approval**
   from a sufficiently privileged user (`customer_admin`, `fde`, `fde_lead` or
   `platform_admin`). Acceptance test 14.
2. **Remediation is unreachable until the evidence has been gathered**, because the route
   to it runs through `branches` from the diagnostic steps. A playbook that jumps straight
   to a change step is an authoring bug, and `validate_graph()` detects it.
3. **A completed checklist is not a resolution.** Finishing every step leads to an explicit
   outcome capture — resolved / partially / not resolved / escalated — with evidence. The
   ticket is only marked resolved on an explicit `resolved` outcome with evidence supplied.

Nothing in this module executes anything. `step.commands` are strings rendered for a human
to run. There is no code path from a playbook to a subprocess, a Kubernetes client, or a
SQL connection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from aiengine.services import redaction
from common.audit import record_audit
from common.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    DomainValidationError,
)
from common.versioning import environment_matches, version_matches
from tickets.models import Ticket, TicketEvent, TicketEventType, TicketStatus

from ..models import (
    APPROVAL_REQUIRED_STEP_TYPES,
    ExecutionStatus,
    PlaybookExecution,
    PlaybookStep,
    PlaybookStepResponse,
    ResolutionPlaybook,
    ResponseKind,
    RiskLevel,
    StepType,
)

logger = logging.getLogger("compass.replay")

#: Terminal branch targets. A branch may point at a step key or at one of these.
TERMINAL_RESOLVED = "__resolved"
TERMINAL_ESCALATE = "__escalate"
TERMINAL_NOT_RESOLVED = "__not_resolved"
TERMINALS = {TERMINAL_RESOLVED, TERMINAL_ESCALATE, TERMINAL_NOT_RESOLVED}

#: Roles permitted to approve a system-changing step.
APPROVER_ROLES = frozenset({"fde", "fde_lead", "platform_admin"})

#: Hard ceiling on steps in one execution. A malformed `branches` map can describe a cycle;
#: without this the engine would loop until the request timed out.
MAX_STEPS = 60


# =======================================================================================
# Authoring validation
# =======================================================================================


@dataclass
class GraphIssue:
    severity: str  # error | warning
    step_key: str
    message: str


def validate_graph(playbook: ResolutionPlaybook) -> list[GraphIssue]:
    """
    Check a playbook's step graph before it can be approved.

    Catches the authoring mistakes that would make a workflow unsafe or unfinishable:
    dangling branch targets, unreachable steps, a change step reachable without any
    preceding diagnostic, and no path to a terminal outcome.

    Called by the approval service — a playbook with an `error`-severity issue cannot be
    approved. Enforcing this at approval time rather than at save time is deliberate: an
    FDE should be able to save a half-finished draft.
    """
    steps = list(playbook.steps.order_by("order"))
    if not steps:
        return [GraphIssue("error", "", "The playbook has no steps.")]

    by_key = {step.key: step for step in steps}
    issues: list[GraphIssue] = []

    # Dangling branch targets.
    for step in steps:
        for response_value, target in (step.branches or {}).items():
            if target in TERMINALS:
                continue
            if target not in by_key:
                issues.append(
                    GraphIssue(
                        "error",
                        step.key,
                        f"Branch for response {response_value!r} points at {target!r}, "
                        "which is not a step in this playbook.",
                    )
                )

    # Reachability from the first step, and the diagnostic-before-change rule.
    #
    # The traversal state is (step key, "has a diagnostic been seen on this path") — a
    # boolean, not a count. That matters for termination: a playbook whose `branches`
    # describe a cycle (a → b → a) is an authoring error this function must *report*, and
    # an accumulating counter would make the state space infinite and loop forever instead.
    # With a boolean the state space is at most 2 × len(steps), so the walk always ends.
    diagnostic_types = {StepType.READ_ONLY_DIAGNOSTIC, StepType.CONFIGURATION_REVIEW}
    first = steps[0]
    seen_states: set[tuple[str, bool]] = set()
    frontier: list[tuple[str, bool]] = [(first.key, False)]
    #: Whether each step is reachable by *some* path that includes a prior diagnostic.
    diagnostic_before: dict[str, bool] = {}
    reachable: set[str] = set()

    while frontier:
        key, had_diagnostic = frontier.pop()
        state = (key, had_diagnostic)
        if state in seen_states:
            continue
        seen_states.add(state)
        reachable.add(key)
        # A step counts as "safely reached" only if *every* path to it passed a diagnostic,
        # so record the pessimistic case: reaching it without one at all is what matters.
        diagnostic_before[key] = diagnostic_before.get(key, True) and had_diagnostic

        step = by_key.get(key)
        if step is None:
            continue
        next_had_diagnostic = had_diagnostic or step.step_type in diagnostic_types

        targets = [t for t in (step.branches or {}).values() if t not in TERMINALS]
        if not targets and not step.is_terminal and not (step.branches or {}):
            # Implicit fall-through to the next step by order.
            following = next((s for s in steps if s.order > step.order), None)
            if following:
                targets = [following.key]
        for target in targets:
            if target in by_key:
                frontier.append((target, next_had_diagnostic))

    for step in steps:
        if step.key not in reachable:
            issues.append(
                GraphIssue(
                    "warning",
                    step.key,
                    "This step is not reachable from the first step, so a user will never "
                    "see it.",
                )
            )
        if step.step_type in APPROVAL_REQUIRED_STEP_TYPES:
            if not diagnostic_before.get(step.key, False):
                issues.append(
                    GraphIssue(
                        "error",
                        step.key,
                        "This step can change a running system but is reachable without "
                        "any preceding read-only diagnostic step. Remediation must come "
                        "after the evidence that justifies it.",
                    )
                )
            if not step.blast_radius:
                issues.append(
                    GraphIssue(
                        "error",
                        step.key,
                        "A step that can change a running system must declare its blast "
                        "radius; it is shown in the confirmation gate.",
                    )
                )

    # At least one path must reach a terminal outcome.
    has_terminal = any(
        step.is_terminal or any(t in TERMINALS for t in (step.branches or {}).values())
        for step in steps
    )
    if not has_terminal:
        issues.append(
            GraphIssue(
                "error",
                "",
                "No step leads to a terminal outcome (__resolved, __escalate or "
                "__not_resolved), so a user could never finish this workflow.",
            )
        )

    # Unsafe commands.
    for step in steps:
        for command in step.commands or []:
            text = str(command.get("command", "")).lower()
            for danger in (
                "kubectl delete", "drop table", "drop database", "truncate", "rm -rf",
                "--force", "delete from", "kubectl drain", "shutdown", "> /dev/sd",
            ):
                if danger in text:
                    issues.append(
                        GraphIssue(
                            "error",
                            step.key,
                            f"Command contains {danger!r}. Playbooks must not instruct "
                            "destructive operations; escalate to an FDE instead.",
                        )
                    )
    return issues


# =======================================================================================
# Applicability
# =======================================================================================


@dataclass
class ApplicabilityCheck:
    applicable: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_applicability(*, playbook: ResolutionPlaybook, ticket: Ticket) -> ApplicabilityCheck:
    """
    Can this playbook legitimately be run against this ticket?

    Checked again at start time even though retrieval already gated: a user can bookmark a
    URL, an API client can post any playbook id, and a playbook can be deprecated between
    the search and the click. Authorization and safety checks belong at the point of
    action.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    if playbook.approval_status != "approved":
        reasons.append(
            f"This playbook is {playbook.get_approval_status_display().lower()}, not "
            "approved. Only approved playbooks can be run as guided workflows."
        )
    if playbook.is_deprecated:
        reasons.append("This playbook is deprecated and is no longer a recommended fix.")

    version_ok = version_matches(ticket.iomete_version, playbook.applicable_versions)
    if version_ok is False:
        reasons.append(
            f"This playbook applies to IOMETE versions {playbook.applicable_versions}; "
            f"this cluster reports version "
            f"{ticket.iomete_version or 'none recorded'}."
        )
    elif version_ok is None:
        reasons.append(
            "The IOMETE version for this ticket is unknown, so applicability cannot be "
            "established. Add the product version to the ticket to proceed."
        )

    environment_ok = environment_matches(
        ticket.environment, playbook.applicable_environments
    )
    if environment_ok is False:
        reasons.append(
            f"This playbook applies to {', '.join(playbook.applicable_environments)}; this "
            f"ticket is {ticket.get_environment_display().lower()}."
        )
    elif environment_ok is None:
        warnings.append(
            "The deployment environment is unknown. The workflow can proceed, but "
            "environment-specific steps should be checked carefully."
        )

    if playbook.is_review_overdue:
        warnings.append(
            f"This playbook was due for re-review on {playbook.review_due_at:%d %b %Y}. "
            "Product behaviour may have changed since it was last verified."
        )
    if playbook.risk_level == RiskLevel.HIGH:
        warnings.append(
            "This playbook is classified high risk: it contains a step that can affect a "
            "running workload. That step will require explicit approval."
        )

    return ApplicabilityCheck(applicable=not reasons, reasons=reasons, warnings=warnings)


# =======================================================================================
# Execution
# =======================================================================================


@transaction.atomic
def start(*, ticket: Ticket, playbook: ResolutionPlaybook, user: User) -> PlaybookExecution:
    """Begin a Resolution Replay session."""
    existing = PlaybookExecution.objects.filter(
        ticket=ticket, playbook=playbook, status=ExecutionStatus.IN_PROGRESS
    ).first()
    if existing:
        # Resuming is the right behaviour: a user who refreshed the page should not lose
        # their collected observations or start a parallel session.
        return existing

    check = check_applicability(playbook=playbook, ticket=ticket)
    if not check.applicable:
        raise DomainValidationError(
            detail="This playbook cannot be run against this ticket: "
            + " ".join(check.reasons)
        )

    first_step = playbook.steps.order_by("order").first()
    if first_step is None:
        raise ConflictError(detail="This playbook has no steps defined.")

    execution = PlaybookExecution.objects.create(
        organization=ticket.organization,
        ticket=ticket,
        playbook=playbook,
        playbook_version=playbook.version,
        started_by=user,
        status=ExecutionStatus.IN_PROGRESS,
        current_step=first_step,
        path=[first_step.key],
        diagnostic_summary={"warnings": check.warnings, "observations": []},
    )

    ResolutionPlaybook.objects.filter(pk=playbook.pk).update(
        usage_count=playbook.usage_count + 1
    )

    if ticket.status in {TicketStatus.NEW, TicketStatus.TRIAGING}:
        Ticket.objects.filter(pk=ticket.pk).update(status=TicketStatus.IN_PROGRESS)
        ticket.status = TicketStatus.IN_PROGRESS

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.PLAYBOOK_STARTED,
        author=user,
        author_label=user.email,
        body=f"Started Resolution Replay: {playbook.title} (v{playbook.version}).",
        metadata={
            "playbook_id": playbook.playbook_id,
            "version": playbook.version,
            "execution_id": str(execution.id),
            "warnings": check.warnings,
        },
    )
    record_audit(
        action="execution.started",
        actor=user,
        organization=ticket.organization,
        target_type="playbook_execution",
        target_id=str(execution.id),
        summary=f"{ticket.reference}: started {playbook.playbook_id} v{playbook.version}",
        metadata={"playbook_id": playbook.playbook_id, "risk_level": playbook.risk_level},
    )
    return execution


def _validate_response(step: PlaybookStep, response_value: str) -> str:
    """Validate the answer against the step's declared response schema."""
    value = (response_value or "").strip()

    if step.response_kind == ResponseKind.BOOLEAN:
        normalised = value.lower()
        if normalised in {"yes", "true", "1", "y"}:
            return "yes"
        if normalised in {"no", "false", "0", "n"}:
            return "no"
        raise DomainValidationError(detail="This step expects a yes or no answer.")

    if step.response_kind == ResponseKind.CHOICE:
        allowed = {str(option.get("value")) for option in (step.response_options or [])}
        if value not in allowed:
            raise DomainValidationError(
                detail=f"Expected one of: {', '.join(sorted(allowed))}."
            )
        return value

    if step.response_kind == ResponseKind.NUMERIC:
        try:
            float(value)
        except ValueError as exc:
            raise DomainValidationError(detail="This step expects a number.") from exc
        return value

    if step.response_kind == ResponseKind.ACKNOWLEDGE:
        return "acknowledged"

    # Free text.
    if not value:
        raise DomainValidationError(
            detail="Please describe what you observed — the observation is the evidence "
            "this workflow records."
        )
    return value[:120]


def _resolve_next(step: PlaybookStep, response_value: str) -> str:
    """
    Follow the branch map.

    Precedence: an exact response match, then `__default`, then the next step by order.
    The ordered fall-through means a simple linear playbook needs no `branches` at all,
    while a branching one is fully explicit.
    """
    branches = step.branches or {}
    if response_value in branches:
        return branches[response_value]
    if "__default" in branches:
        return branches["__default"]
    if step.is_terminal:
        return TERMINAL_NOT_RESOLVED
    following = (
        PlaybookStep.objects.filter(playbook_id=step.playbook_id, order__gt=step.order)
        .order_by("order")
        .first()
    )
    return following.key if following else TERMINAL_NOT_RESOLVED


def can_approve(user: User, execution: PlaybookExecution) -> bool:
    """
    May `user` approve a system-changing step in this execution?

    IOMETE staff always may. A customer may only if they are an administrator *of the
    organization that owns this execution* — approving a change to your own production
    cluster is a legitimate customer decision; approving one for a different tenant is not.
    """
    if user.is_iomete_staff:
        return True
    return user.has_membership_role("admin", organization_id=execution.organization_id)


@dataclass
class AdvanceResult:
    execution: PlaybookExecution
    response: PlaybookStepResponse
    next_step: PlaybookStep | None
    terminal: str | None
    requires_outcome_capture: bool


@transaction.atomic
def advance(
    *,
    execution: PlaybookExecution,
    user: User,
    response_value: str,
    observation: str = "",
    approval_note: str = "",
) -> AdvanceResult:
    """
    Record the answer to the current step and move to the next.

    `select_for_update` on the execution prevents two concurrent submissions from both
    appending at the same sequence number and corrupting the path.
    """
    execution = (
        PlaybookExecution.objects.select_for_update()
        .select_related("playbook", "ticket", "current_step")
        .get(pk=execution.pk)
    )

    if execution.status != ExecutionStatus.IN_PROGRESS:
        raise ConflictError(
            detail=f"This workflow is already {execution.get_status_display().lower()} and "
            "cannot be advanced. Its history is preserved; start a new run if needed."
        )

    step = execution.current_step
    if step is None:
        raise ConflictError(detail="This workflow has no current step.")

    if execution.responses.count() >= MAX_STEPS:
        raise ConflictError(
            detail="This workflow has run for an unusual number of steps, which suggests a "
            "loop in the playbook. It has been stopped; please escalate to an FDE."
        )

    # --- The approval gate ----------------------------------------------------------
    approver = None
    if step.step_type in APPROVAL_REQUIRED_STEP_TYPES:
        if not can_approve(user, execution):
            raise ApprovalRequiredError(
                detail=(
                    f"“{step.title}” can change a running system"
                    + (f" ({step.blast_radius})" if step.blast_radius else "")
                    + ". Completing it requires approval from an IOMETE engineer or an "
                    "administrator of your organization. Your current role cannot approve "
                    "it — ask an administrator to complete this step, or escalate."
                )
            )
        approver = user

    validated = _validate_response(step, response_value)
    clean_observation = redaction.redact(observation).text if observation else ""

    sequence = execution.responses.count() + 1
    next_key = _resolve_next(step, validated)

    response = PlaybookStepResponse.objects.create(
        execution=execution,
        step=step,
        sequence=sequence,
        response_value=validated,
        observation=clean_observation,
        matched_expectation=_matched_expectation(step, validated),
        completed_by=user,
        approval_granted_by=approver,
        approval_granted_at=timezone.now() if approver else None,
        approval_note=approval_note[:2000] if approver else "",
        next_step_key=next_key,
    )

    # Accumulate the diagnostic record — this is what an escalation package is built from.
    summary = execution.diagnostic_summary or {}
    observations = summary.setdefault("observations", [])
    observations.append(
        {
            "sequence": sequence,
            "step_key": step.key,
            "step_title": step.title,
            "step_type": step.step_type,
            "expected": step.expected_observation,
            "response": validated,
            "observation": clean_observation,
            "matched_expectation": response.matched_expectation,
            "at": timezone.now().isoformat(),
        }
    )
    execution.diagnostic_summary = summary

    terminal = None
    next_step = None
    if next_key in TERMINALS:
        terminal = next_key
        execution.current_step = None
    else:
        next_step = PlaybookStep.objects.filter(
            playbook_id=execution.playbook_id, key=next_key
        ).first()
        if next_step is None:
            logger.error(
                "Playbook %s step %s branches to unknown key %r; ending the workflow as "
                "not resolved rather than stranding the user.",
                execution.playbook.playbook_id, step.key, next_key,
            )
            terminal = TERMINAL_NOT_RESOLVED
            execution.current_step = None
        else:
            execution.current_step = next_step
            execution.path = [*list(execution.path or []), next_step.key]

    execution.save(update_fields=["current_step", "path", "diagnostic_summary", "updated_at"])

    TicketEvent.objects.create(
        ticket=execution.ticket,
        event_type=TicketEventType.PLAYBOOK_STEP,
        author=user,
        author_label=user.email,
        body=f"{step.title} → {validated}"
        + (f" — {clean_observation[:200]}" if clean_observation else ""),
        metadata={
            "execution_id": str(execution.id),
            "step_key": step.key,
            "step_type": step.step_type,
            "response": validated,
            "approved_by": approver.email if approver else None,
            "next": next_key,
        },
    )

    if approver:
        record_audit(
            action="execution.step_approval_granted",
            actor=approver,
            organization=execution.organization,
            target_type="playbook_execution",
            target_id=str(execution.id),
            summary=(
                f"{execution.ticket.reference}: approved change step “{step.title}” "
                f"({step.blast_radius[:120]})"
            ),
            metadata={"step_key": step.key, "risk_level": step.risk_level},
        )
    else:
        record_audit(
            action="execution.step_completed",
            actor=user,
            organization=execution.organization,
            target_type="playbook_execution",
            target_id=str(execution.id),
            summary=f"{execution.ticket.reference}: step “{step.title}” → {validated}",
            metadata={"step_key": step.key, "next": next_key},
        )

    return AdvanceResult(
        execution=execution,
        response=response,
        next_step=next_step,
        terminal=terminal,
        # A terminal branch does not itself end the run: the user must still state the
        # outcome and supply evidence. A completed checklist is not proof of a fix.
        requires_outcome_capture=terminal is not None,
    )


def _matched_expectation(step: PlaybookStep, response_value: str) -> bool | None:
    """
    Did the observation match what the step expected?

    Only meaningful for boolean steps, where the step text asks "did you see X?". Returning
    None for other kinds is honest: inferring a match from free text would be guessing.
    """
    if step.response_kind != ResponseKind.BOOLEAN:
        return None
    return response_value == "yes"


@transaction.atomic
def complete(
    *,
    execution: PlaybookExecution,
    user: User,
    outcome: str,
    outcome_summary: str = "",
    outcome_evidence: str = "",
) -> PlaybookExecution:
    """
    Finish an execution with an explicit outcome.

    `outcome_evidence` is **required** for a `resolved` outcome. This is the rule the brief
    calls out: a completed checklist is not proof a problem is fixed. Requiring the user to
    state what they observed converts a click into a record, and that record is what makes
    the resulting knowledge draft worth anything.
    """
    execution = (
        PlaybookExecution.objects.select_for_update()
        .select_related("ticket", "playbook")
        .get(pk=execution.pk)
    )
    if execution.status != ExecutionStatus.IN_PROGRESS:
        raise ConflictError(detail="This workflow has already been completed.")

    valid = {
        ExecutionStatus.RESOLVED,
        ExecutionStatus.PARTIALLY_RESOLVED,
        ExecutionStatus.NOT_RESOLVED,
        ExecutionStatus.ESCALATED,
        ExecutionStatus.ABANDONED,
    }
    if outcome not in {status.value for status in valid}:
        raise DomainValidationError(detail=f"Unknown outcome {outcome!r}.")

    if outcome == ExecutionStatus.RESOLVED and not outcome_evidence.strip():
        raise DomainValidationError(
            detail="To record this as resolved, describe what you observed that shows the "
            "problem is gone — for example that the failing query now completes, or that "
            "the error no longer appears. Completing the steps is not by itself evidence "
            "of a fix."
        )

    ticket = execution.ticket
    execution.status = outcome
    execution.outcome_summary = redaction.redact(outcome_summary).text[:4000]
    execution.outcome_evidence = redaction.redact(outcome_evidence).text[:4000]
    execution.completed_at = timezone.now()
    execution.duration_seconds = int(
        (execution.completed_at - execution.created_at).total_seconds()
    )
    execution.current_step = None
    execution.save()

    playbook = execution.playbook
    if outcome == ExecutionStatus.RESOLVED:
        ResolutionPlaybook.objects.filter(pk=playbook.pk).update(
            success_count=playbook.success_count + 1
        )
    elif outcome in {ExecutionStatus.NOT_RESOLVED, ExecutionStatus.ESCALATED}:
        ResolutionPlaybook.objects.filter(pk=playbook.pk).update(
            failure_count=playbook.failure_count + 1
        )

    if outcome == ExecutionStatus.RESOLVED:
        # Self-service resolution: the headline metric for whether COMPASS works.
        # `resolution_verified` is deliberately NOT set here — customer-reported success is
        # not FDE verification, and only the latter admits a resolution to trusted
        # retrieval. See playbooks.services.knowledge.
        Ticket.objects.filter(pk=ticket.pk).update(
            status=TicketStatus.RESOLVED,
            resolved_at=execution.completed_at,
            resolution_summary=execution.outcome_summary
            or f"Resolved by following the playbook “{playbook.title}”.",
            resolution_evidence=execution.outcome_evidence,
            self_service_resolved=True,
            resolved_via_playbook=playbook,
            time_to_resolution_seconds=int(
                (execution.completed_at - ticket.created_at).total_seconds()
            ),
        )
    elif outcome == ExecutionStatus.PARTIALLY_RESOLVED:
        Ticket.objects.filter(pk=ticket.pk).update(status=TicketStatus.IN_PROGRESS)

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.PLAYBOOK_COMPLETED,
        author=user,
        author_label=user.email,
        body=(
            f"Resolution Replay finished: {execution.get_status_display()}. "
            f"{execution.outcome_summary[:300]}"
        ),
        metadata={
            "execution_id": str(execution.id),
            "outcome": outcome,
            "steps_completed": execution.responses.count(),
            "duration_seconds": execution.duration_seconds,
        },
    )
    record_audit(
        action="execution.completed",
        actor=user,
        organization=execution.organization,
        target_type="playbook_execution",
        target_id=str(execution.id),
        summary=f"{ticket.reference}: replay {outcome} after {execution.responses.count()} steps",
        metadata={"outcome": outcome, "playbook_id": playbook.playbook_id},
    )
    return execution


def build_escalation_package(execution: PlaybookExecution) -> dict:
    """
    Assemble everything an FDE needs, from the execution record.

    The point of Resolution Replay for an unresolved case is that the escalation arrives
    with the investigation already done: what was checked, what was seen, what was ruled
    out. An FDE should not have to ask the customer to re-run the diagnostics.
    """
    responses = list(
        execution.responses.select_related("step").order_by("sequence")
    )
    ruled_out: list[str] = []
    confirmed: list[str] = []
    for response in responses:
        step = response.step
        if response.matched_expectation is False and step.expected_observation:
            ruled_out.append(f"{step.title}: did not observe “{step.expected_observation}”.")
        elif response.matched_expectation is True and step.expected_observation:
            confirmed.append(f"{step.title}: observed “{step.expected_observation}”.")

    return {
        "playbook": {
            "playbook_id": execution.playbook.playbook_id,
            "title": execution.playbook.title,
            "version": execution.playbook_version,
            "root_cause_tested": execution.playbook.confirmed_root_cause,
        },
        "path": execution.path,
        "steps_completed": [
            {
                "sequence": response.sequence,
                "title": response.step.title,
                "step_type": response.step.step_type,
                "what_to_inspect": response.step.what_to_inspect,
                "expected": response.step.expected_observation,
                "response_value": response.response_value,
                "observation": response.observation,
                "matched_expectation": response.matched_expectation,
            }
            for response in responses
        ],
        "confirmed_observations": confirmed,
        "ruled_out": ruled_out,
        "outcome": execution.status,
        "outcome_summary": execution.outcome_summary,
        "outcome_evidence": execution.outcome_evidence,
        "warnings": (execution.diagnostic_summary or {}).get("warnings", []),
        "duration_seconds": execution.duration_seconds,
    }


def serialize_step(step: PlaybookStep, *, user: User, execution: PlaybookExecution) -> dict:
    """
    Render a step for the client.

    `requires_approval` and `can_current_user_approve` are both returned so the UI can
    distinguish "this needs approval and you can give it" from "this needs approval and you
    cannot" — two situations that need different interfaces. The server enforces the rule
    regardless of what the UI does with them.
    """
    return {
        "id": str(step.id),
        "key": step.key,
        "order": step.order,
        "title": step.title,
        "plain_explanation": step.plain_explanation,
        "what_to_inspect": step.what_to_inspect,
        "expected_observation": step.expected_observation,
        "why_this_step": step.why_this_step,
        "step_type": step.step_type,
        "step_type_label": step.get_step_type_display(),
        "risk_level": step.risk_level,
        "risk_level_label": step.get_risk_level_display(),
        "blast_radius": step.blast_radius,
        "is_read_only": step.is_read_only,
        "requires_approval": step.requires_approval,
        "can_current_user_approve": (
            can_approve(user, execution) if step.requires_approval else True
        ),
        "commands": step.commands,
        "commands_notice": (
            "These commands are shown for you to run yourself. COMPASS never executes "
            "anything against your cluster."
        )
        if step.commands
        else "",
        "response_kind": step.response_kind,
        "response_options": step.response_options,
        "references": step.references,
    }

"""
Resolution playbooks and Resolution Replay execution.

The trust model, because it is the whole point of this app:

* A playbook is **data**, never code. The backend never executes a command from one. The
  `commands` on a step are *displayed* for a human to run. An LLM drafts playbooks; a
  human approves them; nothing is ever run automatically.
* Only `approval_status == APPROVED` playbooks enter trusted retrieval. Drafts, rejected
  and deprecated rows remain readable for audit and are visually distinct everywhere.
* `ResolutionPlaybook` is **not** tenant-owned. Approved playbooks are the one thing that
  legitimately crosses the tenant boundary — which is exactly why they must be reviewed
  and redacted by an FDE before approval. `origin_organization` records where the
  investigation came from and is withheld from other tenants.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from common.models import BaseModel, SyntheticDataMixin, TenantOwnedModel
from tickets.models import FailureCategory, TicketComponent


class RiskLevel(models.TextChoices):
    INFORMATIONAL = "informational", "Informational — reading only"
    LOW = "low", "Low — no system change"
    MEDIUM = "medium", "Medium — configuration change, reversible"
    HIGH = "high", "High — can affect a running workload"


class ApprovalStatus(models.TextChoices):
    DRAFT = "draft", "Draft — AI-generated, not reviewed"
    IN_REVIEW = "in_review", "In review"
    APPROVED = "approved", "Approved — trusted"
    REJECTED = "rejected", "Rejected"
    DEPRECATED = "deprecated", "Deprecated — superseded or no longer valid"


class StepType(models.TextChoices):
    """
    The safety contract of a workflow step.

    `CHANGE_REQUIRING_APPROVAL` is the only type that may alter a running system, and
    `PlaybookExecutionService.advance()` refuses to complete one without a recorded
    approval from a sufficiently privileged user. That rule is enforced in the service and
    covered by a dedicated test, not left to the UI.
    """

    INFORMATIONAL = "informational", "Informational"
    READ_ONLY_DIAGNOSTIC = "read_only_diagnostic", "Read-only diagnostic"
    CONFIGURATION_REVIEW = "configuration_review", "Configuration review (read, do not edit)"
    CHANGE_REQUIRING_APPROVAL = "change_requiring_approval", "Change requiring approval"
    VERIFICATION = "verification", "Verification"
    ESCALATION = "escalation", "Escalation"


#: Step types that can change a running system. Must not complete without approval.
APPROVAL_REQUIRED_STEP_TYPES = frozenset({StepType.CHANGE_REQUIRING_APPROVAL.value})

#: Step types that are safe to present without a confirmation gate.
READ_ONLY_STEP_TYPES = frozenset(
    {
        StepType.INFORMATIONAL.value,
        StepType.READ_ONLY_DIAGNOSTIC.value,
        StepType.CONFIGURATION_REVIEW.value,
        StepType.VERIFICATION.value,
        StepType.ESCALATION.value,
    }
)


class ResponseKind(models.TextChoices):
    BOOLEAN = "boolean", "Yes / no"
    CHOICE = "choice", "One of several options"
    TEXT = "text", "Free text observation"
    NUMERIC = "numeric", "A number"
    ACKNOWLEDGE = "acknowledge", "Acknowledge and continue"


class PlaybookQuerySet(models.QuerySet):
    def trusted(self) -> PlaybookQuerySet:
        """
        Playbooks that may be *recommended*.

        Approved, shared and not deprecated. This is the gate referenced by acceptance
        tests 5 and 10 — an unverified or deprecated playbook must never reach trusted
        retrieval, no matter how well it scores.
        """
        return self.filter(approval_status=ApprovalStatus.APPROVED, is_shared=True)

    def visible_to(self, user) -> PlaybookQuerySet:
        """
        What a user may *read*. Distinct from `trusted()`, which is what may be recommended.

        IOMETE staff see everything, including drafts and rejected rows, because reviewing
        them is their job.

        A customer sees:

        * approved shared playbooks — the trusted set;
        * **deprecated** shared playbooks, readable and clearly flagged. A customer who
          followed a playbook last month must still be able to open it; a 404 on something
          they were previously instructed to do is both confusing and bad for audit. These
          are excluded from `trusted()`, so they are never *recommended*;
        * drafts originating from their own organization's tickets, so they can see what is
          being written up about their own incident.

        Never another tenant's unapproved material.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_iomete_staff", False):
            return self
        org_ids = user.organization_ids()
        return self.filter(
            models.Q(
                approval_status__in=[ApprovalStatus.APPROVED, ApprovalStatus.DEPRECATED],
                is_shared=True,
            )
            | models.Q(origin_organization_id__in=org_ids)
        ).distinct()


class ResolutionPlaybook(BaseModel, SyntheticDataMixin):
    playbook_id = models.SlugField(
        max_length=120,
        db_index=True,
        help_text="Stable slug shared across versions of the same playbook.",
    )
    version = models.PositiveIntegerField(default=1)

    title = models.CharField(max_length=250)
    description = models.TextField()
    component = models.CharField(
        max_length=40, choices=TicketComponent.choices, default=TicketComponent.OTHER, db_index=True
    )
    category = models.CharField(
        max_length=40, choices=FailureCategory.choices, default=FailureCategory.UNKNOWN
    )

    # --- Applicability (the compatibility gate reads these) -------------------------
    applicable_versions = models.CharField(
        max_length=120,
        blank=True,
        help_text="Version spec, e.g. '>=3.0,<4.0' or '==3.19.1'. Blank/'*' means no "
        "constraint. Authors are instructed to narrow rather than leave it open: a false "
        "positive here means a wrong fix on a production cluster.",
    )
    applicable_environments = models.JSONField(
        default=list, blank=True, help_text="e.g. ['production', 'staging']. Empty = any."
    )
    applicable_deployments = models.JSONField(
        default=list, blank=True, help_text="e.g. ['on_premises', 'public_cloud']. Empty = any."
    )
    applicable_cloud_providers = models.JSONField(default=list, blank=True)

    # --- Diagnosis ------------------------------------------------------------------
    symptoms = models.JSONField(default=list, blank=True)
    confirmed_root_cause = models.TextField(
        help_text="What was actually wrong. Required for approval."
    )
    preconditions = models.JSONField(
        default=list, blank=True,
        help_text="What must be true before these steps make sense.",
    )
    expected_evidence = models.JSONField(
        default=list, blank=True,
        help_text="Observations that confirm this is the right playbook.",
    )
    resolution_instructions = models.TextField()
    verification_steps = models.JSONField(default=list, blank=True)
    known_limitations = models.TextField(blank=True)

    risk_level = models.CharField(
        max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW, db_index=True
    )

    # --- Review lifecycle -----------------------------------------------------------
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT, db_index=True
    )
    is_shared = models.BooleanField(
        default=True,
        help_text="Whether this playbook may be offered to other organizations. The FDE "
        "sets this to False when the content is irreducibly customer-specific.",
    )
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_playbooks",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    review_due_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When this must be re-reviewed. A stale playbook is a liability: "
        "product behaviour changes under it.",
    )
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="superseded_by"
    )
    redaction_notes = models.TextField(
        blank=True, help_text="What the reviewing FDE removed before approving."
    )

    # --- Provenance -----------------------------------------------------------------
    source_ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generated_playbooks",
    )
    origin_organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="originated_playbooks",
        help_text="Where the investigation came from. Withheld from other tenants.",
    )
    cluster = models.ForeignKey(
        "tickets.IssueCluster", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="playbooks",
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_playbooks",
    )
    generated_by = models.CharField(
        max_length=40, blank=True,
        help_text="Which provider drafted this ('demo', 'gemini', 'human'). Disclosed in "
        "the review UI so a reviewer knows what they are reading.",
    )

    # --- Outcome tracking (feeds resolution_confidence) -----------------------------
    usage_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)

    # --- Retrieval ------------------------------------------------------------------
    search_text = models.TextField(blank=True)
    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=80, blank=True)
    embedding_dim = models.PositiveIntegerField(null=True, blank=True)
    fingerprints = models.ManyToManyField(
        "tickets.ErrorFingerprint", blank=True, related_name="playbooks"
    )

    objects = models.Manager.from_queryset(PlaybookQuerySet)()

    class Meta:
        ordering = ("-approved_at", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["playbook_id", "version"], name="unique_playbook_version"
            )
        ]
        indexes = [
            models.Index(fields=["approval_status", "component"]),
            models.Index(fields=["playbook_id", "-version"]),
            models.Index(fields=["approval_status", "is_shared", "component"]),
        ]

    def __str__(self) -> str:
        return f"{self.playbook_id} v{self.version} — {self.title}"

    @property
    def is_trusted(self) -> bool:
        """May this be recommended as a verified resolution?"""
        return self.approval_status == ApprovalStatus.APPROVED and self.is_shared

    @property
    def is_deprecated(self) -> bool:
        return self.approval_status == ApprovalStatus.DEPRECATED

    @property
    def success_rate(self) -> float | None:
        """
        Observed success rate, or None when there is not enough data.

        Returning None rather than 0.0 matters: "no data" and "it never works" are
        different claims, and the UI must not present the former as the latter.
        """
        total = self.success_count + self.failure_count
        if total == 0:
            return None
        return round(self.success_count / total, 3)

    @property
    def is_review_overdue(self) -> bool:
        return bool(self.review_due_at and self.review_due_at < timezone.now())

    @property
    def requires_approval_steps(self) -> int:
        return self.steps.filter(step_type__in=APPROVAL_REQUIRED_STEP_TYPES).count()


class PlaybookStep(BaseModel):
    """
    One node in the troubleshooting workflow.

    `branches` maps a response value to the next step's `key`, or to a terminal outcome
    (`"__resolved"`, `"__escalate"`, `"__not_resolved"`). Branching on observations is what
    makes this a decision graph rather than a checklist — and it is how we guarantee a
    remediation step is unreachable until the diagnostic evidence has been gathered.
    """

    playbook = models.ForeignKey(
        ResolutionPlaybook, on_delete=models.CASCADE, related_name="steps"
    )
    order = models.PositiveSmallIntegerField()
    key = models.SlugField(
        max_length=80, help_text="Referenced by other steps' `branches`. Unique per playbook."
    )

    title = models.CharField(max_length=250)
    plain_explanation = models.TextField(
        help_text="Understandable by a customer engineer who is not an IOMETE expert."
    )
    what_to_inspect = models.TextField(blank=True)
    expected_observation = models.TextField(blank=True)
    why_this_step = models.TextField(
        blank=True, help_text="What this step rules in or out. Shown on request."
    )

    step_type = models.CharField(
        max_length=40, choices=StepType.choices, default=StepType.READ_ONLY_DIAGNOSTIC,
        db_index=True,
    )
    risk_level = models.CharField(
        max_length=20, choices=RiskLevel.choices, default=RiskLevel.INFORMATIONAL
    )
    blast_radius = models.CharField(
        max_length=300, blank=True,
        help_text="For medium/high risk steps: what is affected if this goes wrong. "
        "Rendered in the confirmation gate.",
    )

    commands = models.JSONField(
        default=list,
        blank=True,
        help_text="Display-only commands for a human to run. The backend never executes "
        "these. Each entry: {label, command, language, is_read_only}.",
    )
    response_kind = models.CharField(
        max_length=20, choices=ResponseKind.choices, default=ResponseKind.BOOLEAN
    )
    response_options = models.JSONField(
        default=list, blank=True, help_text="For `choice`: [{value, label, hint}]."
    )
    branches = models.JSONField(
        default=dict,
        blank=True,
        help_text="{response_value: step_key | '__resolved' | '__escalate' | "
        "'__not_resolved'}. '__default' is the fallback.",
    )
    is_terminal = models.BooleanField(default=False)
    references = models.JSONField(
        default=list, blank=True,
        help_text="Supporting documentation links, each {title, url}.",
    )

    class Meta:
        ordering = ("playbook", "order")
        constraints = [
            models.UniqueConstraint(fields=["playbook", "key"], name="unique_step_key_per_playbook"),
            models.UniqueConstraint(fields=["playbook", "order"], name="unique_step_order"),
        ]

    def __str__(self) -> str:
        return f"{self.playbook.playbook_id}#{self.order} {self.title}"

    @property
    def requires_approval(self) -> bool:
        return self.step_type in APPROVAL_REQUIRED_STEP_TYPES

    @property
    def is_read_only(self) -> bool:
        return self.step_type in READ_ONLY_STEP_TYPES


class ExecutionStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    RESOLVED = "resolved", "Resolved"
    PARTIALLY_RESOLVED = "partially_resolved", "Partially resolved"
    NOT_RESOLVED = "not_resolved", "Not resolved"
    ESCALATED = "escalated", "Escalated to an FDE"
    ABANDONED = "abandoned", "Abandoned"


class PlaybookExecution(TenantOwnedModel):
    """
    One customer's run through one playbook — the Resolution Replay session.

    `playbook_version` is denormalised on purpose: when a playbook is later superseded,
    the record of what the engineer was actually shown must not silently change.
    """

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="executions"
    )
    playbook = models.ForeignKey(
        ResolutionPlaybook, on_delete=models.PROTECT, related_name="executions"
    )
    playbook_version = models.PositiveIntegerField(
        help_text="Denormalised so the history reflects what was shown at the time."
    )
    started_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="started_executions",
    )
    status = models.CharField(
        max_length=32, choices=ExecutionStatus.choices, default=ExecutionStatus.IN_PROGRESS,
        db_index=True,
    )
    current_step = models.ForeignKey(
        PlaybookStep, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_executions",
    )
    path = models.JSONField(
        default=list, blank=True, help_text="Ordered step keys actually traversed."
    )

    outcome_summary = models.TextField(blank=True)
    outcome_evidence = models.TextField(
        blank=True,
        help_text="What the user observed that shows the problem is or is not gone. A "
        "completed checklist is not evidence; this field is.",
    )
    diagnostic_summary = models.JSONField(
        default=dict, blank=True,
        help_text="Collected observations, used to build an escalation package.",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["ticket", "-created_at"]),
            models.Index(fields=["playbook", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket.reference} → {self.playbook.playbook_id} ({self.status})"

    @property
    def is_complete(self) -> bool:
        return self.status != ExecutionStatus.IN_PROGRESS

    @property
    def steps_completed(self) -> int:
        return self.responses.count()


class PlaybookStepResponse(BaseModel):
    """
    What the user observed and answered at one step.

    Append-only: the troubleshooting history must be preserved, so there is no update path
    in the API. `approval_granted_by` is populated only for steps whose `step_type`
    requires it, and the execution service refuses to record a completion without it.
    """

    execution = models.ForeignKey(
        PlaybookExecution, on_delete=models.CASCADE, related_name="responses"
    )
    step = models.ForeignKey(PlaybookStep, on_delete=models.PROTECT, related_name="responses")
    sequence = models.PositiveSmallIntegerField(
        help_text="Position in this execution's path, not the step's own order — a "
        "branching workflow can revisit or skip steps."
    )

    response_value = models.CharField(max_length=120, blank=True)
    observation = models.TextField(
        blank=True, help_text="Free-text note from the user. Redacted before storage."
    )
    matched_expectation = models.BooleanField(null=True, blank=True)

    completed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="completed_steps",
    )
    approval_granted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="granted_step_approvals",
        help_text="Required for a change_requiring_approval step. Enforced in the service.",
    )
    approval_granted_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True)

    next_step_key = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("execution", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "sequence"], name="unique_response_sequence"
            )
        ]

    def __str__(self) -> str:
        return f"{self.execution_id} step {self.sequence}: {self.response_value}"


class ApprovalDecision(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    DEPRECATED = "deprecated", "Deprecated"


class KnowledgeApproval(BaseModel):
    """
    An FDE review decision on a playbook. Append-only: the review trail is the evidence
    that trusted knowledge was actually reviewed by a named person on a given date.
    """

    playbook = models.ForeignKey(
        ResolutionPlaybook, on_delete=models.CASCADE, related_name="approvals"
    )
    playbook_version = models.PositiveIntegerField()
    reviewer = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="knowledge_reviews",
    )
    reviewer_label = models.CharField(max_length=255, blank=True)
    decision = models.CharField(max_length=32, choices=ApprovalDecision.choices, db_index=True)
    notes = models.TextField(blank=True)
    redactions_made = models.TextField(blank=True)
    applicability_changes = models.JSONField(default=dict, blank=True)
    review_due_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["playbook", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.playbook.playbook_id} v{self.playbook_version}: {self.decision}"


class PlaybookMatch(BaseModel):
    """
    A playbook proposed for a ticket, with its own gate decision and confidence.

    Separate from `SimilarityMatch` (ticket↔ticket) because the questions differ: there,
    "is this the same problem?"; here, "is this fix safe and applicable *here*?".
    """

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="playbook_matches"
    )
    playbook = models.ForeignKey(
        ResolutionPlaybook, on_delete=models.CASCADE, related_name="ticket_matches"
    )
    rank = models.PositiveSmallIntegerField()

    similarity_score = models.FloatField()
    resolution_confidence = models.FloatField()
    gate_status = models.CharField(
        max_length=20, choices=[("clean", "clean"), ("penalised", "penalised"), ("gated", "gated")],
        default="clean", db_index=True,
    )
    gate_reason = models.CharField(max_length=300, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    channel_scores = models.JSONField(default=dict, blank=True)
    retrieval_run = models.ForeignKey(
        "aiengine.RetrievalRun", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="playbook_matches",
    )

    class Meta:
        ordering = ("ticket", "rank")
        indexes = [models.Index(fields=["ticket", "rank"])]

    def __str__(self) -> str:
        return f"{self.ticket.reference} → {self.playbook.playbook_id} ({self.gate_status})"

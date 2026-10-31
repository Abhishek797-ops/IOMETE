"""
Support ticket models.

Design notes worth knowing before changing anything here:

* **Stored text is already redacted.** `description`, `error_message` and `diagnostics` hold
  the output of `SensitiveDataRedactionService`. The original is never persisted. There is
  no "raw" column to leak, because the safest way to protect a secret is not to store it.
* **`Ticket` is tenant-owned; `IssueCluster` is not.** A cluster spans customers by its
  nature ("18 tickets with this symptom across 6 organizations"), so it is FDE-only and
  exposes only counts and symptom signatures — never another tenant's ticket content.
* **Retrieval output is persisted** (`SimilarityMatch`) rather than recomputed per render.
  Support decisions get audited months later; "what did the system show the engineer on
  the day?" must be answerable.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from common.models import BaseModel, SyntheticDataMixin, TenantOwnedModel


class TicketComponent(models.TextChoices):
    """
    Product areas, aligned to the services IOMETE actually documents.

    See `docs/product-knowledge/knowledge.json` → `architecture.services`.
    """

    SPARK_COMPUTE = "spark_compute", "Spark compute cluster"
    SPARK_JOBS = "spark_jobs", "Spark jobs / orchestration"
    KUBERNETES = "kubernetes", "Kubernetes / infrastructure"
    ICEBERG_METADATA = "iceberg_metadata", "Iceberg tables and metadata"
    ICEBERG_CATALOG = "iceberg_catalog", "Iceberg REST Catalog"
    SQL_SERVICE = "sql_service", "SQL service / editor"
    PERMISSIONS = "permissions", "Access control (Ranger / identity)"
    IDENTITY_SSO = "identity_sso", "Identity, LDAP and SSO"
    DATA_INGESTION = "data_ingestion", "Data ingestion / event streams"
    OBJECT_STORAGE = "object_storage", "Object storage connectivity"
    CATALOG_SEARCH = "catalog_search", "Data catalog and search"
    GATEWAY_NETWORK = "gateway_network", "Gateway, ingress and networking"
    JUPYTER = "jupyter", "Jupyter containers"
    PLATFORM_METADATA = "platform_metadata", "Platform metadata (PostgreSQL)"
    UPGRADE = "upgrade", "Installation and upgrade"
    OTHER = "other", "Other / not sure"


class FailureCategory(models.TextChoices):
    """
    Hypothesised failure class, produced by `TicketNormalizationService`.

    It is a *hypothesis* used to narrow retrieval, never a diagnosis. `UNKNOWN` is a
    legitimate and common value; forcing a guess here would poison the metadata channel.
    """

    RESOURCE_EXHAUSTION = "resource_exhaustion", "Resource exhaustion (memory / CPU / quota)"
    PERMISSION_DENIED = "permission_denied", "Permission denied"
    CONFIGURATION_ERROR = "configuration_error", "Configuration error"
    CONNECTIVITY = "connectivity", "Connectivity / networking"
    METADATA_INCONSISTENCY = "metadata_inconsistency", "Metadata or table-state inconsistency"
    VERSION_INCOMPATIBILITY = "version_incompatibility", "Version incompatibility"
    CAPACITY_LIMIT = "capacity_limit", "Capacity or concurrency limit"
    DATA_QUALITY = "data_quality", "Data quality or schema mismatch"
    AUTHENTICATION = "authentication", "Authentication failure"
    PERFORMANCE = "performance", "Performance degradation"
    UNKNOWN = "unknown", "Not yet categorised"


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical — production down"
    HIGH = "high", "High — major functionality impaired"
    MEDIUM = "medium", "Medium — degraded or workaround exists"
    LOW = "low", "Low — question or minor issue"


class TicketStatus(models.TextChoices):
    NEW = "new", "New"
    TRIAGING = "triaging", "Triaging"
    AWAITING_CUSTOMER = "awaiting_customer", "Awaiting customer"
    IN_PROGRESS = "in_progress", "In progress"
    ESCALATED = "escalated", "Escalated to FDE"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


OPEN_STATUSES = (
    TicketStatus.NEW,
    TicketStatus.TRIAGING,
    TicketStatus.AWAITING_CUSTOMER,
    TicketStatus.IN_PROGRESS,
    TicketStatus.ESCALATED,
)


class Environment(models.TextChoices):
    PRODUCTION = "production", "Production"
    STAGING = "staging", "Staging / pre-production"
    DEVELOPMENT = "development", "Development"
    TEST = "test", "Test"
    UNKNOWN = "unknown", "Unknown"


class ErrorFingerprint(BaseModel):
    """
    A stable digest of a normalised error signature.

    This is the highest-signal retrieval channel. Two tickets sharing a fingerprint are
    reporting the same *error*, which is far stronger evidence than two tickets whose prose
    reads alike — but it is still not proof of the same root cause, which is why it feeds
    `similarity` and `diagnosis_confidence` separately.

    Global rather than tenant-owned: the digest is derived from product error text with all
    customer-specific values stripped, so it carries no tenant data.
    """

    digest = models.CharField(max_length=64, unique=True, db_index=True)
    signature = models.TextField(
        help_text="The normalised error signature this digest was computed from."
    )
    error_codes = models.JSONField(default=list, blank=True)
    key_phrases = models.JSONField(default=list, blank=True)
    component = models.CharField(
        max_length=40, choices=TicketComponent.choices, default=TicketComponent.OTHER, db_index=True
    )
    occurrence_count = models.PositiveIntegerField(default=0)
    distinct_organization_count = models.PositiveIntegerField(
        default=0, help_text="How many tenants have hit this. Aggregate only — no tenant ids."
    )
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-occurrence_count", "-last_seen_at")
        indexes = [models.Index(fields=["component", "-occurrence_count"])]

    def __str__(self) -> str:
        return f"{self.digest[:12]} ({self.occurrence_count}x)"


class ClusterStatus(models.TextChoices):
    OPEN = "open", "Open — grouped, not investigated"
    INVESTIGATING = "investigating", "Under investigation"
    ROOT_CAUSE_CONFIRMED = "root_cause_confirmed", "Root cause confirmed"
    MITIGATED = "mitigated", "Mitigated"
    CLOSED = "closed", "Closed"


class IssueCluster(BaseModel, SyntheticDataMixin):
    """
    A group of tickets sharing a symptom signature.

    **A cluster is a hypothesis, not a finding.** Grouping eighteen "executor keeps
    restarting" tickets together is useful triage; asserting they share a root cause before
    anyone investigated is how an AI support tool produces confident nonsense. Hence
    `hypothesised_root_cause` (free text, clearly labelled) is separate from
    `is_root_cause_confirmed` (set only by an FDE after investigation), and the API renders
    them differently.

    Not tenant-owned: clusters are a cross-customer view and are FDE-only. The customer-
    facing API never exposes cluster membership of another tenant's tickets.
    """

    key = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    component = models.CharField(
        max_length=40, choices=TicketComponent.choices, default=TicketComponent.OTHER, db_index=True
    )
    category = models.CharField(
        max_length=40, choices=FailureCategory.choices, default=FailureCategory.UNKNOWN
    )
    symptom_signature = models.JSONField(
        default=list, blank=True, help_text="The shared symptoms that define membership."
    )
    common_error_codes = models.JSONField(default=list, blank=True)

    hypothesised_root_cause = models.TextField(
        blank=True,
        help_text="A working theory. Must be rendered as unconfirmed until "
        "is_root_cause_confirmed is set by an FDE.",
    )
    is_root_cause_confirmed = models.BooleanField(
        default=False,
        help_text="Set only by an FDE after investigation. Gates whether the UI may "
        "present the cluster as a confirmed shared cause.",
    )
    confirmed_root_cause = models.TextField(blank=True)
    status = models.CharField(
        max_length=32, choices=ClusterStatus.choices, default=ClusterStatus.OPEN, db_index=True
    )
    investigation_notes = models.TextField(blank=True)
    owner = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="owned_clusters",
    )
    fingerprints = models.ManyToManyField(
        ErrorFingerprint, blank=True, related_name="clusters"
    )

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["status", "component"])]

    def __str__(self) -> str:
        return self.title

    @property
    def ticket_count(self) -> int:
        return self.tickets.count()

    @property
    def verified_resolution_count(self) -> int:
        return self.tickets.filter(resolution_verified=True).count()

    @property
    def affected_organization_count(self) -> int:
        """Count only. Never expose *which* organizations to a non-staff caller."""
        return self.tickets.values("organization_id").distinct().count()


class Ticket(TenantOwnedModel, SyntheticDataMixin):
    reference = models.CharField(max_length=32, unique=True, db_index=True)
    title = models.CharField(max_length=250)

    # --- Redacted content ----------------------------------------------------------
    description = models.TextField(
        help_text="Redacted. The original submission is never persisted."
    )
    error_message = models.TextField(blank=True, help_text="Redacted.")
    diagnostics = models.TextField(
        blank=True, help_text="Redacted sanitised diagnostic output supplied by the customer."
    )
    redaction_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text="What the redaction service removed, by category and count. Shown to the "
        "submitter so redaction is visible rather than silent.",
    )

    # --- Classification ------------------------------------------------------------
    component = models.CharField(
        max_length=40, choices=TicketComponent.choices, default=TicketComponent.OTHER, db_index=True
    )
    category = models.CharField(
        max_length=40, choices=FailureCategory.choices, default=FailureCategory.UNKNOWN,
        db_index=True,
    )
    severity = models.CharField(
        max_length=20, choices=Severity.choices, default=Severity.MEDIUM, db_index=True
    )
    status = models.CharField(
        max_length=32, choices=TicketStatus.choices, default=TicketStatus.NEW, db_index=True
    )

    # --- Environment metadata (drives the compatibility gate) ----------------------
    iomete_version = models.CharField(max_length=32, blank=True, db_index=True)
    environment = models.CharField(
        max_length=20, choices=Environment.choices, default=Environment.UNKNOWN, db_index=True
    )
    deployment_model = models.CharField(max_length=32, blank=True)
    cloud_provider = models.CharField(max_length=32, blank=True)
    kubernetes_distribution = models.CharField(max_length=80, blank=True)

    # --- Normalisation output ------------------------------------------------------
    normalized = models.JSONField(
        default=dict,
        blank=True,
        help_text="Output of TicketNormalizationService: error codes, key phrases, "
        "symptoms, affected components, extracted version.",
    )
    fingerprint = models.ForeignKey(
        ErrorFingerprint, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets",
    )
    search_text = models.TextField(
        blank=True,
        help_text="Denormalised, redacted text used by the lexical retrieval channel.",
    )

    # --- Embedding (portable source of truth; pgvector index mirrors it) -----------
    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=80, blank=True)
    embedding_dim = models.PositiveIntegerField(null=True, blank=True)
    embedded_at = models.DateTimeField(null=True, blank=True)

    # --- People --------------------------------------------------------------------
    reporter = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reported_tickets",
    )
    reporter_label = models.CharField(
        max_length=255, blank=True, help_text="Survives reporter deletion."
    )
    assigned_fde = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )

    # --- Clustering ----------------------------------------------------------------
    cluster = models.ForeignKey(
        IssueCluster, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )

    # --- Lifecycle -----------------------------------------------------------------
    first_response_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_reason = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_summary = models.TextField(blank=True)
    resolution_evidence = models.TextField(
        blank=True, help_text="What the customer observed that shows the problem is gone."
    )
    resolution_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text="An FDE confirmed the resolution. A completed checklist alone does not "
        "set this — see playbooks.services.execution.",
    )
    resolution_verified_at = models.DateTimeField(null=True, blank=True)
    resolution_verified_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="verified_resolutions",
    )
    resolution_quality = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="1-5, set by the reviewing FDE. Feeds resolution_confidence for future "
        "matches, so a poorly-executed fix does not become a confident recommendation.",
    )
    self_service_resolved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Resolved by the customer through Resolution Replay without FDE "
        "involvement. The headline metric for whether COMPASS is working.",
    )
    resolved_via_playbook = models.ForeignKey(
        "playbooks.ResolutionPlaybook", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="resolved_tickets",
    )
    time_to_resolution_seconds = models.PositiveIntegerField(null=True, blank=True)
    fde_investigation_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="FDE-reported effort. Used for the 'hours saved' estimate, which is "
        "presented as an estimate derived from these reported figures, never as a fact.",
    )

    # --- External ticketing --------------------------------------------------------
    external_provider = models.CharField(max_length=40, blank=True)
    external_reference = models.CharField(max_length=80, blank=True, db_index=True)
    external_url = models.URLField(blank=True)
    external_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["component", "category"]),
            models.Index(fields=["status", "severity", "-created_at"]),
            models.Index(fields=["assigned_fde", "status"]),
            models.Index(fields=["resolution_verified", "component"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.title}"

    @property
    def is_open(self) -> bool:
        return self.status in {s.value for s in OPEN_STATUSES}

    @property
    def age_hours(self) -> float:
        end = self.resolved_at or timezone.now()
        return round((end - self.created_at).total_seconds() / 3600, 1)


class TicketEventType(models.TextChoices):
    CREATED = "created", "Created"
    STATUS_CHANGED = "status_changed", "Status changed"
    COMMENT = "comment", "Comment"
    INTERNAL_NOTE = "internal_note", "Internal FDE note"
    ASSIGNED = "assigned", "Assigned"
    ESCALATED = "escalated", "Escalated"
    SIMILAR_SEARCH = "similar_search", "Similar-ticket search run"
    PLAYBOOK_STARTED = "playbook_started", "Resolution Replay started"
    PLAYBOOK_STEP = "playbook_step", "Resolution Replay step completed"
    PLAYBOOK_COMPLETED = "playbook_completed", "Resolution Replay completed"
    RESOLUTION = "resolution", "Resolution recorded"
    VERIFICATION = "verification", "Resolution verified"
    ATTACHMENT = "attachment", "Attachment added"
    KNOWLEDGE_DRAFT = "knowledge_draft", "Knowledge draft generated"
    EXTERNAL_SYNC = "external_sync", "External system sync"


class TicketEvent(BaseModel):
    """
    The ticket's timeline.

    `is_internal` marks FDE-only entries. Customer-facing serializers filter on it, and
    there is a dedicated tenant-isolation test for exactly this: an internal note is the
    kind of thing that leaks through a hastily added endpoint.

    Preserving the original troubleshooting history is a requirement, so there is no update
    or delete path for events in the API.
    """

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(
        max_length=32, choices=TicketEventType.choices, default=TicketEventType.COMMENT,
        db_index=True,
    )
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ticket_events",
    )
    author_label = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True, help_text="Redacted before storage.")
    is_internal = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True for FDE-only notes. Must never reach a customer serializer.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=["ticket", "created_at"])]

    def __str__(self) -> str:
        return f"{self.ticket.reference}: {self.event_type}"


class TicketAttachment(BaseModel):
    """
    An uploaded diagnostic file.

    Upload safety is enforced in `tickets/services/attachments.py`: extension and
    content-type allowlist, size cap, generated storage name (never the client-supplied
    one), and stored outside any served directory.
    """

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="ticket-attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="uploaded_attachments",
    )
    redaction_applied = models.BooleanField(
        default=False,
        help_text="True when the stored copy is a redacted rewrite of a text upload.",
    )
    redaction_summary = models.JSONField(default=dict, blank=True)
    is_internal = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.original_name} ({self.size_bytes} bytes)"


class GateStatus(models.TextChoices):
    CLEAN = "clean", "Applicable"
    PENALISED = "penalised", "Partially applicable — scored down"
    GATED = "gated", "Not applicable — excluded from recommendation"


class SimilarityMatch(BaseModel):
    """
    A persisted retrieval result: one historical ticket proposed for one query ticket.

    The three scores are deliberately separate columns, not one number:

    * `similarity_score` — how alike the two tickets look (retrieval fusion output).
    * `diagnosis_confidence` — how much the evidence supports the same *root cause*.
    * `resolution_confidence` — how likely the historical fix is to work *here*.

    A paraphrase can score 0.93 similarity with 0.30 diagnosis confidence. Collapsing
    these into "93% match" is the single most misleading thing a support AI can do.
    """

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="similarity_matches",
        help_text="The ticket the search was run for.",
    )
    matched_ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="matched_by",
        help_text="The historical ticket proposed as related.",
    )
    rank = models.PositiveSmallIntegerField()

    similarity_score = models.FloatField()
    diagnosis_confidence = models.FloatField()
    resolution_confidence = models.FloatField()

    channel_scores = models.JSONField(
        default=dict, blank=True,
        help_text="Per-channel contribution (vector / lexical / fingerprint / metadata), "
        "so a ranking can be explained rather than asserted.",
    )
    evidence = models.JSONField(
        default=list, blank=True,
        help_text="Structured reasons this match was proposed: shared error codes, "
        "overlapping symptoms, same component, matching environment.",
    )
    matched_symptoms = models.JSONField(default=list, blank=True)

    gate_status = models.CharField(
        max_length=20, choices=GateStatus.choices, default=GateStatus.CLEAN, db_index=True
    )
    gate_reason = models.CharField(max_length=300, blank=True)

    retrieval_backend = models.CharField(
        max_length=40, blank=True, help_text="pgvector | numpy — reported, never hidden."
    )
    retrieval_run = models.ForeignKey(
        "aiengine.RetrievalRun", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="matches",
    )

    class Meta:
        ordering = ("ticket", "rank")
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "matched_ticket", "retrieval_run"],
                name="unique_match_per_run",
            )
        ]
        indexes = [models.Index(fields=["ticket", "rank"])]

    def __str__(self) -> str:
        return (
            f"{self.ticket.reference} ~ {self.matched_ticket.reference} "
            f"(sim {self.similarity_score:.2f})"
        )

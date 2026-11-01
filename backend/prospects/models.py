"""
Prospect-side models: discovery answers, fit assessments, architecture recommendations and
demo requests.

Privacy posture: these records are created by people who are not customers yet, often
before any relationship exists. So:

* We collect the minimum that makes the assessment useful, and nothing speculative.
* Contact details are optional — the Fit Finder works anonymously and only asks for an
  email if the prospect wants the report or a demo.
* `consent_given` plus the exact `consent_text` shown at the time is stored, because
  "they ticked a box" is not evidence of what they agreed to.
"""

from __future__ import annotations

from django.db import models

from common.models import BaseModel, SyntheticDataMixin


class CompanyType(models.TextChoices):
    ENTERPRISE = "enterprise", "Large enterprise"
    MID_MARKET = "mid_market", "Mid-market company"
    STARTUP = "startup", "Startup / scale-up"
    PUBLIC_SECTOR = "public_sector", "Government or public sector"
    FINANCIAL = "financial", "Financial services"
    HEALTHCARE = "healthcare", "Healthcare or life sciences"
    TELECOM = "telecom", "Telecommunications"
    CONSULTANCY = "consultancy", "Consultancy or systems integrator"
    OTHER = "other", "Other"


class InfrastructureLocation(models.TextChoices):
    ON_PREMISES = "on_premises", "Entirely on-premises"
    PUBLIC_CLOUD = "public_cloud", "Public cloud"
    PRIVATE_CLOUD = "private_cloud", "Private cloud"
    HYBRID = "hybrid", "Hybrid — on-premises and cloud"
    AIR_GAPPED = "air_gapped", "Air-gapped / isolated network"
    UNDECIDED = "undecided", "Not decided yet"


class DataVolume(models.TextChoices):
    UNDER_1TB = "under_1tb", "Under 1 TB"
    TB_1_10 = "tb_1_10", "1–10 TB"
    TB_10_100 = "tb_10_100", "10–100 TB"
    TB_100_1PB = "tb_100_1pb", "100 TB – 1 PB"
    OVER_1PB = "over_1pb", "Over 1 PB"
    UNKNOWN = "unknown", "Not sure"


class UseCase(models.TextChoices):
    BI_REPORTING = "bi_reporting", "BI and reporting"
    DATA_ENGINEERING = "data_engineering", "Data engineering and ETL"
    REAL_TIME = "real_time", "Real-time analytics"
    AI_ML = "ai_ml", "AI and machine learning"
    DATA_SCIENCE = "data_science", "Data science and exploration"
    GOVERNANCE = "governance", "Governance and compliance reporting"
    CONSOLIDATION = "consolidation", "Consolidating lake and warehouse"
    DATA_MESH = "data_mesh", "Data mesh / domain ownership"
    OTHER = "other", "Other"


class SovereigntyRequirement(models.TextChoices):
    MANDATORY = "mandatory", "Mandatory — data cannot leave our control"
    STRONG = "strong", "Strong preference"
    SOME = "some", "Some workloads only"
    NONE = "none", "No specific requirement"
    UNKNOWN = "unknown", "Not sure"


class CurrentArchitecture(models.TextChoices):
    WAREHOUSE = "warehouse", "Cloud data warehouse"
    DATA_LAKE = "data_lake", "Data lake"
    BOTH = "both", "Both a lake and a warehouse"
    LAKEHOUSE = "lakehouse", "Already a lakehouse"
    DATABASES_ONLY = "databases_only", "Operational databases only"
    NONE = "none", "Nothing formal yet"


class FitBand(models.TextChoices):
    """
    Deliberately a *band*, not a percentage.

    A "87% compatible" number implies a precision this assessment does not have, and the
    brief explicitly forbids misleading compatibility percentages. Bands carry an
    indicative score and a published rubric instead, and every assessment states that it
    is indicative rather than an official IOMETE determination.
    """

    STRONG = "strong", "Strong indicative fit"
    PROMISING = "promising", "Promising, with open questions"
    CONDITIONAL = "conditional", "Conditional — depends on specifics"
    LIMITED = "limited", "Limited indicative fit"
    NEEDS_DISCUSSION = "needs_discussion", "Not enough information — needs discussion"


class ProspectProfile(BaseModel, SyntheticDataMixin):
    """Who is evaluating, and what their environment looks like."""

    company_name = models.CharField(max_length=200, blank=True)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(
        blank=True, help_text="Optional. The Fit Finder works without it."
    )
    contact_role = models.CharField(max_length=150, blank=True)
    persona = models.CharField(
        max_length=40, blank=True,
        help_text="Which /explore persona they identified with, if any.",
    )

    company_type = models.CharField(
        max_length=32, choices=CompanyType.choices, default=CompanyType.OTHER
    )
    infrastructure_location = models.CharField(
        max_length=32, choices=InfrastructureLocation.choices,
        default=InfrastructureLocation.UNDECIDED,
    )
    cloud_providers = models.JSONField(default=list, blank=True)
    current_systems = models.JSONField(
        default=list, blank=True, help_text="Databases, storage and warehouses in use."
    )
    data_volume = models.CharField(
        max_length=32, choices=DataVolume.choices, default=DataVolume.UNKNOWN
    )
    primary_use_case = models.CharField(
        max_length=32, choices=UseCase.choices, default=UseCase.OTHER
    )
    secondary_use_cases = models.JSONField(default=list, blank=True)
    sovereignty_requirement = models.CharField(
        max_length=32, choices=SovereigntyRequirement.choices,
        default=SovereigntyRequirement.UNKNOWN,
    )
    challenges = models.JSONField(default=list, blank=True)
    current_architecture = models.CharField(
        max_length=32, choices=CurrentArchitecture.choices, default=CurrentArchitecture.NONE
    )
    constraints = models.JSONField(
        default=list, blank=True,
        help_text="Operational constraints: team size, Kubernetes skills, budget cycle, "
        "procurement, timeline.",
    )
    kubernetes_maturity = models.CharField(max_length=40, blank=True)
    team_size = models.CharField(max_length=40, blank=True)

    consent_given = models.BooleanField(default=False)
    consent_text = models.TextField(
        blank=True,
        help_text="The exact wording shown when consent was given. Stored because 'they "
        "ticked a box' is not evidence of what they agreed to.",
    )
    consent_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=60, blank=True, help_text="fit-finder | request-demo")

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["-created_at"]), models.Index(fields=["contact_email"])]

    def __str__(self) -> str:
        return self.company_name or self.contact_email or f"Anonymous prospect {self.id}"

    @property
    def is_identified(self) -> bool:
        return bool(self.contact_email or self.company_name)


class FitAssessment(BaseModel, SyntheticDataMixin):
    """
    An indicative suitability assessment.

    `indicative_score` exists but is always published alongside `rubric` — the full
    breakdown of how each point was awarded — and `disclaimer`. A score without a visible
    rubric is a number people will quote at each other in a procurement meeting without
    knowing what it means.
    """

    prospect = models.ForeignKey(
        ProspectProfile, on_delete=models.CASCADE, related_name="assessments"
    )
    answers = models.JSONField(default=dict, help_text="Raw wizard answers, for reproducibility.")
    rubric_version = models.CharField(max_length=20, default="1.0")

    indicative_score = models.PositiveSmallIntegerField(
        help_text="0-100. Indicative only. Always rendered with the rubric breakdown."
    )
    band = models.CharField(max_length=32, choices=FitBand.choices, db_index=True)
    rubric = models.JSONField(
        default=list,
        help_text="Per-dimension breakdown: [{dimension, weight, awarded, max, reasoning}]. "
        "This is what makes the score defensible.",
    )

    requirement_summary = models.TextField()
    suitability_reasons = models.JSONField(default=list)
    technical_requirements = models.JSONField(default=list)
    advantages = models.JSONField(default=list)
    gaps = models.JSONField(
        default=list,
        help_text="Honest limitations and misfits. A fit assessment with no gaps is "
        "marketing, not an assessment.",
    )
    questions_for_sales = models.JSONField(default=list)
    caps_applied = models.JSONField(
        default=list,
        help_text="Hard caps from the rubric that overrode the weighted band. Persisted "
        "rather than recomputed so that reopening an assessment by its link shows the "
        "same reasoning, even after the rubric changes.",
    )
    next_step = models.TextField(blank=True)
    cited_sources = models.JSONField(
        default=list, help_text="Source ids from the product knowledge base."
    )
    disclaimer = models.TextField()
    generated_by = models.CharField(max_length=40, default="rubric")

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.prospect} — {self.band} ({self.indicative_score})"


class ArchitectureRecommendation(BaseModel, SyntheticDataMixin):
    """
    A proposed architecture laid out as a graph the frontend renders with React Flow.

    `conceptual_disclaimer` is mandatory and non-blank. The diagram mixes IOMETE's
    documented architecture with the customer's own stated systems; a reader must be able
    to tell which parts are documented product behaviour and which are a conceptual
    placement. Each node therefore also carries its own `claim_status`.
    """

    prospect = models.ForeignKey(
        ProspectProfile, null=True, blank=True, on_delete=models.CASCADE,
        related_name="recommendations",
    )
    assessment = models.ForeignKey(
        FitAssessment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recommendations",
    )
    title = models.CharField(max_length=200)
    inputs = models.JSONField(default=dict, help_text="The stated infrastructure this was built from.")
    nodes = models.JSONField(
        default=list,
        help_text="[{id, label, layer, kind, claim_status, description, sources}]. "
        "`claim_status` distinguishes documented product components from conceptual "
        "placements of the customer's own systems.",
    )
    edges = models.JSONField(default=list, help_text="[{source, target, label, kind}]")
    layers = models.JSONField(default=list)
    narrative = models.TextField(blank=True)
    integration_notes = models.JSONField(default=list)
    open_questions = models.JSONField(default=list)
    conceptual_disclaimer = models.TextField()
    cited_sources = models.JSONField(default=list)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title


class DemoRequestStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    QUALIFIED = "qualified", "Qualified"
    SCHEDULED = "scheduled", "Demo scheduled"
    CLOSED = "closed", "Closed"


class DemoRequest(BaseModel, SyntheticDataMixin):
    prospect = models.ForeignKey(
        ProspectProfile, on_delete=models.CASCADE, related_name="demo_requests"
    )
    assessment = models.ForeignKey(
        FitAssessment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="demo_requests",
        help_text="Attached when the request came from a completed Fit Finder, which is "
        "what makes it a qualified lead rather than a form fill.",
    )
    message = models.TextField(blank=True)
    preferred_timeframe = models.CharField(max_length=100, blank=True)
    interests = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=32, choices=DemoRequestStatus.choices, default=DemoRequestStatus.NEW,
        db_index=True,
    )
    internal_notes = models.TextField(
        blank=True, help_text="IOMETE-side only. Never serialized to the prospect."
    )
    handled_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="handled_demo_requests",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Demo request from {self.prospect} ({self.status})"

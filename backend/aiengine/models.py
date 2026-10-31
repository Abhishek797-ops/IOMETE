"""
Observability for the AI layer.

These rows exist so that an answer the product gave three months ago can be explained:
which retrieval backend ran, which channels contributed, which provider generated the
text, and which sources it was told to ground in. "The AI said so" is not an acceptable
audit answer for guidance about changing production infrastructure.

Note what is *not* here: prompts and completions are not stored verbatim. A prompt contains
redacted-but-still-customer-specific diagnostic text, and keeping a second copy of it in a
log table widens the blast radius for no operational benefit. Hashes plus structured
metadata answer the audit question without the duplication.
"""

from __future__ import annotations

from django.db import models

from common.models import BaseModel


class RetrievalRun(BaseModel):
    """One execution of `HybridRetrievalService.search()`."""

    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="retrieval_runs",
    )
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="retrieval_runs",
    )
    requested_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="retrieval_runs",
    )

    query_hash = models.CharField(
        max_length=64, db_index=True,
        help_text="SHA-256 of the normalised query. Lets us group repeat searches without "
        "storing the query text a second time.",
    )
    vector_backend = models.CharField(
        max_length=20, help_text="pgvector | numpy — what actually answered."
    )
    embedding_provider = models.CharField(max_length=40, blank=True)
    embedding_model = models.CharField(max_length=80, blank=True)

    channel_counts = models.JSONField(
        default=dict, blank=True,
        help_text="Candidates contributed per channel: "
        "{vector, lexical, fingerprint, metadata}.",
    )
    channel_weights = models.JSONField(default=dict, blank=True)
    candidate_count = models.PositiveIntegerField(default=0)
    returned_count = models.PositiveIntegerField(default=0)
    gated_count = models.PositiveIntegerField(
        default=0, help_text="How many high-scoring candidates the compatibility gate excluded."
    )
    duration_ms = models.PositiveIntegerField(default=0)
    tenant_scope_applied = models.BooleanField(
        default=True,
        help_text="Recorded explicitly: a retrieval run that did not apply tenant scoping "
        "would be the most severe defect in this product, so it is auditable.",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["organization", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"retrieval {self.vector_backend} → {self.returned_count} results"


class GenerationPurpose(models.TextChoices):
    TICKET_NORMALIZATION = "ticket_normalization", "Ticket normalization"
    MATCH_EXPLANATION = "match_explanation", "Match evidence explanation"
    RESOLUTION_GUIDANCE = "resolution_guidance", "Resolution guidance"
    KNOWLEDGE_EXTRACTION = "knowledge_extraction", "Knowledge draft extraction"
    ESCALATION_SUMMARY = "escalation_summary", "Escalation summary"
    FIT_NARRATIVE = "fit_narrative", "Fit assessment narrative"
    CLUSTER_HYPOTHESIS = "cluster_hypothesis", "Issue cluster hypothesis"


class AIGeneration(BaseModel):
    """One LLM (or demo-provider) invocation."""

    purpose = models.CharField(
        max_length=40, choices=GenerationPurpose.choices, db_index=True
    )
    provider = models.CharField(
        max_length=40, help_text="demo | gemini. 'demo' is deterministic and offline."
    )
    model = models.CharField(max_length=80, blank=True)
    was_live = models.BooleanField(
        default=False,
        help_text="False for the deterministic demo provider. Surfaced wherever generated "
        "text appears, so a reader always knows what produced it.",
    )

    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generations",
    )
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generations",
    )

    prompt_hash = models.CharField(max_length=64, blank=True)
    grounding_source_ids = models.JSONField(
        default=list, blank=True,
        help_text="The ticket references, playbook ids and knowledge-base source ids the "
        "model was given. Every claim in the output should trace to one of these.",
    )
    ungrounded_claim_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Claims the grounding validator could not attribute. Non-zero is a "
        "quality signal worth alerting on, not a silent condition.",
    )
    output_schema = models.CharField(max_length=80, blank=True)
    output_valid = models.BooleanField(default=True)
    duration_ms = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["purpose", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.purpose} via {self.provider} ({'live' if self.was_live else 'demo'})"

"""
Lakehouse playground.

The synthetic dataset and the SQL engine are *code*, not database rows — see
`lakehouse/services/`. That is deliberate: the playground must behave identically in every
environment, and a prospect running a sample query must not be able to affect what the
next prospect sees.

What is persisted is the query log, so the playground is observable and so a rate-limit or
abuse pattern is visible.
"""

from __future__ import annotations

from django.db import models

from common.models import BaseModel


class PlaygroundMode(models.TextChoices):
    """
    Two explicitly distinguishable modes.

    `DEMO` runs against the in-memory synthetic dataset with a restricted SELECT-only
    parser. `CONNECTED` would execute against a real IOMETE SQL endpoint — and is reachable
    only when an `IntegrationConfiguration` for the IOMETE provider has actually completed
    a live handshake. There is no code path that labels a demo result as connected.
    """

    DEMO = "demo", "Demo — synthetic dataset, simulated execution"
    CONNECTED = "connected", "Connected — executed against a live IOMETE SQL endpoint"


class LakehouseQueryRun(BaseModel):
    """One sample query execution in the playground."""

    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lakehouse_query_runs",
        help_text="Null for an anonymous prospect using the public playground.",
    )
    executed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lakehouse_query_runs",
    )
    session_key = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Opaque client-generated session id, so an anonymous prospect's query "
        "history persists within their visit without requiring an account.",
    )

    mode = models.CharField(
        max_length=20, choices=PlaygroundMode.choices, default=PlaygroundMode.DEMO, db_index=True
    )
    sql = models.TextField()
    dataset = models.CharField(max_length=80, blank=True)
    sample_query_id = models.SlugField(
        max_length=80, blank=True, help_text="Set when the user ran a curated sample."
    )

    succeeded = models.BooleanField(default=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=400, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    column_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    simulated_execution_plan = models.JSONField(
        default=list, blank=True,
        help_text="The illustrative Spark/Iceberg stages shown to the user. Labelled as "
        "illustrative, not as a real Spark plan.",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["session_key", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.mode} query → {self.row_count} rows ({self.duration_ms}ms)"

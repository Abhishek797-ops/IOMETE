"""
Integration configuration.

The central rule, enforced by the `mode` state machine below: **COMPASS never reports a
connection it has not made.** Having credentials on file is `CONFIGURED`. Only a
successful live handshake produces `CONNECTED`, and that state decays — if the last test
failed, the integration drops back to `CONFIGURED` rather than keeping a stale green light.

Credentials live in an `EncryptedJSONField` and are never serialized back out. The API
exposes which credential keys are present, never their values.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from common.crypto import EncryptedJSONField
from common.models import BaseModel


class IntegrationProvider(models.TextChoices):
    JIRA = "jira", "Jira Service Management"
    IOMETE = "iomete", "IOMETE platform (lakehouse connector)"
    MOCK = "mock", "Mock ticket provider (demo)"


class IntegrationMode(models.TextChoices):
    """
    Three states, and the distinction between the last two is the whole point.

    * `DEMO` — no credentials. Functional, deterministic, synthetic data. Clearly labelled.
    * `CONFIGURED` — credentials present but no successful handshake (yet, or any more).
    * `CONNECTED` — a live connection test succeeded. Set only by the connection-test
      service, never by saving a form.
    """

    DEMO = "demo", "Demo — simulated, no credentials configured"
    CONFIGURED = "configured", "Configured — credentials present, not yet verified"
    CONNECTED = "connected", "Connected — live connection verified"


class SyncStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial — some records failed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped — integration not connected"


class IntegrationConfiguration(BaseModel):
    """
    One configured integration.

    `organization` is nullable: a Jira connection may be platform-wide (IOMETE's own
    service desk) or scoped to one customer tenant.
    """

    provider = models.CharField(
        max_length=32, choices=IntegrationProvider.choices, db_index=True
    )
    display_name = models.CharField(max_length=150)
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.CASCADE,
        related_name="integrations",
        help_text="Null for a platform-wide integration.",
    )

    config = models.JSONField(
        default=dict, blank=True,
        help_text="Non-secret settings: base URL, project key, workspace, field mappings.",
    )
    credentials = EncryptedJSONField(
        default=dict, blank=True,
        help_text="Encrypted at rest. Write-only: never returned by the API.",
    )

    is_enabled = models.BooleanField(default=True)

    # --- Connection state (the honesty machinery) -----------------------------------
    mode = models.CharField(
        max_length=20, choices=IntegrationMode.choices, default=IntegrationMode.DEMO,
        db_index=True,
        help_text="Derived state. Only a successful live test can set 'connected'.",
    )
    last_connection_test_at = models.DateTimeField(null=True, blank=True)
    last_connection_ok = models.BooleanField(null=True, blank=True)
    last_connection_message = models.CharField(max_length=400, blank=True)
    connection_detail = models.JSONField(
        default=dict, blank=True,
        help_text="Non-secret facts the handshake returned (server version, account name, "
        "project name) — the evidence that the connection was real.",
    )

    # --- Sync state -----------------------------------------------------------------
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=20, choices=SyncStatus.choices, blank=True
    )
    webhook_configured = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_integrations",
    )

    class Meta:
        ordering = ("provider", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "organization"],
                name="unique_provider_per_organization",
            )
        ]
        indexes = [models.Index(fields=["provider", "mode", "is_enabled"])]

    def __str__(self) -> str:
        scope = self.organization.slug if self.organization else "platform"
        return f"{self.get_provider_display()} @ {scope} ({self.mode})"

    # --- Derived state ---------------------------------------------------------------

    @property
    def credential_keys(self) -> list[str]:
        """Which credential keys are on file. Safe to expose; the values are not."""
        return sorted(self.credentials.keys()) if isinstance(self.credentials, dict) else []

    @property
    def has_credentials(self) -> bool:
        return bool(self.credential_keys)

    def recompute_mode(self) -> str:
        """
        Derive `mode` from facts, never from intent.

        Called after any credential change and after every connection test. A failed or
        never-run test cannot yield `CONNECTED`, so a stale green light is impossible.
        """
        if not self.has_credentials or not self.is_enabled:
            self.mode = IntegrationMode.DEMO
        elif self.last_connection_ok is True:
            self.mode = IntegrationMode.CONNECTED
        else:
            self.mode = IntegrationMode.CONFIGURED
        return self.mode

    @property
    def is_live(self) -> bool:
        return self.mode == IntegrationMode.CONNECTED

    @property
    def is_simulated(self) -> bool:
        return self.mode == IntegrationMode.DEMO

    def mark_connection_result(self, *, ok: bool, message: str, detail: dict | None = None) -> None:
        self.last_connection_test_at = timezone.now()
        self.last_connection_ok = ok
        self.last_connection_message = message[:400]
        self.connection_detail = detail or {}
        self.recompute_mode()


class IntegrationSyncRun(BaseModel):
    """
    One synchronisation attempt. Persisted so that failed syncs and retries are visible
    rather than disappearing into a log file.
    """

    integration = models.ForeignKey(
        IntegrationConfiguration, on_delete=models.CASCADE, related_name="sync_runs"
    )
    direction = models.CharField(
        max_length=20,
        choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
        default="inbound",
    )
    status = models.CharField(max_length=20, choices=SyncStatus.choices)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    records_seen = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_failed = models.PositiveIntegerField(default=0)
    attempt = models.PositiveSmallIntegerField(default=1)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    was_simulated = models.BooleanField(
        default=False,
        help_text="True when the run used the demo adapter. Surfaced in the UI so a "
        "simulated sync is never mistaken for a real one.",
    )
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [models.Index(fields=["integration", "-started_at"])]

    def __str__(self) -> str:
        return f"{self.integration.provider} sync {self.status} at {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration_seconds(self) -> float | None:
        if not self.finished_at:
            return None
        return round((self.finished_at - self.started_at).total_seconds(), 2)

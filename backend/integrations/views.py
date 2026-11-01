"""
Integration configuration API.

Credentials are **write-only**. The serializer exposes which credential keys are on file,
never their values — so an administrator can see "api_token is set" without the API ever
becoming a credential-exfiltration endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization
from common.audit import record_audit
from common.permissions import IsIometeStaff, IsPlatformAdmin

from .models import (
    IntegrationConfiguration,
    IntegrationMode,
    IntegrationProvider,
    IntegrationSyncRun,
)
from .services import registry, sync

logger = logging.getLogger("compass.integrations")


class IntegrationSerializer(serializers.ModelSerializer):
    """
    Read serializer.

    `credentials` is absent. `credential_keys` reports which keys exist so the UI can show
    completeness without ever transmitting a secret.
    """

    provider_label = serializers.CharField(source="get_provider_display", read_only=True)
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    organization_name = serializers.CharField(
        source="organization.name", read_only=True, default=None
    )
    credential_keys = serializers.ListField(child=serializers.CharField(), read_only=True)
    has_credentials = serializers.BooleanField(read_only=True)
    is_live = serializers.BooleanField(read_only=True)
    adapter_description = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationConfiguration
        fields = (
            "id", "provider", "provider_label", "display_name", "organization",
            "organization_name", "config", "credential_keys", "has_credentials",
            "is_enabled", "mode", "mode_label", "is_live", "last_connection_test_at",
            "last_connection_ok", "last_connection_message", "connection_detail",
            "last_sync_at", "last_sync_status", "webhook_configured",
            "adapter_description", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "provider_label", "mode", "mode_label", "is_live", "credential_keys",
            "has_credentials", "last_connection_test_at", "last_connection_ok",
            "last_connection_message", "connection_detail", "last_sync_at",
            "last_sync_status", "webhook_configured", "adapter_description",
            "organization_name", "created_at", "updated_at",
        )

    def get_adapter_description(self, obj) -> dict:
        return registry.adapter_for(obj).describe().to_dict()

    def validate_config(self, value: dict) -> dict:
        """
        Reject anything secret-looking in the non-secret `config` blob.

        Without this, an administrator pasting a token into `config` instead of
        `credentials` would store it unencrypted and have it returned by every GET.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError("config must be an object.")
        suspicious = [
            key for key in value
            if any(
                token in str(key).lower()
                for token in ("token", "secret", "password", "api_key", "apikey",
                              "credential", "private_key")
            )
        ]
        if suspicious:
            raise serializers.ValidationError(
                f"These look like credentials and must go in `credentials`, which is "
                f"encrypted at rest and never returned: {', '.join(suspicious)}."
            )
        return value


class IntegrationWriteSerializer(IntegrationSerializer):
    """Write serializer. `credentials` is accepted but never read back."""

    credentials = serializers.DictField(
        write_only=True, required=False,
        help_text="Encrypted at rest. Write-only — never returned by the API. "
        "Jira: {email, api_token}. IOMETE: {api_token}.",
    )

    class Meta(IntegrationSerializer.Meta):
        fields = (*IntegrationSerializer.Meta.fields, "credentials")


class SyncRunSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)
    provider = serializers.CharField(source="integration.provider", read_only=True)

    class Meta:
        model = IntegrationSyncRun
        fields = (
            "id", "integration", "provider", "direction", "status", "started_at",
            "finished_at", "duration_seconds", "records_seen", "records_created",
            "records_updated", "records_failed", "attempt", "error_code",
            "error_message", "was_simulated", "detail",
        )
        read_only_fields = fields


@extend_schema_view(
    list=extend_schema(
        tags=["integrations"],
        summary="List integrations",
        description=(
            "Each entry reports its real `mode` — `demo` (simulated), `configured` "
            "(credentials present, unverified) or `connected` (a live test succeeded) — "
            "plus the adapter's own description of what it can and cannot do in that mode.\n\n"
            "Credential *values* are never returned. `credential_keys` tells you which keys "
            "are on file."
        ),
    ),
    retrieve=extend_schema(tags=["integrations"], summary="Retrieve an integration"),
    create=extend_schema(tags=["integrations"], summary="Configure an integration"),
    partial_update=extend_schema(tags=["integrations"], summary="Update an integration"),
)
class IntegrationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = IntegrationConfiguration.objects.select_related("organization", "created_by")
    permission_classes = [IsPlatformAdmin]
    filterset_fields = ("provider", "mode", "is_enabled", "organization")

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return IntegrationWriteSerializer
        return IntegrationSerializer

    def perform_create(self, serializer):
        configuration = serializer.save(created_by=self.request.user)
        # Mode is derived, never asserted: a newly saved integration with credentials is
        # `configured`, not `connected`, until a test succeeds.
        configuration.recompute_mode()
        configuration.save(update_fields=["mode", "updated_at"])
        record_audit(
            action="integration.configured",
            actor=self.request.user,
            organization=configuration.organization,
            target_type="integration",
            target_id=str(configuration.id),
            summary=f"Configured {configuration.get_provider_display()}",
            metadata={
                "provider": configuration.provider,
                "credential_keys": configuration.credential_keys,
                "mode": configuration.mode,
            },
        )

    def perform_update(self, serializer):
        had_credentials = serializer.instance.has_credentials
        configuration = serializer.save()
        if configuration.has_credentials != had_credentials or "credentials" in serializer.validated_data:
            # Credentials changed, so any previous verification is void.
            configuration.last_connection_ok = None
            configuration.last_connection_message = (
                "Credentials changed; re-run the connection test."
            )
            configuration.connection_detail = {}
            record_audit(
                action="integration.credentials_updated",
                actor=self.request.user,
                organization=configuration.organization,
                target_type="integration",
                target_id=str(configuration.id),
                summary=f"{configuration.get_provider_display()}: credentials updated",
                metadata={"credential_keys": configuration.credential_keys},
            )
        configuration.recompute_mode()
        configuration.save()

    @extend_schema(
        tags=["integrations"],
        summary="Test the connection",
        description=(
            "Performs a **real** request against the configured endpoint and derives the "
            "integration's mode from the result.\n\n"
            "This is the only operation in COMPASS that can set `mode` to `connected`, and "
            "only a successful live handshake does so. A failure demotes a previously "
            "connected integration back to `configured`, so a stale green light is "
            "impossible. The response includes the non-secret `evidence` the remote system "
            "returned — a server version, an account name, a project name — so the "
            "connected state is verifiable rather than merely asserted."
        ),
        request=None,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        configuration = self.get_object()
        result = sync.test_connection(configuration=configuration, actor=request.user)
        configuration.refresh_from_db()
        return Response(
            {
                "ok": result.ok,
                "message": result.message,
                "evidence": result.evidence,
                "error_code": result.error_code,
                "mode": configuration.mode,
                "integration": IntegrationSerializer(configuration).data,
            },
            status=status.HTTP_200_OK if result.ok else status.HTTP_502_BAD_GATEWAY,
        )

    @extend_schema(
        tags=["integrations"],
        summary="Run an inbound ticket synchronisation",
        description=(
            "Imports issues from the ticket provider into COMPASS tickets, through the full "
            "intake pipeline (redact → normalise → fingerprint → embed).\n\n"
            "Deduplicated on the external key, so re-running is idempotent. When Jira is "
            "not configured, the simulated provider is used and the run is recorded with "
            "`was_simulated: true` — a simulated sync is never presented as a real one."
        ),
        request=None,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="sync")
    def run_sync(self, request, pk=None):
        configuration = self.get_object()
        organization = configuration.organization
        if organization is None:
            organization_id = request.data.get("organization")
            if not organization_id:
                return Response(
                    {
                        "error": {
                            "code": "domain_validation_error",
                            "message": (
                                "This is a platform-wide integration, so the target customer "
                                "organization must be specified."
                            ),
                            "details": {},
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            organization = get_object_or_404(Organization, id=organization_id)

        result = sync.sync_inbound(
            organization=organization,
            actor=request.user,
            configuration=configuration,
            limit=int(request.data.get("limit", 25)),
        )
        return Response(
            {
                "status": result.run.status,
                "was_simulated": result.was_simulated,
                "message": result.message,
                "created": [ticket.reference for ticket in result.created],
                "updated": [ticket.reference for ticket in result.updated],
                "failed": result.failed,
                "run": SyncRunSerializer(result.run).data,
            }
        )

    @extend_schema(
        tags=["integrations"], summary="Synchronisation history",
        responses={200: SyncRunSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="sync-runs")
    def sync_runs(self, request, pk=None):
        configuration = self.get_object()
        runs = configuration.sync_runs.all()[:50]
        return Response(SyncRunSerializer(runs, many=True).data)


@extend_schema(
    tags=["integrations"],
    summary="Integration mode report",
    description=(
        "What is real in this deployment, per provider. Drives the \"simulated\" badges in "
        "the UI. Available to IOMETE staff; the public subset is on "
        "`/api/v1/system/status/`."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class IntegrationStatusView(APIView):
    permission_classes = [IsIometeStaff]

    def get(self, _request) -> Response:
        return Response(registry.describe_integration_modes())


@extend_schema(
    tags=["integrations"],
    summary="Jira webhook receiver",
    description=(
        "Receives Jira webhook notifications.\n\n"
        "Refuses every request unless the integration has a configured webhook secret and "
        "the request carries a valid HMAC-SHA256 signature over the raw body. An "
        "unauthenticated endpoint that creates tickets is an open door, so there is no "
        "'accept unsigned for convenience' path."
    ),
    request=None,
    responses={200: OpenApiTypes.OBJECT},
)
class JiraWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def post(self, request, integration_id=None) -> Response:
        configuration = get_object_or_404(
            IntegrationConfiguration,
            id=integration_id,
            provider=IntegrationProvider.JIRA,
            is_enabled=True,
        )

        secret = (configuration.credentials or {}).get("webhook_secret", "")
        if not secret or not configuration.webhook_configured:
            return Response(
                {
                    "error": {
                        "code": "integration_not_configured",
                        "message": (
                            "Webhook delivery is not enabled for this integration. Configure "
                            "a webhook secret first."
                        ),
                        "details": {},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            secret.encode(), request.body, hashlib.sha256
        ).hexdigest()
        # Constant-time comparison: a naive `==` leaks signature bytes through timing.
        if not signature or not hmac.compare_digest(signature, expected):
            logger.warning(
                "Rejected a Jira webhook with an invalid signature for integration %s.",
                integration_id,
            )
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "Invalid or missing webhook signature.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if configuration.mode != IntegrationMode.CONNECTED:
            return Response(
                {
                    "error": {
                        "code": "integration_not_configured",
                        "message": (
                            "The signature is valid but this integration has no verified "
                            "connection, so inbound events are not processed. Run a "
                            "connection test first."
                        ),
                        "details": {"mode": configuration.mode},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        event = (request.data or {}).get("webhookEvent", "unknown")
        issue_key = ((request.data or {}).get("issue") or {}).get("key", "")

        record_audit(
            action="integration.sync_run",
            organization=configuration.organization,
            target_type="integration",
            target_id=str(configuration.id),
            summary=f"Jira webhook received: {event} for {issue_key or 'an issue'}",
            metadata={"event": event, "issue_key": issue_key},
        )

        # Deliberately conservative: acknowledge, and let the next scheduled inbound sync
        # reconcile. Mutating a ticket directly from a webhook payload — which can arrive
        # out of order and duplicated — is how two systems disagree about state.
        return Response(
            {
                "received": True,
                "event": event,
                "issue_key": issue_key,
                "note": (
                    "Acknowledged. The change will be reconciled by the next inbound "
                    "synchronisation, which deduplicates on the external key and cannot be "
                    "confused by out-of-order delivery."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )

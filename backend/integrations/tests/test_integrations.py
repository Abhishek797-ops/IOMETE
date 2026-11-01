"""
Integrations — acceptance tests 12 and 13.

Test 12: missing Jira credentials must not break ticket workflows.
Test 13: connected mode must never appear active without a real connection.

The second is the one that matters most. A green "connected" badge over simulated data is
the single most damaging thing an integration layer can do, so the state machine is tested
from every direction: saving credentials, failing a test, passing then failing again, and
the demo adapter's own refusal to claim success.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from accounts.models import Organization
from common.exceptions import IntegrationNotConfiguredError
from integrations.models import (
    IntegrationConfiguration,
    IntegrationMode,
    IntegrationProvider,
    SyncStatus,
)
from integrations.services import registry, sync
from integrations.services.iomete import DemoLakehouseAdapter, IometeAdapter
from integrations.services.jira import JiraAdapter, MockTicketProvider
from tickets.models import Ticket

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


# =======================================================================================
# Acceptance test 12 — Jira absence does not break anything
# =======================================================================================


class TestTicketWorkflowsSurviveMissingJira:
    def test_the_resolved_provider_is_the_mock_when_jira_is_unconfigured(self):
        provider = registry.ticket_provider()
        assert isinstance(provider, MockTicketProvider)
        description = provider.describe()
        assert description.mode == IntegrationMode.DEMO
        assert description.is_simulated is True
        assert description.missing_configuration, (
            "The adapter should say what would be needed for live mode."
        )

    def test_a_customer_can_submit_and_resolve_a_ticket_with_no_jira(
        self, auth_client, customer_a, org_a
    ):
        client = auth_client(customer_a)
        created = client.post(
            "/api/v1/tickets/",
            {
                "title": "Executors keep restarting during the nightly job",
                "description": (
                    "The nightly aggregation fails partway through and executors are "
                    "terminated repeatedly."
                ),
                "component": "spark_compute",
                "severity": "high",
                "iomete_version": "3.19.1",
                "environment": "production",
                "error_message": "Container killed: OOMKilled (exit code 137)",
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        ticket_id = created.data["id"]

        assert client.post(
            f"/api/v1/tickets/{ticket_id}/similar/", {}, format="json"
        ).status_code == 200
        assert client.post(
            f"/api/v1/tickets/{ticket_id}/comment/",
            {"body": "Adding more detail about the failure window."},
            format="json",
        ).status_code == 201
        assert client.post(
            f"/api/v1/tickets/{ticket_id}/escalate/",
            {"reason": "We cannot determine the cause from the logs available to us."},
            format="json",
        ).status_code == 201

    def test_an_inbound_sync_runs_against_the_mock_and_is_marked_simulated(
        self, org_a, fde
    ):
        result = sync.sync_inbound(organization=org_a, actor=fde, limit=5)
        assert result.was_simulated is True
        assert result.created, "The mock provider should have produced importable issues."
        assert result.run.status == SyncStatus.SUCCESS
        assert result.run.was_simulated is True
        assert "simulated synchronisation" in result.message

        # The imported tickets went through the real intake pipeline.
        imported = Ticket.objects.filter(organization=org_a, external_reference="SUP-4412").first()
        assert imported is not None
        assert imported.fingerprint_id is not None
        assert imported.embedding
        assert imported.is_synthetic is True
        assert imported.external_provider == "jira-demo", (
            "A simulated import must not claim the 'jira' provider."
        )

    def test_a_repeated_sync_updates_rather_than_duplicating(self, org_a, fde):
        first = sync.sync_inbound(organization=org_a, actor=fde, limit=5)
        second = sync.sync_inbound(organization=org_a, actor=fde, limit=5)
        assert first.created
        assert second.created == []
        assert second.updated
        assert Ticket.objects.filter(
            organization=org_a, external_reference="SUP-4412"
        ).count() == 1

    def test_a_simulated_outbound_push_is_labelled(self, make_ticket, org_a, customer_a, fde):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        result = sync.push_escalation(ticket=ticket, actor=fde)
        assert result["is_simulated"] is True
        assert result["key"].startswith("DEMO-"), (
            "A simulated key must be visibly distinct from a real Jira key."
        )
        assert "notice" in result
        ticket.refresh_from_db()
        assert ticket.external_provider == "jira-demo"

    def test_a_sync_against_the_mock_never_claims_connected(self, org_a, fde):
        sync.sync_inbound(organization=org_a, actor=fde, limit=3)
        configuration = IntegrationConfiguration.objects.get(
            provider=IntegrationProvider.JIRA, organization=org_a
        )
        assert configuration.mode == IntegrationMode.DEMO


# =======================================================================================
# Acceptance test 13 — connected is never claimed without a handshake
# =======================================================================================


class TestConnectedModeRequiresAHandshake:
    def test_the_lakehouse_adapter_is_the_demo_one_by_default(self):
        adapter = registry.lakehouse_adapter()
        assert isinstance(adapter, DemoLakehouseAdapter)
        description = adapter.describe()
        assert description.mode == IntegrationMode.DEMO
        assert description.is_simulated is True

    def test_saving_credentials_yields_configured_not_connected(self, platform_admin):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Customer IOMETE",
            config={"base_url": "https://lakehouse.example/catalog", "verify_tls": True},
            credentials={"api_token": "a-token-that-was-never-verified"},
            created_by=platform_admin,
        )
        configuration.recompute_mode()
        assert configuration.mode == IntegrationMode.CONFIGURED
        assert configuration.is_live is False

    def test_a_failed_connection_test_cannot_produce_connected(
        self, platform_admin, monkeypatch
    ):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Unreachable IOMETE",
            config={"base_url": "https://unreachable.invalid/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )

        from integrations.services import base

        def _fail(*_args, **_kwargs):
            return False, None, "Could not reach unreachable.invalid: ConnectionError"

        monkeypatch.setattr(base, "request_json", _fail)
        monkeypatch.setattr("integrations.services.iomete.request_json", _fail)

        result = sync.test_connection(configuration=configuration, actor=platform_admin)
        assert result.ok is False
        configuration.refresh_from_db()
        assert configuration.mode == IntegrationMode.CONFIGURED
        assert configuration.last_connection_ok is False

    def test_a_successful_handshake_produces_connected_with_evidence(
        self, platform_admin, monkeypatch
    ):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Reachable IOMETE",
            config={"base_url": "https://lakehouse.example/catalog", "warehouse": "main"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )

        def _ok(_session, _method, url, **_kwargs):
            if url.endswith("/v1/config"):
                return True, {"defaults": {"warehouse": "main"}, "overrides": {}}, "OK"
            if url.endswith("/v1/namespaces"):
                return True, {"namespaces": [["retail"], ["telemetry"]]}, "OK"
            return False, None, "unexpected"

        monkeypatch.setattr("integrations.services.iomete.request_json", _ok)

        result = sync.test_connection(configuration=configuration, actor=platform_admin)
        assert result.ok is True
        configuration.refresh_from_db()
        assert configuration.mode == IntegrationMode.CONNECTED
        # Evidence is what makes "connected" verifiable rather than merely asserted.
        assert result.evidence["spec"] == "Apache Iceberg REST Catalog"
        assert result.evidence["namespaces_visible"] == 2

    def test_a_later_failure_demotes_a_previously_connected_integration(
        self, platform_admin, monkeypatch
    ):
        """No stale green lights: the mode is derived from the latest fact, not remembered."""
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Flaky IOMETE",
            config={"base_url": "https://lakehouse.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )

        def _ok(_session, _method, url, **_kwargs):
            if url.endswith("/v1/config"):
                return True, {"defaults": {}, "overrides": {}}, "OK"
            return True, {"namespaces": []}, "OK"

        monkeypatch.setattr("integrations.services.iomete.request_json", _ok)
        sync.test_connection(configuration=configuration, actor=platform_admin)
        configuration.refresh_from_db()
        assert configuration.mode == IntegrationMode.CONNECTED

        def _fail(*_args, **_kwargs):
            return False, None, "Authentication was rejected (401)."

        monkeypatch.setattr("integrations.services.iomete.request_json", _fail)
        sync.test_connection(configuration=configuration, actor=platform_admin)
        configuration.refresh_from_db()
        assert configuration.mode == IntegrationMode.CONFIGURED

    def test_removing_credentials_reverts_to_demo(self, platform_admin, monkeypatch):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="IOMETE",
            config={"base_url": "https://lakehouse.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        configuration.last_connection_ok = True
        configuration.recompute_mode()
        assert configuration.mode == IntegrationMode.CONNECTED

        configuration.credentials = {}
        configuration.recompute_mode()
        assert configuration.mode == IntegrationMode.DEMO

    def test_disabling_reverts_to_demo(self, platform_admin):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="IOMETE",
            config={"base_url": "https://x.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        configuration.last_connection_ok = True
        configuration.is_enabled = False
        configuration.recompute_mode()
        assert configuration.mode == IntegrationMode.DEMO

    def test_the_demo_adapters_refuse_to_report_a_successful_connection(self):
        """
        Both demo adapters are working correctly and are not *connected* to anything. A
        truthful `test_connection` therefore fails — otherwise `recompute_mode()` would
        promote a simulation to connected.
        """
        for adapter in (DemoLakehouseAdapter(), MockTicketProvider()):
            result = adapter.test_connection()
            assert result.ok is False
            assert result.error_code == "simulated_provider"
            assert "functioning normally" in result.message

    def test_an_unconfigured_adapter_cannot_be_tested_into_connected(self, platform_admin):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Half configured",
            config={},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        adapter = IometeAdapter(configuration)
        assert adapter.is_configured is False
        result = adapter.test_connection()
        assert result.ok is False
        assert result.error_code == "not_configured"
        assert any("base_url" in item for item in adapter.missing_configuration)

    def test_catalog_reads_refuse_without_a_verified_connection(self, platform_admin):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Unverified",
            config={"base_url": "https://lakehouse.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        configuration.recompute_mode()
        adapter = IometeAdapter(configuration)
        with pytest.raises(IntegrationNotConfiguredError) as excinfo:
            adapter.list_namespaces()
        assert "connection test" in str(excinfo.value.detail).lower()


class TestConnectedModeNeverFabricatesQueryResults:
    def test_connected_sql_execution_raises_rather_than_returning_demo_data(
        self, platform_admin, monkeypatch
    ):
        """
        IOMETE's documented query interfaces are driver-based, not REST. Returning synthetic
        rows under a connected label would be the worst possible behaviour, so the adapter
        raises and explains instead.
        """
        from common.exceptions import IntegrationUnavailableError

        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Connected IOMETE",
            config={"base_url": "https://lakehouse.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        configuration.last_connection_ok = True
        configuration.recompute_mode()
        configuration.save()

        adapter = IometeAdapter(configuration)
        with pytest.raises(IntegrationUnavailableError) as excinfo:
            adapter.run_query("SELECT 1")
        message = str(excinfo.value.detail)
        assert "cannot execute SQL" in message
        assert "Arrow Flight" in message
        assert "will not return synthetic results" in message

    def test_the_playground_endpoint_refuses_sql_in_connected_mode(
        self, api, platform_admin, monkeypatch
    ):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.IOMETE,
            display_name="Connected IOMETE",
            config={"base_url": "https://lakehouse.example/catalog"},
            credentials={"api_token": "token"},
            created_by=platform_admin,
        )
        configuration.last_connection_ok = True
        configuration.recompute_mode()
        configuration.save()
        assert configuration.mode == IntegrationMode.CONNECTED

        response = api.post(
            "/api/v1/lakehouse-demo/query/",
            {"sql": "SELECT 1"},
            format="json",
        )
        assert response.status_code == 409
        assert response.data["error"]["code"] == "integration_unavailable"
        assert "will not return synthetic results" in response.data["error"]["message"]

    def test_the_playground_reports_demo_mode_by_default(self, api):
        response = api.get("/api/v1/lakehouse-demo/status/")
        assert response.status_code == 200
        assert response.data["mode"] == "demo"
        assert response.data["is_simulated"] is True
        assert response.data["sql_execution_available"] is True

    def test_the_catalog_endpoint_refuses_in_demo_mode(self, api):
        """No substituting synthetic data for a live catalog read."""
        response = api.get("/api/v1/lakehouse-demo/catalog/retail_analytics/orders/")
        assert response.status_code == 409
        assert response.data["error"]["code"] == "integration_not_configured"


class TestEnvironmentConfiguredIntegrations:
    @override_settings(
        JIRA_BASE_URL="https://acme.atlassian.net",
        JIRA_EMAIL="ops@acme.example",
        JIRA_API_TOKEN="a-token",
        JIRA_PROJECT_KEY="SUP",
    )
    def test_environment_variables_produce_configured_not_connected(self):
        provider = registry.ticket_provider()
        assert isinstance(provider, JiraAdapter)
        description = provider.describe()
        assert description.mode == IntegrationMode.CONFIGURED
        assert description.is_simulated is True, (
            "Configured-but-unverified must still be treated as not live."
        )

    @override_settings(
        JIRA_BASE_URL="https://acme.atlassian.net",
        JIRA_EMAIL="ops@acme.example",
        JIRA_API_TOKEN="a-token",
        JIRA_PROJECT_KEY=None,
    )
    def test_incomplete_environment_configuration_falls_back_to_the_mock(self):
        provider = registry.ticket_provider()
        assert isinstance(provider, MockTicketProvider)

    @override_settings(
        JIRA_BASE_URL="https://acme.atlassian.net",
        JIRA_EMAIL="ops@acme.example",
        JIRA_API_TOKEN="a-token",
        JIRA_PROJECT_KEY="SUP",
    )
    def test_jira_operations_require_configuration_before_they_will_run(self, monkeypatch):
        """
        With credentials present but unreachable, the adapter raises a typed error rather
        than silently returning nothing — a sync that quietly imports zero issues is worse
        than one that fails loudly.
        """
        from common.exceptions import IntegrationUnavailableError

        provider = registry.ticket_provider()

        def _fail(*_args, **_kwargs):
            return False, None, "Timed out connecting to acme.atlassian.net after 10s."

        monkeypatch.setattr("integrations.services.jira.request_json", _fail)
        with pytest.raises(IntegrationUnavailableError):
            provider.fetch_issues(limit=5)

    def test_a_failed_sync_is_recorded_rather_than_swallowed(
        self, org_a, fde, platform_admin, monkeypatch
    ):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.JIRA,
            display_name="Jira",
            organization=org_a,
            config={"base_url": "https://acme.atlassian.net", "project_key": "SUP"},
            credentials={"email": "ops@acme.example", "api_token": "token"},
            created_by=platform_admin,
        )

        def _fail(*_args, **_kwargs):
            return False, None, "Authentication was rejected (401)."

        monkeypatch.setattr("integrations.services.jira.request_json", _fail)
        result = sync.sync_inbound(
            organization=org_a, actor=fde, configuration=configuration, limit=5
        )
        assert result.run.status == SyncStatus.FAILED
        assert result.run.error_code
        assert result.run.error_message
        assert "failed" in result.message.lower()


class TestCredentialsAreNeverReturned:
    @pytest.fixture
    def configuration(self, platform_admin, org_a):
        return IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.JIRA,
            display_name="Jira",
            organization=org_a,
            config={"base_url": "https://acme.atlassian.net", "project_key": "SUP"},
            credentials={"email": "ops@acme.example", "api_token": "super-secret-token"},
            created_by=platform_admin,
        )

    def test_the_api_never_serializes_credential_values(
        self, auth_client, platform_admin, configuration
    ):
        response = auth_client(platform_admin).get(
            f"/api/v1/integrations/{configuration.id}/"
        )
        assert response.status_code == 200
        serialised = str(response.data)
        assert "super-secret-token" not in serialised
        # But which keys exist is safe and useful.
        assert set(response.data["credential_keys"]) == {"api_token", "email"}
        assert response.data["has_credentials"] is True

    def test_credentials_are_encrypted_at_rest(self, configuration):
        """
        Read the raw column, bypassing the field's decryption, to prove what is actually on
        disk.

        Every row is read rather than filtering by id, because a UUID primary key is stored
        differently per backend (SQLite keeps 32 hex characters without hyphens), and the
        assertion — "the plaintext token appears nowhere in this table" — is the one that
        matters anyway.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT credentials FROM integrations_integrationconfiguration")
            rows = [row[0] for row in cursor.fetchall()]

        assert rows, "The configuration row should exist."
        for stored in rows:
            assert "super-secret-token" not in stored
            assert stored.startswith("enc:v1:"), (
                f"Credentials were stored unencrypted: {stored[:40]!r}"
            )

    def test_a_round_trip_decrypts_correctly(self, configuration):
        configuration.refresh_from_db()
        assert configuration.credentials["api_token"] == "super-secret-token"

    def test_secret_looking_keys_are_rejected_from_the_non_secret_config(
        self, auth_client, platform_admin, org_b
    ):
        response = auth_client(platform_admin).post(
            "/api/v1/integrations/",
            {
                "provider": "jira",
                "display_name": "Misconfigured",
                "organization": str(org_b.id),
                "config": {"base_url": "https://x.example", "api_token": "oops"},
            },
            format="json",
        )
        assert response.status_code == 400
        assert "credentials" in str(response.data).lower()

    def test_integration_management_is_platform_admin_only(
        self, auth_client, fde, customer_a_admin, configuration
    ):
        for user in (fde, customer_a_admin):
            response = auth_client(user).get(f"/api/v1/integrations/{configuration.id}/")
            assert response.status_code == 403, user.email

    def test_changing_credentials_invalidates_a_previous_verification(
        self, configuration, platform_admin, auth_client
    ):
        configuration.last_connection_ok = True
        configuration.recompute_mode()
        configuration.save()
        assert configuration.mode == IntegrationMode.CONNECTED

        response = auth_client(platform_admin).patch(
            f"/api/v1/integrations/{configuration.id}/",
            {"credentials": {"email": "ops@acme.example", "api_token": "rotated-token"}},
            format="json",
        )
        assert response.status_code == 200
        configuration.refresh_from_db()
        assert configuration.mode == IntegrationMode.CONFIGURED
        assert configuration.last_connection_ok is None
        assert "re-run the connection test" in configuration.last_connection_message


class TestWebhookSecurity:
    @pytest.fixture
    def configuration(self, platform_admin, org_a):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.JIRA,
            display_name="Jira",
            organization=org_a,
            config={"base_url": "https://acme.atlassian.net", "project_key": "SUP"},
            credentials={"email": "ops@acme.example", "api_token": "token"},
            created_by=platform_admin,
        )
        sync.configure_webhook_secret(
            configuration=configuration, secret="a-sufficiently-long-secret"
        )
        configuration.last_connection_ok = True
        configuration.recompute_mode()
        configuration.save()
        return configuration

    def test_an_unsigned_webhook_is_refused(self, api, configuration):
        response = api.post(
            f"/api/v1/integrations/webhooks/jira/{configuration.id}/",
            {"webhookEvent": "jira:issue_updated"},
            format="json",
        )
        assert response.status_code == 403
        assert "signature" in response.data["error"]["message"].lower()

    def test_a_wrongly_signed_webhook_is_refused(self, api, configuration):
        response = api.post(
            f"/api/v1/integrations/webhooks/jira/{configuration.id}/",
            {"webhookEvent": "jira:issue_updated"},
            format="json",
            HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
        )
        assert response.status_code == 403

    def test_a_correctly_signed_webhook_is_accepted(self, api, configuration):
        import hashlib
        import hmac
        import json

        payload = {"webhookEvent": "jira:issue_updated", "issue": {"key": "SUP-1"}}
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(
            b"a-sufficiently-long-secret", body, hashlib.sha256
        ).hexdigest()

        response = api.generic(
            "POST",
            f"/api/v1/integrations/webhooks/jira/{configuration.id}/",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        assert response.status_code == 202
        assert response.data["received"] is True
        assert response.data["issue_key"] == "SUP-1"

    def test_a_webhook_without_a_configured_secret_is_refused(
        self, api, platform_admin, org_b
    ):
        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.JIRA,
            display_name="No webhook secret",
            organization=org_b,
            config={"base_url": "https://x.example", "project_key": "SUP"},
            credentials={"email": "a@b.example", "api_token": "token"},
            created_by=platform_admin,
        )
        response = api.post(
            f"/api/v1/integrations/webhooks/jira/{configuration.id}/",
            {"webhookEvent": "jira:issue_updated"},
            format="json",
        )
        assert response.status_code == 409
        assert response.data["error"]["code"] == "integration_not_configured"

    def test_a_short_webhook_secret_is_rejected(self, platform_admin, org_b):
        from common.exceptions import DomainValidationError

        configuration = IntegrationConfiguration.objects.create(
            provider=IntegrationProvider.JIRA,
            display_name="Jira",
            organization=org_b,
            config={},
            credentials={},
            created_by=platform_admin,
        )
        with pytest.raises(DomainValidationError):
            sync.configure_webhook_secret(configuration=configuration, secret="short")


class TestModeReporting:
    def test_the_status_report_covers_both_providers_with_a_notice(self):
        described = registry.describe_integration_modes()
        assert set(described) >= {"jira", "iomete", "notice"}
        for provider in ("jira", "iomete"):
            entry = described[provider]
            assert entry["mode"] in {"demo", "configured", "connected"}
            assert entry["summary"]
            assert entry["purpose"]
            assert "capabilities" in entry
            assert "limitations" in entry
        assert "only reported as `connected`" in described["notice"]

    def test_the_staff_endpoint_exposes_the_report(self, auth_client, fde):
        response = auth_client(fde).get("/api/v1/integrations/status/")
        assert response.status_code == 200
        assert response.data["jira"]["is_simulated"] is True

    def test_customers_cannot_read_the_integration_status(self, auth_client, customer_a_admin):
        response = auth_client(customer_a_admin).get("/api/v1/integrations/status/")
        assert response.status_code == 403

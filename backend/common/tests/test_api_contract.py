"""
Cross-cutting API contract: auth, error shape, pagination, throttling and audit.

These are the behaviours every endpoint relies on, so a regression here breaks the whole
frontend at once rather than one page.
"""

from __future__ import annotations

import pytest

from accounts.models import AuditLog, Membership, MembershipRole, SystemRole, User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


class TestAuthentication:
    def test_login_returns_a_token_pair_and_the_user(self, api, customer_a):
        response = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": PASSWORD},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["refresh"]
        assert response.data["user"]["email"] == customer_a.email
        assert response.data["user"]["memberships"]

    def test_the_password_is_never_returned(self, api, customer_a):
        response = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": PASSWORD},
            format="json",
        )
        assert "password" not in str(response.data)

    def test_a_wrong_password_and_an_unknown_email_give_the_same_message(
        self, api, customer_a
    ):
        """
        Distinguishable messages turn the login endpoint into an account-enumeration oracle.
        """
        wrong_password = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": "definitely-not-it"},
            format="json",
        )
        unknown_email = api.post(
            "/api/v1/auth/login/",
            {"email": "nobody@nowhere.test", "password": PASSWORD},
            format="json",
        )
        assert wrong_password.status_code == unknown_email.status_code == 400
        assert (
            wrong_password.data["error"]["message"] == unknown_email.data["error"]["message"]
        )

    def test_a_deactivated_account_cannot_sign_in(self, api, customer_a):
        """
        The refusal is the same generic message as a wrong password. Saying "this account is
        deactivated" would confirm the address exists, so the distinction is recorded in the
        audit trail instead of being returned to the caller.
        """
        customer_a.is_active = False
        customer_a.save(update_fields=["is_active"])
        response = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": PASSWORD},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["message"] == "Incorrect email address or password."

        entry = AuditLog.objects.filter(action="user.login_failed").latest("created_at")
        assert entry.metadata["reason"] == "account is deactivated"

    def test_the_audit_trail_distinguishes_why_a_login_failed(self, api, customer_a):
        api.post(
            "/api/v1/auth/login/",
            {"email": "nobody@nowhere.test", "password": PASSWORD},
            format="json",
        )
        assert AuditLog.objects.filter(
            action="user.login_failed", metadata__reason="no such account"
        ).exists()

        api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": "wrong"},
            format="json",
        )
        assert AuditLog.objects.filter(
            action="user.login_failed", metadata__reason="incorrect password"
        ).exists()

    def test_failed_logins_are_audited(self, api, customer_a):
        api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": "wrong"},
            format="json",
        )
        assert AuditLog.objects.filter(action="user.login_failed").exists()

    def test_the_audit_entry_does_not_contain_the_password(self, api, customer_a):
        api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": "a-very-distinctive-password"},
            format="json",
        )
        entry = AuditLog.objects.filter(action="user.login_failed").latest("created_at")
        assert "a-very-distinctive-password" not in str(entry.metadata)
        assert "a-very-distinctive-password" not in entry.summary

    def test_protected_endpoints_reject_anonymous_requests(self, api):
        for path in ("/api/v1/tickets/", "/api/v1/auth/me/", "/api/v1/analytics/dashboard/"):
            assert api.get(path).status_code == 401, path

    def test_public_endpoints_do_not_require_authentication(self, api):
        for path in (
            "/api/v1/system/status/",
            "/api/v1/knowledge/product/",
            "/api/v1/knowledge/explainer/",
            "/api/v1/knowledge/architecture/",
            "/api/v1/lakehouse-demo/dataset/",
            "/api/v1/lakehouse-demo/sample-queries/",
            "/api/v1/architecture/reference/",
            "/api/v1/fit-assessments/rubric/",
            "/api/v1/auth/demo-accounts/",
        ):
            assert api.get(path).status_code == 200, path

    def test_a_refresh_token_can_be_exchanged(self, api, customer_a):
        login = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": PASSWORD},
            format="json",
        )
        response = api.post(
            "/api/v1/auth/refresh/", {"refresh": login.data["refresh"]}, format="json"
        )
        assert response.status_code == 200
        assert response.data["access"]

    def test_logout_blacklists_the_refresh_token(self, api, auth_client, customer_a):
        login = api.post(
            "/api/v1/auth/login/",
            {"email": customer_a.email, "password": PASSWORD},
            format="json",
        )
        refresh = login.data["refresh"]
        client = auth_client(customer_a)
        assert client.post(
            "/api/v1/auth/logout/", {"refresh": refresh}, format="json"
        ).status_code == 204
        # The blacklisted token can no longer be exchanged.
        assert api.post(
            "/api/v1/auth/refresh/", {"refresh": refresh}, format="json"
        ).status_code == 401

    def test_me_reflects_the_authenticated_user(self, auth_client, customer_a):
        response = auth_client(customer_a).get("/api/v1/auth/me/")
        assert response.status_code == 200
        assert response.data["email"] == customer_a.email
        assert response.data["is_iomete_staff"] is False

    def test_a_user_cannot_change_their_own_role_through_the_profile_endpoint(
        self, auth_client, customer_a
    ):
        response = auth_client(customer_a).patch(
            "/api/v1/auth/me/",
            {"full_name": "Renamed", "system_role": SystemRole.PLATFORM_ADMIN},
            format="json",
        )
        assert response.status_code == 200
        customer_a.refresh_from_db()
        assert customer_a.full_name == "Renamed"
        assert customer_a.system_role == SystemRole.CUSTOMER


class TestDemoAccountDisclosure:
    def test_demo_accounts_are_only_the_synthetic_ones(self, api, customer_a):
        """A real account must never appear in the published credential list."""
        customer_a.is_synthetic = False
        customer_a.save(update_fields=["is_synthetic"])
        response = api.get("/api/v1/auth/demo-accounts/")
        assert response.status_code == 200
        emails = {account["email"] for account in response.data["accounts"]}
        assert customer_a.email not in emails

    def test_a_synthetic_account_is_published_with_its_role(self, api, customer_a):
        customer_a.is_synthetic = True
        customer_a.save(update_fields=["is_synthetic"])
        response = api.get("/api/v1/auth/demo-accounts/")
        account = next(
            item for item in response.data["accounts"] if item["email"] == customer_a.email
        )
        assert account["system_role"] == SystemRole.CUSTOMER
        assert account["description"]

    def test_nothing_is_published_when_demo_mode_is_off(self, api, settings, customer_a):
        customer_a.is_synthetic = True
        customer_a.save(update_fields=["is_synthetic"])
        settings.COMPASS_DEMO_MODE = False
        response = api.get("/api/v1/auth/demo-accounts/")
        assert response.data["demo_mode"] is False
        assert response.data["accounts"] == []


class TestErrorEnvelope:
    def test_a_validation_error_uses_the_envelope(self, auth_client, customer_a):
        response = auth_client(customer_a).post(
            "/api/v1/tickets/", {"title": "too short"}, format="json"
        )
        assert response.status_code == 400
        assert set(response.data["error"]) == {"code", "message", "details"}
        assert response.data["error"]["code"]
        assert response.data["error"]["message"]

    def test_a_not_found_uses_the_envelope(self, auth_client, customer_a):
        response = auth_client(customer_a).get(
            "/api/v1/tickets/00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404
        assert response.data["error"]["code"] == "not_found"

    def test_a_permission_denial_uses_the_envelope(self, auth_client, customer_a):
        response = auth_client(customer_a).get("/api/v1/fde/inbox/")
        assert response.status_code == 403
        assert response.data["error"]["code"] == "permission_denied"
        assert response.data["error"]["message"]

    def test_an_unauthenticated_request_uses_the_envelope(self, api):
        response = api.get("/api/v1/tickets/")
        assert response.status_code == 401
        assert response.data["error"]["code"] in {"not_authenticated", "authentication_failed"}

    def test_a_domain_error_carries_its_stable_code(
        self, auth_client, customer_a, make_ticket, org_a
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{ticket.id}/escalate/", {"reason": ""}, format="json"
        )
        assert response.status_code == 400
        # The frontend switches on `code`, so it must be a slug and not prose.
        assert response.data["error"]["code"].replace("_", "").isalnum()

    def test_an_error_message_is_a_single_readable_sentence(
        self, auth_client, customer_a
    ):
        response = auth_client(customer_a).post(
            "/api/v1/tickets/", {"title": "x"}, format="json"
        )
        message = response.data["error"]["message"]
        assert isinstance(message, str)
        assert len(message) > 10


class TestPagination:
    def test_list_responses_are_paginated_with_a_stable_shape(
        self, auth_client, customer_a, org_a, make_ticket
    ):
        for index in range(3):
            make_ticket(organization=org_a, reporter=customer_a, title=f"Incident {index} here")
        response = auth_client(customer_a).get("/api/v1/tickets/")
        assert response.status_code == 200
        for key in ("count", "page", "page_size", "num_pages", "next", "previous", "results"):
            assert key in response.data, key
        assert response.data["count"] == 3

    def test_the_page_size_is_capped(self, auth_client, customer_a):
        response = auth_client(customer_a).get("/api/v1/tickets/?page_size=10000")
        assert response.status_code == 200
        assert response.data["page_size"] <= 100

    def test_paging_works(self, auth_client, customer_a, org_a, make_ticket):
        for index in range(5):
            make_ticket(organization=org_a, reporter=customer_a, title=f"Incident {index} here")
        first = auth_client(customer_a).get("/api/v1/tickets/?page_size=2")
        assert len(first.data["results"]) == 2
        assert first.data["next"]
        second = auth_client(customer_a).get("/api/v1/tickets/?page_size=2&page=2")
        assert len(second.data["results"]) == 2
        assert {row["id"] for row in first.data["results"]} & {
            row["id"] for row in second.data["results"]
        } == set()


class TestAuditTrail:
    def test_a_ticket_creation_is_audited_with_its_actor(
        self, auth_client, customer_a, org_a
    ):
        auth_client(customer_a).post(
            "/api/v1/tickets/",
            {
                "title": "Executors keep restarting during the nightly job",
                "description": (
                    "The nightly job fails partway through and executors are terminated."
                ),
                "component": "spark_compute",
            },
            format="json",
        )
        entry = AuditLog.objects.filter(action="ticket.created").latest("created_at")
        assert entry.actor_id == customer_a.id
        assert entry.actor_label == customer_a.email
        assert entry.organization_id == org_a.id
        assert entry.request_id, "The request correlation id should be recorded."

    def test_the_actor_label_survives_user_deletion(
        self, make_ticket, org_a, customer_a
    ):
        """
        `actor` is SET_NULL, so without the denormalised label the trail would lose who did
        what the moment an account is removed.
        """
        make_ticket(organization=org_a, reporter=customer_a)
        email = customer_a.email
        entry = AuditLog.objects.filter(action="ticket.created").latest("created_at")
        customer_a.delete()
        entry.refresh_from_db()
        assert entry.actor_id is None
        assert entry.actor_label == email

    def test_metadata_redacts_secret_looking_keys(self):
        from common.audit import record_audit

        entry = record_audit(
            action="integration.configured",
            summary="Test",
            metadata={"api_token": "super-secret", "provider": "jira"},
        )
        assert entry.metadata["api_token"] == "[REDACTED]"
        assert entry.metadata["provider"] == "jira"

    def test_an_unknown_action_is_rejected(self):
        from common.audit import record_audit

        with pytest.raises(ValueError) as excinfo:
            record_audit(action="something.invented", summary="Test")
        assert "deliberately" in str(excinfo.value)

    def test_customers_see_only_their_own_organization_in_the_audit_view(
        self, auth_client, customer_a_admin, customer_b, org_b, make_ticket, org_a
    ):
        make_ticket(organization=org_a, reporter=customer_a_admin)
        make_ticket(organization=org_b, reporter=customer_b)

        response = auth_client(customer_a_admin).get("/api/v1/auth/audit/")
        assert response.status_code == 200
        organizations = {row["organization"] for row in response.data["results"]}
        assert str(org_b.id) not in {str(item) for item in organizations if item}

    def test_a_non_admin_customer_sees_only_their_own_actions(
        self, auth_client, customer_a, customer_a_viewer, org_a, make_ticket
    ):
        make_ticket(organization=org_a, reporter=customer_a)
        response = auth_client(customer_a_viewer).get("/api/v1/auth/audit/")
        assert response.status_code == 200
        actors = {row["actor"] for row in response.data["results"]}
        assert str(customer_a.id) not in {str(item) for item in actors if item}


class TestUserAdministration:
    def test_only_a_platform_admin_can_manage_users(
        self, auth_client, fde, customer_a_admin, platform_admin
    ):
        for user in (fde, customer_a_admin):
            assert auth_client(user).get("/api/v1/auth/users/").status_code == 403
        assert auth_client(platform_admin).get("/api/v1/auth/users/").status_code == 200

    def test_the_last_platform_admin_cannot_be_demoted(
        self, auth_client, platform_admin
    ):
        response = auth_client(platform_admin).post(
            f"/api/v1/auth/users/{platform_admin.id}/change-role/",
            {"role": SystemRole.CUSTOMER},
            format="json",
        )
        assert response.status_code == 400
        platform_admin.refresh_from_db()
        assert platform_admin.system_role == SystemRole.PLATFORM_ADMIN

    def test_a_user_cannot_deactivate_themselves(self, auth_client, platform_admin):
        response = auth_client(platform_admin).post(
            f"/api/v1/auth/users/{platform_admin.id}/deactivate/", {}, format="json"
        )
        assert response.status_code == 400

    def test_a_role_change_is_audited(self, auth_client, platform_admin, customer_a):
        response = auth_client(platform_admin).post(
            f"/api/v1/auth/users/{customer_a.id}/change-role/",
            {"role": SystemRole.FDE},
            format="json",
        )
        assert response.status_code == 200
        entry = AuditLog.objects.filter(action="user.role_changed").latest("created_at")
        assert entry.metadata["from"] == SystemRole.CUSTOMER
        assert entry.metadata["to"] == SystemRole.FDE

    def test_an_organization_cannot_be_left_without_an_administrator(
        self, auth_client, platform_admin, org_a, customer_a_admin
    ):
        membership = Membership.objects.get(user=customer_a_admin, organization=org_a)
        response = auth_client(platform_admin).post(
            f"/api/v1/auth/memberships/{membership.id}/change-role/",
            {"role": MembershipRole.VIEWER},
            format="json",
        )
        assert response.status_code == 409
        assert "administrator" in response.data["error"]["message"].lower()

    def test_a_customer_admin_can_add_a_colleague_to_their_own_organization(
        self, auth_client, customer_a_admin, org_a
    ):
        colleague = User.objects.create_user(
            email="new@alpha.test", password=PASSWORD, full_name="New Person"
        )
        response = auth_client(customer_a_admin).post(
            "/api/v1/auth/memberships/",
            {
                "user": str(colleague.id),
                "organization": str(org_a.id),
                "role": MembershipRole.ENGINEER,
            },
            format="json",
        )
        assert response.status_code == 201

    def test_a_customer_admin_cannot_add_a_member_to_another_organization(
        self, auth_client, customer_a_admin, org_b
    ):
        outsider = User.objects.create_user(
            email="outsider@beta.test", password=PASSWORD, full_name="Outsider"
        )
        response = auth_client(customer_a_admin).post(
            "/api/v1/auth/memberships/",
            {
                "user": str(outsider.id),
                "organization": str(org_b.id),
                "role": MembershipRole.ADMIN,
            },
            format="json",
        )
        assert response.status_code == 403


class TestSystemStatusAndHealth:
    def test_health_is_a_liveness_probe_that_leaks_nothing(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_the_status_endpoint_is_public_and_complete(self, api):
        response = api.get("/api/v1/system/status/")
        assert response.status_code == 200
        for key in ("demo_mode", "ai", "retrieval", "integrations", "knowledge_base"):
            assert key in response.data, key

    def test_the_request_id_header_is_echoed(self, api):
        response = api.get("/api/v1/system/status/", HTTP_X_REQUEST_ID="abc-123")
        assert response["X-Request-ID"] == "abc-123"

    def test_a_request_id_is_generated_when_absent(self, api):
        response = api.get("/api/v1/system/status/")
        assert response["X-Request-ID"]


class TestApiDocumentation:
    def test_the_openapi_schema_generates(self, api):
        response = api.get("/api/schema/")
        assert response.status_code == 200

    def test_the_swagger_ui_is_served(self, api):
        response = api.get("/api/docs/")
        assert response.status_code == 200

    def test_every_route_lives_under_the_version_prefix(self):
        """
        `/api/v1/` with no exceptions. An unversioned endpoint becomes impossible to change
        later without breaking a client.
        """
        from django.urls import get_resolver

        allowed_prefixes = ("api/v1/", "api/schema", "api/docs", "admin/", "healthz", "media/")
        unversioned = []

        def walk(patterns, prefix=""):
            for pattern in patterns:
                route = prefix + str(getattr(pattern, "pattern", ""))
                if hasattr(pattern, "url_patterns"):
                    walk(pattern.url_patterns, route)
                elif not route.startswith(allowed_prefixes):
                    unversioned.append(route)

        walk(get_resolver().url_patterns)
        assert not unversioned, f"Unversioned routes: {unversioned}"


class TestCrypto:
    def test_an_encrypted_field_round_trips(self):
        from common.crypto import decrypt_text, encrypt_text

        secret = "a-token-worth-protecting"
        encrypted = encrypt_text(secret)
        assert encrypted.startswith("enc:v1:")
        assert secret not in encrypted
        assert decrypt_text(encrypted) == secret

    def test_an_empty_value_is_handled(self):
        from common.crypto import decrypt_text, encrypt_text

        assert encrypt_text("") == ""
        assert decrypt_text("") == ""

    def test_decryption_with_a_rotated_key_degrades_rather_than_crashing(self, settings):
        """
        A wrong key must drop the integration to demo mode, not 500 the request — and the
        integration will then correctly report that it is not connected.
        """
        from cryptography.fernet import Fernet

        from common import crypto

        encrypted = crypto.encrypt_text("secret")
        crypto._fernet.cache_clear()
        settings.COMPASS_ENCRYPTION_KEY = Fernet.generate_key().decode()
        try:
            assert crypto.decrypt_text(encrypted) == ""
        finally:
            crypto._fernet.cache_clear()


class TestLogRedaction:
    def test_the_logging_filter_redacts_secrets(self):
        import logging

        from common.logging_filters import RedactingFilter

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Connecting with api_key=super-secret-value and AKIAIOSFODNN7EXAMPLE",
            args=(),
            exc_info=None,
        )
        RedactingFilter().filter(record)
        assert "super-secret-value" not in record.msg
        assert "AKIAIOSFODNN7EXAMPLE" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_the_filter_redacts_arguments_too(self):
        import logging

        from common.logging_filters import RedactingFilter

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Token was %s",
            args=("Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",),
            exc_info=None,
        )
        RedactingFilter().filter(record)
        assert "eyJhbGciOiJIUzI1NiJ9" not in str(record.args)

    def test_the_filter_never_breaks_logging(self):
        import logging

        from common.logging_filters import RedactingFilter

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg=object(), args=(), exc_info=None,  # a non-string msg
        )
        assert RedactingFilter().filter(record) is True


class TestVersioningHelpers:
    @pytest.mark.parametrize(
        "version,spec,expected",
        [
            ("3.19.1", ">=3.0,<4.0", True),
            ("2.9.0", ">=3.0,<4.0", False),
            ("4.0.0", ">=3.0,<4.0", False),
            ("3.19.1", "==3.19.1", True),
            ("3.19.2", "==3.19.1", False),
            ("3.19.1", "*", True),
            ("3.19.1", "", True),
            ("", ">=3.0", None),
            (None, ">=3.0", None),
            ("not-a-version", ">=3.0", None),
            ("3.19.1", "garbage", None),
        ],
    )
    def test_version_matching(self, version, spec, expected):
        from common.versioning import version_matches

        assert version_matches(version, spec) is expected

    @pytest.mark.parametrize(
        "environment,applicable,expected",
        [
            ("production", ["production", "staging"], True),
            ("development", ["production"], False),
            ("production", [], True),
            ("", ["production"], None),
            (None, ["production"], None),
        ],
    )
    def test_environment_matching(self, environment, applicable, expected):
        from common.versioning import environment_matches

        assert environment_matches(environment, applicable) is expected

    def test_unknown_applicability_is_not_recommendable(self):
        """Unknown must mean "do not recommend", never "probably fine"."""
        from common.versioning import describe_gate

        recommendable, reason = describe_gate(None, True)
        assert recommendable is False
        assert "unknown" in reason.lower()

    def test_a_clean_gate_explains_itself(self):
        from common.versioning import describe_gate

        recommendable, reason = describe_gate(True, True)
        assert recommendable is True
        assert "applicable" in reason.lower()
        assert "match" in reason.lower()

"""
Acceptance test 1: a customer cannot access another customer's private data.

This is the highest-severity defect class in COMPASS, so the coverage is deliberately
broad rather than a single happy-path check. Every reachable surface is exercised: list,
retrieve, update actions, the timeline, internal notes, attachments, similar-ticket
retrieval, executions, analytics and clusters.

The tests assert on *outcomes a user could observe*, not on queryset internals — a view
that bypasses `for_user()` and reintroduces hand-filtering would still have to fail these.
"""

from __future__ import annotations

import pytest

from tickets.models import Ticket, TicketEvent
from tickets.services import intake

pytestmark = [pytest.mark.django_db, pytest.mark.security, pytest.mark.acceptance]


@pytest.fixture
def ticket_a(make_ticket, org_a, customer_a):
    return make_ticket(organization=org_a, reporter=customer_a)


@pytest.fixture
def ticket_b(make_ticket, org_b, customer_b):
    return make_ticket(
        organization=org_b,
        reporter=customer_b,
        title="Beta's private incident with a confidential detail",
        description=(
            "Our proprietary pricing pipeline is failing. This description is commercially "
            "sensitive and must never be visible to another customer."
        ),
    )


class TestTicketReadIsolation:
    def test_list_excludes_other_tenants(self, auth_client, customer_a, ticket_a, ticket_b):
        response = auth_client(customer_a).get("/api/v1/tickets/?page_size=100")
        assert response.status_code == 200
        references = {row["reference"] for row in response.data["results"]}
        assert ticket_a.reference in references
        assert ticket_b.reference not in references

    def test_retrieve_other_tenant_returns_404(self, auth_client, customer_a, ticket_b):
        response = auth_client(customer_a).get(f"/api/v1/tickets/{ticket_b.id}/")
        assert response.status_code == 404

    def test_search_cannot_surface_other_tenants(
        self, auth_client, customer_a, ticket_b
    ):
        # Searching for the other tenant's exact reference must still return nothing.
        response = auth_client(customer_a).get(
            f"/api/v1/tickets/?search={ticket_b.reference}"
        )
        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_organization_filter_cannot_be_used_to_escape_scope(
        self, auth_client, customer_a, org_b, ticket_b
    ):
        """
        Passing another tenant's organization id as a filter must yield nothing.

        A filter applied on top of an already-scoped queryset is safe; a filter applied to
        an unscoped one is a breach. This asserts which one we have.
        """
        response = auth_client(customer_a).get(f"/api/v1/tickets/?organization={org_b.id}")
        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_timeline_of_other_tenant_is_unreachable(
        self, auth_client, customer_a, ticket_b
    ):
        response = auth_client(customer_a).get(f"/api/v1/tickets/{ticket_b.id}/events/")
        assert response.status_code == 404


class TestTicketWriteIsolation:
    def test_cannot_comment_on_other_tenants_ticket(
        self, auth_client, customer_a, ticket_b
    ):
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{ticket_b.id}/comment/",
            {"body": "I should not be able to write here."},
            format="json",
        )
        assert response.status_code == 404
        assert not TicketEvent.objects.filter(
            ticket=ticket_b, body__icontains="should not be able"
        ).exists()

    def test_cannot_change_status_of_other_tenants_ticket(
        self, auth_client, customer_a, ticket_b
    ):
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{ticket_b.id}/status/",
            {"status": "closed"},
            format="json",
        )
        assert response.status_code == 404
        ticket_b.refresh_from_db()
        assert ticket_b.status != "closed"

    def test_cannot_escalate_other_tenants_ticket(self, auth_client, customer_a, ticket_b):
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{ticket_b.id}/escalate/",
            {"reason": "Escalating someone else's ticket."},
            format="json",
        )
        assert response.status_code == 404

    def test_cannot_file_a_ticket_against_another_organization(
        self, auth_client, customer_a, org_b
    ):
        response = auth_client(customer_a).post(
            "/api/v1/tickets/",
            {
                "title": "Filing this against the wrong tenant",
                "description": "This submission names an organization I am not a member of.",
                "organization": str(org_b.id),
                "component": "spark_compute",
            },
            format="json",
        )
        assert response.status_code == 400
        assert not Ticket.objects.filter(
            organization=org_b, title__icontains="wrong tenant"
        ).exists()


class TestInternalNotesAreNeverExposed:
    """
    Internal FDE notes are the field most likely to leak through a hastily added endpoint,
    so they get their own class.
    """

    def test_customer_cannot_see_internal_notes_on_their_own_ticket(
        self, auth_client, customer_a, ticket_a, fde
    ):
        intake.add_comment(
            ticket=ticket_a,
            author=fde,
            body="INTERNAL: this account is in a commercial dispute, handle carefully.",
            is_internal=True,
        )
        response = auth_client(customer_a).get(f"/api/v1/tickets/{ticket_a.id}/")
        assert response.status_code == 200
        serialised = str(response.data)
        assert "commercial dispute" not in serialised

    def test_internal_notes_absent_from_the_events_endpoint(
        self, auth_client, customer_a, ticket_a, fde
    ):
        intake.add_comment(
            ticket=ticket_a, author=fde, body="INTERNAL: escalate to legal.", is_internal=True
        )
        response = auth_client(customer_a).get(f"/api/v1/tickets/{ticket_a.id}/events/")
        assert response.status_code == 200
        assert all(not event["is_internal"] for event in response.data)
        assert "escalate to legal" not in str(response.data)

    def test_fde_does_see_internal_notes(self, auth_client, fde, ticket_a):
        intake.add_comment(
            ticket=ticket_a, author=fde, body="INTERNAL: check the node pool first.", is_internal=True
        )
        response = auth_client(fde).get(f"/api/v1/tickets/{ticket_a.id}/events/")
        assert response.status_code == 200
        assert any(event["is_internal"] for event in response.data)

    def test_customer_cannot_author_an_internal_note(
        self, auth_client, customer_a, ticket_a
    ):
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{ticket_a.id}/comment/",
            {"body": "Pretending this is internal.", "is_internal": True},
            format="json",
        )
        assert response.status_code == 400
        assert not TicketEvent.objects.filter(ticket=ticket_a, is_internal=True).exists()


class TestRetrievalIsolation:
    """
    The subtlest breach: retrieval reaching across tenants.

    A customer's similar-ticket search must only return their own history. Cross-customer
    learning is delivered through approved playbooks, which an FDE has reviewed and
    redacted for exactly that purpose.
    """

    def test_similar_search_never_returns_another_tenants_ticket(
        self, auth_client, customer_a, org_a, org_b, customer_b, make_ticket, fde_lead
    ):
        from tickets.services import lifecycle

        # A resolved ticket in B with an identical error signature — the hardest case,
        # because every retrieval channel would rank it highly if scoping were missing.
        other = make_ticket(
            organization=org_b,
            reporter=customer_b,
            title="Executors keep restarting during the nightly job",
        )
        lifecycle.record_resolution(
            ticket=other,
            user=fde_lead,
            summary="Beta's confidential remediation detail.",
            evidence="Beta's confidential verification detail.",
        )
        lifecycle.verify_resolution(ticket=other, reviewer=fde_lead, quality=5)

        mine = make_ticket(organization=org_a, reporter=customer_a)
        response = auth_client(customer_a).post(
            f"/api/v1/tickets/{mine.id}/similar/", {}, format="json"
        )
        assert response.status_code == 200
        serialised = str(response.data)
        assert other.reference not in serialised
        assert "confidential" not in serialised

    def test_fde_retrieval_does_span_tenants(
        self, auth_client, fde_lead, org_a, org_b, customer_a, customer_b, make_ticket
    ):
        """
        The counterpart assertion. An FDE *should* see cross-tenant history — that is the
        entire purpose of the command center — so a test that only checked "nobody sees
        anything" would pass on a broken-but-useless implementation.
        """
        from tickets.services import lifecycle

        other = make_ticket(organization=org_b, reporter=customer_b)
        lifecycle.record_resolution(
            ticket=other, user=fde_lead, summary="Raised executor memory.", evidence="Job completes."
        )
        lifecycle.verify_resolution(ticket=other, reviewer=fde_lead, quality=4)

        mine = make_ticket(organization=org_a, reporter=customer_a)
        response = auth_client(fde_lead).post(
            f"/api/v1/tickets/{mine.id}/similar/", {}, format="json"
        )
        assert response.status_code == 200
        assert other.reference in str(response.data)

    def test_retrieval_run_records_that_scoping_was_applied(
        self, customer_a, org_a, make_ticket
    ):
        """The audit trail must show tenant scoping ran. An unscoped run is auditable."""
        from aiengine.models import RetrievalRun
        from tickets.services import similar

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        similar.analyse(ticket=ticket, user=customer_a, limit=3)
        run = RetrievalRun.objects.filter(ticket=ticket).latest("created_at")
        assert run.tenant_scope_applied is True


class TestExecutionAndAnalyticsIsolation:
    def test_executions_are_tenant_scoped(
        self, auth_client, customer_a, customer_b, org_b, make_ticket, approved_playbook
    ):
        from playbooks.services import execution as execution_service

        ticket = make_ticket(organization=org_b, reporter=customer_b)
        execution = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_b
        )

        response = auth_client(customer_a).get("/api/v1/playbook-executions/")
        assert response.status_code == 200
        assert str(execution.id) not in str(response.data)

        detail = auth_client(customer_a).get(f"/api/v1/playbook-executions/{execution.id}/")
        assert detail.status_code == 404

    def test_analytics_counts_only_own_organization(
        self, auth_client, customer_a, ticket_a, ticket_b
    ):
        response = auth_client(customer_a).get("/api/v1/analytics/dashboard/?window=all")
        assert response.status_code == 200
        metrics = {metric["key"]: metric for metric in response.data["metrics"]}
        # Two tickets exist in total; only one belongs to this customer.
        assert metrics["open_tickets"]["value"] == 1

    def test_analytics_organization_filter_cannot_target_another_tenant(
        self, auth_client, customer_a, org_b, ticket_b
    ):
        response = auth_client(customer_a).get(
            f"/api/v1/analytics/dashboard/?organization={org_b.id}"
        )
        assert response.status_code == 404

    def test_clusters_are_fde_only(self, auth_client, customer_a, customer_a_admin):
        """
        Clusters span tenants by construction, so no customer role may list them — not even
        an organization administrator.
        """
        for user in (customer_a, customer_a_admin):
            response = auth_client(user).get("/api/v1/fde/clusters/")
            assert response.status_code == 403, user.email

    def test_fde_inbox_is_fde_only(self, auth_client, customer_a_admin):
        response = auth_client(customer_a_admin).get("/api/v1/fde/inbox/")
        assert response.status_code == 403


class TestAttachmentIsolation:
    def test_cannot_download_another_tenants_attachment(
        self, auth_client, customer_a, customer_b, ticket_b
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from tickets.services import attachments

        attachment = attachments.upload(
            ticket=ticket_b,
            uploaded_file=SimpleUploadedFile(
                "diag.log", b"Beta confidential log line\n", content_type="text/plain"
            ),
            user=customer_b,
        )
        response = auth_client(customer_a).get(
            f"/api/v1/tickets/{ticket_b.id}/attachments/{attachment.id}/download/"
        )
        assert response.status_code == 404

    def test_internal_attachment_not_downloadable_by_customer(
        self, auth_client, customer_a, ticket_a, fde
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from tickets.services import attachments

        attachment = attachments.upload(
            ticket=ticket_a,
            uploaded_file=SimpleUploadedFile(
                "internal.log", b"internal only\n", content_type="text/plain"
            ),
            user=fde,
            is_internal=True,
        )
        response = auth_client(customer_a).get(
            f"/api/v1/tickets/{ticket_a.id}/attachments/{attachment.id}/download/"
        )
        assert response.status_code == 404

        # And the FDE can.
        allowed = auth_client(fde).get(
            f"/api/v1/tickets/{ticket_a.id}/attachments/{attachment.id}/download/"
        )
        assert allowed.status_code == 200


class TestOrganizationDataIsolation:
    def test_customer_cannot_list_other_organizations(
        self, auth_client, customer_a, org_a, org_b
    ):
        response = auth_client(customer_a).get("/api/v1/organizations/")
        assert response.status_code == 200
        slugs = {row["slug"] for row in response.data["results"]}
        assert slugs == {org_a.slug}

    def test_internal_vendor_fields_withheld_from_customers(
        self, auth_client, customer_a, org_a, fde
    ):
        org_a.notes = "Internal: this account is at renewal risk."
        org_a.assigned_fde = fde
        org_a.save()
        response = auth_client(customer_a).get(f"/api/v1/organizations/{org_a.id}/")
        assert response.status_code == 200
        assert "renewal risk" not in str(response.data)
        assert "assigned_fde" not in response.data

    def test_customer_cannot_enumerate_the_fde_directory(self, auth_client, customer_a_admin):
        response = auth_client(customer_a_admin).get("/api/v1/auth/fdes/")
        assert response.status_code == 403

    def test_prospect_profiles_are_staff_only(self, auth_client, customer_a_admin):
        response = auth_client(customer_a_admin).get("/api/v1/prospects/")
        assert response.status_code == 403

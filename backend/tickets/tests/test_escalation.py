"""
Escalation — acceptance test 7.

An unresolved issue must produce an escalation that carries the diagnostic summary, so the
FDE starts where the customer stopped. That is the mechanism by which COMPASS saves FDE
hours, so "an escalation happened" is not enough — the evidence has to travel with it.
"""

from __future__ import annotations

import pytest

from common.exceptions import ConflictError, DomainValidationError
from playbooks.models import ExecutionStatus
from playbooks.services import execution as execution_service
from tickets.models import TicketEventType, TicketStatus
from tickets.services import lifecycle

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


class TestEscalationCarriesTheInvestigation:
    def test_escalation_after_a_replay_includes_what_was_checked(
        self, make_ticket, org_a, customer_a, approved_playbook
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        execution = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_a
        )
        execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="no",
            observation="The pod reports Evicted from disk pressure, not OOMKilled.",
        )
        execution.refresh_from_db()

        result = lifecycle.escalate(
            ticket=ticket,
            user=customer_a,
            reason=(
                "Worked through the memory playbook. The pod shows Evicted rather than "
                "OOMKilled, so the diagnosis does not hold. We are still failing nightly."
            ),
            execution=execution,
        )

        assert result.ticket.status == TicketStatus.ESCALATED
        assert result.ticket.escalated_at is not None

        package = result.summary["diagnostic_package"]
        assert package["playbook"]["title"]
        assert len(package["steps_completed"]) == 1
        step = package["steps_completed"][0]
        assert step["what_to_inspect"]
        assert "Evicted" in step["observation"]
        assert package["ruled_out"], "What was ruled out is the most useful part."
        assert result.summary["summary"]

    def test_escalating_closes_an_in_progress_execution(
        self, make_ticket, org_a, customer_a, approved_playbook
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        execution = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_a
        )
        lifecycle.escalate(
            ticket=ticket, user=customer_a, reason="Cannot proceed.", execution=execution
        )
        execution.refresh_from_db()
        assert execution.status == ExecutionStatus.ESCALATED
        assert execution.current_step is None

    def test_escalation_without_a_replay_still_works(
        self, make_ticket, org_a, customer_a
    ):
        """
        Not every escalation follows a workflow. A customer who files and immediately
        escalates must still get a coherent summary rather than an error.
        """
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        result = lifecycle.escalate(
            ticket=ticket,
            user=customer_a,
            reason="This is a total outage and we need help immediately.",
        )
        assert result.ticket.status == TicketStatus.ESCALATED
        assert result.summary["summary"]
        assert result.summary["diagnostic_package"] == {}

    def test_escalation_requires_a_reason(self, make_ticket, org_a, customer_a):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            lifecycle.escalate(ticket=ticket, user=customer_a, reason="   ")
        assert "what you have tried" in str(excinfo.value.detail).lower()

    def test_a_closed_ticket_cannot_be_escalated(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.record_resolution(
            ticket=ticket, user=fde_lead, summary="Fixed.", evidence="Verified."
        )
        lifecycle.change_status(
            ticket=ticket, user=fde_lead, new_status=TicketStatus.CLOSED
        )
        ticket.refresh_from_db()
        with pytest.raises(ConflictError):
            lifecycle.escalate(ticket=ticket, user=customer_a, reason="Still broken.")

    def test_escalation_reason_is_redacted(self, make_ticket, org_a, customer_a):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.escalate(
            ticket=ticket,
            user=customer_a,
            reason=(
                "We tried with AWS_SECRET_ACCESS_KEY="
                "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY and it still fails."
            ),
        )
        ticket.refresh_from_db()
        assert "wJalrXUtnFEMI" not in ticket.escalation_reason
        assert "REDACTED" in ticket.escalation_reason

    def test_escalation_produces_a_timeline_entry_and_audit_record(
        self, make_ticket, org_a, customer_a
    ):
        from accounts.models import AuditLog

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.escalate(
            ticket=ticket, user=customer_a, reason="Tried everything in the runbook."
        )
        assert ticket.events.filter(event_type=TicketEventType.ESCALATED).exists()
        assert AuditLog.objects.filter(
            action="ticket.escalated", target_id=str(ticket.id)
        ).exists()

    def test_the_api_returns_the_escalation_summary(
        self, auth_client, make_ticket, org_a, customer_a, approved_playbook
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        client = auth_client(customer_a)

        start = client.post(
            "/api/v1/playbook-executions/",
            {"ticket": str(ticket.id), "playbook": str(approved_playbook.id)},
            format="json",
        )
        assert start.status_code == 201
        execution_id = start.data["id"]
        client.post(
            f"/api/v1/playbook-executions/{execution_id}/advance/",
            {"response_value": "no", "observation": "Evicted, not OOMKilled."},
            format="json",
        )

        response = client.post(
            f"/api/v1/tickets/{ticket.id}/escalate/",
            {
                "reason": "The memory diagnosis does not fit; the pod was evicted.",
                "execution_id": execution_id,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["ticket"]["status"] == "escalated"
        summary = response.data["escalation_summary"]
        assert summary["summary"]
        assert summary["diagnostic_package"]["steps_completed"]
        # The provider is disclosed so nobody mistakes composed text for model output.
        assert response.data["ai"]["provider"] == "demo"
        assert response.data["ai"]["is_live_model"] is False
        assert response.data["ai"]["notice"]

    def test_escalated_tickets_appear_in_the_fde_inbox(
        self, auth_client, make_ticket, org_a, customer_a, fde
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.escalate(ticket=ticket, user=customer_a, reason="Need help.")

        response = auth_client(fde).get("/api/v1/fde/inbox/")
        assert response.status_code == 200
        assert response.data["counts"]["escalated"] >= 1
        references = {row["reference"] for row in response.data["buckets"]["escalated"]}
        assert ticket.reference in references


class TestResolutionVersusVerification:
    """
    The distinction that protects future customers: a customer can resolve, only an FDE can
    verify, and only verified resolutions become retrieval precedent.
    """

    def test_a_customer_cannot_verify_a_resolution(
        self, make_ticket, org_a, customer_a, customer_a_admin
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.record_resolution(
            ticket=ticket,
            user=customer_a,
            summary="We raised the memory ourselves.",
            evidence="The job completes now.",
        )
        for actor in (customer_a, customer_a_admin):
            with pytest.raises(DomainValidationError) as excinfo:
                lifecycle.verify_resolution(ticket=ticket, reviewer=actor, quality=5)
            assert "only an fde" in str(excinfo.value.detail).lower()

        ticket.refresh_from_db()
        assert ticket.resolution_verified is False

    def test_the_verify_endpoint_is_staff_only(
        self, auth_client, make_ticket, org_a, customer_a, customer_a_admin, fde_lead
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.record_resolution(
            ticket=ticket, user=customer_a, summary="Fixed.", evidence="Confirmed."
        )
        refused = auth_client(customer_a_admin).post(
            f"/api/v1/tickets/{ticket.id}/verify/", {"quality": 5}, format="json"
        )
        assert refused.status_code == 403

        allowed = auth_client(fde_lead).post(
            f"/api/v1/tickets/{ticket.id}/verify/", {"quality": 4}, format="json"
        )
        assert allowed.status_code == 200
        ticket.refresh_from_db()
        assert ticket.resolution_verified is True
        assert ticket.resolution_quality == 4

    def test_a_resolution_requires_evidence(self, make_ticket, org_a, customer_a):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            lifecycle.record_resolution(
                ticket=ticket, user=customer_a, summary="Fixed it.", evidence=""
            )
        assert "observed" in str(excinfo.value.detail).lower()

    def test_only_staff_can_record_investigation_time(
        self, make_ticket, org_a, customer_a
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError):
            lifecycle.record_resolution(
                ticket=ticket,
                user=customer_a,
                summary="Fixed.",
                evidence="Confirmed.",
                fde_investigation_minutes=120,
            )

    def test_reopening_clears_verification(self, make_ticket, org_a, customer_a, fde_lead):
        """
        A reopened ticket's resolution no longer holds, so it must stop being precedent.
        """
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.record_resolution(
            ticket=ticket, user=fde_lead, summary="Fixed.", evidence="Confirmed."
        )
        lifecycle.verify_resolution(ticket=ticket, reviewer=fde_lead, quality=5)
        ticket.refresh_from_db()
        assert ticket.resolution_verified is True

        lifecycle.change_status(
            ticket=ticket, user=customer_a, new_status=TicketStatus.IN_PROGRESS
        )
        ticket.refresh_from_db()
        assert ticket.resolution_verified is False
        assert ticket.resolved_at is None
        assert ticket.self_service_resolved is False

    def test_an_unverified_resolution_scores_lower_than_a_verified_one(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        from tickets.services import similar

        verified = make_ticket(
            organization=org_a, reporter=customer_a, title="First OOM incident"
        )
        lifecycle.record_resolution(
            ticket=verified, user=fde_lead, summary="Raised memory to 12g.",
            evidence="Job completes.",
        )
        lifecycle.verify_resolution(ticket=verified, reviewer=fde_lead, quality=5)

        unverified = make_ticket(
            organization=org_a, reporter=customer_a, title="Second OOM incident"
        )
        lifecycle.record_resolution(
            ticket=unverified, user=customer_a, summary="We think raising memory helped.",
            evidence="It seems fine now.",
        )

        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=5)
        scores = {match.ticket.reference: match.score for match in analysis.ticket_matches}
        assert verified.reference in scores and unverified.reference in scores
        assert (
            scores[verified.reference].resolution_confidence
            > scores[unverified.reference].resolution_confidence
        )
        # And the unverified one must say so in its evidence.
        kinds = {item.kind for item in scores[unverified.reference].evidence}
        assert "unverified_resolution" in kinds


class TestStatusTransitions:
    def test_a_customer_cannot_assign_an_fde(self, make_ticket, org_a, customer_a_admin):
        ticket = make_ticket(organization=org_a, reporter=customer_a_admin)
        with pytest.raises(DomainValidationError) as excinfo:
            lifecycle.assign(ticket=ticket, user=customer_a_admin, assignee=customer_a_admin)
        assert "only iomete staff" in str(excinfo.value.detail).lower()

    def test_a_ticket_can_only_be_assigned_to_staff(
        self, make_ticket, org_a, customer_a, fde
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            lifecycle.assign(ticket=ticket, user=fde, assignee=customer_a)
        assert "fde or platform administrator" in str(excinfo.value.detail).lower()

    def test_a_customer_cannot_jump_a_closed_ticket_back_open(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.record_resolution(
            ticket=ticket, user=fde_lead, summary="Fixed.", evidence="Confirmed."
        )
        lifecycle.change_status(ticket=ticket, user=fde_lead, new_status=TicketStatus.CLOSED)
        ticket.refresh_from_db()
        with pytest.raises(DomainValidationError):
            lifecycle.change_status(
                ticket=ticket, user=customer_a, new_status=TicketStatus.IN_PROGRESS
            )

    def test_staff_may_move_a_ticket_anywhere(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        lifecycle.change_status(
            ticket=ticket, user=fde_lead, new_status=TicketStatus.AWAITING_CUSTOMER
        )
        ticket.refresh_from_db()
        assert ticket.status == TicketStatus.AWAITING_CUSTOMER

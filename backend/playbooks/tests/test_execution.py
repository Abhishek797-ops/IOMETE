"""
Resolution Replay — acceptance tests 6 and 14.

Test 6: a customer can complete a guided troubleshooting workflow, including a branch.
Test 14: a step that can change a running system cannot be completed without authorization.

The approval gate is the single most important rule in this module, so it is tested from
both the service layer and the API, for every role.
"""

from __future__ import annotations

import pytest

from common.exceptions import ApprovalRequiredError, ConflictError, DomainValidationError
from playbooks.models import ExecutionStatus, PlaybookStepResponse
from playbooks.services import execution as execution_service
from tickets.models import TicketEventType, TicketStatus

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


@pytest.fixture
def execution(make_ticket, org_a, customer_a, approved_playbook):
    ticket = make_ticket(organization=org_a, reporter=customer_a)
    return execution_service.start(
        ticket=ticket, playbook=approved_playbook, user=customer_a
    )


class TestWorkflowCompletion:
    """Acceptance test 6."""

    def test_a_customer_can_complete_the_happy_path_end_to_end(
        self, execution, customer_a, customer_a_admin
    ):
        assert execution.status == ExecutionStatus.IN_PROGRESS
        assert execution.current_step.key == "confirm"

        # Step 1: a read-only diagnostic, which any customer role may complete.
        first = execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="yes",
            observation="Last State: Terminated, Reason: OOMKilled, Exit Code: 137.",
        )
        assert first.execution.current_step.key == "apply"
        assert first.terminal is None

        # Step 2: a change step, which needs an approver.
        second = execution_service.advance(
            execution=first.execution,
            user=customer_a_admin,
            response_value="yes",
            observation="Raised executor memory to 12g; cluster restarted in 95 seconds.",
            approval_note="Approved in the Tuesday maintenance window.",
        )
        assert second.execution.current_step.key == "verify"
        assert second.response.approval_granted_by_id == customer_a_admin.id
        assert second.response.approval_granted_at is not None

        # Step 3: verification, which reaches a terminal outcome.
        third = execution_service.advance(
            execution=second.execution,
            user=customer_a,
            response_value="yes",
            observation="The job completed in 38 minutes with no OOMKilled events.",
        )
        assert third.terminal == execution_service.TERMINAL_RESOLVED
        assert third.requires_outcome_capture is True
        # Reaching a terminal branch does not itself close the run.
        assert third.execution.status == ExecutionStatus.IN_PROGRESS

        completed = execution_service.complete(
            execution=third.execution,
            user=customer_a,
            outcome="resolved",
            outcome_summary="Raised executor memory per the playbook.",
            outcome_evidence="The job completed and OOMKilled no longer appears.",
        )
        assert completed.status == ExecutionStatus.RESOLVED
        assert completed.responses.count() == 3
        assert completed.path == ["confirm", "apply", "verify"]

        completed.ticket.refresh_from_db()
        assert completed.ticket.status == TicketStatus.RESOLVED
        assert completed.ticket.self_service_resolved is True

    def test_a_branch_can_lead_to_escalation_instead(self, execution, customer_a):
        """
        The branching case. Answering "no" at the first diagnostic must route to escalation
        rather than continuing to the change step — which is what makes this a decision
        graph rather than a checklist.
        """
        result = execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="no",
            observation="The pod shows Evicted, not OOMKilled.",
        )
        assert result.terminal == execution_service.TERMINAL_ESCALATE
        assert result.execution.current_step is None
        # The change step was never reached.
        assert "apply" not in result.execution.path

    def test_the_path_records_only_the_steps_actually_traversed(
        self, execution, customer_a
    ):
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        execution.refresh_from_db()
        assert execution.path == ["confirm"]
        assert execution.responses.count() == 1

    def test_observations_are_recorded_against_each_step(self, execution, customer_a):
        execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="yes",
            observation="Reason: OOMKilled with exit code 137.",
        )
        response = PlaybookStepResponse.objects.get(execution=execution, sequence=1)
        assert "OOMKilled" in response.observation
        assert response.matched_expectation is True
        assert response.completed_by_id == customer_a.id

    def test_each_step_produces_a_ticket_timeline_entry(self, execution, customer_a):
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        events = execution.ticket.events.filter(event_type=TicketEventType.PLAYBOOK_STEP)
        assert events.count() == 1
        assert "Evicted" in events.first().body

    def test_starting_twice_resumes_rather_than_duplicating(
        self, make_ticket, org_a, customer_a, approved_playbook
    ):
        """A page refresh must not lose collected observations or fork the session."""
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        first = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_a
        )
        execution_service.advance(
            execution=first, user=customer_a, response_value="yes", observation="OOMKilled."
        )
        second = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_a
        )
        assert second.id == first.id
        assert second.responses.count() == 1

    def test_a_completed_execution_cannot_be_advanced(self, execution, customer_a):
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        execution.refresh_from_db()
        execution_service.complete(
            execution=execution,
            user=customer_a,
            outcome="not_resolved",
            outcome_summary="Different cause.",
        )
        execution.refresh_from_db()
        with pytest.raises(ConflictError):
            execution_service.advance(
                execution=execution, user=customer_a, response_value="yes"
            )


class TestApprovalGate:
    """
    Acceptance test 14. A change step must not complete without authorization.
    """

    def _reach_change_step(self, execution, user):
        result = execution_service.advance(
            execution=execution, user=user, response_value="yes", observation="OOMKilled."
        )
        assert result.execution.current_step.key == "apply"
        assert result.execution.current_step.requires_approval is True
        return result.execution

    @pytest.mark.parametrize("role_fixture", ["customer_a", "customer_a_viewer"])
    def test_an_unprivileged_customer_cannot_complete_a_change_step(
        self, request, execution, customer_a, role_fixture
    ):
        at_change = self._reach_change_step(execution, customer_a)
        actor = request.getfixturevalue(role_fixture)

        with pytest.raises(ApprovalRequiredError) as excinfo:
            execution_service.advance(
                execution=at_change,
                user=actor,
                response_value="yes",
                observation="Trying to apply the change.",
            )
        message = str(excinfo.value.detail)
        # The refusal must explain itself and state the blast radius.
        assert "approval" in message.lower()
        assert "restarts the compute cluster" in message.lower()

        at_change.refresh_from_db()
        # And nothing was recorded for the step.
        assert at_change.current_step.key == "apply"
        assert at_change.responses.count() == 1

    def test_an_organization_admin_can_approve_their_own_cluster_change(
        self, execution, customer_a, customer_a_admin
    ):
        at_change = self._reach_change_step(execution, customer_a)
        result = execution_service.advance(
            execution=at_change,
            user=customer_a_admin,
            response_value="yes",
            observation="Applied.",
            approval_note="Maintenance window.",
        )
        assert result.response.approval_granted_by_id == customer_a_admin.id
        assert result.response.approval_note

    def test_an_fde_can_approve(self, execution, customer_a, fde):
        at_change = self._reach_change_step(execution, customer_a)
        result = execution_service.advance(
            execution=at_change, user=fde, response_value="yes", observation="Applied."
        )
        assert result.response.approval_granted_by_id == fde.id

    def test_an_admin_of_a_different_organization_cannot_approve(
        self, execution, customer_a, org_b, db
    ):
        """
        Approving a change to your *own* production cluster is a legitimate customer
        decision. Approving one for a different tenant is not.
        """
        from accounts.models import Membership, MembershipRole, SystemRole, User
        from conftest import PASSWORD

        other_admin = User.objects.create_user(
            email="admin@beta.test",
            password=PASSWORD,
            full_name="Bea Admin",
            system_role=SystemRole.CUSTOMER,
        )
        Membership.objects.create(
            user=other_admin, organization=org_b, role=MembershipRole.ADMIN
        )

        at_change = self._reach_change_step(execution, customer_a)
        assert execution_service.can_approve(other_admin, at_change) is False
        with pytest.raises(ApprovalRequiredError):
            execution_service.advance(
                execution=at_change, user=other_admin, response_value="yes"
            )

    def test_the_api_returns_403_approval_required(
        self, auth_client, execution, customer_a
    ):
        client = auth_client(customer_a)
        first = client.post(
            f"/api/v1/playbook-executions/{execution.id}/advance/",
            {"response_value": "yes", "observation": "OOMKilled."},
            format="json",
        )
        assert first.status_code == 200
        assert first.data["execution"]["current_step_detail"]["requires_approval"] is True
        assert first.data["execution"]["current_step_detail"]["can_current_user_approve"] is False

        second = client.post(
            f"/api/v1/playbook-executions/{execution.id}/advance/",
            {"response_value": "yes", "observation": "Applying."},
            format="json",
        )
        assert second.status_code == 403
        assert second.data["error"]["code"] == "approval_required"
        assert "approval" in second.data["error"]["message"].lower()

    def test_the_api_reports_approval_capability_per_role(
        self, auth_client, execution, customer_a, customer_a_admin
    ):
        auth_client(customer_a).post(
            f"/api/v1/playbook-executions/{execution.id}/advance/",
            {"response_value": "yes", "observation": "OOMKilled."},
            format="json",
        )
        as_admin = auth_client(customer_a_admin).get(
            f"/api/v1/playbook-executions/{execution.id}/"
        )
        assert as_admin.status_code == 200
        step = as_admin.data["current_step_detail"]
        assert step["requires_approval"] is True
        assert step["can_current_user_approve"] is True

    def test_an_approval_is_audited_with_the_blast_radius(
        self, execution, customer_a, customer_a_admin
    ):
        from accounts.models import AuditLog

        at_change = self._reach_change_step(execution, customer_a)
        execution_service.advance(
            execution=at_change,
            user=customer_a_admin,
            response_value="yes",
            observation="Applied.",
        )
        entry = AuditLog.objects.filter(
            action="execution.step_approval_granted", actor=customer_a_admin
        ).first()
        assert entry is not None
        assert "approved change step" in entry.summary.lower()
        assert "restarts the compute cluster" in entry.summary.lower()

    def test_read_only_steps_never_require_approval(self, execution, customer_a):
        step = execution.current_step
        assert step.is_read_only is True
        assert step.requires_approval is False
        result = execution_service.advance(
            execution=execution, user=customer_a, response_value="yes"
        )
        assert result.response.approval_granted_by_id is None


class TestOutcomeCapture:
    def test_a_resolved_outcome_requires_evidence(self, execution, customer_a):
        """A completed checklist is not proof a problem is fixed."""
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        execution.refresh_from_db()
        with pytest.raises(DomainValidationError) as excinfo:
            execution_service.complete(
                execution=execution,
                user=customer_a,
                outcome="resolved",
                outcome_summary="All done.",
                outcome_evidence="",
            )
        assert "observed" in str(excinfo.value.detail).lower()

    def test_a_non_resolved_outcome_does_not_require_evidence(self, execution, customer_a):
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        execution.refresh_from_db()
        result = execution_service.complete(
            execution=execution,
            user=customer_a,
            outcome="not_resolved",
            outcome_summary="The symptoms do not match this playbook.",
        )
        assert result.status == ExecutionStatus.NOT_RESOLVED

    def test_a_customer_resolution_is_not_fde_verified(
        self, execution, customer_a, customer_a_admin
    ):
        """
        The distinction that protects every future customer: self-reported success does not
        admit a resolution to trusted retrieval.
        """
        at_change = self._complete_to_verify(execution, customer_a, customer_a_admin)
        completed = execution_service.complete(
            execution=at_change,
            user=customer_a,
            outcome="resolved",
            outcome_summary="Raised memory.",
            outcome_evidence="Job completes.",
        )
        ticket = completed.ticket
        ticket.refresh_from_db()
        assert ticket.status == TicketStatus.RESOLVED
        assert ticket.self_service_resolved is True
        assert ticket.resolution_verified is False
        assert ticket.resolution_verified_by_id is None

    def test_playbook_outcome_counters_are_updated(
        self, execution, customer_a, customer_a_admin, approved_playbook
    ):
        at_verify = self._complete_to_verify(execution, customer_a, customer_a_admin)
        execution_service.complete(
            execution=at_verify,
            user=customer_a,
            outcome="resolved",
            outcome_summary="Fixed.",
            outcome_evidence="Verified by re-running.",
        )
        approved_playbook.refresh_from_db()
        assert approved_playbook.success_count == 1
        assert approved_playbook.failure_count == 0
        assert approved_playbook.usage_count == 1
        assert approved_playbook.success_rate == 1.0

    def test_a_failed_outcome_counts_against_the_playbook(self, execution, customer_a, approved_playbook):
        execution_service.advance(
            execution=execution, user=customer_a, response_value="no", observation="Evicted."
        )
        execution.refresh_from_db()
        execution_service.complete(
            execution=execution,
            user=customer_a,
            outcome="not_resolved",
            outcome_summary="Wrong playbook.",
        )
        approved_playbook.refresh_from_db()
        assert approved_playbook.failure_count == 1
        assert approved_playbook.success_rate == 0.0

    def test_success_rate_is_none_before_any_outcome(self, approved_playbook):
        """`None` and `0.0` are different claims: "untested" is not "never works"."""
        assert approved_playbook.success_rate is None

    @staticmethod
    def _complete_to_verify(execution, customer, admin):
        first = execution_service.advance(
            execution=execution, user=customer, response_value="yes", observation="OOMKilled."
        )
        second = execution_service.advance(
            execution=first.execution, user=admin, response_value="yes", observation="Applied."
        )
        third = execution_service.advance(
            execution=second.execution, user=customer, response_value="yes",
            observation="Job completes.",
        )
        return third.execution


class TestEscalationPackage:
    def test_the_package_carries_the_diagnostic_record(
        self, execution, customer_a
    ):
        execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="no",
            observation="The pod shows Evicted due to disk pressure, not OOMKilled.",
        )
        execution.refresh_from_db()
        package = execution_service.build_escalation_package(execution)

        assert package["playbook"]["title"]
        assert package["path"] == ["confirm"]
        assert len(package["steps_completed"]) == 1
        step = package["steps_completed"][0]
        assert step["what_to_inspect"]
        assert step["expected"]
        assert "Evicted" in step["observation"]
        # The negative observation is what was ruled out, which is the useful part.
        assert package["ruled_out"], package
        assert "did not observe" in package["ruled_out"][0]

    def test_the_package_is_available_through_the_api(
        self, auth_client, execution, customer_a
    ):
        auth_client(customer_a).post(
            f"/api/v1/playbook-executions/{execution.id}/advance/",
            {"response_value": "no", "observation": "Evicted, not OOMKilled."},
            format="json",
        )
        response = auth_client(customer_a).get(
            f"/api/v1/playbook-executions/{execution.id}/escalation-package/"
        )
        assert response.status_code == 200
        assert response.data["steps_completed"]
        assert response.data["ruled_out"]


class TestApplicabilityAtStartTime:
    def test_applicability_is_rechecked_at_start_not_only_in_search(
        self, make_ticket, org_legacy, customer_legacy, approved_playbook
    ):
        """
        A user can bookmark a URL and a playbook can be deprecated between the search and
        the click, so the check belongs at the point of action.
        """
        ticket = make_ticket(organization=org_legacy, reporter=customer_legacy)
        check = execution_service.check_applicability(
            playbook=approved_playbook, ticket=ticket
        )
        assert check.applicable is False
        assert any("version" in reason.lower() for reason in check.reasons)

        with pytest.raises(DomainValidationError):
            execution_service.start(
                ticket=ticket, playbook=approved_playbook, user=customer_legacy
            )

    def test_the_applicability_endpoint_explains_before_the_click(
        self, auth_client, make_ticket, org_legacy, customer_legacy, approved_playbook
    ):
        ticket = make_ticket(organization=org_legacy, reporter=customer_legacy)
        response = auth_client(customer_legacy).get(
            "/api/v1/playbook-executions/applicability/"
            f"?ticket={ticket.id}&playbook={approved_playbook.id}"
        )
        assert response.status_code == 200
        assert response.data["applicable"] is False
        assert response.data["reasons"]

    def test_a_high_risk_playbook_warns_up_front(
        self, make_ticket, org_a, customer_a, make_playbook, fde_lead
    ):
        from playbooks.models import RiskLevel

        playbook = make_playbook(
            reviewer=fde_lead, approve=True, risk_level=RiskLevel.HIGH
        )
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        check = execution_service.check_applicability(playbook=playbook, ticket=ticket)
        assert check.applicable is True
        assert any("high risk" in warning.lower() for warning in check.warnings)


class TestNoCommandExecution:
    def test_commands_are_data_and_marked_display_only(self, execution, customer_a):
        """
        The backend never runs anything from a playbook. The serialized step says so
        explicitly, so the UI cannot present a command as something COMPASS will execute.
        """
        step = execution.current_step
        payload = execution_service.serialize_step(
            step, user=customer_a, execution=execution
        )
        assert payload["commands"]
        assert all(command["is_read_only"] for command in payload["commands"])
        assert "never executes" in payload["commands_notice"].lower()

    def test_no_shell_execution_primitive_is_reachable_from_the_engine(self):
        """
        A structural guard over the execution engine and the services it orchestrates.

        Parsed as an AST rather than grepped as text, so the module's own prose — which
        discusses subprocesses precisely in order to rule them out — does not trip it, and
        so a genuine `import subprocess` or `eval(...)` cannot hide inside a string. If this
        ever fails, a reviewer should be stopped and asked why playbook content is being
        executed.
        """
        import ast
        import inspect

        from playbooks.services import knowledge as knowledge_service

        forbidden_modules = {"subprocess", "os", "pty", "shlex", "commands", "popen2"}
        forbidden_calls = {"eval", "exec", "compile", "__import__", "system", "popen"}

        for module in (execution_service, knowledge_service):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        assert root not in forbidden_modules, (
                            f"{module.__name__} imports {alias.name!r}. Playbook content is "
                            "data and must never be executed."
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0]
                    assert root not in forbidden_modules, (
                        f"{module.__name__} imports from {node.module!r}."
                    )
                elif isinstance(node, ast.Call):
                    name = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    assert name not in forbidden_calls, (
                        f"{module.__name__} calls {name!r}, which can execute code."
                    )

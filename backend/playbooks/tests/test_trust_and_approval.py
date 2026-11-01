"""
Knowledge trust and the approval lifecycle — acceptance tests 5, 8, 9 and 10.

The claim being defended: "approved" means a named human reviewed this on a recorded date,
and nothing else reaches a customer as a verified resolution.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from playbooks.models import (
    ApprovalDecision,
    ApprovalStatus,
    KnowledgeApproval,
    PlaybookStep,
    ResolutionPlaybook,
    ResponseKind,
    RiskLevel,
    StepType,
)
from playbooks.services import execution as execution_service
from playbooks.services import knowledge as knowledge_service
from tickets.services import similar

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


class TestUnverifiedKnowledgeNeverEntersTrustedSearch:
    """Acceptance test 5."""

    @pytest.mark.parametrize(
        "status",
        [ApprovalStatus.DRAFT, ApprovalStatus.IN_REVIEW, ApprovalStatus.REJECTED,
         ApprovalStatus.DEPRECATED],
    )
    def test_only_approved_playbooks_are_trusted(self, make_playbook, fde_lead, status):
        playbook = make_playbook(reviewer=fde_lead, approve=False)
        playbook.approval_status = status
        playbook.save(update_fields=["approval_status"])

        trusted_ids = set(ResolutionPlaybook.objects.trusted().values_list("id", flat=True))
        assert playbook.id not in trusted_ids
        assert playbook.is_trusted is False

    def test_a_draft_is_not_offered_to_a_matching_ticket(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        draft = make_playbook(reviewer=fde_lead, approve=False)
        ticket = make_ticket(organization=org_a, reporter=customer_a)

        analysis = similar.analyse(ticket=ticket, user=customer_a, limit=5)
        offered = {match.playbook.playbook_id for match in analysis.playbook_matches}
        assert draft.playbook_id not in offered
        assert analysis.recommended_playbook is None

    def test_a_non_shared_approved_playbook_is_not_trusted_globally(
        self, make_playbook, fde_lead
    ):
        """
        An FDE can approve a playbook but mark it not-shared when its content is
        irreducibly customer-specific. That must keep it out of cross-tenant retrieval.
        """
        playbook = make_playbook(reviewer=fde_lead, approve=False, is_shared=False)
        knowledge_service.approve(playbook=playbook, reviewer=fde_lead, is_shared=False)
        playbook.refresh_from_db()
        assert playbook.approval_status == ApprovalStatus.APPROVED
        assert playbook.is_trusted is False
        assert playbook.id not in set(
            ResolutionPlaybook.objects.trusted().values_list("id", flat=True)
        )

    def test_a_draft_cannot_be_run_as_a_workflow(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        from common.exceptions import DomainValidationError

        draft = make_playbook(reviewer=fde_lead, approve=False)
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            execution_service.start(ticket=ticket, playbook=draft, user=customer_a)
        assert "approved" in str(excinfo.value.detail).lower()

    def test_starting_a_draft_is_refused_through_the_api(
        self, auth_client, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        """
        A draft the customer *can* see — because it was drafted from their own ticket —
        still cannot be run.

        `origin_organization` is set deliberately: without it the draft is invisible to the
        customer and the API answers 404, which is also correct but tests visibility rather
        than the approval rule this case is about.
        """
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        draft = make_playbook(reviewer=fde_lead, approve=False)
        draft.origin_organization = org_a
        draft.source_ticket = ticket
        draft.save(update_fields=["origin_organization", "source_ticket"])

        client = auth_client(customer_a)
        # Readable…
        assert client.get(f"/api/v1/playbooks/{draft.id}/").status_code == 200
        # …but not runnable.
        response = client.post(
            "/api/v1/playbook-executions/",
            {"ticket": str(ticket.id), "playbook": str(draft.id)},
            format="json",
        )
        assert response.status_code == 400
        assert "approved" in str(response.data).lower()

    def test_an_invisible_draft_is_not_even_addressable(
        self, auth_client, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        draft = make_playbook(reviewer=fde_lead, approve=False)
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        response = auth_client(customer_a).post(
            "/api/v1/playbook-executions/",
            {"ticket": str(ticket.id), "playbook": str(draft.id)},
            format="json",
        )
        assert response.status_code == 404


class TestWhoMayApprove:
    """Acceptance test 8."""

    @pytest.mark.parametrize("role_fixture", ["customer_a", "customer_a_admin", "customer_a_viewer"])
    def test_no_customer_role_can_approve(
        self, request, auth_client, make_playbook, fde_lead, role_fixture
    ):
        user = request.getfixturevalue(role_fixture)
        playbook = make_playbook(reviewer=fde_lead, approve=False)
        response = auth_client(user).post(
            f"/api/v1/playbooks/{playbook.id}/approve/", {}, format="json"
        )
        assert response.status_code == 403, f"{user.email} should not be able to approve"
        playbook.refresh_from_db()
        assert playbook.approval_status != ApprovalStatus.APPROVED

    @pytest.mark.parametrize("role_fixture", ["fde", "fde_lead", "platform_admin"])
    def test_iomete_staff_can_approve(
        self, request, auth_client, make_playbook, fde_lead, role_fixture
    ):
        reviewer = request.getfixturevalue(role_fixture)
        playbook = make_playbook(
            reviewer=fde_lead, approve=False, playbook_id=f"pb-{role_fixture}"
        )
        response = auth_client(reviewer).post(
            f"/api/v1/playbooks/{playbook.id}/approve/",
            {"notes": "Reviewed."},
            format="json",
        )
        assert response.status_code == 200, response.data
        playbook.refresh_from_db()
        assert playbook.approval_status == ApprovalStatus.APPROVED
        assert playbook.approved_by_id == reviewer.id

    def test_customer_cannot_reject_or_deprecate(
        self, auth_client, customer_a_admin, approved_playbook, make_playbook, fde_lead
    ):
        draft = make_playbook(reviewer=fde_lead, approve=False, playbook_id="pb-reject")
        client = auth_client(customer_a_admin)
        assert client.post(
            f"/api/v1/playbooks/{draft.id}/reject/", {"reason": "no"}, format="json"
        ).status_code == 403
        assert client.post(
            f"/api/v1/playbooks/{approved_playbook.id}/deprecate/",
            {"reason": "no"},
            format="json",
        ).status_code == 403

    def test_approval_is_recorded_with_a_named_reviewer_and_date(
        self, make_playbook, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=False)
        result = knowledge_service.approve(
            playbook=playbook, reviewer=fde_lead, notes="Checked against two incidents."
        )
        approval = result.approval
        assert approval.decision == ApprovalDecision.APPROVED
        assert approval.reviewer_id == fde_lead.id
        assert approval.reviewer_label == fde_lead.email
        assert approval.notes
        playbook.refresh_from_db()
        assert playbook.approved_at is not None
        assert playbook.review_due_at is not None
        assert playbook.review_due_at > playbook.approved_at


class TestApprovalRefusesUnsafeContent:
    def test_cannot_approve_without_a_confirmed_root_cause(self, make_playbook, fde_lead):
        from common.exceptions import DomainValidationError

        playbook = make_playbook(reviewer=fde_lead, approve=False)
        playbook.confirmed_root_cause = ""
        playbook.save(update_fields=["confirmed_root_cause"])
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        assert "root cause" in str(excinfo.value.detail).lower()

    def test_cannot_approve_a_change_step_reachable_without_diagnostics(
        self, fde_lead
    ):
        """
        The safety rule that makes Resolution Replay trustworthy: remediation must come
        after the evidence that justifies it.
        """
        from common.exceptions import DomainValidationError

        playbook = ResolutionPlaybook.objects.create(
            playbook_id="unsafe-jump-to-change",
            version=1,
            title="Jumps straight to a change",
            description="Badly authored.",
            confirmed_root_cause="Something.",
            resolution_instructions="Change it.",
            is_synthetic=True,
        )
        PlaybookStep.objects.create(
            playbook=playbook,
            order=1,
            key="change",
            title="Restart everything immediately",
            plain_explanation="No diagnostics first.",
            step_type=StepType.CHANGE_REQUIRING_APPROVAL,
            risk_level=RiskLevel.HIGH,
            blast_radius="Everything.",
            response_kind=ResponseKind.BOOLEAN,
            branches={"yes": "__resolved", "no": "__escalate"},
            is_terminal=True,
        )
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        message = str(excinfo.value.detail).lower()
        assert "diagnostic" in message

    def test_cannot_approve_a_change_step_without_a_blast_radius(self, fde_lead):
        from common.exceptions import DomainValidationError

        playbook = ResolutionPlaybook.objects.create(
            playbook_id="no-blast-radius",
            version=1,
            title="Change step with no stated impact",
            description="Badly authored.",
            confirmed_root_cause="Something.",
            resolution_instructions="Change it.",
            is_synthetic=True,
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=1, key="look", title="Look at the pod",
            plain_explanation="Read-only.", step_type=StepType.READ_ONLY_DIAGNOSTIC,
            response_kind=ResponseKind.BOOLEAN, branches={"yes": "change", "no": "__escalate"},
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=2, key="change", title="Change it",
            plain_explanation="Changes a running system.",
            step_type=StepType.CHANGE_REQUIRING_APPROVAL, risk_level=RiskLevel.MEDIUM,
            blast_radius="",  # the omission under test
            response_kind=ResponseKind.BOOLEAN, branches={"yes": "__resolved", "no": "__escalate"},
            is_terminal=True,
        )
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        assert "blast radius" in str(excinfo.value.detail).lower()

    def test_cannot_approve_a_playbook_containing_a_destructive_command(self, fde_lead):
        from common.exceptions import DomainValidationError

        playbook = ResolutionPlaybook.objects.create(
            playbook_id="destructive-command",
            version=1,
            title="Contains a destructive command",
            description="Badly authored.",
            confirmed_root_cause="Something.",
            resolution_instructions="Delete it.",
            is_synthetic=True,
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=1, key="look", title="Look",
            plain_explanation="Read-only.", step_type=StepType.READ_ONLY_DIAGNOSTIC,
            response_kind=ResponseKind.BOOLEAN, branches={"yes": "nuke", "no": "__escalate"},
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=2, key="nuke", title="Delete the deployment",
            plain_explanation="Destroys the workload.",
            step_type=StepType.CHANGE_REQUIRING_APPROVAL, risk_level=RiskLevel.HIGH,
            blast_radius="Destroys the workload.",
            commands=[{"label": "Delete", "command": "kubectl delete deployment iom-core",
                       "language": "bash", "is_read_only": False}],
            response_kind=ResponseKind.BOOLEAN, branches={"yes": "__resolved", "no": "__escalate"},
            is_terminal=True,
        )
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        assert "destructive" in str(excinfo.value.detail).lower()

    def test_a_playbook_with_no_terminal_outcome_cannot_be_approved(self, fde_lead):
        from common.exceptions import DomainValidationError

        playbook = ResolutionPlaybook.objects.create(
            playbook_id="no-terminal",
            version=1,
            title="Never finishes",
            description="Badly authored.",
            confirmed_root_cause="Something.",
            resolution_instructions="Look forever.",
            is_synthetic=True,
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=1, key="a", title="Step A",
            plain_explanation="Look.", step_type=StepType.READ_ONLY_DIAGNOSTIC,
            response_kind=ResponseKind.BOOLEAN, branches={"__default": "b"},
        )
        PlaybookStep.objects.create(
            playbook=playbook, order=2, key="b", title="Step B",
            plain_explanation="Look again.", step_type=StepType.READ_ONLY_DIAGNOSTIC,
            response_kind=ResponseKind.BOOLEAN, branches={"__default": "a"},
        )
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        assert "terminal" in str(excinfo.value.detail).lower()

    def test_rejection_requires_and_retains_a_reason(self, make_playbook, fde_lead):
        from common.exceptions import DomainValidationError

        playbook = make_playbook(reviewer=fde_lead, approve=False)
        with pytest.raises(DomainValidationError):
            knowledge_service.reject(playbook=playbook, reviewer=fde_lead, reason="   ")

        knowledge_service.reject(
            playbook=playbook,
            reviewer=fde_lead,
            reason="The root cause is a guess; the source ticket was never verified.",
        )
        playbook.refresh_from_db()
        # Retained, not deleted — the reason is itself institutional knowledge.
        assert playbook.approval_status == ApprovalStatus.REJECTED
        assert "never verified" in playbook.rejection_reason
        assert KnowledgeApproval.objects.filter(
            playbook=playbook, decision=ApprovalDecision.REJECTED
        ).exists()


class TestApprovedPlaybookBecomesAvailable:
    """Acceptance test 9."""

    def test_approving_makes_it_reachable_for_an_eligible_future_ticket(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=False)
        before = make_ticket(organization=org_a, reporter=customer_a)
        analysis_before = similar.analyse(ticket=before, user=customer_a, limit=5)
        assert playbook.playbook_id not in {
            match.playbook.playbook_id for match in analysis_before.playbook_matches
        }

        knowledge_service.approve(playbook=playbook, reviewer=fde_lead)
        playbook.refresh_from_db()

        after = make_ticket(organization=org_a, reporter=customer_a)
        analysis_after = similar.analyse(ticket=after, user=customer_a, limit=5)
        offered = {match.playbook.playbook_id for match in analysis_after.playbook_matches}
        assert playbook.playbook_id in offered
        assert analysis_after.recommendation == "run_playbook"
        assert analysis_after.recommended_playbook.playbook_id == playbook.playbook_id

    def test_an_approved_playbook_crosses_the_tenant_boundary(
        self, make_playbook, make_ticket, org_b, customer_b, fde_lead
    ):
        """
        The one sanctioned cross-tenant path. A playbook approved from org A's incident is
        offered to org B — which is the entire value of knowledge compounding, and is safe
        precisely because an FDE reviewed and redacted it.
        """
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        ticket = make_ticket(organization=org_b, reporter=customer_b)
        analysis = similar.analyse(ticket=ticket, user=customer_b, limit=5)
        assert playbook.playbook_id in {
            match.playbook.playbook_id for match in analysis.playbook_matches
        }

    def test_customer_can_read_an_approved_playbook_through_the_api(
        self, auth_client, customer_a, approved_playbook
    ):
        response = auth_client(customer_a).get(f"/api/v1/playbooks/{approved_playbook.id}/")
        assert response.status_code == 200
        assert response.data["is_trusted"] is True
        assert "Verified knowledge" in response.data["trust_notice"]
        assert response.data["steps"]

    def test_customer_cannot_read_another_tenants_draft(
        self, auth_client, customer_a, make_playbook, make_ticket, org_b, customer_b, fde_lead
    ):
        other_ticket = make_ticket(organization=org_b, reporter=customer_b)
        draft = make_playbook(reviewer=fde_lead, approve=False)
        draft.origin_organization = org_b
        draft.source_ticket = other_ticket
        draft.save(update_fields=["origin_organization", "source_ticket"])

        response = auth_client(customer_a).get(f"/api/v1/playbooks/{draft.id}/")
        assert response.status_code == 404


class TestDeprecation:
    """Acceptance test 10."""

    def test_a_deprecated_playbook_is_not_recommended(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        knowledge_service.deprecate(
            playbook=playbook,
            reviewer=fde_lead,
            reason="Superseded by platform defaults in the 3.20 release.",
        )
        playbook.refresh_from_db()
        assert playbook.is_deprecated
        assert playbook.is_trusted is False

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=ticket, user=customer_a, limit=5)
        assert playbook.playbook_id not in {
            match.playbook.playbook_id for match in analysis.playbook_matches
        }
        assert analysis.recommended_playbook is None

    def test_a_deprecated_playbook_remains_readable_and_flagged(
        self, auth_client, customer_a, make_playbook, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        knowledge_service.deprecate(
            playbook=playbook, reviewer=fde_lead, reason="No longer valid."
        )
        response = auth_client(customer_a).get(f"/api/v1/playbooks/{playbook.id}/")
        # Still readable — anyone who followed it in the past needs to be able to see it.
        assert response.status_code == 200
        assert response.data["is_trusted"] is False
        assert "Deprecated" in response.data["trust_notice"]

    def test_a_deprecated_playbook_cannot_be_run(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        from common.exceptions import DomainValidationError

        playbook = make_playbook(reviewer=fde_lead, approve=True)
        knowledge_service.deprecate(
            playbook=playbook, reviewer=fde_lead, reason="No longer valid."
        )
        playbook.refresh_from_db()
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            execution_service.start(ticket=ticket, playbook=playbook, user=customer_a)
        assert "deprecated" in str(excinfo.value.detail).lower()

    def test_an_overdue_review_lowers_resolution_confidence(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        from datetime import timedelta

        make_playbook(reviewer=fde_lead, approve=True, playbook_id="fresh-pb")
        stale = make_playbook(reviewer=fde_lead, approve=True, playbook_id="stale-pb")
        stale.review_due_at = timezone.now() - timedelta(days=30)
        stale.save(update_fields=["review_due_at"])
        stale.refresh_from_db()
        assert stale.is_review_overdue

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=ticket, user=customer_a, limit=5)
        scores = {
            match.playbook.playbook_id: match.score for match in analysis.playbook_matches
        }
        assert "fresh-pb" in scores and "stale-pb" in scores
        assert scores["stale-pb"].resolution_confidence < scores["fresh-pb"].resolution_confidence
        assert any(
            item.kind == "review_overdue" for item in scores["stale-pb"].evidence
        )


class TestVersioning:
    def test_a_new_version_starts_as_a_draft_and_supersedes_the_old(
        self, make_playbook, fde_lead
    ):
        original = make_playbook(reviewer=fde_lead, approve=True)
        new_version = knowledge_service.create_new_version(
            playbook=original, author=fde_lead
        )
        assert new_version.version == original.version + 1
        assert new_version.approval_status == ApprovalStatus.DRAFT
        assert new_version.supersedes_id == original.id
        assert new_version.steps.count() == original.steps.count()
        # The new draft is not trusted until it is approved in its own right.
        assert new_version.is_trusted is False

    def test_an_execution_keeps_the_version_it_actually_ran(
        self, make_playbook, make_ticket, org_a, customer_a, fde_lead
    ):
        """
        `playbook_version` is denormalised on the execution so that superseding a playbook
        cannot silently rewrite the history of what an engineer was shown.
        """
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        ticket = make_ticket(organization=org_a, reporter=customer_a)
        execution = execution_service.start(
            ticket=ticket, playbook=playbook, user=customer_a
        )
        assert execution.playbook_version == 1

        knowledge_service.create_new_version(playbook=playbook, author=fde_lead)
        execution.refresh_from_db()
        assert execution.playbook_version == 1


class TestDuplicatePrevention:
    def test_extraction_links_to_an_existing_playbook_instead_of_duplicating(
        self, resolved_ticket, make_playbook, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        # Share the fingerprint, which is the strongest duplicate signal.
        if resolved_ticket.fingerprint_id:
            playbook.fingerprints.add(resolved_ticket.fingerprint)

        before = ResolutionPlaybook.objects.count()
        result = knowledge_service.extract_from_ticket(
            ticket=resolved_ticket, actor=fde_lead
        )
        assert result.playbook is None
        assert result.duplicate_of is not None
        assert result.duplicate_of.id == playbook.id
        assert ResolutionPlaybook.objects.count() == before
        assert any("already covers" in note for note in result.notes)

    def test_force_overrides_duplicate_detection(
        self, resolved_ticket, make_playbook, fde_lead
    ):
        playbook = make_playbook(reviewer=fde_lead, approve=True)
        if resolved_ticket.fingerprint_id:
            playbook.fingerprints.add(resolved_ticket.fingerprint)

        result = knowledge_service.extract_from_ticket(
            ticket=resolved_ticket, actor=fde_lead, force=True
        )
        assert result.playbook is not None
        assert result.playbook.approval_status == ApprovalStatus.DRAFT

    def test_extraction_requires_a_recorded_resolution(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        from common.exceptions import DomainValidationError

        open_ticket = make_ticket(organization=org_a, reporter=customer_a)
        with pytest.raises(DomainValidationError) as excinfo:
            knowledge_service.extract_from_ticket(ticket=open_ticket, actor=fde_lead)
        assert "no recorded resolution" in str(excinfo.value.detail).lower()

    def test_a_generated_draft_declares_what_produced_it(self, resolved_ticket, fde_lead):
        result = knowledge_service.extract_from_ticket(
            ticket=resolved_ticket, actor=fde_lead
        )
        playbook = result.playbook
        assert playbook is not None
        # The reviewer must know they are reading machine-drafted content.
        assert playbook.generated_by == "demo"
        assert playbook.approval_status == ApprovalStatus.DRAFT
        assert any("not trusted knowledge" in note for note in result.notes)

    def test_a_draft_starts_with_narrow_applicability(self, resolved_ticket, fde_lead):
        """
        Applicability must start at exactly what was observed. Widening it is a reviewer's
        explicit decision, because the opposite default silently recommends unverified fixes.
        """
        result = knowledge_service.extract_from_ticket(
            ticket=resolved_ticket, actor=fde_lead
        )
        playbook = result.playbook
        assert playbook.applicable_versions == f"=={resolved_ticket.iomete_version}"
        assert playbook.applicable_environments == [resolved_ticket.environment]

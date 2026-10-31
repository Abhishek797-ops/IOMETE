"""
Shared test fixtures.

The fixtures build data through the **real services** (`intake.create_ticket`,
`lifecycle.record_resolution`, `knowledge.approve`), not by writing rows. That is
deliberate: a fixture that inserts a `Ticket` directly produces a row with no fingerprint,
no embedding and no normalisation, so a retrieval test against it would pass while proving
nothing about the actual pipeline.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import (
    CloudProvider,
    DeploymentModel,
    Membership,
    MembershipRole,
    Organization,
    SystemRole,
    User,
)
from playbooks.models import (
    PlaybookStep,
    ResolutionPlaybook,
    ResponseKind,
    RiskLevel,
    StepType,
)
from playbooks.services import knowledge as knowledge_service
from tickets.models import Environment, Severity, TicketComponent
from tickets.services import intake, lifecycle

PASSWORD = "test-password-9871"


# =======================================================================================
# Organizations
# =======================================================================================


@pytest.fixture
def org_a(db) -> Organization:
    return Organization.objects.create(
        name="Alpha Analytics",
        slug="alpha",
        iomete_version="3.19.1",
        environment_label="production",
        deployment_model=DeploymentModel.ON_PREMISES,
        cloud_provider=CloudProvider.ON_PREM,
        is_synthetic=True,
    )


@pytest.fixture
def org_b(db) -> Organization:
    return Organization.objects.create(
        name="Beta Logistics",
        slug="beta",
        iomete_version="3.19.1",
        environment_label="production",
        deployment_model=DeploymentModel.PUBLIC_CLOUD,
        cloud_provider=CloudProvider.AWS,
        is_synthetic=True,
    )


@pytest.fixture
def org_legacy(db) -> Organization:
    """An organization on an older release, so version gating has something to gate."""
    return Organization.objects.create(
        name="Gamma Freight",
        slug="gamma",
        iomete_version="2.4.0",
        environment_label="production",
        deployment_model=DeploymentModel.PRIVATE_CLOUD,
        cloud_provider=CloudProvider.OTHER,
        is_synthetic=True,
    )


# =======================================================================================
# Users
# =======================================================================================


def _make_user(email: str, role: str, name: str) -> User:
    return User.objects.create_user(
        email=email, password=PASSWORD, full_name=name, system_role=role
    )


@pytest.fixture
def fde(db) -> User:
    return _make_user("fde@iomete.test", SystemRole.FDE, "Fran Delgado")


@pytest.fixture
def fde_lead(db) -> User:
    return _make_user("lead@iomete.test", SystemRole.FDE_LEAD, "Lena Dubois")


@pytest.fixture
def platform_admin(db) -> User:
    return _make_user("admin@iomete.test", SystemRole.PLATFORM_ADMIN, "Pat Admin")


@pytest.fixture
def customer_a(db, org_a) -> User:
    user = _make_user("eng@alpha.test", SystemRole.CUSTOMER, "Ana Engineer")
    Membership.objects.create(user=user, organization=org_a, role=MembershipRole.ENGINEER)
    return user


@pytest.fixture
def customer_a_admin(db, org_a) -> User:
    user = _make_user("admin@alpha.test", SystemRole.CUSTOMER, "Alex Admin")
    Membership.objects.create(user=user, organization=org_a, role=MembershipRole.ADMIN)
    return user


@pytest.fixture
def customer_a_viewer(db, org_a) -> User:
    user = _make_user("view@alpha.test", SystemRole.CUSTOMER, "Val Viewer")
    Membership.objects.create(user=user, organization=org_a, role=MembershipRole.VIEWER)
    return user


@pytest.fixture
def customer_b(db, org_b) -> User:
    user = _make_user("eng@beta.test", SystemRole.CUSTOMER, "Ben Engineer")
    Membership.objects.create(user=user, organization=org_b, role=MembershipRole.ENGINEER)
    return user


@pytest.fixture
def customer_legacy(db, org_legacy) -> User:
    user = _make_user("eng@gamma.test", SystemRole.CUSTOMER, "Gus Engineer")
    Membership.objects.create(user=user, organization=org_legacy, role=MembershipRole.ADMIN)
    return user


# =======================================================================================
# API clients
# =======================================================================================


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_client():
    """Factory: `auth_client(user)` returns an APIClient authenticated as that user."""

    def _build(user: User) -> APIClient:
        client = APIClient()
        response = client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
        )
        assert response.status_code == 200, response.data
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    return _build


# =======================================================================================
# Tickets
# =======================================================================================

OOM_ERROR = (
    "ExecutorLostFailure (executor 7 exited caused by one of the running tasks) "
    "Reason: Container killed: OOMKilled (exit code 137)"
)


@pytest.fixture
def make_ticket():
    """
    Factory for tickets created through the real intake pipeline.

    Returns redacted, normalised, fingerprinted, embedded tickets — which is what the
    retrieval tests need in order to mean anything.
    """

    def _build(
        *,
        organization,
        reporter=None,
        title="Executors keep restarting during the nightly job",
        description=(
            "Our nightly aggregation job fails partway through. Executors are terminated "
            "repeatedly and the job never finishes."
        ),
        error_message=OOM_ERROR,
        diagnostics="",
        component=TicketComponent.SPARK_COMPUTE,
        severity=Severity.HIGH,
        environment=Environment.PRODUCTION,
        iomete_version=None,
        **extra,
    ):
        return intake.create_ticket(
            organization=organization,
            reporter=reporter,
            title=title,
            description=description,
            error_message=error_message,
            diagnostics=diagnostics,
            component=component,
            severity=severity,
            environment=environment,
            iomete_version=iomete_version or organization.iomete_version,
            is_synthetic=True,
            **extra,
        ).ticket

    return _build


@pytest.fixture
def resolved_ticket(make_ticket, org_a, customer_a, fde_lead):
    """A verified, resolved ticket in org A — the canonical historical precedent."""
    ticket = make_ticket(organization=org_a, reporter=customer_a)
    lifecycle.record_resolution(
        ticket=ticket,
        user=fde_lead,
        summary=(
            "spark.executor.memory was provisioned below the peak requirement of a skewed "
            "partition. Raised executor memory to 12g and enabled adaptive skew-join "
            "handling."
        ),
        evidence=(
            "The nightly job completed in 38 minutes with no executor loss and OOMKilled no "
            "longer appears in the executor events."
        ),
        self_service=False,
        fde_investigation_minutes=180,
    )
    lifecycle.verify_resolution(ticket=ticket, reviewer=fde_lead, quality=5)
    ticket.refresh_from_db()
    return ticket


# =======================================================================================
# Playbooks
# =======================================================================================


@pytest.fixture
def make_playbook():
    """
    Factory producing a valid, branching playbook with a diagnostic step before its
    approval-gated change step — so `validate_graph()` passes and the approval-enforcement
    tests have something realistic to run against.
    """

    def _build(
        *,
        playbook_id="test-oom-playbook",
        title="Spark executor terminated with OOMKilled",
        component=TicketComponent.SPARK_COMPUTE,
        category="resource_exhaustion",
        applicable_versions=">=3.0,<4.0",
        applicable_environments=None,
        symptoms=None,
        risk_level=RiskLevel.MEDIUM,
        approve=True,
        reviewer=None,
        is_shared=True,
    ):
        playbook = ResolutionPlaybook.objects.create(
            playbook_id=playbook_id,
            version=1,
            title=title,
            description="Executors are killed because the container exceeded its memory limit.",
            component=component,
            category=category,
            applicable_versions=applicable_versions,
            applicable_environments=(
                ["production", "staging"]
                if applicable_environments is None
                else applicable_environments
            ),
            symptoms=symptoms if symptoms is not None else ["executor_restarting", "out_of_memory"],
            confirmed_root_cause=(
                "Executor memory was below the workload's peak requirement, so the kubelet "
                "terminated the container with OOMKilled."
            ),
            expected_evidence=["Reason: OOMKilled with Exit Code: 137"],
            resolution_instructions="Raise spark.executor.memory and memoryOverhead.",
            verification_steps=["Re-run the failing job and confirm it completes."],
            risk_level=risk_level,
            is_shared=is_shared,
            is_synthetic=True,
        )
        PlaybookStep.objects.create(
            playbook=playbook,
            order=1,
            key="confirm",
            title="Confirm the executor was killed for memory",
            plain_explanation="Check the pod's last state for OOMKilled.",
            what_to_inspect="kubectl describe pod <executor-pod>",
            expected_observation="Reason: OOMKilled",
            step_type=StepType.READ_ONLY_DIAGNOSTIC,
            risk_level=RiskLevel.LOW,
            commands=[
                {
                    "label": "Pod status",
                    "language": "bash",
                    "command": "kubectl describe pod <executor-pod> -n <namespace>",
                    "is_read_only": True,
                }
            ],
            response_kind=ResponseKind.BOOLEAN,
            branches={"yes": "apply", "no": "__escalate"},
        )
        PlaybookStep.objects.create(
            playbook=playbook,
            order=2,
            key="apply",
            title="Raise executor memory",
            plain_explanation="Increase spark.executor.memory. The cluster restarts.",
            expected_observation="The cluster restarts cleanly",
            step_type=StepType.CHANGE_REQUIRING_APPROVAL,
            risk_level=RiskLevel.MEDIUM,
            blast_radius="Restarts the compute cluster; running queries are interrupted.",
            response_kind=ResponseKind.BOOLEAN,
            branches={"yes": "verify", "no": "__escalate"},
        )
        PlaybookStep.objects.create(
            playbook=playbook,
            order=3,
            key="verify",
            title="Re-run the failing workload",
            plain_explanation="Confirm the job now completes.",
            expected_observation="The job completes with no OOMKilled",
            step_type=StepType.VERIFICATION,
            risk_level=RiskLevel.INFORMATIONAL,
            response_kind=ResponseKind.BOOLEAN,
            branches={"yes": "__resolved", "no": "__escalate"},
            is_terminal=True,
        )

        if approve:
            assert reviewer is not None, "Approving a playbook requires a reviewer."
            knowledge_service.approve(playbook=playbook, reviewer=reviewer)
            playbook.refresh_from_db()
        else:
            knowledge_service.refresh_index(playbook)
            playbook.refresh_from_db()
        return playbook

    return _build


@pytest.fixture
def approved_playbook(make_playbook, fde_lead):
    return make_playbook(reviewer=fde_lead, approve=True)


@pytest.fixture(autouse=True)
def _reset_retrieval_backend_cache():
    """
    Clear the cached pgvector detection between tests.

    The detection is `lru_cache`d for performance in production, which would otherwise leak
    state across tests that change the database vendor assumption.
    """
    from aiengine.services import retrieval

    retrieval.reset_backend_cache()
    yield
    retrieval.reset_backend_cache()


@pytest.fixture(autouse=True)
def _reset_knowledge_cache():
    """The product knowledge base is process-cached; tests may reload it."""
    from knowledge.services import product_knowledge

    product_knowledge.load.cache_clear()
    yield
    product_knowledge.load.cache_clear()

"""
Playbook, Resolution Replay and knowledge-approval API.

Permission notes that matter:

* Playbook *reads* use `ResolutionPlaybook.objects.visible_to(user)` — a customer sees
  approved shared playbooks plus drafts from their own tickets, never another tenant's
  unapproved material.
* Playbook *writes* and all approval actions require IOMETE staff. `CanApproveKnowledge`
  guards approve/reject/deprecate specifically, because that is the trust boundary of the
  whole compounding loop.
* Execution writes are tenant-scoped and the approval gate inside
  `PlaybookExecutionService.advance()` is the authority on system-changing steps — the view
  does not duplicate that logic, it just surfaces the error.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import (
    CanApproveKnowledge,
    IsAuthenticatedAndActive,
    IsIometeStaff,
    IsSameOrganization,
)
from tickets.models import Ticket

from .models import ApprovalStatus, PlaybookExecution, PlaybookStep, ResolutionPlaybook
from .serializers import (
    ApproveSerializer,
    DeprecateSerializer,
    ExecutionAdvanceSerializer,
    ExecutionCompleteSerializer,
    ExecutionSerializer,
    ExecutionStartSerializer,
    ExtractSerializer,
    FdePlaybookSerializer,
    GraphIssueSerializer,
    KnowledgeApprovalSerializer,
    PlaybookDetailSerializer,
    PlaybookListSerializer,
    PlaybookStepWriteSerializer,
    PlaybookWriteSerializer,
    RejectSerializer,
)
from .services import execution as execution_service
from .services import knowledge as knowledge_service


@extend_schema_view(
    list=extend_schema(
        tags=["playbooks"],
        summary="List resolution playbooks",
        description=(
            "Every payload carries `is_trusted` and a `trust_notice` stating exactly what "
            "its approval status means, so a draft cannot be rendered as verified "
            "knowledge by omission.\n\n"
            "Pass `?trusted=true` for approved, shared, non-deprecated playbooks only — "
            "the set that may be recommended."
        ),
        parameters=[
            OpenApiParameter("trusted", bool, OpenApiParameter.QUERY,
                             description="Only playbooks that may be recommended."),
        ],
    ),
    retrieve=extend_schema(tags=["playbooks"], summary="Retrieve a playbook"),
    partial_update=extend_schema(
        tags=["playbooks"], summary="Edit a playbook (IOMETE staff)",
        description="Content only. Approval happens through the dedicated approve action so "
                    "that graph validation and the audit record cannot be bypassed.",
    ),
)
class PlaybookViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive]
    filterset_fields = ("component", "category", "risk_level", "approval_status",
                        "is_shared", "is_synthetic")
    search_fields = ("playbook_id", "title", "description", "confirmed_root_cause")
    ordering_fields = ("approved_at", "created_at", "usage_count", "title")

    def get_permissions(self):
        if self.action in {"update", "partial_update", "steps", "create_version",
                           "validate", "extract"}:
            return [IsIometeStaff()]
        if self.action in {"approve", "reject", "request_changes", "deprecate"}:
            return [CanApproveKnowledge()]
        return [IsAuthenticatedAndActive()]

    def get_queryset(self):
        queryset = (
            ResolutionPlaybook.objects.visible_to(self.request.user)
            .select_related("approved_by", "created_by", "source_ticket",
                            "origin_organization", "cluster", "supersedes")
            .prefetch_related("steps")
        )
        if str(self.request.query_params.get("trusted", "")).lower() in {"1", "true", "yes"}:
            queryset = queryset.trusted()
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return PlaybookListSerializer
        if self.action in {"update", "partial_update"}:
            return PlaybookWriteSerializer
        if self.request.user.is_authenticated and self.request.user.is_iomete_staff:
            return FdePlaybookSerializer
        return PlaybookDetailSerializer

    def perform_update(self, serializer):
        playbook = serializer.save()
        # Content changed, so the retrieval text and embedding must follow or the playbook
        # becomes unfindable by its new wording.
        knowledge_service.refresh_index(playbook)

    # --- Step editing ---------------------------------------------------------------

    @extend_schema(
        tags=["playbooks"],
        summary="Replace a playbook's steps (IOMETE staff)",
        description=(
            "Replaces the full step list atomically. Steps are replaced rather than "
            "patched individually because the branch graph is only coherent as a whole — a "
            "partial update can leave dangling targets.\n\n"
            "The response includes `graph_issues`: errors here will block approval."
        ),
        request=PlaybookStepWriteSerializer(many=True),
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["put"])
    def steps(self, request, pk=None):
        playbook = self.get_object()
        if playbook.approval_status == ApprovalStatus.APPROVED:
            return Response(
                {
                    "error": {
                        "code": "conflict",
                        "message": (
                            "This playbook is approved. Create a new version rather than "
                            "editing the steps of one that executions have already run "
                            "against."
                        ),
                        "details": {},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = PlaybookStepWriteSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        from django.db import transaction

        with transaction.atomic():
            playbook.steps.all().delete()
            for item in serializer.validated_data:
                PlaybookStep.objects.create(playbook=playbook, **item)

        issues = execution_service.validate_graph(playbook)
        knowledge_service.refresh_index(playbook)
        return Response(
            {
                "playbook": FdePlaybookSerializer(playbook).data,
                "graph_issues": GraphIssueSerializer(
                    [issue.__dict__ for issue in issues], many=True
                ).data,
            }
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Validate the step graph",
        description=(
            "Checks for dangling branch targets, unreachable steps, a system-changing step "
            "reachable without a preceding diagnostic, a missing blast-radius declaration, "
            "no path to a terminal outcome, and destructive commands. Errors block approval."
        ),
        responses={200: GraphIssueSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def validate(self, request, pk=None):
        playbook = self.get_object()
        issues = execution_service.validate_graph(playbook)
        return Response(
            {
                "can_be_approved": not any(i.severity == "error" for i in issues),
                "issues": GraphIssueSerializer(
                    [issue.__dict__ for issue in issues], many=True
                ).data,
            }
        )

    # --- Approval lifecycle ---------------------------------------------------------

    @extend_schema(
        tags=["fde"],
        summary="Approve a playbook into trusted knowledge",
        description=(
            "The trust boundary. Refused if the step graph has errors, or if the playbook "
            "has no confirmed root cause — an unexplained fix is not verified knowledge.\n\n"
            "Approval sets a re-review date. Reviewers can narrow applicability and risk "
            "in the same call; those changes are recorded on the approval record."
        ),
        request=ApproveSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        playbook = self.get_object()
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = knowledge_service.approve(
            playbook=playbook, reviewer=request.user, **serializer.validated_data
        )
        return Response(
            {
                "playbook": FdePlaybookSerializer(result.playbook).data,
                "approval": KnowledgeApprovalSerializer(result.approval).data,
                "warnings": GraphIssueSerializer(
                    [issue.__dict__ for issue in result.graph_issues], many=True
                ).data,
            }
        )

    @extend_schema(tags=["fde"], summary="Reject a draft", request=RejectSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        playbook = self.get_object()
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = knowledge_service.reject(
            playbook=playbook, reviewer=request.user,
            reason=serializer.validated_data["reason"],
        )
        playbook.refresh_from_db()
        return Response(
            {
                "playbook": FdePlaybookSerializer(playbook).data,
                "approval": KnowledgeApprovalSerializer(approval).data,
            }
        )

    @extend_schema(tags=["fde"], summary="Request changes", request=RejectSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="request-changes")
    def request_changes(self, request, pk=None):
        playbook = self.get_object()
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = knowledge_service.request_changes(
            playbook=playbook, reviewer=request.user,
            notes=serializer.validated_data["reason"],
        )
        playbook.refresh_from_db()
        return Response(
            {
                "playbook": FdePlaybookSerializer(playbook).data,
                "approval": KnowledgeApprovalSerializer(approval).data,
            }
        )

    @extend_schema(
        tags=["fde"],
        summary="Deprecate an approved playbook",
        description=(
            "Removes it from recommendations immediately while keeping it readable, "
            "flagged, for audit and for anyone who followed it before."
        ),
        request=DeprecateSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def deprecate(self, request, pk=None):
        playbook = self.get_object()
        serializer = DeprecateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval = knowledge_service.deprecate(
            playbook=playbook, reviewer=request.user,
            reason=serializer.validated_data["reason"],
        )
        playbook.refresh_from_db()
        return Response(
            {
                "playbook": FdePlaybookSerializer(playbook).data,
                "approval": KnowledgeApprovalSerializer(approval).data,
            }
        )

    @extend_schema(
        tags=["fde"],
        summary="Create a new draft version",
        description=(
            "Forks an approved playbook into a new draft. Existing executions keep "
            "pointing at the version they actually ran, which is why "
            "`PlaybookExecution.playbook_version` is denormalised."
        ),
        request=None,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="new-version")
    def create_version(self, request, pk=None):
        playbook = self.get_object()
        new_version = knowledge_service.create_new_version(
            playbook=playbook, author=request.user
        )
        return Response(
            FdePlaybookSerializer(new_version).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        tags=["fde"], summary="Review history",
        responses={200: KnowledgeApprovalSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def approvals(self, request, pk=None):
        playbook = self.get_object()
        return Response(
            KnowledgeApprovalSerializer(
                playbook.approvals.select_related("reviewer"), many=True
            ).data
        )

    @extend_schema(
        tags=["fde"],
        summary="All versions of this playbook",
        responses={200: PlaybookListSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        playbook = self.get_object()
        queryset = ResolutionPlaybook.objects.visible_to(request.user).filter(
            playbook_id=playbook.playbook_id
        ).order_by("-version")
        return Response(PlaybookListSerializer(queryset, many=True).data)


@extend_schema(
    tags=["fde"],
    summary="Generate a knowledge draft from a resolved ticket",
    description=(
        "The knowledge-compounding step. Extracts symptoms, root cause, investigation, "
        "resolution and verification from a resolved ticket (and its Resolution Replay run, "
        "when there was one) into a **draft** playbook.\n\n"
        "Duplicate-aware: if an existing playbook already covers this error signature or "
        "the ticket's cluster, no draft is created and the existing playbook is returned "
        "instead. Pass `force: true` to override.\n\n"
        "The draft starts with deliberately narrow applicability — exactly the version and "
        "environment the fix was observed in. Widening it is a reviewer's explicit decision."
    ),
    request=ExtractSerializer,
    responses={200: OpenApiTypes.OBJECT},
)
class KnowledgeExtractionView(APIView):
    permission_classes = [IsIometeStaff]
    throttle_scope = "ai"

    def post(self, request) -> Response:
        serializer = ExtractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = get_object_or_404(
            Ticket.objects.for_user(request.user),
            id=serializer.validated_data["ticket"],
        )
        result = knowledge_service.extract_from_ticket(
            ticket=ticket, actor=request.user,
            force=serializer.validated_data["force"],
        )
        return Response(
            {
                "playbook": (
                    FdePlaybookSerializer(result.playbook).data if result.playbook else None
                ),
                "duplicate_of": (
                    PlaybookListSerializer(result.duplicate_of).data
                    if result.duplicate_of
                    else None
                ),
                "redaction_flags": result.redaction_flags,
                "notes": result.notes,
                "ai": {
                    "provider": result.provider,
                    "is_live_model": result.provider_is_live,
                    "notice": result.provider_notice,
                },
            },
            status=status.HTTP_201_CREATED if result.playbook else status.HTTP_200_OK,
        )


@extend_schema(
    tags=["fde"],
    summary="Knowledge review queue",
    description=(
        "Everything awaiting FDE attention: new drafts, playbooks with requested changes, "
        "approved playbooks overdue for re-review, and resolved tickets that have no draft "
        "yet. The last bucket is the one that keeps the loop turning — a resolved "
        "investigation with no playbook is knowledge that will be re-derived from scratch."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class KnowledgeReviewQueueView(APIView):
    permission_classes = [IsIometeStaff]

    def get(self, request) -> Response:
        from django.db.models import Exists, OuterRef
        from django.utils import timezone

        drafts = ResolutionPlaybook.objects.filter(
            approval_status=ApprovalStatus.DRAFT
        ).select_related("source_ticket", "created_by", "origin_organization")
        in_review = ResolutionPlaybook.objects.filter(
            approval_status=ApprovalStatus.IN_REVIEW
        ).select_related("source_ticket", "created_by")
        overdue = ResolutionPlaybook.objects.filter(
            approval_status=ApprovalStatus.APPROVED,
            review_due_at__lt=timezone.now(),
        ).select_related("approved_by")

        has_playbook = ResolutionPlaybook.objects.filter(source_ticket=OuterRef("pk"))
        undocumented = (
            Ticket.objects.for_user(request.user)
            .filter(resolution_verified=True)
            .exclude(resolution_summary="")
            .annotate(documented=Exists(has_playbook))
            .filter(documented=False)
            .select_related("organization")
            .order_by("-resolved_at")
        )

        from tickets.serializers import TicketListSerializer

        return Response(
            {
                "counts": {
                    "drafts": drafts.count(),
                    "changes_requested": in_review.count(),
                    "review_overdue": overdue.count(),
                    "verified_tickets_without_a_playbook": undocumented.count(),
                },
                "drafts": PlaybookListSerializer(drafts[:25], many=True).data,
                "changes_requested": PlaybookListSerializer(in_review[:25], many=True).data,
                "review_overdue": PlaybookListSerializer(overdue[:25], many=True).data,
                "verified_tickets_without_a_playbook": TicketListSerializer(
                    undocumented[:25], many=True
                ).data,
                "notes": {
                    "verified_tickets_without_a_playbook": (
                        "These resolutions were verified but never written up. Each one is "
                        "an investigation that will have to be repeated the next time a "
                        "customer hits the same problem."
                    ),
                    "review_overdue": (
                        "Approved playbooks past their re-review date. The product they "
                        "describe may have changed underneath them."
                    ),
                },
            }
        )


@extend_schema_view(
    list=extend_schema(
        tags=["playbooks"], summary="List Resolution Replay runs",
        description="Tenant-scoped. Includes the full response history for each run.",
    ),
    retrieve=extend_schema(tags=["playbooks"], summary="Retrieve a run"),
)
class ExecutionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ExecutionSerializer
    permission_classes = [IsAuthenticatedAndActive, IsSameOrganization]
    filterset_fields = ("status", "ticket", "playbook", "organization")
    ordering_fields = ("created_at", "completed_at")

    def get_queryset(self):
        return (
            PlaybookExecution.objects.for_user(self.request.user)
            .select_related("ticket", "playbook", "started_by", "current_step",
                            "organization")
            .prefetch_related("responses__step")
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Start a Resolution Replay",
        description=(
            "Begins a guided workflow for a ticket. Applicability is re-checked here even "
            "though retrieval already gated — a playbook can be deprecated between the "
            "search and the click, and an API client can post any id.\n\n"
            "Resuming is idempotent: an in-progress run for the same ticket and playbook "
            "is returned rather than duplicated, so a page refresh does not lose collected "
            "observations."
        ),
        request=ExecutionStartSerializer,
        responses={201: ExecutionSerializer},
    )
    def create(self, request):
        serializer = ExecutionStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = get_object_or_404(
            Ticket.objects.for_user(request.user), id=serializer.validated_data["ticket"]
        )
        playbook = get_object_or_404(
            ResolutionPlaybook.objects.visible_to(request.user),
            id=serializer.validated_data["playbook"],
        )
        execution = execution_service.start(
            ticket=ticket, playbook=playbook, user=request.user
        )
        return Response(
            ExecutionSerializer(execution, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Check whether a playbook can be run against a ticket",
        description=(
            "Dry run of the applicability check, so the UI can explain why a playbook is "
            "unavailable before the user clicks."
        ),
        parameters=[
            OpenApiParameter("ticket", str, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("playbook", str, OpenApiParameter.QUERY, required=True),
        ],
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="applicability")
    def applicability(self, request):
        ticket = get_object_or_404(
            Ticket.objects.for_user(request.user), id=request.query_params.get("ticket")
        )
        playbook = get_object_or_404(
            ResolutionPlaybook.objects.visible_to(request.user),
            id=request.query_params.get("playbook"),
        )
        check = execution_service.check_applicability(playbook=playbook, ticket=ticket)
        return Response(
            {
                "applicable": check.applicable,
                "reasons": check.reasons,
                "warnings": check.warnings,
            }
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Answer the current step and advance",
        description=(
            "Records the observation and follows the branch map.\n\n"
            "A step whose `step_type` is `change_requiring_approval` **cannot be completed** "
            "without an approving user — IOMETE staff, or an administrator of the "
            "organization that owns the execution. An unauthorised attempt returns 403 "
            "`approval_required` with an explanation, not a silent failure."
        ),
        request=ExecutionAdvanceSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        execution = self.get_object()
        serializer = ExecutionAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execution_service.advance(
            execution=execution, user=request.user, **serializer.validated_data
        )
        return Response(
            {
                "execution": ExecutionSerializer(
                    result.execution, context={"request": request}
                ).data,
                "terminal": result.terminal,
                "requires_outcome_capture": result.requires_outcome_capture,
                "outcome_prompt": (
                    "The workflow has reached an end point. Record what actually happened "
                    "and what you observed — completing the steps is not by itself "
                    "evidence that the problem is fixed."
                )
                if result.requires_outcome_capture
                else "",
            }
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Finish a run with an explicit outcome",
        description=(
            "`outcome_evidence` is required for a `resolved` outcome. A `resolved` run marks "
            "the ticket resolved and self-service, but does **not** mark the resolution "
            "verified — only an FDE can do that, and verification is what admits a fix to "
            "trusted retrieval as precedent for other customers."
        ),
        request=ExecutionCompleteSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        execution = self.get_object()
        serializer = ExecutionCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = execution_service.complete(
            execution=execution, user=request.user, **serializer.validated_data
        )
        return Response(
            ExecutionSerializer(updated, context={"request": request}).data
        )

    @extend_schema(
        tags=["playbooks"],
        summary="Escalation package",
        description=(
            "Everything an FDE needs from this run: the path taken, what was observed, what "
            "was ruled out. This is what makes an escalation from COMPASS different from an "
            "email — the investigation arrives already done."
        ),
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"], url_path="escalation-package")
    def escalation_package(self, request, pk=None):
        execution = self.get_object()
        return Response(execution_service.build_escalation_package(execution))

"""
Ticket API.

Views validate, delegate to one service, and serialize. Every queryset goes through
`Ticket.objects.for_user()` — the single sanctioned tenant-scoping mechanism — and
`IsSameOrganization` makes the object-level authorization decision explicitly rather than
inferring it from a 404.
"""

from __future__ import annotations

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization, User
from common.exceptions import DomainValidationError
from common.permissions import (
    IsAuthenticatedAndActive,
    IsIometeStaff,
    IsSameOrganization,
)
from playbooks.serializers import PlaybookMatchSerializer

from .models import IssueCluster, Ticket, TicketAttachment
from .serializers import (
    AttachmentUploadSerializer,
    ClusterConfirmSerializer,
    ClusterStatusSerializer,
    CustomerTicketSerializer,
    FdeTicketSerializer,
    IssueClusterSerializer,
    SimilarityMatchSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketCommentSerializer,
    TicketCreateSerializer,
    TicketEscalateSerializer,
    TicketEventSerializer,
    TicketListSerializer,
    TicketResolveSerializer,
    TicketStatusChangeSerializer,
    TicketVerifySerializer,
)
from .services import attachments as attachment_service
from .services import clustering, intake, lifecycle, similar


def _resolve_organization(user: User, requested_id) -> Organization:
    """
    Which organization should a new ticket belong to?

    Explicit when the user belongs to several; inferred when there is exactly one. An
    IOMETE staff member must always state it — filing a ticket "on behalf of" the wrong
    tenant would put one customer's diagnostics in another's record.
    """
    organization_ids = user.organization_ids()
    if requested_id:
        if not user.is_iomete_staff and str(requested_id) not in {str(i) for i in organization_ids}:
            raise DomainValidationError(
                detail="You are not a member of that organization."
            )
        return get_object_or_404(Organization, id=requested_id)
    if user.is_iomete_staff:
        raise DomainValidationError(
            detail="IOMETE staff must specify which customer organization this ticket "
            "belongs to."
        )
    if len(organization_ids) == 1:
        return get_object_or_404(Organization, id=organization_ids[0])
    if not organization_ids:
        raise DomainValidationError(
            detail="Your account is not a member of any organization yet."
        )
    raise DomainValidationError(
        detail="You belong to more than one organization. Specify which one this ticket is for."
    )


@extend_schema_view(
    list=extend_schema(
        tags=["tickets"],
        summary="List tickets",
        description=(
            "Tenant-scoped. A customer sees their organizations' tickets; IOMETE staff see "
            "every tenant's. Internal FDE notes are never included for a customer role."
        ),
    ),
    retrieve=extend_schema(tags=["tickets"], summary="Retrieve a ticket"),
)
class TicketViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive, IsSameOrganization]
    filterset_fields = (
        "status", "severity", "component", "category", "organization",
        "resolution_verified", "self_service_resolved", "assigned_fde", "environment",
    )
    search_fields = ("reference", "title", "description", "error_message")
    ordering_fields = ("created_at", "resolved_at", "severity", "status")

    def get_queryset(self):
        return (
            Ticket.objects.for_user(self.request.user)
            .select_related("organization", "assigned_fde", "reporter", "cluster",
                            "fingerprint", "resolved_via_playbook")
            .prefetch_related("playbook_matches__playbook")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return TicketListSerializer
        if self.request.user.is_authenticated and self.request.user.is_iomete_staff:
            return FdeTicketSerializer
        return CustomerTicketSerializer

    # --- Creation -------------------------------------------------------------------

    @extend_schema(
        tags=["tickets"],
        summary="Submit a ticket",
        description=(
            "Creates a ticket. The submission is redacted, normalised (error codes, "
            "symptoms, failure category), fingerprinted and embedded before it is stored. "
            "The response reports what was redacted, so redaction is visible rather than "
            "silent.\n\n"
            "Supplying `error_message` and `iomete_version` materially improves the "
            "matches: the error line is the strongest retrieval signal, and without a "
            "version, resolutions cannot be checked for applicability and are gated out."
        ),
        request=TicketCreateSerializer,
        responses={201: CustomerTicketSerializer},
        examples=[
            OpenApiExample(
                "Spark executor OOM",
                value={
                    "title": "Executors keep restarting during the nightly rollup",
                    "description": "Our nightly aggregation over the transactions table "
                                   "fails partway through. Executors are terminated and "
                                   "the job never completes.",
                    "component": "spark_compute",
                    "severity": "high",
                    "iomete_version": "3.19.1",
                    "environment": "production",
                    "error_message": "ExecutorLostFailure Reason: Container killed: "
                                     "OOMKilled (exit code 137)",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        organization = _resolve_organization(request.user, data.pop("organization", None))

        result = intake.create_ticket(
            organization=organization, reporter=request.user, **data
        )
        clustering.assign_cluster(result.ticket)

        payload = self.get_serializer(result.ticket).data
        payload["intake"] = {
            "redaction_summary": result.redaction_summary,
            "redaction_notice": result.redaction_notice,
            "extracted_error_codes": result.normalization.error_codes,
            "extracted_symptoms": result.normalization.symptom_labels,
            "inferred_category": result.normalization.category,
            "inferred_component": result.normalization.component,
            "confidence_note": result.normalization.confidence_note,
            "embedding_provider": result.embedding_provider,
            "fingerprint": result.fingerprint_digest[:16],
        }
        return Response(payload, status=status.HTTP_201_CREATED)

    # --- The resolution engine ------------------------------------------------------

    @extend_schema(
        tags=["tickets"],
        summary="Find related history and applicable playbooks",
        description=(
            "Runs hybrid retrieval (vector + lexical + error fingerprint + metadata), "
            "scores each candidate on three *separate* confidences, applies the "
            "compatibility gate, and returns a grounded explanation with a "
            "recommendation.\n\n"
            "**The three scores are not interchangeable.** `similarity_score` says the "
            "reports look alike. `diagnosis_confidence` says the evidence supports the "
            "same cause. `resolution_confidence` says the fix is likely to work in *your* "
            "environment. A paraphrase can score 0.93 similarity with 0.30 diagnosis "
            "confidence.\n\n"
            "Retrieval is tenant-scoped: a customer searches their own resolved history. "
            "Cross-customer learning arrives through approved, FDE-redacted playbooks, "
            "which is the only sanctioned path across the tenant boundary."
        ),
        parameters=[
            OpenApiParameter("limit", int, OpenApiParameter.QUERY,
                             description="Maximum historical matches (default 8)."),
            OpenApiParameter("refresh", bool, OpenApiParameter.QUERY,
                             description="Re-run retrieval instead of returning the last "
                                         "stored result set."),
        ],
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get", "post"], url_path="similar")
    def similar(self, request, pk=None):
        ticket = self.get_object()
        refresh = (
            request.method == "POST"
            or str(request.query_params.get("refresh", "")).lower() in {"1", "true", "yes"}
        )
        try:
            limit = min(int(request.query_params.get("limit", 8)), 20)
        except (TypeError, ValueError):
            limit = 8

        existing = similar.latest_matches(ticket)
        if existing and not refresh:
            return Response(
                {
                    "ticket": ticket.reference,
                    "from_cache": True,
                    "matches": SimilarityMatchSerializer(existing, many=True).data,
                    "playbook_matches": PlaybookMatchSerializer(
                        similar.latest_playbook_matches(ticket), many=True
                    ).data,
                    "note": "Previously computed result set. Pass ?refresh=true to re-run.",
                }
            )

        analysis = similar.analyse(ticket=ticket, user=request.user, limit=limit)
        return Response(
            {
                "ticket": ticket.reference,
                "from_cache": False,
                "matches": SimilarityMatchSerializer(
                    similar.latest_matches(ticket), many=True
                ).data,
                "playbook_matches": PlaybookMatchSerializer(
                    similar.latest_playbook_matches(ticket), many=True
                ).data,
                "recommendation": analysis.recommendation,
                "recommendation_reason": analysis.recommendation_reason,
                "recommended_playbook_id": (
                    str(analysis.recommended_playbook.id)
                    if analysis.recommended_playbook
                    else None
                ),
                "explanation": analysis.explanation,
                "diagnostic_questions": analysis.diagnostic_questions,
                "retrieval": {
                    "vector_backend": analysis.retrieval_run.vector_backend,
                    "channel_counts": analysis.retrieval_run.channel_counts,
                    "channel_weights": analysis.retrieval_run.channel_weights,
                    "candidate_count": analysis.retrieval_run.candidate_count,
                    "gated_count": analysis.retrieval_run.gated_count,
                    "duration_ms": analysis.retrieval_run.duration_ms,
                    "embedding_provider": analysis.retrieval_run.embedding_provider,
                    "notes": analysis.retrieval_notes,
                },
                "ai": {
                    "provider": analysis.provider,
                    "is_live_model": analysis.provider_is_live,
                    "notice": analysis.provider_notice,
                },
            }
        )

    # --- Timeline and workflow ------------------------------------------------------

    @extend_schema(
        tags=["tickets"], summary="Ticket timeline",
        responses={200: TicketEventSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        ticket = self.get_object()
        queryset = ticket.events.select_related("author")
        if not request.user.is_iomete_staff:
            queryset = queryset.filter(is_internal=False)
        return Response(TicketEventSerializer(queryset, many=True).data)

    @extend_schema(
        tags=["tickets"], summary="Add a comment or internal note",
        request=TicketCommentSerializer, responses={201: TicketEventSerializer},
    )
    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = intake.add_comment(
            ticket=ticket, author=request.user, **serializer.validated_data
        )
        return Response(TicketEventSerializer(event).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["tickets"], summary="Change status", request=TicketStatusChangeSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = lifecycle.change_status(
            ticket=ticket, user=request.user,
            new_status=serializer.validated_data["status"],
            note=serializer.validated_data.get("note", ""),
        )
        return Response(self.get_serializer(updated).data)

    @extend_schema(
        tags=["tickets"],
        summary="Escalate to an FDE",
        description=(
            "Escalates with the diagnostic record attached. When the customer has run a "
            "Resolution Replay, the escalation carries what was checked, what was observed "
            "and what was ruled out — so the FDE starts where the customer stopped."
        ),
        request=TicketEscalateSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketEscalateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        execution = None
        if execution_id := serializer.validated_data.get("execution_id"):
            from playbooks.models import PlaybookExecution

            execution = get_object_or_404(
                PlaybookExecution.objects.for_user(request.user),
                id=execution_id, ticket=ticket,
            )

        result = lifecycle.escalate(
            ticket=ticket, user=request.user,
            reason=serializer.validated_data["reason"], execution=execution,
        )
        return Response(
            {
                "ticket": self.get_serializer(result.ticket).data,
                "escalation_summary": result.summary,
                "ai": {
                    "provider": result.provider,
                    "is_live_model": result.provider_is_live,
                    "notice": result.provider_notice,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["tickets"], summary="Record a resolution", request=TicketResolveSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = lifecycle.record_resolution(
            ticket=ticket, user=request.user, **serializer.validated_data
        )
        return Response(self.get_serializer(updated).data)

    @extend_schema(
        tags=["fde"],
        summary="Verify a resolution (IOMETE staff only)",
        description=(
            "Marks a resolution as FDE-verified, which is what admits it to trusted "
            "retrieval as precedent for other tickets. A customer marking a ticket "
            "resolved does *not* verify it."
        ),
        request=TicketVerifySerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsIometeStaff])
    def verify(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = lifecycle.verify_resolution(
            ticket=ticket, reviewer=request.user, **serializer.validated_data
        )
        return Response(FdeTicketSerializer(updated).data)

    @extend_schema(
        tags=["fde"], summary="Assign an FDE", request=TicketAssignSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], permission_classes=[IsIometeStaff])
    def assign(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignee_id = serializer.validated_data.get("assigned_fde")
        assignee = get_object_or_404(User, id=assignee_id) if assignee_id else None
        updated = lifecycle.assign(ticket=ticket, user=request.user, assignee=assignee)
        return Response(FdeTicketSerializer(updated).data)

    # --- Attachments ----------------------------------------------------------------

    @extend_schema(
        tags=["tickets"],
        summary="Attach a diagnostic file",
        description=(
            "Accepts logs, configuration excerpts and screenshots. Text uploads are "
            "**redacted in place** before the bytes are written, and the response reports "
            "what was removed. The client-supplied filename is kept as metadata only; the "
            "stored name is generated."
        ),
        request=AttachmentUploadSerializer,
        responses={201: TicketAttachmentSerializer},
    )
    @action(
        detail=True, methods=["post"], url_path="attachments",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_attachment(self, request, pk=None):
        ticket = self.get_object()
        serializer = AttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = attachment_service.upload(
            ticket=ticket,
            uploaded_file=serializer.validated_data["file"],
            user=request.user,
            is_internal=serializer.validated_data["is_internal"],
        )
        return Response(
            TicketAttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["tickets"],
        summary="Download an attachment",
        description=(
            "Authorizing download. Attachments are never served from a guessable static "
            "media path, and an internal attachment is not downloadable by a customer role."
        ),
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(
        detail=True, methods=["get"],
        url_path=r"attachments/(?P<attachment_id>[0-9a-f-]+)/download",
    )
    def download_attachment(self, request, pk=None, attachment_id=None):
        ticket = self.get_object()
        attachment = get_object_or_404(
            TicketAttachment, id=attachment_id, ticket=ticket
        )
        if attachment.is_internal and not request.user.is_iomete_staff:
            raise Http404
        try:
            handle = attachment.file.open("rb")
        except FileNotFoundError as exc:
            raise Http404("The stored file is missing.") from exc
        return FileResponse(
            handle,
            as_attachment=True,
            filename=attachment.original_name,
            content_type=attachment.content_type,
        )


@extend_schema_view(
    list=extend_schema(
        tags=["fde"],
        summary="List recurring issue clusters",
        description=(
            "IOMETE staff only — clusters span tenants by nature.\n\n"
            "**A cluster is a hypothesis.** `hypothesised_root_cause` is a working theory; "
            "`confirmed_root_cause` is only populated once an FDE has investigated and "
            "`is_root_cause_confirmed` is set. The two must be rendered differently: "
            "tickets with identical symptoms regularly have different causes."
        ),
    ),
    retrieve=extend_schema(tags=["fde"], summary="Retrieve a cluster"),
)
class IssueClusterViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = IssueClusterSerializer
    permission_classes = [IsIometeStaff]
    filterset_fields = ("status", "component", "category", "is_root_cause_confirmed")
    search_fields = ("title", "description", "key")
    ordering_fields = ("created_at", "updated_at")

    def get_queryset(self):
        return IssueCluster.objects.select_related("owner").prefetch_related(
            "tickets", "playbooks"
        )

    @extend_schema(
        tags=["fde"], summary="Tickets in this cluster",
        responses={200: TicketListSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        cluster = self.get_object()
        queryset = (
            cluster.tickets.select_related("organization", "assigned_fde")
            .prefetch_related("playbook_matches__playbook")
            .order_by("-created_at")
        )
        return Response(TicketListSerializer(queryset, many=True).data)

    @extend_schema(
        tags=["fde"],
        summary="Generate a grounded cluster hypothesis",
        description=(
            "Produces a working theory and a suggested investigation, grounded in the "
            "cluster's tickets. The result always reports `is_confirmed: false` — a "
            "generated hypothesis is never a finding."
        ),
        request=None,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="hypothesis")
    def hypothesis(self, request, pk=None):
        cluster = self.get_object()
        return Response(clustering.generate_hypothesis(cluster=cluster, actor=request.user))

    @extend_schema(
        tags=["fde"], summary="Confirm the root cause", request=ClusterConfirmSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="confirm-root-cause")
    def confirm_root_cause(self, request, pk=None):
        cluster = self.get_object()
        serializer = ClusterConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = clustering.confirm_root_cause(
            cluster=cluster, reviewer=request.user, **serializer.validated_data
        )
        return Response(IssueClusterSerializer(updated).data)

    @extend_schema(
        tags=["fde"], summary="Update investigation status", request=ClusterStatusSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        cluster = self.get_object()
        serializer = ClusterStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = clustering.update_status(
            cluster=cluster, reviewer=request.user, **serializer.validated_data
        )
        return Response(IssueClusterSerializer(updated).data)


@extend_schema(
    tags=["fde"],
    summary="FDE ticket inbox",
    description=(
        "A prioritised inbox rather than a list. Buckets are computed from the data and "
        "each carries its own count, so an FDE can see at a glance where the leverage is — "
        "particularly `has_approved_playbook`, which is work a customer could have done "
        "themselves."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class FdeInboxView(APIView):
    permission_classes = [IsIometeStaff]

    def get(self, request) -> Response:

        base = (
            Ticket.objects.for_user(request.user)
            .select_related("organization", "assigned_fde", "reporter", "cluster")
            .prefetch_related("playbook_matches__playbook")
        )
        open_tickets = base.exclude(status__in=["resolved", "closed"])

        with_playbook = open_tickets.filter(
            playbook_matches__playbook__approval_status="approved"
        ).exclude(playbook_matches__gate_status="gated").distinct()

        buckets = {
            "escalated": open_tickets.filter(status="escalated"),
            "critical": open_tickets.filter(severity="critical"),
            "unassigned": open_tickets.filter(assigned_fde__isnull=True),
            "assigned_to_me": open_tickets.filter(assigned_fde=request.user),
            "has_approved_playbook": with_playbook,
            "awaiting_verification": base.filter(
                status="resolved", resolution_verified=False
            ).exclude(resolution_summary=""),
        }

        return Response(
            {
                "counts": {name: queryset.count() for name, queryset in buckets.items()},
                "buckets": {
                    name: TicketListSerializer(queryset.order_by("-created_at")[:25],
                                               many=True).data
                    for name, queryset in buckets.items()
                },
                "notes": {
                    "has_approved_playbook": (
                        "These open tickets match an approved playbook that applies to "
                        "their environment. They are candidates for customer self-service "
                        "and the clearest signal of where COMPASS is saving FDE time."
                    ),
                    "awaiting_verification": (
                        "Resolved but not yet FDE-verified. Verification is what admits a "
                        "resolution to trusted retrieval, so this queue directly controls "
                        "the quality of future recommendations."
                    ),
                },
            }
        )

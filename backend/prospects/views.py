"""
Prospect-facing API: fit assessments, architecture recommendations, demo requests.

These are the only public *write* endpoints in COMPASS, so they are throttled and they
collect as little as possible. The Fit Finder works entirely anonymously; contact details
are optional and consent is recorded with the exact wording shown at the time.
"""

from __future__ import annotations

from dataclasses import asdict

from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.audit import record_audit
from common.permissions import IsIometeStaff

from .models import (
    ArchitectureRecommendation,
    DemoRequest,
    FitAssessment,
    ProspectProfile,
)
from .serializers import (
    CONSENT_TEXT,
    ArchitectureRecommendationSerializer,
    ArchitectureRequestSerializer,
    CallPrepRequestSerializer,
    DemoRequestCreateSerializer,
    DemoRequestSerializer,
    DemoRequestUpdateSerializer,
    FdeDemoRequestSerializer,
    FitAssessmentRequestSerializer,
    FitAssessmentSerializer,
    ProspectProfileSerializer,
)
from .services import architecture as architecture_service
from .services import call_prep as call_prep_service
from .services import fit as fit_service


def _profile_from_answers(answers: dict, *, contact: dict, source: str) -> ProspectProfile:
    consent = bool(contact.get("consent_given"))
    return ProspectProfile.objects.create(
        company_name=answers.get("company_name") or "",
        contact_name=contact.get("contact_name") or "",
        contact_email=contact.get("contact_email") or "",
        contact_role=answers.get("contact_role") or contact.get("contact_role") or "",
        persona=answers.get("persona") or "",
        company_type=answers.get("company_type", "other"),
        infrastructure_location=answers.get("infrastructure_location", "undecided"),
        cloud_providers=answers.get("cloud_providers") or [],
        current_systems=answers.get("current_systems") or [],
        data_volume=answers.get("data_volume", "unknown"),
        primary_use_case=answers.get("primary_use_case", "other"),
        secondary_use_cases=answers.get("secondary_use_cases") or [],
        sovereignty_requirement=answers.get("sovereignty_requirement", "unknown"),
        challenges=answers.get("challenges") or [],
        current_architecture=answers.get("current_architecture", "none"),
        constraints=answers.get("constraints") or [],
        kubernetes_maturity=answers.get("kubernetes_maturity") or "",
        team_size=answers.get("team_size") or "",
        consent_given=consent,
        # The exact wording shown, stored alongside the flag. "They ticked a box" is not
        # evidence of what they agreed to.
        consent_text=CONSENT_TEXT if consent else "",
        consent_at=timezone.now() if consent else None,
        source=source,
    )


@extend_schema(
    tags=["prospects"],
    summary="The published fit-assessment rubric",
    description=(
        "How a fit assessment is scored, published *before* you answer anything. Seven "
        "weighted dimensions summing to 100, the band thresholds, and the hard caps that "
        "override the arithmetic.\n\n"
        "This exists because the brief forbids misleading compatibility percentages. A "
        "score whose derivation is inspectable is a useful conversation starter; a bare "
        "\"87% compatible\" is a number people repeat without knowing what it means."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class FitRubricView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, _request) -> Response:
        return Response(fit_service.rubric_definition())


@extend_schema_view(
    list=extend_schema(tags=["prospects"], summary="List fit assessments (IOMETE staff)"),
    retrieve=extend_schema(
        tags=["prospects"],
        summary="Retrieve a fit assessment",
        description="Public by id, so a prospect can return to their own result via its link.",
    ),
)
class FitAssessmentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = FitAssessmentSerializer
    queryset = FitAssessment.objects.select_related("prospect").all()
    filterset_fields = ("band", "rubric_version", "is_synthetic")
    ordering_fields = ("created_at", "indicative_score")

    #: Actions a prospect may reach without an account. The assessment id is an
    #: unguessable UUID and acts as their own link back to their result and report.
    #: Listing stays staff-only — otherwise it would enumerate every prospect's answers.
    PUBLIC_ACTIONS = {"retrieve", "create", "rubric", "architecture", "report"}

    def get_permissions(self):
        # Note: this deliberately overrides any `permission_classes` on an @action
        # decorator, so every public action has to be named above. Keeping the decision in
        # one place is worth the small duplication — the alternative is a public endpoint
        # that is private by accident, or the reverse.
        if self.action in self.PUBLIC_ACTIONS:
            return [AllowAny()]
        return [IsIometeStaff()]

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "public"
        return super().get_throttles()

    @extend_schema(
        tags=["prospects"],
        summary="Create an indicative fit assessment",
        description=(
            "Scores the answers against the published rubric and returns the full "
            "breakdown: band, per-dimension reasoning, technical requirements, advantages, "
            "**gaps**, questions for an IOMETE sales engineer and a suggested next step.\n\n"
            "Works anonymously — contact details are optional, and consent is only required "
            "if you supply them.\n\n"
            "Every product statement cites IOMETE's own documentation. The assessment "
            "always includes gaps: one with no limitations would be marketing, not an "
            "assessment."
        ),
        request=FitAssessmentRequestSerializer,
        responses={201: FitAssessmentSerializer},
        examples=[
            OpenApiExample(
                "Regulated bank, on-premises",
                value={
                    "answers": {
                        "company_type": "financial",
                        "company_name": "Northwind Bank",
                        "infrastructure_location": "on_premises",
                        "current_systems": ["PostgreSQL", "Oracle", "S3"],
                        "bi_tools": ["Power BI"],
                        "data_volume": "tb_10_100",
                        "primary_use_case": "consolidation",
                        "sovereignty_requirement": "mandatory",
                        "challenges": ["data_residency", "cost", "duplicate_copies"],
                        "current_architecture": "both",
                        "kubernetes_maturity": "production",
                        "team_size": "dedicated platform team",
                    }
                },
                request_only=True,
            )
        ],
    )
    def create(self, request):
        serializer = FitAssessmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = dict(serializer.validated_data["answers"])
        contact = {
            "contact_name": serializer.validated_data.get("contact_name", ""),
            "contact_email": serializer.validated_data.get("contact_email", ""),
            "consent_given": serializer.validated_data.get("consent_given", False),
        }

        result = fit_service.assess(answers)

        with transaction.atomic():
            profile = _profile_from_answers(answers, contact=contact, source="fit-finder")
            assessment = FitAssessment.objects.create(
                prospect=profile,
                answers=answers,
                rubric_version=fit_service.RUBRIC_VERSION,
                indicative_score=result.score,
                band=result.band,
                rubric=result.rubric,
                requirement_summary=result.requirement_summary,
                suitability_reasons=result.suitability_reasons,
                technical_requirements=result.technical_requirements,
                advantages=result.advantages,
                gaps=result.gaps,
                questions_for_sales=result.questions_for_sales,
                caps_applied=result.caps_applied,
                next_step=result.next_step,
                cited_sources=result.cited_sources,
                disclaimer=result.disclaimer,
                generated_by="rubric",
            )
            # Generate the architecture alongside it: the recommendation is most of the
            # value and asking the prospect to click again loses half of them.
            graph = architecture_service.generate(answers, assessment=assessment)
            recommendation = ArchitectureRecommendation.objects.create(
                prospect=profile,
                assessment=assessment,
                title=graph.title,
                inputs=answers,
                nodes=graph.nodes,
                edges=graph.edges,
                layers=graph.layers,
                narrative=graph.narrative,
                integration_notes=graph.integration_notes,
                open_questions=graph.open_questions,
                conceptual_disclaimer=graph.conceptual_disclaimer,
                cited_sources=graph.cited_sources,
            )
            record_audit(
                action="fit_assessment.created",
                actor=request.user if request.user.is_authenticated else None,
                target_type="fit_assessment",
                target_id=str(assessment.id),
                summary=f"Fit assessment: {result.band} ({result.score}/100)",
                metadata={
                    "band": result.band,
                    "score": result.score,
                    "identified": profile.is_identified,
                    "caps_applied": result.caps_applied,
                },
            )

        return Response(
            {
                "assessment": FitAssessmentSerializer(assessment).data,
                "architecture": ArchitectureRecommendationSerializer(recommendation).data,
                "legend": graph.legend,
                "caps_applied": result.caps_applied,
                "rubric_definition_url": "/api/v1/fit-assessments/rubric/",
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["prospects"],
        summary="Architecture recommendation for an assessment",
        responses={200: ArchitectureRecommendationSerializer},
    )
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def architecture(self, request, pk=None):
        assessment = self.get_object()
        recommendation = assessment.recommendations.order_by("-created_at").first()
        if recommendation is None:
            graph = architecture_service.generate(assessment.answers, assessment=assessment)
            recommendation = ArchitectureRecommendation.objects.create(
                prospect=assessment.prospect,
                assessment=assessment,
                title=graph.title,
                inputs=assessment.answers,
                nodes=graph.nodes,
                edges=graph.edges,
                layers=graph.layers,
                narrative=graph.narrative,
                integration_notes=graph.integration_notes,
                open_questions=graph.open_questions,
                conceptual_disclaimer=graph.conceptual_disclaimer,
                cited_sources=graph.cited_sources,
            )
        return Response(
            {
                **ArchitectureRecommendationSerializer(recommendation).data,
                "legend": architecture_service.LEGEND,
            }
        )

    @extend_schema(
        tags=["prospects"],
        summary="Report data for download",
        description=(
            "Everything needed to render a downloadable architecture and fit report, in one "
            "payload: the assessment with its rubric, the architecture graph, resolved "
            "source citations and the disclaimers.\n\n"
            "The document itself is generated client-side so no prospect PII has to make a "
            "second round trip, and the prospect can produce the PDF without us storing one."
        ),
    responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"], permission_classes=[AllowAny], url_path="report")
    def report(self, request, pk=None):
        from knowledge.services.product_knowledge import resolve_sources, status_legend

        assessment = self.get_object()
        recommendation = assessment.recommendations.order_by("-created_at").first()
        return Response(
            {
                "generated_at": timezone.now().isoformat(),
                "product": "IOMETE COMPASS",
                "assessment": FitAssessmentSerializer(assessment).data,
                "architecture": (
                    ArchitectureRecommendationSerializer(recommendation).data
                    if recommendation
                    else None
                ),
                "legend": architecture_service.LEGEND,
                "rubric_definition": fit_service.rubric_definition(),
                "sources": resolve_sources(
                    sorted(
                        set(assessment.cited_sources)
                        | set(recommendation.cited_sources if recommendation else [])
                    )
                ),
                "status_legend": status_legend(),
                "disclaimer": assessment.disclaimer,
            }
        )


@extend_schema(
    tags=["prospects"],
    summary="Generate an architecture recommendation",
    description=(
        "Builds a layered architecture graph from stated infrastructure, without requiring "
        "a full fit assessment.\n\n"
        "**Every node carries a `claim_status`** so documented IOMETE components are "
        "distinguishable from COMPASS's conceptual placement of your systems: "
        "`documented`, `documented_integration`, `customer_system`, `conceptual`, "
        "`needs_confirmation`. The `legend` explains each and the frontend renders them "
        "differently. IOMETE does not replace your source systems or BI tools, and the "
        "graph is built so that cannot be implied."
    ),
    request=ArchitectureRequestSerializer,
    responses={200: OpenApiTypes.OBJECT},
)
class ArchitectureGenerateView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def post(self, request) -> Response:
        serializer = ArchitectureRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = dict(serializer.validated_data["answers"])

        assessment = None
        if assessment_id := serializer.validated_data.get("assessment"):
            assessment = FitAssessment.objects.filter(id=assessment_id).first()

        graph = architecture_service.generate(answers, assessment=assessment)
        return Response(
            {
                "title": graph.title,
                "nodes": graph.nodes,
                "edges": graph.edges,
                "layers": graph.layers,
                "legend": graph.legend,
                "narrative": graph.narrative,
                "integration_notes": graph.integration_notes,
                "open_questions": graph.open_questions,
                "conceptual_disclaimer": graph.conceptual_disclaimer,
                "cited_sources": graph.cited_sources,
            }
        )


@extend_schema(
    tags=["prospects"],
    summary="Reference architecture for the playground",
    description=(
        "The generic conceptual architecture behind `/architecture`, requiring no input. "
        "Source systems and BI tools shown are explicitly illustrative and labelled as "
        "such; every IOMETE component is documented and cited."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class ReferenceArchitectureView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, _request) -> Response:
        return Response(architecture_service.reference_architecture())


@extend_schema(
    tags=["prospects"],
    summary="Options for the call-prep form",
    responses={200: OpenApiTypes.OBJECT},
)
class CallPrepOptionsView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, _request) -> Response:
        from knowledge.services import product_knowledge as pk

        return Response(
            {
                "industries": call_prep_service.industries(),
                "meeting_types": call_prep_service.meeting_types(),
                "personas": [
                    {"value": persona["id"], "label": persona["label"]}
                    for persona in pk.personas()
                ],
                "status_legend": pk.status_legend(),
            }
        )


@extend_schema(
    tags=["prospects"],
    summary="Generate a call-preparation brief",
    description=(
        "Builds a sales-call brief from IOMETE's public documentation plus what the rep "
        "knows about the company.\n\n"
        "**Every statement carries a `status`.** `verified` and `vendor_claim` trace to "
        "IOMETE's own documentation with source ids attached; `assumed` marks an "
        "inference drawn from the submitted inputs rather than from any source; "
        "`unknown` marks a question the public documentation does not answer.\n\n"
        "Unknowns are **not** rewritten as plausible prose. They are collected into "
        "`unknowns` and counted in `coverage.unknown_rate`, so a rep can see before the "
        "call what proportion of the likely conversation COMPASS could not substantiate. "
        "`do_not_say` travels with every brief because the moment a rep most needs those "
        "guardrails is the moment they are improvising.\n\n"
        "Deterministic: the same inputs produce the same brief. No language model is "
        "involved."
    ),
    request=CallPrepRequestSerializer,
    responses={200: OpenApiTypes.OBJECT},
    examples=[
        OpenApiExample(
            "Regulated bank, discovery call",
            value={
                "company_name": "Northwind Bank",
                "industry": "financial_services",
                "company_size": "enterprise",
                "meeting_type": "discovery",
                "known_stack": ["Snowflake", "Oracle", "Power BI", "Kubernetes"],
                "attendee_personas": ["cto", "security-compliance"],
            },
            request_only=True,
        )
    ],
)
class CallPrepView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def post(self, request) -> Response:
        serializer = CallPrepRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        brief = call_prep_service.prepare(dict(serializer.validated_data))
        return Response(asdict(brief))


@extend_schema_view(
    list=extend_schema(tags=["prospects"], summary="List demo requests (IOMETE staff)"),
    retrieve=extend_schema(tags=["prospects"], summary="Retrieve a demo request"),
)
class DemoRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = DemoRequest.objects.select_related("prospect", "assessment", "handled_by")
    filterset_fields = ("status", "is_synthetic")
    search_fields = ("prospect__company_name", "prospect__contact_email", "message")
    ordering_fields = ("created_at",)

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsIometeStaff()]

    def get_serializer_class(self):
        if self.request.user.is_authenticated and self.request.user.is_iomete_staff:
            return FdeDemoRequestSerializer
        return DemoRequestSerializer

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "public"
        return super().get_throttles()

    @extend_schema(
        tags=["prospects"],
        summary="Request a demonstration",
        description=(
            "Captures a qualified prospect. Attaching a completed `assessment` is what "
            "makes it qualified: the sales engineer arrives already knowing the prospect's "
            "environment, constraints, gaps and open questions, so the first call is "
            "substantive rather than discovery.\n\n"
            "Consent is required, and the exact wording shown is stored with the record."
        ),
        request=DemoRequestCreateSerializer,
        responses={201: DemoRequestSerializer},
    )
    def create(self, request):
        serializer = DemoRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        assessment = None
        if assessment_id := data.get("assessment"):
            assessment = FitAssessment.objects.filter(id=assessment_id).first()

        with transaction.atomic():
            profile = None
            if prospect_id := data.get("prospect"):
                profile = ProspectProfile.objects.filter(id=prospect_id).first()
            if profile is None and assessment is not None:
                profile = assessment.prospect

            if profile is None:
                profile = _profile_from_answers(
                    {"company_name": data["company_name"], "contact_role": data.get("contact_role", "")},
                    contact={
                        "contact_name": data["contact_name"],
                        "contact_email": data["contact_email"],
                        "consent_given": True,
                    },
                    source="request-demo",
                )
            else:
                # Fill in contact details the anonymous assessment did not have.
                profile.contact_name = profile.contact_name or data["contact_name"]
                profile.contact_email = profile.contact_email or data["contact_email"]
                profile.company_name = profile.company_name or data["company_name"]
                profile.contact_role = profile.contact_role or data.get("contact_role", "")
                profile.consent_given = True
                profile.consent_text = CONSENT_TEXT
                profile.consent_at = profile.consent_at or timezone.now()
                profile.save()

            demo_request = DemoRequest.objects.create(
                prospect=profile,
                assessment=assessment,
                message=data.get("message", ""),
                preferred_timeframe=data.get("preferred_timeframe", ""),
                interests=data.get("interests") or [],
            )
            record_audit(
                action="demo_request.created",
                target_type="demo_request",
                target_id=str(demo_request.id),
                summary=f"Demo request from {profile.company_name or profile.contact_email}",
                metadata={
                    "has_assessment": assessment is not None,
                    "band": assessment.band if assessment else None,
                },
            )

        return Response(
            {
                **DemoRequestSerializer(demo_request).data,
                "confirmation": (
                    "Thank you — your request has been recorded"
                    + (
                        " along with your fit assessment, so the IOMETE team will have your "
                        "environment and open questions before the call."
                        if assessment
                        else "."
                    )
                ),
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["prospects"], summary="Update status or internal notes (IOMETE staff)",
        request=DemoRequestUpdateSerializer,
    responses={200: OpenApiTypes.OBJECT},
    )
    def partial_update(self, request, *args, **kwargs):
        demo_request = self.get_object()
        serializer = DemoRequestUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(demo_request, field, value)
        if "status" in serializer.validated_data:
            demo_request.handled_by = request.user
        demo_request.save()
        return Response(FdeDemoRequestSerializer(demo_request).data)


@extend_schema_view(
    list=extend_schema(
        tags=["prospects"],
        summary="List prospect profiles (IOMETE staff)",
        description="Staff-only. Listing these publicly would enumerate every prospect's answers.",
    ),
    retrieve=extend_schema(tags=["prospects"], summary="Retrieve a prospect profile"),
)
class ProspectProfileViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ProspectProfileSerializer
    permission_classes = [IsIometeStaff]
    queryset = ProspectProfile.objects.prefetch_related("assessments", "demo_requests")
    filterset_fields = ("company_type", "infrastructure_location", "sovereignty_requirement",
                        "consent_given", "source", "is_synthetic")
    search_fields = ("company_name", "contact_email", "contact_name")
    ordering_fields = ("created_at",)

    @extend_schema(
        tags=["prospects"], summary="Assessments for this prospect",
        responses={200: FitAssessmentSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def assessments(self, request, pk=None):
        profile = self.get_object()
        return Response(
            FitAssessmentSerializer(profile.assessments.order_by("-created_at"), many=True).data
        )

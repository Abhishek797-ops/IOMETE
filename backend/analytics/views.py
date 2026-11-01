"""
Analytics API.

Every response carries its methodology. The figures are tenant-scoped through
`Ticket.objects.for_user()`, so a customer's dashboard and an FDE's dashboard are the same
code with different visibility.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization
from common.permissions import IsAuthenticatedAndActive, IsIometeStaff

from .services import metrics

_WINDOW_PARAM = OpenApiParameter(
    "window", str, OpenApiParameter.QUERY,
    description="7d | 30d | 90d | 365d | all. Defaults to 30d.",
)
_ORG_PARAM = OpenApiParameter(
    "organization", str, OpenApiParameter.QUERY,
    description="Narrow to one organization. IOMETE staff only; a customer is already "
                "scoped to their own.",
)


def _window(request, default: str = "30d") -> str:
    window = request.query_params.get("window", default)
    return window if window in metrics.WINDOWS else default


def _organization(request):
    """
    Resolve an organization filter.

    A customer cannot use this to look at another tenant: the filter is applied *on top of*
    a `for_user()`-scoped queryset, so an id they are not a member of yields nothing. The
    explicit membership check is there to return a clear 404 instead of a confusing empty
    dashboard.
    """
    organization_id = request.query_params.get("organization")
    if not organization_id:
        return None
    organization = get_object_or_404(Organization, id=organization_id)
    if not request.user.is_iomete_staff:
        if organization.id not in request.user.organization_ids():
            get_object_or_404(Organization, id=None)  # deliberate 404
    return organization


@extend_schema(
    tags=["analytics"],
    summary="Support-effectiveness dashboard",
    description=(
        "Live metrics computed from database rows at request time. There are no stored "
        "aggregates and no hardcoded figures.\n\n"
        "Each metric reports `window`, `sample_size`, `basis` (how it was derived) and "
        "`confidence`:\n\n"
        "* `measured` — computed from enough rows to mean something.\n"
        "* `estimated` — derived through a stated model. `estimated_fde_hours_saved` is the "
        "notable one: it is genuinely useful and genuinely a model, so it is labelled as "
        "such and its derivation is published.\n"
        "* `insufficient_data` — fewer than five underlying rows, so the value is null "
        "rather than a precise-looking number computed from three tickets.\n\n"
        "Tenant-scoped: a customer sees only their own organization's figures."
    ),
    parameters=[_WINDOW_PARAM, _ORG_PARAM],
    responses={200: OpenApiTypes.OBJECT},
)
class DashboardView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request) -> Response:
        return Response(
            metrics.dashboard(
                request.user,
                window=_window(request),
                organization=_organization(request),
            )
        )


@extend_schema(
    tags=["fde"],
    summary="FDE command-center dashboard",
    description=(
        "The dashboard plus the knowledge-lifecycle funnel and playbook effectiveness, in "
        "one call — the FDE overview needs all three and a single request keeps the page "
        "fast."
    ),
    parameters=[_WINDOW_PARAM, _ORG_PARAM],
    responses={200: OpenApiTypes.OBJECT},
)
class FdeDashboardView(APIView):
    permission_classes = [IsIometeStaff]

    def get(self, request) -> Response:
        window = _window(request)
        organization = _organization(request)
        return Response(
            {
                **metrics.dashboard(request.user, window=window, organization=organization),
                "knowledge_lifecycle": metrics.knowledge_lifecycle(request.user),
                "playbook_effectiveness": metrics.playbook_effectiveness(request.user),
                "trends": metrics.trends(request.user, window="90d", organization=organization),
            }
        )


@extend_schema(
    tags=["analytics"],
    summary="Ticket trends over time",
    description=(
        "Weekly buckets. Weekly rather than daily because daily counts at realistic support "
        "volumes are noise, and a chart that looks precise but is not is worse than a "
        "coarser one that is."
    ),
    parameters=[_WINDOW_PARAM, _ORG_PARAM],
    responses={200: OpenApiTypes.OBJECT},
)
class TrendsView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request) -> Response:
        return Response(
            metrics.trends(
                request.user,
                window=_window(request, "90d"),
                organization=_organization(request),
            )
        )


@extend_schema(
    tags=["analytics"],
    summary="Breakdowns by component, category and severity",
    description=(
        "Distributions with resolution outcomes per group. Rates are null where the "
        "denominator is zero rather than reported as 0%."
    ),
    parameters=[_WINDOW_PARAM, _ORG_PARAM],
    responses={200: OpenApiTypes.OBJECT},
)
class BreakdownsView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request) -> Response:
        return Response(
            metrics.breakdowns(
                request.user,
                window=_window(request, "90d"),
                organization=_organization(request),
            )
        )


@extend_schema(
    tags=["analytics"],
    summary="Playbook effectiveness",
    description=(
        "Per-playbook usage and outcomes. `success_rate` is null for an untested playbook — "
        "'never run' and 'never works' are different findings, and conflating them would "
        "mislead the FDE deciding what to review."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class PlaybookEffectivenessView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request) -> Response:
        return Response(metrics.playbook_effectiveness(request.user))


@extend_schema(
    tags=["analytics"],
    summary="Knowledge-compounding funnel",
    description=(
        "The loop as a funnel: resolved → verified → drafted → approved → **reused**.\n\n"
        "The last stage is the one that matters. A library of approved playbooks nobody has "
        "used is not knowledge compounding, and this funnel is designed to make that "
        "visible rather than to flatter the product."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class KnowledgeLifecycleView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request) -> Response:
        return Response(metrics.knowledge_lifecycle(request.user))


@extend_schema(
    tags=["analytics"],
    summary="How these metrics are computed",
    description="The methodology, served separately so it can be linked from anywhere.",
    responses={200: OpenApiTypes.OBJECT},
)
class MethodologyView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, _request) -> Response:
        return Response(metrics.methodology())

"""
Tenant management API.

`Organization` itself lives in `accounts.models` because `common.models.TenantOwnedModel`
depends on it and a circular app dependency would be worse than a slightly surprising
location. This app is a pure API layer over it: serializers, views, urls, no models.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Membership, Organization
from accounts.serializers import MembershipSerializer
from common.audit import record_audit
from common.permissions import (
    IsAuthenticatedAndActive,
    IsIometeStaff,
    IsOrganizationAdminOrStaff,
)


class OrganizationSerializer(serializers.ModelSerializer):
    # Method fields rather than `IntegerField(read_only=True)`: the queryset annotates
    # these, and an annotation whose alias matches a model property raises
    # "property has no setter" when Django tries to assign it to the instance. Reading the
    # annotation when present and falling back to the property keeps both paths working.
    member_count = serializers.SerializerMethodField()
    open_ticket_count = serializers.SerializerMethodField()
    assigned_fde_name = serializers.CharField(
        source="assigned_fde.full_name", read_only=True, default=None
    )

    def get_member_count(self, obj) -> int:
        annotated = getattr(obj, "active_member_count", None)
        if annotated is not None:
            return annotated
        return obj.memberships.filter(is_active=True).count()

    def get_open_ticket_count(self, obj) -> int:
        annotated = getattr(obj, "open_tickets_count", None)
        if annotated is not None:
            return annotated
        return obj.tickets.exclude(status__in=["resolved", "closed"]).count()

    class Meta:
        model = Organization
        fields = (
            "id", "name", "slug", "industry", "region", "employee_band",
            "deployment_model", "cloud_provider", "iomete_version", "environment_label",
            "kubernetes_distribution", "object_storage", "support_tier",
            "assigned_fde", "assigned_fde_name", "data_residency_requirement",
            "notes", "is_active", "is_synthetic", "member_count", "open_ticket_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "member_count", "open_ticket_count", "assigned_fde_name",
                            "is_synthetic", "created_at", "updated_at")


class CustomerOrganizationSerializer(OrganizationSerializer):
    """
    What a customer may see about their own organization.

    `notes` and `assigned_fde` are internal vendor context, so they are withheld.
    """

    class Meta(OrganizationSerializer.Meta):
        fields = tuple(
            f for f in OrganizationSerializer.Meta.fields
            if f not in {"notes", "assigned_fde", "assigned_fde_name", "support_tier"}
        )
        read_only_fields = fields


@extend_schema_view(
    list=extend_schema(
        tags=["organizations"],
        summary="List organizations",
        description=(
            "IOMETE staff see every tenant. A customer sees only the organizations they "
            "are a member of, with internal vendor fields withheld."
        ),
    ),
    retrieve=extend_schema(tags=["organizations"], summary="Retrieve an organization"),
    create=extend_schema(tags=["organizations"], summary="Create an organization (IOMETE staff)"),
    partial_update=extend_schema(tags=["organizations"], summary="Update an organization"),
)
class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticatedAndActive]
    filterset_fields = ("deployment_model", "cloud_provider", "support_tier", "is_active")
    search_fields = ("name", "slug", "industry", "region")
    ordering_fields = ("name", "created_at")

    def get_permissions(self):
        if self.action in {"create"}:
            return [IsIometeStaff()]
        if self.action in {"update", "partial_update"}:
            return [IsOrganizationAdminOrStaff()]
        return [IsAuthenticatedAndActive()]

    def get_serializer_class(self):
        if self.request.user.is_authenticated and not self.request.user.is_iomete_staff:
            return CustomerOrganizationSerializer
        return OrganizationSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Organization.objects.none()
        base = (
            Organization.objects.select_related("assigned_fde")
            .annotate(
                active_member_count=Count(
                    "memberships", filter=Q(memberships__is_active=True), distinct=True
                ),
                open_tickets_count=Count(
                    "tickets",
                    filter=~Q(tickets__status__in=["resolved", "closed"]),
                    distinct=True,
                ),
            )
        )
        if user.is_iomete_staff:
            return base
        return base.filter(id__in=user.organization_ids())

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.save()
        record_audit(
            action="organization.created",
            actor=self.request.user,
            organization=organization,
            target_type="organization",
            target_id=str(organization.id),
            summary=f"Created organization {organization.name}",
        )

    @transaction.atomic
    def perform_update(self, serializer):
        organization = serializer.save()
        record_audit(
            action="organization.updated",
            actor=self.request.user,
            organization=organization,
            target_type="organization",
            target_id=str(organization.id),
            summary=f"Updated organization {organization.name}",
            metadata={"changed_fields": sorted(serializer.validated_data.keys())},
        )

    @extend_schema(
        tags=["organizations"],
        summary="List an organization's members",
        responses={200: MembershipSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        organization = self.get_object()
        if not request.user.is_iomete_staff and not request.user.has_membership_role(
            "admin", organization_id=organization.id
        ):
            # A non-admin member can see that the organization exists but not enumerate
            # colleagues' roles.
            memberships = Membership.objects.filter(
                organization=organization, user=request.user, is_active=True
            )
        else:
            memberships = Membership.objects.filter(
                organization=organization, is_active=True
            ).select_related("user")
        return Response(MembershipSerializer(memberships, many=True).data)

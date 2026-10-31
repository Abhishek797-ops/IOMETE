"""Auth, user and audit endpoints. Views stay thin; rules live in services/identity.py."""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from common.permissions import (
    IsAuthenticatedAndActive,
    IsIometeStaff,
    IsPlatformAdmin,
)

from .models import AuditLog, Membership, User
from .serializers import (
    AdminUserWriteSerializer,
    AuditLogSerializer,
    DemoAccountSerializer,
    LoginSerializer,
    LogoutSerializer,
    MembershipSerializer,
    TokenPairSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .services import identity


@extend_schema(
    tags=["auth"],
    summary="Sign in",
    description=(
        "Exchange an email and password for a JWT access/refresh pair plus the current "
        "user. Failed attempts are rate-limited and audited."
    ),
    request=LoginSerializer,
    responses={200: TokenPairSerializer},
)
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pair = identity.login(**serializer.validated_data)
        return Response(
            {
                "access": pair.access,
                "refresh": pair.refresh,
                "user": UserSerializer(pair.user).data,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["auth"],
    summary="Refresh an access token",
    description="Exchange a refresh token for a new access token. Refresh tokens rotate.",
)
class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"


@extend_schema(
    tags=["auth"],
    summary="Sign out",
    description="Blacklists the supplied refresh token so it cannot be reused.",
    request=LogoutSerializer,
    responses={204: None},
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity.logout(user=request.user, refresh_token=serializer.validated_data["refresh"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class MeView(APIView):
    """The authenticated user, including organization memberships and effective roles."""

    permission_classes = [IsAuthenticatedAndActive]

    @extend_schema(summary="Current user", responses={200: UserSerializer})
    def get(self, request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(
        summary="Update own profile",
        description="Name, job title and timezone only. Roles cannot be self-assigned.",
        request=UserUpdateSerializer,
        responses={200: UserSerializer},
    )
    def patch(self, request) -> Response:
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


@extend_schema(
    tags=["auth"],
    summary="List seeded demo accounts",
    description=(
        "Returns the synthetic local-development logins created by `manage.py seed_demo`, "
        "so the sign-in screen can offer one-click role switching during a demo.\n\n"
        "Returns an empty list unless `COMPASS_DEMO_MODE` is enabled, and only ever "
        "includes accounts explicitly flagged as synthetic. A production deployment "
        "therefore cannot publish a working credential list through this endpoint."
    ),
    responses={200: DemoAccountSerializer(many=True)},
)
class DemoAccountsView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, _request) -> Response:
        return Response(
            {
                "demo_mode": settings.COMPASS_DEMO_MODE,
                "accounts": DemoAccountSerializer(identity.list_demo_accounts(), many=True).data,
            }
        )


@extend_schema_view(
    list=extend_schema(tags=["auth"], summary="List users (platform admin)"),
    retrieve=extend_schema(tags=["auth"], summary="Retrieve a user (platform admin)"),
    create=extend_schema(tags=["auth"], summary="Create a user (platform admin)"),
    partial_update=extend_schema(tags=["auth"], summary="Update a user (platform admin)"),
)
class UserAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    User and role management.

    Restricted to `platform_admin`. Role changes and deactivation go through the service
    so the last-admin guards and audit writes cannot be bypassed.
    """

    permission_classes = [IsPlatformAdmin]
    queryset = User.objects.all().prefetch_related("memberships__organization")
    search_fields = ("email", "full_name", "job_title")
    ordering_fields = ("full_name", "email", "created_at", "last_seen_at")
    filterset_fields = ("system_role", "is_active")

    def get_serializer_class(self):
        if self.action in {"create", "partial_update", "update"}:
            return AdminUserWriteSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = AdminUserWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = identity.create_user(actor=request.user, **serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["auth"],
        summary="Change a user's system role",
        request=None,
        parameters=[
            OpenApiParameter(
                "role", str, OpenApiParameter.QUERY, required=True,
                description="customer | fde | fde_lead | platform_admin",
            )
        ],
        responses={200: UserSerializer},
    )
    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        user = self.get_object()
        new_role = request.data.get("role") or request.query_params.get("role")
        updated = identity.change_system_role(actor=request.user, user=user, new_role=new_role)
        return Response(UserSerializer(updated).data)

    @extend_schema(
        tags=["auth"], summary="Deactivate a user", request=None, responses={200: UserSerializer}
    )
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        return Response(UserSerializer(identity.deactivate_user(actor=request.user, user=user)).data)


@extend_schema_view(
    list=extend_schema(tags=["organizations"], summary="List memberships"),
    create=extend_schema(tags=["organizations"], summary="Add a user to an organization"),
    destroy=extend_schema(tags=["organizations"], summary="Remove a membership"),
)
class MembershipViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Membership management.

    IOMETE staff manage any organization's memberships. A customer organization admin
    manages only their own organization's — enforced by the queryset *and* by the explicit
    organization check in `perform_create`.
    """

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticatedAndActive]
    filterset_fields = ("organization", "role", "is_active")

    def get_queryset(self):
        user = self.request.user
        base = Membership.objects.select_related("user", "organization")
        if not user.is_authenticated:
            # Reached only by schema generation; real requests are blocked by permissions.
            return base.none()
        if user.is_iomete_staff:
            return base
        # A customer may see memberships of organizations they administer; a non-admin
        # member sees only their own row.
        admin_org_ids = [
            m.organization_id
            for m in user.memberships.filter(is_active=True, role="admin")
        ]
        return base.filter(Q(organization_id__in=admin_org_ids) | Q(user=user))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = serializer.validated_data["organization"]
        target_user = serializer.validated_data["user"]

        if not request.user.is_iomete_staff and not request.user.has_membership_role(
            "admin", organization_id=organization.id
        ):
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "You must be an administrator of that organization to add members.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        membership = identity.add_membership(
            actor=request.user,
            user=target_user,
            organization=organization,
            role=serializer.validated_data.get("role", "viewer"),
        )
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["organizations"], summary="Change a membership role", request=None,
        responses={200: MembershipSerializer},
    )
    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        membership = self.get_object()
        if not request.user.is_iomete_staff and not request.user.has_membership_role(
            "admin", organization_id=membership.organization_id
        ):
            return Response(
                {
                    "error": {
                        "code": "permission_denied",
                        "message": "Only an administrator of that organization can change roles.",
                        "details": {},
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        updated = identity.change_membership_role(
            actor=request.user, membership=membership, new_role=request.data.get("role")
        )
        return Response(MembershipSerializer(updated).data)

    def perform_destroy(self, instance):
        if not self.request.user.is_iomete_staff and not self.request.user.has_membership_role(
            "admin", organization_id=instance.organization_id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only an administrator of that organization can remove members.")
        identity.remove_membership(actor=self.request.user, membership=instance)


@extend_schema_view(
    list=extend_schema(
        tags=["auth"],
        summary="Audit history",
        description=(
            "Append-only audit trail. IOMETE staff see every tenant's entries; a customer "
            "organization administrator sees only their own organization's."
        ),
    )
)
class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticatedAndActive]
    filterset_fields = ("action", "organization", "target_type", "actor")
    search_fields = ("summary", "actor_label", "target_id")
    ordering_fields = ("created_at", "action")

    def get_queryset(self):
        user = self.request.user
        base = AuditLog.objects.select_related("actor", "organization")
        if not user.is_authenticated:
            return base.none()
        if user.is_iomete_staff:
            return base
        admin_org_ids = [
            m.organization_id for m in user.memberships.filter(is_active=True, role="admin")
        ]
        if not admin_org_ids:
            # A non-admin customer sees only their own actions — enough to answer "what
            # did I do", without exposing colleagues' activity.
            return base.filter(actor=user)
        return base.filter(organization_id__in=admin_org_ids)


@extend_schema(tags=["auth"], summary="List FDE users", responses={200: UserSerializer(many=True)})
class FdeDirectoryView(APIView):
    """
    FDE directory, for ticket assignment dropdowns.

    Restricted to IOMETE staff: a customer has no legitimate need for a list of the
    vendor's engineers.
    """

    permission_classes = [IsIometeStaff]

    def get(self, _request) -> Response:
        users = User.objects.filter(
            system_role__in=["fde", "fde_lead"], is_active=True
        ).order_by("full_name")
        return Response(UserSerializer(users, many=True).data)

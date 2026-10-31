"""Serializers for identity, membership and audit."""

from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AuditLog, Membership, MembershipRole, Organization, SystemRole, User


class MembershipBriefSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    organization_slug = serializers.SlugField(source="organization.slug", read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "organization_id", "organization_name", "organization_slug",
                  "role", "is_default")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """
    Read serializer for a user.

    Explicit field list — never `__all__`. `password`, `is_superuser` and the permission
    m2m fields must not leave the server.
    """

    memberships = MembershipBriefSerializer(many=True, read_only=True)
    is_iomete_staff = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "email", "full_name", "job_title", "system_role", "is_iomete_staff",
            "avatar_initials", "timezone_name", "is_active", "last_seen_at",
            "memberships", "is_synthetic", "created_at",
        )
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile edit. Deliberately cannot touch `system_role` or `is_active`."""

    class Meta:
        model = User
        fields = ("full_name", "job_title", "timezone_name")


class AdminUserWriteSerializer(serializers.ModelSerializer):
    """
    Platform-admin user management.

    `system_role` *is* writable here — that is the point of the endpoint — but the view
    guards it with `IsPlatformAdmin` and the service refuses self-demotion of the last
    platform admin.
    """

    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = User
        fields = ("email", "full_name", "job_title", "system_role", "is_active", "password")

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_system_role(self, value: str) -> str:
        if value not in dict(SystemRole.choices):
            raise serializers.ValidationError("Unknown system role.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class MembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Membership
        fields = (
            "id", "user", "user_email", "user_full_name", "organization",
            "organization_name", "role", "is_default", "is_active", "created_at",
        )
        read_only_fields = ("id", "user_email", "user_full_name", "organization_name", "created_at")

    def validate_role(self, value: str) -> str:
        if value not in dict(MembershipRole.choices):
            raise serializers.ValidationError("Unknown membership role.")
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class TokenPairSerializer(serializers.Serializer):
    """Documentation-only shape for the login response."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        help_text="The refresh token to blacklist. Without it the token stays valid until expiry."
    )


class DemoAccountSerializer(serializers.Serializer):
    """
    A seeded local development login.

    Only returned when `COMPASS_DEMO_MODE` is on and the account is flagged synthetic, so
    a real deployment cannot accidentally publish a credential list.
    """

    email = serializers.EmailField()
    password = serializers.CharField()
    full_name = serializers.CharField()
    system_role = serializers.CharField()
    organization = serializers.CharField(allow_null=True)
    description = serializers.CharField()


class AuditLogSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = (
            "id", "action", "actor", "actor_label", "organization", "organization_name",
            "target_type", "target_id", "summary", "metadata", "request_id",
            "ip_address", "created_at",
        )
        read_only_fields = fields


class OrganizationBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "deployment_model", "cloud_provider", "iomete_version")
        read_only_fields = fields

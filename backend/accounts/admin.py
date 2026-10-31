from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, Membership, Organization, User


class MembershipInline(admin.TabularInline):
    model = Membership
    # Membership has two FKs to User (`user` and `invited_by`); name the one we mean.
    fk_name = "user"
    extra = 0
    autocomplete_fields = ("organization",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "system_role", "is_active", "is_synthetic", "last_seen_at")
    list_filter = ("system_role", "is_active", "is_synthetic", "is_staff")
    search_fields = ("email", "full_name", "job_title")
    ordering = ("full_name",)
    inlines = (MembershipInline,)
    readonly_fields = ("id", "created_at", "updated_at", "last_seen_at", "avatar_initials")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "job_title", "timezone_name", "avatar_initials")}),
        ("Roles", {"fields": ("system_role", "is_active", "is_staff", "is_superuser",
                              "groups", "user_permissions")}),
        ("Metadata", {"fields": ("id", "is_synthetic", "last_seen_at", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "system_role", "password1", "password2"),
        }),
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "deployment_model", "cloud_provider", "iomete_version",
                    "support_tier", "is_active", "is_synthetic")
    list_filter = ("deployment_model", "cloud_provider", "support_tier", "is_active", "is_synthetic")
    search_fields = ("name", "slug", "industry", "region")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("assigned_fde",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "is_default")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "organization__name")
    autocomplete_fields = ("user", "organization", "invited_by")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_label", "organization", "target_type", "summary")
    list_filter = ("action", "organization")
    search_fields = ("summary", "actor_label", "target_id", "request_id")
    readonly_fields = tuple(f.name for f in AuditLog._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # The audit trail is append-only. Deleting entries defeats its purpose.
        return False

from django.contrib import admin

from .models import IntegrationConfiguration, IntegrationSyncRun


class SyncRunInline(admin.TabularInline):
    model = IntegrationSyncRun
    extra = 0
    fields = ("started_at", "direction", "status", "records_created", "records_updated",
              "records_failed", "was_simulated", "error_code")
    readonly_fields = fields
    can_delete = False


@admin.register(IntegrationConfiguration)
class IntegrationConfigurationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "provider", "organization", "mode", "is_enabled",
                    "last_connection_ok", "last_sync_at")
    list_filter = ("provider", "mode", "is_enabled")
    search_fields = ("display_name", "provider")
    autocomplete_fields = ("organization", "created_by")
    inlines = (SyncRunInline,)
    # `credentials` is excluded from the admin entirely. The admin renders field values,
    # and this one holds decrypted secrets — there is no safe way to show it.
    exclude = ("credentials",)
    readonly_fields = ("mode", "last_connection_test_at", "last_connection_ok",
                       "last_connection_message", "connection_detail", "last_sync_at",
                       "last_sync_status", "credential_keys_display")

    @admin.display(description="Credential keys on file")
    def credential_keys_display(self, obj):
        return ", ".join(obj.credential_keys) or "(none)"


@admin.register(IntegrationSyncRun)
class IntegrationSyncRunAdmin(admin.ModelAdmin):
    list_display = ("integration", "direction", "status", "started_at", "records_created",
                    "records_updated", "records_failed", "was_simulated")
    list_filter = ("status", "direction", "was_simulated")
    readonly_fields = tuple(f.name for f in IntegrationSyncRun._meta.fields)

    def has_add_permission(self, request):
        return False

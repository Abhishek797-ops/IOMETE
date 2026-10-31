from django.contrib import admin

from .models import LakehouseQueryRun


@admin.register(LakehouseQueryRun)
class LakehouseQueryRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "mode", "succeeded", "row_count", "duration_ms",
                    "sample_query_id", "organization")
    list_filter = ("mode", "succeeded", "error_code")
    search_fields = ("sql", "session_key", "sample_query_id")
    readonly_fields = tuple(f.name for f in LakehouseQueryRun._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

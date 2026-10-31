from django.contrib import admin

from .models import (
    ErrorFingerprint,
    IssueCluster,
    SimilarityMatch,
    Ticket,
    TicketAttachment,
    TicketEvent,
)


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    fields = ("created_at", "event_type", "author_label", "is_internal", "body")
    readonly_fields = fields
    can_delete = False
    show_change_link = False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "organization", "component", "severity", "status",
                    "resolution_verified", "self_service_resolved", "is_synthetic", "created_at")
    list_filter = ("status", "severity", "component", "category", "resolution_verified",
                   "self_service_resolved", "is_synthetic", "organization")
    search_fields = ("reference", "title", "description", "error_message")
    date_hierarchy = "created_at"
    autocomplete_fields = ("organization", "reporter", "assigned_fde", "cluster")
    readonly_fields = ("normalized", "search_text", "embedding_model", "embedding_dim",
                       "embedded_at", "redaction_summary", "fingerprint")
    inlines = (TicketEventInline,)
    # `embedding` is excluded: a 384-float list renders as an unusable wall of numbers.
    exclude = ("embedding",)


@admin.register(IssueCluster)
class IssueClusterAdmin(admin.ModelAdmin):
    list_display = ("title", "component", "status", "is_root_cause_confirmed", "is_synthetic",
                    "updated_at")
    list_filter = ("status", "component", "category", "is_root_cause_confirmed")
    search_fields = ("title", "key", "description")
    prepopulated_fields = {"key": ("title",)}
    autocomplete_fields = ("owner",)
    filter_horizontal = ("fingerprints",)


@admin.register(ErrorFingerprint)
class ErrorFingerprintAdmin(admin.ModelAdmin):
    list_display = ("digest", "component", "occurrence_count", "distinct_organization_count",
                    "last_seen_at")
    list_filter = ("component",)
    search_fields = ("digest", "signature")
    readonly_fields = tuple(f.name for f in ErrorFingerprint._meta.fields)


@admin.register(SimilarityMatch)
class SimilarityMatchAdmin(admin.ModelAdmin):
    list_display = ("ticket", "matched_ticket", "rank", "similarity_score",
                    "diagnosis_confidence", "resolution_confidence", "gate_status")
    list_filter = ("gate_status", "retrieval_backend")
    readonly_fields = tuple(f.name for f in SimilarityMatch._meta.fields)


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "ticket", "content_type", "size_bytes",
                    "redaction_applied", "is_internal", "created_at")
    list_filter = ("redaction_applied", "is_internal", "content_type")
    readonly_fields = ("checksum_sha256", "redaction_summary", "size_bytes")

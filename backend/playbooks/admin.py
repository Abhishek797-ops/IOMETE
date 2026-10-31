from django.contrib import admin

from .models import (
    KnowledgeApproval,
    PlaybookExecution,
    PlaybookStep,
    PlaybookStepResponse,
    ResolutionPlaybook,
)


class PlaybookStepInline(admin.TabularInline):
    model = PlaybookStep
    extra = 0
    fields = ("order", "key", "title", "step_type", "risk_level", "branches", "is_terminal")
    ordering = ("order",)


@admin.register(ResolutionPlaybook)
class ResolutionPlaybookAdmin(admin.ModelAdmin):
    list_display = ("playbook_id", "version", "title", "component", "risk_level",
                    "approval_status", "is_shared", "usage_count", "success_count",
                    "is_synthetic")
    list_filter = ("approval_status", "component", "category", "risk_level", "is_shared",
                   "is_synthetic")
    search_fields = ("playbook_id", "title", "description", "confirmed_root_cause")
    autocomplete_fields = ("approved_by", "created_by", "source_ticket",
                           "origin_organization", "cluster", "supersedes")
    filter_horizontal = ("fingerprints",)
    inlines = (PlaybookStepInline,)
    readonly_fields = ("search_text", "embedding_model", "embedding_dim", "usage_count",
                       "success_count", "failure_count")
    exclude = ("embedding",)


class StepResponseInline(admin.TabularInline):
    model = PlaybookStepResponse
    extra = 0
    fields = ("sequence", "step", "response_value", "observation", "matched_expectation",
              "completed_by", "approval_granted_by", "next_step_key")
    readonly_fields = fields
    can_delete = False


@admin.register(PlaybookExecution)
class PlaybookExecutionAdmin(admin.ModelAdmin):
    list_display = ("ticket", "playbook", "playbook_version", "status", "organization",
                    "completed_at")
    list_filter = ("status", "organization")
    search_fields = ("ticket__reference", "playbook__playbook_id")
    autocomplete_fields = ("ticket", "playbook", "started_by", "organization")
    inlines = (StepResponseInline,)
    readonly_fields = ("path", "diagnostic_summary", "duration_seconds")


@admin.register(KnowledgeApproval)
class KnowledgeApprovalAdmin(admin.ModelAdmin):
    list_display = ("playbook", "playbook_version", "decision", "reviewer_label", "created_at")
    list_filter = ("decision",)
    search_fields = ("playbook__playbook_id", "reviewer_label", "notes")
    readonly_fields = tuple(f.name for f in KnowledgeApproval._meta.fields)

    def has_change_permission(self, request, obj=None):
        # The review trail is the evidence that knowledge was reviewed. It is append-only.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

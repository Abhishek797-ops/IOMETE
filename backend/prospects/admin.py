from django.contrib import admin

from .models import ArchitectureRecommendation, DemoRequest, FitAssessment, ProspectProfile


@admin.register(ProspectProfile)
class ProspectProfileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "company_type", "infrastructure_location", "data_volume",
                    "sovereignty_requirement", "consent_given", "source", "created_at")
    list_filter = ("company_type", "infrastructure_location", "data_volume",
                   "sovereignty_requirement", "consent_given", "source", "is_synthetic")
    search_fields = ("company_name", "contact_email", "contact_name")
    readonly_fields = ("consent_text", "consent_at")
    date_hierarchy = "created_at"


@admin.register(FitAssessment)
class FitAssessmentAdmin(admin.ModelAdmin):
    list_display = ("prospect", "band", "indicative_score", "rubric_version", "created_at")
    list_filter = ("band", "rubric_version", "is_synthetic")
    search_fields = ("prospect__company_name", "prospect__contact_email")
    readonly_fields = ("answers", "rubric", "technical_requirements", "advantages", "gaps",
                       "questions_for_sales", "cited_sources", "disclaimer")
    autocomplete_fields = ("prospect",)


@admin.register(ArchitectureRecommendation)
class ArchitectureRecommendationAdmin(admin.ModelAdmin):
    list_display = ("title", "prospect", "assessment", "created_at")
    search_fields = ("title", "prospect__company_name")
    readonly_fields = ("nodes", "edges", "layers", "inputs", "integration_notes",
                       "open_questions", "cited_sources")


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ("prospect", "status", "assessment", "handled_by", "created_at")
    list_filter = ("status", "is_synthetic")
    search_fields = ("prospect__company_name", "prospect__contact_email", "message")
    autocomplete_fields = ("prospect", "handled_by")
    date_hierarchy = "created_at"

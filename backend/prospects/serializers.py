"""
Prospect-side serializers.

Privacy shape: the Fit Finder is usable anonymously. Contact fields are optional and only
requested when the prospect wants a report or a demo, and consent is captured with the
exact wording that was shown.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    ArchitectureRecommendation,
    CompanyType,
    CurrentArchitecture,
    DataVolume,
    DemoRequest,
    DemoRequestStatus,
    FitAssessment,
    InfrastructureLocation,
    ProspectProfile,
    SovereigntyRequirement,
    UseCase,
)

CONSENT_TEXT = (
    "I agree that IOMETE may contact me about this enquiry. My answers will be used to "
    "prepare an indicative assessment and architecture recommendation."
)


class FitAnswersSerializer(serializers.Serializer):
    """
    The ten discovery questions.

    Only `company_type`, `infrastructure_location` and `primary_use_case` have practical
    defaults; everything else is optional so a prospect can give a partial picture and
    still get something useful. The rubric handles missing data by capping the band at
    "needs discussion" rather than guessing — which is the honest behaviour.
    """

    # 1
    company_type = serializers.ChoiceField(
        choices=CompanyType.choices, default=CompanyType.OTHER
    )
    company_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    # 2
    contact_role = serializers.CharField(max_length=150, required=False, allow_blank=True)
    persona = serializers.CharField(max_length=40, required=False, allow_blank=True)
    # 3
    infrastructure_location = serializers.ChoiceField(
        choices=InfrastructureLocation.choices, default=InfrastructureLocation.UNDECIDED
    )
    cloud_providers = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list
    )
    # 4
    current_systems = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, default=list,
        help_text="Databases, storage and warehouses you use today.",
    )
    bi_tools = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, default=list,
        help_text="BI and analysis tools that must keep working.",
    )
    # 5
    data_volume = serializers.ChoiceField(
        choices=DataVolume.choices, default=DataVolume.UNKNOWN
    )
    # 6
    primary_use_case = serializers.ChoiceField(choices=UseCase.choices, default=UseCase.OTHER)
    secondary_use_cases = serializers.ListField(
        child=serializers.ChoiceField(choices=UseCase.choices), required=False, default=list
    )
    # 7
    sovereignty_requirement = serializers.ChoiceField(
        choices=SovereigntyRequirement.choices, default=SovereigntyRequirement.UNKNOWN
    )
    # 8
    challenges = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list,
        help_text="e.g. cost, vendor_lock_in, data_residency, performance, governance, "
        "data_silos, scaling, compliance, slow_queries, duplicate_copies",
    )
    # 9
    current_architecture = serializers.ChoiceField(
        choices=CurrentArchitecture.choices, default=CurrentArchitecture.NONE
    )
    # 10
    constraints = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list,
        help_text="e.g. tight_timeline, limited_budget, small_team, procurement_process",
    )
    kubernetes_maturity = serializers.CharField(
        max_length=40, required=False, allow_blank=True,
        help_text="none | basic | some | advanced | production",
    )
    team_size = serializers.CharField(max_length=40, required=False, allow_blank=True)


class FitAssessmentRequestSerializer(serializers.Serializer):
    answers = FitAnswersSerializer()
    contact_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    consent_given = serializers.BooleanField(default=False)

    def validate(self, attrs):
        """
        Consent is required *only* when contact details are supplied.

        An anonymous assessment collects nothing to consent about, and demanding a
        tick-box for it would be theatre.
        """
        has_contact = bool(attrs.get("contact_email") or attrs.get("contact_name"))
        if has_contact and not attrs.get("consent_given"):
            raise serializers.ValidationError(
                {
                    "consent_given": (
                        "Please confirm you agree to be contacted, or remove your contact "
                        "details — the assessment works anonymously."
                    )
                }
            )
        return attrs


class ProspectProfileSerializer(serializers.ModelSerializer):
    company_type_label = serializers.CharField(source="get_company_type_display", read_only=True)
    is_identified = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProspectProfile
        fields = (
            "id", "company_name", "contact_name", "contact_email", "contact_role",
            "persona", "company_type", "company_type_label", "infrastructure_location",
            "cloud_providers", "current_systems", "data_volume", "primary_use_case",
            "secondary_use_cases", "sovereignty_requirement", "challenges",
            "current_architecture", "constraints", "kubernetes_maturity", "team_size",
            "consent_given", "consent_at", "source", "is_identified", "is_synthetic",
            "created_at",
        )
        read_only_fields = fields


class FitAssessmentSerializer(serializers.ModelSerializer):
    band_label = serializers.CharField(source="get_band_display", read_only=True)
    band_explanation = serializers.SerializerMethodField()
    score_caveat = serializers.SerializerMethodField()
    cited_source_detail = serializers.SerializerMethodField()

    class Meta:
        model = FitAssessment
        fields = (
            "id", "prospect", "rubric_version", "indicative_score", "band", "band_label",
            "band_explanation", "score_caveat", "rubric", "requirement_summary",
            "suitability_reasons", "technical_requirements", "advantages", "gaps",
            "questions_for_sales", "caps_applied", "next_step", "cited_sources",
            "cited_source_detail",
            "disclaimer", "generated_by", "is_synthetic", "created_at",
        )
        read_only_fields = fields

    def get_band_explanation(self, obj) -> str:
        from .services.fit import BAND_EXPLANATIONS

        return BAND_EXPLANATIONS.get(obj.band, "")

    def get_score_caveat(self, _obj) -> str:
        """
        Travels with every assessment so a client cannot render the number bare.

        The brief forbids misleading compatibility percentages; this is the sentence that
        keeps `indicative_score` honest wherever it appears.
        """
        return (
            "This score is an ordering aid, not a compatibility percentage. It is the sum "
            "of the seven weighted dimensions shown in the rubric, each with its reasoning. "
            "The band is the meaningful output; read the gaps and open questions before "
            "drawing any conclusion."
        )

    def get_cited_source_detail(self, obj) -> list[dict]:
        from knowledge.services.product_knowledge import resolve_sources

        return resolve_sources(obj.cited_sources)


class ArchitectureRecommendationSerializer(serializers.ModelSerializer):
    cited_source_detail = serializers.SerializerMethodField()

    class Meta:
        model = ArchitectureRecommendation
        fields = (
            "id", "prospect", "assessment", "title", "inputs", "nodes", "edges",
            "layers", "narrative", "integration_notes", "open_questions",
            "conceptual_disclaimer", "cited_sources", "cited_source_detail",
            "is_synthetic", "created_at",
        )
        read_only_fields = fields

    def get_cited_source_detail(self, obj) -> list[dict]:
        from knowledge.services.product_knowledge import resolve_sources

        return resolve_sources(obj.cited_sources)


class ArchitectureRequestSerializer(serializers.Serializer):
    """Generate a recommendation without going through the full Fit Finder."""

    answers = FitAnswersSerializer()
    assessment = serializers.UUIDField(required=False, allow_null=True)


class DemoRequestCreateSerializer(serializers.Serializer):
    contact_name = serializers.CharField(max_length=200)
    contact_email = serializers.EmailField()
    company_name = serializers.CharField(max_length=200)
    contact_role = serializers.CharField(max_length=150, required=False, allow_blank=True)
    message = serializers.CharField(required=False, allow_blank=True)
    preferred_timeframe = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    interests = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list
    )
    assessment = serializers.UUIDField(
        required=False, allow_null=True,
        help_text="Attach a completed fit assessment. This is what makes the request a "
        "qualified lead rather than a form fill — the sales engineer arrives knowing the "
        "prospect's environment, constraints and open questions.",
    )
    prospect = serializers.UUIDField(required=False, allow_null=True)
    consent_given = serializers.BooleanField()

    def validate_consent_given(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "We need your agreement to be contacted before we can pass this to the "
                "sales team."
            )
        return value


class DemoRequestSerializer(serializers.ModelSerializer):
    """
    What the *prospect* gets back. `internal_notes` and `handled_by` are deliberately absent.
    """

    prospect_detail = ProspectProfileSerializer(source="prospect", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DemoRequest
        fields = (
            "id", "prospect", "prospect_detail", "assessment", "message",
            "preferred_timeframe", "interests", "status", "status_label",
            "is_synthetic", "created_at",
        )
        read_only_fields = fields


class FdeDemoRequestSerializer(DemoRequestSerializer):
    """IOMETE-side view, with the internal fields."""

    assessment_band = serializers.CharField(source="assessment.band", read_only=True, default=None)
    assessment_score = serializers.IntegerField(
        source="assessment.indicative_score", read_only=True, default=None
    )
    handled_by_name = serializers.CharField(
        source="handled_by.full_name", read_only=True, default=None
    )

    class Meta(DemoRequestSerializer.Meta):
        fields = (*DemoRequestSerializer.Meta.fields, "internal_notes", "handled_by", "handled_by_name", "assessment_band", "assessment_score", "updated_at")
        read_only_fields = ("id", "prospect", "prospect_detail", "assessment",
                            "assessment_band", "assessment_score", "created_at",
                            "updated_at", "handled_by_name", "status_label",
                            "is_synthetic")


class DemoRequestUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=DemoRequestStatus.choices, required=False)
    internal_notes = serializers.CharField(required=False, allow_blank=True)


class CallPrepRequestSerializer(serializers.Serializer):
    """
    Inputs for a call brief.

    Only `company_name` is required. Everything else narrows the brief, and whatever is
    left blank shows up in the output as an explicit assumption or unknown rather than
    being quietly filled in — which is the whole point of the feature.
    """

    company_name = serializers.CharField(max_length=200)
    industry = serializers.CharField(max_length=60, required=False, allow_blank=True)
    company_size = serializers.ChoiceField(
        choices=[
            ("small", "Small"),
            ("medium", "Medium"),
            ("large", "Large"),
            ("enterprise", "Enterprise"),
            ("unknown", "Unknown"),
        ],
        required=False,
        allow_blank=True,
    )
    meeting_type = serializers.CharField(max_length=40, required=False, allow_blank=True)
    known_stack = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, default=list
    )
    attendee_personas = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list
    )

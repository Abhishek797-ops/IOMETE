"""
Ticket serializers.

Two families, and the split is a security boundary rather than a convenience:

* `Customer*` serializers withhold internal FDE notes, raw diagnostics belonging to other
  tenants, assignment details and investigation effort.
* `Fde*` serializers expose the full record.

Field lists are always explicit. `fields = "__all__"` on a model that grows a sensitive
column later is a leak waiting to happen, so it appears nowhere in this codebase.
"""

from __future__ import annotations

from rest_framework import serializers

from accounts.serializers import OrganizationBriefSerializer
from aiengine.services.normalization import symptom_label

from .models import (
    Environment,
    ErrorFingerprint,
    IssueCluster,
    Severity,
    SimilarityMatch,
    Ticket,
    TicketAttachment,
    TicketComponent,
    TicketEvent,
    TicketStatus,
)


class TicketCreateSerializer(serializers.Serializer):
    """
    Customer ticket submission.

    A `Serializer` rather than a `ModelSerializer` because intake is not a straight field
    mapping: the service redacts, normalises, fingerprints and embeds, and several model
    fields (`category`, `normalized`, `search_text`, `embedding`) are *derived* and must not
    be settable by a client.
    """

    title = serializers.CharField(max_length=250)
    description = serializers.CharField(
        help_text="What is going wrong. Sensitive values are redacted before storage."
    )
    component = serializers.ChoiceField(
        choices=TicketComponent.choices, default=TicketComponent.OTHER,
        help_text="If you are not sure, leave this as 'other' — COMPASS will infer it.",
    )
    severity = serializers.ChoiceField(choices=Severity.choices, default=Severity.MEDIUM)
    iomete_version = serializers.CharField(
        max_length=32, required=False, allow_blank=True,
        help_text="e.g. 3.19.1. Without it, resolutions cannot be checked for "
        "applicability and will be gated out of recommendations.",
    )
    environment = serializers.ChoiceField(
        choices=Environment.choices, default=Environment.UNKNOWN
    )
    cloud_provider = serializers.CharField(max_length=32, required=False, allow_blank=True)
    kubernetes_distribution = serializers.CharField(
        max_length=80, required=False, allow_blank=True
    )
    error_message = serializers.CharField(
        required=False, allow_blank=True,
        help_text="The verbatim error line. This is the single strongest matching signal.",
    )
    diagnostics = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Sanitised diagnostic output. Credentials are redacted automatically, "
        "but please avoid pasting secrets.",
    )
    organization = serializers.UUIDField(
        required=False,
        help_text="Required only when you belong to more than one organization.",
    )

    def validate_title(self, value: str) -> str:
        if len(value.strip()) < 8:
            raise serializers.ValidationError(
                "Please give the problem a descriptive title — it is used for matching."
            )
        return value.strip()

    def validate_description(self, value: str) -> str:
        if len(value.strip()) < 20:
            raise serializers.ValidationError(
                "Please describe what is happening in a little more detail. Short "
                "descriptions produce poor matches against historical cases."
            )
        return value.strip()


class ErrorFingerprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorFingerprint
        fields = (
            "id", "digest", "error_codes", "component", "occurrence_count",
            "distinct_organization_count", "first_seen_at", "last_seen_at",
        )
        read_only_fields = fields


class TicketEventSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True, default=None)
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = TicketEvent
        fields = (
            "id", "event_type", "event_type_label", "author", "author_name", "author_label",
            "body", "is_internal", "metadata", "created_at",
        )
        read_only_fields = fields


class TicketAttachmentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = (
            "id", "original_name", "content_type", "size_bytes", "redaction_applied",
            "redaction_summary", "is_internal", "created_at", "download_url",
        )
        read_only_fields = fields

    def get_download_url(self, obj) -> str:
        # Served through an authorizing view, never as a direct storage path — a raw media
        # URL would be an unauthenticated read of another tenant's diagnostics.
        return f"/api/v1/tickets/{obj.ticket_id}/attachments/{obj.id}/download/"


class TicketListSerializer(serializers.ModelSerializer):
    """Compact row for list views."""

    component_label = serializers.CharField(source="get_component_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    severity_label = serializers.CharField(source="get_severity_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    symptom_labels = serializers.SerializerMethodField()
    age_hours = serializers.FloatField(read_only=True)
    has_approved_playbook = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id", "reference", "title", "component", "component_label", "category",
            "category_label", "severity", "severity_label", "status", "status_label",
            "iomete_version", "environment", "organization", "organization_name",
            "symptom_labels", "resolution_verified", "self_service_resolved",
            "is_synthetic", "age_hours", "has_approved_playbook",
            "created_at", "resolved_at",
        )
        read_only_fields = fields

    def get_symptom_labels(self, obj) -> list[str]:
        return [symptom_label(s) for s in (obj.normalized or {}).get("symptoms", [])][:4]

    def get_has_approved_playbook(self, obj) -> bool:
        """
        Does an approved playbook already exist for this ticket's problem?

        Drives the FDE inbox's most useful signal: tickets a customer could have resolved
        themselves. Computed from prefetched matches where available to avoid N+1.
        """
        matches = getattr(obj, "_prefetched_objects_cache", {}).get("playbook_matches")
        if matches is not None:
            return any(
                m.gate_status != "gated" and m.playbook.approval_status == "approved"
                for m in matches
            )
        return obj.playbook_matches.filter(
            playbook__approval_status="approved"
        ).exclude(gate_status="gated").exists()


class CustomerTicketSerializer(TicketListSerializer):
    """
    Full ticket as a customer may see it.

    Excludes `assigned_fde` and `fde_investigation_minutes`: who inside IOMETE is working
    on a ticket and how long they spent is internal operational data.
    """

    organization = OrganizationBriefSerializer(read_only=True)
    normalized_summary = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    redaction_notice = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = (*TicketListSerializer.Meta.fields, "description", "error_message", "diagnostics", "redaction_summary", "redaction_notice", "deployment_model", "cloud_provider", "kubernetes_distribution", "normalized_summary", "escalation_reason", "escalated_at", "resolution_summary", "resolution_evidence", "resolution_verified_at", "time_to_resolution_seconds", "events", "attachments", "updated_at")
        read_only_fields = fields

    def get_normalized_summary(self, obj) -> dict:
        normalized = obj.normalized or {}
        return {
            "error_codes": normalized.get("error_codes", [])[:10],
            "symptoms": [
                {"key": s, "label": symptom_label(s)} for s in normalized.get("symptoms", [])
            ],
            "key_phrases": normalized.get("key_phrases", [])[:10],
            "affected_components": normalized.get("affected_components", {}),
            "extracted_version": normalized.get("extracted_version", ""),
            "confidence_note": normalized.get("confidence_note", ""),
        }

    def get_events(self, obj) -> list[dict]:
        # The tenant-isolation guarantee for internal notes, applied here.
        events = obj.events.filter(is_internal=False).select_related("author")
        return TicketEventSerializer(events, many=True).data

    def get_attachments(self, obj) -> list[dict]:
        attachments = obj.attachments.filter(is_internal=False)
        return TicketAttachmentSerializer(attachments, many=True, context=self.context).data

    def get_redaction_notice(self, obj) -> str:
        if not obj.redaction_summary:
            return ""
        from aiengine.services.redaction import RedactionResult

        return RedactionResult(text="", summary=obj.redaction_summary).describe()


class FdeTicketSerializer(CustomerTicketSerializer):
    """Full record, including internal notes and investigation effort."""

    assigned_fde_name = serializers.CharField(
        source="assigned_fde.full_name", read_only=True, default=None
    )
    reporter_name = serializers.CharField(
        source="reporter.full_name", read_only=True, default=None
    )
    cluster_title = serializers.CharField(source="cluster.title", read_only=True, default=None)
    fingerprint_detail = ErrorFingerprintSerializer(source="fingerprint", read_only=True)

    class Meta(CustomerTicketSerializer.Meta):
        fields = (*CustomerTicketSerializer.Meta.fields, "assigned_fde", "assigned_fde_name", "reporter", "reporter_name", "reporter_label", "fde_investigation_minutes", "resolution_quality", "resolution_verified_by", "cluster", "cluster_title", "fingerprint_detail", "first_response_at", "external_provider", "external_reference", "external_url", "external_synced_at")
        read_only_fields = fields

    def get_events(self, obj) -> list[dict]:
        return TicketEventSerializer(
            obj.events.select_related("author"), many=True
        ).data

    def get_attachments(self, obj) -> list[dict]:
        return TicketAttachmentSerializer(
            obj.attachments.all(), many=True, context=self.context
        ).data


class MatchedTicketBriefSerializer(serializers.ModelSerializer):
    """
    The matched ticket, as shown inside a similarity result.

    Note what is absent: the matched ticket's `description`, `diagnostics` and
    `organization`. For an FDE looking at cross-tenant matches, exposing another customer's
    full diagnostic text inside a match card would turn a useful feature into a data-sharing
    incident. The FDE can open the ticket itself, where the access is deliberate and
    audited; the match card carries only what is needed to judge relevance.
    """

    component_label = serializers.CharField(source="get_component_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    symptom_labels = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id", "reference", "title", "component", "component_label", "category",
            "category_label", "iomete_version", "environment", "deployment_model",
            "resolution_summary", "resolution_verified", "resolution_verified_at",
            "resolution_quality", "symptom_labels", "is_synthetic",
            "created_at", "resolved_at",
        )
        read_only_fields = fields

    def get_symptom_labels(self, obj) -> list[str]:
        return [symptom_label(s) for s in (obj.normalized or {}).get("symptoms", [])]


class SimilarityMatchSerializer(serializers.ModelSerializer):
    """
    One proposed historical match.

    The three scores are returned as separate fields with separate explanations, and the
    client is expected to render them separately. `score_explanations` travels with the
    data so the UI cannot drift from the semantics.
    """

    matched_ticket = MatchedTicketBriefSerializer(read_only=True)
    gate_status_label = serializers.CharField(source="get_gate_status_display", read_only=True)
    matched_symptom_labels = serializers.SerializerMethodField()
    score_explanations = serializers.SerializerMethodField()

    class Meta:
        model = SimilarityMatch
        fields = (
            "id", "rank", "matched_ticket", "similarity_score", "diagnosis_confidence",
            "resolution_confidence", "channel_scores", "evidence", "matched_symptoms",
            "matched_symptom_labels", "gate_status", "gate_status_label", "gate_reason",
            "retrieval_backend", "score_explanations", "created_at",
        )
        read_only_fields = fields

    def get_matched_symptom_labels(self, obj) -> list[str]:
        return [symptom_label(s) for s in (obj.matched_symptoms or [])]

    def get_score_explanations(self, _obj) -> dict:
        return {
            "similarity_score": (
                "How alike the two reports are, fused from four independent retrieval "
                "signals. High similarity means the descriptions match — it does not mean "
                "the underlying cause is the same."
            ),
            "diagnosis_confidence": (
                "How much the collected evidence supports the same root cause. Capped below "
                "full certainty by design: only inspecting your system can confirm a cause."
            ),
            "resolution_confidence": (
                "How likely this historical fix is to work in your environment — accounting "
                "for whether it was verified, how well it was executed, its age, and "
                "whether it applies to your version and deployment."
            ),
        }


class IssueClusterSerializer(serializers.ModelSerializer):
    """
    FDE-only cluster view.

    `hypothesised_root_cause` and `confirmed_root_cause` are separate fields and
    `is_root_cause_confirmed` gates which one the UI may present as a finding. The
    `caveat` field states the epistemics in words, because a reader skimming a dashboard
    will not infer them from a boolean.
    """

    component_label = serializers.CharField(source="get_component_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    ticket_count = serializers.IntegerField(read_only=True)
    verified_resolution_count = serializers.IntegerField(read_only=True)
    affected_organization_count = serializers.IntegerField(read_only=True)
    symptom_labels = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.full_name", read_only=True, default=None)
    caveat = serializers.SerializerMethodField()
    playbook_count = serializers.SerializerMethodField()

    class Meta:
        model = IssueCluster
        fields = (
            "id", "key", "title", "description", "component", "component_label",
            "category", "category_label", "status", "status_label", "symptom_signature",
            "symptom_labels", "common_error_codes", "hypothesised_root_cause",
            "is_root_cause_confirmed", "confirmed_root_cause", "investigation_notes",
            "owner", "owner_name", "ticket_count", "verified_resolution_count",
            "affected_organization_count", "playbook_count", "caveat", "is_synthetic",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_symptom_labels(self, obj) -> list[str]:
        return [symptom_label(s) for s in (obj.symptom_signature or [])]

    def get_playbook_count(self, obj) -> int:
        return obj.playbooks.filter(approval_status="approved").count()

    def get_caveat(self, obj) -> str:
        if obj.is_root_cause_confirmed:
            return (
                "Root cause confirmed by an FDE investigation. Tickets in this cluster "
                "that have not been individually verified may still differ."
            )
        return (
            "This grouping is a triage hypothesis based on shared symptoms, not a "
            "confirmed shared root cause. Tickets with identical symptoms regularly have "
            "different causes."
        )


class TicketStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TicketStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True)


class TicketCommentSerializer(serializers.Serializer):
    body = serializers.CharField()
    is_internal = serializers.BooleanField(
        default=False,
        help_text="IOMETE staff only. An internal note is never shown to the customer.",
    )


class TicketEscalateSerializer(serializers.Serializer):
    reason = serializers.CharField(
        help_text="What you have tried and what is still wrong. This becomes the FDE's "
        "starting point."
    )
    execution_id = serializers.UUIDField(
        required=False,
        help_text="Attach a specific Resolution Replay run. Defaults to the most recent.",
    )


class TicketResolveSerializer(serializers.Serializer):
    summary = serializers.CharField(help_text="How the problem was resolved.")
    evidence = serializers.CharField(
        help_text="What you observed that shows the problem is gone. Required: this "
        "resolution may be offered to other customers as precedent."
    )
    fde_investigation_minutes = serializers.IntegerField(
        required=False, min_value=0, max_value=100000,
        help_text="IOMETE staff only. Feeds the estimated-hours-saved figure.",
    )


class TicketVerifySerializer(serializers.Serializer):
    quality = serializers.IntegerField(
        min_value=1, max_value=5,
        help_text="How well was this resolved? Feeds resolution confidence for future "
        "matches, so a fix that worked but was a poor approach does not become a "
        "confident recommendation.",
    )
    note = serializers.CharField(required=False, allow_blank=True)


class TicketAssignSerializer(serializers.Serializer):
    assigned_fde = serializers.UUIDField(
        required=False, allow_null=True, help_text="Omit or null to clear the assignment."
    )


class ClusterConfirmSerializer(serializers.Serializer):
    root_cause = serializers.CharField(help_text="The confirmed root cause, in writing.")
    notes = serializers.CharField(required=False, allow_blank=True)


class ClusterStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True)


class AttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    is_internal = serializers.BooleanField(default=False)

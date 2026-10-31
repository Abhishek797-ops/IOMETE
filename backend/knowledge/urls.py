from django.urls import path

from .views import (
    ArchitectureView,
    CapabilityListView,
    DoNotClaimView,
    ExplainerView,
    KnowledgeSearchView,
    PersonaListView,
    PersonaView,
    ProductKnowledgeView,
)

urlpatterns = [
    path("product/", ProductKnowledgeView.as_view(), name="knowledge-product"),
    path("explainer/", ExplainerView.as_view(), name="knowledge-explainer"),
    path("personas/", PersonaListView.as_view(), name="knowledge-personas"),
    path("personas/<str:persona_id>/", PersonaView.as_view(), name="knowledge-persona"),
    path("architecture/", ArchitectureView.as_view(), name="knowledge-architecture"),
    path("capabilities/", CapabilityListView.as_view(), name="knowledge-capabilities"),
    path("search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("do-not-claim/", DoNotClaimView.as_view(), name="knowledge-do-not-claim"),
]

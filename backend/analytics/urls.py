from django.urls import path

from .views import (
    BreakdownsView,
    DashboardView,
    KnowledgeLifecycleView,
    MethodologyView,
    PlaybookEffectivenessView,
    TrendsView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="analytics-dashboard"),
    path("trends/", TrendsView.as_view(), name="analytics-trends"),
    path("breakdowns/", BreakdownsView.as_view(), name="analytics-breakdowns"),
    path("playbooks/", PlaybookEffectivenessView.as_view(), name="analytics-playbooks"),
    path("knowledge-lifecycle/", KnowledgeLifecycleView.as_view(),
         name="analytics-knowledge-lifecycle"),
    path("methodology/", MethodologyView.as_view(), name="analytics-methodology"),
]

"""
FDE command center routes, mounted at /api/v1/fde/.

Separated from tickets/urls.py so the FDE surface is visible as its own thing in the API
documentation and so the IsIometeStaff restriction is obvious from the URL alone.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from analytics.views import FdeDashboardView
from playbooks.views import KnowledgeReviewQueueView
from tickets.views import FdeInboxView, IssueClusterViewSet

router = DefaultRouter()
router.register("clusters", IssueClusterViewSet, basename="cluster")

urlpatterns = [
    path("inbox/", FdeInboxView.as_view(), name="fde-inbox"),
    path("dashboard/", FdeDashboardView.as_view(), name="fde-dashboard"),
    path("knowledge-review/", KnowledgeReviewQueueView.as_view(), name="fde-knowledge-review"),
    *router.urls,
]

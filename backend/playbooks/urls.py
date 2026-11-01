"""
Mounted at /api/v1/ so the resource names read as documented in the brief:
  /api/v1/playbooks/ and /api/v1/playbook-executions/
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ExecutionViewSet, KnowledgeExtractionView, PlaybookViewSet

router = DefaultRouter()
router.register("playbooks", PlaybookViewSet, basename="playbook")
router.register("playbook-executions", ExecutionViewSet, basename="playbook-execution")

urlpatterns = [
    path("knowledge/extract/", KnowledgeExtractionView.as_view(), name="knowledge-extract"),
    *router.urls,
]

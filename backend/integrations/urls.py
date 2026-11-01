from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import IntegrationStatusView, IntegrationViewSet, JiraWebhookView

router = DefaultRouter()
router.register("", IntegrationViewSet, basename="integration")

urlpatterns = [
    path("status/", IntegrationStatusView.as_view(), name="integration-status"),
    path("webhooks/jira/<uuid:integration_id>/", JiraWebhookView.as_view(),
         name="integration-jira-webhook"),
    *router.urls,
]

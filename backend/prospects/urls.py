"""Mounted at /api/v1/ so endpoint names match the brief's groups."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ArchitectureGenerateView,
    CallPrepOptionsView,
    CallPrepView,
    DemoRequestViewSet,
    FitAssessmentViewSet,
    FitRubricView,
    ProspectProfileViewSet,
    ReferenceArchitectureView,
)

router = DefaultRouter()
router.register("fit-assessments", FitAssessmentViewSet, basename="fit-assessment")
router.register("prospects", ProspectProfileViewSet, basename="prospect")
router.register("demo-requests", DemoRequestViewSet, basename="demo-request")

urlpatterns = [
    # Declared before the router so /fit-assessments/rubric/ is not swallowed by the
    # detail route's pk converter.
    path("fit-assessments/rubric/", FitRubricView.as_view(), name="fit-rubric"),
    path("call-prep/", CallPrepView.as_view(), name="call-prep"),
    path("call-prep/options/", CallPrepOptionsView.as_view(), name="call-prep-options"),
    path("architecture/generate/", ArchitectureGenerateView.as_view(), name="architecture-generate"),
    path("architecture/reference/", ReferenceArchitectureView.as_view(),
         name="architecture-reference"),
    *router.urls,
]

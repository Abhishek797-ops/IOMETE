from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AuditLogViewSet,
    DemoAccountsView,
    FdeDirectoryView,
    LoginView,
    LogoutView,
    MembershipViewSet,
    MeView,
    RefreshView,
    UserAdminViewSet,
)

router = DefaultRouter()
router.register("users", UserAdminViewSet, basename="user")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("audit", AuditLogViewSet, basename="audit")

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("demo-accounts/", DemoAccountsView.as_view(), name="auth-demo-accounts"),
    path("fdes/", FdeDirectoryView.as_view(), name="auth-fde-directory"),
    path("", include(router.urls)),
]

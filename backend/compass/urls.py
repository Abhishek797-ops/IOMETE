"""
Root URL configuration.

Every API route lives under `/api/v1/`. Each app owns its own `urls.py`; this module only
composes them so that the public API surface is readable in one place.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common.views import SystemStatusView, health

API = "api/v1/"

urlpatterns = [
    path("admin/", admin.site.urls),
    # --- Liveness / capability reporting -------------------------------------------
    path("healthz", health, name="health"),
    path(f"{API}system/status/", SystemStatusView.as_view(), name="system-status"),
    # --- API documentation ----------------------------------------------------------
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # --- Area 0: identity -----------------------------------------------------------
    path(f"{API}auth/", include("accounts.urls")),
    path(f"{API}organizations/", include("organizations.urls")),
    # --- Area 1: public customer experience -----------------------------------------
    path(f"{API}knowledge/", include("knowledge.urls")),
    path(f"{API}", include("prospects.urls")),
    path(f"{API}lakehouse-demo/", include("lakehouse.urls")),
    # --- Area 2 & 3: support intelligence -------------------------------------------
    path(f"{API}tickets/", include("tickets.urls")),
    path(f"{API}", include("playbooks.urls")),
    path(f"{API}fde/", include("tickets.fde_urls")),
    path(f"{API}analytics/", include("analytics.urls")),
    # --- Area 4: administration -----------------------------------------------------
    path(f"{API}integrations/", include("integrations.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

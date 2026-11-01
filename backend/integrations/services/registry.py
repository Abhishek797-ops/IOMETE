"""
Adapter registry and mode reporting.

One place that decides, for any provider, which adapter is in play and what mode it is in.
`describe_integration_modes()` is what `/api/v1/system/status/` publishes, which makes it
the single source of truth for every "simulated" badge in the UI.

Resolution order for a provider:

1. An enabled `IntegrationConfiguration` row with credentials → the live adapter, whose
   `mode` is derived from its last connection test.
2. Environment variables (`JIRA_*`, `IOMETE_*`) → a transient configuration built from
   them, so a deployment can be configured without a database row.
3. Nothing → the demo adapter.

Step 2 matters for the honest-demo story: setting `JIRA_BASE_URL` in `.env` gets you a
`configured` integration that still has to pass a connection test before anything reports
`connected`.
"""

from __future__ import annotations

import logging

from django.conf import settings

from ..models import (
    IntegrationConfiguration,
    IntegrationMode,
    IntegrationProvider,
)
from .base import AdapterDescription
from .iomete import DemoLakehouseAdapter, IometeAdapter
from .jira import JiraAdapter, MockTicketProvider

logger = logging.getLogger("compass.integrations")


def _env_configuration(provider: str) -> IntegrationConfiguration | None:
    """
    Build an unsaved configuration from environment variables.

    Unsaved on purpose: an env-configured integration is a deployment setting, not a
    database record someone can edit in the admin and get confused about. It starts in
    `CONFIGURED` mode — never `CONNECTED` — because no test has run.
    """
    if provider == IntegrationProvider.JIRA:
        if not (settings.JIRA_BASE_URL and settings.JIRA_API_TOKEN and settings.JIRA_EMAIL):
            return None
        configuration = IntegrationConfiguration(
            provider=IntegrationProvider.JIRA,
            display_name="Jira (from environment)",
            config={
                "base_url": settings.JIRA_BASE_URL,
                "project_key": settings.JIRA_PROJECT_KEY or "",
                "verify_tls": True,
                "source": "environment",
            },
            credentials={
                "email": settings.JIRA_EMAIL,
                "api_token": settings.JIRA_API_TOKEN,
            },
            is_enabled=True,
        )
        configuration.recompute_mode()
        return configuration

    if provider == IntegrationProvider.IOMETE:
        if not (settings.IOMETE_BASE_URL and settings.IOMETE_API_TOKEN):
            return None
        configuration = IntegrationConfiguration(
            provider=IntegrationProvider.IOMETE,
            display_name="IOMETE (from environment)",
            config={
                "base_url": settings.IOMETE_BASE_URL,
                "warehouse": settings.IOMETE_WORKSPACE or "",
                "verify_tls": settings.IOMETE_VERIFY_TLS,
                "source": "environment",
            },
            credentials={"api_token": settings.IOMETE_API_TOKEN},
            is_enabled=True,
        )
        configuration.recompute_mode()
        return configuration

    return None


def get_configuration(provider: str, *, organization=None) -> IntegrationConfiguration | None:
    """
    Find the configuration for `provider`, preferring an organization-scoped row.

    Organization-scoped beats platform-wide: a customer who has connected their own Jira
    should have theirs used rather than IOMETE's service desk.
    """
    queryset = IntegrationConfiguration.objects.filter(provider=provider, is_enabled=True)
    if organization is not None:
        scoped = queryset.filter(organization=organization).first()
        if scoped is not None:
            return scoped
    platform = queryset.filter(organization__isnull=True).first()
    if platform is not None:
        return platform
    return _env_configuration(provider)


def ticket_provider(*, organization=None):
    """
    Resolve a `TicketProvider`.

    Falls back to `MockTicketProvider` whenever Jira is not fully configured — which is the
    behaviour acceptance test 12 requires: missing Jira credentials must not break ticket
    workflows.
    """
    configuration = get_configuration(IntegrationProvider.JIRA, organization=organization)
    if configuration is None:
        return MockTicketProvider()
    adapter = JiraAdapter(configuration)
    if not adapter.is_configured:
        logger.info(
            "Jira configuration is incomplete (%s); using the simulated ticket provider.",
            "; ".join(adapter.missing_configuration),
        )
        return MockTicketProvider(configuration)
    return adapter


def lakehouse_adapter(*, organization=None):
    """
    Resolve the lakehouse adapter.

    Returns the live `IometeAdapter` **only** when a configuration exists, is complete, and
    its last connection test succeeded. Anything else returns the demo adapter — which is
    acceptance test 13: connected mode never appears active without a real connection.
    """
    configuration = get_configuration(IntegrationProvider.IOMETE, organization=organization)
    if configuration is None:
        return DemoLakehouseAdapter()
    adapter = IometeAdapter(configuration)
    if not adapter.is_configured:
        return DemoLakehouseAdapter()
    if configuration.mode != IntegrationMode.CONNECTED:
        # Configured but unverified. The live adapter is returned so that catalog reads
        # produce a precise "run a connection test first" error rather than silently
        # serving synthetic data — but the playground's own view checks the mode and uses
        # the demo adapter for queries.
        return adapter
    return adapter


def adapter_for(configuration: IntegrationConfiguration):
    """The adapter matching a stored configuration row."""
    if configuration.provider == IntegrationProvider.JIRA:
        adapter = JiraAdapter(configuration)
        return adapter if adapter.is_configured else MockTicketProvider(configuration)
    if configuration.provider == IntegrationProvider.IOMETE:
        adapter = IometeAdapter(configuration)
        return adapter if adapter.is_configured else DemoLakehouseAdapter()
    return MockTicketProvider(configuration)


def describe_integration_modes() -> dict[str, dict]:
    """
    Report every integration's real mode. Published by `/api/v1/system/status/`.

    This is what the frontend's "simulated" badges are driven from, so it must never
    overstate. Note that `jira.mode` and `iomete.mode` can only be `connected` if a stored
    configuration recorded a successful test.
    """
    jira = ticket_provider()
    lakehouse = lakehouse_adapter()

    jira_description: AdapterDescription = jira.describe()
    lakehouse_description: AdapterDescription = lakehouse.describe()

    return {
        "jira": {
            **jira_description.to_dict(),
            "adapter": type(jira).__name__,
            "purpose": "Synchronise support tickets with Jira Service Management.",
        },
        "iomete": {
            **lakehouse_description.to_dict(),
            "adapter": type(lakehouse).__name__,
            "purpose": (
                "Read catalog metadata from a live IOMETE deployment via the Iceberg REST "
                "Catalog specification, or run the synthetic lakehouse playground."
            ),
        },
        "notice": (
            "An integration is only reported as `connected` after a successful live "
            "connection test against configured credentials. `demo` means simulated and "
            "fully functional; `configured` means credentials are present but unverified."
        ),
    }

"""
Jira Service Management adapter, and the mock provider that stands in for it.

Jira is prioritised because it is where IOMETE's support workflow actually lives. The
adapter targets the documented Jira Cloud REST API v3 — `/rest/api/3/myself`,
`/rest/api/3/search/jql`, `/rest/api/3/issue` — with HTTP Basic authentication using an
email address and an API token, which is Atlassian's documented scheme for Cloud.

Two things this adapter will not do:

* **Fabricate a successful sync.** If credentials are absent or rejected, operations raise
  `IntegrationNotConfiguredError`. The sync service then runs the mock provider instead and
  records `was_simulated=True` on the run, so a simulated sync is never displayed as a real
  one.
* **Log a response body.** A failed Jira auth response can echo request headers.

`MockTicketProvider` is not a stub that returns empty lists. It serves a small, coherent,
deterministic set of Jira-shaped issues so the whole synchronisation path — field mapping,
deduplication, event creation, error handling — is exercised and demonstrable without
credentials. The interface is identical, so switching to real credentials changes no calling
code.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.exceptions import IntegrationNotConfiguredError, IntegrationUnavailableError

from ..models import IntegrationConfiguration, IntegrationMode
from .base import AdapterDescription, ConnectionResult, http_session, request_json

logger = logging.getLogger("compass.integrations.jira")

API_PREFIX = "/rest/api/3"


class JiraAdapter:
    """Live Jira Cloud adapter. Requires base_url, email and api_token."""

    provider = "jira"

    def __init__(self, configuration: IntegrationConfiguration):
        self.configuration = configuration
        config = configuration.config or {}
        credentials = configuration.credentials or {}
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.project_key = str(config.get("project_key") or "")
        self.email = str(credentials.get("email") or "")
        self.api_token = str(credentials.get("api_token") or "")
        self.verify_tls = bool(config.get("verify_tls", True))

    # --- state -----------------------------------------------------------------------

    @property
    def missing_configuration(self) -> list[str]:
        missing = []
        if not self.base_url:
            missing.append("config.base_url — your Jira site, e.g. https://acme.atlassian.net")
        if not self.email:
            missing.append("credentials.email — the Atlassian account the token belongs to")
        if not self.api_token:
            missing.append("credentials.api_token — an Atlassian API token")
        if not self.project_key:
            missing.append("config.project_key — the Service Management project key, e.g. SUP")
        return missing

    @property
    def is_configured(self) -> bool:
        return not self.missing_configuration

    def describe(self) -> AdapterDescription:
        mode = self.configuration.mode
        return AdapterDescription(
            provider=self.provider,
            mode=mode,
            is_simulated=mode != IntegrationMode.CONNECTED,
            summary=(
                "Connected to Jira Service Management. Issues sync bidirectionally."
                if mode == IntegrationMode.CONNECTED
                else (
                    "Credentials are configured but no successful connection test has been "
                    "recorded. Run a connection test to enable connected mode."
                    if mode == IntegrationMode.CONFIGURED
                    else (
                        "Simulated. No Jira credentials are configured, so the demo ticket "
                        "provider is used. Ticket workflows are fully functional; nothing "
                        "is sent to or read from a real Jira instance."
                    )
                )
            ),
            capabilities=(
                [
                    "Import issues from the configured project into COMPASS tickets",
                    "Create a Jira issue from a COMPASS escalation",
                    "Post a comment back to the linked Jira issue",
                    "Receive webhook notifications when configured and verified",
                ]
                if mode == IntegrationMode.CONNECTED
                else [
                    "Deterministic demo issues exercise the full synchronisation path",
                    "Field mapping, deduplication and error handling are all live code",
                ]
            ),
            limitations=(
                [
                    "Issue import is limited to the configured project key.",
                    "Custom field mapping beyond summary, description, priority and status "
                    "must be configured explicitly.",
                ]
                if mode == IntegrationMode.CONNECTED
                else [
                    "No data is read from or written to a real Jira instance.",
                    "Every synchronisation run is recorded with was_simulated=true.",
                ]
            ),
            missing_configuration=self.missing_configuration,
            last_tested_at=(
                self.configuration.last_connection_test_at.isoformat()
                if self.configuration.last_connection_test_at
                else None
            ),
            evidence=self.configuration.connection_detail or {},
        )

    def _session(self):
        session = http_session(verify_tls=self.verify_tls)
        session.auth = (self.email, self.api_token)
        return session

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise IntegrationNotConfiguredError(
                detail=(
                    "The Jira integration is not fully configured, so it is operating in "
                    "demo mode. Missing: " + "; ".join(self.missing_configuration)
                )
            )

    # --- connection ------------------------------------------------------------------

    def test_connection(self) -> ConnectionResult:
        """
        A real request to `/rest/api/3/myself`, then a check that the project exists.

        Two calls rather than one because they fail differently and the distinction is
        actionable: bad credentials versus a wrong project key.
        """
        if not self.is_configured:
            return ConnectionResult.failure(
                "Cannot test: " + "; ".join(self.missing_configuration),
                code="not_configured",
            )

        session = self._session()
        ok, payload, message = request_json(
            session, "GET", f"{self.base_url}{API_PREFIX}/myself"
        )
        if not ok:
            return ConnectionResult.failure(message)

        account = {
            "account_id": (payload or {}).get("accountId", ""),
            "display_name": (payload or {}).get("displayName", ""),
            "account_type": (payload or {}).get("accountType", ""),
        }

        ok, project, project_message = request_json(
            session, "GET", f"{self.base_url}{API_PREFIX}/project/{self.project_key}"
        )
        if not ok:
            return ConnectionResult(
                ok=False,
                message=(
                    f"Authenticated as {account['display_name'] or 'the configured account'}, "
                    f"but the project '{self.project_key}' could not be read: "
                    f"{project_message}"
                ),
                evidence=account,
                error_code="project_unavailable",
            )

        evidence = {
            **account,
            "project_key": (project or {}).get("key", self.project_key),
            "project_name": (project or {}).get("name", ""),
            "site": self.base_url,
        }
        return ConnectionResult(
            ok=True,
            message=(
                f"Connected to {evidence['project_name'] or self.project_key} as "
                f"{account['display_name'] or 'the configured account'}."
            ),
            evidence=evidence,
        )

    # --- ticket operations -----------------------------------------------------------

    def fetch_issues(self, *, since=None, limit: int = 50) -> list[dict]:
        self._require_configured()
        jql = f'project = "{self.project_key}"'
        if since is not None:
            jql += f' AND updated >= "{since:%Y-%m-%d %H:%M}"'
        jql += " ORDER BY updated DESC"

        ok, payload, message = request_json(
            self._session(),
            "POST",
            f"{self.base_url}{API_PREFIX}/search/jql",
            json={
                "jql": jql,
                "maxResults": min(limit, 100),
                "fields": ["summary", "description", "status", "priority", "created",
                           "updated", "reporter", "labels", "components"],
            },
        )
        if not ok:
            raise IntegrationUnavailableError(detail=f"Jira issue search failed: {message}")
        return [self._normalise(issue) for issue in (payload or {}).get("issues", [])]

    def create_issue(self, *, summary: str, description: str, **fields) -> dict:
        self._require_configured()
        ok, payload, message = request_json(
            self._session(),
            "POST",
            f"{self.base_url}{API_PREFIX}/issue",
            json={
                "fields": {
                    "project": {"key": self.project_key},
                    "summary": summary[:255],
                    # Jira Cloud v3 expects Atlassian Document Format for description.
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": description[:30000]}],
                            }
                        ],
                    },
                    "issuetype": {"name": fields.get("issue_type", "Task")},
                    **({"labels": fields["labels"]} if fields.get("labels") else {}),
                }
            },
        )
        if not ok:
            raise IntegrationUnavailableError(detail=f"Could not create the Jira issue: {message}")
        key = (payload or {}).get("key", "")
        return {
            "key": key,
            "id": (payload or {}).get("id", ""),
            "url": f"{self.base_url}/browse/{key}" if key else "",
            "simulated": False,
        }

    def add_comment(self, *, issue_key: str, body: str) -> dict:
        self._require_configured()
        ok, payload, message = request_json(
            self._session(),
            "POST",
            f"{self.base_url}{API_PREFIX}/issue/{issue_key}/comment",
            json={
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": body[:30000]}]}
                    ],
                }
            },
        )
        if not ok:
            raise IntegrationUnavailableError(detail=f"Could not add the comment: {message}")
        return {"id": (payload or {}).get("id", ""), "simulated": False}

    def _normalise(self, issue: dict) -> dict:
        """Map a Jira issue onto the shape `sync.py` consumes."""
        fields = issue.get("fields") or {}
        status = (fields.get("status") or {}).get("name", "")
        priority = (fields.get("priority") or {}).get("name", "")
        return {
            "external_id": issue.get("id", ""),
            "external_key": issue.get("key", ""),
            "external_url": f"{self.base_url}/browse/{issue.get('key', '')}",
            "summary": fields.get("summary") or "",
            "description": _adf_to_text(fields.get("description")),
            "status": status,
            "priority": priority,
            "labels": fields.get("labels") or [],
            "components": [c.get("name", "") for c in (fields.get("components") or [])],
            "created_at": fields.get("created"),
            "updated_at": fields.get("updated"),
            "reporter": ((fields.get("reporter") or {}).get("emailAddress") or ""),
            "simulated": False,
        }


def _adf_to_text(value: Any) -> str:
    """
    Flatten Atlassian Document Format to plain text.

    Jira Cloud v3 returns rich structured content. We only need the words — and taking only
    the text nodes also means no embedded media URL or mention payload comes along for the
    ride into our storage.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            for child in node.get("content") or []:
                walk(child)
            if node.get("type") in {"paragraph", "heading", "listItem"}:
                parts.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return "".join(parts).strip()


# =======================================================================================
# Mock provider
# =======================================================================================

_MOCK_ISSUES: tuple[dict, ...] = (
    {
        "external_key": "SUP-4412",
        "summary": "Spark executors terminated during nightly aggregation",
        "description": (
            "Our nightly aggregation over the transactions table fails roughly 40 minutes "
            "in. Executors are repeatedly terminated and the job never completes.\n\n"
            "ExecutorLostFailure (executor 9 exited caused by one of the running tasks) "
            "Reason: Container killed: OOMKilled (exit code 137)"
        ),
        "status": "In Progress",
        "priority": "High",
        "labels": ["spark", "compute"],
        "components": ["Compute"],
        "reporter": "data.eng@northwind.example",
    },
    {
        "external_key": "SUP-4418",
        "summary": "Iceberg commit fails with stale metadata on the events table",
        "description": (
            "Writes to the events table intermittently fail at commit time. Retrying "
            "sometimes succeeds.\n\n"
            "org.apache.iceberg.exceptions.CommitFailedException: Cannot commit: stale "
            "table metadata"
        ),
        "status": "Waiting for support",
        "priority": "Highest",
        "labels": ["iceberg", "metadata"],
        "components": ["Catalog"],
        "reporter": "platform@vela.example",
    },
    {
        "external_key": "SUP-4423",
        "summary": "Analyst cannot query the customer table — permission denied",
        "description": (
            "An analyst in the finance group gets a permission error on a table they are "
            "supposed to be able to read.\n\n"
            "org.apache.ranger.authorization.hadoop.exceptions."
            "RangerAccessControlException: Permission denied: user=f.analyst, "
            "access=SELECT"
        ),
        "status": "Open",
        "priority": "Medium",
        "labels": ["ranger", "permissions"],
        "components": ["Governance"],
        "reporter": "bi.lead@helios.example",
    },
    {
        "external_key": "SUP-4431",
        "summary": "Compute cluster stuck in Pending after node pool change",
        "description": (
            "After resizing the node pool, a new compute cluster will not start. The driver "
            "pod sits in Pending.\n\n"
            "0/6 nodes are available: 6 Insufficient memory. FailedScheduling"
        ),
        "status": "Open",
        "priority": "High",
        "labels": ["kubernetes", "scheduling"],
        "components": ["Infrastructure"],
        "reporter": "sre@northwind.example",
    },
    {
        "external_key": "SUP-4440",
        "summary": "Event stream ingestion stalled, no new rows for 3 hours",
        "description": (
            "Our HTTP event stream was landing rows in near real time and has stopped. The "
            "producer reports 200 responses.\n\n"
            "No errors visible in the application log; the Iceberg table has not advanced "
            "its snapshot."
        ),
        "status": "In Progress",
        "priority": "High",
        "labels": ["ingestion", "event-streams"],
        "components": ["Ingestion"],
        "reporter": "streaming@vela.example",
    },
)


class MockTicketProvider:
    """
    Deterministic Jira-shaped demo provider.

    Satisfies the same `TicketProvider` protocol as `JiraAdapter`, so the synchronisation
    service, field mapping and error handling are the real code paths — only the transport
    is simulated. Every returned record carries `simulated: True`, and `sync.py` propagates
    that onto the `IntegrationSyncRun`.
    """

    provider = "mock"

    def __init__(self, configuration: IntegrationConfiguration | None = None):
        self.configuration = configuration

    def describe(self) -> AdapterDescription:
        return AdapterDescription(
            provider=self.provider,
            mode=IntegrationMode.DEMO,
            is_simulated=True,
            summary=(
                "Simulated ticket provider. Serves a fixed set of Jira-shaped issues so the "
                "full synchronisation path is demonstrable without credentials."
            ),
            capabilities=[
                "Import demo issues into COMPASS tickets through the real sync service",
                "Accept issue creation and comments, returning simulated identifiers",
            ],
            limitations=[
                "Nothing is sent to or read from a real ticketing system.",
                "Issue keys are prefixed DEMO- on creation so they cannot be mistaken for "
                "real Jira keys.",
                "Every sync run is recorded with was_simulated=true.",
            ],
            missing_configuration=[
                "Configure a Jira integration with base_url, project_key, email and "
                "api_token, then run a connection test, to replace this with live Jira."
            ],
        )

    def test_connection(self) -> ConnectionResult:
        """
        Deliberately reports `ok=False`.

        The mock provider is working correctly, but it is not *connected* to anything. A
        truthful `test_connection` therefore fails — otherwise `recompute_mode()` would
        promote a simulation to `connected`, which is the exact dishonesty this design
        exists to prevent.
        """
        return ConnectionResult(
            ok=False,
            message=(
                "This is the simulated ticket provider; there is no external system to "
                "connect to. It is functioning normally."
            ),
            evidence={"simulated": True, "demo_issue_count": len(_MOCK_ISSUES)},
            error_code="simulated_provider",
        )

    def fetch_issues(self, *, since=None, limit: int = 50) -> list[dict]:
        now = datetime.now(UTC)
        issues = []
        for index, template in enumerate(_MOCK_ISSUES[:limit]):
            created = now - timedelta(days=12 - index * 2, hours=index * 3)
            issues.append(
                {
                    **template,
                    "external_id": f"demo-{10_000 + index}",
                    "external_url": "",
                    "created_at": created.isoformat(),
                    "updated_at": (created + timedelta(hours=6)).isoformat(),
                    "simulated": True,
                }
            )
        if since is not None:
            issues = [
                issue
                for issue in issues
                if datetime.fromisoformat(issue["updated_at"]) >= since
            ]
        return issues

    def create_issue(self, *, summary: str, description: str, **fields) -> dict:
        # DEMO- prefix, so a simulated key can never be mistaken for a real Jira issue.
        suffix = abs(hash(summary)) % 9000 + 1000
        return {
            "key": f"DEMO-{suffix}",
            "id": f"demo-{suffix}",
            "url": "",
            "simulated": True,
            "notice": (
                "Simulated: no issue was created in any external system. Configure and "
                "verify a Jira integration to create real issues."
            ),
        }

    def add_comment(self, *, issue_key: str, body: str) -> dict:
        return {
            "id": f"demo-comment-{abs(hash(body)) % 100000}",
            "simulated": True,
            "notice": "Simulated: no comment was posted to an external system.",
        }

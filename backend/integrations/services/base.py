"""
Integration adapter contract.

The governing rule, and the reason this file exists rather than ad-hoc HTTP calls scattered
through views: **COMPASS never reports a connection it has not made.**

Every adapter implements `test_connection()`, which must perform a real request and return
evidence of what it reached. `IntegrationConfiguration.mode` is then *derived* from that
result — it is never set by saving a form. A failed or never-run test cannot produce
`connected`, so a stale green light is structurally impossible.

Each adapter also implements `describe()`, which reports its mode, what it can and cannot
do in that mode, and — crucially — what is missing to reach connected mode. "It is
simulated, and here is exactly what you would need to configure" is far more useful to an
evaluator than a silent fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests
from django.conf import settings

logger = logging.getLogger("compass.integrations")


@dataclass
class ConnectionResult:
    """
    The outcome of a real connection attempt.

    `evidence` holds non-secret facts the remote system returned — a server version, an
    account display name, a project name. That is what makes `ok=True` a verifiable claim
    rather than an assertion: the UI shows the evidence next to the green state.
    """

    ok: bool
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""

    @classmethod
    def failure(cls, message: str, *, code: str = "connection_failed") -> ConnectionResult:
        return cls(ok=False, message=message, error_code=code)


@dataclass
class AdapterDescription:
    provider: str
    mode: str                       # demo | configured | connected
    is_simulated: bool
    summary: str
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    missing_configuration: list[str] = field(default_factory=list)
    last_tested_at: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "is_simulated": self.is_simulated,
            "summary": self.summary,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "missing_configuration": self.missing_configuration,
            "last_tested_at": self.last_tested_at,
            "evidence": self.evidence,
        }


class IntegrationAdapter(Protocol):
    provider: str

    def describe(self) -> AdapterDescription: ...
    def test_connection(self) -> ConnectionResult: ...


class TicketProvider(Protocol):
    """
    The ticket-provider interface from module nine.

    Implemented by `JiraAdapter` (live when credentials verify) and `MockTicketProvider`
    (functional demo data). The synchronisation service depends only on this protocol, so
    adding another provider — ServiceNow, Zendesk — requires no changes to the sync logic.
    """

    provider: str

    def describe(self) -> AdapterDescription: ...
    def test_connection(self) -> ConnectionResult: ...
    def fetch_issues(self, *, since=None, limit: int = 50) -> list[dict]: ...
    def create_issue(self, *, summary: str, description: str, **fields) -> dict: ...
    def add_comment(self, *, issue_key: str, body: str) -> dict: ...


def http_session(*, verify_tls: bool = True) -> requests.Session:
    """
    A requests session with sane limits for an outbound integration call.

    Retries are deliberately *not* configured here with a blanket adapter: a retry on a
    non-idempotent POST (creating a Jira issue) can produce duplicates. `sync.py` handles
    retries explicitly, per operation, where it knows whether repeating is safe.
    """
    session = requests.Session()
    session.verify = verify_tls
    session.headers.update(
        {
            "User-Agent": "IOMETE-COMPASS/1.0",
            "Accept": "application/json",
        }
    )
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs,
) -> tuple[bool, Any, str]:
    """
    Make a request and return `(ok, payload, message)`.

    Never raises, and never lets a response body reach a log. A 401 from an integration is
    a normal operational condition (rotated credential), not an exception — and the body of
    a failed auth response sometimes echoes the credential that was sent.
    """
    timeout = kwargs.pop("timeout", settings.INTEGRATION_HTTP_TIMEOUT)
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.SSLError as exc:
        return False, None, f"TLS verification failed: {exc.__class__.__name__}"
    except requests.exceptions.ConnectTimeout:
        return False, None, f"Timed out connecting to {_host(url)} after {timeout}s."
    except requests.exceptions.ReadTimeout:
        return False, None, f"{_host(url)} accepted the connection but did not respond in {timeout}s."
    except requests.exceptions.ConnectionError as exc:
        return False, None, f"Could not reach {_host(url)}: {exc.__class__.__name__}"
    except requests.exceptions.RequestException as exc:
        return False, None, f"Request to {_host(url)} failed: {exc.__class__.__name__}"

    if response.status_code == 401:
        return False, None, (
            "Authentication was rejected (401). The credentials are present but not valid — "
            "check whether the API token has been revoked or rotated."
        )
    if response.status_code == 403:
        return False, None, (
            "Access was refused (403). The credentials are valid but lack permission for "
            "this operation."
        )
    if response.status_code == 404:
        return False, None, (
            f"Not found (404) at {_path(url)}. Check the base URL and project or namespace "
            "identifiers."
        )
    if response.status_code >= 500:
        return False, None, f"{_host(url)} returned a server error ({response.status_code})."
    if response.status_code >= 400:
        return False, None, f"Request rejected with status {response.status_code}."

    if not response.content:
        return True, None, "OK"
    try:
        return True, response.json(), "OK"
    except ValueError:
        return False, None, (
            f"{_host(url)} returned a non-JSON response. This often means the base URL "
            "points at a web page rather than an API endpoint."
        )


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc or url


def _path(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path or url

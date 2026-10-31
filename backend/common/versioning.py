"""
Version-range matching for playbook applicability.

Why this exists: the single most dangerous failure mode in an AI support tool is handing a
customer on IOMETE 3.19 a fix that was verified on 2.1. Textual similarity will happily
rank that match at 0.94. So applicability is a *gate*, evaluated here, and it is
deliberately conservative — an unparseable version or spec yields `None` ("unknown"), and
the caller treats unknown as not-applicable for recommendation purposes.

Spec grammar (comma-separated, all clauses must hold):

    ">=3.0,<4.0"      range
    "==3.19.1"        exact
    "3.19.1"          exact (bare version)
    ">=3.0"           open-ended
    "*"               any version
    ""                unknown / unspecified
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_CLAUSE_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<|~=)?\s*(.+?)\s*$")


def parse_version(raw: str | None) -> tuple[int, int, int] | None:
    """Parse ``"3.19.1"`` / ``"v3.19"`` / ``"3"`` into a comparable triple, else None."""
    if not raw:
        return None
    match = _VERSION_RE.match(str(raw))
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor or 0), int(patch or 0)


def _compare(left: tuple[int, int, int], operator: str, right: tuple[int, int, int]) -> bool:
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == "!=":
        return left != right
    if operator == "~=":
        # Compatible release: same major, at least this minor.
        return left[0] == right[0] and left >= right
    return left == right  # "==" and bare


def version_matches(version: str | None, spec: str | None) -> bool | None:
    """
    Does `version` satisfy `spec`?

    Returns True, False, or **None when the answer is unknown** — because the version was
    not supplied, or the spec could not be parsed. Callers must treat None as "do not
    recommend", not as "probably fine". `"*"` and an empty spec mean the playbook declares
    no version constraint, which is True (applies everywhere) — authors are instructed in
    `.claude/skills/resolution-playbooks/SKILL.md` to narrow rather than leave it open.
    """
    if spec is None or str(spec).strip() in {"", "*", "any"}:
        return True
    parsed = parse_version(version)
    if parsed is None:
        return None

    any_clause_parsed = False
    for clause in str(spec).split(","):
        clause = clause.strip()
        if not clause:
            continue
        match = _CLAUSE_RE.match(clause)
        if not match:
            return None
        operator, raw_version = match.groups()
        target = parse_version(raw_version)
        if target is None:
            return None
        any_clause_parsed = True
        if not _compare(parsed, operator or "==", target):
            return False
    return True if any_clause_parsed else None


def environment_matches(environment: str | None, applicable: Iterable[str] | None) -> bool | None:
    """
    Does `environment` appear in `applicable`?

    Same convention: None means unknown. An empty `applicable` list means the playbook
    declares no environment constraint and is treated as applicable.
    """
    allowed = [str(item).strip().lower() for item in (applicable or []) if str(item).strip()]
    if not allowed or "*" in allowed or "any" in allowed:
        return True
    if not environment:
        return None
    return str(environment).strip().lower() in allowed


def describe_gate(version_ok: bool | None, environment_ok: bool | None) -> tuple[bool, str]:
    """
    Collapse two gate results into (is_recommendable, human-readable reason).

    The reason string is shown to the user verbatim, so it explains the decision rather
    than restating it.
    """
    if version_ok is False and environment_ok is False:
        return False, "Gated: both the product version and the environment differ from this match."
    if version_ok is False:
        return False, "Gated: this resolution was verified on a different product version."
    if environment_ok is False:
        return False, "Gated: this resolution was verified in a different deployment environment."
    if version_ok is None and environment_ok is None:
        return False, (
            "Gated: neither the product version nor the environment is known, so "
            "applicability cannot be established."
        )
    if version_ok is None:
        return False, (
            "Gated: the product version is unknown, so version applicability cannot be "
            "established. Supply the IOMETE version to re-evaluate."
        )
    if environment_ok is None:
        return False, (
            "Gated: the deployment environment is unknown, so applicability cannot be "
            "established. Supply the environment to re-evaluate."
        )
    return True, "Applicable: product version and environment both match this resolution."

"""Onboarding migration — design decision #33 A.

Scaffold the connector interface + ship Day 1 connectors for **GitHub**
and **Linear** (the "Linear OR Jira" choice in #33; rationale in
``ADR-F-003``: Linear's API is the more modern issue-tracker surface and
maps more cleanly onto Spine's work-item types). Confluence / Notion /
Asana / Jira / GitLab connectors are deferred to v1.1+ per the design
doc's deferred-items table.

Each connector exposes four pure operations:

* ``import_repos`` — discover source-code repositories.
* ``import_issues`` — discover issue records.
* ``import_comments`` — discover issue comments / discussion threads.
* ``map_to_spine_workitems`` — translate connector-native records into
  Spine ``spine_workitem.work_item`` rows.

Connectors are **side-effect-free at the network layer for tests**: the
HTTP client is injectable so unit tests stub the whole external surface.
Production wires :mod:`httpx` clients with auth headers fetched from
:mod:`shared.secrets` (per #9 — never read tokens from env vars).

The :class:`OnboardingDispatcher` walks a connector matrix and writes
every produced work-item into the destination via a writer protocol that
mirrors :class:`migration.import_.DestWriter` (subset).

Wave 3.5 FIX2 — extraction note
================================

Per V3 Part 1.1 (LOCKED top-level layout) the per-vendor connector
plumbing (``GitHubConnector``, ``LinearConnector``, the ``HttpClient``
protocol) now lives at :mod:`shared.integrations.github` and
:mod:`shared.integrations.linear`. This module re-exports those classes
so every downstream caller (Hub wizard, ``migration/tests/test_onboarding``,
``migration/_mcp_tools/migration``) keeps working unchanged.

The pieces that stay in this module are Spine-internal contracts that
are NOT integration plumbing:

* :class:`WorkItemMapping` — the Spine work-item shape (Spine domain).
* :class:`WorkItemSink` — the destination writer protocol (Spine domain).
* :class:`Connector` — the Spine-side connector contract.
* :class:`OnboardingDispatcher` — the wizard's driver loop.
* :class:`ConnectorRunReport` / :class:`OnboardingDispatchReport` —
  outcome reporting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

# Per-vendor connector plumbing now lives in shared/integrations/.
# Re-export so downstream callers don't need to change import paths.
from shared.integrations.github import (  # noqa: F401  (re-export)
    GitHubConnector,
    HttpClient,
)
from shared.integrations.linear import LinearConnector  # noqa: F401  (re-export)

logger = logging.getLogger("spine.migration.onboarding")

WorkItemType = Literal[
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
]
"""The 7 work-item types Spine v1.0 supports (per #19)."""


@dataclass(frozen=True)
class WorkItemMapping:
    """A connector-native record translated to a Spine work-item shape.

    The mapping is intentionally **dumb** — connectors don't try to be
    clever about decomposition / prioritisation. The mapping captures
    enough provenance (``source_url``, ``source_id``, ``connector``) that
    the conductor role can revisit decisions during the intake phase.
    """

    work_item_type: WorkItemType
    title: str
    body_md: str
    source_id: str
    source_url: str
    connector: str
    labels: tuple[str, ...] = ()
    external_state: Optional[str] = None
    external_created_at: Optional[str] = None
    external_updated_at: Optional[str] = None
    external_assignee: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorRunReport:
    """Per-connector outcome of an onboarding run."""

    connector: str
    repos: int = 0
    issues: int = 0
    comments: int = 0
    work_items_mapped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Connector base — kept here as the Spine-side contract (not vendor plumbing)
# ---------------------------------------------------------------------------


class Connector(Protocol):
    """The contract every onboarding connector implements.

    Concrete connectors (``GitHubConnector``, ``LinearConnector``) live
    in :mod:`shared.integrations` and are re-exported here for
    backward compatibility.
    """

    name: str

    def import_repos(self) -> list[dict[str, Any]]:
        ...

    def import_issues(self) -> list[dict[str, Any]]:
        ...

    def import_comments(self, *, issue_source_id: str) -> list[dict[str, Any]]:
        ...

    def map_to_spine_workitems(
        self, *, issues: list[dict[str, Any]],
    ) -> list[WorkItemMapping]:
        ...


# ---------------------------------------------------------------------------
# Dispatcher — stays here; it's the wizard driver, not connector plumbing
# ---------------------------------------------------------------------------


class WorkItemSink(Protocol):
    """Destination for produced Spine work-items.

    Production wires this to the spine_workitem schema writer. Tests
    capture calls in a list.
    """

    def upsert_work_items(
        self, items: list[WorkItemMapping],
    ) -> int:
        """UPSERT ``items``; return rows written. Idempotent."""
        ...


@dataclass
class OnboardingDispatchReport:
    """Aggregate outcome across all connectors."""

    started_at: str
    finished_at: str = ""
    per_connector: list[ConnectorRunReport] = field(default_factory=list)
    total_work_items: int = 0
    total_written: int = 0
    errors: list[str] = field(default_factory=list)


class OnboardingDispatcher:
    """Drive a configured matrix of connectors and persist their output.

    Per #33 A: "Wizard step in first-time-setup". The Hub wizard hands
    this dispatcher its connector list (one or many of GitHub / Linear in
    v1.0); the dispatcher runs each, hands the produced work-items to the
    sink, and returns an aggregate report.

    The dispatcher is **synchronous + simple** by design — connector
    parallelism is out of scope. v1.0 onboarding is a one-shot wizard
    flow, not a streaming consumer.
    """

    def __init__(self, *, connectors: list[Connector], sink: WorkItemSink) -> None:
        self._connectors = connectors
        self._sink = sink

    def run(self) -> OnboardingDispatchReport:
        report = OnboardingDispatchReport(
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        for c in self._connectors:
            sub = ConnectorRunReport(connector=c.name)
            try:
                repos = c.import_repos()
                sub.repos = len(repos)
                issues = c.import_issues()
                sub.issues = len(issues)
                # Comment counting is best-effort + bounded; we don't
                # actually persist them as work-items, but the count is
                # a useful signal for the wizard UI.
                comment_count = 0
                for issue in issues[:25]:  # cap; full pass on demand later
                    source_id = (
                        issue.get("identifier")
                        or issue.get("id")
                        or f"{issue.get('_spine_repo_full_name', '')}#"
                           f"{issue.get('number', '')}"
                    )
                    if not source_id:
                        continue
                    try:
                        comment_count += len(c.import_comments(
                            issue_source_id=str(source_id),
                        ))
                    except Exception as exc:  # noqa: BLE001
                        sub.errors.append(f"comments({source_id}): {exc}")
                sub.comments = comment_count
                items = c.map_to_spine_workitems(issues=issues)
                sub.work_items_mapped = len(items)
                written = self._sink.upsert_work_items(items)
                report.total_work_items += len(items)
                report.total_written += written
            except Exception as exc:  # noqa: BLE001
                sub.errors.append(str(exc))
                report.errors.append(f"{c.name}: {exc}")
            report.per_connector.append(sub)
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report


__all__ = [
    "Connector",
    "ConnectorRunReport",
    "GitHubConnector",
    "HttpClient",
    "LinearConnector",
    "OnboardingDispatcher",
    "OnboardingDispatchReport",
    "WorkItemMapping",
    "WorkItemSink",
    "WorkItemType",
]

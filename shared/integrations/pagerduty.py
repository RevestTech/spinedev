"""PagerDuty adapter — Events API v2 auth + routing-key plumbing.

Per V3 Part 1.1 this is the canonical home for PagerDuty integration
plumbing. The downstream consumer is
``shared/notify/channels.py``'s ``PagerDutyChannel`` (incident-class
routing per #6 + #11).

Vault path (per #9):

    notify/pagerduty/routing_key   (32-char hex per service integration)

Routing logic (when implemented in v1.1+):

    events with severity=='critical' OR event_type in
    {'verify_failed', 'project_blocked', 'incident_pageout'}
        → ``trigger`` action
    everything else
        → either no-op or ``acknowledge`` per bundle policy
"""

from __future__ import annotations

import logging
from typing import Optional

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationKind,
    TestConnectionResult,
    fetch_secret,
    register_adapter,
)

logger = logging.getLogger("shared.integrations.pagerduty")

VAULT_PATH_ROUTING_KEY = "notify/pagerduty/routing_key"


async def load_routing_key() -> Optional[str]:
    """Fetch the PagerDuty Events API v2 routing key from vault."""
    return await fetch_secret(VAULT_PATH_ROUTING_KEY)


class PagerDutyAdapter(BaseIntegrationAdapter):
    """Canonical integration adapter for PagerDuty.

    v1.0 is a stub: the Events-API POST lives in
    ``shared/notify/channels.py``'s ``PagerDutyChannel`` which raises
    ``NotImplementedError('v1.1+')`` until the real event POST ships.
    The ``test_connection`` probe is the vault-presence check.
    """

    def __init__(self) -> None:
        super().__init__(
            name="pagerduty",
            kind=IntegrationKind.INCIDENT,
            vault_path=VAULT_PATH_ROUTING_KEY,
            stub_v1_1=True,
        )


async def _factory() -> PagerDutyAdapter:
    return PagerDutyAdapter()


async def test_connection() -> TestConnectionResult:
    return await PagerDutyAdapter().test_connection()


register_adapter("pagerduty", _factory)


__all__ = [
    "PagerDutyAdapter",
    "VAULT_PATH_ROUTING_KEY",
    "load_routing_key",
    "test_connection",
]

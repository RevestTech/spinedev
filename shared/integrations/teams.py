"""Microsoft Teams adapter — auth + webhook URL plumbing.

Per V3 Part 1.1 this is the canonical home for Microsoft Teams
integration plumbing. The downstream consumer is
``shared/notify/channels.py``'s ``TeamsChannel`` which reads the same
vault path.

Teams uses Incoming Webhook connector cards — one URL per channel. The
URL itself embeds an unguessable token so we treat the URL as the only
credential.

Vault path (per #9):

    notify/teams/webhook_url
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

logger = logging.getLogger("shared.integrations.teams")

VAULT_PATH_WEBHOOK_URL = "notify/teams/webhook_url"


async def load_webhook_url() -> Optional[str]:
    """Fetch the Teams incoming-webhook URL from vault.

    Returns ``None`` when unconfigured; callers decide whether that's a
    hard error or a soft "Teams disabled" state.
    """
    return await fetch_secret(VAULT_PATH_WEBHOOK_URL)


class TeamsAdapter(BaseIntegrationAdapter):
    """Canonical integration adapter for Microsoft Teams.

    v1.0 is a stub: the webhook send path lives in
    ``shared/notify/channels.py``'s ``TeamsChannel`` which raises
    ``NotImplementedError('v1.1+')`` until the real connector-card POST
    ships. The ``test_connection`` probe is the vault-presence check.
    """

    def __init__(self) -> None:
        super().__init__(
            name="teams",
            kind=IntegrationKind.COMMS,
            vault_path=VAULT_PATH_WEBHOOK_URL,
            stub_v1_1=True,
        )


async def _factory() -> TeamsAdapter:
    return TeamsAdapter()


async def test_connection() -> TestConnectionResult:
    return await TeamsAdapter().test_connection()


register_adapter("teams", _factory)


__all__ = [
    "TeamsAdapter",
    "VAULT_PATH_WEBHOOK_URL",
    "load_webhook_url",
    "test_connection",
]

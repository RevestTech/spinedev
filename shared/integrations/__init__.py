"""shared.integrations — canonical home for external-system connectors.

Per V3 Part 1.1 (LOCKED top-level layout) the
``shared/integrations/`` package consolidates **per-vendor authentication,
connection, and base API clients** for every external system Spine
talks to. The per-domain *use* (voice routing / SMS sending /
issue-tracker import / GRC evidence push) stays in the owning subsystem
and imports from here.

This package was created by Wave 3.5 FIX2 to close the HIGH-severity
drift finding flagged in ``docs/STATUS.md``: ``shared/integrations/``
was referenced in 4 different design docs as the canonical location for
all integration plumbing, but never created. Twilio code was scattered
across ``voice/twilio_adapter.py`` + ``shared/notify/channels.py``;
GitHub + Linear connectors were inline inside
``migration/onboarding.py``; the 6 compliance exporters were in
``evidence/exporters/`` without shared vault/HTTP plumbing.

Public surface
==============

* :class:`IntegrationKind` — enum of the 6 cross-cutting categories
  (scm / issue_tracker / comms / incident / voice / grc) mirrored by
  the MCP tool catalog + SPA panel.
* :class:`TestConnectionResult` — uniform probe envelope every adapter
  returns from ``test_connection()``.
* :class:`BaseIntegrationAdapter` — concrete base class providing the
  shared vault-probe boilerplate.
* :class:`IntegrationAdapter` — abstract Protocol every adapter
  satisfies.
* :func:`fetch_secret` / :func:`fetch_secret_sync` — the ONLY way
  adapters in this package may obtain credentials (per #9).
* :func:`get_adapter` / :func:`known_adapters` — registry lookup used
  by the MCP tool.

Per-adapter modules
===================

* :mod:`shared.integrations.twilio` — voice + SMS + WhatsApp
* :mod:`shared.integrations.teams` — Microsoft Teams webhooks
* :mod:`shared.integrations.pagerduty` — PagerDuty Events API v2
* :mod:`shared.integrations.github` — GitHub repos + issues
* :mod:`shared.integrations.linear` — Linear GraphQL issues

Backward compatibility
======================

Downstream callsites continue to work unchanged:

* ``voice/twilio_adapter.py`` → 1-line re-export of
  :mod:`shared.integrations.twilio` (preserves the
  ``TwilioVoiceAdapter`` / ``TwilioVoiceConfig`` names voice tests
  import).
* ``shared/notify/channels.py`` → ``SMSChannel`` / ``WhatsAppChannel`` /
  ``TeamsChannel`` / ``PagerDutyChannel`` import their vault-path
  constants + ``fetch_secret_sync`` from here.
* ``migration/onboarding.py`` → ``GitHubConnector`` /
  ``LinearConnector`` re-exported from this package.
* ``evidence/exporters/_base.py`` → ``_fetch_secret`` switched to
  :func:`fetch_secret` (sync wrapper) for one canonical implementation.
"""

from __future__ import annotations

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationAdapter,
    IntegrationKind,
    IntegrationKindLiteral,
    TestConnectionResult,
    fetch_secret,
    fetch_secret_sync,
    get_adapter,
    known_adapters,
    register_adapter,
)

# Side-effect imports register adapters with the module-level registry.
# Order matters only in that adapters with circular deps (Linear depends
# on github.HttpClient) must be imported after the dep.
from shared.integrations import (  # noqa: F401  (import for side effects)
    github,
    linear,
    pagerduty,
    teams,
    twilio,
)


__all__ = [
    "BaseIntegrationAdapter",
    "IntegrationAdapter",
    "IntegrationKind",
    "IntegrationKindLiteral",
    "TestConnectionResult",
    "fetch_secret",
    "fetch_secret_sync",
    "get_adapter",
    "github",
    "known_adapters",
    "linear",
    "pagerduty",
    "register_adapter",
    "teams",
    "twilio",
]

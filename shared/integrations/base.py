"""Shared base for every external-system integration adapter (Wave 3.5 FIX2).

Per V3 Part 1.1 the locked top-level layout declares
``shared/integrations/`` as the canonical home for **per-vendor
authentication, connection, and base API clients**. The per-domain *use*
of an integration (voice routing in ``voice/``, SMS sending in
``shared/notify/``, GitHub repo import in ``migration/``, Vanta evidence
push in ``evidence/``) stays in the owning subsystem and consumes the
plumbing exported here.

This module is **plumbing-only** — there is no per-vendor business logic
in this file. Concrete adapter modules (``twilio.py``, ``github.py``,
``linear.py``, ``teams.py``, ``pagerduty.py``) live next to this file
and each inherit / use ``IntegrationAdapter`` + ``TestConnectionResult``
to expose a uniform ``test_connection()`` probe that the SPA route at
``/api/v2/integrations/{name}/test-connection`` and the MCP tool
``integrations_test_connection`` dispatch to generically.

Design contracts
================

* **Per #9 — vault-only credentials.** Every adapter MUST resolve its
  secret material through :func:`fetch_secret` (a thin wrapper around
  :func:`shared.secrets.get_secret`). No env vars, no ``~/.spine/*.yaml``
  files. ``fetch_secret`` returns ``None`` (never raises) when the vault
  entry is missing so a partially-configured Hub still imports.

* **Per #18 — closed-source posture.** No GPL deps may be imported here.
  The default HTTP path uses stdlib ``urllib.request``; per-vendor SDKs
  (``twilio``, ``httpx``, ``requests``) are lazy-imported inside the
  method that needs them so unconfigured Hubs don't pay the dep cost at
  module-load time.

* **Per V3 Part 1.1 — placement.** ``shared/integrations/`` exposes
  *connection + auth*. The *use* of an integration belongs to the
  consuming subsystem:

    - voice/twilio_adapter.py  → ``shared.integrations.twilio``
    - shared/notify/channels.py → ``shared.integrations.{twilio,teams,pagerduty}``
    - migration/onboarding.py   → ``shared.integrations.{github,linear}``
    - evidence/exporters/*.py   → ``shared.integrations.base.fetch_secret``
                                  (the 6 compliance exporters keep their
                                  domain logic in ``evidence/`` because
                                  the cohesive grouping there is "compliance
                                  evidence push", not "integration plumbing").

Two-way compatibility
=====================

Every previously-extracted callsite keeps working unchanged via a one-line
re-export shim in the legacy location (see ``voice/twilio_adapter.py``
and ``migration/onboarding.py``). Public APIs in ``voice/``,
``shared/notify/``, ``migration/``, and ``evidence/`` are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol

logger = logging.getLogger("shared.integrations")

# ---------------------------------------------------------------------------
# IntegrationKind — taxonomy mirrored by the MCP tool catalog + SPA panel
# ---------------------------------------------------------------------------


class IntegrationKind(str, Enum):
    """Cross-cutting classification for every integration adapter.

    The values are deliberately stable (string-valued) so the MCP tool
    catalog, the SPA integrations panel, and the bundle ``integrations``
    block can all reference them as plain strings without importing the
    enum.

    Categories:

    * ``SCM`` — source-control hosts (GitHub, GitLab eventually).
    * ``ISSUE_TRACKER`` — Linear, Jira, …
    * ``COMMS`` — Slack, Microsoft Teams, …
    * ``INCIDENT`` — PagerDuty, Opsgenie, …
    * ``VOICE`` — Twilio Programmable Voice / SMS / WhatsApp.
    * ``GRC`` — Vanta / Drata / Secureframe / Tugboat / Strike Graph /
      Thoropass (compliance evidence push targets).
    """

    SCM = "scm"
    ISSUE_TRACKER = "issue_tracker"
    COMMS = "comms"
    INCIDENT = "incident"
    VOICE = "voice"
    GRC = "grc"


# Convenience Literal for callers that want strict typing without
# importing the enum class.
IntegrationKindLiteral = Literal[
    "scm", "issue_tracker", "comms", "incident", "voice", "grc",
]


# ---------------------------------------------------------------------------
# TestConnectionResult — uniform probe envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestConnectionResult:
    """Outcome of a single ``test_connection()`` probe.

    Note: the ``__test__ = False`` class attribute below tells pytest
    *not* to treat this class as a test collection target despite the
    ``Test`` prefix in its name. (The name matches the public surface
    docs and SPA panel labels, so renaming is not on the table.)

    The shape is intentionally minimal — the SPA route + the MCP tool
    both wrap this into their own envelopes; what they need from the
    adapter is the binary outcome + a short human-readable detail +
    enough metadata to render a row in the integrations panel.

    Fields:

    * ``name`` — adapter identifier (``"twilio"``, ``"github"``, …).
    * ``healthy`` — True iff the adapter could authenticate AND reach
      the vendor (or, for stub adapters, iff the vault entry is set).
    * ``probe_mode`` — ``"real"`` when a live HTTP request was made;
      ``"stub"`` when only a vault-presence check could be performed
      (v1.1+ adapters).
    * ``detail`` — single-line operator-facing summary; safe to log.
    * ``vault_path`` — the canonical vault path the adapter read from;
      enables the SPA "configure" affordance to deep-link to the right
      vault row.
    * ``error`` — populated only when ``healthy is False``; captures the
      vendor / network / vault error in a single string.
    """

    # pytest opt-out — see class docstring.
    __test__ = False

    name: str
    healthy: bool
    probe_mode: Literal["real", "stub"]
    detail: str = ""
    vault_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Vault helper — every adapter MUST go through this
# ---------------------------------------------------------------------------


async def fetch_secret(path: str) -> Optional[str]:
    """Async vault read; returns ``None`` for missing-but-readable entries.

    Per #9 this is the ONLY way an adapter in ``shared/integrations/``
    may obtain credential material. Implementation defers to
    :func:`shared.secrets.get_secret` and degrades gracefully when:

    * The ``shared.secrets`` module cannot be imported (e.g. minimal
      test harness without the package on path).
    * The vault entry is missing (``SecretNotFound``).
    * The backend errors (logged at warning level; returned as ``None``
      so adapters can produce a clean "not configured" outcome).
    """
    try:
        from shared.secrets import (  # noqa: PLC0415
            SecretBackendError,
            SecretNotFound,
            get_secret,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("shared.secrets unavailable for %s: %s", path, exc)
        return None
    try:
        return await get_secret(path)
    except SecretNotFound:
        return None
    except SecretBackendError as exc:
        logger.debug("no secret backend for %s: %s", path, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never crash adapter ctor
        logger.warning("vault read failed for %s: %s", path, exc)
        return None


def fetch_secret_sync(path: str) -> Optional[str]:
    """Sync convenience wrapper used by channel/exporter constructors.

    Channel constructors in ``shared/notify/channels.py`` are sync and
    can be invoked from inside an already-running event loop (the
    federation daemon's notifier or a CLI script). When that happens
    we return ``None`` rather than blowing up — the caller surfaces a
    clear "credential not loaded" error at ``send()`` time instead.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.debug(
                "skipping vault fetch for %s — running event loop",
                path,
            )
            return None
    except RuntimeError:
        # No event loop bound to this thread — safe to spin a new one.
        pass
    try:
        return asyncio.run(fetch_secret(path))
    except RuntimeError:
        # Another nested-loop scenario we cannot recover from cleanly.
        return None


# ---------------------------------------------------------------------------
# IntegrationAdapter — abstract contract every per-vendor module follows
# ---------------------------------------------------------------------------


class IntegrationAdapter(Protocol):
    """The contract every concrete integration module must satisfy.

    Concrete adapters (``TwilioAdapter``, ``GitHubAdapter``,
    ``LinearAdapter``, ``TeamsAdapter``, ``PagerDutyAdapter``) take an
    HTTP client or vendor SDK at construction so tests can inject
    mocks. Production wiring constructs them via the registry helpers
    in this module.
    """

    #: Canonical adapter name; matches the catalog key in the MCP tool +
    #: SPA route. Always lowercase, ascii.
    name: str

    #: Cross-cutting taxonomy bucket.
    kind: IntegrationKind

    async def test_connection(self) -> TestConnectionResult:
        """Probe the integration; never raises."""
        ...


@dataclass
class BaseIntegrationAdapter:
    """Concrete base offering the common boilerplate + a stub probe.

    Concrete adapters compose this class instead of subclassing
    ``IntegrationAdapter`` directly so they get:

    * ``name`` + ``kind`` storage,
    * the standard vault-only ``test_connection`` fallback (used by
      Twilio / Teams / PagerDuty stub adapters per V3 #6 + #29),
    * a uniform ``_vault_probe`` helper for real adapters that want to
      fall back to the vault-only check when the vendor SDK is missing.

    Subclasses MAY override ``test_connection`` to swap in a real
    HTTP probe (see ``GitHubAdapter`` / ``LinearAdapter``).
    """

    name: str
    kind: IntegrationKind
    vault_path: Optional[str] = None
    #: When True ``test_connection`` returns a ``probe_mode='stub'``
    #: envelope even if the vault entry is present. Used by v1.1+ stub
    #: adapters (Teams / PagerDuty webhook send / Twilio voice routing).
    stub_v1_1: bool = False

    async def _vault_probe(self) -> TestConnectionResult:
        """Vault-only liveness check; the default ``test_connection``.

        Returns ``healthy=True`` iff the canonical ``vault_path`` (if
        any) resolves to a non-empty secret. Used by:

        * Stub adapters (Teams / Twilio voice / GRC v1.1+ exporters)
          where there is no real vendor probe yet.
        * Real adapters as a fallback when the vendor SDK is missing
          (e.g. ``requests`` not installed in a minimal Hub deploy).
        """
        if self.vault_path is None:
            return TestConnectionResult(
                name=self.name,
                healthy=True,
                probe_mode="stub",
                detail="no vault_path declared; nothing to probe",
            )
        value = await fetch_secret(self.vault_path)
        if value:
            return TestConnectionResult(
                name=self.name,
                healthy=True,
                probe_mode="stub",
                detail=f"vault secret present at {self.vault_path!r}",
                vault_path=self.vault_path,
            )
        return TestConnectionResult(
            name=self.name,
            healthy=False,
            probe_mode="stub",
            detail=f"vault secret missing at {self.vault_path!r}",
            vault_path=self.vault_path,
            error="vault_secret_missing",
        )

    async def test_connection(self) -> TestConnectionResult:
        """Default implementation = vault-only check.

        Real adapters override; stub adapters inherit this directly.
        """
        return await self._vault_probe()


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


#: Per-adapter factory registry. Adapter modules register themselves at
#: import time so consumers can look up adapters by name without
#: importing the module directly. Keyed by lowercase canonical name.
_REGISTRY: dict[str, Callable[[], Awaitable[BaseIntegrationAdapter]]] = {}


def register_adapter(
    name: str,
    factory: Callable[[], Awaitable[BaseIntegrationAdapter]],
) -> None:
    """Idempotent registration; last-write-wins (per V3 §"last-writer" KG)."""
    _REGISTRY[name.lower()] = factory


async def get_adapter(name: str) -> Optional[BaseIntegrationAdapter]:
    """Look up an adapter by canonical name; returns ``None`` if absent."""
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        return None
    return await factory()


def known_adapters() -> list[str]:
    """Return every registered adapter name (sorted, for stable UIs)."""
    return sorted(_REGISTRY)


__all__ = [
    "BaseIntegrationAdapter",
    "IntegrationAdapter",
    "IntegrationKind",
    "IntegrationKindLiteral",
    "TestConnectionResult",
    "fetch_secret",
    "fetch_secret_sync",
    "get_adapter",
    "known_adapters",
    "register_adapter",
]

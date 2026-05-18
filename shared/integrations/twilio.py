"""Twilio adapter (canonical) — auth + signature validation + base client.

Per V3 Part 1.1 this is the canonical home for Twilio plumbing. Three
downstream callers consume what's here:

* ``voice/twilio_adapter.py`` re-exports ``TwilioVoiceAdapter`` +
  ``TwilioVoiceConfig`` for voice routing (Wave 6 Stream I).
* ``shared/notify/channels.py``'s ``SMSChannel`` + ``WhatsAppChannel``
  consume :class:`TwilioCredentials` for SMS/WhatsApp dispatch
  (Wave 1 scaffolds).
* ``shared/mcp/tools/integrations.py`` dispatches
  ``integrations_test_connection(name='twilio')`` to
  :func:`test_connection` here.

Vault path scheme (per #9 — no env vars, no YAML):

    notify/twilio/account_sid          (required)
    notify/twilio/auth_token           (required)
    notify/twilio/from_number          (required for SMS / outbound voice)
    notify/twilio/whatsapp_from        (required for WhatsApp)
    voice/twilio/incident_call_number  (optional — Master-CTO callable)

Signature validation
====================

The HMAC-SHA1 Twilio webhook signature algorithm is implemented in
:func:`validate_twilio_signature` so every caller (voice route, voice
adapter, future SMS reply route) shares one implementation. The
implementation is constant-time and never raises — wrong input simply
returns ``False``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationKind,
    TestConnectionResult,
    fetch_secret,
    register_adapter,
)

logger = logging.getLogger("shared.integrations.twilio")


# ---------------------------------------------------------------------------
# Vault paths (PATHS only — never values; per #9)
# ---------------------------------------------------------------------------

VAULT_PATH_ACCOUNT_SID = "notify/twilio/account_sid"
VAULT_PATH_AUTH_TOKEN = "notify/twilio/auth_token"
VAULT_PATH_FROM_NUMBER = "notify/twilio/from_number"
VAULT_PATH_WHATSAPP_FROM = "notify/twilio/whatsapp_from"
VAULT_PATH_INCIDENT_NUMBER = "voice/twilio/incident_call_number"

#: TwiML envelope returned by future ``route_call`` implementations.
#: Kept here so test fixtures + the voice route + the adapter share it.
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


# ---------------------------------------------------------------------------
# Credentials value object
# ---------------------------------------------------------------------------


@dataclass
class TwilioCredentials:
    """Materialised Twilio credentials (loaded from vault).

    All fields default to ``None`` so an unconfigured Hub can still
    construct the credentials object — the consuming site decides
    whether the missing field is a hard error or a soft "not configured"
    state.
    """

    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None
    whatsapp_from: Optional[str] = None
    incident_number: Optional[str] = None

    @classmethod
    async def from_vault(cls) -> "TwilioCredentials":
        """Resolve every credential from vault — single async hop per field."""
        return cls(
            account_sid=await fetch_secret(VAULT_PATH_ACCOUNT_SID),
            auth_token=await fetch_secret(VAULT_PATH_AUTH_TOKEN),
            from_number=await fetch_secret(VAULT_PATH_FROM_NUMBER),
            whatsapp_from=await fetch_secret(VAULT_PATH_WHATSAPP_FROM),
            incident_number=await fetch_secret(VAULT_PATH_INCIDENT_NUMBER),
        )

    @property
    def is_configured(self) -> bool:
        """True iff the minimum-viable account_sid + auth_token + from_number trio is set."""
        return bool(self.account_sid and self.auth_token and self.from_number)

    @property
    def is_whatsapp_configured(self) -> bool:
        """True iff the WhatsApp sender is set in addition to base creds."""
        return bool(
            self.account_sid and self.auth_token and self.whatsapp_from,
        )


# ---------------------------------------------------------------------------
# Signature validation (Twilio HMAC-SHA1)
# ---------------------------------------------------------------------------


def validate_twilio_signature(
    *, auth_token: str, url: str, params: dict[str, str], signature: str,
) -> bool:
    """Validate an inbound Twilio signature header.

    Twilio's algorithm (per their security docs):

    1. Concatenate the full request URL with each POST parameter sorted
       alphabetically by name (``key + value`` with no separators).
    2. HMAC-SHA1 the concatenation using the account's auth token.
    3. Base64-encode the digest.
    4. ``hmac.compare_digest`` against the ``X-Twilio-Signature`` header.

    Returns ``False`` for any malformed input rather than raising — the
    webhook route translates this into a 403 cleanly.
    """
    if not (auth_token and signature):
        return False
    try:
        data = url + "".join(
            f"{k}{v}" for k, v in sorted(params.items())
        )
        digest = hmac.new(
            auth_token.encode(), data.encode(), hashlib.sha1,
        ).digest()
        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(expected, signature)
    except Exception as exc:  # noqa: BLE001 — never crash the webhook
        logger.debug("twilio signature validation error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Twilio voice adapter (Wave 6 Stream I) — re-exported from voice/
# ---------------------------------------------------------------------------


@dataclass
class TwilioVoiceConfig:
    """Backward-compat alias for the voice/ adapter's credentials view.

    Predates the canonical :class:`TwilioCredentials` and is preserved
    here so ``voice/twilio_adapter.py``'s public API (which downstream
    voice tests import directly) stays binary-compatible.
    """

    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None
    incident_number: Optional[str] = None

    @classmethod
    async def from_vault(cls) -> "TwilioVoiceConfig":
        creds = await TwilioCredentials.from_vault()
        return cls(
            account_sid=creds.account_sid,
            auth_token=creds.auth_token,
            from_number=creds.from_number,
            incident_number=creds.incident_number,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)


@dataclass
class TwilioVoiceAdapter:
    """Voice-specific extension of the Twilio scaffold (Wave 6 Stream I).

    Owns three responsibilities:

    1. **Config** — load Twilio creds from vault (per #9).
    2. **Signature verification** — delegate to :func:`validate_twilio_signature`
       so one impl serves the webhook route AND any future adapter-driven
       outbound call.
    3. **Call routing** — produce TwiML in response to inbound voice
       webhooks. v1.0 raises ``NotImplementedError("v1.1+")``; v1.1+
       returns real TwiML XML.

    The adapter is async-init by convention::

        adapter = await TwilioVoiceAdapter.from_vault()
    """

    config: TwilioVoiceConfig = field(default_factory=TwilioVoiceConfig)

    @classmethod
    async def from_vault(cls) -> "TwilioVoiceAdapter":
        return cls(config=await TwilioVoiceConfig.from_vault())

    def verify_signature(
        self, *, url: str, params: dict[str, str], signature: str,
    ) -> bool:
        """Validate an inbound Twilio signature; False for unconfigured Hub."""
        if not self.config.auth_token:
            return False
        return validate_twilio_signature(
            auth_token=self.config.auth_token,
            url=url,
            params=params,
            signature=signature,
        )

    def route_call(self, params: dict[str, Any]) -> str:  # noqa: ARG002
        """Produce TwiML for an inbound voice webhook — v1.1+ feature."""
        raise NotImplementedError(
            "Twilio voice call routing is a v1.1+ flow; the v1.0 scaffold "
            "validates the signature only. See voice/README.md for the "
            "v1.1+ build plan (most likely first flow: Master CTO "
            "callable for incidents per #29)."
        )

    def place_outbound_call(
        self, *, to: str, twiml_url: str,
    ) -> dict[str, Any]:
        """Place an outbound call via Twilio's REST API — v1.1+ feature."""
        raise NotImplementedError(
            f"Twilio outbound voice calls are a v1.1+ feature; "
            f"requested to={to!r} twiml_url={twiml_url!r} would "
            f"`calls.create(to=to, from_=self.config.from_number, url=twiml_url)`."
        )


# ---------------------------------------------------------------------------
# Standard integration-adapter facade (used by MCP + SPA)
# ---------------------------------------------------------------------------


class TwilioAdapter(BaseIntegrationAdapter):
    """Canonical integration adapter for the Twilio voice/SMS surface.

    Wraps :class:`TwilioCredentials` + presents the uniform
    ``test_connection`` probe consumed by the MCP tool + SPA route.
    For v1.0 the probe is the vault-presence fallback (Twilio's REST
    API requires real outbound network access we don't want to ship by
    default); v1.1+ promotes to a real ``GET /Accounts/{SID}.json``
    HTTP probe.
    """

    def __init__(self) -> None:
        super().__init__(
            name="twilio",
            kind=IntegrationKind.VOICE,
            vault_path=VAULT_PATH_AUTH_TOKEN,
            stub_v1_1=True,  # promote to real HTTP probe in v1.1+
        )


async def _factory() -> TwilioAdapter:
    return TwilioAdapter()


async def test_connection() -> TestConnectionResult:
    """Module-level entry point dispatched by ``integrations_test_connection``."""
    return await TwilioAdapter().test_connection()


# Register at import time so the MCP tool can look us up by name.
register_adapter("twilio", _factory)


__all__ = [
    "EMPTY_TWIML",
    "TwilioAdapter",
    "TwilioCredentials",
    "TwilioVoiceAdapter",
    "TwilioVoiceConfig",
    "VAULT_PATH_ACCOUNT_SID",
    "VAULT_PATH_AUTH_TOKEN",
    "VAULT_PATH_FROM_NUMBER",
    "VAULT_PATH_INCIDENT_NUMBER",
    "VAULT_PATH_WHATSAPP_FROM",
    "test_connection",
    "validate_twilio_signature",
]

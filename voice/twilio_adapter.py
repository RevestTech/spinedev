"""Twilio Programmable Voice adapter — SCAFFOLD (#29).

Per V3 #29 the v1.0 ship date includes:

* **real** config loading from vault (per #9) — ``account_sid`` +
  ``auth_token`` + ``from_number`` come from
  ``notify/twilio/{account_sid,auth_token,from_number}``;
* **real** Twilio signature verification (delegated to the validator in
  ``shared/api/routes/voice.py`` so both webhook and adapter share one
  implementation);
* **stubbed** call routing — :meth:`TwilioVoiceAdapter.route_call`
  raises ``NotImplementedError("v1.1+")`` with a clear upgrade path.

The adapter is intentionally a thin extension of the existing Twilio
scaffold (Wave 1 added ``SMSChannel`` + ``WhatsAppChannel`` in
``shared/notify/channels.py``). Wave 6 adds voice — same vault paths,
same auth model, same SDK eventually. The shape is parallel to the
SMS/WhatsApp scaffolds so v1.1+ teams have one mental model to learn.

Note: ``shared/integrations/twilio.py`` is referenced in the build plan
(``docs/V3_BUILD_SEQUENCE.md`` Wave 6 Stream I) as the canonical
location for the shared Twilio client. That module has not yet been
extracted from ``shared/notify/channels.py``; when it lands (v1.1+ or
late Wave 4), this adapter SHOULD import its ``TwilioClient`` rather
than re-fetching secrets here. Until then we duplicate the three vault
reads — three lines of repetition is the right cost to keep Stream I
shippable without coupling to Stream B's pending refactor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("spine.voice.twilio_adapter")

#: Vault paths the adapter resolves (PATHS only, NEVER values — per #9).
VAULT_PATH_ACCOUNT_SID = "notify/twilio/account_sid"
VAULT_PATH_AUTH_TOKEN = "notify/twilio/auth_token"
VAULT_PATH_FROM_NUMBER = "notify/twilio/from_number"
#: v1.1+ vault path — the number dialed FROM to reach the on-call CTO
#: (the "Master CTO callable for incidents" pattern).
VAULT_PATH_INCIDENT_NUMBER = "voice/twilio/incident_call_number"

#: TwiML envelope returned by future ``route_call`` implementations.
#: Kept here so test fixtures + the route module can share the constant.
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


async def _fetch(path: str) -> Optional[str]:
    """Vault-only secret fetch helper (per #9).

    Returns ``None`` if the vault entry is missing — callers decide
    whether that's a hard error or a soft "voice not configured" state.
    """
    try:
        from shared.secrets import get_secret  # noqa: PLC0415
    except Exception:  # pragma: no cover - py_compile guard
        return None
    try:
        return await get_secret(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("twilio_vault_fetch_failed", extra={"path": path, "error": str(exc)})
        return None


@dataclass
class TwilioVoiceConfig:
    """Materialised Twilio voice credentials (loaded from vault).

    All fields default to ``None`` so an unconfigured Hub can still
    construct the adapter (the webhook route then 503s rather than
    blowing up at import time).
    """

    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_number: Optional[str] = None
    incident_number: Optional[str] = None

    @classmethod
    async def from_vault(cls) -> "TwilioVoiceConfig":
        """Resolve every value from vault — single async hop per field."""
        return cls(
            account_sid=await _fetch(VAULT_PATH_ACCOUNT_SID),
            auth_token=await _fetch(VAULT_PATH_AUTH_TOKEN),
            from_number=await _fetch(VAULT_PATH_FROM_NUMBER),
            incident_number=await _fetch(VAULT_PATH_INCIDENT_NUMBER),
        )

    @property
    def is_configured(self) -> bool:
        """True iff the minimum-viable trio is set."""
        return bool(self.account_sid and self.auth_token and self.from_number)


@dataclass
class TwilioVoiceAdapter:
    """Voice-specific extension of the Wave-1 Twilio scaffold.

    The adapter owns three responsibilities:

    1. **Config** — load Twilio creds from vault (per #9).
    2. **Signature verification** — re-export the validator from
       ``shared/api/routes/voice.py`` so one impl serves both the webhook
       route and any future adapter-driven outbound call.
    3. **Call routing** — produce TwiML in response to inbound voice
       webhooks. v1.0 raises ``NotImplementedError("v1.1+")``; v1.1+
       returns real TwiML XML.

    The adapter is async-init by convention: callers do::

        adapter = await TwilioVoiceAdapter.from_vault()

    rather than blocking the event loop on synchronous vault reads.
    """

    config: TwilioVoiceConfig = field(default_factory=TwilioVoiceConfig)

    @classmethod
    async def from_vault(cls) -> "TwilioVoiceAdapter":
        """Async factory — pulls Twilio creds from vault and constructs."""
        return cls(config=await TwilioVoiceConfig.from_vault())

    def verify_signature(
        self, *, url: str, params: dict[str, str], signature: str
    ) -> bool:
        """Validate an inbound Twilio signature header.

        Returns False if the adapter has no auth token (unconfigured
        Hub) so callers can produce a 503/401 rather than crashing.
        """
        if not self.config.auth_token:
            return False
        # Re-use the validator from the route module so a future fix
        # touches one implementation, not two.
        from shared.api.routes.voice import _validate_twilio_signature  # noqa: PLC0415

        return _validate_twilio_signature(
            auth_token=self.config.auth_token,
            url=url,
            params=params,
            signature=signature,
        )

    def route_call(self, params: dict[str, Any]) -> str:  # noqa: ARG002
        """Produce TwiML in response to an inbound voice webhook.

        **v1.0 — SCAFFOLD ONLY.** Per #29 actual call routing (TwiML
        composition + DTMF capture + role dispatch + Master-CTO callable
        pattern) is deferred to v1.1+. Raising
        ``NotImplementedError("v1.1+")`` here means the webhook route in
        ``shared/api/routes/voice.py`` knows to return the scaffold echo
        envelope rather than malformed TwiML.

        v1.1+ implementations replace this method body with TwiML
        composition that calls the voice-integration interface to:
          * dispatch to a voice-reachable role (per the catalogue), or
          * accept a voice-approval DTMF response (per the catalogue), or
          * fall through to a human on-call number.
        """
        raise NotImplementedError(
            "Twilio voice call routing is a v1.1+ flow; the v1.0 scaffold "
            "validates the signature only. See voice/README.md for the "
            "v1.1+ build plan (most likely first flow: Master CTO "
            "callable for incidents per #29)."
        )

    def place_outbound_call(  # noqa: D401 - imperative API
        self, *, to: str, twiml_url: str
    ) -> dict[str, Any]:
        """Place an outbound call via the Twilio REST API.

        **v1.0 — SCAFFOLD ONLY.** Same contract as :meth:`route_call`:
        v1.1+ implementations use the Twilio Python SDK
        (``twilio.rest.Client``) to ``calls.create(...)``. The signature
        documented here is what the v1.1+ implementation MUST honour.
        """
        raise NotImplementedError(
            f"Twilio outbound voice calls are a v1.1+ feature; "
            f"requested to={to!r} twiml_url={twiml_url!r} would "
            f"`calls.create(to=to, from_=self.config.from_number, url=twiml_url)`."
        )


__all__ = [
    "TwilioVoiceAdapter",
    "TwilioVoiceConfig",
    "VAULT_PATH_ACCOUNT_SID",
    "VAULT_PATH_AUTH_TOKEN",
    "VAULT_PATH_FROM_NUMBER",
    "VAULT_PATH_INCIDENT_NUMBER",
    "EMPTY_TWIML",
]

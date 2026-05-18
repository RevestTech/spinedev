"""Twilio Programmable Voice adapter — voice/ re-export shim (#29).

Per V3 Part 1.1 (LOCKED top-level layout) the canonical home for Twilio
plumbing is :mod:`shared.integrations.twilio`. This module is preserved
as a 1-line re-export shim so the voice-scaffold callsites
(``voice.tests.test_voice_scaffold``, ``shared.api.routes.voice``)
continue to import the same names without churn.

If you are writing new code, prefer importing from
``shared.integrations.twilio`` directly.

Wave 3.5 FIX2 — extraction commit. The previous implementation lived
inline here; it now lives at ``shared/integrations/twilio.py`` and
exposes the same public surface (``TwilioVoiceAdapter``,
``TwilioVoiceConfig``, ``EMPTY_TWIML``, the ``VAULT_PATH_*`` constants).
"""

from __future__ import annotations

from shared.integrations.twilio import (  # noqa: F401  (re-export)
    EMPTY_TWIML,
    TwilioVoiceAdapter,
    TwilioVoiceConfig,
    VAULT_PATH_ACCOUNT_SID,
    VAULT_PATH_AUTH_TOKEN,
    VAULT_PATH_FROM_NUMBER,
    VAULT_PATH_INCIDENT_NUMBER,
    validate_twilio_signature,
)

__all__ = [
    "EMPTY_TWIML",
    "TwilioVoiceAdapter",
    "TwilioVoiceConfig",
    "VAULT_PATH_ACCOUNT_SID",
    "VAULT_PATH_AUTH_TOKEN",
    "VAULT_PATH_FROM_NUMBER",
    "VAULT_PATH_INCIDENT_NUMBER",
    "validate_twilio_signature",
]

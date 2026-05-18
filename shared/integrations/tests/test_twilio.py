"""Tests for ``shared.integrations.twilio`` — canonical Twilio adapter.

Covers:

* Vault-only credential resolution via ``TwilioCredentials.from_vault``.
* ``validate_twilio_signature`` HMAC-SHA1 implementation matches Twilio's
  documented algorithm; rejects malformed / wrong-signature inputs.
* ``TwilioAdapter.test_connection`` returns the documented stub envelope.
* ``TwilioVoiceAdapter`` (the voice/-compat object) preserves its
  ``route_call`` / ``place_outbound_call`` v1.1+ contract.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac

import pytest

from shared.integrations.twilio import (
    EMPTY_TWIML,
    TwilioAdapter,
    TwilioCredentials,
    TwilioVoiceAdapter,
    TwilioVoiceConfig,
    VAULT_PATH_ACCOUNT_SID,
    VAULT_PATH_AUTH_TOKEN,
    VAULT_PATH_FROM_NUMBER,
    VAULT_PATH_INCIDENT_NUMBER,
    validate_twilio_signature,
)
from shared.integrations.twilio import test_connection as probe_connection


# ---------------------------------------------------------------------------
# Vault paths (all PATHS, no values — per #9)
# ---------------------------------------------------------------------------


def test_vault_paths_match_documented_scheme() -> None:
    assert VAULT_PATH_ACCOUNT_SID == "notify/twilio/account_sid"
    assert VAULT_PATH_AUTH_TOKEN == "notify/twilio/auth_token"
    assert VAULT_PATH_FROM_NUMBER == "notify/twilio/from_number"
    assert VAULT_PATH_INCIDENT_NUMBER == "voice/twilio/incident_call_number"


# ---------------------------------------------------------------------------
# Credentials — vault-only
# ---------------------------------------------------------------------------


def test_credentials_from_vault_calls_every_path(monkeypatch) -> None:
    """All 5 documented vault paths must be read on each load."""
    import shared.integrations.twilio as mod

    called: list[str] = []

    async def _fake(path: str) -> str:
        called.append(path)
        return f"VAL:{path}"

    monkeypatch.setattr(mod, "fetch_secret", _fake, raising=True)
    creds = asyncio.run(TwilioCredentials.from_vault())
    assert set(called) == {
        VAULT_PATH_ACCOUNT_SID,
        VAULT_PATH_AUTH_TOKEN,
        VAULT_PATH_FROM_NUMBER,
        "notify/twilio/whatsapp_from",
        VAULT_PATH_INCIDENT_NUMBER,
    }
    assert creds.is_configured is True


def test_credentials_unconfigured_default() -> None:
    creds = TwilioCredentials()
    assert creds.is_configured is False
    assert creds.is_whatsapp_configured is False


def test_credentials_minimum_viable_trio() -> None:
    creds = TwilioCredentials(
        account_sid="AC1", auth_token="t", from_number="+15551112222",
    )
    assert creds.is_configured is True
    assert creds.is_whatsapp_configured is False  # WhatsApp needs its own number


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------


def _twilio_sign(token: str, url: str, params: dict[str, str]) -> str:
    """Replica of Twilio's signing algorithm — used to forge VALID signatures."""
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def test_validate_returns_false_for_empty_token() -> None:
    assert validate_twilio_signature(
        auth_token="", url="https://x", params={}, signature="abc",
    ) is False


def test_validate_returns_false_for_empty_signature() -> None:
    assert validate_twilio_signature(
        auth_token="k", url="https://x", params={}, signature="",
    ) is False


def test_validate_returns_false_for_wrong_signature() -> None:
    assert validate_twilio_signature(
        auth_token="k", url="https://x", params={}, signature="zzz",
    ) is False


def test_validate_accepts_correctly_signed_request() -> None:
    token = "abc"
    url = "https://x/y"
    params = {"From": "+15551112222", "CallSid": "CA1"}
    good = _twilio_sign(token, url, params)
    assert validate_twilio_signature(
        auth_token=token, url=url, params=params, signature=good,
    ) is True


def test_validate_param_order_independent() -> None:
    """Sorting param keys means caller dict ordering is irrelevant."""
    token, url = "k", "https://x"
    p1 = {"a": "1", "b": "2"}
    p2 = {"b": "2", "a": "1"}
    sig = _twilio_sign(token, url, p1)
    assert validate_twilio_signature(
        auth_token=token, url=url, params=p2, signature=sig,
    ) is True


# ---------------------------------------------------------------------------
# TwilioAdapter (registry facade)
# ---------------------------------------------------------------------------


def test_twilio_adapter_is_stub_v1_1() -> None:
    """v1.0 ships a vault-only probe; v1.1+ promotes to real REST call."""
    adapter = TwilioAdapter()
    assert adapter.name == "twilio"
    assert adapter.stub_v1_1 is True


def test_module_test_connection_returns_stub_envelope(monkeypatch) -> None:
    """``shared.integrations.twilio.test_connection()`` returns a probe envelope."""
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> str:
        return "configured"

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection())
    assert result.name == "twilio"
    assert result.probe_mode == "stub"
    assert result.healthy is True


def test_module_test_connection_unhealthy_when_unconfigured(monkeypatch) -> None:
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> None:
        return None

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection())
    assert result.healthy is False
    assert result.error == "vault_secret_missing"


# ---------------------------------------------------------------------------
# Voice adapter (backward-compat surface used by voice/ tests)
# ---------------------------------------------------------------------------


def test_voice_adapter_route_call_is_v1_1_stub() -> None:
    adapter = TwilioVoiceAdapter()
    with pytest.raises(NotImplementedError) as exc:
        adapter.route_call({"CallSid": "CA1"})
    assert "v1.1+" in str(exc.value)


def test_voice_adapter_outbound_call_is_v1_1_stub() -> None:
    adapter = TwilioVoiceAdapter()
    with pytest.raises(NotImplementedError) as exc:
        adapter.place_outbound_call(to="+15551112222", twiml_url="https://x")
    assert "v1.1+" in str(exc.value)


def test_voice_config_minimum_viable_trio() -> None:
    cfg = TwilioVoiceConfig()
    assert cfg.is_configured is False
    cfg2 = TwilioVoiceConfig(
        account_sid="AC1", auth_token="t", from_number="+15551112222",
    )
    assert cfg2.is_configured is True


def test_voice_adapter_verify_signature_delegates_to_validator() -> None:
    token = "tk"
    adapter = TwilioVoiceAdapter(config=TwilioVoiceConfig(
        account_sid="AC1", auth_token=token, from_number="+15551112222",
    ))
    url, params = "https://x/y", {"a": "1", "b": "2"}
    sig = _twilio_sign(token, url, params)
    assert adapter.verify_signature(url=url, params=params, signature=sig) is True
    assert adapter.verify_signature(
        url=url, params=params, signature="wrong",
    ) is False


def test_voice_adapter_unconfigured_signature_returns_false() -> None:
    adapter = TwilioVoiceAdapter()
    assert adapter.verify_signature(
        url="https://x", params={}, signature="anything",
    ) is False


def test_empty_twiml_is_wellformed_xml() -> None:
    assert EMPTY_TWIML.startswith("<?xml")
    assert "<Response>" in EMPTY_TWIML

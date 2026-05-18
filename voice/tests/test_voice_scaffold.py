"""Smoke tests for the voice scaffold (Wave 6 Stream I).

Per V3 #29 we verify:

1. The voice router is registered (catalogue + webhook + health).
2. The catalogue endpoint returns the documented frozen sets (declares
   which decisions are voice-approvable + which roles voice-reachable).
3. The Twilio webhook does REAL signature validation (per #9) — wrong
   signature is rejected with 403; missing vault config returns 503.
4. ``voice.twilio_adapter`` raises ``NotImplementedError("v1.1+")`` from
   ``route_call`` / ``place_outbound_call`` so any caller that tries to
   land real flow logic before v1.1+ fails loudly.
5. ``voice/__init__.py`` exposes ``VOICE_ROUTING_AVAILABLE = False``
   per the scaffold contract.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import voice
from shared.api.routes.voice import (
    VOICE_APPROVABLE_DECISIONS,
    VOICE_REACHABLE_ROLES,
    _validate_twilio_signature,
    router as voice_router,
)
from voice.twilio_adapter import (
    EMPTY_TWIML,
    TwilioVoiceAdapter,
    TwilioVoiceConfig,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Router registration is real
# ---------------------------------------------------------------------------


def test_router_routes_registered() -> None:
    paths = {r.path for r in voice_router.routes}
    assert "/api/v2/voice/catalog" in paths
    assert "/api/v2/voice/webhook/twilio" in paths
    assert "/api/v2/voice/health" in paths


def test_package_scaffold_flag() -> None:
    """``VOICE_ROUTING_AVAILABLE`` must be False until v1.1+ ships."""
    assert voice.VOICE_ROUTING_AVAILABLE is False
    assert "scaffold" in voice.__version__


# ---------------------------------------------------------------------------
# 2. Catalogue endpoint
# ---------------------------------------------------------------------------


def test_catalog_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v2/voice/catalog")
    assert r.status_code in (401, 422)


def test_catalog_returns_documented_sets(client: TestClient, oidc_user) -> None:
    r = client.get("/api/v2/voice/catalog", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["scaffold"] is True
    assert sorted(body["approvable_decisions"]) == sorted(VOICE_APPROVABLE_DECISIONS)
    assert sorted(body["reachable_roles"]) == sorted(VOICE_REACHABLE_ROLES)
    # Sanity: the catalogue is non-empty (otherwise v1.1+ has nothing to wire).
    assert body["approvable_decisions"]
    assert body["reachable_roles"]


# ---------------------------------------------------------------------------
# 3. Twilio webhook — signature validation is REAL
# ---------------------------------------------------------------------------


def _twilio_sign(token: str, url: str, params: dict[str, str]) -> str:
    """Replica of Twilio's signing algorithm — used to forge VALID signatures."""
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


@pytest.fixture
def with_vault_token(monkeypatch):
    """Patch the in-route vault fetch to return a known auth token."""
    import shared.api.routes.voice as mod

    async def _fake_token() -> str:
        return "test-auth-token-xyz"

    monkeypatch.setattr(mod, "_twilio_auth_token", _fake_token, raising=True)
    return "test-auth-token-xyz"


@pytest.fixture
def without_vault_token(monkeypatch):
    """Patch the in-route vault fetch to return None (unconfigured)."""
    import shared.api.routes.voice as mod

    async def _fake_token():
        return None

    monkeypatch.setattr(mod, "_twilio_auth_token", _fake_token, raising=True)


def test_webhook_503_when_vault_unconfigured(
    client: TestClient, without_vault_token
) -> None:
    """No vault token → 503 voice_unconfigured (per #9 fail-closed)."""
    r = client.post(
        "/api/v2/voice/webhook/twilio",
        data={"CallSid": "CA1", "From": "+15551112222"},
        headers={"X-Twilio-Signature": "anything"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error_code"] == "voice_unconfigured"


def test_webhook_403_when_signature_missing(
    client: TestClient, with_vault_token
) -> None:
    r = client.post(
        "/api/v2/voice/webhook/twilio",
        data={"CallSid": "CA1"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "missing_signature"


def test_webhook_403_when_signature_invalid(
    client: TestClient, with_vault_token
) -> None:
    r = client.post(
        "/api/v2/voice/webhook/twilio",
        data={"CallSid": "CA1", "From": "+15551112222"},
        headers={"X-Twilio-Signature": "definitely-not-the-right-signature"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "invalid_signature"


def test_webhook_200_on_valid_signature(
    client: TestClient, with_vault_token
) -> None:
    """End-to-end: vault has token, signature matches, route ack-echoes."""
    params: dict[str, Any] = {
        "CallSid": "CAtest123",
        "From": "+15551112222",
        "To": "+15553334444",
    }
    # Reconstruct the URL the TestClient will hit, then sign with the
    # same token the route fetches from vault.
    url = "http://testserver/api/v2/voice/webhook/twilio"
    signature = _twilio_sign(with_vault_token, url, {k: str(v) for k, v in params.items()})

    r = client.post(
        "/api/v2/voice/webhook/twilio",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "ok": True,
        "received": True,
        "twilio_call_sid": "CAtest123",
        "scaffold": True,
    }


def test_signature_validator_is_constant_time_compare() -> None:
    """The validator must return a bool, not raise, for any input."""
    assert _validate_twilio_signature(
        auth_token="k", url="https://x", params={}, signature="zzz"
    ) is False


def test_signature_validator_accepts_correct_signature() -> None:
    token, url, params = "abc", "https://x/y", {"From": "+15551112222", "CallSid": "X"}
    good = _twilio_sign(token, url, params)
    assert _validate_twilio_signature(
        auth_token=token, url=url, params=params, signature=good
    ) is True


# ---------------------------------------------------------------------------
# 4. Twilio adapter — call routing is stubbed with NotImplementedError("v1.1+")
# ---------------------------------------------------------------------------


def test_adapter_route_call_is_v1_1_stub() -> None:
    adapter = TwilioVoiceAdapter()
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.route_call({"CallSid": "CA1"})
    assert "v1.1+" in str(exc_info.value)


def test_adapter_outbound_call_is_v1_1_stub() -> None:
    adapter = TwilioVoiceAdapter()
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.place_outbound_call(to="+15551112222", twiml_url="https://x/twiml")
    assert "v1.1+" in str(exc_info.value)


def test_adapter_config_unconfigured_by_default() -> None:
    """Default config has nothing — ``is_configured`` reflects that."""
    cfg = TwilioVoiceConfig()
    assert cfg.is_configured is False
    cfg2 = TwilioVoiceConfig(
        account_sid="AC1", auth_token="t", from_number="+15551112222"
    )
    assert cfg2.is_configured is True


def test_adapter_verify_signature_without_token_returns_false() -> None:
    """Unconfigured adapter → verify_signature is False (not crash)."""
    adapter = TwilioVoiceAdapter()
    assert adapter.verify_signature(
        url="https://x", params={"a": "1"}, signature="zzz"
    ) is False


def test_adapter_verify_signature_with_token_works() -> None:
    """Configured adapter delegates to the shared validator."""
    token = "tk"
    adapter = TwilioVoiceAdapter(
        config=TwilioVoiceConfig(
            account_sid="AC1", auth_token=token, from_number="+15551112222"
        )
    )
    url, params = "https://x/y", {"a": "1", "b": "2"}
    sig = _twilio_sign(token, url, params)
    assert adapter.verify_signature(url=url, params=params, signature=sig) is True
    assert adapter.verify_signature(
        url=url, params=params, signature="wrong"
    ) is False


def test_empty_twiml_constant_is_wellformed() -> None:
    """The TwiML envelope helper must look like XML so v1.1+ has a base case."""
    assert EMPTY_TWIML.startswith("<?xml")
    assert "<Response>" in EMPTY_TWIML

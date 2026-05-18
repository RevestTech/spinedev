"""``/api/v2/voice`` — voice-integration interface + Twilio webhook receiver
(#29 — voice/phone SCAFFOLD).

Per V3 design decision #29, v1.0 ships **the contract** for voice flows,
not the flows themselves. Actual call routing — DTMF capture, TwiML
flows, voice biometric, the Master-CTO callable-for-incidents pattern —
lands in v1.1+ once customer demand surfaces (see ``voice/README.md``).

Two surfaces, both deliberately thin:

1. **Voice-integration interface** — declares WHICH decisions are
   voice-approvable and WHICH roles are voice-reachable. Native voice
   front-ends (Twilio's Programmable Voice + Studio) read this catalogue
   to render the IVR menu structure. Source-of-truth lives here so the
   web Hub, the SPA, and the IVR all agree.

2. **Twilio webhook receiver scaffold** — accepts Twilio's
   ``application/x-www-form-urlencoded`` voice webhooks (status callbacks,
   inbound call notifications), validates the signature, and returns
   ``NotImplementedError`` for actual TwiML responses. The signature-
   validation path is real (#9 — vault-only secrets, real crypto); only
   the call-routing payload is stubbed.

Endpoints
---------

* ``GET  /api/v2/voice/catalog``             — voice-approvable decisions + reachable roles
* ``POST /api/v2/voice/webhook/twilio``      — Twilio Programmable Voice webhook receiver
* ``GET  /api/v2/voice/health``              — scaffold health (always 200 with ``scaffold=True``)

Auth contract:

* ``GET /catalog`` requires Keycloak Bearer (per #25). It's a
  configuration surface that exposes role identifiers; only authenticated
  users see it.
* ``POST /webhook/twilio`` does NOT use Keycloak — Twilio cannot present
  a Bearer token. It uses **Twilio's request signature** (HMAC-SHA1 of
  the URL + body params, signed with the vault-stored auth token) per
  Twilio's documented webhook security model. Reject with 403 if the
  signature header is missing or invalid.

Cite-or-Refuse note (#12): when ``voice_approve_decision`` lands as an
MCP tool (v1.1+, ``shared/mcp/tools/voice.py``), it MUST be registered
with ``requires_citation=True`` — voice-approving a critical decision
without an audit citation is exactly the failure mode the contract was
written to prevent.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import current_user
from shared.identity.models import User

logger = logging.getLogger("spine.api.voice")
router = APIRouter(prefix="/api/v2/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Catalogue — which decisions are voice-approvable + which roles voice-reachable
# ---------------------------------------------------------------------------

#: Decision classes that are SAFE to expose via voice in v1.1+. Approval
#: + briefing classes are easy ("press 1 to approve"); incident/release/
#: budget/policy_change are higher-stakes and need DTMF confirmation
#: AND voice-print verification before they land in the catalogue.
VOICE_APPROVABLE_DECISIONS: frozenset[str] = frozenset(
    {
        "approval",   # press-1-to-approve flow
        "briefing",   # listen-and-acknowledge flow
        "incident",   # Master CTO callable-for-incidents (likely v1.1 first flow)
    }
)

#: Role identifiers that are reachable by voice in v1.1+ — i.e. the
#: customer can phone the Hub and ask to speak to one of these roles.
#: Listed roles are TTS-rendered from their charter prompts via the LLM.
VOICE_REACHABLE_ROLES: frozenset[str] = frozenset(
    {
        # Master roles — most likely to be paged out-of-hours
        "conductor",
        "architect",
        "security_engineer",
        "devops",
        "release_manager",
        # On-call support
        "customer_support",
        "operator",
    }
)


class VoiceCatalog(BaseModel):
    """``GET /voice/catalog`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    approvable_decisions: list[str] = Field(
        ..., description="decision classes safe to voice-approve in v1.1+"
    )
    reachable_roles: list[str] = Field(
        ..., description="role IDs the caller may ask to speak to via IVR"
    )
    scaffold: bool = Field(
        True,
        description="True until v1.1+ ships actual call routing (#29)",
    )


class VoiceWebhookEcho(BaseModel):
    """Scaffold response — Twilio expects TwiML in production, but
    the v1.0 scaffold returns a JSON envelope so smoke tests can assert.

    v1.1+ will return ``Content-Type: application/xml`` with a TwiML
    payload (``<Response><Say>...</Say></Response>``) per Twilio's
    Programmable Voice protocol.
    """

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    received: bool = True
    twilio_call_sid: Optional[str] = None
    scaffold: bool = True


# ---------------------------------------------------------------------------
# Twilio signature validation — REAL (per #9), wrapped for testability
# ---------------------------------------------------------------------------


async def _twilio_auth_token() -> str | None:
    """Fetch the Twilio auth token from vault.

    Per #9 (vault-only secrets), the auth token is NEVER read from env
    vars holding the secret value — only ever from the vault adapter.
    The vault PATH may be overridden by env (``SPINE_TWILIO_AUTH_VAULT_PATH``)
    but the SECRET is always vault-resident.

    Returns ``None`` if the vault entry is missing (Hub still starting,
    or operator hasn't run the install wizard yet); callers handle that
    as a 503-style "voice not configured" state.
    """
    try:
        from shared.secrets import get_secret  # noqa: PLC0415
    except Exception:  # pragma: no cover - py_compile guard
        return None
    try:
        return await get_secret("notify/twilio/auth_token")
    except Exception as exc:  # noqa: BLE001
        logger.warning("twilio_auth_token_missing", extra={"error": str(exc)})
        return None


def _validate_twilio_signature(
    *,
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str,
) -> bool:
    """Validate Twilio's request signature.

    Twilio signs every webhook with HMAC-SHA1 over ``url + concat(sorted(
    POST params))``, then base64-encodes the digest and sends it in
    ``X-Twilio-Signature``. We re-compute and compare in constant time.

    Standard Twilio algorithm (per
    https://www.twilio.com/docs/usage/webhooks/webhooks-security):

      data = url + ''.join(f'{k}{v}' for k, v in sorted(params.items()))
      digest = hmac_sha1(auth_token, data)
      expected = base64(digest)

    Returns ``True`` iff the supplied signature matches.
    """
    import base64
    import hashlib
    import hmac

    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(
        auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/catalog", response_model=VoiceCatalog)
async def voice_catalog(
    user: Annotated[User, Depends(current_user)],
) -> VoiceCatalog:
    """Return the voice-integration interface — what's reachable how.

    Consumed by:

    * the Hub SPA (renders a per-user "voice settings" panel),
    * the Twilio Studio IVR flow definition (v1.1+),
    * native mobile apps that surface "call your team" affordances.
    """
    return VoiceCatalog(
        approvable_decisions=sorted(VOICE_APPROVABLE_DECISIONS),
        reachable_roles=sorted(VOICE_REACHABLE_ROLES),
    )


@router.post("/webhook/twilio", response_model=VoiceWebhookEcho)
async def twilio_webhook(request: Request) -> VoiceWebhookEcho:
    """Receive a Twilio Programmable Voice webhook.

    Validation is REAL (per #9) — Twilio's signature is verified against
    the vault-stored auth token. Actual call routing (TwiML response,
    DTMF capture, role dispatch) is **not** implemented; the adapter at
    ``voice/twilio_adapter.py`` raises ``NotImplementedError("v1.1+")``.

    Returns the scaffold echo envelope so smoke tests can assert
    "webhook arrived + signature verified + route registered". v1.1+
    will return TwiML XML here.
    """
    auth_token = await _twilio_auth_token()
    if not auth_token:
        # No auth token in vault → Hub can't validate; refuse loudly so
        # an unconfigured Hub doesn't accept spoofed Twilio calls.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "voice_unconfigured",
                "message": "Twilio auth token not present in vault; "
                "run the install wizard or set notify/twilio/auth_token.",
            },
        )

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "missing_signature",
                "message": "X-Twilio-Signature header required",
            },
        )

    # Twilio sends voice webhooks as application/x-www-form-urlencoded.
    form = await request.form()
    params: dict[str, str] = {k: str(v) for k, v in form.items()}

    # Reconstruct the URL Twilio signed — must match exactly (scheme +
    # host + path + query) including any trailing slash.
    url = str(request.url)

    if not _validate_twilio_signature(
        auth_token=auth_token, url=url, params=params, signature=signature
    ):
        logger.warning(
            "twilio_signature_invalid",
            extra={"url": url, "param_count": len(params)},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "invalid_signature",
                "message": "Twilio signature did not match vault-stored auth token",
            },
        )

    call_sid = params.get("CallSid")
    logger.info(
        "twilio_webhook_received",
        extra={
            "call_sid": call_sid,
            "from": params.get("From"),
            "to": params.get("To"),
            "scaffold": True,
        },
    )

    # v1.1+ will hand off to voice/twilio_adapter.route_call(params)
    # which produces TwiML. For v1.0 we acknowledge receipt only.
    return VoiceWebhookEcho(received=True, twilio_call_sid=call_sid)


@router.get("/health")
async def voice_health() -> dict[str, Any]:
    """Scaffold health endpoint — always 200, ``scaffold=True``.

    Public (no auth) so Twilio's status pingers can hit it without
    needing OIDC tokens. Returns no sensitive data.
    """
    has_token = bool(await _twilio_auth_token())
    return {
        "ok": True,
        "scaffold": True,
        "voice_configured": has_token,
        "approvable_decisions": len(VOICE_APPROVABLE_DECISIONS),
        "reachable_roles": len(VOICE_REACHABLE_ROLES),
    }


__all__ = [
    "router",
    "VoiceCatalog",
    "VoiceWebhookEcho",
    "VOICE_APPROVABLE_DECISIONS",
    "VOICE_REACHABLE_ROLES",
    "_validate_twilio_signature",
]

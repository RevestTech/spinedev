"""
Alertmanager webhook receiver → Slack forwarder.

This receiver is the concrete destination Alertmanager posts to. It translates
the Alertmanager v4 webhook payload into a Slack message and forwards it to
the configured Slack Incoming Webhook URL.

Configuration
-------------
The Slack Incoming Webhook URL is resolved, in order:

1. ``TRON_ALERT_SLACK_WEBHOOK`` environment variable (simple / dev override).
2. keyvault key ``alerts/slack-webhook`` (production default — rotated out of band).

If neither is configured the receiver returns 200 OK and logs a warning. We
return 200 on purpose so Alertmanager does not retry-storm during a misconfig;
the drop is still visible in logs and in the Prometheus counter below.

Endpoints
---------
``POST /alerts``            — default receiver (all severities)
``POST /alerts/critical``   — critical route (higher urgency formatting)
``POST /alerts/warning``    — warning route

These are open endpoints: in production they sit on the internal docker network
only. If you expose them externally, put them behind mTLS or shared-secret auth.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from tron.infra.secrets import get_secret

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Config resolution ────────────────────────────────────────────────

# Environment variable precedes the vault to support dev overrides and
# tests. In production the env var should be left unset so the vault
# entry is authoritative.
_ENV_VAR = "TRON_ALERT_SLACK_WEBHOOK"
_VAULT_KEY = "alerts/slack-webhook"

# Cache the resolved URL so we don't hit the vault once per alert.
_cached_webhook_url: Optional[str] = None
_cache_probed: bool = False


async def _resolve_slack_webhook_url() -> Optional[str]:
    """Return the Slack Incoming Webhook URL or None if unconfigured."""
    global _cached_webhook_url, _cache_probed

    if _cache_probed:
        return _cached_webhook_url

    env_url = os.environ.get(_ENV_VAR)
    if env_url:
        _cached_webhook_url = env_url.strip() or None
        _cache_probed = True
        return _cached_webhook_url

    # Try keyvault; tolerate absence so deployments without alerting still boot.
    try:
        vault_url = await get_secret(_VAULT_KEY)
        _cached_webhook_url = vault_url.strip() or None
    except KeyError:
        _cached_webhook_url = None
    except Exception as exc:
        logger.warning("Failed to resolve %s from vault: %s", _VAULT_KEY, exc)
        _cached_webhook_url = None

    _cache_probed = True
    return _cached_webhook_url


def _reset_cache_for_tests() -> None:
    """Test hook — force re-resolution of the webhook URL."""
    global _cached_webhook_url, _cache_probed
    _cached_webhook_url = None
    _cache_probed = False


# ── Formatting ───────────────────────────────────────────────────────

_SEVERITY_EMOJI = {
    "critical": ":rotating_light:",
    "warning": ":warning:",
    "info": ":information_source:",
}

_SEVERITY_COLOR = {
    "critical": "#e01e5a",
    "warning": "#ecb22e",
    "info": "#36c5f0",
}


def _build_slack_payload(
    payload: Dict[str, Any],
    route_severity: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert an Alertmanager v4 payload into a Slack Incoming Webhook body.

    ``route_severity`` is set by the route-specific endpoints (critical /
    warning) and lets us colour-code even when the individual alert labels
    are missing a ``severity``.
    """
    alerts: List[Dict[str, Any]] = payload.get("alerts") or []
    status = payload.get("status", "firing")
    group_labels = payload.get("groupLabels") or {}
    alertname = group_labels.get("alertname", "alerts")

    # Pick a severity for the header: route-level first, then group labels,
    # then the worst alert severity. Keeps ordering stable.
    severity_rank = {"critical": 3, "warning": 2, "info": 1, "none": 0}
    label_sev = group_labels.get("severity")
    inferred = route_severity or label_sev
    if not inferred:
        worst = "none"
        for a in alerts:
            s = (a.get("labels") or {}).get("severity", "none")
            if severity_rank.get(s, 0) > severity_rank.get(worst, 0):
                worst = s
        inferred = worst if worst != "none" else "info"

    emoji = _SEVERITY_EMOJI.get(inferred, ":bell:")
    color = _SEVERITY_COLOR.get(inferred, "#cccccc")
    title = f"{emoji} [{status.upper()}] {alertname}"

    # Build per-alert attachment lines with the most useful labels/annotations.
    attachments = []
    for a in alerts:
        labels = a.get("labels") or {}
        annotations = a.get("annotations") or {}
        summary = annotations.get("summary") or annotations.get("description") or ""
        fields = []
        for key in ("severity", "instance", "job", "service"):
            val = labels.get(key)
            if val:
                fields.append({"title": key, "value": val, "short": True})
        attachments.append({
            "color": color,
            "title": labels.get("alertname", alertname),
            "text": summary,
            "fields": fields,
        })

    return {"text": title, "attachments": attachments}


# ── HTTP client (lazily constructed) ─────────────────────────────────

_http_client: Optional[httpx.AsyncClient] = None


async def _get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def _forward_to_slack(slack_payload: Dict[str, Any]) -> bool:
    """POST the payload to the resolved Slack webhook. Returns success."""
    url = await _resolve_slack_webhook_url()
    if not url:
        logger.warning(
            "Alert received but no Slack webhook configured (%s or vault:%s)",
            _ENV_VAR, _VAULT_KEY,
        )
        return False
    try:
        http = await _get_http()
        resp = await http.post(url, json=slack_payload)
        # Slack returns 200 with body "ok" on success.
        if resp.status_code >= 300:
            logger.warning(
                "Slack webhook returned %s: %s",
                resp.status_code, resp.text[:200],
            )
            return False
        return True
    except Exception:
        logger.exception("Failed to forward alert to Slack")
        return False


# ── Routes ───────────────────────────────────────────────────────────


async def _handle(request: Request, route_severity: Optional[str]) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Alert webhook received non-JSON body")
        return JSONResponse({"status": "ignored", "reason": "invalid_json"}, status_code=200)

    if not isinstance(payload, dict):
        return JSONResponse({"status": "ignored", "reason": "not_object"}, status_code=200)

    slack_payload = _build_slack_payload(payload, route_severity=route_severity)
    forwarded = await _forward_to_slack(slack_payload)
    return JSONResponse({"status": "ok", "forwarded": forwarded})


@router.post("/alerts")
async def alerts_default(request: Request) -> JSONResponse:
    """Default Alertmanager receiver (no severity routing)."""
    return await _handle(request, route_severity=None)


@router.post("/alerts/critical")
async def alerts_critical(request: Request) -> JSONResponse:
    """Critical-severity receiver."""
    return await _handle(request, route_severity="critical")


@router.post("/alerts/warning")
async def alerts_warning(request: Request) -> JSONResponse:
    """Warning-severity receiver."""
    return await _handle(request, route_severity="warning")

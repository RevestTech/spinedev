"""
Outbound webhook on audit completion (#7).

When a project has ``audit_webhook_url`` set, Tron POSTs a summary of
each completed (or failed) audit to that URL. Customers wire their own
Slack / Linear / Jira / PagerDuty / whatever without us building bespoke
integrations for each of those.

Body shape (versioned via ``schema_version``):

    {
      "schema_version": 1,
      "event": "audit.completed" | "audit.failed",
      "audit_run_id": "uuid",
      "project_id": "uuid",
      "project_name": "string",
      "status": "completed" | "failed",
      "started_at": "iso8601",
      "completed_at": "iso8601" | null,
      "duration_seconds": float,
      "findings": {
        "total": int,
        "critical": int,
        "high": int,
        "medium": int,
        "low": int
      },
      "diff": {  // present only for diff-mode audits
        "base_ref": "string" | null,
        "head_ref": "string" | null,
        "files_count": int
      } | null,
      "tron_audit_url": "string" // browser link to the audit in Tron
    }

Signing
-------
When ``audit_webhook_secret_id`` resolves to a keyvault entry, the body
is HMAC-SHA256-signed and the hex digest goes in ``X-Tron-Signature``
(``sha256=<hex>``). Receivers MUST verify the signature before trusting
the body — otherwise anyone who learns the URL can forge events.

Delivery
--------
Best-effort with bounded retries (3 attempts, exponential backoff).
A single bad receiver should NEVER block an audit's completion path,
so this runs as a fire-and-forget task with a 10s per-request timeout
and total 60s budget. Failures are logged but never re-raised.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import timezone
from typing import Any, Dict, Optional

import httpx

from tron.api.config import settings
from tron.domain.models import AuditRun, Project

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_ATTEMPTS = 3


# ── Public payload model — receivers can use this to validate ─────────────
#
# Importing here is deferred so this module stays import-cheap (it sits on
# the audit-completion hot path). The model is exported via
# ``tron/api/routes/integrations.py`` as a JSON Schema for customer
# integrations.

from pydantic import BaseModel, Field as _Field  # noqa: E402


class AuditWebhookFindings(BaseModel):
    total: int
    critical: int
    high: int
    medium: int
    low: int


class AuditWebhookDiff(BaseModel):
    base_ref: Optional[str]
    head_ref: Optional[str]
    files_count: int


class AuditWebhookPayload(BaseModel):
    """Public schema for the outbound audit webhook body.

    The matching JSON Schema is exposed at
    ``GET /api/integrations/audit-webhook/schema`` so receivers can
    validate incoming events without depending on an SDK. Bumping
    ``schema_version`` is a breaking change — receivers should be
    warned a release ahead.
    """

    schema_version: int = _Field(
        default=SCHEMA_VERSION,
        description="Schema version of this payload. Increment on breaking changes.",
    )
    event: str = _Field(
        description="``audit.completed`` or ``audit.failed``.",
    )
    audit_run_id: str = _Field(description="UUID of the audit run.")
    project_id: str = _Field(description="UUID of the Tron project.")
    project_name: str
    status: str = _Field(description="``completed`` or ``failed``.")
    started_at: Optional[str] = _Field(
        description="ISO-8601 timestamp the audit started.",
    )
    completed_at: Optional[str] = _Field(
        description="ISO-8601 timestamp the audit reached a terminal state.",
    )
    duration_seconds: float
    findings: AuditWebhookFindings
    diff: Optional[AuditWebhookDiff] = _Field(
        default=None,
        description="Present only for diff-mode audits (PR gates).",
    )
    tron_audit_url: str = _Field(
        description="Browser link to the audit detail page in Tron.",
    )


def _build_payload(
    *,
    event: str,
    audit: AuditRun,
    project: Project,
) -> Dict[str, Any]:
    duration: float = 0.0
    if audit.started_at and audit.completed_at:
        duration = (audit.completed_at - audit.started_at).total_seconds()

    diff_block: Optional[Dict[str, Any]] = None
    diff_files = audit.diff_files_json
    if diff_files is not None:
        diff_block = {
            "base_ref": audit.diff_base_ref,
            "head_ref": audit.diff_head_ref,
            "files_count": len(diff_files) if isinstance(diff_files, list) else 0,
        }

    audit_url = f"{settings.tron_ui_base}/audits/{audit.id}"

    return {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "audit_run_id": str(audit.id),
        "project_id": str(project.id),
        "project_name": project.name,
        "status": audit.status,
        "started_at": (
            audit.started_at.replace(tzinfo=timezone.utc).isoformat()
            if audit.started_at and audit.started_at.tzinfo is None
            else (audit.started_at.isoformat() if audit.started_at else None)
        ),
        "completed_at": (
            audit.completed_at.isoformat() if audit.completed_at else None
        ),
        "duration_seconds": duration,
        "findings": {
            "total": audit.findings_total or 0,
            "critical": audit.findings_critical or 0,
            "high": audit.findings_high or 0,
            "medium": audit.findings_medium or 0,
            "low": audit.findings_low or 0,
        },
        "diff": diff_block,
        "tron_audit_url": audit_url,
    }


def _sign_body(body_bytes: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


async def _post_with_retries(
    url: str, body_bytes: bytes, headers: Dict[str, str]
) -> bool:
    """POST with bounded retries on 5xx and timeouts. Returns True on 2xx."""
    backoff = 1.0
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(url, content=body_bytes, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.info(
                        "Audit webhook delivered (%d) on attempt %d",
                        resp.status_code, attempt,
                    )
                    return True
                # 4xx is the receiver's fault — don't retry, log and bail.
                if 400 <= resp.status_code < 500:
                    logger.warning(
                        "Audit webhook 4xx (%d) — not retrying: %s",
                        resp.status_code, resp.text[:200],
                    )
                    return False
                logger.warning(
                    "Audit webhook %d on attempt %d — will retry",
                    resp.status_code, attempt,
                )
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                logger.warning(
                    "Audit webhook attempt %d failed: %s", attempt, exc
                )

            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(backoff)
                backoff *= 2

    logger.error("Audit webhook gave up after %d attempts: %s", _MAX_ATTEMPTS, url)
    return False


async def fire_audit_webhook(
    *,
    event: str,
    audit: AuditRun,
    project: Project,
    secrets: Optional[Dict[str, str]] = None,
) -> bool:
    """Fire a project's outbound webhook for an audit event.

    Returns True if delivery succeeded, False otherwise. Never raises —
    audit completion must not be blocked by webhook problems.

    ``event`` is ``"audit.completed"`` or ``"audit.failed"``.

    ``secrets`` should contain the keyvault entry referenced by
    ``project.audit_webhook_secret_id`` if signing is desired. Pass
    ``None`` (or an empty dict) for unsigned delivery.
    """
    url = (project.audit_webhook_url or "").strip()
    if not url:
        return False  # webhook not configured — silent skip

    payload = _build_payload(event=event, audit=audit, project=project)
    body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "Tron-Audit-Webhook/1.0",
        "X-Tron-Event": event,
        "X-Tron-Audit-Run-Id": str(audit.id),
        "X-Tron-Schema-Version": str(SCHEMA_VERSION),
    }

    secret_id = (project.audit_webhook_secret_id or "").strip()
    if secret_id:
        # NB: don't short-circuit on `if secrets` — an empty dict is falsy
        # but the project IS configured for signing. Emit the warning.
        secret = (secrets or {}).get(secret_id)
        if secret:
            headers["X-Tron-Signature"] = _sign_body(body_bytes, secret)
        else:
            # Configured but secret not present — log and proceed unsigned.
            # Better noisy + delivered than silent + dropped.
            logger.warning(
                "Project %s audit_webhook_secret_id=%s not in secrets; "
                "delivering UNSIGNED",
                project.id, secret_id,
            )

    try:
        return await _post_with_retries(url, body_bytes, headers)
    except Exception:
        logger.exception("Audit webhook fired with unexpected failure")
        return False


def make_test_signature(body: bytes, secret: str) -> str:
    """Public helper for tests / customer verification examples.

    Receivers should compare ``X-Tron-Signature`` to
    ``make_test_signature(raw_body, shared_secret)`` using
    ``hmac.compare_digest``. Exposed so client-side example code can
    import this directly.
    """
    return _sign_body(body, secret)

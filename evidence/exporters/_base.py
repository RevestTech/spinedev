"""Shared base for evidence exporters.

Each concrete exporter only has to provide:
  * ``EXPORTER_NAME`` — one of the V25 ``exporter`` CHECK values.
  * ``DEFAULT_URL``  — fallback endpoint when the vault doesn't carry
    an override.
  * ``_render_batch(payloads)`` → ``bytes`` — vendor-specific body.

The base class handles:
  * Secret fetch via ``shared.secrets.get_secret`` (with sync wrapper for
    callers that are not in an event loop yet).
  * HTTP POST via ``urllib.request`` (no requests dep — matches the
    existing ``shared.audit.exporter`` HTTP sink).
  * One ``ExportResult`` per call, always returned, plus a best-effort
    ``spine_evidence.export_log`` INSERT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, Optional

from evidence._types import EvidencePayload, ExportResult, ExporterName

logger = logging.getLogger(__name__)

#: Top-level vault prefix every exporter reads under.
#:
#:   evidence/vanta/api_key
#:   evidence/vanta/api_url    (optional)
#:   evidence/drata/api_key
#:   evidence/drata/api_url    (optional)
#:   evidence/secureframe/api_key
#:   evidence/secureframe/api_url (optional)
#:   evidence/tugboat/api_key      (stub; v1.1+)
#:   evidence/strikegraph/api_key  (stub; v1.1+)
#:   evidence/thoropass/api_key    (stub; v1.1+)
EVIDENCE_VAULT_PREFIX = "evidence"


def _run_sync(coro: Any) -> Any:
    """Sync→async bridge mirroring shared.mcp.tools.verify._run_async."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _fetch_secret(path: str) -> str:
    """Fetch a secret value via shared.secrets — fresh on every call.

    Per #9 the returned string lives only as long as the caller's HTTP
    request. ``shared.secrets`` is the ONLY module in Spine that may
    read secret values from any backend.

    Wave 3.5 FIX2 unified path: delegates to
    :func:`shared.integrations.fetch_secret` (async) wrapped with
    :func:`_run_sync` so every integration adapter — including the
    evidence exporters here — uses one canonical secret-fetch helper.
    Returns ``""`` (not ``None``) when the vault entry is missing,
    matching the prior contract that downstream exporters relied on.
    """
    from shared.integrations import fetch_secret as _async_fetch  # noqa: PLC0415

    value = _run_sync(_async_fetch(path))
    return value or ""


def _log_export(result: ExportResult, db_url: Optional[str] = None) -> None:
    """Append one row to ``spine_evidence.export_log`` per #24.

    Best-effort: if psql is unavailable (test env) we log a warning and
    return. The export itself already happened — the log row is
    auditor-facing observability, not the source of truth.
    """
    url = db_url or os.environ.get("SPINE_DB_URL")
    if not url:
        logger.debug("export_log: SPINE_DB_URL not set; skipping log row")
        return
    err_lit = "NULL" if result.error is None else "'" + result.error.replace("'", "''")[:1000] + "'"
    status_lit = "NULL" if result.response_status is None else str(int(result.response_status))
    sql = (
        "INSERT INTO spine_evidence.export_log "
        "(exporter, target_url, records_count, exported_at, "
        " response_status, error) VALUES ("
        f"'{result.exporter}', "
        f"'{result.target_url.replace(chr(39), chr(39)*2)}', "
        f"{int(result.records_count)}, "
        f"'{result.exported_at.isoformat()}'::timestamptz, "
        f"{status_lit}, {err_lit});"
    )
    try:
        subprocess.run(
            ["psql", url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
            check=True, capture_output=True, text=True,
        )
    except Exception as exc:  # pragma: no cover - best-effort log
        logger.warning("export_log insert failed: %s", exc)


class BaseExporter:
    """Common scaffolding for every concrete exporter."""

    EXPORTER_NAME: ExporterName = "vanta"  # overridden in subclasses
    DEFAULT_URL: str = ""
    #: When True ``send()`` raises NotImplementedError("v1.1+"). Used by
    #: the three v1.1+ stub exporters per V3 #24.
    STUB_V1_1: bool = False

    def __init__(self, *, vault_prefix: Optional[str] = None,
                 timeout_sec: int = 30) -> None:
        self.vault_prefix = (vault_prefix or
                             f"{EVIDENCE_VAULT_PREFIX}/{self.EXPORTER_NAME}")
        self.timeout_sec = timeout_sec

    # ── credentials ────────────────────────────────────────────────────
    def _api_key(self) -> str:
        return _fetch_secret(f"{self.vault_prefix}/api_key")

    def _target_url(self) -> str:
        """Try vault for an override; fall back to DEFAULT_URL.

        URL override is OPTIONAL — most deployments will use the default
        cloud endpoint. Override is supported for sandbox / on-prem /
        air-gapped GRC instances.
        """
        try:
            return _fetch_secret(f"{self.vault_prefix}/api_url")
        except Exception:  # any backend error → use default
            return self.DEFAULT_URL

    # ── vendor-specific (override in subclass) ─────────────────────────
    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        """Render the batch to a vendor-specific HTTP body."""
        records = [
            {
                "framework": p.framework,
                "control_id": p.control_id,
                "evidence_type": p.evidence_type,
                "source_audit_record_id": p.source_audit_record_id,
                "collected_at": p.collected_at.isoformat(),
                "payload": p.body,
            }
            for p in payloads
        ]
        return json.dumps({"records": records}).encode("utf-8")

    def _auth_headers(self, api_key: str) -> dict[str, str]:
        """Default = Bearer auth; vendors override if they want a header name."""
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Spine-Evidence/1.0",
        }

    # ── transport ──────────────────────────────────────────────────────
    def send(self, payloads: list[EvidencePayload], *,
             http_client: Any = None, log_db_url: Optional[str] = None) -> ExportResult:
        """POST the batch to the vendor; record one ExportResult.

        ``http_client`` is a test injection seam — if provided the
        function calls ``http_client(url, body, headers, timeout)`` and
        expects a ``(status_int, response_bytes)`` tuple back. Otherwise
        a stdlib ``urllib.request`` POST is made.
        """
        if self.STUB_V1_1:
            raise NotImplementedError(
                f"{self.EXPORTER_NAME} exporter is v1.1+ (per V3 #24 — "
                "Vanta + Drata + Secureframe Day 1; Tugboat / Strike Graph / "
                "Thoropass v1.1+). Config + auth are wired; promote to real "
                "send() in v1.1."
            )
        target = self._target_url()
        body = self._render_batch(payloads)
        api_key = self._api_key()
        headers = self._auth_headers(api_key)
        status: Optional[int] = None
        err: Optional[str] = None
        ok = False
        try:
            if http_client is not None:
                status, _ = http_client(target, body, headers, self.timeout_sec)
            else:  # pragma: no cover - real HTTP path
                req = urllib.request.Request(
                    target, data=body, method="POST", headers=headers,
                )
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:  # noqa: S310
                    status = resp.status
            ok = bool(status and 200 <= status < 300)
        except urllib.error.HTTPError as exc:  # pragma: no cover
            status = exc.code
            err = f"HTTPError {exc.code}: {exc.reason}"
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
        finally:
            # Drop the key reference from local frame immediately (#9).
            api_key = ""  # noqa: F841

        result = ExportResult(
            exporter=self.EXPORTER_NAME,
            target_url=target,
            records_count=len(payloads),
            response_status=status,
            success=ok,
            error=err,
        )
        _log_export(result, db_url=log_db_url)
        return result


__all__ = ["BaseExporter", "EVIDENCE_VAULT_PREFIX"]

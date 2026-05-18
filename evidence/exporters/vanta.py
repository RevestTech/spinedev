"""Vanta evidence exporter (V3 #24 Day-1 real implementation).

Vault paths:
  * ``evidence/vanta/api_key`` (required) — Vanta API bearer token.
  * ``evidence/vanta/api_url`` (optional) — endpoint override, e.g.
    Vanta EU region or sandbox tenant.

Default endpoint: ``https://api.vanta.com/v1/evidence``.

Wire format: ``{"evidence_records": [...], "spine_meta": {"exporter":
"spine-1.0"}}`` — Vanta's public ingestion endpoint accepts a JSON
array under the ``evidence_records`` key. Each record carries the
framework/control_id mapping plus the inline body, which is what Vanta's
UI surfaces under the matching control in the customer's tenant.

Per #9 the API key is fetched fresh on every ``send()`` call and never
persisted on the exporter instance.
"""
from __future__ import annotations

import json
from typing import Any

from evidence._types import EvidencePayload
from evidence.exporters._base import BaseExporter


class VantaExporter(BaseExporter):
    EXPORTER_NAME = "vanta"
    DEFAULT_URL = "https://api.vanta.com/v1/evidence"

    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        records = [
            {
                "framework": p.framework,
                "controlId": p.control_id,                  # Vanta camelCase
                "evidenceType": p.evidence_type,
                "sourceAuditRecordId": p.source_audit_record_id,
                "collectedAt": p.collected_at.isoformat(),
                "body": p.body,
            }
            for p in payloads
        ]
        return json.dumps({
            "evidence_records": records,
            "spine_meta": {"exporter": "spine-1.0"},
        }).encode("utf-8")

    def _auth_headers(self, api_key: str) -> dict[str, str]:
        # Vanta uses Bearer token auth on its public REST API.
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Spine-Evidence/1.0 (vanta)",
        }


send: Any = VantaExporter().send  # convenience handle for one-shot callers

__all__ = ["VantaExporter", "send"]

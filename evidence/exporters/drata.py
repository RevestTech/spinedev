"""Drata evidence exporter (V3 #24 Day-1 real implementation).

Vault paths:
  * ``evidence/drata/api_key`` (required) — Drata API bearer token.
  * ``evidence/drata/api_url`` (optional) — endpoint override.

Default endpoint: ``https://api.drata.com/public/v1/evidence``.

Wire format mirrors Drata's public API: a top-level ``evidence`` array
with framework + control mapping + evidence body. Drata's UI surfaces
this on the matching control card in the customer's tenant.

Per #9 the API key is fetched fresh per ``send()``.
"""
from __future__ import annotations

import json
from typing import Any

from evidence._types import EvidencePayload
from evidence.exporters._base import BaseExporter


class DrataExporter(BaseExporter):
    EXPORTER_NAME = "drata"
    DEFAULT_URL = "https://api.drata.com/public/v1/evidence"

    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        items = [
            {
                "framework": p.framework,
                "control_id": p.control_id,
                "evidence_type": p.evidence_type,
                "source_audit_record_id": p.source_audit_record_id,
                "collected_at": p.collected_at.isoformat(),
                "body": p.body,
            }
            for p in payloads
        ]
        return json.dumps({
            "evidence": items,
            "spine_meta": {"exporter": "spine-1.0"},
        }).encode("utf-8")

    def _auth_headers(self, api_key: str) -> dict[str, str]:
        # Drata's public API documents an `Authorization: Bearer ...` scheme.
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Spine-Evidence/1.0 (drata)",
        }


send: Any = DrataExporter().send

__all__ = ["DrataExporter", "send"]

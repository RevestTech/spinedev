"""Secureframe evidence exporter (V3 #24 Day-1 real implementation).

Vault paths:
  * ``evidence/secureframe/api_key`` (required) — Secureframe API token.
  * ``evidence/secureframe/api_url`` (optional) — endpoint override.

Default endpoint:
``https://api.secureframe.com/v1/evidence_collections``.

Secureframe groups evidence under an ``evidence_collection`` per
control. We render one ``evidence_collection`` block per (framework,
control_id) pair so the vendor UI can fan out to the right control card
without server-side reshaping.

Per #9 the API key is fetched fresh per ``send()``.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from evidence._types import EvidencePayload
from evidence.exporters._base import BaseExporter


class SecureframeExporter(BaseExporter):
    EXPORTER_NAME = "secureframe"
    DEFAULT_URL = "https://api.secureframe.com/v1/evidence_collections"

    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        grouped: dict[tuple[str, str], list[EvidencePayload]] = defaultdict(list)
        for p in payloads:
            grouped[(p.framework, p.control_id)].append(p)
        collections = [
            {
                "framework": fw,
                "control_id": cid,
                "items": [
                    {
                        "evidence_type": p.evidence_type,
                        "source_audit_record_id": p.source_audit_record_id,
                        "collected_at": p.collected_at.isoformat(),
                        "body": p.body,
                    }
                    for p in items
                ],
            }
            for (fw, cid), items in grouped.items()
        ]
        return json.dumps({
            "evidence_collections": collections,
            "spine_meta": {"exporter": "spine-1.0"},
        }).encode("utf-8")

    def _auth_headers(self, api_key: str) -> dict[str, str]:
        # Secureframe's public API uses an `Authorization: Bearer` token.
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Spine-Evidence/1.0 (secureframe)",
        }


send: Any = SecureframeExporter().send

__all__ = ["SecureframeExporter", "send"]

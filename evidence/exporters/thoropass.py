"""Thoropass evidence exporter — v1.1+ STUB (see tugboat.py header).

Vault paths:
  * ``evidence/thoropass/api_key`` (required at v1.1)
  * ``evidence/thoropass/api_url`` (optional override)

``send()`` raises ``NotImplementedError("v1.1+")`` per V3 #24.
"""
from __future__ import annotations

import json
from typing import Any

from evidence._types import EvidencePayload
from evidence.exporters._base import BaseExporter


class ThoropassExporter(BaseExporter):
    EXPORTER_NAME = "thoropass"
    DEFAULT_URL = "https://api.thoropass.com/v1/evidence"  # confirm at v1.1
    STUB_V1_1 = True

    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        return json.dumps({
            "evidence": [
                {
                    "framework": p.framework,
                    "control_id": p.control_id,
                    "evidence_type": p.evidence_type,
                    "collected_at": p.collected_at.isoformat(),
                    "body": p.body,
                }
                for p in payloads
            ],
            "spine_meta": {"exporter": "spine-1.0", "stub": True},
        }).encode("utf-8")


send: Any = ThoropassExporter().send

__all__ = ["ThoropassExporter", "send"]

"""Tugboat Logic evidence exporter — v1.1+ STUB.

Per V3 #24: Vanta + Drata + Secureframe Day 1; Tugboat Logic / Strike
Graph / Thoropass v1.1+ (covers ~95% of GRC SaaS market).

This stub:
  * Wires the vault path convention (``evidence/tugboat/api_key`` +
    ``evidence/tugboat/api_url``) so v1.1 promotion is a one-file swap.
  * Wires the bearer-auth header so the credential plumbing is verified
    against the rest of the codebase Day 1.
  * Raises ``NotImplementedError("v1.1+")`` from ``send()`` via
    ``STUB_V1_1=True`` — the explicit refusal lets the MCP tool surface
    a clear "promote to v1.1" message to operators.
"""
from __future__ import annotations

import json
from typing import Any

from evidence._types import EvidencePayload
from evidence.exporters._base import BaseExporter


class TugboatExporter(BaseExporter):
    EXPORTER_NAME = "tugboat"
    DEFAULT_URL = "https://api.tugboatlogic.com/v1/evidence"  # confirm at v1.1
    STUB_V1_1 = True

    def _render_batch(self, payloads: list[EvidencePayload]) -> bytes:
        # Same JSON envelope as the real exporters — keeps tests honest.
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


send: Any = TugboatExporter().send

__all__ = ["TugboatExporter", "send"]

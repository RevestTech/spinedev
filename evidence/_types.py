"""Shared dataclasses for the evidence subsystem (collectors + exporters).

Kept separate from ``evidence/__init__.py`` so importing the package
does not pull every collector/exporter module (and their lazy ``psql``
or HTTP deps) into memory.

Per V3 #24 every Spine audit-chain event is potential evidence; per V25
schema each evidence_record lives under exactly one compliance control.
``EvidencePayload`` is the in-memory representation of one row before
it lands in ``spine_evidence.evidence_record``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

EvidenceType = Literal[
    "policy_doc", "access_review", "scan_result",
    "test_run", "config_snapshot",
]
"""Allowed evidence_type values from V25 schema comment.

Collectors map their Spine action onto one of these five so the
``spine_evidence.evidence_record.evidence_type`` column always carries a
known value.
"""


ExporterName = Literal[
    "vanta", "drata", "secureframe", "tugboat", "strikegraph", "thoropass",
]
"""All six supported vendor names from V25 CHECK constraint."""


def _utcnow() -> datetime:
    """UTC-aware ``datetime`` factory used by dataclass defaults."""
    return datetime.now(timezone.utc)


@dataclass
class EvidencePayload:
    """One unit of evidence that maps to a ``spine_evidence.evidence_record``.

    Attributes:
        framework: SOC2 | ISO27001 | HIPAA | PCI_DSS | GDPR | NIST_CSF.
        control_id: Native control id (e.g. CC6.1 for SOC2 CC6.1).
        evidence_type: One of the V25 allowed types.
        source_audit_record_id: UUID of the originating
            ``spine_audit.audit_event`` row (used as the citation per
            #12 / Cite-or-Refuse). May be None if the evidence is a
            config snapshot not tied to a specific event.
        collected_at: Capture timestamp; defaults to ``now()``.
        body: Vendor-bound payload — collectors place whatever JSON the
            target GRC tool will accept. Exporters transform per vendor.
        attestor_a_signature / attestor_b_signature: Optional Ed25519
            (or PGP) signatures used to compute the two-party attestation
            hash. Single-party evidence leaves these as None.
    """

    framework: str
    control_id: str
    evidence_type: EvidenceType
    source_audit_record_id: Optional[str] = None
    collected_at: datetime = field(default_factory=_utcnow)
    body: dict[str, Any] = field(default_factory=dict)
    attestor_a_signature: Optional[bytes] = None
    attestor_b_signature: Optional[bytes] = None

    def canonical_json(self) -> bytes:
        """Stable JSON encoding used as the input to attestation hashing.

        ``datetime`` → ISO 8601 UTC; ``bytes`` → hex; everything else
        runs through ``json.dumps(..., sort_keys=True, separators=(',', ':'))``
        so the same payload always hashes the same. Signatures are NOT
        included in this representation — they are appended in
        ``two_party_attestation.compute_attestation_hash``.
        """
        payload = {
            "framework": self.framework,
            "control_id": self.control_id,
            "evidence_type": self.evidence_type,
            "source_audit_record_id": self.source_audit_record_id,
            "collected_at": self.collected_at.astimezone(timezone.utc).isoformat(),
            "body": self.body,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          default=str).encode("utf-8")


@dataclass
class ExportBatch:
    """A batch of evidence headed to a single GRC vendor."""

    exporter: ExporterName
    payloads: list[EvidencePayload] = field(default_factory=list)
    target_url: str = ""


@dataclass
class ExportResult:
    """Outcome of one exporter ``send()`` call.

    Always written to ``spine_evidence.export_log`` whether ``success``
    is True or False — the log row + ``response_status`` are the
    auditor's first corroboration point.
    """

    exporter: ExporterName
    target_url: str
    records_count: int
    response_status: Optional[int] = None
    success: bool = False
    error: Optional[str] = None
    exported_at: datetime = field(default_factory=_utcnow)


__all__ = [
    "EvidenceType",
    "ExporterName",
    "EvidencePayload",
    "ExportBatch",
    "ExportResult",
]

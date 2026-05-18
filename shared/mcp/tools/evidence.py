"""Evidence subsystem MCP tools (V3 #24 — Wave 4 Squad C).

Four tools surface the ``evidence/`` package to the orchestrator and to
the ``compliance_officer`` master role:

  * ``evidence_collect``            — invoke one of 5 collectors;
                                      returns the gathered EvidencePayloads.
                                      ``requires_citation=True`` (#12 —
                                      the audit_record_id of each payload
                                      IS the citation).
  * ``evidence_export``             — push a payload batch to a vendor
                                      exporter (vanta / drata /
                                      secureframe + 3 v1.1+ stubs).
                                      ``requires_citation=True`` (#12 —
                                      the export_log row anchors the
                                      vendor-side hash).
  * ``evidence_status``             — read-only status of controls and
                                      records (no citation requirement).
  * ``evidence_attestation_verify`` — verifies a stored two-party
                                      attestation hash against the
                                      payload + signature pair (read-only
                                      verification; no citation required
                                      — the verification answer IS the
                                      output).
"""
from __future__ import annotations

import binascii
import logging
from datetime import datetime
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse, ToolStatus
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


CollectorName = Literal["audit_chain", "role_decision", "vault_access",
                        "deploy", "approval"]
ExporterName = Literal["vanta", "drata", "secureframe",
                       "tugboat", "strikegraph", "thoropass"]


# ── Helpers ────────────────────────────────────────────────────────────


def _error(code: str, msg: str, *, retryable: bool = False) -> ToolResponse:
    return ToolResponse(status="error", data={}, error=ToolError(
        code=code, message=msg, retryable=retryable,
    ))


def _payload_to_dict(p: Any) -> dict[str, Any]:
    """``EvidencePayload`` → JSON-safe dict for the response envelope."""
    return {
        "framework": p.framework,
        "control_id": p.control_id,
        "evidence_type": p.evidence_type,
        "source_audit_record_id": p.source_audit_record_id,
        "collected_at": p.collected_at.isoformat(),
        "body": p.body,
    }


def _citations_from_payloads(payloads: list[Any], summary_audit_id: UUID) -> list[Citation]:
    """One audit_hash citation per payload + the summary fallback.

    Per #12 the audit_record_id IS the citation. We emit one
    ``audit_hash`` Citation per source_audit_record_id (deduplicated)
    plus a final fallback tying the response itself to its own audit_id
    so a zero-payload collect still satisfies Cite-or-Refuse.
    """
    cites: list[Citation] = [
        Citation(
            type="audit_hash",
            ref=str(summary_audit_id),
            excerpt="evidence collector summary",
        ),
    ]
    seen: set[str] = set()
    for p in payloads:
        ref = p.source_audit_record_id
        if not ref or ref in seen:
            continue
        seen.add(ref)
        cites.append(Citation(
            type="audit_hash",
            ref=str(ref),
            excerpt=f"{p.framework}/{p.control_id}:{p.evidence_type}",
        ))
    return cites


# ── evidence_collect ───────────────────────────────────────────────────


class EvidenceCollectInput(BaseModel):
    """Inputs for ``evidence_collect`` (V3 #24)."""

    model_config = ConfigDict(extra="forbid")
    collector: CollectorName = Field(..., description="Which collector to invoke.")
    framework: str = Field(..., min_length=1)
    control_id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    since: datetime | None = None
    until: datetime | None = None
    actor: str = Field(default="compliance_officer", min_length=1)


def _dispatch_collector(payload: EvidenceCollectInput) -> list[Any]:
    """Route to the right ``collect_*`` function based on ``collector``."""
    from evidence.collectors.audit_chain import collect_audit_chain
    from evidence.collectors.approval import collect_approvals
    from evidence.collectors.deploy import collect_deploys
    from evidence.collectors.role_decision import collect_role_decisions
    from evidence.collectors.vault_access import collect_vault_access

    kwargs = dict(framework=payload.framework, control_id=payload.control_id,
                  since=payload.since, until=payload.until,
                  project_id=payload.project_id)
    if payload.collector == "audit_chain":   return collect_audit_chain(**kwargs)
    if payload.collector == "role_decision": return collect_role_decisions(**kwargs)
    if payload.collector == "vault_access":  return collect_vault_access(**kwargs)
    if payload.collector == "deploy":        return collect_deploys(**kwargs)
    if payload.collector == "approval":      return collect_approvals(**kwargs)
    raise ValueError(f"unknown collector {payload.collector!r}")


@register_tool(
    name="evidence_collect",
    input_model=EvidenceCollectInput,
    story="WAVE-4.C.1",
    description="Invoke a Spine evidence collector and return EvidencePayloads.",
    tags=("evidence", "collect"),
    requires_citation=True,  # V3 #12 — audit_record_id IS the citation.
)
def evidence_collect(payload: EvidenceCollectInput) -> ToolResponse:
    """Run one collector; return its payloads + audit_hash citations."""
    t0 = perf_counter()
    audit_id = uuid4()
    logger.info("evidence_collect: collector=%s framework=%s control=%s",
                payload.collector, payload.framework, payload.control_id)
    try:
        payloads = _dispatch_collector(payload)
    except Exception as exc:
        logger.exception("evidence_collect failed")
        return _error("collector_failed", str(exc), retryable=True)
    duration_ms = int((perf_counter() - t0) * 1000)
    data = {
        "collector": payload.collector,
        "framework": payload.framework,
        "control_id": payload.control_id,
        "payload_count": len(payloads),
        "payloads": [_payload_to_dict(p) for p in payloads],
        "duration_ms": duration_ms,
    }
    citations = _citations_from_payloads(payloads, audit_id)
    status: ToolStatus = "ok"
    return ToolResponse(status=status, data=data, audit_id=audit_id, citation=citations)


# ── evidence_export ────────────────────────────────────────────────────


class EvidenceExportInput(BaseModel):
    """Inputs for ``evidence_export``."""

    model_config = ConfigDict(extra="forbid")
    exporter: ExporterName = Field(..., description="Target GRC vendor.")
    framework: str = Field(..., min_length=1)
    control_id: str = Field(..., min_length=1)
    collector: CollectorName = Field(default="audit_chain")
    project_id: str = Field(..., min_length=1)
    since: datetime | None = None
    until: datetime | None = None
    actor: str = Field(default="compliance_officer", min_length=1)


def _build_exporter(name: ExporterName) -> Any:
    """Lazy-import + instantiate the named exporter class."""
    from evidence.exporters.drata import DrataExporter
    from evidence.exporters.secureframe import SecureframeExporter
    from evidence.exporters.strikegraph import StrikeGraphExporter
    from evidence.exporters.thoropass import ThoropassExporter
    from evidence.exporters.tugboat import TugboatExporter
    from evidence.exporters.vanta import VantaExporter
    table = {
        "vanta":       VantaExporter,
        "drata":       DrataExporter,
        "secureframe": SecureframeExporter,
        "tugboat":     TugboatExporter,
        "strikegraph": StrikeGraphExporter,
        "thoropass":   ThoropassExporter,
    }
    return table[name]()


@register_tool(
    name="evidence_export",
    input_model=EvidenceExportInput,
    story="WAVE-4.C.2",
    description="Collect + push evidence to a GRC vendor (Vanta/Drata/Secureframe Day 1).",
    tags=("evidence", "export"),
    requires_citation=True,  # V3 #12 — export_log row + audit_record_ids are the citation.
)
def evidence_export(payload: EvidenceExportInput) -> ToolResponse:
    """Collect then export; surface ExportResult + audit_hash citations."""
    t0 = perf_counter()
    audit_id = uuid4()
    collect_in = EvidenceCollectInput(
        collector=payload.collector, framework=payload.framework,
        control_id=payload.control_id, project_id=payload.project_id,
        since=payload.since, until=payload.until, actor=payload.actor,
    )
    try:
        payloads = _dispatch_collector(collect_in)
    except Exception as exc:
        logger.exception("evidence_export: collector failed")
        return _error("collector_failed", str(exc), retryable=True)
    if not payloads:
        # Zero-payload export is still a valid "we ran" event; emit the
        # response with the fallback citation per #12 instead of refusing.
        return ToolResponse(
            status="ok",
            data={"exporter": payload.exporter, "records_count": 0,
                  "success": True, "skipped": "no payloads"},
            audit_id=audit_id,
            citation=[Citation(type="audit_hash", ref=str(audit_id),
                               excerpt="empty export")],
        )
    try:
        exporter = _build_exporter(payload.exporter)
        result = exporter.send(payloads)
    except NotImplementedError as exc:
        return _error("exporter_v1_1_stub", str(exc), retryable=False)
    except Exception as exc:
        logger.exception("evidence_export: send failed")
        return _error("exporter_failed", str(exc), retryable=True)
    duration_ms = int((perf_counter() - t0) * 1000)
    data = {
        "exporter": result.exporter,
        "target_url": result.target_url,
        "records_count": result.records_count,
        "response_status": result.response_status,
        "success": result.success,
        "error": result.error,
        "duration_ms": duration_ms,
    }
    citations = _citations_from_payloads(payloads, audit_id)
    status: ToolStatus = "ok" if result.success else "error"
    err = (None if result.success else
           ToolError(code="exporter_http_error",
                     message=result.error or f"status={result.response_status}",
                     retryable=True))
    return ToolResponse(status=status, data=data, error=err,
                        audit_id=audit_id, citation=citations)


# ── evidence_status ────────────────────────────────────────────────────


class EvidenceStatusInput(BaseModel):
    """Inputs for ``evidence_status`` (read-only)."""

    model_config = ConfigDict(extra="forbid")
    framework: str | None = Field(default=None,
        description="Filter to one framework, e.g. SOC2.")
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="compliance_officer", min_length=1)


@register_tool(
    name="evidence_status",
    input_model=EvidenceStatusInput,
    story="WAVE-4.C.3",
    description="Read-only count of controls + evidence_records per framework.",
    tags=("evidence", "status"),
)
def evidence_status(payload: EvidenceStatusInput) -> ToolResponse:
    """Aggregate counts from spine_evidence — best-effort, no citation."""
    from evidence._db import query_rows
    where = ""
    if payload.framework:
        fw = payload.framework.replace("'", "''")
        where = f"WHERE framework = '{fw}'"
    sql = (
        "SELECT framework, status, COUNT(*)::int AS n "
        f"FROM spine_evidence.control {where} "
        "GROUP BY framework, status ORDER BY framework, status"
    )
    counts: list[dict[str, Any]] = []
    try:
        for row in query_rows(sql):
            counts.append(row)
    except Exception as exc:  # pragma: no cover - DB-dependent path
        logger.warning("evidence_status: query failed: %s", exc)
        return _error("status_query_failed", str(exc), retryable=True)
    return ToolResponse(status="ok", data={"controls_by_status": counts})


# ── evidence_attestation_verify ────────────────────────────────────────


class EvidenceAttestationVerifyInput(BaseModel):
    """Inputs for ``evidence_attestation_verify``.

    The payload dict mirrors ``EvidencePayload``'s public fields; the
    three byte fields arrive hex-encoded so they're JSON-safe over the
    wire (and round-trippable to the V25 ``bytea`` column).
    """

    model_config = ConfigDict(extra="forbid")
    framework: str = Field(..., min_length=1)
    control_id: str = Field(..., min_length=1)
    evidence_type: str = Field(..., min_length=1)
    source_audit_record_id: str | None = None
    collected_at: datetime
    body: dict[str, Any] = Field(default_factory=dict)
    attestor_a_signature_hex: str = Field(..., min_length=2)
    attestor_b_signature_hex: str = Field(..., min_length=2)
    expected_hash_hex: str = Field(..., min_length=64, max_length=64)
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="compliance_officer", min_length=1)


@register_tool(
    name="evidence_attestation_verify",
    input_model=EvidenceAttestationVerifyInput,
    story="WAVE-4.C.4",
    description="Verify a stored two-party attestation hash per V25 schema.",
    tags=("evidence", "attestation", "verify"),
)
def evidence_attestation_verify(payload: EvidenceAttestationVerifyInput) -> ToolResponse:
    """Regenerate SHA-256(payload || sigA || sigB); compare to expected."""
    from evidence._types import EvidencePayload
    from evidence.two_party_attestation import verify_attestation
    try:
        sig_a = binascii.unhexlify(payload.attestor_a_signature_hex)
        sig_b = binascii.unhexlify(payload.attestor_b_signature_hex)
        expected = binascii.unhexlify(payload.expected_hash_hex)
    except binascii.Error as exc:
        return _error("invalid_hex", str(exc), retryable=False)
    ep = EvidencePayload(
        framework=payload.framework,
        control_id=payload.control_id,
        evidence_type=payload.evidence_type,  # type: ignore[arg-type]
        source_audit_record_id=payload.source_audit_record_id,
        collected_at=payload.collected_at,
        body=payload.body,
    )
    verified = verify_attestation(ep, sig_a, sig_b, expected)
    return ToolResponse(
        status="ok",
        data={
            "verified": bool(verified),
            "framework": payload.framework,
            "control_id": payload.control_id,
            "expected_hash_hex": payload.expected_hash_hex,
        },
    )


__all__ = [
    "EvidenceCollectInput", "evidence_collect",
    "EvidenceExportInput", "evidence_export",
    "EvidenceStatusInput", "evidence_status",
    "EvidenceAttestationVerifyInput", "evidence_attestation_verify",
]

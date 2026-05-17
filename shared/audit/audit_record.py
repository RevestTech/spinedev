"""Pydantic AuditRecord for spine_audit.audit_event (STORY-3.1.1 / 3.1.2)."""
from __future__ import annotations
import hashlib, json, os, subprocess
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_SUBSYSTEMS = {"plan", "build", "verify", "orchestrator", "shared"}

def _sha256(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
def _canon(o: Any) -> Any:
    """Canonical encoder for UUID / datetime / Decimal -> str."""
    if isinstance(o, UUID): return str(o)
    if isinstance(o, datetime): return o.astimezone(timezone.utc).isoformat()
    if isinstance(o, Decimal): return format(o, "f")
    raise TypeError(f"Unserializable: {type(o)!r}")


class AuditRecord(BaseModel):
    """One spine_audit.audit_event row, hash-chained and ready to persist."""

    HASHED_EXCLUDE: ClassVar[set[str]] = {"content_hash", "event_id", "event_uuid"}

    event_id: Optional[int] = None
    event_uuid: UUID = Field(default_factory=uuid4)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_id: Optional[int] = None
    phase: Optional[str] = None
    role: str
    subsystem: str
    action: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    actor: str
    rationale: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_hash: Optional[str] = None
    output_hash: Optional[str] = None
    cost_usd: Optional[Decimal] = None
    pipeline_version: Optional[str] = None
    correlation_id: Optional[UUID] = None
    parent_event_id: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    prev_event_hash: Optional[str] = None
    content_hash: Optional[str] = None

    @field_validator("subsystem")
    @classmethod
    def _subsystem(cls, v: str) -> str:
        """subsystem must match the DB CHECK set."""
        if v not in ALLOWED_SUBSYSTEMS:
            raise ValueError(f"subsystem {v!r} not in {sorted(ALLOWED_SUBSYSTEMS)}")
        return v
    @field_validator("cost_usd")
    @classmethod
    def _cost(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        """cost_usd must be non-negative."""
        if v is not None and v < 0:
            raise ValueError("cost_usd must be >= 0")
        return v
    @model_validator(mode="after")
    def _hash(self) -> "AuditRecord":
        """Refuse a stored content_hash that disagrees with the record."""
        if self.content_hash and self.content_hash != compute_content_hash(self):
            raise ValueError("stale content_hash; recompute before write")
        return self


def compute_content_hash(record: AuditRecord) -> str:
    """SHA-256 of canonical JSON of the record, excluding content_hash itself."""
    payload = record.model_dump(exclude=AuditRecord.HASHED_EXCLUDE, mode="python")
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_canon))
def chain_to_previous(record: AuditRecord, prev_hash: Optional[str]) -> AuditRecord:
    """Set prev_event_hash and (re)compute content_hash; returns a new record."""
    updated = record.model_copy(update={"prev_event_hash": prev_hash, "content_hash": None})
    updated.content_hash = compute_content_hash(updated)
    return updated

def serialize_for_postgres(record: AuditRecord) -> dict[str, Any]:
    """psql-ready param dict (UUID/datetime/Decimal -> str; dict -> dict).

    Nested dicts are kept as Python dicts so the outer ``json.dumps`` in
    ``write_via_psql`` encodes them as proper JSON objects; pre-stringifying
    here would make ``jsonb_populate_record`` see a quoted string for the
    JSONB column and fail with `invalid input syntax for type jsonb`.
    """
    if record.content_hash is None:
        raise ValueError("content_hash unset; call chain_to_previous() first")
    def _v(v: Any) -> Any:
        if v is None or isinstance(v, (str, int, float, bool, dict, list)): return v
        if isinstance(v, (UUID, datetime, Decimal)): return _canon(v)
        return v
    return {k: _v(v) for k, v in record.model_dump(exclude={"event_id"}, mode="python").items()}
def _redact_enabled() -> bool:
    """Honour ``SPINE_AUDIT_REDACT`` env var; default ON (STORY-3.1.4)."""
    val = os.environ.get("SPINE_AUDIT_REDACT", "true").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _apply_redaction(record: AuditRecord) -> AuditRecord:
    """Run the PII redactor and re-chain the record so content_hash matches.

    Imported lazily to avoid a circular import (redactor.py imports
    AuditRecord). Stamps ``metadata.audit_redactions`` with the count
    of fields scrubbed so downstream consumers can spot redacted rows.
    """
    from .redactor import redact  # local import — see docstring

    redacted, summary = redact(record)
    if not summary.redactions_applied:
        return record  # nothing changed — preserve caller-chained hash exactly.
    meta = dict(redacted.metadata or {})
    meta["audit_redactions"] = summary.redactions_applied
    meta["audit_redacted_fields"] = summary.redacted_fields
    redacted = redacted.model_copy(update={"metadata": meta, "content_hash": None})
    return chain_to_previous(redacted, redacted.prev_event_hash)


def write_via_psql(record: AuditRecord, db_url: Optional[str] = None,
                   *, skip_redaction: bool = False) -> int:
    """INSERT the record via `psql` subprocess; returns generated event_id.

    When ``SPINE_AUDIT_REDACT`` is truthy (default) and ``skip_redaction``
    is False, the row is passed through ``redactor.redact()`` first to
    scrub secrets/PII per STORY-3.1.4. Pass ``skip_redaction=True`` for
    audit rows whose subject IS the redaction event itself (avoid
    recursion / preserve forensic fidelity).
    """
    url = db_url or os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set and db_url not provided")
    if not skip_redaction and _redact_enabled():
        record = _apply_redaction(record)
    serialized = serialize_for_postgres(record)
    payload = json.dumps(serialized, default=_canon).replace("'", "''")
    # Explicit column list (omitting event_id so BIGSERIAL fires its default);
    # SELECT only the columns we're inserting from the populated record so
    # type widening still happens via the row constructor.
    cols = list(serialized.keys())
    col_csv = ", ".join(cols)
    sel_csv = ", ".join(f"t.{c}" for c in cols)
    sql = (f"INSERT INTO spine_audit.audit_event ({col_csv}) "
           f"SELECT {sel_csv} FROM jsonb_populate_record("
           f"NULL::spine_audit.audit_event, '{payload}'::jsonb) t "
           "RETURNING event_id;")
    proc = subprocess.run(["psql", url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                          check=True, capture_output=True, text=True)
    # psql can emit a command tag ("INSERT 0 1") alongside RETURNING in some
    # configurations; grab the first numeric line which is the event_id.
    for line in proc.stdout.strip().splitlines():
        s = line.strip()
        if s.isdigit():
            return int(s)
    raise RuntimeError(f"write_via_psql: no event_id in psql output: {proc.stdout!r}")


# ─── Convenience constructors (monkey-patched onto AuditRecord) ──────────────

def _llm_call(cls, project_id, role, subsystem, prompt, output, model, cost):
    """llm_call record with prompt/output hashes."""
    return cls(project_id=project_id, role=role, subsystem=subsystem, action="llm_call",
               actor=role, subject_type="prompt", prompt_hash=_sha256(prompt),
               output_hash=_sha256(output), cost_usd=Decimal(str(cost)),
               metadata={"model": model})

def _phase_advanced(cls, project_id, from_phase, to_phase, actor, rationale, approval_id):
    """phase_advanced record."""
    return cls(project_id=project_id, phase=to_phase, role="orchestrator",
               subsystem="orchestrator", action="phase_advanced", actor=actor,
               subject_type="approval", subject_id=str(approval_id), rationale=rationale,
               metadata={"from_phase": from_phase, "to_phase": to_phase})

def _gate_decision(cls, project_id, phase, decision, actor, rationale):
    """gate_check record."""
    return cls(project_id=project_id, phase=phase, role="orchestrator",
               subsystem="orchestrator", action="gate_check", actor=actor,
               subject_type="gate", subject_id=phase, rationale=rationale,
               metadata={"decision": decision})

def _directive_dispatched(cls, project_id, phase, subsystem, role, directive_ref, actor):
    """directive_dispatched record."""
    return cls(project_id=project_id, phase=phase, role=role, subsystem=subsystem,
               action="directive_dispatched", actor=actor, subject_type="directive",
               subject_id=directive_ref)

def _approval_granted(cls, project_id, phase, approver, approval_id):
    """approval_granted record."""
    return cls(project_id=project_id, phase=phase, role="approver",
               subsystem="orchestrator", action="approval_granted", actor=approver,
               subject_type="approval", subject_id=str(approval_id))

for _n, _f in (("llm_call", _llm_call), ("phase_advanced", _phase_advanced),
               ("gate_decision", _gate_decision),
               ("directive_dispatched", _directive_dispatched),
               ("approval_granted", _approval_granted)):
    setattr(AuditRecord, _n, classmethod(_f))  # type: ignore[arg-type]

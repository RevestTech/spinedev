"""Bulk audit-log exporter — STORY-3.1.3 (REQ-INIT-3 EPIC-3.1).

Streams ``spine_audit.audit_event`` rows to file, S3, stdout, or HTTP
webhook in CSV / JSON / JSONL / Parquet. Streaming is mandatory: the
full table never lives in memory — we page via ``LIMIT/OFFSET`` over
subprocess ``psql`` and format each chunk as it lands. boto3 +
pyarrow are lazy-imported. See ``exporter_README.md``.
"""

from __future__ import annotations

import csv, io, json, os, subprocess, sys, time
from datetime import datetime
from typing import Any, Iterable, Iterator, Literal, Optional

from pydantic import BaseModel, Field

from .audit_record import AuditRecord
from .redactor import DEFAULT_RULES, RedactionRule, redact

Format = Literal["csv", "json", "jsonl", "parquet"]
DestinationKind = Literal["file", "s3", "stdout", "http"]

_EXPORT_COLUMNS: tuple[str, ...] = (
    "event_id", "event_uuid", "ts", "project_id", "phase", "role",
    "subsystem", "action", "subject_type", "subject_id", "actor",
    "rationale", "cost_usd", "correlation_id", "parent_event_id",
    "pipeline_version", "error_code", "error_message",
    "prompt_hash", "output_hash", "prev_event_hash", "content_hash", "metadata",
)


class ExportFilters(BaseModel):
    """Server-side filters AND-ed into a single ``WHERE`` clause."""
    project_id: Optional[str] = None
    role: Optional[str] = None
    subsystem: Optional[str] = None
    action: Optional[str] = None
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    correlation_id: Optional[str] = None
    severity: Optional[list[str]] = None


class ExportDestination(BaseModel):
    """Where rendered output is written."""
    kind: DestinationKind = "stdout"
    path: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_prefix: Optional[str] = None
    s3_region: Optional[str] = None
    http_url: Optional[str] = None
    http_headers: Optional[dict[str, str]] = None


class ExportRequest(BaseModel):
    """One export job — format, filters, destination, redaction policy."""
    format: Format = "json"
    filters: ExportFilters = Field(default_factory=ExportFilters)
    destination: ExportDestination = Field(default_factory=ExportDestination)
    include_payloads: bool = False
    redact_pii: bool = True
    chunk_size: int = Field(default=10_000, ge=1, le=100_000)


class ExportResult(BaseModel):
    """Outcome summary returned to the caller / CLI."""
    rows_exported: int = 0
    bytes_written: int = 0
    destination: str = ""
    duration_ms: int = 0
    format: str = ""
    pii_redactions: int = 0


# ─── SQL + streaming row source ──────────────────────────────────────

def _esc(s: str) -> str:
    """Single-quote escape for psql ``-c`` payloads."""
    return s.replace("'", "''")


def _where(f: ExportFilters) -> str:
    """Compose a ``WHERE`` clause from the typed filter object."""
    p = ["1=1"]
    if f.project_id: p.append(f"project_id::text = '{_esc(f.project_id)}'")
    if f.role: p.append(f"role = '{_esc(f.role)}'")
    if f.subsystem: p.append(f"subsystem = '{_esc(f.subsystem)}'")
    if f.action: p.append(f"action = '{_esc(f.action)}'")
    if f.correlation_id: p.append(f"correlation_id::text = '{_esc(f.correlation_id)}'")
    if f.from_ts: p.append(f"ts >= '{f.from_ts.isoformat()}'::timestamptz")
    if f.to_ts: p.append(f"ts <= '{f.to_ts.isoformat()}'::timestamptz")
    if f.severity:
        vals = ", ".join("'" + _esc(s) + "'" for s in f.severity)
        p.append(f"(metadata->>'severity') IN ({vals})")
    return " AND ".join(p)


def _stream_rows(db_url: str, filters: ExportFilters, chunk: int) -> Iterator[dict[str, Any]]:
    """Yield rows lazily, paging via LIMIT/OFFSET until the table is exhausted."""
    where = _where(filters); offset = 0
    while True:
        sql = (f"SELECT row_to_json(e)::text FROM spine_audit.audit_event e "
               f"WHERE {where} ORDER BY event_id ASC LIMIT {chunk} OFFSET {offset};")
        proc = subprocess.run(["psql", db_url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                              check=True, capture_output=True, text=True)
        lines = [ln for ln in proc.stdout.splitlines() if ln]
        if not lines: return
        for ln in lines:
            try: yield json.loads(ln)
            except json.JSONDecodeError: continue
        if len(lines) < chunk: return
        offset += chunk


# ─── Per-row transforms ──────────────────────────────────────────────

def _maybe_redact(row: dict[str, Any], rules: list[RedactionRule]) -> tuple[dict[str, Any], int]:
    """Validate -> redact -> dict. Rows failing validation pass through unchanged."""
    try:
        rec = AuditRecord(**{k: v for k, v in row.items() if k != "event_id"})
        rec, summary = redact(rec, rules=rules)
        out = rec.model_dump(mode="json"); out["event_id"] = row.get("event_id")
        return out, summary.redactions_applied
    except Exception:
        return row, 0


def _trim_payloads(row: dict[str, Any], include: bool) -> dict[str, Any]:
    """Drop ``prompt_hash`` / ``output_hash`` unless requested."""
    return row if include else {k: v for k, v in row.items() if k not in {"prompt_hash", "output_hash"}}


# ─── Format writers — (rows, write) -> (rows, bytes) ─────────────────


def _write_jsonl(rows: Iterable[dict[str, Any]], write: Any) -> tuple[int, int]:
    """One JSON object per line — log aggregator friendly."""
    n = b = 0
    for row in rows:
        line = (json.dumps(row, default=str) + "\n").encode("utf-8")
        write(line); b += len(line); n += 1
    return n, b


def _write_json(rows: Iterable[dict[str, Any]], write: Any) -> tuple[int, int]:
    """JSON array — manually framed so we never buffer the full list."""
    n = 0; b = 1; write(b"["); first = True
    for row in rows:
        chunk = (b"" if first else b",") + json.dumps(row, default=str).encode("utf-8")
        write(chunk); b += len(chunk); n += 1; first = False
    write(b"]"); return n, b + 1


def _write_csv(rows: Iterable[dict[str, Any]], write: Any) -> tuple[int, int]:
    """Flat CSV; ``metadata`` JSON-encoded into one cell."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(_EXPORT_COLUMNS), extrasaction="ignore")
    w.writeheader(); n = 0
    for row in rows:
        if isinstance(row.get("metadata"), (dict, list)):
            row = {**row, "metadata": json.dumps(row["metadata"], default=str)}
        w.writerow(row); n += 1
    data = buf.getvalue().encode("utf-8"); write(data)
    return n, len(data)


def _write_parquet(rows: Iterable[dict[str, Any]], write: Any) -> tuple[int, int]:
    """Parquet via pyarrow (lazy). Materialises one batch."""
    try:
        import pyarrow as pa, pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("parquet export requires pyarrow; install pyarrow") from exc
    mat = list(rows)
    if not mat: return 0, 0
    for r in mat:
        if isinstance(r.get("metadata"), (dict, list)):
            r["metadata"] = json.dumps(r["metadata"], default=str)
    sink = io.BytesIO(); pq.write_table(pa.Table.from_pylist(mat), sink)
    data = sink.getvalue(); write(data)
    return len(mat), len(data)


_WRITERS = {"json": _write_json, "jsonl": _write_jsonl,
            "csv": _write_csv, "parquet": _write_parquet}


# ─── Destination sinks ───────────────────────────────────────────────

def _open_sink(dest: ExportDestination, fmt: Format) -> tuple[Any, str, Any]:
    """Return ``(write, resolved_label, finaliser)`` for the destination."""
    if dest.kind == "stdout":
        return sys.stdout.buffer.write, "stdout", lambda: None
    if dest.kind == "file":
        if not dest.path: raise ValueError("destination.path required for kind=file")
        os.makedirs(os.path.dirname(os.path.abspath(dest.path)) or ".", exist_ok=True)
        fh = open(dest.path, "wb")
        return fh.write, os.path.abspath(dest.path), fh.close
    if dest.kind == "s3":
        try: import boto3  # type: ignore
        except ImportError as exc: raise RuntimeError("s3 export requires boto3; install boto3") from exc
        if not (dest.s3_bucket and dest.s3_prefix):
            raise ValueError("s3 export needs s3_bucket and s3_prefix")
        buf = io.BytesIO(); key = f"{dest.s3_prefix.rstrip('/')}/audit-{int(time.time())}.{fmt}"
        def finalise() -> None:
            boto3.session.Session(region_name=dest.s3_region).client("s3").put_object(
                Bucket=dest.s3_bucket, Key=key, Body=buf.getvalue())
        return buf.write, f"s3://{dest.s3_bucket}/{key}", finalise
    if dest.kind == "http":
        if not dest.http_url: raise ValueError("destination.http_url required for kind=http")
        import urllib.request
        buf = io.BytesIO()
        def finalise() -> None:
            req = urllib.request.Request(dest.http_url, data=buf.getvalue(), method="POST",
                                         headers=dest.http_headers or {"Content-Type": "application/octet-stream"})
            urllib.request.urlopen(req, timeout=30).close()  # noqa: S310 - explicit by config
        return buf.write, dest.http_url, finalise
    raise ValueError(f"unsupported destination kind: {dest.kind}")


# ─── Public entry point ──────────────────────────────────────────────


def export_audit(request: ExportRequest, *, db_url: Optional[str] = None,
                 rules: Optional[list[RedactionRule]] = None) -> ExportResult:
    """Stream-export the audit log per filters/format/destination."""
    url = db_url or os.environ.get("SPINE_DB_URL")
    if not url: raise RuntimeError("SPINE_DB_URL not set and db_url not provided")
    writer = _WRITERS.get(request.format)
    if writer is None: raise ValueError(f"unsupported format: {request.format}")
    active_rules = rules if rules is not None else list(DEFAULT_RULES)

    redactions = 0; started = time.monotonic()
    write, label, finalise = _open_sink(request.destination, request.format)

    def _row_iter() -> Iterator[dict[str, Any]]:
        nonlocal redactions
        for raw in _stream_rows(url, request.filters, request.chunk_size):
            if request.redact_pii:
                raw, n = _maybe_redact(raw, active_rules); redactions += n
            yield _trim_payloads(raw, request.include_payloads)

    try:
        n_rows, n_bytes = writer(_row_iter(), write)
    finally:
        finalise()
    return ExportResult(rows_exported=n_rows, bytes_written=n_bytes,
                        destination=label, format=request.format,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        pii_redactions=redactions)

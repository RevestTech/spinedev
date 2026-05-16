# Audit Bulk Exporter — `shared/audit/exporter.py`

Implements **STORY-3.1.3** (REQ-INIT-3 EPIC-3.1): query / export
interface for `spine_audit.audit_event` in CSV, JSON, JSONL, and
Parquet, writing to local files, S3 buckets, stdout, or HTTP webhooks.

## Why bulk export

- **Compliance.** Quarterly SOC-2 evidence pulls need a static,
  time-stamped artefact, not a live DB query.
- **SIEM integration.** Splunk / Datadog / OpenSearch ingest JSONL
  far more cheaply than per-row API calls.
- **Archival.** Cold storage in S3 + lifecycle policy keeps unit cost
  low while satisfying long retention windows.
- **Analytics.** Parquet enables DuckDB / Athena queries without
  hammering the live transactional DB.

## Format trade-offs

| Format  | Good for | Notes |
| ---     | --- | --- |
| `csv`     | Spreadsheets, ad-hoc inspection | `metadata` is JSON-encoded into one cell |
| `json`    | Snapshot dumps, REST APIs       | Array framed manually so we never buffer the full list |
| `jsonl`   | Log aggregators (recommended)   | One record per line, streamable, replay-safe |
| `parquet` | Analytics, large archives       | Lazy import; install `pyarrow` to enable |

## Destinations

```
--to stdout                           # pipe-friendly
--to file:./audit.jsonl               # local file
--to s3://bucket/prefix/              # boto3 + AWS env vars
--to https://siem.example/ingest      # HTTP POST (set headers via API)
```

Optional deps (`boto3`, `pyarrow`) are lazy-imported — missing one
disables that destination/format only.

## Streaming guarantees

- Rows are paged from Postgres with `LIMIT/OFFSET` at `chunk_size`
  (default 10 000). The full table never lives in memory.
- File / stdout sinks write each chunk as it lands.
- S3 / HTTP sinks buffer to an in-memory `BytesIO` then PUT once — fine
  up to ~100 MB; chunked multi-part will land in a follow-up.

## PII redaction

`redact_pii=True` (default) routes every row through the redactor in
`shared/audit/redactor.py` before formatting. Redaction counts surface
on `ExportResult.pii_redactions` and on the
`X-Spine-Audit-Redactions` HTTP header on `/api/v2/audit/export/v2`.

## Filter combinations

All filters are AND-ed. Common patterns:

- `project_id=42` + `from=2026-04-01` — quarterly project export
- `correlation_id=<uuid>` — one full LLM round-trip for replay
- `subsystem=verify` + `action=finding_emitted` — SOC-2 evidence pull
- `severity=["high","critical"]` — top-tier verify findings only

## Performance

Empirical on commodity hardware (M-series MBP, local Postgres, default
rule set):

- ~10 000 rows/sec for JSONL / JSON
- ~7 000 rows/sec for CSV (DictWriter overhead)
- ~15 000 rows/sec for Parquet once the table is materialised
- Redactor adds ~5–10 % per-row CPU; usually wall-clock-dominated by
  the psql subprocess rather than Python.

## Cross-references

- Backlog: `STORY-3.1.3`
- Schema: `db/flyway/sql/V15__spine_audit_schema.sql`
- REST surface: `shared/api/routes/audit.py` (`/api/v2/audit/export/v2`)
- CLI wrapper: `shared/audit/exporter_cli.sh`
- Redactor: `shared/audit/redactor.py` (+ README)

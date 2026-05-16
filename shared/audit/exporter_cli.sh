#!/usr/bin/env bash
# spine audit export — bulk audit-log export CLI (STORY-3.1.3).
#
# Thin shell over shared/audit/exporter.py + shared/audit/redactor.py.
# Examples
#   spine audit export --format jsonl --to file:./audit.jsonl --project-id 42
#   spine audit export --format csv   --to s3://acme-bucket/spine/ --from 2026-04-01
#   spine audit export --format json  --to stdout | jq '.[] | .action' | sort -u
#   spine audit redaction status
#   spine audit redaction test 'sk-ant-EXAMPLE_KEY_VALUE_FOR_DEMO_ONLY'

set -euo pipefail

PY="${SPINE_PYTHON:-python3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

usage() {
  cat <<'USAGE'
Usage: spine audit export   [options]
       spine audit redaction (status|test <text>)

Export options:
  --format <csv|json|jsonl|parquet>    Output format (default: jsonl)
  --to <dest>                          file:./path | s3://bucket/prefix | stdout | http://url
  --project-id <id>                    Filter by project_id
  --role <role>                        Filter by role
  --subsystem <sub>                    Filter by subsystem
  --action <action>                    Filter by action
  --correlation-id <uuid>              Filter by correlation_id
  --from <iso_ts>                      Earliest event ts
  --to-ts <iso_ts>                     Latest event ts
  --redact / --no-redact               Apply PII redactor (default: redact)
  --include-payloads                   Include prompt_hash + output_hash columns
  --chunk-size <n>                     DB page size (default: 10000)
USAGE
}

parse_destination() {
  local raw="$1"
  case "$raw" in
    stdout)        echo '{"kind":"stdout"}' ;;
    file:*)        printf '{"kind":"file","path":"%s"}' "${raw#file:}" ;;
    s3://*)        local rest="${raw#s3://}" bkt="${rest%%/*}" pfx="${rest#*/}"
                   printf '{"kind":"s3","s3_bucket":"%s","s3_prefix":"%s"}' "$bkt" "$pfx" ;;
    http://*|https://*) printf '{"kind":"http","http_url":"%s"}' "$raw" ;;
    *)             echo "unknown destination: $raw" >&2; exit 2 ;;
  esac
}

cmd_export() {
  local fmt=jsonl dest_raw=stdout redact=true payloads=false chunk=10000
  local project= role= subsystem= action= corr= ts_from= ts_to=
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --format)           fmt="$2"; shift 2 ;;
      --to)               dest_raw="$2"; shift 2 ;;
      --project-id)       project="$2"; shift 2 ;;
      --role)             role="$2"; shift 2 ;;
      --subsystem)        subsystem="$2"; shift 2 ;;
      --action)           action="$2"; shift 2 ;;
      --correlation-id)   corr="$2"; shift 2 ;;
      --from)             ts_from="$2"; shift 2 ;;
      --to-ts)            ts_to="$2"; shift 2 ;;
      --redact)           redact=true; shift ;;
      --no-redact)        redact=false; shift ;;
      --include-payloads) payloads=true; shift ;;
      --chunk-size)       chunk="$2"; shift 2 ;;
      -h|--help)          usage; exit 0 ;;
      *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
    esac
  done
  local dest_json; dest_json="$(parse_destination "$dest_raw")"
  "$PY" - "$fmt" "$dest_json" "$project" "$role" "$subsystem" "$action" \
                 "$corr" "$ts_from" "$ts_to" "$redact" "$payloads" "$chunk" <<'PY'
import json, sys
from shared.audit.exporter import (ExportRequest, ExportFilters,
                                   ExportDestination, export_audit)
(_, fmt, dest_json, project, role, subsystem, action,
 corr, ts_from, ts_to, redact, payloads, chunk) = sys.argv
dest = ExportDestination.model_validate(json.loads(dest_json))
filt = ExportFilters(project_id=project or None, role=role or None,
                     subsystem=subsystem or None, action=action or None,
                     correlation_id=corr or None,
                     from_ts=ts_from or None, to_ts=ts_to or None)
req = ExportRequest(format=fmt, destination=dest, filters=filt,
                    redact_pii=(redact == "true"),
                    include_payloads=(payloads == "true"),
                    chunk_size=int(chunk))
res = export_audit(req)
sys.stderr.write(res.model_dump_json(indent=2) + "\n")
PY
}

cmd_redaction() {
  local sub="${1:-status}"; shift || true
  case "$sub" in
    status) "$PY" -c 'from shared.audit.redactor import DEFAULT_RULES
for r in DEFAULT_RULES: print(f"{r.severity:8s}  {r.name:20s}  {r.pattern}")' ;;
    test)   [[ $# -ge 1 ]] || { echo "spine audit redaction test <text>" >&2; exit 2; }
            "$PY" -c 'import sys; from shared.audit.redactor import redact_text
out, res = redact_text(sys.argv[1])
print(out); print("--", res.model_dump_json())' "$1" ;;
    *) echo "unknown redaction sub-command: $sub" >&2; exit 2 ;;
  esac
}

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    export)    cmd_export "$@" ;;
    redaction) cmd_redaction "$@" ;;
    -h|--help|help) usage ;;
    *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
  esac
}

main "$@"

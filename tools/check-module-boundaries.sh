#!/usr/bin/env bash
# check-module-boundaries.sh — Spine cross-subsystem module-boundary CI lint.
#
# Implements STORY-7.1.3 (Module boundary check, generalised across
# orchestrator/plan/build/verify/shared). Single dispatch chokepoint —
# Makefile.v2 `check-boundaries` calls this; CI calls it; devs run it
# locally before pushing.
#
# Rule (REQ-INIT-7 §7.5 FR-1): subsystems import only from themselves
# and `shared/`; cross-subsystem traffic flows through `shared/mcp/`.
# The Python helper at tools/_boundary_parser.py owns language-aware
# parsing; this wrapper owns CLI ergonomics, --changed-only scoping,
# formatting, and exception bookkeeping.
#
# CLI:
#   check-module-boundaries.sh                        # full repo scan
#   check-module-boundaries.sh --changed-only         # diff vs origin/main
#   check-module-boundaries.sh --format text|json|junit
#   check-module-boundaries.sh --explain              # show rule per finding
#   check-module-boundaries.sh --add-exception <src> <tgt> <reason>
#
# Exit: 0 clean · 1 violations · 2 warnings only · 3 parser error · 64 bad usage.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARSER="$SCRIPT_DIR/_boundary_parser.py"
RULES_FILE="${SPINE_BOUNDARY_RULES:-$SCRIPT_DIR/boundary-rules.yaml}"
PYTHON="${SPINE_PYTHON:-python3}"

# ISO-8601 stderr logging — matches orchestrator/lib/router.sh.
_log() { printf '%s check-module-boundaries.sh %s %s\n' \
           "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_die() { _log ERROR "$*"; exit 3; }

# Colour only on TTY + NO_COLOR unset.
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'
  C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=""; C_YEL=""; C_GRN=""; C_DIM=""; C_RST=""
fi

usage() {
  cat <<'EOF'
Usage: check-module-boundaries.sh [OPTIONS]
       check-module-boundaries.sh --add-exception <src> <tgt> <reason>

Options:
  --changed-only     Scan only files changed vs origin/main (or HEAD).
  --format <fmt>     text (default) | json | junit
  --explain          Print the rule that classified each finding.
  --rules <path>     Override rules file (default: tools/boundary-rules.yaml).
  -h, --help         Show this help.

Exit: 0 clean · 1 violations · 2 warnings only · 3 parser error · 64 bad usage.
See tools/check-boundaries-README.md for the full contract.
EOF
}

# --add-exception: append a YAML stanza to RULES_FILE. No clever editor —
# we honour the documented shape (top-level `exceptions:` list of maps)
# and append a block. Idempotency is the caller's job.
add_exception() {
  local src="${1:-}" tgt="${2:-}" reason="${3:-}"
  [[ -z "$src" || -z "$tgt" || -z "$reason" ]] && { usage; exit 64; }
  [[ -f "$RULES_FILE" ]] || _die "rules file missing: $RULES_FILE"
  # 90-day default — long enough to schedule cleanup, short enough to
  # force a conversation if it lingers.
  local expires
  expires="$(date -u -v+90d +%Y-%m-%d 2>/dev/null || date -u -d '+90 days' +%Y-%m-%d)"
  grep -q '^exceptions:' "$RULES_FILE" || printf '\nexceptions:\n' >> "$RULES_FILE"
  {
    printf '  - source: %s\n' "$src"
    printf '    target: %s\n' "$tgt"
    printf '    reason: %q\n' "$reason"
    printf '    expires: %s\n' "$expires"
  } >> "$RULES_FILE"
  _log INFO "appended exception $src -> $tgt (expires $expires)"
  printf '%sappended%s exception %s -> %s expiring %s\n' \
    "$C_GRN" "$C_RST" "$src" "$tgt" "$expires"
}

# Pretty printer (text format). Parses the parser's JSON via jq when
# available, pure-python otherwise — both are equally fast on small docs.
render_text() {
  local json="$1" explain="$2"
  local scanned violations warnings exceptions duration
  if command -v jq >/dev/null 2>&1; then
    scanned=$(printf    '%s' "$json" | jq -r '.scanned_files')
    violations=$(printf '%s' "$json" | jq -r '.violations | length')
    warnings=$(printf   '%s' "$json" | jq -r '.warnings   | length')
    exceptions=$(printf '%s' "$json" | jq -r '.exceptions_applied')
    duration=$(printf   '%s' "$json" | jq -r '.duration_ms')
  else
    eval "$(printf '%s' "$json" | "$PYTHON" -c '
import json, sys
d = json.load(sys.stdin)
print(f"scanned={d[\"scanned_files\"]}")
print(f"violations={len(d[\"violations\"])}")
print(f"warnings={len(d[\"warnings\"])}")
print(f"exceptions={d[\"exceptions_applied\"]}")
print(f"duration={d[\"duration_ms\"]}")')"
  fi

  if [[ "$violations" -gt 0 ]]; then
    printf '%sVIOLATIONS%s\n' "$C_RED" "$C_RST"
    printf '%s' "$json" | EXPLAIN="$explain" "$PYTHON" -c '
import json, os, sys
explain = os.environ.get("EXPLAIN") == "1"
for v in json.load(sys.stdin)["violations"]:
    print(f"  {v[\"source\"]}:{v[\"line\"]} -> {v[\"target\"]}  ({v[\"imported_name\"]})")
    if explain and v.get("rule_violated"):
        print(f"      rule: {v[\"rule_violated\"]}")'
  fi
  if [[ "$warnings" -gt 0 ]]; then
    printf '%sWARNINGS%s\n' "$C_YEL" "$C_RST"
    printf '%s' "$json" | "$PYTHON" -c '
import json, sys
for w in json.load(sys.stdin)["warnings"]:
    print(f"  {w[\"source\"]}:{w[\"line\"]} -> {w[\"target\"]}  ({w[\"imported_name\"]})  {w.get(\"note\",\"\")}")'
  fi

  local colour="$C_GRN"
  [[ "$violations" -gt 0 ]] && colour="$C_RED"
  [[ "$violations" -eq 0 && "$warnings" -gt 0 ]] && colour="$C_YEL"
  printf '%s%s files scanned, %s violations, %s warnings, %s exceptions applied%s %s(%sms)%s\n' \
    "$colour" "$scanned" "$violations" "$warnings" "$exceptions" "$C_RST" \
    "$C_DIM" "$duration" "$C_RST"
}

# Main scan. Always invokes parser with --format json then either passes
# through (json/junit) or renders text. Parser's exit code propagates.
run_scan() {
  local fmt="$1" explain="$2" changed_only="$3" rules="$4"
  command -v "$PYTHON" >/dev/null 2>&1 || _die "$PYTHON not on PATH"
  [[ -f "$PARSER" ]] || _die "parser missing: $PARSER"
  [[ -f "$rules"  ]] || _die "rules missing: $rules"

  local args=( "$PARSER" "--rules" "$rules" "--root" "$REPO_ROOT" )
  [[ "$changed_only" == "1" ]] && args+=( "--changed-only" )
  [[ "$explain"      == "1" ]] && args+=( "--explain" )

  case "$fmt" in
    json|junit)
      args+=( "--format" "$fmt" )
      "$PYTHON" "${args[@]}"; return $?
      ;;
    text)
      args+=( "--format" "json" )
      local json rc=0
      json="$("$PYTHON" "${args[@]}")" || rc=$?
      [[ $rc -eq 3 ]] && { printf '%s' "$json" >&2; return 3; }
      render_text "$json" "$explain"
      return $rc
      ;;
    *) _die "unknown --format: $fmt" ;;
  esac
}

# Hand-rolled arg parse (no getopt; macOS + Linux portable).
FORMAT="text"; EXPLAIN="0"; CHANGED_ONLY="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --changed-only)    CHANGED_ONLY="1"; shift ;;
    --explain)         EXPLAIN="1"; shift ;;
    --format)          FORMAT="${2:-text}"; shift 2 ;;
    --rules)           RULES_FILE="${2:-$RULES_FILE}"; shift 2 ;;
    --add-exception)   shift; add_exception "${1:-}" "${2:-}" "${3:-}"; exit 0 ;;
    -h|--help)         usage; exit 0 ;;
    *)                 _log ERROR "unknown arg: $1"; usage; exit 64 ;;
  esac
done

run_scan "$FORMAT" "$EXPLAIN" "$CHANGED_ONLY" "$RULES_FILE"

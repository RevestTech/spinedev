#!/usr/bin/env bash
# verify_dispatcher.sh — wraps the `verify_audit` MCP call when a project
# transitions into `verify_in_progress`. Implements STORY-8.7.1 (manifest
# wires verify as a canonical SDLC phase), STORY-8.7.2 (org bundle overrides
# which TRON ISO agents fire), STORY-8.7.3 (verify-fail auto-routes back to
# Build via EPIC-9.8 / remediation.sh). See:
#   - docs/PRD.md REQ-INIT-8 §8.5 FR-6 (verify-as-canonical-phase)
#   - docs/BACKLOG.md EPIC-8.6 (STORY-8.7.1, 8.7.2, 8.7.3)
#   - plan/artifacts/sdlc-pipeline-default.yaml (`verify_config:`)
#   - orchestrator/state/phases.yaml (runtime mirror + transitions)
#   - shared/standards/bundle-schema.yaml (`verify_overrides:`)
#   - shared/mcp/tools/verify.py (`verify_audit`, wave 6 — DO NOT modify)
#   - orchestrator/lib/remediation.sh (verify-fail loop, wave 3)
#
# Architectural rule: this module does NOT re-implement dispatch, transition,
# or remediation logic. It sources router.sh, transition.sh, remediation.sh
# and is the policy layer that (a) loads the locked verify_config, (b)
# applies org-bundle overrides to the ISO-agent set, (c) parses the
# VerifyFindings response, (d) routes to the right next-phase per the
# configured severity transitions.
#
# CLI:
#   verify_dispatcher.sh dispatch <project_id> <build_artifact_id> [--dry-run]

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
PIPELINE_YAML="${SPINE_PIPELINE_YAML:-$SCRIPT_DIR/../../plan/artifacts/sdlc-pipeline-default.yaml}"
SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"
ROUTER_SH="${SPINE_ROUTER_SH:-$SCRIPT_DIR/router.sh}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"
REMEDIATION_SH="${SPINE_REMEDIATION_SH:-$SCRIPT_DIR/remediation.sh}"
BUNDLE_DIR="${SPINE_BUNDLE_DIR:-$SCRIPT_DIR/../../shared/standards}"
VERIFY_DEFAULT_PHASE="${SPINE_VERIFY_PHASE:-verify_in_progress}"

# shellcheck source=router.sh
. "$ROUTER_SH"
# shellcheck source=transition.sh
. "$TRANSITION_SH"
# shellcheck source=remediation.sh
. "$REMEDIATION_SH"

_vlog() { printf '%s verify_dispatcher.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_verr() {
  local code="$1" msg="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' "$code" "${msg//\"/\\\"}" "$extra"
  _vlog ERROR "$code: $msg"
}

# ─────────────────────────────────────────────────────────────────────
# verify_config loader — prefers the locked pipeline manifest (project pins
# one at creation time per STORY-1.7.5); falls back to phases.yaml's mirror.
# Returns a JSON blob on stdout. Requires yq for full fidelity.
# ─────────────────────────────────────────────────────────────────────
_load_verify_config() {
  local phase="${1:-$VERIFY_DEFAULT_PHASE}" src="$PIPELINE_YAML"
  [[ -f "$src" ]] || src="$PHASES_YAML"
  if command -v yq >/dev/null 2>&1; then
    yq -o=json ".phases[] | select(.id == \"$phase\") | .verify_config // {}" "$src" 2>/dev/null \
      | tr -d '\n' || printf '{}'
  else
    # yq-less fallback: minimal config so the dispatcher still routes.
    printf '{"mcp_tool":"verify_audit","auto_remediation_severity":"high","cost_cap_usd":5.00,"transitions":{"on_pass":"verify_approved","on_critical":"blocked","on_high":"build_in_progress","on_medium":"verify_approved_with_warnings","on_low":"verify_approved"}}'
  fi
}

# Bundle override (STORY-8.7.2). Reads verify_overrides from the project's
# active org bundle (discovered via project.metadata.org_bundle_path), deep-
# merges over the manifest verify_config so bundle keys win.
_apply_bundle_overrides() {
  local cfg="$1" pid="$2" bundle override
  bundle="$(_psql -c "SELECT COALESCE(metadata->>'org_bundle_path','')
                        FROM spine_lifecycle.project WHERE id = $pid;" 2>/dev/null || true)"
  bundle="${bundle//[[:space:]]/}"
  [[ -n "$bundle" && -f "$bundle" ]] || bundle="$BUNDLE_DIR/bundle-startup-saas.yaml"
  [[ -f "$bundle" ]] || { printf '%s' "$cfg"; return 0; }
  if command -v yq >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    override="$(yq -o=json '.verify_overrides // {}' "$bundle" 2>/dev/null || echo '{}')"
    printf '%s' "$cfg" | jq --argjson o "$override" '. * $o' 2>/dev/null || printf '%s' "$cfg"
  else
    printf '%s' "$cfg"
  fi
}

# BuildArtifact fetch — sealed JSON payload from spine_audit.build_artifact
# (V14+); empty string if missing so the caller can fail cleanly.
_fetch_build_artifact() {
  _psql -c "SELECT payload::text FROM spine_audit.build_artifact
              WHERE id = '$(_sql_esc "$1")' LIMIT 1;" 2>/dev/null || true
}

# Blueprint composer — combines project_type + bundle blueprint_overrides
# into Blueprint shape (file_patterns, check_types, not_in_scope). Pure JSON.
_build_blueprint() {
  local cfg="$1" pid="$2" ptype
  ptype="$(_psql -c "SELECT COALESCE(project_type,'web-app')
                       FROM spine_lifecycle.project WHERE id = $pid;" 2>/dev/null || echo web-app)"
  ptype="${ptype//[[:space:]]/}"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$cfg" | jq -c --arg pt "$ptype" \
      '(.blueprint_overrides // {}) as $b
       | {file_patterns: ($b.file_patterns // []),
          check_types:   ($b.check_types   // ["security","quality","performance"]),
          not_in_scope:  ($b.not_in_scope  // []),
          project_type:  $pt}'
  else
    printf '{"file_patterns":[],"check_types":["security","quality","performance"],"not_in_scope":[],"project_type":"%s"}' "$ptype"
  fi
}

# Severity → transition. Reads on_{pass,critical,high,medium,low} from the
# merged verify_config and dispatches. Returns chosen next-phase on stdout.
_apply_transition_rules() {
  local pid="$1" cfg="$2" findings_json="$3" failed_did="${4:-}"
  local worst rule_field next_phase
  if command -v jq >/dev/null 2>&1; then
    worst="$(printf '%s' "$findings_json" \
      | jq -r '[.findings[]?.severity] | (if any(. == "critical") then "critical"
              elif any(. == "high") then "high" elif any(. == "medium") then "medium"
              elif any(. == "low") then "low" else "pass" end)' 2>/dev/null || echo pass)"
  else
    worst=pass
    printf '%s' "$findings_json" | grep -q '"severity":"critical"' && worst=critical
    [[ $worst == pass ]] && printf '%s' "$findings_json" | grep -q '"severity":"high"' && worst=high
  fi
  case "$worst" in
    pass)     rule_field=on_pass ;;
    critical) rule_field=on_critical ;;
    high)     rule_field=on_high ;;
    medium)   rule_field=on_medium ;;
    low)      rule_field=on_low ;;
  esac
  if command -v jq >/dev/null 2>&1; then
    next_phase="$(printf '%s' "$cfg" | jq -r ".transitions.$rule_field // \"verify_approved\"" 2>/dev/null)"
  else
    next_phase=verify_approved
  fi
  case "$next_phase" in
    blocked)
      remediation_surface_to_user "$pid" "verify_audit: critical findings" >/dev/null || true
      printf 'blocked' ;;
    build_in_progress)
      # STORY-8.7.3: verify-fail loops back via canonical remediation path.
      [[ -n "$failed_did" ]] && remediation_dispatch "$failed_did" "$findings_json" >/dev/null || true
      printf 'build_in_progress' ;;
    *)
      transition_execute "$pid" "$next_phase" "orchestrator.verify_dispatcher" \
        "verify_audit severity=$worst" >/dev/null || true
      printf '%s' "$next_phase" ;;
  esac
}

# Public — dispatch: compose payload → MCP verify_audit → apply transition.
verify_dispatch() {
  local pid="${1:-}" baid="${2:-}" dry=""
  [[ "${3:-}" == "--dry-run" ]] && dry=1
  [[ -z "$pid" || -z "$baid" ]] && { _verr "invalid_input" \
    "dispatch requires <project_id> <build_artifact_id> [--dry-run]"; return 2; }

  local pinv; pinv="$(route_locked_pipeline_version "$pid")" || return $?
  local cfg; cfg="$(_load_verify_config "$VERIFY_DEFAULT_PHASE")"
  cfg="$(_apply_bundle_overrides "$cfg" "$pid")"
  local artifact; artifact="$(_fetch_build_artifact "$baid")"
  [[ -z "$artifact" ]] && { _verr "build_artifact_missing" "no build_artifact row for $baid"; return 3; }
  local blueprint; blueprint="$(_build_blueprint "$cfg" "$pid")"

  local payload
  payload=$(printf '{"project_id":"%s","actor":"orchestrator.verify_dispatcher","pipeline_version":"%s","build_artifact":%s,"blueprint":%s}' \
                   "$pid" "$pinv" "$artifact" "$blueprint")
  if [[ -n "$dry" ]]; then
    printf '{"ok":true,"dry_run":true,"tool":"%s","payload_bytes":%d}\n' \
      "${SPINE_MCP_TOOL[verify]}" "${#payload}"; return 0
  fi

  local resp; resp="$(_mcp_call "${SPINE_MCP_TOOL[verify]}" "$payload")" \
    || { _verr "mcp_call_failed" "verify_audit dispatch failed pid=$pid"; return 4; }
  local failed_did
  failed_did="$(printf '%s' "$resp" | sed -n 's/.*"build_directive_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  local next; next="$(_apply_transition_rules "$pid" "$cfg" "$resp" "$failed_did")"
  _audit_row "$pid" "$VERIFY_DEFAULT_PHASE" "verify_dispatched" \
    "next=$next build_artifact_id=$baid" || true
  printf '{"ok":true,"project_id":"%s","build_artifact_id":"%s","next_phase":"%s","pipeline_version":"%s"}\n' \
    "$pid" "$baid" "$next" "$pinv"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    dispatch) verify_dispatch "$@" ;;
    -h|--help|"") sed -n '2,24p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _verr "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

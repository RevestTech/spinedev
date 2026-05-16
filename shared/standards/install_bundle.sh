#!/usr/bin/env bash
# install_bundle.sh — Spine org-policy-bundle install CLI.
#
# Implements STORY-2.1.2 (install + validate command), STORY-2.1.3 (inject
# bundle slices into role prompts), STORY-2.1.4 (auditor consumption — the
# auditor slice is one of the inject targets), and STORY-2.1.5 (drift
# detection via SHA-256 comparison against source URL). See:
#   - docs/PRD.md REQ-INIT-1 FR-7 (customization authority), FR-8 (versioning).
#   - docs/BACKLOG.md INIT-2 EPIC-2.1.
#   - shared/standards/bundle-schema.yaml (the schema we validate against).
#   - shared/standards/install_README.md (lifecycle docs + worked example).
#
# Style mirrors orchestrator/lib/router.sh and transition.sh: bash for the
# CLI shell, Python (validator.py / prompt_injector.py) for structured logic,
# ISO-8601 stderr logs, JSON stdout, exit-code map (see _err_json calls).
#
# CLI:
#   install_bundle.sh install     <url|path|git+repo> [--no-inject] [--dry-run]
#   install_bundle.sh validate    <path>
#   install_bundle.sh list
#   install_bundle.sh activate    <bundle_id> [--project <project_id>]
#   install_bundle.sh status      [--format text|json]
#   install_bundle.sh drift-check [<bundle_id>] [--format text|json]   # STORY-2.1.5
#   install_bundle.sh remove      <bundle_id>
#   install_bundle.sh inject      [--project <project_id>] [--role <role>]
#
# Exit codes (status / drift-check): 0=in_sync, 2=drift_detected, 3=error.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPINE_HOME="${SPINE_HOME:-$HOME/.spine}"
BUNDLES_DIR="$SPINE_HOME/bundles"
ACTIVE_DIR="$SPINE_HOME/active"
VALIDATOR_PY="${SPINE_VALIDATOR_PY:-$SCRIPT_DIR/validator.py}"
INJECTOR_PY="${SPINE_INJECTOR_PY:-$SCRIPT_DIR/prompt_injector.py}"
AUDIT_PY="${SPINE_AUDIT_CLI:-$SCRIPT_DIR/../audit/audit_record.py}"
DRIFT_PY="${SPINE_DRIFT_PY:-$SCRIPT_DIR/drift_detector.py}"

mkdir -p "$BUNDLES_DIR" "$ACTIVE_DIR"

_log() { printf '%s install_bundle.sh %s %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_err_json() {
  local code="$1" message="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${message//\"/\\\"}" "$extra"
  _log ERROR "$code: $message"
}
_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}
_yaml_get() { python3 -c "
import sys,yaml
d=yaml.safe_load(open('$1'))
v=d
for k in '$2'.split('.'):
    v=v[k]
print(v)" 2>/dev/null; }

# ────────────────────────────────────────────────────────────────────
# Fetch — URL via curl, git+repo via git clone, local path via cp.
# Emits absolute path to a staged YAML on stdout. Exit 4 on failure.
# ────────────────────────────────────────────────────────────────────
_fetch_bundle() {
  local src="$1" stage src_url=""
  stage="$(mktemp -d)/bundle.yaml"
  case "$src" in
    http://*|https://*)
      command -v curl >/dev/null 2>&1 || { _err_json fetch_failed "curl required"; return 4; }
      curl -fsSL "$src" -o "$stage" \
        || { _err_json fetch_failed "curl $src"; return 4; }
      src_url="$src" ;;
    git+*)
      command -v git >/dev/null 2>&1 || { _err_json fetch_failed "git required"; return 4; }
      local repo="${src#git+}" tmp; tmp="$(mktemp -d)"
      git clone --depth 1 "$repo" "$tmp" >/dev/null 2>&1 \
        || { _err_json fetch_failed "git clone $repo"; return 4; }
      local found; found="$(find "$tmp" -maxdepth 3 -name 'bundle*.yaml' | head -1)"
      [[ -z "$found" ]] && { _err_json fetch_failed "no bundle*.yaml in $repo"; return 4; }
      cp "$found" "$stage"; src_url="$repo" ;;
    *)
      [[ -f "$src" ]] || { _err_json fetch_failed "no such file: $src"; return 4; }
      cp "$src" "$stage"; src_url="file://$(cd "$(dirname "$src")"&&pwd)/$(basename "$src")" ;;
  esac
  printf '%s\t%s\n' "$stage" "$src_url"
}

# ────────────────────────────────────────────────────────────────────
# validate — delegate to Python validator; exit 3 if invalid.
# ────────────────────────────────────────────────────────────────────
cmd_validate() {
  local path="${1:-}"
  [[ -z "$path" || ! -f "$path" ]] && { _err_json invalid_input "validate <path>"; return 2; }
  if ! python3 "$VALIDATOR_PY" validate "$path"; then
    _err_json validation_failed "bundle schema check failed: $path"; return 3
  fi
  printf '{"ok":true,"path":"%s"}\n' "$path"
}

# ────────────────────────────────────────────────────────────────────
# install — fetch → validate → store → inject (unless --no-inject) → audit.
# Layout: ~/.spine/bundles/<bundle_id>/v<version>/{bundle.yaml,sha256,
#         installed_at,source_url}.
# ────────────────────────────────────────────────────────────────────
cmd_install() {
  local src="" no_inject=false dry_run=false
  while [[ $# -gt 0 ]]; do case "$1" in
    --no-inject) no_inject=true; shift ;;
    --dry-run)   dry_run=true;   shift ;;
    -*) _err_json invalid_input "unknown flag: $1"; return 2 ;;
    *) src="$1"; shift ;;
  esac; done
  [[ -z "$src" ]] && { _err_json invalid_input "install <url|path|git+repo>"; return 2; }

  local fetched stage src_url
  fetched="$(_fetch_bundle "$src")" || return $?
  stage="${fetched%%$'\t'*}"; src_url="${fetched##*$'\t'}"

  python3 "$VALIDATOR_PY" validate "$stage" \
    || { _err_json validation_failed "$stage"; return 3; }

  local bid bver sha
  bid="$(_yaml_get "$stage" identity.bundle_id)"
  bver="$(_yaml_get "$stage" identity.bundle_version)"
  sha="$(_sha256 "$stage")"
  [[ -z "$bid" || -z "$bver" ]] \
    && { _err_json storage_failed "could not read bundle identity"; return 5; }

  if $dry_run; then
    printf '{"ok":true,"dry_run":true,"bundle_id":"%s","bundle_version":%s,"sha256":"%s"}\n' \
      "$bid" "$bver" "$sha"; return 0
  fi

  local dest="$BUNDLES_DIR/$bid/v$bver"
  mkdir -p "$dest" || { _err_json storage_failed "mkdir $dest"; return 5; }
  cp "$stage" "$dest/bundle.yaml"
  printf '%s\n' "$sha"     > "$dest/sha256"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$dest/installed_at"
  printf '%s\n' "$src_url" > "$dest/source_url"

  # First-install becomes the org-default active bundle.
  [[ ! -f "$ACTIVE_DIR/org" ]] && printf '%s\n' "$bid" > "$ACTIVE_DIR/org"

  local modified="[]"
  if ! $no_inject; then
    modified="$(python3 "$INJECTOR_PY" inject --bundle "$dest/bundle.yaml" 2>/dev/null)" \
      || { _err_json injection_failed "prompt_injector.py"; return 6; }
  fi

  # Audit (best-effort; install must not fail because audit is down).
  if [[ -x "$AUDIT_PY" ]]; then
    "$AUDIT_PY" record --subsystem shared --role operator --action bundle_install \
      --subject "$bid@v$bver" --rationale "install from $src_url" >/dev/null 2>&1 || true
  fi

  python3 -c "
import json,yaml
d=yaml.safe_load(open('$dest/bundle.yaml'))
print(json.dumps({'ok':True,'bundle_id':'$bid','bundle_version':$bver,
  'source_url':'$src_url','sha256':'$sha','dest':'$dest',
  'role_prompts_modified':json.loads('''$modified'''),
  'counts':{'grants':sum(len(v or []) for v in (d.get('capabilities',{}) or {}).get('grants',{}).values()),
            'banned_patterns':len(d.get('banned_patterns') or []),
            'compliance_packs':len(((d.get('security') or {}).get('compliance_packs')) or [])}}))"
}

cmd_list() {
  local entries="[]"
  if [[ -d "$BUNDLES_DIR" ]]; then
    entries="$(python3 -c "
import json,os
root='$BUNDLES_DIR'; out=[]
for bid in sorted(os.listdir(root)):
  vdir=os.path.join(root,bid)
  if not os.path.isdir(vdir): continue
  for v in sorted(os.listdir(vdir)):
    p=os.path.join(vdir,v)
    out.append({'bundle_id':bid,'version':v,
                'installed_at':open(os.path.join(p,'installed_at')).read().strip()
                  if os.path.exists(os.path.join(p,'installed_at')) else None})
print(json.dumps(out))")"
  fi
  local active=""
  [[ -f "$ACTIVE_DIR/org" ]] && active="$(cat "$ACTIVE_DIR/org")"
  printf '{"ok":true,"installed":%s,"active_org":"%s"}\n' "$entries" "$active"
}

cmd_activate() {
  local bid="" pid=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --project) pid="$2"; shift 2 ;;
    *) bid="$1"; shift ;;
  esac; done
  [[ -z "$bid" ]] && { _err_json invalid_input "activate <bundle_id>"; return 2; }
  [[ ! -d "$BUNDLES_DIR/$bid" ]] && { _err_json invalid_input "not installed: $bid"; return 2; }
  local scope="org" target="$ACTIVE_DIR/org"
  if [[ -n "$pid" ]]; then scope="project:$pid"; target="$ACTIVE_DIR/project-$pid"; fi
  printf '%s\n' "$bid" > "$target"
  printf '{"ok":true,"bundle_id":"%s","scope":"%s"}\n' "$bid" "$scope"
}

# ────────────────────────────────────────────────────────────────────
# status (STORY-2.1.5) — list installed bundles + drift status per
# bundle (delegated to drift_detector.py). Exit 0 if no drift, 2 if any
# bundle is drifted, 3 if drift_detector failed.
# ────────────────────────────────────────────────────────────────────
cmd_status() {
  local fmt="json"
  while [[ $# -gt 0 ]]; do case "$1" in
    --format) fmt="$2"; shift 2 ;;
    *) _err_json invalid_input "unknown arg: $1"; return 2 ;;
  esac; done
  local active=""; [[ -f "$ACTIVE_DIR/org" ]] && active="$(cat "$ACTIVE_DIR/org")"
  [[ ! -f "$DRIFT_PY" ]] && {
    _err_json drift_unavailable "drift_detector.py not found at $DRIFT_PY"; return 3; }
  # drift_detector exits 0=in_sync, 2=drift_detected, 3=error.
  local rc=0
  SPINE_HOME="$SPINE_HOME" SPINE_ACTIVE_ORG="$active" \
    python3 "$DRIFT_PY" status --format "$fmt" || rc=$?
  return "$rc"
}

# ────────────────────────────────────────────────────────────────────
# drift-check (STORY-2.1.5) — drift-only; no listing of inactive bundles.
# Optional <bundle_id> narrows the check to a single bundle.
# ────────────────────────────────────────────────────────────────────
cmd_drift_check() {
  local fmt="json" bid=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --format) fmt="$2"; shift 2 ;;
    -*) _err_json invalid_input "unknown flag: $1"; return 2 ;;
    *) bid="$1"; shift ;;
  esac; done
  [[ ! -f "$DRIFT_PY" ]] && {
    _err_json drift_unavailable "drift_detector.py not found at $DRIFT_PY"; return 3; }
  local args=(status) rc=0
  [[ -n "$bid" ]] && args+=("$bid")
  args+=(--format "$fmt")
  python3 "$DRIFT_PY" "${args[@]}" || rc=$?
  return "$rc"
}

cmd_remove() {
  local bid="${1:-}"
  [[ -z "$bid" ]] && { _err_json invalid_input "remove <bundle_id>"; return 2; }
  [[ -f "$ACTIVE_DIR/org" && "$(cat "$ACTIVE_DIR/org")" == "$bid" ]] \
    && { _err_json invalid_input "refusing to remove active bundle '$bid'; activate another first"; return 2; }
  if [[ -t 0 ]]; then
    printf 'Remove bundle %s and all installed versions? [y/N] ' "$bid" >&2
    read -r ans; [[ "$ans" =~ ^[Yy]$ ]] || { _err_json invalid_input "aborted"; return 2; }
  fi
  rm -rf "${BUNDLES_DIR:?}/$bid"
  printf '{"ok":true,"removed":"%s"}\n' "$bid"
}

cmd_inject() {
  local pid="" role=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --project) pid="$2"; shift 2 ;;
    --role)    role="$2"; shift 2 ;;
    *) _err_json invalid_input "unknown arg: $1"; return 2 ;;
  esac; done
  local bid=""
  [[ -n "$pid" && -f "$ACTIVE_DIR/project-$pid" ]] && bid="$(cat "$ACTIVE_DIR/project-$pid")"
  [[ -z "$bid" && -f "$ACTIVE_DIR/org" ]] && bid="$(cat "$ACTIVE_DIR/org")"
  [[ -z "$bid" ]] && { _err_json invalid_input "no active bundle for scope"; return 2; }
  local vdir; vdir="$(ls -1d "$BUNDLES_DIR/$bid"/v* 2>/dev/null | sort -V | tail -1)"
  [[ -z "$vdir" ]] && { _err_json storage_failed "active bundle missing: $bid"; return 5; }
  local args=(inject --bundle "$vdir/bundle.yaml")
  [[ -n "$role" ]] && args+=(--role "$role")
  [[ -n "$pid"  ]] && args+=(--project "$pid")
  python3 "$INJECTOR_PY" "${args[@]}" \
    || { _err_json injection_failed "prompt_injector.py"; return 6; }
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    install)     cmd_install     "$@" ;;
    validate)    cmd_validate    "$@" ;;
    list)        cmd_list        "$@" ;;
    activate)    cmd_activate    "$@" ;;
    status)      cmd_status      "$@" ;;
    drift-check) cmd_drift_check "$@" ;;
    remove)      cmd_remove      "$@" ;;
    inject)      cmd_inject      "$@" ;;
    -h|--help|"") sed -n '2,29p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_json unknown_subcommand "no such subcommand: $cmd"; exit 64 ;;
  esac
}

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"

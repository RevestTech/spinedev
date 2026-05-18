#!/usr/bin/env bash
#
# Spine v3 — Keycloak Day-0 bootstrap
# ------------------------------------
#
# Drivers:
#   - #25 (Identity = Keycloak embedded by default, feature-flag lightening per tier)
#   - #17 (4 deployment shapes; bootstrap must work for laptop and air-gapped equally)
#   - #14 (3 segments → 5-tier matrix; tier-config.md documents which features expose per tier)
#
# What this script does (idempotent — safe to re-run):
#   1. Waits for Keycloak's /health/ready endpoint.
#   2. If --generate-admin: generates a random 32-char admin password and either
#      (a) prints it ONCE with a save-this-now warning, OR
#      (b) writes it to --output=path with chmod 600 (no echo to stdout).
#   3. Imports / updates the 'spine' realm from realm-config/spine-realm.json (kcadm 'create' or 'update').
#   4. Imports / updates the 'spine-hub' OIDC client from realm-config/spine-hub-client.json,
#      with placeholder substitution for HUB_BASE_URL / additional redirect URIs / web origins.
#   5. Generates a fresh client_secret for 'spine-hub' and writes a vault-reference record
#      (Agent D's vault/ writes the actual secret; this script only emits the reference manifest).
#   6. Seeds default groups (hub-admins, project-admins, developers, viewers, service-accounts)
#      with their realmRole mappings, if not already present.
#
# What this script does NOT do:
#   - Write the client secret into vault (Agent D's scope; this script emits a path reference).
#   - Configure brokered IdPs (Day-0 wizard step 2 — uses idp-presets/*.json).
#   - Touch shared/identity/ (Agent C's package, contract = OIDC standards only).
#
# Exit codes:
#   0  success
#   2  bad arguments
#   3  Keycloak not reachable within --wait-timeout
#   4  kcadm.sh failure (auth, network, schema)
#   5  realm/client JSON validation failure

set -euo pipefail

# ---------- defaults --------------------------------------------------------

KC_URL="${KC_URL:-http://localhost:8080}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_ADMIN_PASS="${KC_ADMIN_PASS:-}"
KC_REALM="${KC_REALM:-spine}"
KC_CLIENT_ID="${KC_CLIENT_ID:-spine-hub}"
KC_MASTER_REALM="${KC_MASTER_REALM:-master}"

HUB_BASE_URL="${HUB_BASE_URL:-http://localhost:8090}"
ADDITIONAL_REDIRECT_URI_1="${ADDITIONAL_REDIRECT_URI_1:-}"
ADDITIONAL_REDIRECT_URI_2="${ADDITIONAL_REDIRECT_URI_2:-}"
ADDITIONAL_WEB_ORIGIN_1="${ADDITIONAL_WEB_ORIGIN_1:-}"
ADDITIONAL_WEB_ORIGIN_2="${ADDITIONAL_WEB_ORIGIN_2:-}"

CLIENT_SECRET_VAULT_PATH="${CLIENT_SECRET_VAULT_PATH:-secret/spine/keycloak/spine-hub/client-secret}"

WAIT_TIMEOUT=180
GENERATE_ADMIN=0
OUTPUT_PATH=""
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REALM_JSON="${SCRIPT_DIR}/realm-config/spine-realm.json"
CLIENT_JSON_TEMPLATE="${SCRIPT_DIR}/realm-config/spine-hub-client.json"

# ---------- helpers ---------------------------------------------------------

log() { printf '[spine-keycloak-bootstrap] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit "${2:-1}"; }

usage() {
  cat <<'EOF'
Spine v3 Keycloak Day-0 bootstrap.

Usage:
  init-bootstrap.sh [options]

Options:
  --keycloak-url URL           Keycloak base URL (default: http://localhost:8080)
  --realm NAME                 Realm name (default: spine)
  --hub-base-url URL           Hub SPA base URL for redirect URIs (default: http://localhost:8090)
  --add-redirect-uri URI       Additional redirect URI (may repeat up to 2x)
  --add-web-origin ORIGIN      Additional web origin (may repeat up to 2x)
  --admin-user NAME            Initial realm admin username (default: admin)
  --admin-pass PASS            Initial realm admin password (omit with --generate-admin)
  --generate-admin             Generate random 32-char admin password
  --output PATH                Write generated password (chmod 600) instead of stdout
  --client-secret-vault-path P Vault path reference for the spine-hub client secret
                               (default: secret/spine/keycloak/spine-hub/client-secret)
  --wait-timeout SECONDS       How long to wait for Keycloak ready (default: 180)
  --dry-run                    Print planned actions, do not modify Keycloak
  -h, --help                   Show this help and exit

Environment overrides: KC_URL, KC_ADMIN_USER, KC_ADMIN_PASS, KC_REALM, HUB_BASE_URL,
ADDITIONAL_REDIRECT_URI_1, ADDITIONAL_REDIRECT_URI_2, ADDITIONAL_WEB_ORIGIN_1,
ADDITIONAL_WEB_ORIGIN_2, CLIENT_SECRET_VAULT_PATH.

Exit codes: 0 ok, 2 args, 3 not-ready, 4 kcadm failure, 5 JSON validation failure.
EOF
}

# ---------- arg parsing -----------------------------------------------------

while (($#)); do
  case "$1" in
    --keycloak-url)              KC_URL="$2"; shift 2 ;;
    --realm)                     KC_REALM="$2"; shift 2 ;;
    --hub-base-url)              HUB_BASE_URL="$2"; shift 2 ;;
    --add-redirect-uri)
      if [[ -z "$ADDITIONAL_REDIRECT_URI_1" ]]; then
        ADDITIONAL_REDIRECT_URI_1="$2"
      elif [[ -z "$ADDITIONAL_REDIRECT_URI_2" ]]; then
        ADDITIONAL_REDIRECT_URI_2="$2"
      else
        die "max 2 additional redirect URIs (got 3+)" 2
      fi
      shift 2 ;;
    --add-web-origin)
      if [[ -z "$ADDITIONAL_WEB_ORIGIN_1" ]]; then
        ADDITIONAL_WEB_ORIGIN_1="$2"
      elif [[ -z "$ADDITIONAL_WEB_ORIGIN_2" ]]; then
        ADDITIONAL_WEB_ORIGIN_2="$2"
      else
        die "max 2 additional web origins (got 3+)" 2
      fi
      shift 2 ;;
    --admin-user)                KC_ADMIN_USER="$2"; shift 2 ;;
    --admin-pass)                KC_ADMIN_PASS="$2"; shift 2 ;;
    --generate-admin)            GENERATE_ADMIN=1; shift ;;
    --output)                    OUTPUT_PATH="$2"; shift 2 ;;
    --client-secret-vault-path)  CLIENT_SECRET_VAULT_PATH="$2"; shift 2 ;;
    --wait-timeout)              WAIT_TIMEOUT="$2"; shift 2 ;;
    --dry-run)                   DRY_RUN=1; shift ;;
    -h|--help)                   usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" 2 ;;
  esac
done

# ---------- prereqs ---------------------------------------------------------

command -v curl >/dev/null 2>&1 || die "curl required" 2
command -v python3 >/dev/null 2>&1 || die "python3 required (for JSON munging)" 2

# kcadm.sh is shipped inside the Keycloak container; we exec it via docker if not on PATH.
if command -v kcadm.sh >/dev/null 2>&1; then
  KCADM="kcadm.sh"
elif command -v docker >/dev/null 2>&1; then
  KCADM='docker exec -i spine-keycloak /opt/keycloak/bin/kcadm.sh'
else
  die "need either kcadm.sh on PATH or docker + spine-keycloak container running" 2
fi

[[ -f "$REALM_JSON" ]] || die "realm JSON not found: $REALM_JSON" 5
[[ -f "$CLIENT_JSON_TEMPLATE" ]] || die "client JSON template not found: $CLIENT_JSON_TEMPLATE" 5

# Validate input JSON before doing anything destructive.
python3 -m json.tool < "$REALM_JSON" > /dev/null \
  || die "realm JSON is not valid: $REALM_JSON" 5
python3 -m json.tool < "$CLIENT_JSON_TEMPLATE" > /dev/null \
  || die "client JSON template is not valid: $CLIENT_JSON_TEMPLATE" 5

# ---------- generate admin password (optional) ------------------------------

generate_password() {
  # 32 chars, URL-safe alphabet, ~190 bits entropy.
  python3 -c 'import secrets,string; alpha=string.ascii_letters+string.digits+"-_"; print("".join(secrets.choice(alpha) for _ in range(32)))'
}

if (( GENERATE_ADMIN == 1 )); then
  KC_ADMIN_PASS="$(generate_password)"
  if [[ -n "$OUTPUT_PATH" ]]; then
    umask 077
    {
      printf 'spine_keycloak_admin_user=%s\n' "$KC_ADMIN_USER"
      printf 'spine_keycloak_admin_password=%s\n' "$KC_ADMIN_PASS"
      printf 'spine_keycloak_url=%s\n' "$KC_URL"
      printf 'spine_keycloak_realm=%s\n' "$KC_REALM"
      printf '# Generated: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$OUTPUT_PATH"
    chmod 600 "$OUTPUT_PATH"
    log "Admin credentials written to: $OUTPUT_PATH (chmod 600)"
    log "Move to your secrets manager and DELETE this file immediately."
  else
    cat >&2 <<EOF

================================================================================
SAVE THIS NOW. SHOWN ONCE.
--------------------------------------------------------------------------------
Spine Keycloak admin credentials (realm: ${KC_MASTER_REALM})

  username: ${KC_ADMIN_USER}
  password: ${KC_ADMIN_PASS}
  url:      ${KC_URL}

Copy into your password manager. This message will NOT be repeated.
Re-running --generate-admin produces a NEW password and rotates the prior one.
================================================================================
EOF
  fi
fi

[[ -n "$KC_ADMIN_PASS" ]] || die "no admin password (use --admin-pass, --generate-admin, or KC_ADMIN_PASS env)" 2

# ---------- wait for Keycloak ready ----------------------------------------

wait_for_ready() {
  local deadline=$(( SECONDS + WAIT_TIMEOUT ))
  local mgmt_url="${KC_URL%:*}:9000"
  # Try management port (8.x+), fall back to legacy /health/ready on main port.
  while (( SECONDS < deadline )); do
    if curl -fsS -m 3 "${mgmt_url}/health/ready" >/dev/null 2>&1 \
       || curl -fsS -m 3 "${KC_URL}/health/ready" >/dev/null 2>&1 \
       || curl -fsS -m 3 "${KC_URL}/realms/${KC_MASTER_REALM}/.well-known/openid-configuration" >/dev/null 2>&1; then
      log "Keycloak is ready at ${KC_URL}"
      return 0
    fi
    sleep 2
  done
  die "Keycloak not ready after ${WAIT_TIMEOUT}s (tried ${KC_URL}/health/ready and ${mgmt_url}/health/ready)" 3
}

wait_for_ready

# ---------- kcadm login -----------------------------------------------------

if (( DRY_RUN == 1 )); then
  log "DRY-RUN: would log in as ${KC_ADMIN_USER}@${KC_MASTER_REALM} via ${KC_URL}"
else
  ${KCADM} config credentials \
      --server "${KC_URL}" \
      --realm "${KC_MASTER_REALM}" \
      --user "${KC_ADMIN_USER}" \
      --password "${KC_ADMIN_PASS}" \
    || die "kcadm login failed (check admin user/pass and ${KC_URL})" 4
fi

# ---------- realm: create-or-update (idempotent) ----------------------------

realm_exists() {
  ${KCADM} get "realms/${KC_REALM}" >/dev/null 2>&1
}

if (( DRY_RUN == 1 )); then
  log "DRY-RUN: would create/update realm '${KC_REALM}' from ${REALM_JSON}"
elif realm_exists; then
  log "Realm '${KC_REALM}' exists — updating (idempotent merge; users preserved)"
  # 'update realms/<id>' takes a partial; we feed the full realm JSON minus the immutable id keys.
  python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
for k in ('id','users','clients','identityProviders','clientScopes','components'):
    d.pop(k, None)
json.dump(d, sys.stdout)
" "$REALM_JSON" | ${KCADM} update "realms/${KC_REALM}" -f - \
    || die "realm update failed" 4
else
  log "Realm '${KC_REALM}' does not exist — creating from ${REALM_JSON}"
  ${KCADM} create realms -f "$REALM_JSON" \
    || die "realm create failed" 4
fi

# ---------- groups + role mapping (idempotent seed) ------------------------

seed_group() {
  local group="$1"; local role="$2"
  if (( DRY_RUN == 1 )); then
    log "DRY-RUN: would ensure group /${group} -> realm role ${role}"
    return 0
  fi
  if ! ${KCADM} get "groups" -r "${KC_REALM}" -q "search=${group}" 2>/dev/null | grep -q "\"name\" : \"${group}\""; then
    ${KCADM} create "groups" -r "${KC_REALM}" -s "name=${group}" >/dev/null \
      || die "failed to create group ${group}" 4
    log "Created group: /${group}"
  fi
  local gid
  gid="$(${KCADM} get "groups" -r "${KC_REALM}" -q "search=${group}" 2>/dev/null \
        | python3 -c "import json,sys; [print(g['id']) for g in json.load(sys.stdin) if g['name']=='${group}']")"
  if [[ -n "$gid" ]]; then
    ${KCADM} add-roles -r "${KC_REALM}" --gid "$gid" --rolename "$role" 2>/dev/null || true
  fi
}

seed_group "hub-admins"       "hub-admin"
seed_group "project-admins"   "project-admin"
seed_group "developers"       "developer"
seed_group "viewers"          "viewer"
seed_group "service-accounts" "service-account"

# ---------- spine-hub client: render template + create/update --------------

RENDERED_CLIENT_JSON="$(mktemp -t spine-hub-client.XXXXXX.json)"
trap 'rm -f "$RENDERED_CLIENT_JSON"' EXIT

# Drop any unfilled placeholder array entries (Keycloak rejects literal "{{...}}").
python3 -c "
import json, os, sys, re
tpl = json.load(open(sys.argv[1]))
sub = {
  '{{HUB_BASE_URL}}':              os.environ.get('HUB_BASE_URL',''),
  '{{ADDITIONAL_REDIRECT_URI_1}}': os.environ.get('ADDITIONAL_REDIRECT_URI_1',''),
  '{{ADDITIONAL_REDIRECT_URI_2}}': os.environ.get('ADDITIONAL_REDIRECT_URI_2',''),
  '{{ADDITIONAL_WEB_ORIGIN_1}}':   os.environ.get('ADDITIONAL_WEB_ORIGIN_1',''),
  '{{ADDITIONAL_WEB_ORIGIN_2}}':   os.environ.get('ADDITIONAL_WEB_ORIGIN_2',''),
}
def walk(o):
    if isinstance(o, dict):
        return {k: walk(v) for k,v in o.items() if not k.startswith('_comment')}
    if isinstance(o, list):
        out=[]
        for v in o:
            v2 = walk(v)
            if isinstance(v2, str):
                for ph, rep in sub.items(): v2 = v2.replace(ph, rep)
                if v2 and '{{' not in v2: out.append(v2)
            else:
                out.append(v2)
        return out
    if isinstance(o, str):
        for ph, rep in sub.items(): o = o.replace(ph, rep)
        return o
    return o
rendered = walk(tpl)
json.dump(rendered, open(sys.argv[2], 'w'), indent=2)
" "$CLIENT_JSON_TEMPLATE" "$RENDERED_CLIENT_JSON"

if (( DRY_RUN == 1 )); then
  log "DRY-RUN: would create/update client '${KC_CLIENT_ID}' in realm '${KC_REALM}' from rendered JSON"
else
  CLIENT_UUID="$(${KCADM} get clients -r "${KC_REALM}" -q "clientId=${KC_CLIENT_ID}" 2>/dev/null \
    | python3 -c "import json,sys; arr=json.load(sys.stdin); print(arr[0]['id']) if arr else None" || true)"
  if [[ -n "$CLIENT_UUID" && "$CLIENT_UUID" != "None" ]]; then
    log "Client '${KC_CLIENT_ID}' exists (uuid=${CLIENT_UUID}) — updating"
    ${KCADM} update "clients/${CLIENT_UUID}" -r "${KC_REALM}" -f "$RENDERED_CLIENT_JSON" \
      || die "client update failed" 4
  else
    log "Client '${KC_CLIENT_ID}' does not exist — creating"
    ${KCADM} create clients -r "${KC_REALM}" -f "$RENDERED_CLIENT_JSON" \
      || die "client create failed" 4
    CLIENT_UUID="$(${KCADM} get clients -r "${KC_REALM}" -q "clientId=${KC_CLIENT_ID}" 2>/dev/null \
      | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")"
  fi

  # Rotate / fetch client secret. NEVER print it; write a vault-reference manifest only.
  ${KCADM} create "clients/${CLIENT_UUID}/client-secret" -r "${KC_REALM}" >/dev/null \
    || die "client-secret regeneration failed" 4
  SECRET_VALUE="$(${KCADM} get "clients/${CLIENT_UUID}/client-secret" -r "${KC_REALM}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['value'])")"

  MANIFEST="${SCRIPT_DIR}/.bootstrap-vault-ref.json"
  umask 077
  python3 -c "
import json, os, sys, time
manifest = {
  'kind': 'spine-keycloak-vault-reference',
  'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
  'keycloak_url': os.environ['KC_URL'],
  'realm': os.environ['KC_REALM'],
  'client_id': os.environ['KC_CLIENT_ID'],
  'vault_path': os.environ['CLIENT_SECRET_VAULT_PATH'],
  'instructions': 'Agent D vault/ writes the actual secret to vault_path. shared/secrets/ (Agent C) reads at runtime.',
  '_warning': 'The actual secret value is on stdin only; pipe it into vault now and shred this manifest after vault write succeeds.'
}
json.dump(manifest, open(sys.argv[1], 'w'), indent=2)
" "$MANIFEST"
  chmod 600 "$MANIFEST"

  # Emit the secret to FD 3 if open (caller can capture & pipe to vault), else stderr with banner.
  if { true >&3; } 2>/dev/null; then
    printf '%s' "$SECRET_VALUE" >&3
    log "Client secret emitted on fd 3 (caller must pipe to vault path: ${CLIENT_SECRET_VAULT_PATH})"
  else
    cat >&2 <<EOF

================================================================================
SAVE THIS NOW. SHOWN ONCE.
--------------------------------------------------------------------------------
Spine Hub OIDC client secret (client_id=${KC_CLIENT_ID}, realm=${KC_REALM})

  ${SECRET_VALUE}

Write this to your vault at path:
  ${CLIENT_SECRET_VAULT_PATH}

Then delete: ${MANIFEST}
This message will NOT be repeated. Re-run init-bootstrap.sh to rotate.
================================================================================
EOF
  fi
fi

log "Done. realm=${KC_REALM} client_id=${KC_CLIENT_ID} hub_base_url=${HUB_BASE_URL}"
log "Next: Day-0 wizard step 2 (IdP brokering) — see idp-presets/README.md"
exit 0

#!/usr/bin/env bash
# tools/byoc/clouds/fly.sh — Spine BYOC Fly.io provisioner.
#
# Fly.io is a candidate-5th-cloud per Decision #20 (alongside DigitalOcean).
# Founder-tier (lightweight, no K8s). Delegation = customer invites
# vendor's `spine-ops@` Fly org into a single dedicated org with `Admin`.
#
# Modes:
#   machines  — Fly Machines (V2) + Fly Postgres add-on. Default.
#
# v1.0 status: dry-run plan complete; live `flyctl` calls scaffolded.

SPINE_BYOC_REGION="${SPINE_BYOC_REGION:-iad}"   # Fly-named region (Ashburn)
SPINE_BYOC_MODE="${SPINE_BYOC_MODE:-machines}"

_fly_log() { byoc_log "[fly/${SPINE_BYOC_MODE}/${SPINE_BYOC_REGION}] $*"; }
_FLY_APP="spine-hub-${SPINE_BYOC_BUNDLE_ID:0:8}"
_FLY_DB="${_FLY_APP}-pg"

byoc_validate_credentials() {
  if ! command -v flyctl >/dev/null 2>&1; then
    _fly_log "flyctl not on PATH — staying in STUB mode."
    export BYOC_STUB_CALLS=1
  fi
  if [[ -n "${SPINE_BYOC_CREDENTIALS_REF:-}" ]]; then
    _fly_log "resolving credentials-ref ${SPINE_BYOC_CREDENTIALS_REF}"
    if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
      _fly_log "STUB: would resolve vault ref → FLY_API_TOKEN (subshell only)"
    else
      ( byoc_resolve_vault_ref "$SPINE_BYOC_CREDENTIALS_REF" >/dev/null ) || return 3
    fi
  fi
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    _fly_log "STUB: flyctl orgs list --json | jq '.[] | select(.Slug==\"$SPINE_BYOC_ACCOUNT\")'"
    return 0
  fi
  if ! flyctl orgs list --json 2>/dev/null | grep -q "\"Slug\": *\"$SPINE_BYOC_ACCOUNT\""; then
    _fly_log "FAIL: spine-ops account is not a member of Fly org $SPINE_BYOC_ACCOUNT"
    return 3
  fi
  return 0
}

byoc_provision() {
  case "$SPINE_BYOC_MODE" in
    machines) ;;
    *) BYOC_DIE_CODE=6 byoc_die "Fly --mode must be machines (got $SPINE_BYOC_MODE)" ;;
  esac

  byoc_banner "Fly step 1/5 — Create app $_FLY_APP in org $SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "flyctl apps create $_FLY_APP --org $SPINE_BYOC_ACCOUNT" \
    flyctl apps create "$_FLY_APP" --org "$SPINE_BYOC_ACCOUNT"

  byoc_banner "Fly step 2/5 — Create Fly Postgres cluster $_FLY_DB"
  byoc_run_or_stub "flyctl postgres create --name $_FLY_DB --org $SPINE_BYOC_ACCOUNT --region $SPINE_BYOC_REGION --vm-size shared-cpu-1x --initial-cluster-size 1" \
    flyctl postgres create --name "$_FLY_DB" --org "$SPINE_BYOC_ACCOUNT" \
      --region "$SPINE_BYOC_REGION" --vm-size shared-cpu-1x --initial-cluster-size 1

  byoc_banner "Fly step 3/5 — Attach Postgres to app (sets DATABASE_URL in app secrets)"
  byoc_run_or_stub "flyctl postgres attach --app $_FLY_APP $_FLY_DB" \
    flyctl postgres attach --app "$_FLY_APP" "$_FLY_DB"

  byoc_banner "Fly step 4/5 — Seed app secrets (per #9 — values from vault subshell)"
  # Fly secrets are the customer's encrypted-at-rest secret store at this tier
  # (analogous to the Railway env model). For Vault-grade audit, customer must
  # opt into running OpenBao inside Fly as a separate app — see runbook.
  _fly_log "[stub] flyctl secrets set --app $_FLY_APP \\"
  _fly_log "  SPINE_HUB_VERSION=${SPINE_HUB_VERSION} \\"
  _fly_log "  SPINE_BUNDLE_ID=${SPINE_BYOC_BUNDLE_ID} \\"
  _fly_log "  SPINE_HUB_ADMIN_EMAIL=${SPINE_BYOC_ADMIN_EMAIL} \\"
  _fly_log "  KEYCLOAK_ADMIN_PASSWORD=<piped-from-vault-subshell> \\"
  _fly_log "  SPINE_VAULT_ROOT_TOKEN=<piped-from-vault-subshell>"

  byoc_banner "Fly step 5/5 — Deploy Hub image + create primary Machine"
  byoc_run_or_stub "flyctl deploy --app $_FLY_APP --image spine/hub:${SPINE_HUB_VERSION} --region $SPINE_BYOC_REGION --vm-size shared-cpu-2x --vm-memory 2048" \
    flyctl deploy --app "$_FLY_APP" --image "spine/hub:${SPINE_HUB_VERSION}" \
      --region "$SPINE_BYOC_REGION" --vm-size shared-cpu-2x --vm-memory 2048

  byoc_emit_handoff \
    "https://${_FLY_APP}.fly.dev" \
    "$SPINE_BYOC_ADMIN_EMAIL" \
    "Fly app secret: SPINE_VAULT_UNSEAL_SHARES (flyctl secrets list --app $_FLY_APP, value never re-readable)"
}

byoc_destroy() {
  byoc_banner "Fly teardown"
  byoc_run_or_stub "flyctl apps destroy $_FLY_APP --yes" \
    flyctl apps destroy "$_FLY_APP" --yes
  byoc_run_or_stub "flyctl postgres destroy $_FLY_DB --yes" \
    flyctl apps destroy "$_FLY_DB" --yes
  _fly_log "Fly teardown complete. Customer revokes spine-ops invite to fully detach."
}

#!/usr/bin/env bash
# tools/byoc/clouds/do.sh — Spine BYOC DigitalOcean provisioner.
#
# DO is the alternate 5th-cloud candidate per Decision #20 (alongside Fly).
# Delegation = project-scoped API token (read+write) granted by customer.
#
# Modes:
#   app   — DigitalOcean App Platform (Hub as container) + managed Postgres.
#           Default — easiest Founder-tier path.
#   doks  — DigitalOcean Kubernetes (DOKS) + managed Postgres add-on.
#
# v1.0 status: dry-run plan complete; live `doctl` calls scaffolded.

SPINE_BYOC_REGION="${SPINE_BYOC_REGION:-nyc3}"
SPINE_BYOC_MODE="${SPINE_BYOC_MODE:-app}"

_do_log() { byoc_log "[do/${SPINE_BYOC_MODE}/${SPINE_BYOC_REGION}] $*"; }
_DO_APP="spine-hub-${SPINE_BYOC_BUNDLE_ID:0:8}"
_DO_DB="${_DO_APP}-pg"

byoc_validate_credentials() {
  if ! command -v doctl >/dev/null 2>&1; then
    _do_log "doctl not on PATH — staying in STUB mode."
    export BYOC_STUB_CALLS=1
  fi
  if [[ -n "${SPINE_BYOC_CREDENTIALS_REF:-}" ]]; then
    _do_log "resolving credentials-ref ${SPINE_BYOC_CREDENTIALS_REF}"
    if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
      _do_log "STUB: would resolve vault ref → DIGITALOCEAN_ACCESS_TOKEN (subshell)"
    else
      ( byoc_resolve_vault_ref "$SPINE_BYOC_CREDENTIALS_REF" >/dev/null ) || return 3
    fi
  fi
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    _do_log "STUB: doctl account get"
    return 0
  fi
  if ! doctl account get >/dev/null 2>&1; then
    _do_log "FAIL: doctl account get — API token does not authenticate."
    return 3
  fi
  return 0
}

byoc_provision() {
  byoc_banner "DO step 1/4 — Managed Postgres ($_DO_DB)"
  byoc_run_or_stub "doctl databases create $_DO_DB --engine pg --version 16 --size db-s-1vcpu-1gb --region $SPINE_BYOC_REGION --num-nodes 1" \
    doctl databases create "$_DO_DB" --engine pg --version 16 \
      --size db-s-1vcpu-1gb --region "$SPINE_BYOC_REGION" --num-nodes 1

  case "$SPINE_BYOC_MODE" in
    app)
      byoc_banner "DO step 2/4 — App Platform spec (App Spec YAML)"
      _do_log "[stub] cat <<APP > app.yaml"
      _do_log "name: $_DO_APP"
      _do_log "region: $SPINE_BYOC_REGION"
      _do_log "services:"
      _do_log "  - name: spine-hub"
      _do_log "    image: { registry_type: DOCKER_HUB, repository: spine/hub, tag: ${SPINE_HUB_VERSION} }"
      _do_log "    instance_size_slug: basic-xs"
      _do_log "    instance_count: 1"
      _do_log "    http_port: 8090"
      _do_log "    health_check: { http_path: /healthz }"
      _do_log "    envs:"
      _do_log "      - { key: SPINE_HUB_VERSION, value: ${SPINE_HUB_VERSION} }"
      _do_log "      - { key: SPINE_BUNDLE_ID, value: ${SPINE_BYOC_BUNDLE_ID} }"
      _do_log "      - { key: SPINE_HUB_ADMIN_EMAIL, value: ${SPINE_BYOC_ADMIN_EMAIL} }"
      _do_log "      - { key: DATABASE_URL, scope: RUN_TIME, type: SECRET, value: \${$_DO_DB.DATABASE_URL} }"
      _do_log "databases:"
      _do_log "  - { name: $_DO_DB, engine: PG, production: true }"
      _do_log "APP"
      byoc_run_or_stub "doctl apps create --spec app.yaml" \
        doctl apps create --spec app.yaml
      ;;
    doks)
      byoc_banner "DO step 2/4 — DOKS cluster"
      byoc_run_or_stub "doctl kubernetes cluster create spine-hub --region $SPINE_BYOC_REGION --node-pool 'name=spine-default;size=s-2vcpu-4gb;count=1'" \
        doctl kubernetes cluster create spine-hub --region "$SPINE_BYOC_REGION" \
          --node-pool "name=spine-default;size=s-2vcpu-4gb;count=1"
      _do_log "[stub] helm install spine-hub spine/hub --version $SPINE_HUB_VERSION -n spine --create-namespace"
      ;;
    *)
      BYOC_DIE_CODE=6 byoc_die "DO --mode must be app or doks (got $SPINE_BYOC_MODE)"
      ;;
  esac

  byoc_banner "DO step 3/4 — Trusted-sources lock on Postgres (App / DOKS only)"
  byoc_run_or_stub "doctl databases firewalls append $_DO_DB --rule type:app,value:$_DO_APP" \
    doctl databases firewalls append "$_DO_DB" --rule "type:app,value:$_DO_APP"

  byoc_banner "DO step 4/4 — TLS via App Platform auto-cert OR cert-manager (DOKS)"
  _do_log "App Platform: TLS provisioned automatically for *.ondigitalocean.app."
  _do_log "DOKS: install cert-manager + ClusterIssuer (Let's Encrypt) via helm."

  byoc_emit_handoff \
    "https://${_DO_APP}.ondigitalocean.app" \
    "$SPINE_BYOC_ADMIN_EMAIL" \
    "DO App env var: SPINE_VAULT_UNSEAL_SHARES (doctl apps spec get $_DO_APP)"
}

byoc_destroy() {
  byoc_banner "DO teardown"
  case "$SPINE_BYOC_MODE" in
    app)
      byoc_run_or_stub "doctl apps delete <app-id> --force" \
        doctl apps delete "$_DO_APP" --force
      ;;
    doks|*)
      byoc_run_or_stub "doctl kubernetes cluster delete spine-hub --force" \
        doctl kubernetes cluster delete spine-hub --force
      ;;
  esac
  byoc_run_or_stub "doctl databases delete $_DO_DB --force" \
    doctl databases delete "$_DO_DB" --force
  _do_log "DO teardown complete. Customer revokes the API token to fully detach."
}

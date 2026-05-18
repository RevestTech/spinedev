#!/usr/bin/env bash
# tools/byoc/provision.sh — Spine BYOC per-cloud orchestrator (Wave 5).
#
# Single entry-point that vendor's automation (or an AI agent per #21)
# calls to provision a Hub + OpenBao + Postgres + Keycloak into the
# CUSTOMER's cloud account via the DELEGATED role they granted to Spine
# at sign-up (per docs/V3_DESIGN_DECISIONS.md §17 BYOC mechanics).
#
# This script is the orchestrator only: it (a) loads + validates inputs,
# (b) acquires an idempotency lock, (c) dispatches to the per-cloud
# implementation in tools/byoc/clouds/<cloud>.sh, (d) writes a structured
# handoff JSON to stdout. It does NOT itself talk to any cloud API.
#
# Design drivers (per docs/V3_DESIGN_DECISIONS.md):
#   #9   No secrets in scripts. All creds via `vault://<path>` refs, OR
#        runtime prompts (interactive only). Never written to disk.
#   #15  BYOC = Spine-company-managed-customer-cloud. Spine NEVER holds
#        customer secrets / data / workloads. This script runs from
#        VENDOR infrastructure, but every cloud API call inside it uses
#        the CUSTOMER's delegated role.
#   #17  4 deployment shapes; this script services shape #2 (BYOC).
#   #20  5+ clouds Day 1 — AWS + Azure + GCP + Railway + Fly + DigitalOcean.
#        Hostinger is long-tail (v1.1).
#   #21  Every interactive prompt has a non-interactive flag equivalent.
#   #18  No GPL / AGPL deps shipped in this script.
#   #11  This script is the manual entry point; long-term the devops
#        control plane (devops/planes/infrastructure.py) will invoke
#        this script (or its successor) programmatically. Wave 5 ships
#        the script + runbook; cross-wiring is post-v1.0.
#
# Exit codes (echoed at end on JSON line):
#   0  ok
#   1  generic failure
#   2  bad input (unknown flag, unknown cloud, missing required flag)
#   3  delegated-role validation failed
#   4  cloud-API failure
#   5  resource already exists, --force not given
#   6  unsupported (cloud / mode / region combination)
#
# Usage:
#   tools/byoc/provision.sh \
#       --cloud=aws --account=acct-12345 \
#       --hub-version=1.0.0 --bundle-id=$(uuidgen) \
#       --region=us-east-1 [--mode=eks] [--dry-run] [--non-interactive]
#
#   tools/byoc/provision.sh \
#       --config=path/to/byoc-config.yaml [--dry-run] [--non-interactive]
#
# YAML config schema (loaded via PyYAML; same keys as flags):
#   cloud: aws
#   account: acct-12345
#   hub_version: 1.0.0
#   bundle_id: 5e8f...
#   region: us-east-1
#   mode: eks
#   admin_email: ops@customer.com
#   credentials_ref: "vault://kv/byoc/acct-12345/aws_assume_role"
#   parent_hub_url: ""        # null for root Hub

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

BYOC_LOG_TAG="provision"

# ─── defaults ───────────────────────────────────────────────────────
SPINE_BYOC_CLOUD=""
SPINE_BYOC_ACCOUNT=""
SPINE_BYOC_REGION=""
SPINE_BYOC_MODE=""
SPINE_HUB_VERSION=""
SPINE_BYOC_BUNDLE_ID=""
SPINE_BYOC_ADMIN_EMAIL=""
SPINE_BYOC_PARENT_HUB_URL=""
SPINE_BYOC_CREDENTIALS_REF=""
SPINE_BYOC_CONFIG_PATH="${SPINE_BYOC_CONFIG:-}"
DESTROY=0
BYOC_DRY_RUN=0
BYOC_INTERACTIVE=1
BYOC_FORCE=0
EXPORT_ENV_BLOCK=()

# ─── arg parsing ────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
tools/byoc/provision.sh — Spine BYOC per-cloud orchestrator.

USAGE
  tools/byoc/provision.sh --cloud=<c> --account=<ref> [options...]
  tools/byoc/provision.sh --config=path/to/byoc-config.yaml [options...]

REQUIRED
  --cloud=NAME            aws | azure | gcp | railway | fly | do
  --account=REF           Customer's account/project reference (cloud-specific format).

PROVISIONING
  --hub-version=VER       Hub container version (semver), e.g. 1.0.0.
  --bundle-id=UUID        License bundle UUID for this customer (V22 schema).
  --region=NAME           Cloud region (e.g. us-east-1, westeurope, us-central1).
  --mode=MODE             Cloud-specific deployment mode. Defaults per-cloud:
                            aws    → ec2 (single-host)   alt: eks
                            azure  → vm                  alt: aks
                            gcp    → gce                 alt: gke
                            railway → service
                            fly    → machines
                            do     → app                  alt: doks
  --admin-email=ADDR      Initial Keycloak admin email (per hub/wizard/init.sh).
  --parent-hub-url=URL    Federation parent Hub (#10); empty = root Hub.
  --credentials-ref=REF   vault:// reference to delegated-role creds for THIS
                          provisioning run. Per #9. The cloud script resolves
                          this at runtime; the value is never logged.

MODE FLAGS
  --config=PATH           YAML config (alternative to flags). CLI flags win.
  --destroy               Tear down a previously provisioned BYOC stack.
                          Requires --cloud + --account. Refuses without
                          --force if state-file says the stack is healthy.
  --dry-run               Print the plan; don't call any cloud API.
  --non-interactive       Refuse to prompt. Every required value must be
                          set via flag or config. Per #21.
  --force                 Bypass idempotency lock + healthy-stack guard.
  -h, --help              Show this message.

EXAMPLES
  # Real provisioning, AWS, EC2 single-host (Founder tier default).
  tools/byoc/provision.sh \
    --cloud=aws --account=arn:aws:iam::123456789012:role/SpineByoc \
    --region=us-east-1 --mode=ec2 \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/acct-123/aws_assume_role

  # AI-driven dry-run, Railway.
  tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=railway --account=team_abc --hub-version=1.0.0 \
    --bundle-id=00000000-0000-0000-0000-000000000000 \
    --admin-email=founder@startup.com

  # Teardown.
  tools/byoc/provision.sh --destroy --cloud=aws \
    --account=arn:aws:iam::123456789012:role/SpineByoc --force

EOF
}

for arg in "$@"; do
  case "$arg" in
    --cloud=*)              SPINE_BYOC_CLOUD="$(byoc_flag_value "$arg")" ;;
    --account=*)            SPINE_BYOC_ACCOUNT="$(byoc_flag_value "$arg")" ;;
    --region=*)             SPINE_BYOC_REGION="$(byoc_flag_value "$arg")" ;;
    --mode=*)               SPINE_BYOC_MODE="$(byoc_flag_value "$arg")" ;;
    --hub-version=*)        SPINE_HUB_VERSION="$(byoc_flag_value "$arg")" ;;
    --bundle-id=*)          SPINE_BYOC_BUNDLE_ID="$(byoc_flag_value "$arg")" ;;
    --admin-email=*)        SPINE_BYOC_ADMIN_EMAIL="$(byoc_flag_value "$arg")" ;;
    --parent-hub-url=*)     SPINE_BYOC_PARENT_HUB_URL="$(byoc_flag_value "$arg")" ;;
    --credentials-ref=*)    SPINE_BYOC_CREDENTIALS_REF="$(byoc_flag_value "$arg")" ;;
    --config=*)             SPINE_BYOC_CONFIG_PATH="$(byoc_flag_value "$arg")" ;;
    --destroy)              DESTROY=1 ;;
    --dry-run)              BYOC_DRY_RUN=1 ;;
    --non-interactive)      BYOC_INTERACTIVE=0 ;;
    --force)                BYOC_FORCE=1 ;;
    -h|--help)              usage; exit 0 ;;
    *)
      BYOC_DIE_CODE=2 byoc_die "unknown flag: $arg (try --help)"
      ;;
  esac
done

export BYOC_DRY_RUN BYOC_INTERACTIVE BYOC_FORCE
export SPINE_BYOC_CLOUD SPINE_BYOC_ACCOUNT SPINE_BYOC_REGION SPINE_BYOC_MODE
export SPINE_HUB_VERSION SPINE_BYOC_BUNDLE_ID SPINE_BYOC_ADMIN_EMAIL
export SPINE_BYOC_PARENT_HUB_URL SPINE_BYOC_CREDENTIALS_REF

# ─── load YAML config (CLI flags win) ───────────────────────────────
load_config_yaml() {
  local path="$1"
  [[ -r "$path" ]] || BYOC_DIE_CODE=2 byoc_die "--config not readable: $path"
  if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    BYOC_DIE_CODE=2 byoc_die "--config requires PyYAML (pip install PyYAML)"
  fi
  # Print KEY=VALUE pairs we can eval safely.
  local kvs
  kvs="$(python3 - <<PY "$path"
import json, sys, yaml
with open(sys.argv[1]) as fp:
    cfg = yaml.safe_load(fp) or {}
allowed = {
    "cloud","account","region","mode","hub_version","bundle_id",
    "admin_email","parent_hub_url","credentials_ref",
}
for k, v in cfg.items():
    if k not in allowed:
        sys.stderr.write(f"[byoc:provision][WARN] ignoring unknown config key: {k}\n")
        continue
    if v is None:
        continue
    # Shell-safe: JSON-encode then strip quotes for primitives.
    s = json.dumps(str(v))
    print(f"_CFG_{k.upper()}={s}")
PY
  )"
  # shellcheck disable=SC1090
  eval "$kvs"
  [[ -z "$SPINE_BYOC_CLOUD"             && -n "${_CFG_CLOUD:-}"            ]] && SPINE_BYOC_CLOUD="${_CFG_CLOUD}"
  [[ -z "$SPINE_BYOC_ACCOUNT"           && -n "${_CFG_ACCOUNT:-}"          ]] && SPINE_BYOC_ACCOUNT="${_CFG_ACCOUNT}"
  [[ -z "$SPINE_BYOC_REGION"            && -n "${_CFG_REGION:-}"           ]] && SPINE_BYOC_REGION="${_CFG_REGION}"
  [[ -z "$SPINE_BYOC_MODE"              && -n "${_CFG_MODE:-}"             ]] && SPINE_BYOC_MODE="${_CFG_MODE}"
  [[ -z "$SPINE_HUB_VERSION"            && -n "${_CFG_HUB_VERSION:-}"      ]] && SPINE_HUB_VERSION="${_CFG_HUB_VERSION}"
  [[ -z "$SPINE_BYOC_BUNDLE_ID"         && -n "${_CFG_BUNDLE_ID:-}"        ]] && SPINE_BYOC_BUNDLE_ID="${_CFG_BUNDLE_ID}"
  [[ -z "$SPINE_BYOC_ADMIN_EMAIL"       && -n "${_CFG_ADMIN_EMAIL:-}"      ]] && SPINE_BYOC_ADMIN_EMAIL="${_CFG_ADMIN_EMAIL}"
  [[ -z "$SPINE_BYOC_PARENT_HUB_URL"    && -n "${_CFG_PARENT_HUB_URL:-}"   ]] && SPINE_BYOC_PARENT_HUB_URL="${_CFG_PARENT_HUB_URL}"
  [[ -z "$SPINE_BYOC_CREDENTIALS_REF"   && -n "${_CFG_CREDENTIALS_REF:-}"  ]] && SPINE_BYOC_CREDENTIALS_REF="${_CFG_CREDENTIALS_REF}"
}

if [[ -n "$SPINE_BYOC_CONFIG_PATH" ]]; then
  load_config_yaml "$SPINE_BYOC_CONFIG_PATH"
fi

# ─── interactive fallback (NEVER for credentials-ref) ───────────────
prompt_if_blank() {
  local var="$1" prompt="$2"
  [[ -n "${!var:-}" ]] && return 0
  if (( BYOC_INTERACTIVE == 0 )); then
    BYOC_DIE_CODE=2 byoc_die "non-interactive but $var is empty (set --${var,,//_/-} or use --config)"
  fi
  read -r -p "$prompt: " val
  printf -v "$var" '%s' "$val"
}

# ─── validate cloud ────────────────────────────────────────────────
# `${VAR,,}` (bash-4+ lowercase expansion) breaks on macOS bash 3.2;
# use `tr` for portability. Audit fix 2026-05-18.
SPINE_BYOC_CLOUD_LC="$(printf '%s' "$SPINE_BYOC_CLOUD" | tr '[:upper:]' '[:lower:]')"
case "$SPINE_BYOC_CLOUD_LC" in
  aws|azure|gcp|railway|fly|do) SPINE_BYOC_CLOUD="$SPINE_BYOC_CLOUD_LC" ;;
  "")
    prompt_if_blank SPINE_BYOC_CLOUD "Cloud (aws|azure|gcp|railway|fly|do)"
    ;;
  *) BYOC_DIE_CODE=6 byoc_die "unsupported --cloud=$SPINE_BYOC_CLOUD (got aws|azure|gcp|railway|fly|do; hostinger is v1.1)" ;;
esac

byoc_require SPINE_BYOC_CLOUD   --cloud

# Per-cloud script file.
CLOUD_SCRIPT="${SCRIPT_DIR}/clouds/${SPINE_BYOC_CLOUD}.sh"
[[ -r "$CLOUD_SCRIPT" ]] || BYOC_DIE_CODE=6 byoc_die "no cloud script at $CLOUD_SCRIPT"

# ─── destroy path ───────────────────────────────────────────────────
if (( DESTROY == 1 )); then
  byoc_require SPINE_BYOC_ACCOUNT --account
  byoc_banner "BYOC TEARDOWN — ${SPINE_BYOC_CLOUD} / ${SPINE_BYOC_ACCOUNT}"
  byoc_log "dispatching to $CLOUD_SCRIPT --destroy"
  # shellcheck disable=SC1090
  source "$CLOUD_SCRIPT"
  if ! declare -f byoc_destroy >/dev/null 2>&1; then
    byoc_die "$CLOUD_SCRIPT does not define byoc_destroy()"
  fi
  byoc_assert_credentials
  byoc_destroy
  byoc_log "teardown complete."
  exit 0
fi

# ─── provisioning path: gather + validate ───────────────────────────
byoc_require SPINE_BYOC_ACCOUNT       --account
prompt_if_blank SPINE_HUB_VERSION       "Hub version (semver, e.g. 1.0.0)"
prompt_if_blank SPINE_BYOC_BUNDLE_ID    "License bundle UUID"
prompt_if_blank SPINE_BYOC_ADMIN_EMAIL  "Initial admin email"

# Region + mode have per-cloud defaults; cloud script may set them.
# Credentials ref is REQUIRED in non-interactive mode. In interactive
# mode, we accept that the operator may have pre-loaded an environment
# (e.g. assumed role via okta-aws-cli), but we will WARN.
if [[ -z "$SPINE_BYOC_CREDENTIALS_REF" ]]; then
  if (( BYOC_INTERACTIVE == 0 )); then
    BYOC_DIE_CODE=2 byoc_die "non-interactive mode requires --credentials-ref=vault://… per #9"
  else
    byoc_warn "no --credentials-ref set; assuming caller pre-loaded delegated-role creds in the env."
  fi
fi

# Sanity-check the version + uuid shapes.
[[ "$SPINE_HUB_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.+-]+)?$ ]] \
  || BYOC_DIE_CODE=2 byoc_die "--hub-version not semver: $SPINE_HUB_VERSION"
[[ "$SPINE_BYOC_BUNDLE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] \
  || BYOC_DIE_CODE=2 byoc_die "--bundle-id not a UUID: $SPINE_BYOC_BUNDLE_ID"
[[ "$SPINE_BYOC_ADMIN_EMAIL" == *@* ]] \
  || BYOC_DIE_CODE=2 byoc_die "--admin-email malformed: $SPINE_BYOC_ADMIN_EMAIL"

byoc_banner "BYOC PROVISION — ${SPINE_BYOC_CLOUD} / ${SPINE_BYOC_ACCOUNT}"
byoc_log "hub-version    = $SPINE_HUB_VERSION"
byoc_log "bundle-id      = $SPINE_BYOC_BUNDLE_ID"
byoc_log "admin-email    = $SPINE_BYOC_ADMIN_EMAIL"
byoc_log "region         = ${SPINE_BYOC_REGION:-(cloud default)}"
byoc_log "mode           = ${SPINE_BYOC_MODE:-(cloud default)}"
byoc_log "parent-hub-url = ${SPINE_BYOC_PARENT_HUB_URL:-(root)}"
byoc_log "dry-run        = $BYOC_DRY_RUN"
byoc_log "non-interactive= $((1 - BYOC_INTERACTIVE))"
byoc_log "credentials    = ${SPINE_BYOC_CREDENTIALS_REF:-(env-preloaded)}"

# ─── idempotency lock ───────────────────────────────────────────────
byoc_acquire_lock "$SPINE_BYOC_CLOUD" "$SPINE_BYOC_ACCOUNT"

# ─── dispatch ───────────────────────────────────────────────────────
# shellcheck disable=SC1090
source "$CLOUD_SCRIPT"
if ! declare -f byoc_provision >/dev/null 2>&1; then
  byoc_die "$CLOUD_SCRIPT does not define byoc_provision()"
fi
byoc_assert_credentials
byoc_provision

byoc_log "provision returned cleanly."
exit 0

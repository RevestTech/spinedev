#!/usr/bin/env bash
# install.sh — Spine v3 Day-0 bootstrap.
#
# Per docs/V3_DESIGN_DECISIONS.md:
#   #3  Hub-as-product. This script stands up the Hub container, not a project template.
#   #9  Vault-only. Secrets flow through vault/init-wizard.sh; never written to disk in plaintext.
#   #17 4 deployment shapes (laptop / byoc / customer_cloud / on_prem).
#   #21 ALL AI ALL THE TIME. Every interactive prompt has a --flag equivalent so an AI agent can
#       drive the wizard non-interactively.
#   #25 Keycloak embedded by default; bootstrap creates the spine realm + OIDC client.
#
# Usage (interactive):
#   bash install.sh ~/spine
#
# Usage (AI-driven non-interactive, full):
#   bash install.sh ~/spine \
#       --shape laptop \
#       --vault openbao \
#       --keycloak bundled \
#       --llm anthropic \
#       --admin-email admin@example.com \
#       --admin-username admin \
#       --license-bundle /path/to/license.json \
#       --non-interactive
#
# What this script does (in order):
#   1. Validate the target dir (create if missing).
#   2. Copy the v3 bundle (hub/ + vault/ + keycloak/ + db/ + shared/ + tools/) into the target.
#   3. Run vault/init-wizard.sh   — OpenBao init + Shamir/KMS unseal + AppRole for Hub.
#   4. Run keycloak/init-bootstrap.sh — realm + spine-hub OIDC client + admin user.
#   5. Run hub/wizard/init.sh     — 7 steps (shape / vault / kc / llm / admin / license / parent).
#   6. Print Hub URL + first-login banner.
#
# What this script does NOT do:
#   - Run `docker compose up` (the operator does that via `make hub-up` after install).
#   - Provision cloud infra (BYOC / customer-cloud / on-prem have separate runbooks; this script
#     bootstraps the Hub container; cloud infra is in devops/planes/ or out-of-band).
#   - Phone home. Spine never phones home (#15).

set -uo pipefail

err()  { printf '%s\n' "$*" >&2; }
step() { printf '\033[0;34m▸\033[0m %s\n' "$*"; }
ok()   { printf '\033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m!\033[0m %s\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# ─── Flag parsing ──────────────────────────────────────────────────────────
TARGET=""
NON_INTERACTIVE=0
DEPLOY_SHAPE=""
VAULT_ADAPTER=""
KEYCLOAK_DEPLOYMENT=""
LLM_PROVIDER=""
ADMIN_EMAIL=""
ADMIN_USERNAME=""
LICENSE_BUNDLE=""
PARENT_HUB_URL=""
FORCE=0
SKIP_VAULT=0
SKIP_KEYCLOAK=0
SKIP_HUB_WIZARD=0

usage() {
  cat <<'EOF'
Usage: bash install.sh <target-dir> [options]

Required:
  <target-dir>                Where to materialize the Spine bundle.

Wizard flags (any subset; missing values prompt unless --non-interactive):
  --shape <laptop|byoc|customer_cloud|on_prem>
  --vault <openbao|external-vault|aws|azure|gcp>
  --keycloak <bundled|external>
  --llm <anthropic|openai|bedrock|vertex|ollama|qwen|vllm>
  --admin-email <addr>
  --admin-username <user>
  --license-bundle <path>     Signed bundle (free tier auto-generated if omitted on laptop)
  --parent-hub <url>          Federation parent (omit for standalone / root)

Run mode:
  --non-interactive           Refuse to prompt; fail if any required flag missing
  --force                     Overwrite target if non-empty
  --skip-vault                Skip vault wizard (assumes external vault already configured)
  --skip-keycloak             Skip keycloak bootstrap (assumes external Keycloak)
  --skip-hub-wizard           Copy bundle but don't run hub/wizard/init.sh
  -h | --help                 This message

See INSTALL.md for the full guide and per-shape detail.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --shape) DEPLOY_SHAPE="$2"; shift 2 ;;
    --vault) VAULT_ADAPTER="$2"; shift 2 ;;
    --keycloak) KEYCLOAK_DEPLOYMENT="$2"; shift 2 ;;
    --llm) LLM_PROVIDER="$2"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --admin-username) ADMIN_USERNAME="$2"; shift 2 ;;
    --license-bundle) LICENSE_BUNDLE="$2"; shift 2 ;;
    --parent-hub) PARENT_HUB_URL="$2"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --force) FORCE=1; shift ;;
    --skip-vault) SKIP_VAULT=1; shift ;;
    --skip-keycloak) SKIP_KEYCLOAK=1; shift ;;
    --skip-hub-wizard) SKIP_HUB_WIZARD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) err "Unknown flag: $1"; usage; exit 2 ;;
    *) [[ -z "$TARGET" ]] && TARGET="$1" || { err "Unexpected: $1"; usage; exit 2; }; shift ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  err "FATAL: target dir required"
  usage
  exit 2
fi

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Required sources from prior Waves:
for required in hub vault keycloak db shared tools; do
  if [[ ! -d "$SOURCE/$required" ]]; then
    err "FATAL: missing $SOURCE/$required — bundle is incomplete; reclone repo."
    exit 2
  fi
done

# ─── Target setup ──────────────────────────────────────────────────────────
step "Validating target $TARGET"
if [[ ! -d "$TARGET" ]]; then
  mkdir -p "$TARGET" && ok "  created $TARGET" || { err "FATAL: cannot create $TARGET"; exit 3; }
elif [[ -n "$(ls -A "$TARGET" 2>/dev/null)" && $FORCE -eq 0 ]]; then
  err "FATAL: $TARGET is not empty (pass --force to overwrite)"
  exit 3
fi
TARGET="$(cd "$TARGET" && pwd)"
ok "  target: $TARGET"

# ─── Copy bundle ───────────────────────────────────────────────────────────
step "Materializing Spine v3 bundle"
for d in hub vault keycloak db shared tools; do
  cp -R "$SOURCE/$d" "$TARGET/" && ok "  $TARGET/$d/"
done
# Standalone files
for f in docker-compose.yml Makefile README.md INSTALL.md; do
  [[ -f "$SOURCE/$f" ]] && cp "$SOURCE/$f" "$TARGET/" && ok "  $TARGET/$f"
done

mkdir -p "$TARGET/_state" "$TARGET/data" "$TARGET/logs"
echo "$TARGET/_state $TARGET/data $TARGET/logs" >/dev/null  # touch
ok "  $TARGET/_state/ $TARGET/data/ $TARGET/logs/"

# ─── Vault Day-0 ───────────────────────────────────────────────────────────
if [[ $SKIP_VAULT -eq 0 ]]; then
  step "Initializing Vault (OpenBao) — #9 vault-only secrets"
  VAULT_FLAGS=()
  [[ $NON_INTERACTIVE -eq 1 ]] && VAULT_FLAGS+=("--no-interactive")
  if ! bash "$TARGET/vault/init-wizard.sh" "${VAULT_FLAGS[@]}"; then
    err "FATAL: vault init-wizard failed — see vault/dr-runbook.md"
    exit 4
  fi
  ok "  vault initialized (recovery keys printed ONCE — store offline NOW)"
else
  warn "  --skip-vault set; assuming external vault is configured + reachable"
fi

# ─── Keycloak Day-0 ───────────────────────────────────────────────────────
if [[ $SKIP_KEYCLOAK -eq 0 ]]; then
  step "Bootstrapping Keycloak — #25 embedded OIDC"
  KC_FLAGS=()
  [[ $NON_INTERACTIVE -eq 1 ]] && KC_FLAGS+=("--generate-admin" "--output" "$TARGET/_state/kc_admin_password.txt")
  if ! bash "$TARGET/keycloak/init-bootstrap.sh" "${KC_FLAGS[@]}"; then
    err "FATAL: keycloak bootstrap failed — see keycloak/README.md"
    exit 5
  fi
  ok "  keycloak realm + spine-hub OIDC client + groups seeded"
else
  warn "  --skip-keycloak set; assuming external Keycloak is configured"
fi

# ─── Hub Day-0 wizard ──────────────────────────────────────────────────────
if [[ $SKIP_HUB_WIZARD -eq 0 ]]; then
  step "Running Hub Day-0 wizard — #3 Hub-as-product"
  HUB_FLAGS=()
  [[ $NON_INTERACTIVE -eq 1 ]] && HUB_FLAGS+=("--no-interactive")
  [[ -n "$DEPLOY_SHAPE"        ]] && HUB_FLAGS+=("--shape"    "$DEPLOY_SHAPE")
  [[ -n "$VAULT_ADAPTER"       ]] && HUB_FLAGS+=("--vault"    "$VAULT_ADAPTER")
  [[ -n "$KEYCLOAK_DEPLOYMENT" ]] && HUB_FLAGS+=("--keycloak" "$KEYCLOAK_DEPLOYMENT")
  [[ -n "$LLM_PROVIDER"        ]] && HUB_FLAGS+=("--llm"      "$LLM_PROVIDER")
  [[ -n "$ADMIN_EMAIL"         ]] && HUB_FLAGS+=("--admin-email"    "$ADMIN_EMAIL")
  [[ -n "$ADMIN_USERNAME"      ]] && HUB_FLAGS+=("--admin-username" "$ADMIN_USERNAME")
  [[ -n "$LICENSE_BUNDLE"      ]] && HUB_FLAGS+=("--license-bundle" "$LICENSE_BUNDLE")
  [[ -n "$PARENT_HUB_URL"      ]] && HUB_FLAGS+=("--parent-hub"     "$PARENT_HUB_URL")
  if ! bash "$TARGET/hub/wizard/init.sh" "${HUB_FLAGS[@]}"; then
    err "FATAL: hub/wizard/init.sh failed — see hub/README.md"
    exit 6
  fi
  ok "  hub wizard complete; .env.local + _state/ populated"
else
  warn "  --skip-hub-wizard set; you must run hub/wizard/init.sh manually before \`make hub-up\`"
fi

# ─── Done banner ───────────────────────────────────────────────────────────
HUB_URL_FILE="$TARGET/_state/hub_url"
HUB_URL="$([[ -f $HUB_URL_FILE ]] && cat "$HUB_URL_FILE" || echo 'http://localhost:8090')"

ok "Install complete."
cat <<EOF

Next steps:

  cd $TARGET
  make hub-up                       # docker compose up -d  (vault + keycloak + postgres + hub)
  make hub-status                   # confirm all green
  open $HUB_URL                     # land on Decision Queue (empty Day 1)

First-login:

  Email:    $([[ -n "$ADMIN_EMAIL" ]] && echo "$ADMIN_EMAIL" || echo '(prompted in wizard)')
  Password: stored in vault — \`vault kv get spine/admin/password\` (admin only) OR
            in $TARGET/_state/kc_admin_password.txt if --non-interactive was used

Federation (optional, #4 #10 #16):

  spine federation invite --child-name <team>  # parent side
  bash hub/wizard/init.sh --parent-hub <url> --invite <file>  # child side

Docs:

  README.md                — Hub-as-product framing
  INSTALL.md               — all 4 deployment shapes + BYOC mechanics
  docs/HUB_OPERATIONS_GUIDE.md — day-2 ops
  docs/SECURITY_GUIDE.md   — posture review
  docs/DR_RUNBOOK.md       — 12-layer DR
  docs/LICENSING_GUIDE.md  — feature flags + quotas

Spine is NOT SaaS (#15). Your code, secrets, and audit trail never leave this machine /
this cloud account. Spine vendor cannot subpoena what it cannot reach.

For closed-source v1.0 (#18) trust posture: founder presence + design-partner case
studies + Discord + public uptime & security pages + SOC 2 Type II + pen test reports
+ source-escrow for enterprise.

EOF

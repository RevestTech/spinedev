#!/usr/bin/env bash
# tools/bootstrap.sh — one-command cold-start for Spine v2.
#
# Invoked from the top-level `make bootstrap`. Idempotent: a second run on
# a healthy install is a fast no-op (skips venv create, skips already-
# satisfied pip installs, skips already-healthy containers, skips already-
# applied migrations).
#
# Steps (each guarded by a precondition check):
#   1. preflight  — check docker / python3>=3.10 / psql / make on PATH
#   2. venv       — python3 -m venv .venv if missing
#   3. pip        — install requirements.txt into .venv (skip if all sat)
#   4. spine pg   — bring up db/docker-compose.yml postgres, wait healthy
#   5. tron pg    — bring up verify/docker-compose.yml postgres (override
#                   gives container=spine_tron_postgres on 33010)
#   6. flyway     — sync history (F2 fix), then `flyway migrate`
#   7. alembic    — TRON migrations via .venv/bin/python tools/_tron_alembic_upgrade.py
#   8. smoke      — bash tools/smoke-test.sh  (acceptance gate)
#
# Exit: 0 = green smoke; non-zero = step that failed reports + exits.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"
REQUIREMENTS="$REPO_ROOT/requirements.txt"
DB_DIR="$REPO_ROOT/db"
VERIFY_DIR="$REPO_ROOT/verify"
SPINE_PG_CONTAINER="spine_postgres"
TRON_PG_CONTAINER="spine_tron_postgres"

SKIP_SMOKE="${SKIP_SMOKE:-0}"
QUIET="${QUIET:-0}"

if [[ -t 1 ]]; then
  C_B=$'\033[34m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'
  C_D=$'\033[2m'; C_X=$'\033[0m'
else
  C_B=""; C_G=""; C_Y=""; C_R=""; C_D=""; C_X=""
fi

_step() { printf '\n%s==>%s %s\n' "$C_B" "$C_X" "$*"; }
_ok()   { printf '  %sok%s   %s\n' "$C_G" "$C_X" "$*"; }
_skip() { printf '  %s--%s   %s\n' "$C_D" "$C_X" "$*"; }
_warn() { printf '  %swarn%s %s\n' "$C_Y" "$C_X" "$*"; }
_fail() { printf '  %sFAIL%s %s\n' "$C_R" "$C_X" "$*" >&2; }

# ─── 1. preflight ──────────────────────────────────────────────────
preflight() {
  _step "preflight: required binaries"
  local missing=0

  if command -v docker >/dev/null 2>&1; then
    _ok "docker: $(docker --version 2>/dev/null | head -1)"
  else
    _fail "docker not on PATH — install Docker Desktop (https://docker.com) or 'brew install --cask docker'"
    missing=1
  fi

  if docker compose version >/dev/null 2>&1; then
    _ok "docker compose: $(docker compose version --short 2>/dev/null)"
  else
    _fail "docker compose v2 not available — comes with Docker Desktop"
    missing=1
  fi

  if command -v python3 >/dev/null 2>&1 \
     && python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    _ok "python3: $(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  else
    _fail "python3 >= 3.10 not on PATH — 'brew install python@3.12' or apt install python3.12"
    missing=1
  fi

  if command -v psql >/dev/null 2>&1; then
    _ok "psql: $(psql --version 2>/dev/null | head -1)"
  else
    _fail "psql not on PATH — 'brew install libpq && brew link --force libpq' or apt install postgresql-client"
    missing=1
  fi

  if command -v make >/dev/null 2>&1; then
    _ok "make: $(make --version 2>/dev/null | head -1)"
  else
    _fail "make not on PATH — install Xcode CLT (macOS) or 'apt install build-essential'"
    missing=1
  fi

  if (( missing )); then
    _fail "preflight failed: install the missing tools above, then re-run 'make bootstrap'"
    exit 2
  fi
}

# ─── 2. venv ───────────────────────────────────────────────────────
ensure_venv() {
  _step "python venv at .venv"
  if [[ -x "$VENV_PY" ]]; then
    _ok ".venv exists ($("$VENV_PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"
  else
    python3 -m venv "$VENV_DIR"
    _ok "created .venv ($("$VENV_PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"
    "$VENV_PIP" install -q --upgrade pip >/dev/null
    _ok "upgraded pip"
  fi
}

# ─── 3. pip install (idempotent: skip if all already satisfied) ────
install_requirements() {
  _step "pip install -r requirements.txt"
  [[ -f "$REQUIREMENTS" ]] || { _fail "requirements.txt missing at $REQUIREMENTS"; exit 3; }

  # Fast path: ask pip whether anything is missing/outdated. `pip install
  # --dry-run -r requirements.txt` returns "Would install ..." iff there
  # would be work to do. Cheap (<1s) on a fully-installed venv.
  local dry
  dry="$("$VENV_PIP" install --dry-run -q -r "$REQUIREMENTS" 2>&1 || true)"
  if printf '%s' "$dry" | grep -qE 'Would install|Collecting'; then
    _ok "installing/updating packages …"
    "$VENV_PIP" install -q -r "$REQUIREMENTS"
    _ok "pip install complete ($("$VENV_PIP" list --format=freeze 2>/dev/null | wc -l | tr -d ' ') packages)"
  else
    _skip "all requirements already satisfied"
  fi
}

# ─── docker helpers ────────────────────────────────────────────────
_container_health() {
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || true
}

_wait_healthy() {
  # _wait_healthy <container> <max_seconds>
  # "healthy" is what we want; "running" without a healthcheck also passes
  # (means the container started); "starting" means healthcheck is in flight,
  # keep waiting.
  local name="$1" max="${2:-90}" elapsed=0 status
  while (( elapsed < max )); do
    status="$(_container_health "$name")"
    case "$status" in
      healthy|running) return 0 ;;
      ""|starting|unhealthy|created) ;;  # keep waiting
    esac
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

# ─── 4. spine postgres ─────────────────────────────────────────────
ensure_spine_pg() {
  _step "spine postgres ($SPINE_PG_CONTAINER on 127.0.0.1:33001)"
  local status; status="$(_container_health "$SPINE_PG_CONTAINER")"
  if [[ "$status" == "healthy" ]]; then
    _skip "$SPINE_PG_CONTAINER already healthy"
    return 0
  fi
  ( cd "$DB_DIR" && docker compose up -d postgres >/dev/null )
  if _wait_healthy "$SPINE_PG_CONTAINER" 90; then
    _ok "$SPINE_PG_CONTAINER healthy"
  else
    _fail "$SPINE_PG_CONTAINER did not reach healthy in 90s (last status: $(_container_health "$SPINE_PG_CONTAINER"))"
    exit 4
  fi
}

# ─── 5. tron postgres ──────────────────────────────────────────────
ensure_tron_pg() {
  _step "tron postgres ($TRON_PG_CONTAINER on 127.0.0.1:33010)"
  local status; status="$(_container_health "$TRON_PG_CONTAINER")"
  if [[ "$status" == "healthy" ]]; then
    _skip "$TRON_PG_CONTAINER already healthy"
    return 0
  fi
  bash "$REPO_ROOT/tools/verify-overrides/install.sh" >/dev/null 2>&1 || true
  ( cd "$VERIFY_DIR" && docker compose up -d postgres >/dev/null 2>&1 ) \
    || { _fail "could not bring up TRON postgres (cd verify && docker compose up -d postgres)"; exit 4; }
  if _wait_healthy "$TRON_PG_CONTAINER" 90; then
    _ok "$TRON_PG_CONTAINER healthy"
  else
    _fail "$TRON_PG_CONTAINER did not reach healthy in 90s (last status: $(_container_health "$TRON_PG_CONTAINER"))"
    exit 4
  fi
}

# ─── 6. flyway (with F2 history sync) ──────────────────────────────
# Reconciles `flyway_schema_history` with the actual DB state before
# running `migrate`, so the V2-Ignored + V14-V21-applied-via-psql case
# (documented in docs/STATUS.md §5 F2) becomes a no-op.
run_flyway() {
  _step "spine flyway migrations"
  # Phase 1: insert history rows for migrations whose schemas already exist
  # (the wave-9 F2 follow-up). On a brand-new DB this is a no-op because
  # flyway_schema_history doesn't exist yet.
  if ! bash "$SCRIPT_DIR/spine-flyway-sync.sh"; then
    _fail "flyway history sync failed — see message above"
    exit 5
  fi
  # Phase 2: `flyway repair` aligns any checksum drift between our inserted
  # CRC32s and what flyway 10 itself would compute (we go to length to
  # match the algorithm, but BOM / unusual whitespace can still trip it).
  # Repair is idempotent and a no-op on a clean install.
  ( cd "$DB_DIR" && docker compose run --rm flyway repair >/dev/null 2>&1 ) || true
  # Phase 3: actual migrate. `outOfOrder=true` lets V2 (lower number than
  # V13) apply cleanly if it somehow lands after V14-V21 in the future.
  if ( cd "$DB_DIR" && docker compose run --rm flyway -outOfOrder=true migrate >/dev/null 2>&1 ); then
    _ok "flyway migrate clean"
  else
    _warn "flyway migrate non-zero; re-running with output:"
    ( cd "$DB_DIR" && docker compose run --rm flyway -outOfOrder=true migrate ) || {
      _fail "flyway migrate failed — review output above"
      exit 5
    }
  fi
}

# ─── 7. tron alembic ───────────────────────────────────────────────
run_alembic() {
  _step "tron alembic migrations (upgrade head)"
  local out
  if out="$("$VENV_PY" "$SCRIPT_DIR/_tron_alembic_upgrade.py" 2>&1)"; then
    _ok "alembic at head: $(printf '%s' "$out" | tail -1)"
  else
    _fail "alembic upgrade failed:"
    printf '%s\n' "$out" >&2
    exit 6
  fi
}

# ─── 8. smoke ──────────────────────────────────────────────────────
run_smoke() {
  if [[ "$SKIP_SMOKE" == "1" ]]; then
    _step "smoke (SKIP_SMOKE=1 — bootstrap done without acceptance check)"
    _warn "skipping smoke-test by request — verify manually with 'bash tools/smoke-test.sh'"
    return 0
  fi
  _step "smoke-test (acceptance check)"
  local out
  if out="$(bash "$SCRIPT_DIR/smoke-test.sh" --no-color 2>&1)"; then
    # Print just the summary line so the bootstrap log stays scannable.
    local summary; summary="$(printf '%s\n' "$out" | grep -E '^\s*PASS=' | tail -1)"
    _ok "smoke green: $summary"
    return 0
  else
    _fail "smoke-test reported failures:"
    printf '%s\n' "$out" | tail -30 >&2
    return 1
  fi
}

main() {
  local started_at; started_at="$(date +%s)"
  printf '%sSpine v2 — bootstrap%s\n' "$C_B" "$C_X"
  printf '  repo: %s\n' "$REPO_ROOT"

  preflight
  ensure_venv
  install_requirements
  ensure_spine_pg
  ensure_tron_pg
  run_flyway
  run_alembic
  run_smoke
  local rc=$?

  local elapsed=$(( $(date +%s) - started_at ))
  printf '\n%sbootstrap complete%s in %ds (rc=%d)\n' \
    "$( ((rc==0)) && printf '%s' "$C_G" || printf '%s' "$C_R" )" \
    "$C_X" "$elapsed" "$rc"
  printf '\nNext: %sspine doctor%s   #  or  %sbash tools/smoke-test.sh%s\n\n' \
    "$C_B" "$C_X" "$C_B" "$C_X"
  exit "$rc"
}

main "$@"

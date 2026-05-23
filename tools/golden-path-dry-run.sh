#!/usr/bin/env bash
# tools/golden-path-dry-run.sh — verify golden-path MCP + bridge wiring (no LLM).
#
# Exercises orchestrator bridge mappings and legacy build brief synthesis.
# Safe to run overnight / in CI without ANTHROPIC_API_KEY.
#
# Usage:
#   bash tools/golden-path-dry-run.sh

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
fi

export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Reuse smoke DB discovery when present.
if [[ -f "${REPO_ROOT}/db/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${REPO_ROOT}/db/.env"
  set +a
  SPINE_DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT:-33000}/${POSTGRES_DB}"
  export SPINE_DB_URL
fi

python3 "${REPO_ROOT}/tools/golden-path-dry-run.py"
echo "[golden-path-dry-run] PASS"

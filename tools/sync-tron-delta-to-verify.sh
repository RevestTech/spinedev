#!/usr/bin/env bash
# Sync standalone Tron repo → Spine verify/ (one-way delta import).
#
# Preserves Spine-only verify/ additions:
#   charter_evals/ agent_audit/ runtime/ SUBSYSTEM_BOUNDARY.md LLM_BRIDGE.md
#   __init__.py  docker-compose.override.yml (symlink)
# Preserves Spine LLM bridge shim: verify/tron/infra/llm/client.py
#
# Usage:
#   TRON_ROOT=~/path/to/Tron bash tools/sync-tron-delta-to-verify.sh
#   TRON_ROOT defaults to iCloud Archive Utilities/Tron if present.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPINE_VERIFY="${REPO_ROOT}/verify"
DEFAULT_TRON="${HOME}/Library/CloudStorage/iCloudDrive-iCloudDrive (1-19-26 12:14 PM)/com~apple~CloudDocs/Archive/Projects/Utilities/Tron"
TRON_ROOT="${TRON_ROOT:-$DEFAULT_TRON}"

if [[ ! -d "${TRON_ROOT}/tron" ]]; then
  printf 'TRON_ROOT missing tron/: %s\n' "$TRON_ROOT" >&2
  exit 1
fi

SHIM_BACKUP="$(mktemp)"
trap 'rm -f "$SHIM_BACKUP"' EXIT
cp "${SPINE_VERIFY}/tron/infra/llm/client.py" "$SHIM_BACKUP"

rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.env' \
  --exclude '.cursor' \
  --exclude 'admin' \
  --exclude 'Utilities' \
  --exclude 'node_modules' \
  --exclude 'frontend/dist' \
  --exclude 'frontend/node_modules' \
  --exclude 'admin-ui/node_modules' \
  --exclude 'admin-ui/dist' \
  "${TRON_ROOT}/" "${SPINE_VERIFY}/"

cp "$SHIM_BACKUP" "${SPINE_VERIFY}/tron/infra/llm/client.py"

printf 'Synced %s → %s (LLM shim preserved)\n' "$TRON_ROOT" "$SPINE_VERIFY"

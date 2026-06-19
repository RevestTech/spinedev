#!/usr/bin/env bash
# tools/spine-on-spine.sh — bootstrap a Spine-on-Spine dogfood project.
#
# Creates a Hub project whose engineer workspace targets
# ``.spine/dogfood/<uuid>/`` (safe sandbox). Set
# ``SPINE_ON_SPINE_ALLOW_REPO_WRITE=1`` only when you intend to patch the
# platform repo directly (advanced; default off).
#
# Usage:
#   bash tools/spine-on-spine.sh
#   bash tools/spine-on-spine.sh "Improve phase watcher"
#   HUB_URL=http://localhost:8090 bash tools/spine-on-spine.sh

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

readonly HUB_URL="${HUB_URL:-http://localhost:8090}"
readonly PROJECT_NAME="${1:-Spine on Spine}"

echo "[spine-on-spine] Hub URL: ${HUB_URL}"
echo "[spine-on-spine] Project: ${PROJECT_NAME}"
echo "[spine-on-spine] Workspace sandbox: ${REPO_ROOT}/.spine/dogfood/<uuid>/"
echo "[spine-on-spine] Repo write: ${SPINE_ON_SPINE_ALLOW_REPO_WRITE:-0} (set =1 to patch platform repo)"

payload="$(cat <<EOF
{
  "name": "${PROJECT_NAME}",
  "project_type": "feature",
  "spine_on_spine": true,
  "greenfield": false,
  "description": "Dogfood project — improve Spine using Spine roles and gates."
}
EOF
)"

if ! command -v curl >/dev/null 2>&1; then
  echo "[spine-on-spine] curl not found — create project manually via Hub SPA or POST ${HUB_URL}/api/v2/projects"
  echo "${payload}"
  exit 0
fi

resp="$(curl -sS -X POST "${HUB_URL}/api/v2/projects" \
  -H "Content-Type: application/json" \
  -d "${payload}" || true)"

if [[ -z "${resp}" ]]; then
  echo "[spine-on-spine] Hub unreachable at ${HUB_URL}. Start Hub first:"
  echo "  # Export ANTHROPIC_API_KEY from vault (see docs/HUB_OPERATIONS_GUIDE.md)"
  echo "  bash tools/hub-up.sh --rebuild"
  exit 1
fi

echo "${resp}" | python3 -m json.tool 2>/dev/null || echo "${resp}"

echo
echo "[spine-on-spine] Next: open ${HUB_URL}/spa/ → Decision Queue → approve intake card."
echo "[spine-on-spine] Engineer output lands under .spine/dogfood/ unless repo write is enabled."

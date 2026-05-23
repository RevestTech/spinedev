#!/usr/bin/env bash
# tools/golden-path-walkthrough.sh — automated golden-path card approvals.
#
# Creates a spine_on_spine Hub project, polls the decision queue, and acks
# pending cards until the queue is empty or MAX_ITERATIONS is reached.
# Requires Hub running with SPINE_HUB_DEV=1 (no auth header).
#
# Usage:
#   bash tools/golden-path-walkthrough.sh
#   bash tools/golden-path-walkthrough.sh "Improve phase watcher"
#   BASE=http://localhost:8090 bash tools/golden-path-walkthrough.sh

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

readonly BASE="${BASE:-http://localhost:8090}"
readonly PROJECT_NAME="${1:-Golden Path Walkthrough}"
readonly MAX_ITERATIONS="${MAX_ITERATIONS:-50}"
readonly POLL_SLEEP_SEC="${POLL_SLEEP_SEC:-3}"

echo "[golden-path-walkthrough] Hub URL: ${BASE}"
echo "[golden-path-walkthrough] Project: ${PROJECT_NAME}"
echo "[golden-path-walkthrough] Auth: none (expect SPINE_HUB_DEV=1 on Hub)"
echo "[golden-path-walkthrough] Max iterations: ${MAX_ITERATIONS}"

if ! command -v curl >/dev/null 2>&1; then
  echo "[golden-path-walkthrough] curl not found — install curl or run python3 tools/golden-path-walkthrough.py"
  exit 1
fi

export BASE PROJECT_NAME MAX_ITERATIONS POLL_SLEEP_SEC
python3 "${REPO_ROOT}/tools/golden-path-walkthrough.py"

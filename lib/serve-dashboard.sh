#!/usr/bin/env bash
# serve-dashboard.sh — static HTTP server for Spine Control Center.
#
# The dashboard uses fetch("../agent-handoff/...") from /dashboard/, so the HTTP
# root must be .planning/orchestration (not your framework API on another port).
#
# Usage (from repo root):
#   bash scripts/serve-dashboard.sh
#   SPINE_DASH_PORT=8765 bash scripts/serve-dashboard.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCH="$REPO_ROOT/.planning/orchestration"
PORT="${SPINE_DASH_PORT:-60005}"

if [[ ! -d "$ORCH/agent-handoff/teams" ]]; then
  printf '%s\n' "Missing $ORCH/agent-handoff/teams — install Spine in this repo first (bash install.sh .)." >&2
  exit 1
fi

if [[ ! -f "$ORCH/dashboard/index.html" ]]; then
  printf '%s\n' "Missing $ORCH/dashboard/index.html — install or copy lib/dashboard.html there." >&2
  exit 1
fi

cd "$ORCH" || exit 1
printf '%s\n' "Spine Control Center (static):  http://127.0.0.1:${PORT}/dashboard/"
printf '%s\n' "Serving directory: $(pwd)"
printf '%s\n' "(This is not your app backend — Fastify/Express /dashboard routes will 404.)"
printf '%s\n' "If bind fails, pick a free port: SPINE_DASH_PORT=8765 bash scripts/serve-dashboard.sh"
exec python3 -m http.server "$PORT"

#!/usr/bin/env bash
# Broader QA gate — narrow ci-test.sh plus high-signal shared/ API + MCP suites.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

echo "==> fc-sdlc narrow QA (pm.config default)"
bash "$(dirname "$0")/ci-test.sh"

echo "==> shared API route tests"
"$PY" -m pytest -q --tb=line \
  shared/api/tests/test_routes_projects.py \
  shared/api/tests/test_routes_decisions.py \
  shared/api/tests/test_post_ack_golden_path.py \
  shared/api/tests/test_csrf_middleware.py \
  shared/api/tests/test_rate_limit.py

echo "==> shared MCP smoke"
"$PY" -m pytest -q --tb=line shared/mcp/tests/test_server_smoke.py

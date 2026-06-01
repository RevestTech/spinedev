#!/usr/bin/env bash
# Spine mixed-stack CI test runner (fc-sdlc)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

echo "==> python smoke tests"
"$PY" -m pytest -q --tb=line \
  db/dashboard/tests/test_approval.py \
  shared/api/tests/test_metadata_dict_helper.py

echo "==> hub SPA vitest"
cd shared/ui/spa && npm run test -- --run

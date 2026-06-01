#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ -f package.json ]] && npm run 2>/dev/null | grep -q ' typecheck'; then
  npm run typecheck
elif command -v mypy >/dev/null 2>&1; then
  mypy .
else
  echo "No typecheck configured — skip or implement"
  exit 0
fi

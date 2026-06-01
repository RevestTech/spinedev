#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ -f package.json ]] && npm run 2>/dev/null | grep -q ' lint'; then
  npm run lint
elif command -v ruff >/dev/null 2>&1; then
  ruff check .
else
  echo "No linter configured — skip or implement"
  exit 0
fi

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ -f package.json ]] && npm run 2>/dev/null | grep -q ' build'; then
  npm run build
elif [[ -f pyproject.toml ]]; then
  python -m build
elif ls *.sln >/dev/null 2>&1; then
  dotnet build
else
  echo "No build target — skip or implement"
  exit 0
fi

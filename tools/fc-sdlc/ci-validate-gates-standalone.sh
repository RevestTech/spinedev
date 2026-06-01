#!/usr/bin/env bash
# Gate validation for CI when FutureCapital/SDLC sibling is not checked out.
# Full validator: npm run sdlc:validate-gates (requires ../../FutureCapital/Engineering/SDLC).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

errors=0

for g in todo/gates/G*.md; do
  [[ -f "$g" ]] || { echo "missing gate file: $g"; errors=$((errors + 1)); }
done

while IFS= read -r -d '' f; do
  if grep -q '{{' "$f"; then
    echo "placeholder in $f"
    grep -n '{{' "$f" || true
    errors=$((errors + 1))
  fi
done < <(find todo -name '*.md' -print0)

[[ -f pm.config.json ]] || { echo "missing pm.config.json"; errors=$((errors + 1)); }
[[ -f todo/BACKLOG.md ]] || { echo "missing todo/BACKLOG.md"; errors=$((errors + 1)); }

if [[ "$errors" -gt 0 ]]; then
  echo "ci-validate-gates-standalone: FAIL ($errors checks)"
  exit 1
fi

echo "ci-validate-gates-standalone: PASS"

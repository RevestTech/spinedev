#!/usr/bin/env bash
# dogfood.sh — Harness Lite dogfood on SpineDevelopment (no Hub required).
#
# Usage:
#   bash tools/harness/dogfood.sh
#   bash tools/harness/dogfood.sh --smoke   # include tools/smoke-test.sh --ci
set -euo pipefail

HARNESS_TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_TOOL_ROOT}/../.." && pwd)"
RUN_SMOKE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) RUN_SMOKE=1; shift ;;
    -h|--help)
      echo "Usage: bash tools/harness/dogfood.sh [--smoke]"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

cd "${REPO_ROOT}"
export SPINE_HOME="${REPO_ROOT}"

echo "[dogfood] Harness Lite on ${REPO_ROOT} (no Hub)"

bash "${HARNESS_TOOL_ROOT}/spine-harness" stop --project "${REPO_ROOT}" 2>/dev/null || true
bash "${HARNESS_TOOL_ROOT}/spine-harness" init --project "${REPO_ROOT}" --symlink-skills
bash "${HARNESS_TOOL_ROOT}/spine-harness" start feature --project "${REPO_ROOT}"

echo "[dogfood] audit-wave (deterministic scanners) ..."
AUDIT_EXIT=0
bash "${HARNESS_TOOL_ROOT}/spine-harness" audit --project "${REPO_ROOT}" || AUDIT_EXIT=$?

echo "[dogfood] verify-wave (charter evals, lite stub) ..."
VERIFY_EXIT=0
bash "${HARNESS_TOOL_ROOT}/spine-harness" verify --project "${REPO_ROOT}" --markdown || VERIFY_EXIT=$?

REPORT="${REPO_ROOT}/.spine/harness/reports/dogfood-latest.md"
LATEST="${REPO_ROOT}/.spine/harness/reports/latest.md"
mkdir -p "$(dirname "${REPORT}")"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

SMOKE_SUMMARY="skipped (pass --smoke to run tools/smoke-test.sh --ci)"
SMOKE_EXIT=0
TESTS_GATE="unknown"

if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  echo "[dogfood] running smoke-test.sh --ci ..."
  set +e
  SMOKE_OUT="$(mktemp)"
  bash "${REPO_ROOT}/tools/smoke-test.sh" --ci >"${SMOKE_OUT}" 2>&1
  SMOKE_EXIT=$?
  set -e
  if [[ "${SMOKE_EXIT}" -eq 0 ]] && {
    grep -qE 'FAIL=0' "${SMOKE_OUT}" ||
    grep -qE 'failures="0"' "${SMOKE_OUT}";
  }; then
    TESTS_GATE="green"
    if grep -qE 'PASS=[0-9]+' "${SMOKE_OUT}"; then
      SMOKE_SUMMARY="$(grep -E 'PASS=[0-9]+' "${SMOKE_OUT}" | tail -1 | tr -d ' ')"
    else
      SMOKE_SUMMARY="smoke pass (exit ${SMOKE_EXIT}, JUnit failures=0)"
    fi
  else
    TESTS_GATE="red"
    SMOKE_SUMMARY="smoke failed (exit ${SMOKE_EXIT}) — see report"
  fi
  SMOKE_TAIL="$(tail -20 "${SMOKE_OUT}")"
  rm -f "${SMOKE_OUT}"
else
  SMOKE_TAIL=""
fi

python3 "${HARNESS_TOOL_ROOT}/lib/harness_state.py" \
  --project "${REPO_ROOT}" set-gate tests "${TESTS_GATE}" --report "${REPORT}"

cat >"${REPORT}" <<EOF
# Harness Lite dogfood — SpineDevelopment

- **Generated:** ${TS}
- **Mode:** feature (no Hub)
- **Project:** \`${REPO_ROOT}\`

## Smoke / tests gate

- **QA command:** \`bash tools/smoke-test.sh --ci\` (optional: \`bash tools/harness/dogfood.sh --smoke\`)
- **Result:** ${SMOKE_SUMMARY}
- **Gate \`tests\`:** \`${TESTS_GATE}\`

## Harness status snapshot

\`\`\`
$(bash "${HARNESS_TOOL_ROOT}/spine-harness" status --markdown --project "${REPO_ROOT}")
\`\`\`

## Harness verify-wave (charter evals)

- **Command:** \`bash tools/harness/spine-harness verify\`
- **Exit code:** ${VERIFY_EXIT}
- **Latest report:** \`${LATEST}\`

## Next steps

1. Foreground agent runs \`harness-audit-wave\` on remaining unknown gates
2. \`harness-fix-wave\` for HIGH/CRITICAL findings
3. Re-run \`spine harness verify --run-qa\` when Postgres/Docker up
4. Full-mode dogfood: \`bash tools/spine-on-spine.sh\` (Hub required)

EOF

if [[ -f "${LATEST}" ]]; then
  cat >>"${REPORT}" <<EOF

## Verify report excerpt

\`\`\`
$(tail -40 "${LATEST}")
\`\`\`
EOF
fi

if [[ -n "${SMOKE_TAIL}" ]]; then
  cat >>"${REPORT}" <<EOF

## Smoke tail (last 20 lines)

\`\`\`
${SMOKE_TAIL}
\`\`\`
EOF
fi

echo "[dogfood] report → ${REPORT}"
bash "${HARNESS_TOOL_ROOT}/spine-harness" status --markdown --project "${REPO_ROOT}"
echo "[dogfood] done — loops running in background (spine harness stop to clean up)"

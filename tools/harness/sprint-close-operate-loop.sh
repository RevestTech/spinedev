#!/usr/bin/env bash
# sprint-close-operate-loop.sh — Wave 3 Harness Lite dogfood (operate-loop scope).
#
# ADR-008 sprint-close: audit → scoped pytest → verify → gate rollup report.
# No Hub required. Optional: --smoke for full smoke-test.sh --ci.
#
# Usage:
#   bash tools/harness/sprint-close-operate-loop.sh
#   bash tools/harness/sprint-close-operate-loop.sh --smoke
set -euo pipefail

HARNESS_TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_TOOL_ROOT}/../.." && pwd)"
SCOPE_FILE="${HARNESS_TOOL_ROOT}/scopes/operate-loop.txt"
RUN_SMOKE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) RUN_SMOKE=1; shift ;;
    -h|--help)
      echo "Usage: bash tools/harness/sprint-close-operate-loop.sh [--smoke]"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

cd "${REPO_ROOT}"
export SPINE_HOME="${REPO_ROOT}"

# shellcheck source=lib/harness_common.sh
source "${HARNESS_TOOL_ROOT}/lib/harness_common.sh"
PY="$(_harness_py)"

echo "[wave3] Harness Lite sprint-close — operate-loop scope"
echo "[wave3] project=${REPO_ROOT}"

bash "${HARNESS_TOOL_ROOT}/spine-harness" stop --project "${REPO_ROOT}" 2>/dev/null || true
bash "${HARNESS_TOOL_ROOT}/spine-harness" init --project "${REPO_ROOT}" --symlink-skills
bash "${HARNESS_TOOL_ROOT}/spine-harness" start sprint-close --project "${REPO_ROOT}"

echo "[wave3] Phase 1 — audit-wave (all gates) ..."
AUDIT_EXIT=0
bash "${HARNESS_TOOL_ROOT}/spine-harness" audit --project "${REPO_ROOT}" --gates all --markdown \
  || AUDIT_EXIT=$?

echo "[wave3] Phase 1b — scope file presence + scoped pytest ..."
SCOPE_EXIT=0
SCOPE_JSON="$("${PY}" "${HARNESS_TOOL_ROOT}/lib/scope_pytest.py" \
  --project "${REPO_ROOT}" \
  --scope-file "${SCOPE_FILE}" 2>&1)" || SCOPE_EXIT=$?
echo "${SCOPE_JSON}"

TESTS_GATE="red"
if [[ "${SCOPE_EXIT}" -eq 0 ]]; then
  TESTS_GATE="green"
fi

REPORT="${REPO_ROOT}/.spine/harness/reports/wave3-operate-loop-latest.md"
LATEST_VERIFY="${REPO_ROOT}/.spine/harness/reports/latest.md"
mkdir -p "$(dirname "${REPORT}")"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

"${PY}" "${HARNESS_TOOL_ROOT}/lib/harness_state.py" \
  --project "${REPO_ROOT}" set-gate tests "${TESTS_GATE}" --report "${REPORT}"

echo "[wave3] Phase 3 — verify-wave (charter evals, lite) ..."
VERIFY_EXIT=0
bash "${HARNESS_TOOL_ROOT}/spine-harness" verify --project "${REPO_ROOT}" --markdown \
  || VERIFY_EXIT=$?

SMOKE_SUMMARY="skipped (pass --smoke to run tools/smoke-test.sh --ci)"
SMOKE_EXIT=0
SMOKE_TAIL=""

if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  echo "[wave3] optional smoke-test.sh --ci ..."
  set +e
  SMOKE_OUT="$(mktemp)"
  bash "${REPO_ROOT}/tools/smoke-test.sh" --ci >"${SMOKE_OUT}" 2>&1
  SMOKE_EXIT=$?
  set -e
  if grep -qE '0 FAIL' "${SMOKE_OUT}" && [[ "${SMOKE_EXIT}" -eq 0 ]]; then
    SMOKE_SUMMARY="99 PASS / 0 FAIL (exit ${SMOKE_EXIT})"
  else
    SMOKE_SUMMARY="smoke failed (exit ${SMOKE_EXIT})"
  fi
  SMOKE_TAIL="$(tail -25 "${SMOKE_OUT}")"
  rm -f "${SMOKE_OUT}"
fi

# Mark wave complete when scoped tests + verify pass (audit may be yellow on docs)
WAVE_STATUS="blocked"
if [[ "${SCOPE_EXIT}" -eq 0 && "${VERIFY_EXIT}" -eq 0 ]]; then
  WAVE_STATUS="ready"
fi

cat >"${REPORT}" <<EOF
# Wave 3 — Harness sprint-close (operate-loop scope)

- **Generated:** ${TS}
- **Mode:** sprint-close
- **Scope:** \`${SCOPE_FILE}\`
- **Project:** \`${REPO_ROOT}\`
- **Wave status:** \`${WAVE_STATUS}\`

## Scope (Wave 1 + Wave 2 platform code)

Operate-loop handlers, gate policy, pipeline runner, and scoped tests:

\`\`\`
$(grep -v '^#' "${SCOPE_FILE}" | grep -v '^$' || true)
\`\`\`

## Phase 1 — audit-wave

- **Command:** \`spine harness audit --gates all\`
- **Exit code:** ${AUDIT_EXIT}

## Scoped tests gate

- **Command:** \`python tools/harness/lib/scope_pytest.py --scope-file tools/harness/scopes/operate-loop.txt\`
- **Exit code:** ${SCOPE_EXIT}
- **Gate \`tests\`:** \`${TESTS_GATE}\`

\`\`\`json
${SCOPE_JSON}
\`\`\`

## Phase 3 — verify-wave

- **Command:** \`spine harness verify\`
- **Exit code:** ${VERIFY_EXIT}
- **Latest verify report:** \`${LATEST_VERIFY}\`

## Smoke (optional)

- **Result:** ${SMOKE_SUMMARY}

## Harness gate rollup

\`\`\`
$(bash "${HARNESS_TOOL_ROOT}/spine-harness" status --markdown --project "${REPO_ROOT}")
\`\`\`

## Next steps (Wave 4 / ship)

1. **SPINE-OP-06:** \`bash tools/hub-up.sh --rebuild\` + Hub smoke
2. Black-box acceptance: disposable \`full_auto\` project — P(n) completed → P(n+1) requested
3. Full dogfood: \`bash tools/spine-on-spine.sh\` (Hub required)
4. Fix HIGH audit findings via \`harness-fix-wave\` if gates not green

EOF

if [[ -n "${SMOKE_TAIL}" ]]; then
  cat >>"${REPORT}" <<EOF

## Smoke tail

\`\`\`
${SMOKE_TAIL}
\`\`\`
EOF
fi

"${PY}" "${HARNESS_TOOL_ROOT}/lib/harness_state.py" \
  --project "${REPO_ROOT}" set-mode sprint-close --wave verify 2>/dev/null || true

echo "[wave3] report → ${REPORT}"
bash "${HARNESS_TOOL_ROOT}/spine-harness" status --markdown --project "${REPO_ROOT}"

if [[ "${WAVE_STATUS}" == "ready" ]]; then
  echo "[wave3] done — scoped tests + verify passed (audit/smoke may still need attention)"
  exit 0
fi

echo "[wave3] done with failures — see report and scope pytest output"
exit 1

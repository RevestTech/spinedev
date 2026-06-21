#!/usr/bin/env bash
# wave4-ship-gates.sh — Wave 4 G0/G4/G5 evidence rollup (operate-loop program).
#
# Collects automated evidence for ship gates. Human sign-off still required on
# todo/gates/G0-charter.md, G4-test-signoff.md, G5-release-ready.md.
#
# Usage:
#   bash tools/harness/wave4-ship-gates.sh
#   bash tools/harness/wave4-ship-gates.sh --smoke
#   bash tools/harness/wave4-ship-gates.sh --project-uuid '<uuid>'
set -euo pipefail

HARNESS_TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HARNESS_TOOL_ROOT}/../.." && pwd)"
EVIDENCE_DIR="${REPO_ROOT}/todo/gates/evidence"
RUN_SMOKE=0
PROJECT_UUID=""
HUB_URL="${HUB_URL:-http://localhost:8090}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) RUN_SMOKE=1; shift ;;
    --project-uuid) PROJECT_UUID="${2:-}"; shift 2 ;;
    --hub-url) HUB_URL="${2:-}"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: bash tools/harness/wave4-ship-gates.sh [options]

Options:
  --smoke                 Run tools/smoke-test.sh --ci (G4/G5 platform contract)
  --project-uuid UUID     G5 black-box operate acceptance (read-only Hub poll)
  --hub-url URL           Hub base URL (default: http://localhost:8090)
EOF
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

cd "${REPO_ROOT}"
export SPINE_HOME="${REPO_ROOT}"
mkdir -p "${EVIDENCE_DIR}"

# shellcheck source=lib/harness_common.sh
source "${HARNESS_TOOL_ROOT}/lib/harness_common.sh"
PY="$(_harness_py)"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DATE_STAMP="$(date -u +%Y-%m-%d)"
REPORT="${EVIDENCE_DIR}/wave4-operate-loop-${DATE_STAMP}.md"
LATEST="${EVIDENCE_DIR}/wave4-operate-loop-latest.md"

echo "[wave4] Ship gate evidence — operate-loop program"
echo "[wave4] report → ${REPORT}"

WAVE3_EXIT=0
echo "[wave4] G4 — Wave 3 sprint-close (scoped audit + pytest) ..."
set +e
bash "${HARNESS_TOOL_ROOT}/sprint-close-operate-loop.sh" ${RUN_SMOKE:+--smoke} >"${REPO_ROOT}/.spine/harness/reports/wave4-wave3-capture.log" 2>&1
WAVE3_EXIT=$?
set -e

SCOPE_EXIT=0
SCOPE_JSON="$("${PY}" "${HARNESS_TOOL_ROOT}/lib/scope_pytest.py" \
  --project "${REPO_ROOT}" \
  --scope-file "${HARNESS_TOOL_ROOT}/scopes/operate-loop.txt" 2>&1)" || SCOPE_EXIT=$?

SMOKE_EXIT=0
SMOKE_SUMMARY="skipped (pass --smoke)"
if [[ "${RUN_SMOKE}" -eq 1 ]]; then
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
else
  SMOKE_TAIL=""
fi

RECOVERY_SLA="skipped (no --project-uuid)"
BLACKBOX_EXIT=0
BLACKBOX_JSON=""
if [[ -n "${PROJECT_UUID}" ]]; then
  echo "[wave4] G5 — black-box operate acceptance ..."
  set +e
  BLACKBOX_JSON="$("${PY}" "${REPO_ROOT}/tools/acceptance/operate_blackbox.py" \
    --project-uuid "${PROJECT_UUID}" \
    --hub-url "${HUB_URL}" \
    --json 2>&1)" || BLACKBOX_EXIT=$?
  set -e
  RECOVERY_SLA="$(echo "${BLACKBOX_JSON}" | "${PY}" -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for c in d.get('checks', []):
        if c.get('name') == 'recovery_api':
            print(c.get('detail', 'n/a'))
            break
    else:
        print('recovery check missing')
except Exception as e:
    print(f'parse error: {e}')
" 2>/dev/null || echo "blackbox exit ${BLACKBOX_EXIT}")"
fi

G4_READY="no"
if [[ "${SCOPE_EXIT}" -eq 0 && "${WAVE3_EXIT}" -eq 0 ]]; then
  G4_READY="yes (scoped pytest + harness; human sign-off pending)"
fi
if [[ "${RUN_SMOKE}" -eq 1 && "${SMOKE_EXIT}" -ne 0 ]]; then
  G4_READY="no — smoke failed"
fi

G5_READY="no"
if [[ -n "${PROJECT_UUID}" && "${BLACKBOX_EXIT}" -eq 0 ]]; then
  G5_READY="yes (black-box pass; human sign-off pending)"
elif [[ -z "${PROJECT_UUID}" ]]; then
  G5_READY="pending — pass --project-uuid for black-box evidence"
fi

OVERALL="blocked"
if [[ "${G4_READY}" == yes* && "${G5_READY}" == yes* ]]; then
  OVERALL="ready_for_human_signoff"
elif [[ "${G4_READY}" == yes* ]]; then
  OVERALL="g4_ready_g5_pending"
fi

cat >"${REPORT}" <<EOF
# Wave 4 — Ship gate evidence (operate-loop)

- **Generated:** ${TS}
- **Program:** Waves 1–3 platform code + Harness Lite dogfood
- **Overall:** \`${OVERALL}\`

## G0 — Charter

- **Artifact:** [G0-charter.md](../G0-charter.md)
- **Status:** Evidence updated; **human Go required** (PO + Eng lead)
- **Scope in:** Autonomous operate loop (recovery, feature iteration, phase watcher)

## G4 — Test sign-off

- **Artifact:** [G4-test-signoff.md](../G4-test-signoff.md)
- **Ready:** ${G4_READY}

| Check | Command | Exit | Result |
|-------|---------|------|--------|
| Wave 3 sprint-close | \`bash tools/harness/sprint-close-operate-loop.sh\` | ${WAVE3_EXIT} | $([[ ${WAVE3_EXIT} -eq 0 ]] && echo Pass || echo Fail) |
| Scoped pytest | \`tools/harness/lib/scope_pytest.py\` | ${SCOPE_EXIT} | $([[ ${SCOPE_EXIT} -eq 0 ]] && echo Pass || echo Fail) |
| Smoke contract | \`bash tools/smoke-test.sh --ci\` | ${SMOKE_EXIT} | ${SMOKE_SUMMARY} |

### Scoped pytest JSON

\`\`\`json
${SCOPE_JSON}
\`\`\`

### Traceability

See [traceability-matrix.md](../../testing/traceability-matrix.md) — SPINE-OP-* rows.

## G5 — Release ready (operate slice)

- **Artifact:** [G5-release-ready.md](../G5-release-ready.md)
- **Ready:** ${G5_READY}
- **Black-box tool:** \`tools/acceptance/operate_blackbox.py\`
- **Project UUID:** ${PROJECT_UUID:-_(not run)_}
- **Hub URL:** ${HUB_URL}
- **Recovery SLA check:** ${RECOVERY_SLA}

### Black-box JSON

\`\`\`json
${BLACKBOX_JSON:-{}}
\`\`\`

## Human sign-off checklist

1. [ ] G0 — PO + Eng lead mark Go on [G0-charter.md](../G0-charter.md)
2. [ ] G4 — QA + Tech lead mark Go on [G4-test-signoff.md](../G4-test-signoff.md)
3. [ ] G5 — PO + Eng + Release mgr on [G5-release-ready.md](../G5-release-ready.md)
4. [ ] SPINE-OP-06 — \`bash tools/hub-up.sh --rebuild\` with smoke evidence

## Commands to reproduce

\`\`\`bash
bash tools/harness/wave4-ship-gates.sh --smoke
bash tools/harness/wave4-ship-gates.sh --smoke --project-uuid '<disposable-operate-uuid>'
\`\`\`

EOF

if [[ -n "${SMOKE_TAIL}" ]]; then
  cat >>"${REPORT}" <<EOF

## Smoke tail

\`\`\`
${SMOKE_TAIL}
\`\`\`
EOF
fi

cp -f "${REPORT}" "${LATEST}"
echo "[wave4] latest → ${LATEST}"

if [[ "${OVERALL}" == "ready_for_human_signoff" ]]; then
  echo "[wave4] automated gates passed — awaiting human sign-off on todo/gates/*.md"
  exit 0
fi

echo "[wave4] incomplete — see ${REPORT}"
exit 1

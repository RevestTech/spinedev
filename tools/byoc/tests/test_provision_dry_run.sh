#!/usr/bin/env bash
# tools/byoc/tests/test_provision_dry_run.sh — SPINE-016 BYOC dry-run smoke gate.
#
# Asserts tools/byoc/provision.sh --dry-run --non-interactive exits 0 for AWS
# and Railway without calling any cloud API (CI-safe, no credentials required).
#
# Usage:
#   bash tools/byoc/tests/test_provision_dry_run.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROVISION="${REPO_ROOT}/tools/byoc/provision.sh"

COMMON_ARGS=(
  --hub-version=1.0.0
  --bundle-id=00000000-0000-0000-0000-000000000001
  --admin-email=ci@spine.dev
  --non-interactive
  --dry-run
)

# Isolated lock dir so repeated runs do not collide with local state.
export SPINE_BYOC_STATE_DIR
SPINE_BYOC_STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/spine-byoc-test.XXXXXX")"
trap 'rm -rf "$SPINE_BYOC_STATE_DIR"' EXIT

run_dry_run() {
  local cloud="$1" account="$2"
  if ! bash "$PROVISION" --cloud="$cloud" --account="$account" "${COMMON_ARGS[@]}" >/dev/null 2>&1; then
    printf 'FAIL: %s dry-run exited non-zero\n' "$cloud" >&2
    bash "$PROVISION" --cloud="$cloud" --account="$account" "${COMMON_ARGS[@]}" >&2 || true
    return 1
  fi
  printf 'PASS: %s dry-run OK\n' "$cloud"
}

fail=0
run_dry_run aws ci-smoke || fail=1
run_dry_run railway ci-smoke || fail=1

exit "$fail"

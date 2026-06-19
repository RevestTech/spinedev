#!/usr/bin/env bash
# tools/docker-build-smoke.sh — static gate for multi-arch Docker publish CI.
#
# Validates .github/workflows/docker-build.yml contains the SPINE-017 contract:
#   - Docker Buildx setup
#   - platforms: linux/amd64,linux/arm64 (hub + vault + keycloak matrix)
#   - cosign install + sign steps
#
# No docker build — grep-only so it runs in every smoke/bootstrap pass.
#
# Usage:
#   bash tools/docker-build-smoke.sh [--quiet]
#
# Exit codes:
#   0  all required patterns present
#   1  workflow missing or contract violated
#   64 unknown flag

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/docker-build.yml"

QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet|-q) QUIET=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      printf 'unknown flag: %s\n' "$arg" >&2
      exit 64
      ;;
  esac
done

log() {
  [[ $QUIET -eq 1 ]] || printf '[docker-build-smoke] %s\n' "$*" >&2
}

fail() {
  log "FAIL: $*"
  exit 1
}

pass() {
  log "PASS: $*"
}

require_grep() {
  local label="$1" pattern="$2" file="$3"
  if grep -qE "$pattern" "$file"; then
    pass "$label"
  else
    fail "$label — pattern not found: $pattern"
  fi
}

[[ -f "$WORKFLOW" ]] || fail "missing $WORKFLOW"

require_grep "workflow defines docker-build job" '^name: docker-build' "$WORKFLOW"
require_grep "buildx setup action" 'docker/setup-buildx-action' "$WORKFLOW"
require_grep "build-push via buildx" 'docker/build-push-action' "$WORKFLOW"
require_grep "multi-arch platforms amd64+arm64" 'platforms: linux/amd64,linux/arm64' "$WORKFLOW"
require_grep "hub image in build matrix" 'image: hub' "$WORKFLOW"
require_grep "cosign installer" 'cosign-installer' "$WORKFLOW"
require_grep "cosign sign step" 'cosign sign' "$WORKFLOW"
require_grep "SLSA provenance attestation" 'attest-build-provenance' "$WORKFLOW"

log "docker-build.yml multi-arch + cosign contract OK"
exit 0

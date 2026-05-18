#!/usr/bin/env bash
# Spine Hub SPA — OpenAPI → TypeScript codegen (V3 Wave 3 part 2, Squad SPA3).
#
# Replaces hand-maintained shared/ui/spa/src/lib/api/types.ts with a
# generated mirror of the FastAPI OpenAPI document. Two source modes:
#
#   1. LIVE (developer laptop): a running Hub on :8090 (or override via
#      SPINE_OPENAPI_URL=http://host:port) is hit at /api/v2/spec and the
#      response is fed straight to openapi-typescript.
#
#   2. SNAPSHOT (CI / prod): if SPINE_OPENAPI_SNAPSHOT is set (or the live
#      URL is not reachable), we feed the committed snapshot at
#      shared/ui/spa/scripts/openapi-sample.json. Production builds MUST
#      use this mode — they never reach out to a live Hub during build.
#
# Output: shared/ui/spa/src/lib/api/types.generated.ts
# Public surface: shared/ui/spa/src/lib/api/types.ts re-exports everything
# from types.generated.ts so panel imports never change.
#
# Usage:
#   bash shared/ui/spa/scripts/codegen-types.sh                # live (8090)
#   SPINE_OPENAPI_URL=http://localhost:8088 bash ...           # custom port
#   SPINE_OPENAPI_SNAPSHOT=1 bash ...                          # force snapshot
#
# Requires `npx` to resolve openapi-typescript from devDependencies. Hub
# Docker build runs `npm ci` first so the binary is on PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPA_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_FILE="${SPA_ROOT}/src/lib/api/types.generated.ts"
SNAPSHOT_FILE="${SCRIPT_DIR}/openapi-sample.json"

# Dev URL is :8090 — the Hub container's external port per
# shared/api/app.py mounts (matches the smoke-test harness).
DEV_URL="${SPINE_OPENAPI_URL:-http://localhost:8090/api/v2/spec}"

source_describe=""
if [[ "${SPINE_OPENAPI_SNAPSHOT:-}" == "1" ]]; then
  source_describe="snapshot (${SNAPSHOT_FILE})"
  input="${SNAPSHOT_FILE}"
else
  # Probe the live URL with a short timeout; fall back to snapshot if down.
  if command -v curl >/dev/null 2>&1 && \
     curl -fsS --max-time 2 "${DEV_URL}" >/dev/null 2>&1; then
    source_describe="live (${DEV_URL})"
    input="${DEV_URL}"
  else
    source_describe="snapshot fallback (${SNAPSHOT_FILE})"
    input="${SNAPSHOT_FILE}"
  fi
fi

echo "[codegen-types] source: ${source_describe}" >&2
echo "[codegen-types] output: ${OUT_FILE}" >&2

# openapi-typescript v7+ supports both URL and file inputs; emit ESM.
npx --no-install openapi-typescript "${input}" -o "${OUT_FILE}"

echo "[codegen-types] done." >&2

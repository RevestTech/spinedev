#!/usr/bin/env bash
# Spine v3 — Hub container healthcheck
#
# Referenced by hub/Dockerfile HEALTHCHECK. Designed to be:
#   - dependency-free   (curl only; image already includes curl)
#   - fast              (single-shot, 3s connect timeout)
#   - explicit          (exit codes documented for kubectl/docker debugging)
#
# Exit codes:
#   0  healthy             — /healthz returned 200 AND body.ok=true
#   1  curl/connect failed — Hub process is not accepting connections
#   2  non-200 response    — Hub up but degraded (DB or MCP failed)
#   3  unhealthy body      — 200 OK but body.ok=false (transient deps down)
#
# Per shared/api/app.py contract:
#   GET /healthz → 200 {"ok": <bool>, "db": <bool>, "mcp": <bool>}
#                  503 if either dependency missing

set -u  # no -e: we want to inspect exit codes ourselves

PORT="${SPINE_HUB_PORT:-8080}"
HOST="${SPINE_HUB_HOST_HEALTH:-127.0.0.1}"
URL="http://${HOST}:${PORT}/healthz"

# -sS:  silent but show errors; -m 3: max 3s; -w '%{http_code}': append code.
RESP="$(curl -sS -m 3 -w '\n%{http_code}' "$URL" 2>/dev/null)"
CURL_RC=$?
if [[ $CURL_RC -ne 0 ]]; then
  printf '[hub-healthcheck] connect FAILED to %s (curl rc=%d)\n' "$URL" "$CURL_RC" >&2
  exit 1
fi

HTTP_CODE="$(printf '%s' "$RESP" | tail -n1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"

if [[ "$HTTP_CODE" != "200" ]]; then
  printf '[hub-healthcheck] non-200 status=%s body=%s\n' "$HTTP_CODE" "$BODY" >&2
  exit 2
fi

# Parse body.ok; jq if present (faster), python3 fallback.
OK=""
if command -v jq >/dev/null 2>&1; then
  OK="$(printf '%s' "$BODY" | jq -r '.ok // empty' 2>/dev/null || true)"
else
  OK="$(printf '%s' "$BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("ok",""))' 2>/dev/null || true)"
fi

if [[ "$OK" != "True" && "$OK" != "true" ]]; then
  printf '[hub-healthcheck] body.ok=%s body=%s\n' "$OK" "$BODY" >&2
  exit 3
fi

exit 0

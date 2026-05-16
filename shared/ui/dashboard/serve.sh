#!/usr/bin/env bash
# serve.sh - Spine Dashboard dev launcher.
# Serves the dashboard static files at :8080 and reuses the approvals proxy.py
# at :8081 for REST. If proxy.py is already listening we don't double-spawn.
# DEV ONLY. Production goes through the FastAPI surface from STORY-9.9.2.
#
# Usage: ./serve.sh [--port 8080] [--api-port 8081] [--open TAB] [--no-open]
#   TAB in {projects,cost,activity,knowledge}

set -euo pipefail

PORT=8080
API_PORT=8081
OPEN=1
OPEN_TAB=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)     PORT="$2"; shift 2 ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --open)     OPEN_TAB="$2"; shift 2 ;;
    --no-open)  OPEN=0; shift ;;
    -h|--help)  sed -n '2,11p' "$0" >&2; exit 0 ;;
    *) printf 'unknown arg: %s\n' "$1" >&2; exit 2 ;;
  esac
done

UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPINE_ROOT="$(cd "$UI_DIR/../../.." && pwd)"
APPROVALS_DIR="$SPINE_ROOT/shared/ui/approvals"
PROXY_PY="$APPROVALS_DIR/proxy.py"
GATE_SH="${SPINE_GATE_SH:-$SPINE_ROOT/orchestrator/lib/gate.sh}"

command -v python3 >/dev/null || { echo "python3 required" >&2; exit 2; }

# Detect if the proxy is already listening on the API port.
PROXY_RUNNING=0
if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.3);
sys.exit(0 if s.connect_ex(('127.0.0.1', $API_PORT)) == 0 else 1)" 2>/dev/null; then
  PROXY_RUNNING=1
  printf '[serve.sh] reusing existing proxy on :%s\n' "$API_PORT"
fi

STATIC_PID=""
PROXY_PID=""
cleanup() {
  [[ -n "$STATIC_PID" ]] && kill "$STATIC_PID" 2>/dev/null || true
  [[ -n "$PROXY_PID"  ]] && kill "$PROXY_PID"  2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf '[serve.sh] UI dir       : %s\n' "$UI_DIR"
printf '[serve.sh] gate.sh      : %s\n' "$GATE_SH"
printf '[serve.sh] static  port : %s\n' "$PORT"
printf '[serve.sh] proxy   port : %s\n' "$API_PORT"

# Static file server (bind localhost only - dev only, no auth).
( cd "$UI_DIR" && python3 -m http.server "$PORT" --bind 127.0.0.1 ) &
STATIC_PID=$!

if [[ "$PROXY_RUNNING" -eq 0 ]]; then
  if [[ ! -f "$PROXY_PY" ]]; then
    printf '[serve.sh] proxy.py not found at %s; dashboard will run UI-only\n' "$PROXY_PY" >&2
  else
    SPINE_GATE_SH="$GATE_SH" SPINE_ROOT="$SPINE_ROOT" \
      python3 "$PROXY_PY" --port "$API_PORT" &
    PROXY_PID=$!
  fi
fi

URL="http://localhost:${PORT}/index.html"
[[ -n "$OPEN_TAB" ]] && URL="${URL}#tab=${OPEN_TAB}"
printf '[serve.sh] open          : %s\n' "$URL"

if [[ "$OPEN" -eq 1 ]]; then
  if   command -v open >/dev/null;     then open "$URL" || true
  elif command -v xdg-open >/dev/null; then xdg-open "$URL" || true
  fi
fi

printf '[serve.sh] Ctrl-C to stop.\n'
wait

#!/usr/bin/env bash
# serve.sh — Spine Approval Queue dev launcher.
# Boots a static file server + a tiny REST proxy that wraps gate.sh.
# DEV ONLY. Production goes through the FastAPI surface from STORY-9.9.2.
#
# Usage: ./serve.sh [--port 8080] [--api-port 8081] [--no-open]

set -euo pipefail

PORT=8080
API_PORT=8081
OPEN=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)     PORT="$2"; shift 2 ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --no-open)  OPEN=0; shift ;;
    -h|--help)
      sed -n '2,8p' "$0" >&2; exit 0 ;;
    *) printf 'unknown arg: %s\n' "$1" >&2; exit 2 ;;
  esac
done

UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_PY="$UI_DIR/proxy.py"
SPINE_ROOT="$(cd "$UI_DIR/../../.." && pwd)"
GATE_SH="${SPINE_GATE_SH:-$SPINE_ROOT/orchestrator/lib/gate.sh}"

if [[ ! -x "$GATE_SH" && ! -f "$GATE_SH" ]]; then
  printf 'gate.sh not found at %s — set SPINE_GATE_SH to override\n' "$GATE_SH" >&2
  exit 2
fi
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 2; }

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

# Static file server (bind localhost only — dev only, no auth)
( cd "$UI_DIR" && python3 -m http.server "$PORT" --bind 127.0.0.1 ) &
STATIC_PID=$!

# REST proxy → gate.sh
SPINE_GATE_SH="$GATE_SH" SPINE_ROOT="$SPINE_ROOT" \
  python3 "$PROXY_PY" --port "$API_PORT" &
PROXY_PID=$!

URL="http://localhost:${PORT}/index.html"
printf '[serve.sh] open          : %s\n' "$URL"

if [[ "$OPEN" -eq 1 ]]; then
  if   command -v open >/dev/null;     then open "$URL" || true
  elif command -v xdg-open >/dev/null; then xdg-open "$URL" || true
  fi
fi

printf '[serve.sh] Ctrl-C to stop.\n'
wait

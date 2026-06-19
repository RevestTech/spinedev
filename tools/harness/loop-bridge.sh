#!/usr/bin/env bash
# loop-bridge.sh — Cursor /loop AGENT_LOOP_WAKE sentinels for Harness Lite.
# Emits unique sentinels; tracks PIDs under .spine/harness/loops/.
set -euo pipefail

HARNESS_TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/harness_common.sh
source "${HARNESS_TOOL_ROOT}/lib/harness_common.sh"

HARNESS_PROJECT_ROOT="."
LB_MODE=""
LB_INTERVAL=""
LB_DYNAMIC=0
LB_EVENT=""

_skill_prompt_for_mode() {
  case "$1" in
    audit|sprint-close) echo "Run harness-audit-wave skill (ADR-008 Phase 1)" ;;
    fix)                  echo "Run harness-fix-wave skill (ADR-008 Phase 2)" ;;
    verify|release-gate)  echo "Run harness-verify-wave skill (ADR-008 Phase 3)" ;;
    feature)              echo "Run harness-orchestrator skill — feature mode tick" ;;
    watch)                echo "Run harness-orchestrator skill — watch heartbeat" ;;
    bootstrap)            echo "Run harness-orchestrator skill — bootstrap" ;;
    *)                    echo "Run harness-orchestrator skill" ;;
  esac
}

_lb_usage() {
  cat <<'EOF'
loop-bridge.sh — Harness Lite background loop bridge

Usage:
  loop-bridge.sh start --project PATH --mode MODE [--interval 5m] [--dynamic] [--event git]
  loop-bridge.sh stop  --project PATH

Sentinel format (Cursor /loop integration):
  AGENT_LOOP_WAKE_<purpose> {"prompt":"<skill playbook>"}
EOF
}

_lb_pid_file() {
  printf '%s/%s.pid\n' "$(_harness_loops_dir)" "$1"
}

_lb_register() {
  local pid="$1" purpose="$2" sentinel="$3" interval="${4:-}"
  local py
  py="$(_harness_py)"
  "$py" "${HARNESS_TOOL_ROOT}/lib/harness_state.py" \
    --project "${HARNESS_PROJECT_ROOT}" register-loop \
    --pid "${pid}" \
    --purpose "${purpose}" \
    --sentinel "${sentinel}" \
    ${interval:+--interval "${interval}"} \
    --mode "${LB_MODE}"
  printf '%s\n' "${pid}" > "$(_lb_pid_file "${purpose}")"
}

_lb_start_fixed_loop() {
  local purpose="$1" seconds="$2"
  local sentinel="AGENT_LOOP_WAKE_harness_${purpose}"
  local prompt
  prompt="$(_skill_prompt_for_mode "${LB_MODE}")"
  (
    while true; do
      sleep "${seconds}"
      printf '%s {"prompt":"%s"}\n' "${sentinel}" "${prompt}"
    done
  ) &
  local pid=$!
  _lb_register "${pid}" "${purpose}" "${sentinel}" "${seconds}"
  echo "loop-bridge: fixed loop pid=${pid} interval=${seconds}s sentinel=${sentinel}"
  printf '%s {"prompt":"%s"}\n' "${sentinel}" "${prompt}"
}

_lb_start_event_watcher() {
  local purpose="git"
  local sentinel="AGENT_LOOP_WAKE_harness_git"
  local prompt
  prompt="$(_skill_prompt_for_mode "${LB_MODE}")"
  (
    local last=""
    while true; do
      sleep 15
      if [[ -d "${HARNESS_PROJECT_ROOT}/.git" ]]; then
        local head
        head="$(git -C "${HARNESS_PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || true)"
        if [[ -n "${head}" && "${head}" != "${last}" && -n "${last}" ]]; then
          printf '%s {"prompt":"%s"}\n' "${sentinel}" "${prompt}"
        fi
        last="${head}"
      fi
    done
  ) &
  local pid=$!
  _lb_register "${pid}" "${purpose}" "${sentinel}"
  echo "loop-bridge: git watcher pid=${pid} sentinel=${sentinel}"
}

_lb_start_dynamic_heartbeat() {
  local purpose="heartbeat"
  local seconds="${1:-1800}"
  local sentinel="AGENT_LOOP_WAKE_harness_heartbeat"
  local prompt
  prompt="$(_skill_prompt_for_mode "${LB_MODE}")"
  (
    while true; do
      sleep "${seconds}"
      printf '%s {"prompt":"%s"}\n' "${sentinel}" "${prompt}"
    done
  ) &
  local pid=$!
  _lb_register "${pid}" "${purpose}" "${sentinel}" "${seconds}"
  echo "loop-bridge: heartbeat pid=${pid} interval=${seconds}s sentinel=${sentinel}"
}

cmd_start() {
  [[ -z "${LB_MODE}" ]] && _harness_die "start requires --mode"
  mkdir -p "$(_harness_loops_dir)"
  local prompt
  prompt="$(_skill_prompt_for_mode "${LB_MODE}")"
  echo "loop-bridge: immediate tick — ${prompt}"
  if [[ -n "${LB_INTERVAL}" ]]; then
    local seconds
    seconds="$(_harness_parse_interval "${LB_INTERVAL}")"
    _lb_start_fixed_loop "${LB_MODE}" "${seconds}"
  fi
  if [[ "${LB_EVENT}" == "git" ]]; then
    _lb_start_event_watcher
  fi
  if [[ "${LB_DYNAMIC}" -eq 1 && -z "${LB_INTERVAL}" ]]; then
    _lb_start_dynamic_heartbeat 1800
  elif [[ "${LB_DYNAMIC}" -eq 1 ]]; then
    _lb_start_dynamic_heartbeat 3600
  fi
}

cmd_stop() {
  local loops_dir pid_file pid
  loops_dir="$(_harness_loops_dir)"
  if [[ ! -d "${loops_dir}" ]]; then
    echo "loop-bridge: no loops directory"
    return 0
  fi
  shopt -s nullglob
  for pid_file in "${loops_dir}"/*.pid; do
    pid="$(cat "${pid_file}")"
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      echo "loop-bridge: stopped pid=${pid}"
    fi
    rm -f "${pid_file}"
  done
  shopt -u nullglob
}

main() {
  local cmd="${1:-help}"
  shift || true
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) HARNESS_PROJECT_ROOT="$(cd "${2:?}" && pwd)"; shift 2 ;;
      --mode) LB_MODE="$2"; shift 2 ;;
      --interval) LB_INTERVAL="$2"; shift 2 ;;
      --dynamic) LB_DYNAMIC=1; shift ;;
      --event) LB_EVENT="$2"; shift 2 ;;
      -h|--help) _lb_usage; exit 0 ;;
      *) _harness_die "unknown arg: $1" ;;
    esac
  done
  HARNESS_PROJECT_ROOT="$(_harness_repo_root "${HARNESS_PROJECT_ROOT}")"
  case "${cmd}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    *) _lb_usage; exit 64 ;;
  esac
}

main "$@"

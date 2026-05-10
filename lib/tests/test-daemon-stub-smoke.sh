#!/usr/bin/env bash
# End-to-end daemon smoke: synthetic sandbox tree (no install.sh preflight),
# EXECUTOR_KIND=generic + stub writes # Report → costs.csv outcome + agent.log lines.
#
# Works from SpineDevelopment checkout (PROTOCOL.md + lib/*.sh) or an installed tree
# (scripts/*.sh + AGENT_TEAM_PROTOCOL.md + seeded role prompts).
#
# Env:
#   SKIP_DAEMON_STUB_SMOKE=1 — skip entirely
# Negative assertions under set — use explicit `if`; see sibling test headers.
set -euo pipefail

if [[ "${SKIP_DAEMON_STUB_SMOKE:-}" == 1 ]]; then
  echo "SKIP_DAEMON_STUB_SMOKE=1 — skipping daemon stub smoke"
  exit 0
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# costs.csv: column 5 = phase, column 9 = outcome (header row excluded).
costs_row_pickup_outcome() {
  local csv="$1" want_outcome="$2"
  [[ -f "$csv" ]] || return 1
  awk -F, -v want="$want_outcome" '
    NR > 1 && NF >= 9 && $5 == "pickup" && $9 == want { found = 1 }
    END { exit found ? 0 : 1 }
  ' "$csv"
}

write_stub_executor() {
  local dest="$1"
  cat > "$dest" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
sleep "${STUB_SLEEP:-2}"
: "${DIRECTIVE_FILE:?stub requires exported DIRECTIVE_FILE}"
cat > "$DIRECTIVE_FILE" <<'RPT'
# Report — stub
## TL;DR
stub completed
## Files touched
- none
RPT
EOF
  chmod +x "$dest"
}

protocol_src=""
for cand in "$REPO/PROTOCOL.md" "$REPO/.planning/orchestration/AGENT_TEAM_PROTOCOL.md"; do
  [[ -f "$cand" ]] && { protocol_src="$cand"; break; }
done
[[ -n "$protocol_src" ]] || {
  printf '%s\n' "MISSING PROTOCOL.md or AGENT_TEAM_PROTOCOL.md — run from SpineDevelopment checkout or installed project root" >&2
  exit 1
}

role_prompt_src=""
for cand in "$REPO/lib/role-prompts/datawright.md" \
           "$REPO/.planning/orchestration/agent-handoff/teams/datawright/role-prompt.md"; do
  [[ -f "$cand" ]] && { role_prompt_src="$cand"; break; }
done
[[ -n "$role_prompt_src" ]] || {
  printf '%s\n' "MISSING datawright role prompt template or seeded role-prompt.md" >&2
  exit 1
}

copy_daemon_scripts() {
  local dest_scripts="$1"
  mkdir -p "$dest_scripts"
  local f cand found
  for f in roles.sh team-agent-daemon.sh executor.sh costs-csv.sh; do
    found=
    for cand in "$REPO/lib/$f" "$REPO/scripts/$f"; do
      [[ -f "$cand" ]] && { cp "$cand" "$dest_scripts/$f"; found=1; break; }
    done
    [[ -n "$found" ]] || {
      printf '%s\n' "MISSING $f under scripts/ or lib/" >&2
      exit 1
    }
  done
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/spine-daemon-smoke.XXXXXX")"
ROOT2=""
cleanup() { rm -rf "$ROOT" "${ROOT2:-}"; }
trap cleanup EXIT

STUB1="$ROOT/stub-executor.sh"
write_stub_executor "$STUB1"

ORB="$ROOT/.planning/orchestration"
TEAM="$ORB/agent-handoff/teams/datawright"
mkdir -p "$TEAM/state" "$TEAM/log" "$TEAM/workers" "$TEAM/scratch/manager"
cp "$protocol_src" "$ORB/AGENT_TEAM_PROTOCOL.md"
cp "$role_prompt_src" "$TEAM/role-prompt.md"

copy_daemon_scripts "$ROOT/scripts"
chmod +x "$ROOT/scripts/team-agent-daemon.sh" "$ROOT/scripts/executor.sh"

cat > "$TEAM/directive.md" <<'EOF'
# Directive — stub smoke

## Long job: 90

EOF

cd "$ROOT" || exit 1
export EXECUTOR_KIND=generic
export EXECUTOR_CMD="bash $STUB1"
unset STUB_SLEEP

bash "$ROOT/scripts/team-agent-daemon.sh" datawright manager &
dpid=$!

# Stub writes # Report in ~2s; stall watcher then sleeps up to ~30s before it notices the
# child exited — wait for costs.csv before killing the daemon (otherwise log_cost never runs).
deadline=$((SECONDS + 120))
hdr=""
while (( SECONDS < deadline )); do
  hdr="$(head -1 "$TEAM/directive.md" 2>/dev/null || true)"
  [[ "$hdr" == "# Report"* ]] && break
  sleep 2
done

[[ "$hdr" == "# Report"* ]] || {
  printf '%s\n' "expected directive to become # Report — got: ${hdr:-empty}" >&2
  kill "$dpid" 2>/dev/null || true
  wait "$dpid" 2>/dev/null || true
  exit 1
}

deadline2=$((SECONDS + 120))
until costs_row_pickup_outcome "$TEAM/state/costs.csv" completed || (( SECONDS >= deadline2 )); do
  sleep 2
done

kill "$dpid" 2>/dev/null || true
wait "$dpid" 2>/dev/null || true

if ! costs_row_pickup_outcome "$TEAM/state/costs.csv" completed; then
  printf '%s\n' "expected pickup row with outcome column (field 9) exactly completed (see PROTOCOL §13 stall tick)" >&2
  tail -20 "$TEAM/log/agent.log" >&2 || true
  [[ -f "$TEAM/state/costs.csv" ]] && tail -5 "$TEAM/state/costs.csv" >&2 || true
  exit 1
fi

if ! grep -q 'long_job_extended' "$TEAM/log/agent.log" 2>/dev/null; then
  printf '%s\n' "missing long_job_extended in agent.log" >&2
  exit 1
fi

gnu_timeout_bin=
if command -v gtimeout >/dev/null 2>&1; then
  gnu_timeout_bin=gtimeout
elif command -v timeout >/dev/null 2>&1 && timeout --version 2>/dev/null | grep -q GNU; then
  gnu_timeout_bin=timeout
fi

if [[ -n "$gnu_timeout_bin" ]]; then
  ROOT2="$(mktemp -d "${TMPDIR:-/tmp}/spine-daemon-smoke-to.XXXXXX")"
  STUB2="$ROOT2/stub-executor.sh"
  write_stub_executor "$STUB2"
  ORB2="$ROOT2/.planning/orchestration"
  TEAM2="$ORB2/agent-handoff/teams/datawright"
  mkdir -p "$TEAM2/state" "$TEAM2/log" "$TEAM2/workers" "$TEAM2/scratch/manager"
  cp "$protocol_src" "$ORB2/AGENT_TEAM_PROTOCOL.md"
  cp "$role_prompt_src" "$TEAM2/role-prompt.md"
  copy_daemon_scripts "$ROOT2/scripts"
  chmod +x "$ROOT2/scripts/team-agent-daemon.sh" "$ROOT2/scripts/executor.sh"

  cat > "$TEAM2/directive.md" <<'EOF'
# Directive — timeout smoke

## Tier hint: low

EOF

  cd "$ROOT2" || exit 1
  export EXECUTOR_KIND=generic
  export EXECUTOR_CMD="bash $STUB2"
  export STUB_SLEEP=999
  export INVOCATION_TIMEOUT_S=5
  export STALL_THRESHOLD_S=60

  bash "$ROOT2/scripts/team-agent-daemon.sh" datawright manager &
  dpid2=$!

  deadline3=$((SECONDS + 90))
  saw_timeout=0
  while (( SECONDS < deadline3 )); do
    if costs_row_pickup_outcome "$TEAM2/state/costs.csv" timeout; then
      saw_timeout=1
      break
    fi
    sleep 1
  done

  kill "$dpid2" 2>/dev/null || true
  wait "$dpid2" 2>/dev/null || true

  if [[ "$saw_timeout" -ne 1 ]]; then
    printf '%s\n' "expected pickup row with outcome (field 9) exactly timeout (GNU $gnu_timeout_bin + INVOCATION_TIMEOUT_S=5)" >&2
    tail -5 "$TEAM2/state/costs.csv" >&2 || true
    exit 1
  fi
else
  echo "(skip) no GNU timeout/gtimeout on PATH — timeout outcome branch not exercised"
fi

printf '%s\n' "daemon stub smoke OK"

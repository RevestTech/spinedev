#!/usr/bin/env bash
# team-agent-daemon.sh — parameterized daemon for the agent team (package history: SpineDevelopment CHANGELOG.md).
#
# Usage:
#   bash scripts/team-agent-daemon.sh <role> manager
#   bash scripts/team-agent-daemon.sh <role> worker <slot-NN>
#
# Valid roles listed in scripts/roles.sh (`SPINE_TEAM_ROLES`).
#
ROLE="${1:?role required}"
MODE="${2:?mode required (manager|worker)}"
SLOT="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLES_SH="$SCRIPT_DIR/roles.sh"
if [[ ! -f "$ROLES_SH" ]]; then
  echo "FATAL: missing $ROLES_SH — reinstall SpineDevelopment bundle" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ROLES_SH"

if ! spine_role_valid "$ROLE"; then
  echo "FATAL: unknown role '$ROLE'. Expected one of: $(spine_roles_csv)" >&2
  exit 1
fi

if [[ -f "$SCRIPT_DIR/costs-csv.sh" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/costs-csv.sh"
else
  spine_migrate_costs_csv_if_needed() { return 0; }
fi

case "$MODE" in
  manager) ;;
  worker)
    if [[ -z "$SLOT" || ! "$SLOT" =~ ^[0-9]{2}$ ]]; then
      echo "FATAL: worker mode requires 2-digit slot arg (01..10)" >&2
      exit 1
    fi
    ;;
  *) echo "FATAL: unknown mode '$MODE'" >&2; exit 1 ;;
esac

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

TEAM_DIR=".planning/orchestration/agent-handoff/teams/$ROLE"
ROLE_PROMPT_FILE="$TEAM_DIR/role-prompt.md"
MEMORY_FILE="$TEAM_DIR/memory.md"
PROTOCOL_FILE=".planning/orchestration/AGENT_TEAM_PROTOCOL.md"
COSTS_FILE="$TEAM_DIR/state/costs.csv"

if [[ "$MODE" == "manager" ]]; then
  DIRECTIVE_FILE="$TEAM_DIR/directive.md"
  HASH_FILE="$TEAM_DIR/state/manager-LAST_HASH"
  DAEMON_LOG="$TEAM_DIR/log/daemon.log"
  AGENT_LOG="$TEAM_DIR/log/agent.log"
  WORKERS_DIR="$TEAM_DIR/workers"
  IDENTITY="$ROLE/manager"
  SCRATCH_DIR="$TEAM_DIR/scratch/manager"
  OS_TEMP_DIR="/tmp/spine-${ROLE}-mgr"
  HEARTBEAT_FILE="$TEAM_DIR/state/heartbeat"
else
  DIRECTIVE_FILE="$TEAM_DIR/workers/${SLOT}-directive.md"
  HASH_FILE="$TEAM_DIR/state/${SLOT}-LAST_HASH"
  DAEMON_LOG="$TEAM_DIR/log/${SLOT}-daemon.log"
  AGENT_LOG="$TEAM_DIR/log/${SLOT}-agent.log"
  WORKERS_DIR=""
  IDENTITY="$ROLE/worker-$SLOT"
  SCRATCH_DIR="$TEAM_DIR/scratch/${SLOT}"
  OS_TEMP_DIR="/tmp/spine-${ROLE}-${SLOT}"
  HEARTBEAT_FILE="$TEAM_DIR/state/heartbeat-${SLOT}"
fi
ROLLBACK_STACK="$TEAM_DIR/state/rollback-stack.csv"

mkdir -p "$(dirname "$DAEMON_LOG")" "$(dirname "$HASH_FILE")" "$SCRATCH_DIR" "$OS_TEMP_DIR"
touch "$AGENT_LOG" "$DAEMON_LOG" 2>/dev/null || true
LOG_MAX_BYTES="${LOG_MAX_BYTES:-5242880}"   # 5 MB
rotate_log_if_huge() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  local sz
  sz=$(wc -c < "$f" 2>/dev/null || echo 0)
  if (( sz > LOG_MAX_BYTES )); then
    tail -c "$LOG_MAX_BYTES" "$f" > "$f.rotated" 2>/dev/null && mv "$f.rotated" "$f" 2>/dev/null
  fi
}

# Wipe scratch + os-temp dirs. Called when a NEW directive arrives so each
# directive starts with a clean slate.
reset_scratch() {
  rm -rf "$SCRATCH_DIR" "$OS_TEMP_DIR" 2>/dev/null
  mkdir -p "$SCRATCH_DIR" "$OS_TEMP_DIR" 2>/dev/null
  touch "$SCRATCH_DIR/.gitkeep"
}

POLL_INTERVAL="${POLL_INTERVAL:-8}"
HEARTBEAT_EVERY="${HEARTBEAT_EVERY:-60}"
INVOCATION_TIMEOUT_S="${INVOCATION_TIMEOUT_S:-1500}"   # 25 min default
STALL_THRESHOLD_S="${STALL_THRESHOLD_S:-480}"          # 8 min no stdout = stalled

log() {
  local line
  line="$(date -u +%FT%TZ) [$IDENTITY] $*"
  printf '%s\n' "$line" >> "$DAEMON_LOG" 2>/dev/null
  printf '%s\n' "$line" >&2
}

current_hash() {
  if [[ -f "$DIRECTIVE_FILE" ]]; then
    shasum -a 256 "$DIRECTIVE_FILE" 2>/dev/null | awk '{print $1}'
  fi
}

last_hash() { cat "$HASH_FILE" 2>/dev/null; }

classify_file() {
  [[ -f "$DIRECTIVE_FILE" ]] || { echo "missing"; return; }
  local hdr
  hdr="$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)"
  case "$hdr" in
    "# Directive"*)            echo "directive" ;;
    "# Worker Directive"*)     echo "worker-directive" ;;
    "# Plan"*)                 echo "plan" ;;
    "# Awaiting approval"*)
      # If the file now contains "## Approved by:", it's been signed off
      if grep -qE '^## *Approved by *: *' "$DIRECTIVE_FILE" 2>/dev/null; then
        echo "approved"
      else
        echo "awaiting-approval"
      fi
      ;;
    "# Report"*)               echo "report" ;;
    "# Worker Report"*)        echo "worker-report" ;;
    *)                         echo "other" ;;
  esac
}

# True if the directive file declares `## Requires approval: yes`
requires_approval() {
  [[ -f "$DIRECTIVE_FILE" ]] || return 1
  grep -qiE '^## *Requires approval *: *(yes|true)' "$DIRECTIVE_FILE" 2>/dev/null
}

# Parse `## Tier hint` line. Returns: low|medium|high (default: medium).
parse_tier_hint() {
  [[ -f "$DIRECTIVE_FILE" ]] || { echo "medium"; return; }
  local hint
  hint=$(grep -iE '^## *Tier hint' "$DIRECTIVE_FILE" 2>/dev/null \
    | head -1 \
    | sed -E 's/^## *Tier hint[[:space:]]*:?[[:space:]]*//I' \
    | tr '[:upper:]' '[:lower:]' \
    | awk '{print $1}')
  case "$hint" in
    low|cheap|small)    echo "low" ;;
    medium|mid|default) echo "medium" ;;
    high|expensive|big) echo "high" ;;
    *)                  echo "medium" ;;
  esac
}

# Parse `## Long job:` — optional *extension* beyond INVOCATION_TIMEOUT_S only.
# Values below default are ignored (never shorten the daemon budget). Bare number =
# minutes. Suffixes: s, m (default when omitted), h, d. Optional yes/true → 90 minutes.
parse_long_job_seconds() {
  [[ -f "$DIRECTIVE_FILE" ]] || { echo ""; return 0; }
  local rest val
  rest=$(grep -iE '^## *Long job[[:space:]]*:' "$DIRECTIVE_FILE" 2>/dev/null | head -1 \
    | sed -E 's/^## *Long job[[:space:]]*:[[:space:]]*//I' \
    | tr '[:upper:]' '[:lower:]')
  rest="${rest%%#*}"
  val="$(echo "$rest" | awk '{print $1}')"
  [[ -z "$val" ]] && { echo ""; return 0; }
  case "$val" in
    yes|true) echo $((90 * 60)); return 0 ;;
  esac
  if [[ "$val" =~ ^([0-9]+)([smhd]?)$ ]]; then
    local n="${BASH_REMATCH[1]}" u="${BASH_REMATCH[2]:-m}"
    case "$u" in
      s) echo "$n" ;;
      m) echo $((n * 60)) ;;
      h) echo $((n * 3600)) ;;
      d) echo $((n * 86400)) ;;
    esac
    return 0
  fi
  echo ""
}

all_workers_done() {
  [[ -n "$WORKERS_DIR" ]] || return 1
  [[ -d "$WORKERS_DIR" ]] || return 1
  local n_total=0 n_done=0
  shopt -s nullglob
  for f in "$WORKERS_DIR"/*-directive.md; do
    n_total=$((n_total + 1))
    local hdr
    hdr="$(head -1 "$f" 2>/dev/null)"
    case "$hdr" in
      "# Worker Report"*) n_done=$((n_done + 1)) ;;
    esac
  done
  shopt -u nullglob
  [[ "$n_total" -gt 0 && "$n_total" -eq "$n_done" ]]
}

EXECUTOR_PATH="$SCRIPT_DIR/executor.sh"
if [[ ! -f "$EXECUTOR_PATH" ]]; then
  # Fallback for older installs that hadn't been updated
  log "WARN: executor.sh missing — falling back to cursor-agent only"
  for bin in cursor-agent cursor; do
    command -v "$bin" >/dev/null 2>&1 && { CURSOR_BIN="$bin"; break; }
  done
  : "${CURSOR_BIN:?FATAL: no cursor-agent on PATH and no executor.sh available}"
else
  CURSOR_BIN=""
fi

log_cost() {
  local phase="$1" tier="$2" wall_s="$3" rc="$4" outcome="$5"
  spine_migrate_costs_csv_if_needed "$COSTS_FILE"
  if [[ ! -f "$COSTS_FILE" ]]; then
    echo "timestamp,role,mode,slot,phase,tier,wall_s,rc,outcome" > "$COSTS_FILE"
  fi
  echo "$(date -u +%FT%TZ),$ROLE,$MODE,${SLOT:--},$phase,$tier,$wall_s,$rc,$outcome" >> "$COSTS_FILE"
}

# Notification hook — best-effort, never blocks the daemon.
notify() {
  local title="$1" body="$2"
  local hook="$HOME/.spine-development/notify.sh"
  if [[ -x "$hook" ]]; then
    "$hook" "$title" "$body" </dev/null >/dev/null 2>&1 &
  fi
}

# Engineer-only: snapshot the working tree before invoking the agent so we
# can roll back if the directive breaks something. Uses git stash create
# (snapshot without touching the stash list) so it doesn't interfere with
# the architect's own stashes.
snapshot_for_rollback() {
  case "$ROLE" in engineer|engineering-backend|engineering-frontend) ;;
  *) return 0 ;;
  esac
  command -v git >/dev/null 2>&1 || return 0
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  local head_sha stash_sha tracked_sha untracked_sha snap_id
  head_sha=$(git rev-parse HEAD 2>/dev/null || echo "")
  [[ -z "$head_sha" ]] && return 0

  # Capture tracked changes via stash create (no working-tree disturbance).
  tracked_sha=$(git stash create 2>/dev/null || echo "")

  # Capture untracked files separately by hashing their tar.
  untracked_sha=""
  if git ls-files --others --exclude-standard 2>/dev/null | grep -q .; then
    local snap_dir="$TEAM_DIR/state/rollback-snapshots"
    mkdir -p "$snap_dir"
    snap_id=$(date -u +%Y%m%dT%H%M%SZ)
    git ls-files --others --exclude-standard -z 2>/dev/null \
      | tar --null -czf "$snap_dir/$snap_id-untracked.tar.gz" -T - 2>/dev/null \
      && untracked_sha="$snap_id-untracked.tar.gz"
  fi

  # CSV: timestamp, identity, directive_hash, head_sha, tracked_sha, untracked_archive, restored
  if [[ ! -f "$ROLLBACK_STACK" ]]; then
    echo "timestamp,identity,directive_hash,head_sha,tracked_sha,untracked_archive,restored" > "$ROLLBACK_STACK"
  fi
  echo "$(date -u +%FT%TZ),$IDENTITY,$(current_hash),$head_sha,$tracked_sha,$untracked_sha,no" >> "$ROLLBACK_STACK"
  log "rollback snapshot saved (head=${head_sha:0:12} tracked=${tracked_sha:0:12} untracked=${untracked_sha})"
}

load_memory_section() {
  if [[ -f "$MEMORY_FILE" ]] && [[ -s "$MEMORY_FILE" ]]; then
    printf '\n\n## Memory (lessons from prior runs of this role)\n\n'
    cat "$MEMORY_FILE"
  fi
}

build_prompt() {
  local mode="$1" tier
  tier="$(parse_tier_hint)"
  local memory_section
  memory_section="$(load_memory_section)"

  local tier_guidance
  case "$tier" in
    low)
      tier_guidance='COST GUIDANCE: this is a LOW-tier task. Use the cheapest model that can do the job competently (haiku-class / 7B-class / qwen-7b). Do NOT escalate to a high-tier model unless the cheap one explicitly fails on a sub-task and you log why.'
      ;;
    high)
      tier_guidance='COST GUIDANCE: this is a HIGH-tier task. The architect has authorized the most capable model available. Use it to produce careful, thorough output. Document any subjective trade-offs in your report.'
      ;;
    *)
      tier_guidance='COST GUIDANCE: this is a MEDIUM-tier task (default). Start with a mid-tier model (sonnet-class / gpt-4o-class / qwen-72b). Escalate ONLY if you encounter a sub-task that requires deeper reasoning. Document any escalation decision in your report.'
      ;;
  esac

  # File hygiene contract — same for all roles. Daemon wipes SCRATCH_DIR and
  # OS_TEMP_DIR every time a new directive arrives, so anything you put there
  # is guaranteed to be cleaned up. Anything you write OUTSIDE those paths is
  # your responsibility to clean up before reporting done.
  local hygiene_block
  hygiene_block="FILE HYGIENE (mandatory):
- Use \$SCRATCH_DIR=$SCRATCH_DIR for any temporary files (notes, intermediate output, drafts, downloaded fixtures, generated test data). The daemon wipes this dir every time a new directive arrives — anything here is safe to drop.
- Use \$TMPDIR=$OS_TEMP_DIR for OS-level temp files. Same lifecycle — wiped on new directive.
- Do NOT write temp files to repo root, /tmp, ~/Desktop, or anywhere else. If a tool insists on a fixed path, copy to scratch when done.
- Do NOT leave .bak / .orig / ~ / .tmp / .swp files anywhere in the repo. If you create one, delete it before reporting.
- Do NOT leave debug scripts, scratch test files, or one-off verification scripts in the repo. If they're worth keeping, propose a permanent home in your report; otherwise delete.
- Before writing your final # Report, take inventory: list every file you created or modified OUTSIDE of \$SCRATCH_DIR / \$TMPDIR / your role's directive.md / memory.md / scratch dir. Confirm in the report's '## Files touched' section that each is intentional. Anything you can't justify, delete now."

  case "$mode" in
    manager-pickup)
      local approval_block=""
      if requires_approval; then
        approval_block="
APPROVAL GATE (mandatory):
This directive is flagged \`## Requires approval: yes\`. You MUST NOT execute or spawn workers yet. Instead:
1. Analyze the directive and produce a CONCRETE plan (numbered actions with file paths, commands, expected effects).
2. Replace $DIRECTIVE_FILE with a header \"# Awaiting approval — <task>\" followed by:
   - \"## Plan\" section: the numbered actions
   - \"## Risks\" section: what could go wrong, with severity
   - \"## Rollback\" section: how to undo if something breaks
   - The original directive content preserved verbatim under \"## Original directive\"
3. Exit cleanly. The architect will review and add a \`## Approved by: <name> @ <timestamp>\` line to authorize execution. Do NOT add this line yourself."
      fi
      cat <<EOF
You are the $ROLE manager in the file-based agent team. Read $PROTOCOL_FILE for the full contract. Read $ROLE_PROMPT_FILE for your role-specific permissions and prohibitions. Both are mandatory.

$tier_guidance

$hygiene_block
$approval_block

A new directive has landed at $DIRECTIVE_FILE. Read it. Decide:
- Single-shot: execute end-to-end. Replace $DIRECTIVE_FILE with "# Report — <summary>" containing your structured output (see role-prompt for the report shape). Always include a "## TL;DR" section ≤ 5 lines at the top, and a "## Files touched" section listing every file you created/modified outside the team directory.
- Decompose: split into N (≤ 10) parallel worker tasks. Write each to ${WORKERS_DIR}/01-directive.md, ${WORKERS_DIR}/02-directive.md, etc., starting with "# Worker Directive — <slice>". Each worker directive should declare a "## File scope" line listing exactly which files/dirs that worker is allowed to touch. Then OVERWRITE $DIRECTIVE_FILE with "# Plan — <task>" listing the workers + what each is doing. Then exit. Do NOT poll inline.

Hard constraints:
- Stay strictly within your role's permitted set (role-prompt.md).
- Atomic file writes (write to .tmp then mv) so the daemon never sees half-written files.
- If you discover a lesson worth preserving for future invocations, append a one-liner to $MEMORY_FILE before exiting.
- Do not exceed 10 workers without explicit architect approval.
$memory_section

Begin now.
EOF
      ;;
    manager-execute-after-approval)
      cat <<EOF
You are the $ROLE manager. The architect has APPROVED a previously gated plan in $DIRECTIVE_FILE.

$tier_guidance

$hygiene_block

The file currently contains a "# Awaiting approval" header, a "## Plan" you authored, and a "## Approved by:" line the architect added. Read your own plan. Now EXECUTE it.

Your options are the same as a fresh pickup:
- Single-shot execute end-to-end and replace the file with "# Report — <summary>".
- Decompose: write worker directives, replace this file with "# Plan — <task>", then exit. (Each worker directive should declare "## File scope".)

Constraints:
- Execute the plan AS APPROVED. If you discover the plan is wrong, replace the file with "# Report — STOPPED: plan needs revision" and explain why; do not silently re-plan.
- Atomic file writes. "## Files touched" section in the report.
$memory_section

Begin now.
EOF
      ;;
    manager-aggregate)
      cat <<EOF
You are the $ROLE manager. Workers have all reported. Read every file matching ${WORKERS_DIR}/*-directive.md (now containing "# Worker Report ..." content). Synthesize.

$tier_guidance (Most aggregation work is LOW or MEDIUM tier — synthesis is rarely high-reasoning.)

$hygiene_block

Then:
1. Replace $DIRECTIVE_FILE with "# Report — <task>" containing the synthesis (root cause / outcome / per-worker summary / open questions / suggested next directive). Include a "## TL;DR" section ≤ 5 lines at the very top, and a "## Files touched" section that aggregates each worker's "Files touched" lists.
2. Move all worker files to ${WORKERS_DIR}/archive/$(date +%Y%m%dT%H%M%SZ)/ to clear the slate.
3. If a worker reported timeout/failure, surface that prominently and copy the relevant excerpt verbatim.
4. Append any cross-cutting lessons to $MEMORY_FILE.
5. Exit.
$memory_section

Begin now.
EOF
      ;;
    worker)
      cat <<EOF
You are a worker for the $ROLE manager. Read $PROTOCOL_FILE for the contract. Read $ROLE_PROMPT_FILE for permitted actions.

$tier_guidance

$hygiene_block

A worker directive is at $DIRECTIVE_FILE. Read it. Execute your slice. Replace the file's contents with "# Worker Report — <one-line summary>" followed by your structured output, including a "## Files touched" section.

Hard constraints:
- Stay within your role's permitted set AND your directive's "## File scope" line. If you need to edit a file outside your scope, stop and report; do not silently expand.
- Do not spawn further workers (tree is exactly 2 levels).
- If you can't complete, replace the file with "# Worker Report — FAILED: <reason>"; never leave it as a directive.
$memory_section

Begin now.
EOF
      ;;
  esac
}

invoke_cursor() {
  local prompt="$1" phase="$2" tier
  export DIRECTIVE_FILE
  tier="$(parse_tier_hint)"
  local started rc wall_s lj_hint_sec inv_to stall_to
  started=$(date +%s)
  lj_hint_sec="$(parse_long_job_seconds)"
  inv_to="$INVOCATION_TIMEOUT_S"
  stall_to="$STALL_THRESHOLD_S"
  local lj_extended=0
  if [[ -n "$lj_hint_sec" ]] && (( lj_hint_sec > inv_to )); then
    inv_to="$lj_hint_sec"
    stall_to=$((inv_to / 3))
    local stall_cap=$((30 * 60))
    (( stall_to > stall_cap )) && stall_to=$stall_cap
    (( stall_to < 60 )) && stall_to=60
    lj_extended=1
  fi

  local agent_log_size_before
  agent_log_size_before=$(wc -c < "$AGENT_LOG" 2>/dev/null || echo 0)

  local lj_note=""
  [[ "$lj_extended" -eq 1 ]] && lj_note=", long_job_extended"
  echo "----- $(date -u +%FT%TZ) invoke ($IDENTITY, phase=$phase, tier=$tier, timeout=${inv_to}s, stall=${stall_to}s${lj_note}) -----" >> "$AGENT_LOG"

  local TIMEOUT_BIN=
  local timeout_wrapper_used=0
  if command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN=gtimeout
  elif command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN=timeout
  fi
  [[ -n "$TIMEOUT_BIN" ]] && timeout_wrapper_used=1

  # Write prompt to a temp file so we can pass it cleanly to the executor.
  local prompt_file
  prompt_file=$(mktemp "${TMPDIR:-/tmp}/spine-prompt-XXXXXX") || { log "FATAL: cannot mktemp"; return 1; }
  printf '%s' "$prompt" > "$prompt_file"

  # Choose dispatch path: pluggable executor.sh OR legacy direct binary
  local cmd=()
  if [[ -n "$CURSOR_BIN" ]]; then
    cmd=("$CURSOR_BIN" "$prompt")
  else
    cmd=(bash "$EXECUTOR_PATH" "$prompt_file")
  fi

  local stall_kill=0
  if [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" --kill-after=30 "$inv_to" \
      "${cmd[@]}" </dev/null >> "$AGENT_LOG" 2>&1 &
  else
    "${cmd[@]}" </dev/null >> "$AGENT_LOG" 2>&1 &
  fi
  local agent_pid=$!

  # Stall watcher: if AGENT_LOG hasn't grown in stall_to seconds, kill.
  local last_size=$agent_log_size_before
  local last_grow_at=$started
  while kill -0 "$agent_pid" 2>/dev/null; do
    sleep 30
    local now sz
    now=$(date +%s)
    sz=$(wc -c < "$AGENT_LOG" 2>/dev/null || echo "$last_size")
    if (( sz > last_size )); then
      last_size=$sz
      last_grow_at=$now
    elif (( now - last_grow_at > stall_to )); then
      log "STALL: no agent output for ${stall_to}s, killing pid=$agent_pid"
      stall_kill=1
      kill "$agent_pid" 2>/dev/null
      sleep 5
      kill -9 "$agent_pid" 2>/dev/null
      break
    fi
  done

  wait "$agent_pid" 2>/dev/null
  rc=$?
  wall_s=$(( $(date +%s) - started ))

  rm -f "$prompt_file" 2>/dev/null

  local outcome=completed
  if (( stall_kill )); then
    outcome=stall
  elif (( timeout_wrapper_used )) && { [[ "$rc" -eq 124 ]] || [[ "$rc" -eq 137 ]]; }; then
    outcome=timeout
  elif (( rc > 128 )); then
    outcome=killed
  fi

  echo "----- exit rc=$rc wall=${wall_s}s outcome=$outcome -----" >> "$AGENT_LOG"
  log_cost "$phase" "$tier" "$wall_s" "$rc" "$outcome"
  return $rc
}

if [[ -n "$CURSOR_BIN" ]]; then
  log "Daemon v1.2 starting (cli=$CURSOR_BIN [legacy], poll=${POLL_INTERVAL}s, timeout=${INVOCATION_TIMEOUT_S}s, stall=${STALL_THRESHOLD_S}s, file=$DIRECTIVE_FILE)"
else
  log "Daemon v1.2 starting (executor=$EXECUTOR_PATH, EXECUTOR_KIND=${EXECUTOR_KIND:-auto}, EXECUTOR_CMD=${EXECUTOR_CMD:-(auto-detect)}, poll=${POLL_INTERVAL}s, timeout=${INVOCATION_TIMEOUT_S}s, stall=${STALL_THRESHOLD_S}s, file=$DIRECTIVE_FILE)"
fi

# Final-state classifier — used to decide whether to fire a notification
state_after_invocation() {
  local kind_after="$(classify_file)"
  local hdr
  hdr="$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)"
  case "$kind_after" in
    report|worker-report)
      if [[ "$hdr" == *"FAILED"* || "$hdr" == *"STOPPED"* || "$hdr" == *"TIMEOUT"* ]]; then
        echo "failure"
      else
        echo "success"
      fi
      ;;
    awaiting-approval) echo "awaiting-approval" ;;
    *) echo "$kind_after" ;;
  esac
}

idle=0
while true; do
  # Heartbeat: watchdog reads this file's mtime to decide if we're alive
  : > "$HEARTBEAT_FILE" 2>/dev/null || touch "$HEARTBEAT_FILE" 2>/dev/null

  curr="$(current_hash)"
  last="$(last_hash)"
  kind="$(classify_file)"

  workers_just_finished=false
  if [[ "$MODE" == "manager" && "$kind" == "plan" ]]; then
    if all_workers_done; then
      workers_just_finished=true
    fi
  fi

  if [[ -z "$curr" || "$curr" == "$last" ]] && [[ "$workers_just_finished" == false ]]; then
    idle=$((idle + 1))
    if (( idle % HEARTBEAT_EVERY == 0 )); then
      log "idle (state=$kind, last_hash=${last:0:12}, polls=$idle)"
    fi
    sleep "$POLL_INTERVAL"
    continue
  fi

  idle=0

  rotate_log_if_huge "$DAEMON_LOG"
  rotate_log_if_huge "$AGENT_LOG"

  if [[ "$workers_just_finished" == true ]]; then
    log "AGGREGATE: all workers reported, invoking manager to synthesize"
    invoke_cursor "$(build_prompt manager-aggregate)" aggregate
    rc=$?
    final_state=$(state_after_invocation)
    log "aggregate done (rc=$rc, new state=$(classify_file), outcome=$final_state)"
    printf '%s\n' "$(current_hash)" > "$HASH_FILE"
    case "$final_state" in
      success)  notify "[$IDENTITY] aggregate complete" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
      failure)  notify "[$IDENTITY] aggregate FAILED" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
    esac

  elif [[ "$kind" == "directive" && "$MODE" == "manager" ]]; then
    log "PICKUP manager directive (hash=${curr:0:12}, tier=$(parse_tier_hint), approval=$(requires_approval && echo yes || echo no)) — wiping scratch"
    reset_scratch
    snapshot_for_rollback
    invoke_cursor "$(build_prompt manager-pickup)" pickup
    rc=$?
    final_state=$(state_after_invocation)
    log "manager-pickup done (rc=$rc, new state=$(classify_file), outcome=$final_state)"
    printf '%s\n' "$(current_hash)" > "$HASH_FILE"
    case "$final_state" in
      success)            notify "[$IDENTITY] directive complete" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
      failure)            notify "[$IDENTITY] directive FAILED" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
      awaiting-approval)  notify "[$IDENTITY] AWAITING APPROVAL" "Directive paused — review plan in $DIRECTIVE_FILE and add a '## Approved by:' line to authorize execution." ;;
    esac

  elif [[ "$kind" == "approved" && "$MODE" == "manager" ]]; then
    log "APPROVED — executing previously gated plan (hash=${curr:0:12})"
    snapshot_for_rollback
    invoke_cursor "$(build_prompt manager-execute-after-approval)" execute-approved
    rc=$?
    final_state=$(state_after_invocation)
    log "approved-execute done (rc=$rc, new state=$(classify_file), outcome=$final_state)"
    printf '%s\n' "$(current_hash)" > "$HASH_FILE"
    case "$final_state" in
      success)  notify "[$IDENTITY] approved plan complete" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
      failure)  notify "[$IDENTITY] approved plan FAILED" "$(head -1 "$DIRECTIVE_FILE" 2>/dev/null)" ;;
    esac

  elif [[ "$kind" == "worker-directive" && "$MODE" == "worker" ]]; then
    log "PICKUP worker directive (hash=${curr:0:12}, tier=$(parse_tier_hint)) — wiping scratch"
    reset_scratch
    snapshot_for_rollback
    invoke_cursor "$(build_prompt worker)" worker
    rc=$?
    log "worker done (rc=$rc, new state=$(classify_file))"
    printf '%s\n' "$(current_hash)" > "$HASH_FILE"

  else
    log "noop (state=$kind, hash=${curr:0:12})"
    printf '%s\n' "$curr" > "$HASH_FILE"
  fi

  sleep "$POLL_INTERVAL"
done

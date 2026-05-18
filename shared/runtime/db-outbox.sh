#!/usr/bin/env bash
# db-outbox.sh - Append-only JSONL outbox emitter for the Spine daemon.
#
# Purpose:
#   Pass B of the Postgres integration. The daemon continues to write
#   costs.csv as the source of truth. ADDITIONALLY, it appends a JSON
#   line per cost row to <state>/outbox.jsonl. A separate Python watcher
#   process drains the outbox into Postgres. The watcher is the only
#   consumer that advances the byte offset cursor; the daemon never
#   reads its own outbox back.
#
# Contract:
#   spine_outbox_emit_cost ROLE STATE_DIR JSON_CONTENT
#     - Atomic append (one line) to STATE_DIR/outbox.jsonl
#     - Concurrent-safe across daemon processes (multiple worker slots +
#       the manager share the same outbox file, just like costs.csv).
#     - Returns 0 on success.
#     - On ANY failure: logs to stderr but returns 0 anyway. The daemon
#       must NEVER crash because of an outbox write failure - costs.csv
#       is the source of truth and the watcher will catch up later (or
#       a future tick will succeed).
#
# Locking strategy:
#   Linux ships util-linux flock(1). macOS does NOT (Apple's
#   /usr/bin/flock applies to filesystems, not file descriptors). We
#   detect flock(1) on PATH at first call and cache the result:
#     - If available: use `flock -x -w 5 <fd>` around the append.
#     - Otherwise (macOS default): use a directory-as-mutex fallback
#       (mkdir is atomic in POSIX) with a short retry loop.
#   In both paths the actual append is a single `printf >>` so even
#   if locking races, append(2) on most filesystems is atomic for
#   write sizes <= PIPE_BUF (4096 on Linux, 512 on macOS). Cost JSON
#   lines are well under 4096 bytes; the lock is belt-and-braces.

# Intentionally not "set -eu" - this file is sourced by team-agent-daemon.sh
# and a stray error here must not kill the daemon.

# Cached at first use. 1 = flock(1) usable, 0 = fall back to mkdir.
_SPINE_OUTBOX_HAS_FLOCK=""

_spine_outbox_detect_flock() {
  if [[ -n "$_SPINE_OUTBOX_HAS_FLOCK" ]]; then
    return 0
  fi
  if command -v flock >/dev/null 2>&1; then
    # macOS sometimes ships a `flock` from Homebrew util-linux; also
    # verify it accepts an fd argument by checking --help quickly.
    # `flock --version` exits 0 on util-linux; the BSD/macOS namesake
    # rejects it. Suppress all output.
    if flock --version >/dev/null 2>&1; then
      _SPINE_OUTBOX_HAS_FLOCK=1
      return 0
    fi
  fi
  _SPINE_OUTBOX_HAS_FLOCK=0
}

# Internal: append a single line using flock(1) on fd 9.
_spine_outbox_append_flock() {
  local outbox="$1" line="$2"
  # Open fd 9 for append, take an exclusive lock with 5s wait, write line.
  # Subshell so the fd closes (and the lock releases) on exit.
  (
    exec 9>>"$outbox" || exit 1
    if ! flock -x -w 5 9; then
      exit 2
    fi
    printf '%s\n' "$line" >&9 || exit 3
  )
}

# Internal: append a single line using mkdir-as-mutex (macOS fallback).
_spine_outbox_append_mkdir() {
  local outbox="$1" line="$2"
  local lockdir="${outbox}.lockdir"
  local tries=0
  while (( tries < 50 )); do
    if mkdir "$lockdir" 2>/dev/null; then
      # Got the lock. Make sure it's removed even if the printf fails.
      trap 'rmdir "$lockdir" 2>/dev/null' RETURN
      printf '%s\n' "$line" >> "$outbox" || {
        rmdir "$lockdir" 2>/dev/null
        trap - RETURN
        return 1
      }
      rmdir "$lockdir" 2>/dev/null
      trap - RETURN
      return 0
    fi
    # 100ms backoff; 50 tries = 5s max wait, matching the flock path.
    sleep 0.1 2>/dev/null || sleep 1
    tries=$((tries + 1))
  done
  # Timed out waiting; try one last unsynchronized append. append(2) on
  # small lines is atomic on every filesystem we care about, so this is
  # still safer than dropping the line.
  printf '%s\n' "$line" >> "$outbox"
}

# Public: emit one cost row to the role's outbox.
#
#   spine_outbox_emit_cost ROLE STATE_DIR JSON_CONTENT
#
# JSON_CONTENT must be a single-line JSON object. We do not validate; the
# watcher will skip and log malformed lines.
spine_outbox_emit_cost() {
  local role="$1" state_dir="$2" json="$3"

  if [[ -z "$state_dir" || -z "$json" ]]; then
    printf '%s\n' "spine_outbox_emit_cost: missing args (role=$role state_dir=$state_dir)" >&2
    return 0
  fi

  # Ensure state dir exists - the daemon already mkdirs it, but be defensive.
  if ! mkdir -p "$state_dir" 2>/dev/null; then
    printf '%s\n' "spine_outbox_emit_cost: cannot mkdir $state_dir" >&2
    return 0
  fi

  # Pass I-3: splice an engagement_id field into the cost JSON unless one
  # was already provided by the caller. The daemon's log_cost path builds
  # JSON without an engagement_id, so this is the central place to attach
  # the parent engagement when SPINE_ENGAGEMENT_ID is exported. When the
  # env var is unset we still write `"engagement_id":null` so the watcher
  # sees a uniform shape and never has to guess.
  if [[ "$json" != *'"engagement_id"'* ]]; then
    local eng_field
    eng_field="$(_spine_outbox_engagement_field)"
    # Splice the field just before the trailing closing brace.
    json="${json%\}}${eng_field}}"
  fi

  # Pass J F3: splice an idempotency_key field into the cost JSON. The
  # watcher reads this and writes it to assignment.idempotency_key with
  # ON CONFLICT (worker_id, idempotency_key) DO NOTHING so a retried
  # outbox line cannot create a second cost row + second assignment.
  if [[ "$json" != *'"idempotency_key"'* ]]; then
    local idem_field
    idem_field="$(_spine_outbox_idempotency_field)"
    json="${json%\}}${idem_field}}"
  fi

  # Pass K: splice tenant_id so the V11 cost_row.tenant_id column is
  # populated. Default 'default' when SPINE_TENANT is unset.
  if [[ "$json" != *'"tenant_id"'* ]]; then
    local tenant_field
    tenant_field="$(_spine_outbox_tenant_field)"
    json="${json%\}}${tenant_field}}"
  fi

  local outbox="$state_dir/outbox.jsonl"

  _spine_outbox_detect_flock

  if [[ "$_SPINE_OUTBOX_HAS_FLOCK" == "1" ]]; then
    if ! _spine_outbox_append_flock "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_cost: flock append failed for $outbox" >&2
    fi
  else
    if ! _spine_outbox_append_mkdir "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_cost: mkdir-lock append failed for $outbox" >&2
    fi
  fi

  return 0
}

# Helper: emit a JSON field fragment for an optional engagement_id. When
# SPINE_ENGAGEMENT_ID is set to a non-empty value, returns:
#   ,"engagement_id":"<value>"
# Otherwise returns:
#   ,"engagement_id":null
# The leading comma is INCLUDED so callers can splice the fragment into the
# end of an object body (just before the closing brace) without needing
# string concatenation logic. We deliberately avoid jq -- jq isn't on every
# host -- and use printf with conditional substitution.
#
# Pass I-3: cost rows and lifecycle events both pick this up so any
# invocation kicked off under an engagement gets its rows tagged. The
# watcher decodes null vs. uuid string symmetrically.
_spine_outbox_engagement_field() {
  local eid="${SPINE_ENGAGEMENT_ID:-}"
  if [[ -n "$eid" ]]; then
    # JSON-escape defensively even though valid UUIDs need no escaping.
    local esc
    esc="$(spine_outbox_json_escape "$eid")"
    printf ',"engagement_id":"%s"' "$esc"
  else
    printf ',"engagement_id":null'
  fi
}

# Pass J F3: helper mirror to _spine_outbox_engagement_field that emits a
# leading-comma JSON fragment for the idempotency key:
#   ,"idempotency_key":"<sha256-hex>"   -- when SPINE_IDEMPOTENCY_KEY set
#   ,"idempotency_key":null             -- otherwise
# Same conditional-splice pattern so the watcher sees a uniform shape.
_spine_outbox_idempotency_field() {
  local ikey="${SPINE_IDEMPOTENCY_KEY:-}"
  if [[ -n "$ikey" ]]; then
    local esc
    esc="$(spine_outbox_json_escape "$ikey")"
    printf ',"idempotency_key":"%s"' "$esc"
  else
    printf ',"idempotency_key":null'
  fi
}

# Pass K: tenant scoping. Every outbox line gets a tenant_id field so the
# watcher can populate the V11 tenant_id columns. Defaults to "default"
# when SPINE_TENANT is unset — matches the DB-side column default and
# preserves single-tenant behavior. Returns the leading-comma fragment
# in the same spirit as _spine_outbox_engagement_field above.
_spine_outbox_tenant_field() {
  local t="${SPINE_TENANT:-default}"
  local esc
  esc="$(spine_outbox_json_escape "$t")"
  printf ',"tenant_id":"%s"' "$esc"
}

# Helper: minimal JSON-string escaping for values built with printf. We do
# not pull in jq because not every host has it. Escapes the small set that
# matters for one-line cost rows: backslash, double-quote, and control
# characters that would break a JSON parser. Tab/newline/CR are escaped
# explicitly; other control chars are dropped (they should never appear
# in our fields anyway - role/mode/slot/phase/tier/outcome are constrained).
spine_outbox_json_escape() {
  local s="$1"
  # Order matters: backslash first, then quote.
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

# Public: emit one lifecycle event row to the role's outbox.
#
#   spine_outbox_emit_event ROLE STATE_DIR EVENT_TYPE PAYLOAD_JSON
#
# Pass D: lifecycle events (DirectivePickup, PlanWritten, AwaitingApproval,
# Approved, ReportWritten, AggregateCompleted, Reaped, ...) are emitted to
# the SAME outbox.jsonl as cost rows. The outer JSON envelope is:
#   {"type":"event","ts":"<utc-iso>","event_type":"<TYPE>",
#    "role":"...","mode":"...","slot":"...","host_id":"...","instance_id":"...",
#    "payload":<PAYLOAD_JSON>}
# The watcher routes on the outer "type" field: "cost" -> cost_row projection,
# "event" -> event-table insert. Reuses the SAME flock/mkdir locking as
# spine_outbox_emit_cost so multi-process emits stay interleaved-safe.
#
# Required env (exported by team-agent-daemon.sh near the top of the daemon):
#   SPINE_HOST_ID, SPINE_INSTANCE_ID, MODE, SLOT
#
# PAYLOAD_JSON must be a complete JSON value (object, array, string, ...).
# Empty string is normalised to {} so the watcher never has to special-case
# missing payloads.
#
# Returns 0 unconditionally - lifecycle emits are best-effort and must
# never crash the daemon (matches spine_outbox_emit_cost semantics).
spine_outbox_emit_event() {
  local role="$1" state_dir="$2" event_type="$3" payload="${4:-}"

  if [[ -z "$state_dir" || -z "$event_type" ]]; then
    printf '%s\n' "spine_outbox_emit_event: missing args (role=$role state_dir=$state_dir event_type=$event_type)" >&2
    return 0
  fi

  if ! mkdir -p "$state_dir" 2>/dev/null; then
    printf '%s\n' "spine_outbox_emit_event: cannot mkdir $state_dir" >&2
    return 0
  fi

  [[ -z "$payload" ]] && payload='{}'

  local outbox="$state_dir/outbox.jsonl"
  local ts esc_role esc_mode esc_slot esc_event esc_host esc_instance
  ts="$(date -u +%FT%TZ)"
  esc_role="$(spine_outbox_json_escape "$role")"
  esc_mode="$(spine_outbox_json_escape "${MODE:-}")"
  esc_slot="$(spine_outbox_json_escape "${SLOT:--}")"
  esc_event="$(spine_outbox_json_escape "$event_type")"
  esc_host="$(spine_outbox_json_escape "${SPINE_HOST_ID:-}")"
  esc_instance="$(spine_outbox_json_escape "${SPINE_INSTANCE_ID:-}")"

  # Pass I-3: include engagement_id from SPINE_ENGAGEMENT_ID. null when
  # unset (literal, no quotes); a quoted UUID string otherwise. The
  # watcher decodes both shapes symmetrically.
  local eng_field idem_field tenant_field
  eng_field="$(_spine_outbox_engagement_field)"
  # Pass J F3: include idempotency_key the same way so lifecycle events
  # share the assignment dedupe story with cost rows.
  idem_field="$(_spine_outbox_idempotency_field)"
  # Pass K: include tenant_id so the V11 event.tenant_id column is
  # populated. Defaults to 'default' when SPINE_TENANT is unset.
  tenant_field="$(_spine_outbox_tenant_field)"

  local json
  printf -v json '{"type":"event","ts":"%s","event_type":"%s","role":"%s","mode":"%s","slot":"%s","host_id":"%s","instance_id":"%s","payload":%s%s%s%s}' \
    "$ts" "$esc_event" "$esc_role" "$esc_mode" "$esc_slot" "$esc_host" "$esc_instance" "$payload" "$eng_field" "$idem_field" "$tenant_field"

  _spine_outbox_detect_flock

  if [[ "$_SPINE_OUTBOX_HAS_FLOCK" == "1" ]]; then
    if ! _spine_outbox_append_flock "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_event: flock append failed for $outbox" >&2
    fi
  else
    if ! _spine_outbox_append_mkdir "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_event: mkdir-lock append failed for $outbox" >&2
    fi
  fi

  return 0
}

# Public: emit one instance-lifecycle event to the TOP-LEVEL instance outbox.
#
#   spine_outbox_emit_instance_event EVENT_TYPE PAYLOAD_JSON
#
# Pass H (Spine Hub). Unlike per-role lifecycle events, instance events
# describe the whole `team.sh up` invocation (one logical Spine instance),
# not a single agent. To keep watcher discovery dead simple they live in a
# SINGLE file at
#   .planning/orchestration/agent-handoff/.instance-outbox.jsonl
# rather than per-role. The watcher finds this file by walking one level
# above the per-role outboxes (TEAM_BASE/../.instance-outbox.jsonl).
#
# Required env (exported by team.sh::cmd_up before the first call):
#   SPINE_GROUP_ID, SPINE_HOST_ID, SPINE_VERSION_SHA, SPINE_PROJECT_SLUG,
#   SPINE_PROJECT_PATH
#
# Optional:
#   SPINE_INSTANCE_OUTBOX  - override the outbox path (test injection).
#
# The watcher routes on the outer "type":"instance" field. JSON shape:
#   {"type":"instance","ts":"<utc-iso>","event_type":"InstanceStarted",
#    "group_id":"<uuid>","host_id":"...","os_user":"...",
#    "project_slug":"...","project_path":"...",
#    "version_sha":"...","version_short":"...","spine_version":"...",
#    "payload":<PAYLOAD_JSON>}
#
# Returns 0 unconditionally (best-effort, same as the other emitters).
spine_outbox_emit_instance_event() {
  local event_type="$1" payload="${2:-}"

  if [[ -z "$event_type" ]]; then
    printf '%s\n' "spine_outbox_emit_instance_event: event_type required" >&2
    return 0
  fi

  [[ -z "$payload" ]] && payload='{}'

  local outbox="${SPINE_INSTANCE_OUTBOX:-.planning/orchestration/agent-handoff/.instance-outbox.jsonl}"
  if ! mkdir -p "$(dirname "$outbox")" 2>/dev/null; then
    printf '%s\n' "spine_outbox_emit_instance_event: cannot mkdir $(dirname "$outbox")" >&2
    return 0
  fi

  # Resolve spine_version lazily from CHANGELOG.md if not provided. The
  # first non-blank heading line is expected to look like "## v1.4.5 — ...";
  # we extract the bare version token. Missing CHANGELOG -> empty string.
  local spine_version="${SPINE_VERSION:-}"
  if [[ -z "$spine_version" && -f "CHANGELOG.md" ]]; then
    spine_version=$(awk '
      /^##[[:space:]]+v?[0-9]/ {
        for (i=1; i<=NF; i++) {
          if ($i ~ /^v?[0-9]+\.[0-9]+/) {
            sub(/^v/, "", $i); print $i; exit
          }
        }
      }' CHANGELOG.md 2>/dev/null | head -1)
  fi

  local version_sha="${SPINE_VERSION_SHA:-}"
  local version_short="${version_sha:0:12}"
  local os_user="${USER:-${LOGNAME:-unknown}}"

  local ts esc_event esc_group esc_host esc_user esc_slug esc_path
  local esc_sha esc_short esc_sver
  ts="$(date -u +%FT%TZ)"
  esc_event="$(spine_outbox_json_escape "$event_type")"
  esc_group="$(spine_outbox_json_escape "${SPINE_GROUP_ID:-}")"
  esc_host="$(spine_outbox_json_escape "${SPINE_HOST_ID:-}")"
  esc_user="$(spine_outbox_json_escape "$os_user")"
  esc_slug="$(spine_outbox_json_escape "${SPINE_PROJECT_SLUG:-}")"
  esc_path="$(spine_outbox_json_escape "${SPINE_PROJECT_PATH:-}")"
  esc_sha="$(spine_outbox_json_escape "$version_sha")"
  esc_short="$(spine_outbox_json_escape "$version_short")"
  esc_sver="$(spine_outbox_json_escape "$spine_version")"

  # Pass K: include tenant_id so the watcher can populate the V11
  # spine_instance.tenant_id column. Defaults to 'default' when SPINE_TENANT
  # is unset.
  local tenant_field
  tenant_field="$(_spine_outbox_tenant_field)"

  local json
  printf -v json '{"type":"instance","ts":"%s","event_type":"%s","group_id":"%s","host_id":"%s","os_user":"%s","project_slug":"%s","project_path":"%s","version_sha":"%s","version_short":"%s","spine_version":"%s","payload":%s%s}' \
    "$ts" "$esc_event" "$esc_group" "$esc_host" "$esc_user" "$esc_slug" "$esc_path" "$esc_sha" "$esc_short" "$esc_sver" "$payload" "$tenant_field"

  _spine_outbox_detect_flock

  if [[ "$_SPINE_OUTBOX_HAS_FLOCK" == "1" ]]; then
    if ! _spine_outbox_append_flock "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_instance_event: flock append failed for $outbox" >&2
    fi
  else
    if ! _spine_outbox_append_mkdir "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_instance_event: mkdir-lock append failed for $outbox" >&2
    fi
  fi

  return 0
}

# Public: emit one engagement-lifecycle event to the TOP-LEVEL instance outbox.
#
#   spine_outbox_emit_engagement_event ENGAGEMENT_ID EVENT_TYPE PAYLOAD_JSON
#
# Pass I-1 (Engagement entity). Engagement events describe the lifecycle of
# a client engagement (intake -> hardening -> planning -> approval ->
# execution -> delivered). To keep watcher discovery dead simple they
# REUSE the existing top-level instance-outbox (the same file that carries
# InstanceStarted / InstanceHeartbeat / InstanceStopped) rather than
# introducing a third file. The watcher routes on the outer
# "type":"engagement" field.
#
# Required env (exported by team.sh / the dashboard backend before the
# first call):
#   SPINE_GROUP_ID, SPINE_HOST_ID
# Optional:
#   SPINE_INSTANCE_OUTBOX  - override the outbox path (test injection).
#
# Event types this pass:
#   * EngagementCreated         - new engagement just submitted
#   * EngagementStatusChanged   - watcher / later passes flip the status
#
# PAYLOAD_JSON must be a complete JSON object (or other JSON value). Empty
# string is normalised to {} so the watcher never has to special-case
# missing payloads.
#
# Returns 0 unconditionally (best-effort, same as the other emitters).
spine_outbox_emit_engagement_event() {
  local engagement_id="$1" event_type="$2" payload="${3:-}"

  if [[ -z "$engagement_id" || -z "$event_type" ]]; then
    printf '%s\n' "spine_outbox_emit_engagement_event: engagement_id and event_type required" >&2
    return 0
  fi

  [[ -z "$payload" ]] && payload='{}'

  local outbox="${SPINE_INSTANCE_OUTBOX:-.planning/orchestration/agent-handoff/.instance-outbox.jsonl}"
  if ! mkdir -p "$(dirname "$outbox")" 2>/dev/null; then
    printf '%s\n' "spine_outbox_emit_engagement_event: cannot mkdir $(dirname "$outbox")" >&2
    return 0
  fi

  local ts esc_event esc_eid esc_group esc_host
  ts="$(date -u +%FT%TZ)"
  esc_event="$(spine_outbox_json_escape "$event_type")"
  esc_eid="$(spine_outbox_json_escape "$engagement_id")"
  esc_group="$(spine_outbox_json_escape "${SPINE_GROUP_ID:-}")"
  esc_host="$(spine_outbox_json_escape "${SPINE_HOST_ID:-}")"

  # Pass K: include tenant_id so engagement / engagement_message /
  # artifact rows derived from this event get tagged. The watcher reads
  # it from the outer envelope.
  local tenant_field
  tenant_field="$(_spine_outbox_tenant_field)"

  local json
  printf -v json '{"type":"engagement","ts":"%s","event_type":"%s","engagement_id":"%s","group_id":"%s","host_id":"%s","payload":%s%s}' \
    "$ts" "$esc_event" "$esc_eid" "$esc_group" "$esc_host" "$payload" "$tenant_field"

  _spine_outbox_detect_flock

  if [[ "$_SPINE_OUTBOX_HAS_FLOCK" == "1" ]]; then
    if ! _spine_outbox_append_flock "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_engagement_event: flock append failed for $outbox" >&2
    fi
  else
    if ! _spine_outbox_append_mkdir "$outbox" "$json"; then
      printf '%s\n' "spine_outbox_emit_engagement_event: mkdir-lock append failed for $outbox" >&2
    fi
  fi

  return 0
}

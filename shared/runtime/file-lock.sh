#!/usr/bin/env bash
# file-lock.sh — coarse file-level lock helper for engineer workers.
#
# Usage:
#   bash scripts/file-lock.sh acquire <file-path> <holder-id> [timeout-s]
#   bash scripts/file-lock.sh release <file-path> <holder-id>
#   bash scripts/file-lock.sh holder  <file-path>
#
# Lock is implemented as an atomic-create symlink at <file-path>.lock pointing
# at "<holder-id>:<pid>:<hostname>". Atomic because `ln -s` fails if target
# exists.
#
# Stale-lock recovery: on a failed acquire, the script parses the existing
# symlink target. If it encodes a PID on the same hostname AND that PID is
# no longer alive (per `kill -0`), the stale lock is removed automatically
# and the acquire retries. This recovers cleanly from worker crashes.
#
# Cross-host locks (different hostname in the target) cannot be liveness-
# checked from this side; they wait out the timeout as before. That's the
# right default for central-server mode — assume remote holders are alive.
#
# Backward compatibility: legacy locks created by an older version of this
# script encoded only the bare holder ID (no colon). Such locks are treated
# as non-recoverable and wait the full timeout.
#
# Workers SHOULD call this before edit, MUST call it before edit if the manager
# explicitly assigned overlapping file scope. Default usage:
#
#   bash scripts/file-lock.sh acquire src/foo.ts engineer/worker-03 300 || exit 1
#   # do edits
#   bash scripts/file-lock.sh release src/foo.ts engineer/worker-03

CMD="${1:?cmd required: acquire|release|holder}"
PATH_ARG="${2:?path required}"
HOLDER="${3:-}"
TIMEOUT="${4:-300}"

LOCK="$PATH_ARG.lock"
SELF_HOST="$(hostname 2>/dev/null || echo local)"
# Encoded PID: prefer LOCK_PID if the caller passed one (most reliable),
# else default to PPID — the shell that invoked this script. That shell is
# the actual lock holder; this script exits after acquire returns. Using
# $$ here would encode the file-lock.sh process itself, which dies
# immediately and would be reaped on the very next acquire attempt.
# If PPID isn't available, fall back to $$ as a last resort.
SELF_PID="${LOCK_PID:-${PPID:-$$}}"

# Encode the lock target. Format: holder:pid:host
# Holder may not contain colons — strip them defensively.
encode_target() {
  local clean_holder="${HOLDER//:/_}"
  printf '%s:%s:%s' "$clean_holder" "$SELF_PID" "$SELF_HOST"
}

# Parse a lock target. On success exports: PARSED_HOLDER, PARSED_PID, PARSED_HOST.
# Returns 0 if the target is in the new format (with pid+host), 1 otherwise.
parse_target() {
  local target="$1"
  if [[ "$target" =~ ^([^:]+):([0-9]+):([^:]+)$ ]]; then
    PARSED_HOLDER="${BASH_REMATCH[1]}"
    PARSED_PID="${BASH_REMATCH[2]}"
    PARSED_HOST="${BASH_REMATCH[3]}"
    return 0
  fi
  # Legacy format — just a holder string.
  PARSED_HOLDER="$target"
  PARSED_PID=""
  PARSED_HOST=""
  return 1
}

# Check whether the lock at $LOCK is held by a process we can prove dead.
# Returns 0 (true) if the lock is stale and we removed it. Returns 1 otherwise.
try_reap_stale_lock() {
  local target
  target=$(readlink "$LOCK" 2>/dev/null) || return 1
  if ! parse_target "$target"; then
    # Legacy lock — no PID encoded, cannot prove staleness.
    return 1
  fi
  if [[ "$PARSED_HOST" != "$SELF_HOST" ]]; then
    # Remote host — we cannot check liveness from here.
    return 1
  fi
  if kill -0 "$PARSED_PID" 2>/dev/null; then
    # Holder is alive.
    return 1
  fi
  # Holder is dead AND on our host. Reap the stale lock. Use rm -f because
  # the symlink might have been removed by another waiter between our
  # readlink and now — that's fine, we just want it gone.
  rm -f "$LOCK" 2>/dev/null
  return 0
}

case "$CMD" in
  acquire)
    [[ -z "$HOLDER" ]] && { echo "FATAL: holder id required for acquire" >&2; exit 1; }
    started=$(date +%s)
    target=$(encode_target)
    while true; do
      if ln -s "$target" "$LOCK" 2>/dev/null; then
        echo "ACQUIRED $LOCK by $HOLDER (pid $SELF_PID host $SELF_HOST)"
        exit 0
      fi
      # Failed to acquire — try to reap if the holder is provably dead.
      if try_reap_stale_lock; then
        # Reaped. Loop and retry the ln -s on the next iteration; don't
        # report success yet because another waiter could beat us to it.
        continue
      fi
      now=$(date +%s)
      if (( now - started > TIMEOUT )); then
        existing=$(readlink "$LOCK" 2>/dev/null || echo unknown)
        echo "TIMEOUT after ${TIMEOUT}s waiting for $LOCK (held by $existing)" >&2
        exit 2
      fi
      sleep 1
    done
    ;;

  release)
    [[ -z "$HOLDER" ]] && { echo "FATAL: holder id required for release" >&2; exit 1; }
    if [[ ! -L "$LOCK" ]]; then
      echo "WARN: $LOCK not held; nothing to release" >&2
      exit 0
    fi
    held_target=$(readlink "$LOCK")
    parse_target "$held_target"
    if [[ "$PARSED_HOLDER" != "${HOLDER//:/_}" ]]; then
      echo "REFUSED: $LOCK held by $held_target, not $HOLDER" >&2
      exit 3
    fi
    rm "$LOCK"
    echo "RELEASED $LOCK"
    ;;

  holder)
    if [[ ! -L "$LOCK" ]]; then
      echo "(unheld)"
      exit 0
    fi
    target=$(readlink "$LOCK")
    if parse_target "$target"; then
      printf '%s (pid %s on %s)\n' "$PARSED_HOLDER" "$PARSED_PID" "$PARSED_HOST"
    else
      printf '%s (legacy format)\n' "$PARSED_HOLDER"
    fi
    ;;

  *)
    echo "Unknown command: $CMD" >&2
    exit 1
    ;;
esac

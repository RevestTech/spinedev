#!/usr/bin/env bash
# file-lock.sh — coarse file-level lock helper for engineer workers.
#
# Usage:
#   bash scripts/file-lock.sh acquire <file-path> <holder-id> [timeout-s]
#   bash scripts/file-lock.sh release <file-path> <holder-id>
#   bash scripts/file-lock.sh holder  <file-path>
#
# Lock is implemented as an atomic-create symlink at <file-path>.lock pointing
# at the holder-id. Atomic because `ln -s` fails if target exists.
#
# Workers SHOULD call this before edit, MUST call it before edit if the manager
# explicitly assigned overlapping file scope. Default usage is:
#
#   bash scripts/file-lock.sh acquire src/foo.ts engineer/worker-03 300 || exit 1
#   # do edits
#   bash scripts/file-lock.sh release src/foo.ts engineer/worker-03

CMD="${1:?cmd required: acquire|release|holder}"
PATH_ARG="${2:?path required}"
HOLDER="${3:-}"
TIMEOUT="${4:-300}"

LOCK="$PATH_ARG.lock"

case "$CMD" in
  acquire)
    [[ -z "$HOLDER" ]] && { echo "FATAL: holder id required for acquire" >&2; exit 1; }
    started=$(date +%s)
    while true; do
      if ln -s "$HOLDER" "$LOCK" 2>/dev/null; then
        echo "ACQUIRED $LOCK by $HOLDER"
        exit 0
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
    held_by=$(readlink "$LOCK")
    if [[ "$held_by" != "$HOLDER" ]]; then
      echo "REFUSED: $LOCK held by $held_by, not $HOLDER" >&2
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
    readlink "$LOCK"
    ;;

  *)
    echo "Unknown command: $CMD" >&2
    exit 1
    ;;
esac

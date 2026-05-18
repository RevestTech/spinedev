#!/usr/bin/env bash
# tools/verify-overrides/install.sh
#
# Symlinks the Spine-owned `docker-compose.override.yml` into `verify/` at
# runtime so it auto-merges with TRON's `docker-compose.yml` when compose is
# invoked from `verify/`.
#
# WHY THIS EXISTS (T4 / Wave 1):
# `verify/` is a TRON subtree (merged via `git subtree`). Any Spine-authored
# file living inside `verify/` causes merge conflicts on the next subtree
# pull. The override file (container renames + Spine port allocations) is
# Spine policy, not TRON code, so it must live outside `verify/`. We keep
# the canonical copy here in `tools/verify-overrides/` and materialize a
# symlink into `verify/docker-compose.override.yml` whenever the verify
# stack needs to come up.
#
# Idempotent: re-runs are safe. Refuses to clobber a non-symlink in case a
# user has hand-edited the destination — caller must remove it first.
#
# Usage:
#   bash tools/verify-overrides/install.sh             # install symlink
#   bash tools/verify-overrides/install.sh --uninstall # remove symlink
#   bash tools/verify-overrides/install.sh --check     # report status only

set -euo pipefail

# Resolve repo root from this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SRC="${REPO_ROOT}/tools/verify-overrides/docker-compose.override.yml"
DST="${REPO_ROOT}/verify/docker-compose.override.yml"
REL_SRC="../tools/verify-overrides/docker-compose.override.yml"

mode="install"
case "${1:-}" in
  --uninstall) mode="uninstall" ;;
  --check)     mode="check" ;;
  "" )         mode="install" ;;
  *)
    echo "usage: $0 [--uninstall|--check]" >&2
    exit 2
    ;;
esac

if [ ! -f "${SRC}" ]; then
  echo "ERROR: canonical override missing: ${SRC}" >&2
  exit 1
fi

if [ ! -d "${REPO_ROOT}/verify" ]; then
  echo "ERROR: verify/ subtree not present: ${REPO_ROOT}/verify" >&2
  exit 1
fi

case "${mode}" in
  check)
    if [ -L "${DST}" ]; then
      target="$(readlink "${DST}")"
      echo "symlink present: ${DST} -> ${target}"
      exit 0
    elif [ -e "${DST}" ]; then
      echo "WARNING: ${DST} exists and is NOT a symlink" >&2
      exit 1
    else
      echo "not installed: ${DST} (run without --check to install)"
      exit 1
    fi
    ;;

  uninstall)
    if [ -L "${DST}" ]; then
      rm "${DST}"
      echo "removed symlink: ${DST}"
    elif [ -e "${DST}" ]; then
      echo "REFUSING to remove ${DST}: not a symlink (hand-edited?)" >&2
      exit 1
    else
      echo "already absent: ${DST}"
    fi
    exit 0
    ;;

  install)
    if [ -L "${DST}" ]; then
      current="$(readlink "${DST}")"
      if [ "${current}" = "${REL_SRC}" ] || [ "${current}" = "${SRC}" ]; then
        echo "symlink already correct: ${DST} -> ${current}"
        exit 0
      fi
      echo "replacing stale symlink: ${DST} -> ${current}"
      rm "${DST}"
    elif [ -e "${DST}" ]; then
      echo "REFUSING to overwrite ${DST}: not a symlink." >&2
      echo "Remove it manually first (it may be a TRON subtree file or a hand-edit)." >&2
      exit 1
    fi

    # Use a relative symlink so the link works regardless of repo location.
    ln -s "${REL_SRC}" "${DST}"
    echo "installed: ${DST} -> ${REL_SRC}"
    exit 0
    ;;
esac

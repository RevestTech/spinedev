#!/usr/bin/env bash
# Pass L selftest: spin up a temp template git repo with two commits,
# point SPINE_UPDATE_TEMPLATE_DIR at it, run the updater for one tick in
# `pull-pin` mode with SPINE_DB_URL unset, and assert the local clone got
# fast-forwarded.
#
# The harness avoids any network by:
#   1. Creating a bare "origin" repo on disk.
#   2. Cloning it to TEMPLATE_DIR.
#   3. Committing two commits on the origin so a `git pull --ff-only`
#      will advance TEMPLATE_DIR's HEAD.
#   4. Running the updater in the background, sleeping briefly, then
#      killing it. SPINE_DB_URL is unset so pull-pin falls back to plain
#      `git pull --ff-only` on the clone.
#
# Pre-flight: requires `git` on PATH. Skips with success when git is missing.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v git >/dev/null 2>&1; then
  echo "SKIP: git not on PATH"
  exit 0
fi

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/spine-updater.XXXXXX")"
cleanup() { rm -rf "$ROOT" 2>/dev/null || true; }
trap cleanup EXIT

ORIGIN="$ROOT/origin.git"
TEMPLATE_DIR="$ROOT/template"
WORK="$ROOT/seed-work"

# Quiet git globally for the test so we don't print stray noise on FAIL.
export GIT_TERMINAL_PROMPT=0
git_q() { git "$@" >/dev/null 2>&1; }

# 1. Bare origin. Force main as the default branch so the clone after
#    push -u picks up a valid HEAD even on git versions that still
#    default to master.
git_q init -b main --bare "$ORIGIN" 2>/dev/null \
  || { git_q init --bare "$ORIGIN" && git_q -C "$ORIGIN" symbolic-ref HEAD refs/heads/main; }

# 2. Seed-work clone to build the initial history we'll push to origin.
git_q clone "$ORIGIN" "$WORK"
cd "$WORK"
git_q config user.email "test@spine.local"
git_q config user.name  "Spine Test"
git_q config commit.gpgsign false
echo "v1" > README.md
git_q add README.md
git_q -c init.defaultBranch=main commit -m "v1"
git_q branch -M main 2>/dev/null || true
git_q push -u origin main

# Make sure origin's HEAD points at main so cloning gives a valid checkout.
git_q -C "$ORIGIN" symbolic-ref HEAD refs/heads/main

# 3. Template clone (the directory updater.sh will run pull on).
git_q clone "$ORIGIN" "$TEMPLATE_DIR"
cd "$TEMPLATE_DIR"
git_q config user.email "test@spine.local"
git_q config user.name  "Spine Test"
INITIAL_SHA="$(git rev-parse HEAD)"

# 4. Push a second commit to origin so a `git pull --ff-only` will advance
#    the template clone.
cd "$WORK"
echo "v2" > README.md
git_q add README.md
git_q commit -m "v2"
git_q push origin main
NEW_SHA="$(git -C "$WORK" rev-parse origin/main)"

if [[ "$INITIAL_SHA" == "$NEW_SHA" ]]; then
  echo "FAIL: test setup did not advance origin" >&2
  exit 1
fi

# 5. Run updater for one tick.
#    * PARENT_PID unset (default 0) -> the parent-PID watch loop is
#      bypassed; we control the updater's lifetime by killing the
#      background process after it has had time to complete one
#      iteration (the pull, then sleep).
#    * INTERVAL_S=1 keeps the sleep short so we can reap quickly.
#    * SPINE_DB_URL unset -> pull-pin falls back to plain pull.
#    * cd to a dir where the .planning/orchestration path can be created
#      without polluting the repo.
unset SPINE_DB_URL
unset SPINE_UPDATE_PARENT_PID
export SPINE_UPDATE_TEMPLATE_DIR="$TEMPLATE_DIR"
export SPINE_UPDATE_MODE="pull-pin"
export SPINE_UPDATE_CHANNEL="stable"
export SPINE_UPDATE_INTERVAL_S=1

# Sandbox dir so the updater can create .planning/orchestration/agent-handoff/.
SANDBOX="$ROOT/sandbox"
mkdir -p "$SANDBOX"
cd "$SANDBOX"

# Run in background; poll for the template clone to advance to NEW_SHA
# rather than sleeping a fixed duration — keeps the test robust against
# slow sandboxes while still finishing quickly on fast ones.
# Wave 3 (Squad A): updater.sh migrated lib/ → shared/runtime/.
UPDATER_SH="$REPO/shared/runtime/updater.sh"
[[ -f "$UPDATER_SH" ]] || UPDATER_SH="$REPO/lib/updater.sh"
bash "$UPDATER_SH" >/dev/null 2>&1 &
upd_pid=$!

GOT_SHA=""
for _ in $(seq 1 30); do   # up to ~9 seconds (30 * 0.3s)
  GOT_SHA="$(git -C "$TEMPLATE_DIR" rev-parse HEAD 2>/dev/null)"
  if [[ "$GOT_SHA" == "$NEW_SHA" ]]; then break; fi
  sleep 0.3
done
# SIGKILL because the updater is in a sleep loop and we don't need a
# graceful shutdown for the test.
kill -9 "$upd_pid" 2>/dev/null || true
# Don't `wait` — it can hang if the process was already reaped or if
# any background grandchild kept the slot alive. The kill -9 is enough.

# Refresh GOT_SHA one more time in case the kill raced the final write.
GOT_SHA="$(git -C "$TEMPLATE_DIR" rev-parse HEAD 2>/dev/null)"
if [[ "$GOT_SHA" != "$NEW_SHA" ]]; then
  echo "FAIL: template did not fast-forward" >&2
  echo "  initial: $INITIAL_SHA" >&2
  echo "  origin head: $NEW_SHA" >&2
  echo "  template HEAD after updater: $GOT_SHA" >&2
  exit 1
fi

echo "test-updater-pin OK (advanced $INITIAL_SHA -> $GOT_SHA)"

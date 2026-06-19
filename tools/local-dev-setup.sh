#!/usr/bin/env bash
# local-dev-setup.sh — one-time local Spine dev setup (outside iCloud Drive).
#
# Why: repos under ~/Library/CloudStorage/... break Node (vite/vitest) with
# ERR_INVALID_MODULE_SPECIFIER. Use a plain local path like ~/dev/SpineDevelopment.
#
# Usage:
#   bash tools/local-dev-setup.sh              # from existing clone
#   bash tools/local-dev-setup.sh --from-icloud  # rsync iCloud → ~/dev first
set -euo pipefail

LOCAL_ROOT="${SPINE_LOCAL_ROOT:-${HOME}/dev/SpineDevelopment}"
ICLOUD_CANDIDATE="${HOME}/Projects/Apps/SpineDevelopment"
FROM_ICLOUD=0
SKIP_HUB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-icloud) FROM_ICLOUD=1; shift ;;
    --skip-hub) SKIP_HUB=1; shift ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ "${FROM_ICLOUD}" -eq 1 ]]; then
  SRC="${ICLOUD_CANDIDATE}"
  if [[ ! -d "${SRC}/.git" ]]; then
    echo "local-dev-setup: iCloud clone not found at ${SRC}" >&2
    exit 1
  fi
  echo "[local-dev-setup] rsync ${SRC} → ${LOCAL_ROOT}"
  mkdir -p "$(dirname "${LOCAL_ROOT}")"
  rsync -a \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.spine/work' \
    --exclude '.DS_Store' \
    "${SRC}/" "${LOCAL_ROOT}/"
fi

if [[ ! -d "${LOCAL_ROOT}/.git" ]]; then
  echo "local-dev-setup: clone or rsync repo to ${LOCAL_ROOT} first" >&2
  echo "  git clone git@github.com:RevestTech/spinedev.git ${LOCAL_ROOT}" >&2
  exit 1
fi

cd "${LOCAL_ROOT}"
echo "[local-dev-setup] working tree: $(pwd -P)"

echo "[local-dev-setup] python venv + requirements"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -r requirements.txt

echo "[local-dev-setup] hub SPA npm deps + build"
pushd shared/ui/spa >/dev/null
if [[ ! -d node_modules ]]; then
  npm ci --ignore-scripts
fi
PATH="$(pwd)/node_modules/.bin:${PATH}" SPA_BASE_PATH=/spa npm run build
popd >/dev/null

if [[ "${SKIP_HUB}" -eq 0 ]]; then
  echo "[local-dev-setup] docker disk check (need ~5GB free for Hub images)"
  df -h "${HOME}" | tail -1
  echo "[local-dev-setup] starting Hub (tools/hub-up.sh --rebuild if image missing)"
  if ! docker image inspect spine/hub:v3-dev >/dev/null 2>&1; then
    bash tools/hub-up.sh --rebuild
  else
    bash tools/hub-up.sh
  fi
  echo "[local-dev-setup] waiting for Hub health..."
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null http://localhost:8090/spa/ 2>/dev/null; then
      echo "[local-dev-setup] Hub OK: http://localhost:8090/spa/"
      break
    fi
    sleep 2
  done
fi

echo "[local-dev-setup] TRON alembic + smoke"
.venv/bin/python tools/_tron_alembic_upgrade.py
bash tools/smoke-test.sh --ci | tail -3

echo "[local-dev-setup] Harness Lite"
bash tools/harness/spine-harness init --project . --symlink-skills 2>/dev/null || true
bash tools/harness/spine-harness audit --project . --all >/dev/null || true
bash tools/harness/spine-harness verify --project . --run-qa || true

cat <<EOF

Done. Use this repo for daily dev:
  cd ${LOCAL_ROOT}

Hub SPA:  http://localhost:8090/spa/
Harness:  bash tools/harness/spine-harness status --markdown

Keep iCloud copy for sync/backup; run Docker/Node from ${LOCAL_ROOT} only.
EOF

#!/usr/bin/env bash
# tools/hub-up.sh — laptop-dev wrapper that brings up the Hub via
# docker compose with the right SPA build path for the host platform.
#
# On Linux + on customer-cloud CI, the in-Docker spa-builder stage builds
# the SPA without issue. On Docker Desktop for macOS (Apple Silicon),
# esbuild hits two upstream bugs (`lfstack.push` panic on slim images;
# `service was stopped` on full images) that we can't engineer around
# without esbuild fixes. This wrapper:
#
#   1. Detects Docker Desktop on macOS
#   2. If so, builds the SPA on the host first (`npm run build`) and
#      passes the resulting dist/ via buildx --build-context spa-dist=...
#   3. Otherwise builds normally inside Docker via the spa-builder stage
#
# Either way, the Hub image is tagged `spine/hub:v3-dev` so the docker
# compose `image:` directive picks it up.
#
# Usage:
#   bash tools/hub-up.sh                 # build + up -d
#   bash tools/hub-up.sh --rebuild       # force image rebuild
#   bash tools/hub-up.sh --down          # tear down + remove volumes
#   bash tools/hub-up.sh --status        # show container status
#
# LLM keys: if ANTHROPIC_API_KEY / OPENAI_API_KEY are unset or placeholders,
# hub-up pulls from local KMac Vault (kmac-vault on :9999) via
# tools/kmac-fetch-secret.sh. Override vault paths with
# SPINE_KMAC_ANTHROPIC_KEY / SPINE_KMAC_OPENAI_KEY. Explicit host env wins.

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

readonly COMPOSE_FILE="hub/docker-compose.yml"
readonly ENV_FILE="$(mktemp -t spine-hub-up.XXXXXX.env)"
readonly IMAGE_TAG="spine/hub:v3-dev"

# ---------------------------------------------------------------------------
# Projects output directory — where the engineer-generated files land on the
# host. User picks via SPINE_PROJECTS_DIR env. Persisted in ~/.spinerc so
# the choice survives shell reloads. Default: ~/spine-projects.
# ---------------------------------------------------------------------------
readonly SPINERC="${HOME}/.spinerc"

resolve_projects_dir() {
  if [[ -n "${SPINE_PROJECTS_DIR:-}" ]]; then
    # explicit env wins
    echo "${SPINE_PROJECTS_DIR}"
    return
  fi
  if [[ -f "${SPINERC}" ]]; then
    # shellcheck disable=SC1090
    source "${SPINERC}"
    if [[ -n "${SPINE_PROJECTS_DIR:-}" ]]; then
      echo "${SPINE_PROJECTS_DIR}"
      return
    fi
  fi
  echo "${HOME}/spine-projects"
}

readonly PROJECTS_DIR_HOST="$(resolve_projects_dir)"
mkdir -p "${PROJECTS_DIR_HOST}"
# Persist (lightly) so reopening a terminal still finds the same path.
if ! grep -qsF "SPINE_PROJECTS_DIR=" "${SPINERC}" 2>/dev/null; then
  printf '# spine-up persisted config\nSPINE_PROJECTS_DIR=%q\n' "${PROJECTS_DIR_HOST}" >> "${SPINERC}"
fi
echo "[hub-up] projects directory (host): ${PROJECTS_DIR_HOST}"

cleanup() { rm -f "${ENV_FILE}"; }
trap cleanup EXIT

# --- platform detection -----------------------------------------------------
host_needs_prebuilt_spa() {
  if [[ "$(uname -s)" == "Darwin" ]] && command -v docker >/dev/null \
     && docker version --format '{{.Server.Os}}' 2>/dev/null | grep -q '^linux$'; then
    # macOS host + Linux engine = Docker Desktop. Always pre-build to
    # dodge the esbuild bugs.
    return 0
  fi
  return 1
}

# --- KMac Vault LLM key resolution (dev laptop; per #9 no .env secrets) ------
readonly KMAC_FETCH="${REPO_ROOT}/tools/kmac-fetch-secret.sh"

_llm_key_is_placeholder() {
  local v="${1:-}"
  [[ -z "${v}" ]] && return 0
  case "${v}" in
    your-api-key-here|changeme|placeholder|sk-ant-api03-xxx|sk-ant-...)
      return 0
      ;;
  esac
  return 1
}

_kmac_fetch() {
  local vault_key="$1"
  if [[ ! -f "${KMAC_FETCH}" ]]; then
    return 1
  fi
  bash "${KMAC_FETCH}" "${vault_key}" 2>/dev/null
}

resolve_llm_keys_from_kmac() {
  local anthropic_key="${ANTHROPIC_API_KEY:-}"
  local openai_key="${OPENAI_API_KEY:-}"
  local fetched=""

  if _llm_key_is_placeholder "${anthropic_key}"; then
    fetched="$(_kmac_fetch "${SPINE_KMAC_ANTHROPIC_KEY:-tron:llm_anthropic_key}" || true)"
    if [[ -n "${fetched}" ]]; then
      export ANTHROPIC_API_KEY="${fetched}"
      echo "[hub-up] ANTHROPIC_API_KEY from KMac (${SPINE_KMAC_ANTHROPIC_KEY:-tron:llm_anthropic_key})"
    elif _llm_key_is_placeholder "${anthropic_key}"; then
      echo "[hub-up] WARN: no Anthropic key (export ANTHROPIC_API_KEY or start kmac-vault)" >&2
    fi
  fi

  if _llm_key_is_placeholder "${openai_key}"; then
    fetched="$(_kmac_fetch "${SPINE_KMAC_OPENAI_KEY:-tron:llm_openai_key}" || true)"
    if [[ -n "${fetched}" ]]; then
      export OPENAI_API_KEY="${fetched}"
      echo "[hub-up] OPENAI_API_KEY from KMac (${SPINE_KMAC_OPENAI_KEY:-tron:llm_openai_key})"
    fi
  fi
}

# --- write a smoke env-file (matches hub/tests/test-hub-up.sh pattern) ------
write_env_file() {
  resolve_llm_keys_from_kmac
  export SPINE_PROJECTS_DIR="${PROJECTS_DIR_HOST}"
  # shellcheck source=tools/_spine_hub_compose_env.sh
  source "${REPO_ROOT}/tools/_spine_hub_compose_env.sh"
  _spine_hub_compose_write_env "${ENV_FILE}"
}

# --- build SPA on host (when needed) ----------------------------------------
build_spa_on_host() {
  echo "[hub-up] Docker Desktop on macOS — building SPA on host to dodge esbuild bug"
  pushd shared/ui/spa >/dev/null
  if [[ ! -d node_modules ]]; then
    npm install --no-audit --no-fund
  fi
  # SPA_BASE_PATH must match the Hub's mount prefix (shared/api/app.py
  # serves the SPA at /spa/*). Without this, SvelteKit emits absolute
  # /_app/... asset URLs that 404 against the catch-all route.
  SPA_BASE_PATH=/spa npm run build
  popd >/dev/null
  if [[ ! -f shared/ui/spa/dist/index.html ]]; then
    echo "[hub-up] FATAL: SPA build did not produce dist/index.html" >&2
    exit 1
  fi
}

# --- build hub image --------------------------------------------------------
build_image() {
  if host_needs_prebuilt_spa; then
    build_spa_on_host
    echo "[hub-up] building image with host SPA via buildx --build-context"
    # --network=host: Docker Desktop bridge often cannot reach deb.debian.org
    # during apt-get in the runtime stage; host networking avoids flake.
    docker buildx build \
      --network=host \
      --build-context spa-dist=shared/ui/spa/dist \
      -t "${IMAGE_TAG}" \
      -f hub/Dockerfile \
      --load \
      .
  else
    echo "[hub-up] building image with in-Docker spa-builder stage"
    docker buildx build \
      --network=host \
      -t "${IMAGE_TAG}" \
      -f hub/Dockerfile \
      --load \
      .
  fi
}

# --- main -------------------------------------------------------------------
action="${1:-up}"
case "${action}" in
  --down|down)
    # Stop containers but preserve volumes — projects survive --down/--up.
    # Use --reset to wipe everything.
    write_env_file
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down
    ;;
  --status|status)
    docker ps --format '{{.Names}}\t{{.Status}}' | grep -E '^spine-hub' || true
    ;;
  --rebuild|rebuild)
    # NOTE: only stops + removes containers; volumes survive so projects
    # persist across image rebuilds. Use `--reset` if you actually want
    # to wipe the DB + start fresh.
    write_env_file
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down
    build_image
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d
    echo "[hub-up] Hub coming up — give it ~30s; then browse http://localhost:8090/spa/"
    ;;
  --reset|reset)
    write_env_file
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down -v
    build_image
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d
    echo "[hub-up] Hub coming up FRESH (volumes wiped) — ~30s; browse http://localhost:8090/spa/"
    ;;
  --up|up|"")
    write_env_file
    # Build only if image absent.
    if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
      build_image
    fi
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d
    echo "[hub-up] Hub coming up — give it ~30s; then browse http://localhost:8090/spa/"
    ;;
  -h|--help)
    sed -n '1,30p' "${BASH_SOURCE[0]}"
    ;;
  *)
    echo "[hub-up] unknown action: ${action} (try --help)" >&2
    exit 64
    ;;
esac

# syntax=docker/dockerfile:1.7
#
# Spine v3 — Hub container (Wave 3 Squad B)
#
# Decision drivers (per docs/V3_DESIGN_DECISIONS.md):
#   - #3  Hub = containerized product, primary management surface
#   - #14 ALL three segments share the SAME container; tier differs by license bundle
#   - #17 4 deployment shapes (laptop / BYOC / customer-cloud / on-prem) Day 1
#   - #25 Identity = Keycloak embedded by default
#   - #9  Vault-only secrets, no exceptions, no env:// fallback
#   - #18 Closed-source v1.0 — non-root + signed images are the trust mechanism
#   - #21 ALL-AI builds — image must be reproducible from a clean checkout by an AI agent
#
# Multi-arch:
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     --build-arg BUILDPLATFORM=linux/amd64 \
#     -t spine/hub:v3 -f hub/Dockerfile .
#
# NO secrets baked in. Runtime config comes from:
#   - vault   (via shared/secrets/, AppRole credentials passed by the operator)
#   - env     (NON-SECRET hints only — adapter name, hub_id, parent_hub URL)
#   - bundle  (signed YAML mounted at /etc/spine/bundle)
#
# Build context MUST be the repo root (we COPY shared/, plan/, build/, verify/,
# orchestrator/, devops/). The companion compose file sets this.

# --- Multi-arch build args ---------------------------------------------------
# BUILDPLATFORM is set automatically by buildx; ARG declarations make it
# available to the FROM line so we can build for amd64+arm64 from a single
# Dockerfile via `docker buildx build --platform=...`.
ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG PYTHON_VERSION=3.11

# --- Stage 1: builder (compiles wheels for the target arch) ------------------
# Using BUILDPLATFORM here ensures cross-arch builds compile native deps in a
# stage matched to the build host's architecture (faster), then the final
# stage uses TARGETPLATFORM-matched base image for runtime.
FROM --platform=${BUILDPLATFORM:-linux/amd64} python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build deps needed for asyncpg / cryptography / etc. wheels when prebuilt
# manylinux wheels are unavailable for the target arch.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels

# Dependency set documented in hub/README.md (we do NOT modify pyproject.toml
# per Wave 3 Squad B scope boundary). Pinned versions live in the README's
# "Runtime dependencies" table — bump them there and here together.
RUN pip wheel --wheel-dir /wheels \
        "fastapi==0.115.0" \
        "uvicorn[standard]==0.30.6" \
        "pydantic==2.9.2" \
        "asyncpg==0.29.0" \
        "httpx==0.27.2" \
        "PyYAML==6.0.2" \
        "PyJWT[crypto]==2.9.0" \
        "cryptography==43.0.1"

# --- Stage 1b: SPA builder (V3 Wave 3 part 2, Squad SPA1) -------------------
# Builds the SvelteKit Hub SPA → dist/ which the runtime stage copies into
# /app/static/spa/. shared/api/app.py:_mount_spa() serves that directory
# via FastAPI StaticFiles + a /spa/{path:path} catch-all. Node only lives
# in THIS stage so the runtime image stays a Python-only attack surface.
#
# Pin both Node + npm (corepack-managed) so the build is reproducible in
# CI / customer infra without surprises from rolling node:lts.
FROM --platform=${BUILDPLATFORM:-linux/amd64} node:20.18.0-slim AS spa-builder

ENV NODE_ENV=production \
    NPM_CONFIG_PROGRESS=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

WORKDIR /spa

# Copy manifest first so dep-install layer caches across source edits.
COPY shared/ui/spa/package.json shared/ui/spa/package-lock.json* ./
# package-lock.json is committed by Squad SPA1 once npm install is run
# locally; until then `npm install` falls back to the package.json pins.
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi

# Copy the rest of the SPA source + build.
COPY shared/ui/spa/ ./
RUN npm run build && ls -la dist/

# --- Stage 2: runtime --------------------------------------------------------
FROM --platform=${TARGETPLATFORM:-linux/amd64} python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="spine-hub" \
      org.opencontainers.image.description="Spine v3 Hub — containerized product (#3)" \
      org.opencontainers.image.source="https://github.com/spine-dev/spine" \
      org.opencontainers.image.licenses="Proprietary" \
      org.opencontainers.image.vendor="Spine" \
      spine.subsystem="hub" \
      spine.wave="3"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SPINE_HUB_PORT=8080 \
    SPINE_HUB_HOST=0.0.0.0 \
    SPINE_HUB_LOG_LEVEL=info \
    PATH="/usr/local/bin:/home/spine/.local/bin:${PATH}"

# Minimal runtime deps:
#   - libpq5 for asyncpg
#   - curl for healthcheck.sh
#   - tini for proper PID-1 signal handling under uvicorn workers
#   - jq for the entrypoint vault-bootstrap parser
#   - flyway needs java; we keep flyway OUT of this image and assume a
#     sibling `flyway` container in docker-compose.yml runs migrations.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
        tini \
        jq \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /sbin/nologin --uid 1000 spine \
 && mkdir -p /app /etc/spine /var/lib/spine \
 && chown -R spine:spine /app /etc/spine /var/lib/spine

# Install Python wheels from builder stage (no compilers in runtime image).
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl \
 && rm -rf /wheels

WORKDIR /app

# Copy Spine subsystem packages. Order is intentional: shared/ first (lowest
# coupling), then upper layers that depend on it. Each COPY narrows what we
# bring in — never copy the whole repo (would pull tests, docs, secrets).
#
# Per Wave 3 Squad B scope: we do NOT modify shared/ — we just include it as
# a Python package the Hub imports. Squad A extends shared/runtime/, Squad C
# extends shared/api/.
COPY --chown=spine:spine shared/       /app/shared/
COPY --chown=spine:spine plan/         /app/plan/
COPY --chown=spine:spine build/        /app/build/
COPY --chown=spine:spine verify/tron/  /app/verify/tron/
COPY --chown=spine:spine orchestrator/ /app/orchestrator/
COPY --chown=spine:spine devops/       /app/devops/

# Finally copy hub/ (this subsystem). Done last so most rebuilds during Hub
# development only invalidate this layer.
COPY --chown=spine:spine hub/          /app/hub/

# Hub SPA — copied from the dedicated spa-builder stage. shared/api/app.py
# resolves /app/static/spa by default (SPINE_SPA_DIST env override possible).
COPY --from=spa-builder --chown=spine:spine /spa/dist /app/static/spa

# Ensure the per-subsystem __init__.py marker is recognized by Python.
RUN find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Healthcheck: dedicated script so kubectl/podman/docker all see consistent
# behavior. /healthz comes from shared/api/app.py (DB ping + MCP registry).
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["/app/hub/healthcheck.sh"]

EXPOSE 8080

USER spine

# tini = PID 1 → reaps zombies + forwards SIGTERM cleanly to uvicorn workers.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/hub/entrypoint.sh"]
CMD ["serve"]

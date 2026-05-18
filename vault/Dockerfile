# syntax=docker/dockerfile:1.6
#
# Spine v3 — OpenBao server image
#
# Per V3_DESIGN_DECISIONS #9 (Vault-only secrets, OpenBao Day-0 default) and
# V3_BUILD_SEQUENCE Wave 0 (vault/ top-level subsystem). OpenBao is the upstream
# OSS fork of HashiCorp Vault and ships an official multi-arch image.
#
# Build (manual — Wave 0 does NOT actually build):
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t spine/vault:v3 -f vault/Dockerfile vault/
#
# NO secrets are baked into this image. All runtime config (cluster name,
# storage path, KMS unseal credentials) comes from env vars / mounted files.
# See vault/docker-compose.yml + vault/unseal/*.md for setup.

# --- Pinned upstream image ---------------------------------------------------
# OpenBao publishes signed multi-arch images at openbao/openbao. We pin the
# latest stable v2 minor at the time of Wave 0 (2026-05). If the registry
# coordinates change, see README.md "Image source switch (TODO)" for the
# documented fallback to hashicorp/vault:latest.
ARG OPENBAO_VERSION=2.1.1
FROM openbao/openbao:${OPENBAO_VERSION} AS base

# --- Metadata ----------------------------------------------------------------
LABEL org.opencontainers.image.title="Spine Vault (OpenBao)"
LABEL org.opencontainers.image.description="OpenBao secrets engine for Spine v3 (#9 Vault-only)"
LABEL org.opencontainers.image.source="https://github.com/spine-dev/spine"
LABEL org.opencontainers.image.licenses="MPL-2.0"
LABEL org.opencontainers.image.vendor="Spine"
LABEL spine.subsystem="vault"
LABEL spine.wave="0"

# --- Non-root user -----------------------------------------------------------
# OpenBao upstream already runs as user `openbao` (uid 100). We re-affirm here
# and ensure data + config dirs are owned by it. Never run as root in any
# deployment shape (#17).
USER root
RUN mkdir -p /openbao/data /openbao/config /openbao/policies /openbao/logs \
 && chown -R openbao:openbao /openbao

# --- Bundled Spine policies (non-secret HCL) ---------------------------------
# Policy files are PLAIN HCL — they grant capabilities on path patterns, they
# do not contain credentials. Safe to bake into the image.
COPY --chown=openbao:openbao policies/ /openbao/policies/

# --- Healthcheck -------------------------------------------------------------
# /v1/sys/health returns 200 unsealed+active, 429 standby, 472 DR secondary,
# 473 perf standby, 501 not initialized, 503 sealed. We accept ANY documented
# response as "the daemon is up"; sealed/uninit is an operator concern, not a
# container-restart concern.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O- "http://127.0.0.1:8200/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200" \
    >/dev/null 2>&1 || exit 1

# --- Runtime config ----------------------------------------------------------
# Bind 8200 (API) and 8201 (cluster). 8200 is what shared/secrets/ (Agent A's
# VaultAdapter) talks to.
EXPOSE 8200 8201

ENV BAO_ADDR=http://0.0.0.0:8200 \
    BAO_API_ADDR=http://0.0.0.0:8200 \
    BAO_CLUSTER_ADDR=http://0.0.0.0:8201 \
    BAO_LOG_LEVEL=info \
    BAO_LOG_FORMAT=json

USER openbao
WORKDIR /openbao

# Default to single-node file storage at /openbao/data. Production deployments
# (#17 customer-cloud / on-prem) MUST override the storage stanza by mounting
# a custom HCL config + setting BAO_LOCAL_CONFIG or passing -config=.
# A production Raft + KMS unseal HCL is in vault/unseal/kms-config-*.md.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["server"]

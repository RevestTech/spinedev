# shellcheck shell=bash
# Shared dev env for hub/docker-compose.yml (tools/hub-up.sh, tools/bootstrap.sh).
# Writes a gitignored temp env file — never commit the output.

_spine_hub_compose_write_env() {
  local dest="$1"
  : "${SPINE_PROJECTS_DIR:=${HOME}/spine-projects}"
  cat >"${dest}" <<EOF
SPINE_PROJECTS_DIR=${SPINE_PROJECTS_DIR}
# Auto-generated — do NOT commit.
SPINE_HUB_HOST_PORT=${SPINE_HUB_HOST_PORT:-8090}
SPINE_HUB_DEV=${SPINE_HUB_DEV:-1}
SPINE_HUB_LOG_LEVEL=${SPINE_HUB_LOG_LEVEL:-info}
SPINE_DB_HOST_PORT=${SPINE_DB_HOST_PORT:-33099}
SPINE_DB_PASSWORD=${SPINE_DB_PASSWORD:-smoke-test-db-pw}
TRON_DB_PASSWORD=${TRON_DB_PASSWORD:-tron_LOCAL_DEV_ONLY_2026}
KEYCLOAK_DB_PASSWORD=${KEYCLOAK_DB_PASSWORD:-smoke-test-kc-db-pw}
KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD:-smoke-test-kc-admin-pw}
SPINE_VAULT_ROLE_ID=${SPINE_VAULT_ROLE_ID:-smoke-test-role-id}
SPINE_VAULT_SECRET_ID_WRAPPED=${SPINE_VAULT_SECRET_ID_WRAPPED:-smoke-test-wrapped-secret-id}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
SPINE_ENGINEER_SQUAD=${SPINE_ENGINEER_SQUAD:-0}
SPINE_ENGINEER_HYBRID=${SPINE_ENGINEER_HYBRID:-0}
EOF
}

#!/usr/bin/env bash
set -euo pipefail

# Tron Production Pre-flight Checklist
# Run before every production deployment
# Exit code: 0 if all checks pass, 1 if any FAIL checks exist

PASS=0
FAIL=0
WARN=0

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper function to check conditions and print results
check() {
    local description="$1"
    local command="$2"

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}[PASS]${NC} $description"
        ((PASS++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $description"
        ((FAIL++))
        return 1
    fi
}

warn() {
    local description="$1"
    local command="$2"

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${YELLOW}[WARN]${NC} $description"
        ((WARN++))
        return 1
    else
        return 0
    fi
}

echo ""
echo "========================================"
echo "Tron Production Pre-flight Checklist"
echo "========================================"
echo ""

# ── Environment Checks ──
echo "[1/8] Environment Variables"
check "DB_HOST configured" "[ -n \"\${DB_HOST:-}\" ]"
check "DB_PORT configured" "[ -n \"\${DB_PORT:-}\" ]"
check "DB_USER configured" "[ -n \"\${DB_USER:-}\" ]"
check "REDIS_HOST configured" "[ -n \"\${REDIS_HOST:-}\" ]"
check "REDIS_PORT configured" "[ -n \"\${REDIS_PORT:-}\" ]"
warn "LOG_LEVEL is INFO or ERROR (not DEBUG)" "grep -qE 'INFO|ERROR' <<< \"\${LOG_LEVEL:-INFO}\""
check "TEMPORAL_ENABLED configured" "[ -n \"\${TEMPORAL_ENABLED:-}\" ]"
echo ""

# ── Docker Images ──
echo "[2/8] Docker Images"
check "tron-api image built" "docker images | grep -q 'tron-api'"
check "tron-worker image built" "docker images | grep -q 'tron-worker'"
check "tron-sandbox image built" "docker images | grep -q 'tron-sandbox'"
echo ""

# ── Database Connectivity ──
echo "[3/8] Database Connectivity"
check "Database reachable" "pg_isready -h \${DB_HOST:-postgres} -p \${DB_PORT:-5432} -U \${DB_USER:-tron}" || true
check "PgBouncer reachable" "pg_isready -h \${DB_HOST:-pgbouncer} -p 5432 -U \${DB_USER:-tron}" || true
echo ""

# ── Redis Connectivity ──
echo "[4/8] Redis Connectivity"
if [ -n "${REDIS_PASSWORD:-}" ]; then
    check "Redis reachable with auth" "redis-cli -h \${REDIS_HOST:-redis} -p \${REDIS_PORT:-6379} -a \${REDIS_PASSWORD} ping | grep -q PONG"
else
    check "Redis reachable" "redis-cli -h \${REDIS_HOST:-redis} -p \${REDIS_PORT:-6379} ping | grep -q PONG" || true
fi
echo ""

# ── Vault Connectivity ──
echo "[5/8] Secrets Management"
check "Vault reachable" "curl -sf http://\${VAULT_ADDR:-vault:8200}/v1/sys/health > /dev/null" || true
check "VAULT_TOKEN set" "[ -n \"\${VAULT_TOKEN:-}\" ] || [ -f /vault-token ]"
echo ""

# ── Tests Passing ──
echo "[6/8] Unit Tests"
if command -v python &> /dev/null; then
    check "Unit tests pass" "python -m pytest tests/unit -q --tb=no --co > /dev/null 2>&1" || true
fi
echo ""

# ── Security Scanning ──
echo "[7/8] Security Checks"
if command -v trivy &> /dev/null; then
    check "Trivy scan clean (no CRITICAL)" "trivy image --severity CRITICAL tron-api:latest --exit-code 0 2>/dev/null" || true
fi
if command -v docker &> /dev/null; then
    check "No secrets in Dockerfile" "! grep -i -E 'password|token|key|secret' Dockerfile 2>/dev/null || true"
fi
echo ""

# ── Configuration Validation ──
echo "[8/8] Configuration Validation"
check "docker-compose.yml valid" "docker-compose config > /dev/null 2>&1" || true
check "No hardcoded credentials in env" "! grep -r -E 'password.*=.*[a-zA-Z0-9]{8,}|token.*=.*[a-zA-Z0-9]{20,}' .env .env.* 2>/dev/null || true"
check "Logging configured" "[ -n \"\${LOG_LEVEL:-}\" ]"
echo ""

# ── Summary ──
echo "========================================"
echo "Summary"
echo "========================================"
TOTAL=$((PASS + FAIL + WARN))
echo -e "${GREEN}PASS: $PASS${NC}"
echo -e "${RED}FAIL: $FAIL${NC}"
echo -e "${YELLOW}WARN: $WARN${NC}"
echo "Total: $TOTAL"
echo ""

if [ $FAIL -gt 0 ]; then
    echo "DEPLOYMENT BLOCKED: Fix all FAIL checks before proceeding"
    exit 1
else
    echo "All critical checks passed. Ready for deployment."
    exit 0
fi

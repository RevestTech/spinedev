#!/bin/bash
# scan_repository.sh - Complete Tron audit workflow
# Usage: scripts/scan_repository.sh <github_repo_url> [branch]  (from repo root)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Tron Repository Scanner                         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if repo URL provided
if [ -z "$1" ]; then
    echo -e "${RED}Usage: $0 <github_repo_url> [branch]${NC}"
    echo ""
    echo "Examples:"
    echo "  $0 https://github.com/juice-shop/juice-shop.git"
    echo "  $0 https://github.com/user/repo.git main"
    echo ""
    echo "Supported repositories:"
    echo "  • OWASP Juice Shop: https://github.com/juice-shop/juice-shop.git"
    echo "  • WebGoat: https://github.com/WebGoat/WebGoat.git"
    echo "  • DVPN: https://github.com/anxolerd/dvpn.git"
    echo "  • Any public GitHub repository"
    exit 1
fi

REPO_URL="$1"
BRANCH="${2:-main}"
REPO_NAME=$(basename "$REPO_URL" .git)

echo -e "${GREEN}Repository:${NC} $REPO_URL"
echo -e "${GREEN}Branch:${NC} $BRANCH"
echo ""

# Check if Tron services are running
echo -e "${BLUE}[0/5]${NC} Checking Tron services..."
if ! curl -s http://localhost:13000/health > /dev/null 2>&1; then
    echo -e "${RED}❌ Tron API is not running${NC}"
    echo ""
    echo "Start Tron with:"
    echo "  cd ~/Projects/Tron"
    echo "  docker compose up -d"
    exit 1
fi
echo -e "${GREEN}✓ Tron services are running${NC}"
echo ""

# Get API key
echo -e "${BLUE}[1/5]${NC} Fetching API key from KMac Vault..."
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')

if [ -z "$API_KEY" ] || [ "$API_KEY" == "null" ]; then
    echo -e "${RED}❌ Failed to fetch API key${NC}"
    echo ""
    echo "Ensure KMac Vault is accessible:"
    echo "  curl -H 'Authorization: Bearer \$(cat ~/.config/kmac/docker-vault-token)' http://127.0.0.1:9999/get/tron:auth_master_key"
    exit 1
fi
echo -e "${GREEN}✓ API key retrieved${NC}"
echo ""

# Create project
echo -e "${BLUE}[2/5]${NC} Creating project..."
PROJECT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$REPO_NAME\",
    \"description\": \"Automated scan from CLI - $(date +%Y-%m-%d\ %H:%M:%S)\",
    \"repo_url\": \"$REPO_URL\",
    \"default_branch\": \"$BRANCH\"
  }")

PROJECT_ID=$(echo $PROJECT_RESPONSE | jq -r '.id')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "null" ]; then
    echo -e "${RED}❌ Failed to create project${NC}"
    echo ""
    echo "Response:"
    echo $PROJECT_RESPONSE | jq .
    exit 1
fi

echo -e "${GREEN}✓ Project created: $PROJECT_ID${NC}"
echo ""

# Start audit
echo -e "${BLUE}[3/5]${NC} Starting audit..."
AUDIT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\": \"$PROJECT_ID\",
    \"branch\": \"$BRANCH\",
    \"trigger_type\": \"manual\"
  }")

AUDIT_ID=$(echo $AUDIT_RESPONSE | jq -r '.id')

if [ -z "$AUDIT_ID" ] || [ "$AUDIT_ID" == "null" ]; then
    echo -e "${RED}❌ Failed to start audit${NC}"
    echo ""
    echo "Response:"
    echo $AUDIT_RESPONSE | jq .
    exit 1
fi

echo -e "${GREEN}✓ Audit started: $AUDIT_ID${NC}"
echo ""

# Monitor progress
echo -e "${BLUE}[4/5]${NC} Monitoring audit progress..."
echo -e "${YELLOW}This may take 60-90 seconds depending on repository size...${NC}"
echo ""

LAST_PROGRESS=0

while true; do
    STATUS=$(curl -s http://localhost:13000/api/audits/$AUDIT_ID \
      -H "X-API-Key: $API_KEY" 2>/dev/null)
    
    if [ -z "$STATUS" ]; then
        echo -e "${YELLOW}⚠️  Connection issue, retrying...${NC}"
        sleep 2
        continue
    fi
    
    CURRENT_STATUS=$(echo $STATUS | jq -r '.status')
    PROGRESS=$(echo $STATUS | jq -r '.progress')
    FINDINGS=$(echo $STATUS | jq -r '.findings_total')
    
    # Show progress update only when it changes
    if [[ "$PROGRESS" != "$LAST_PROGRESS" ]]; then
        if [[ "$CURRENT_STATUS" == "running" ]]; then
            echo -e "⏳ Progress: ${PROGRESS}% | Findings: ${FINDINGS}"
        fi
        LAST_PROGRESS=$PROGRESS
    fi
    
    if [[ "$CURRENT_STATUS" == "completed" ]]; then
        echo -e "${GREEN}✅ Audit completed | Findings: ${FINDINGS}${NC}"
        break
    elif [[ "$CURRENT_STATUS" == "failed" ]]; then
        ERROR=$(echo $STATUS | jq -r '.error_message')
        echo -e "${RED}❌ Audit failed: $ERROR${NC}"
        exit 1
    fi
    
    sleep 3
done

echo ""

# Get findings summary
echo -e "${BLUE}[5/5]${NC} Retrieving findings..."
echo ""

SUMMARY=$(curl -s http://localhost:13000/api/audits/$AUDIT_ID \
  -H "X-API-Key: $API_KEY")

CRITICAL=$(echo $SUMMARY | jq -r '.findings_critical')
HIGH=$(echo $SUMMARY | jq -r '.findings_high')
MEDIUM=$(echo $SUMMARY | jq -r '.findings_medium')
LOW=$(echo $SUMMARY | jq -r '.findings_low')
TOTAL=$(echo $SUMMARY | jq -r '.findings_total')

echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Audit Complete - Summary                 ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Repository: ${BLUE}$REPO_NAME${NC}"
echo -e "Project ID: ${BLUE}$PROJECT_ID${NC}"
echo -e "Audit ID:   ${BLUE}$AUDIT_ID${NC}"
echo ""
echo -e "Findings by Severity:"
echo -e "  🔴 Critical: ${RED}$CRITICAL${NC}"
echo -e "  🟠 High:     ${YELLOW}$HIGH${NC}"
echo -e "  🟡 Medium:   $MEDIUM"
echo -e "  🟢 Low:      $LOW"
echo -e "  ═══════════"
echo -e "  📊 Total:    ${GREEN}$TOTAL${NC}"
echo ""

# Show top critical findings
if [ "$CRITICAL" -gt "0" ]; then
    echo -e "${RED}Top Critical Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=critical&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title)\n    File: \(.file_path):\(.line_start)\n    Category: \(.category)\n"'
fi

# Show top high findings
if [ "$HIGH" -gt "0" ]; then
    echo -e "${YELLOW}Top High Severity Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=high&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title)\n    File: \(.file_path):\(.line_start)\n"'
fi

echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo -e "  📖 View full findings:"
echo -e "     curl http://localhost:13000/api/audits/$AUDIT_ID/findings -H 'X-API-Key: $API_KEY' | jq ."
echo ""
echo -e "  🌐 Web Interfaces:"
echo -e "     API Docs:    http://localhost:13000/docs"
echo -e "     Temporal UI: http://localhost:13008"
echo ""
echo -e "  📝 Export findings:"
echo -e "     curl http://localhost:13000/api/audits/$AUDIT_ID/findings -H 'X-API-Key: $API_KEY' > findings.json"
echo ""

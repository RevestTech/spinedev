#!/bin/bash
# scan_local_folder.sh - Scan a local project folder with Tron
# Usage: scripts/scan_local_folder.sh <path_to_folder> [project_name]  (from repo root)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Tron Local Folder Scanner                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Usage: $0 <path_to_folder> [project_name]${NC}"
    echo ""
    echo "Examples:"
    echo "  $0 /path/to/my-app"
    echo "  $0 ./my-project \"My Application\""
    echo "  $0 ~/code/webapp \"Production Web App\""
    echo ""
    exit 1
fi

SOURCE_DIR=$(cd "$1" && pwd)
PROJECT_NAME="${2:-$(basename "$SOURCE_DIR")}"

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}❌ Directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}Source Directory:${NC} $SOURCE_DIR"
echo -e "${GREEN}Project Name:${NC} $PROJECT_NAME"
echo ""

# Check if Tron is running
echo -e "${BLUE}[1/7]${NC} Checking Tron services..."
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
echo -e "${BLUE}[2/7]${NC} Fetching API key..."
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')

if [ -z "$API_KEY" ] || [ "$API_KEY" == "null" ]; then
    echo -e "${RED}❌ Failed to fetch API key${NC}"
    exit 1
fi
echo -e "${GREEN}✓ API key retrieved${NC}"
echo ""

# Create temporary git repo in the shared mount directory
# so the Docker container can access it via file:// URL
echo -e "${BLUE}[3/7]${NC} Creating temporary git repository..."
SCAN_DIR="/tmp/tron-scans"
mkdir -p "$SCAN_DIR"
TEMP_REPO="$SCAN_DIR/tron-scan-$(date +%s)"
mkdir -p "$TEMP_REPO"

# Copy files (respecting .gitignore if it exists)
if [ -f "$SOURCE_DIR/.gitignore" ]; then
    echo "Copying files (respecting .gitignore)..."
    rsync -av --exclude-from="$SOURCE_DIR/.gitignore" \
          --exclude='.git' \
          --exclude='node_modules' \
          --exclude='venv' \
          --exclude='.venv' \
          --exclude='venv-tmp' \
          --exclude='venv-tmp2' \
          --exclude='.venv-tmp' \
          --exclude='.venv-tmp2' \
          --exclude='.venv312' \
          --exclude='__pycache__' \
          --exclude='dist' \
          --exclude='build' \
          "$SOURCE_DIR/" "$TEMP_REPO/" > /dev/null 2>&1
else
    echo "Copying all files..."
    rsync -av --exclude='.git' \
          --exclude='node_modules' \
          --exclude='venv' \
          --exclude='.venv' \
          --exclude='venv-tmp' \
          --exclude='venv-tmp2' \
          --exclude='.venv-tmp' \
          --exclude='.venv-tmp2' \
          --exclude='.venv312' \
          --exclude='__pycache__' \
          --exclude='dist' \
          --exclude='build' \
          "$SOURCE_DIR/" "$TEMP_REPO/" > /dev/null 2>&1
fi

cd "$TEMP_REPO"

# Initialize git repo
git init > /dev/null 2>&1
git config user.email "tron-scanner@local.dev" > /dev/null 2>&1
git config user.name "Tron Scanner" > /dev/null 2>&1
git add . > /dev/null 2>&1
git commit -m "Tron local scan - $(date)" > /dev/null 2>&1

echo -e "${GREEN}✓ Temporary repo created: $TEMP_REPO${NC}"
echo ""

# Create bare repo (simulate remote)
echo -e "${BLUE}[4/7]${NC} Setting up scan repository..."
BARE_REPO="$SCAN_DIR/tron-scan-bare-$(date +%s).git"
git clone --bare "$TEMP_REPO" "$BARE_REPO" > /dev/null 2>&1

# Use file:// URL for the bare repo
REPO_URL="file://$BARE_REPO"
echo -e "${GREEN}✓ Scan repository ready${NC}"
echo ""

# Create project in Tron
echo -e "${BLUE}[5/7]${NC} Creating Tron project..."
PROJECT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$PROJECT_NAME\",
    \"description\": \"Local scan from: $SOURCE_DIR\",
    \"repo_url\": \"$REPO_URL\",
    \"default_branch\": \"master\"
  }")

PROJECT_ID=$(echo $PROJECT_RESPONSE | jq -r '.id')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "null" ]; then
    echo -e "${RED}❌ Failed to create project${NC}"
    echo $PROJECT_RESPONSE | jq .
    rm -rf "$TEMP_REPO" "$BARE_REPO"
    exit 1
fi

echo -e "${GREEN}✓ Project created: $PROJECT_ID${NC}"
echo ""

# Start audit
echo -e "${BLUE}[6/7]${NC} Starting audit..."
AUDIT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\": \"$PROJECT_ID\",
    \"branch\": \"master\",
    \"trigger_type\": \"manual\"
  }")

AUDIT_ID=$(echo $AUDIT_RESPONSE | jq -r '.id')

if [ -z "$AUDIT_ID" ] || [ "$AUDIT_ID" == "null" ]; then
    echo -e "${RED}❌ Failed to start audit${NC}"
    echo $AUDIT_RESPONSE | jq .
    rm -rf "$TEMP_REPO" "$BARE_REPO"
    exit 1
fi

echo -e "${GREEN}✓ Audit started: $AUDIT_ID${NC}"
echo ""

# Monitor progress
echo -e "${BLUE}[7/7]${NC} Monitoring audit progress..."
echo -e "${YELLOW}Analyzing your code (this may take 60-90 seconds)...${NC}"
echo ""

LAST_PROGRESS=0

while true; do
    STATUS=$(curl -s http://localhost:13000/api/audits/$AUDIT_ID \
      -H "X-API-Key: $API_KEY" 2>/dev/null)
    
    if [ -z "$STATUS" ]; then
        sleep 2
        continue
    fi
    
    CURRENT_STATUS=$(echo $STATUS | jq -r '.status')
    PROGRESS=$(echo $STATUS | jq -r '.progress')
    FINDINGS=$(echo $STATUS | jq -r '.findings_total')
    
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
        rm -rf "$TEMP_REPO" "$BARE_REPO"
        exit 1
    fi
    
    sleep 3
done

echo ""

# Get findings summary
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
echo -e "Project:    ${BLUE}$PROJECT_NAME${NC}"
echo -e "Source:     ${BLUE}$SOURCE_DIR${NC}"
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

# Show top findings
if [ "$CRITICAL" -gt "0" ]; then
    echo -e "${RED}Critical Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=critical&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title)\n    File: \(.file_path):\(.line_start)\n    Category: \(.category)\n"'
fi

if [ "$HIGH" -gt "0" ]; then
    echo -e "${YELLOW}High Severity Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=high&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title)\n    File: \(.file_path):\(.line_start)\n"'
fi

echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo -e "  📖 View all findings:"
echo -e "     curl http://localhost:13000/api/audits/$AUDIT_ID/findings -H 'X-API-Key: $API_KEY' | jq ."
echo ""
echo -e "  💾 Export to file:"
echo -e "     curl -s http://localhost:13000/api/audits/$AUDIT_ID/findings -H 'X-API-Key: $API_KEY' > findings.json"
echo ""
echo -e "  🌐 View in Temporal UI:"
echo -e "     open http://localhost:13008"
echo ""

# Cleanup
echo -e "${BLUE}Cleaning up temporary files...${NC}"
rm -rf "$TEMP_REPO" "$BARE_REPO"
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

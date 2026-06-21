# How to Run Tron Against Another Application

**Complete guide for scanning any GitHub repository with Tron**

---

## Quick Start (5 Minutes)

### Prerequisites

1. **Tron services running:**
   ```bash
   cd ~/Projects/Tron
   docker compose ps
   # Should show: tron-api, postgres, redis, temporal, tron-worker all "Up (healthy)"
   ```

2. **Get your API key:**
   ```bash
   # Fetch master API key from KMac Vault
   export API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
     http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')
   
   echo "API Key: $API_KEY"
   ```

### Step 1: Create a Project

A "project" in Tron represents a codebase you want to analyze. It requires:
- **name**: Display name (required)
- **repo_url**: GitHub repository URL (required for real scanning)
- **default_branch**: Branch to scan (default: "main")
- **description**: Optional description

**Example: Scan OWASP Juice Shop (vulnerable web app)**

```bash
# Create project pointing to Juice Shop repo
PROJECT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OWASP Juice Shop",
    "description": "Intentionally insecure web application for security testing",
    "repo_url": "https://github.com/juice-shop/juice-shop.git",
    "default_branch": "master"
  }')

# Extract project ID
PROJECT_ID=$(echo $PROJECT_RESPONSE | jq -r '.id')
echo "Project created with ID: $PROJECT_ID"

# View project details
echo $PROJECT_RESPONSE | jq .
```

**Example Output:**
```json
{
  "id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a",
  "name": "OWASP Juice Shop",
  "description": "Intentionally insecure web application for security testing",
  "repo_url": "https://github.com/juice-shop/juice-shop.git",
  "default_branch": "master",
  "status": "active",
  "created_at": "2026-04-12T20:15:30.123456Z",
  "updated_at": "2026-04-12T20:15:30.123456Z"
}
```

### Step 2: Start an Audit

Once you have a project, trigger an audit:

```bash
# Create audit run
AUDIT_RESPONSE=$(curl -s -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\": \"$PROJECT_ID\",
    \"branch\": \"master\",
    \"trigger_type\": \"manual\"
  }")

# Extract audit ID
AUDIT_ID=$(echo $AUDIT_RESPONSE | jq -r '.id')
echo "Audit started with ID: $AUDIT_ID"

# View audit details
echo $AUDIT_RESPONSE | jq .
```

**Example Output:**
```json
{
  "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "project_id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a",
  "status": "queued",
  "progress": 0,
  "findings_total": 0,
  "findings_critical": 0,
  "findings_high": 0,
  "findings_medium": 0,
  "findings_low": 0,
  "started_at": "2026-04-12T20:16:45.678901Z",
  "completed_at": null,
  "error_message": null,
  "created_at": "2026-04-12T20:16:45.678901Z"
}
```

### Step 3: Monitor Progress

**Option A: Polling (Simple)**

```bash
# Check audit status every 5 seconds
while true; do
  STATUS=$(curl -s http://localhost:13000/api/audits/$AUDIT_ID \
    -H "X-API-Key: $API_KEY")
  
  CURRENT_STATUS=$(echo $STATUS | jq -r '.status')
  PROGRESS=$(echo $STATUS | jq -r '.progress')
  FINDINGS=$(echo $STATUS | jq -r '.findings_total')
  
  echo "$(date +%H:%M:%S) - Status: $CURRENT_STATUS | Progress: $PROGRESS% | Findings: $FINDINGS"
  
  # Exit when completed or failed
  if [[ "$CURRENT_STATUS" == "completed" ]] || [[ "$CURRENT_STATUS" == "failed" ]]; then
    break
  fi
  
  sleep 5
done
```

**Option B: WebSocket (Real-time)**

Create `monitor_audit.py`:

```python
#!/usr/bin/env python3
import asyncio
import websockets
import json
import sys

async def monitor_audit(audit_id, api_key):
    uri = f"ws://localhost:13000/ws/audits/{audit_id}?token={api_key}"
    
    print(f"📡 Connecting to audit: {audit_id}")
    
    async with websockets.connect(uri) as ws:
        print("✅ Connected! Listening for events...\n")
        
        while True:
            try:
                message = await ws.recv()
                data = json.loads(message)
                event = data.get('event')
                payload = data.get('data', {})
                
                if event == 'snapshot':
                    print(f"📸 Initial Status: {payload.get('status')}")
                    print(f"   Progress: {payload.get('progress')}%")
                    
                elif event == 'progress_update':
                    print(f"⏳ Progress: {payload.get('progress')}%")
                    
                elif event == 'agent_started':
                    agent = payload.get('agent_id', 'unknown')
                    print(f"🤖 Agent Started: {agent}")
                    
                elif event == 'finding_discovered':
                    severity = payload.get('severity', 'unknown')
                    title = payload.get('title', 'Unknown')
                    file_path = payload.get('file_path', '')
                    print(f"🔍 Finding: [{severity.upper()}] {title}")
                    print(f"   File: {file_path}")
                    
                elif event == 'audit_completed':
                    total = payload.get('findings_total', 0)
                    print(f"\n✅ Audit Complete!")
                    print(f"   Total Findings: {total}")
                    break
                    
                elif event == 'audit_failed':
                    error = payload.get('error_message', 'Unknown error')
                    print(f"\n❌ Audit Failed: {error}")
                    break
                    
                elif event == 'close':
                    print("\n👋 Connection closed")
                    break
                    
            except websockets.ConnectionClosed:
                print("\n⚠️  Connection closed")
                break

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: scripts/monitor_audit.py <audit_id> <api_key>")
        sys.exit(1)
    
    audit_id = sys.argv[1]
    api_key = sys.argv[2]
    
    asyncio.run(monitor_audit(audit_id, api_key))
```

Run it:
```bash
chmod +x monitor_audit.py
scripts/monitor_audit.py $AUDIT_ID $API_KEY
```

### Step 4: Retrieve Findings

Once audit completes:

```bash
# Get all findings
curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?limit=100" \
  -H "X-API-Key: $API_KEY" | jq .

# Filter by severity
curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=critical&limit=20" \
  -H "X-API-Key: $API_KEY" | jq .

# Get finding summary
curl -s "http://localhost:13000/api/audits/$AUDIT_ID" \
  -H "X-API-Key: $API_KEY" | jq '{
    status: .status,
    total: .findings_total,
    critical: .findings_critical,
    high: .findings_high,
    medium: .findings_medium,
    low: .findings_low
  }'
```

**Example Finding:**
```json
{
  "id": "f1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
  "audit_run_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "project_id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a",
  "fingerprint": "sha256:abc123...",
  "rule_id": "security/sql-injection",
  "file_path": "routes/login.js",
  "line_start": 42,
  "line_end": 45,
  "severity": "critical",
  "category": "injection",
  "title": "SQL Injection Vulnerability in User Login",
  "description": "Direct concatenation of user input into SQL query without sanitization. Attacker can inject arbitrary SQL commands.",
  "suggested_fix": "Use parameterized queries or ORM methods. Replace: `SELECT * FROM users WHERE username='${input}'` with prepared statements.",
  "status": "open",
  "code_snippet": "const query = `SELECT * FROM users WHERE username='${req.body.username}'`;",
  "created_at": "2026-04-12T20:17:30.123456Z"
}
```

---

## Complete Workflow Example

Here's a full script you can run:

```bash
#!/bin/bash
# scan_repository.sh - Complete Tron audit workflow

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
    exit 1
fi

REPO_URL="$1"
BRANCH="${2:-main}"
REPO_NAME=$(basename "$REPO_URL" .git)

echo -e "${GREEN}Repository:${NC} $REPO_URL"
echo -e "${GREEN}Branch:${NC} $BRANCH"
echo ""

# Get API key
echo -e "${BLUE}[1/5]${NC} Fetching API key from KMac Vault..."
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')

if [ -z "$API_KEY" ] || [ "$API_KEY" == "null" ]; then
    echo -e "${RED}❌ Failed to fetch API key${NC}"
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
    \"description\": \"Automated scan from CLI\",
    \"repo_url\": \"$REPO_URL\",
    \"default_branch\": \"$BRANCH\"
  }")

PROJECT_ID=$(echo $PROJECT_RESPONSE | jq -r '.id')

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" == "null" ]; then
    echo -e "${RED}❌ Failed to create project${NC}"
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
    echo $AUDIT_RESPONSE | jq .
    exit 1
fi

echo -e "${GREEN}✓ Audit started: $AUDIT_ID${NC}"
echo ""

# Monitor progress
echo -e "${BLUE}[4/5]${NC} Monitoring audit progress..."
echo ""

while true; do
    STATUS=$(curl -s http://localhost:13000/api/audits/$AUDIT_ID \
      -H "X-API-Key: $API_KEY")
    
    CURRENT_STATUS=$(echo $STATUS | jq -r '.status')
    PROGRESS=$(echo $STATUS | jq -r '.progress')
    FINDINGS=$(echo $STATUS | jq -r '.findings_total')
    
    if [[ "$CURRENT_STATUS" == "running" ]]; then
        echo -e "⏳ Status: ${YELLOW}$CURRENT_STATUS${NC} | Progress: ${PROGRESS}% | Findings: ${FINDINGS}"
    elif [[ "$CURRENT_STATUS" == "completed" ]]; then
        echo -e "✅ Status: ${GREEN}$CURRENT_STATUS${NC} | Findings: ${FINDINGS}"
        break
    elif [[ "$CURRENT_STATUS" == "failed" ]]; then
        ERROR=$(echo $STATUS | jq -r '.error_message')
        echo -e "${RED}❌ Audit failed: $ERROR${NC}"
        exit 1
    else
        echo -e "📋 Status: $CURRENT_STATUS"
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

# Show top 5 critical findings
if [ "$CRITICAL" -gt "0" ]; then
    echo -e "${RED}Top Critical Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=critical&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title) (\(.file_path):\(.line_start))"'
    echo ""
fi

# Show top 5 high findings
if [ "$HIGH" -gt "0" ]; then
    echo -e "${YELLOW}Top High Severity Findings:${NC}"
    curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=high&limit=5" \
      -H "X-API-Key: $API_KEY" | jq -r '.items[] | "  • \(.title) (\(.file_path):\(.line_start))"'
    echo ""
fi

echo -e "${GREEN}View full report:${NC}"
echo -e "  API Docs:    http://localhost:13000/docs"
echo -e "  Temporal UI: http://localhost:13008"
echo -e "  Get findings: curl http://localhost:13000/api/audits/$AUDIT_ID/findings -H 'X-API-Key: $API_KEY'"
echo ""
```

Save as `scan_repository.sh` and run:

```bash
chmod +x scan_repository.sh
scripts/scan_repository.sh https://github.com/juice-shop/juice-shop.git master
```

---

## Supported Repository Types

### ✅ Public Repositories (No Authentication)

Tron can scan any public GitHub repository directly:

```bash
# OWASP vulnerable web apps
https://github.com/juice-shop/juice-shop.git
https://github.com/WebGoat/WebGoat.git
https://github.com/anxolerd/dvpn.git

# Popular open source projects
https://github.com/django/django.git
https://github.com/pallets/flask.git
https://github.com/fastapi/fastapi.git
https://github.com/nodejs/node.git
https://github.com/kubernetes/kubernetes.git
```

### 🔐 Private Repositories (Coming Soon)

Private repository support requires authentication configuration:

1. **GitHub Personal Access Token (PAT)**
2. **SSH Key Authentication**
3. **GitHub App Integration**

For current capabilities and backlog, see **`docs/BLUEPRINT.md`**, **`docs/project/TRD.md`**, and **`docs/project/MASTER_PROPOSAL_TODO.md`** (historical phased plan: **`docs/archive/project-journals/IMPLEMENTATION_BLUEPRINT.md`**).

### 📂 Local Repositories (Alternative)

If you have local code you want to scan:

**Option 1: Push to private GitHub repo, then scan**

**Option 2: Use demo mode (no repo_url)**
```bash
# Create project without repo_url - uses demo vulnerable code
curl -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Project",
    "description": "Uses built-in vulnerable code for testing"
  }'
```

---

## What Gets Analyzed

### Repository Cloning

- **Method**: Shallow clone (`git clone --depth 1`)
- **Timeout**: 120 seconds
- **Size Limit**: Repos up to ~500MB (configurable)
- **.gitignore**: Automatically respected

### File Filtering

**Included Files** (up to 500 files, 20MB total):

- **Source Code**: `.py`, `.js`, `.ts`, `.java`, `.go`, `.rb`, `.php`, `.c`, `.cpp`, `.rs`, `.swift`, `.kt`
- **Configuration**: `.yml`, `.json`, `.toml`, `.ini`, `.env.example`, `Dockerfile`, `.tf`
- **Web**: `.html`, `.css`, `.scss`, `.jsx`, `.tsx`, `.vue`
- **Shell**: `.sh`, `.bash`, `.zsh`
- **SQL**: `.sql`

**Excluded** (automatically skipped):

- **Dependencies**: `node_modules/`, `vendor/`, `.venv/`, `venv/`
- **Build Output**: `dist/`, `build/`, `target/`, `out/`
- **Binary Files**: `.exe`, `.dll`, `.so`, `.pyc`, `.class`, `.jar`
- **Media**: `.png`, `.jpg`, `.mp4`, `.pdf`
- **Lock Files**: `package-lock.json`, `yarn.lock`, `Pipfile.lock`
- **Large Files**: Individual files >512KB

### Analysis Performed

**1. Static Analysis (Deterministic)**
- **Bandit**: Python security scanning (100+ tests)
- **Semgrep**: Multi-language SAST (OWASP Top 10)

**2. AI Agent Analysis (3 Agents in Parallel)**
- **SecurityISO**: Vulnerabilities, auth issues, crypto problems
- **BuilderISO**: Dockerfile security, dependency vulnerabilities
- **PerformanceISO**: N+1 queries, blocking I/O, resource leaks

**3. Verification & Validation**
- Schema validation (file exists, code matches)
- Cross-validation for critical findings
- Deduplication by fingerprint

---

## Understanding Results

### Finding Severity Levels

| Severity | Description | Example |
|----------|-------------|---------|
| **Critical** | Immediate security risk, easily exploitable | SQL injection, hardcoded admin credentials |
| **High** | Significant security issue, requires fix | XSS vulnerability, insecure crypto usage |
| **Medium** | Potential security concern, should fix | Missing input validation, weak password policy |
| **Low** | Minor issue or best practice violation | Unused imports, TODO comments in security code |

### Finding Categories

- **injection**: SQL injection, command injection, XSS
- **authentication**: Auth bypass, weak passwords, missing 2FA
- **authorization**: IDOR, privilege escalation, missing access controls
- **cryptography**: Weak crypto, hardcoded keys, insecure algorithms
- **configuration**: Insecure defaults, debug mode enabled, exposed secrets
- **dependencies**: Vulnerable packages, outdated libraries
- **performance**: N+1 queries, memory leaks, blocking operations

### Confidence Scoring

- **0.9-1.0**: Very high confidence (verified by multiple methods)
- **0.7-0.9**: High confidence (confirmed by static analysis + LLM)
- **0.5-0.7**: Medium confidence (LLM analysis only)
- **<0.5**: Low confidence (flagged for manual review)

---

## Advanced Usage

### Custom Branch Scanning

```bash
# Scan specific branch
curl -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\": \"$PROJECT_ID\",
    \"branch\": \"develop\",
    \"trigger_type\": \"manual\"
  }"
```

### Comparing Branches

```bash
# Scan main branch
MAIN_AUDIT=$(curl -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"branch\": \"main\"}")

# Scan feature branch
FEATURE_AUDIT=$(curl -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"branch\": \"feature/new-auth\"}")

# Compare findings (manual diff)
```

### Filtering Findings

```bash
# Get only critical findings
curl "http://localhost:13000/api/audits/$AUDIT_ID/findings?severity=critical" \
  -H "X-API-Key: $API_KEY"

# Get findings in specific file
curl "http://localhost:13000/api/audits/$AUDIT_ID/findings" \
  -H "X-API-Key: $API_KEY" | jq '.items[] | select(.file_path | contains("auth"))'

# Get SQL injection findings
curl "http://localhost:13000/api/audits/$AUDIT_ID/findings" \
  -H "X-API-Key: $API_KEY" | jq '.items[] | select(.category == "injection")'
```

### Monitoring via Temporal UI

```bash
# Open Temporal UI to see workflow execution graph
open http://localhost:13008

# Navigate to:
# - Workflows > Search for audit ID
# - View execution timeline
# - See activity results
# - Check for failures/retries
```

---

## Troubleshooting

### Problem: "Project not found"

**Cause**: Project ID is invalid or was deleted

**Solution**:
```bash
# List all projects
curl http://localhost:13000/api/projects -H "X-API-Key: $API_KEY" | jq '.items'

# Use correct project ID
```

### Problem: "Clone failed (exit 128)"

**Cause**: Repository is private or doesn't exist

**Solutions**:
1. Verify URL is correct and repository is public
2. Check network connectivity: `git clone <url> /tmp/test`
3. For private repos, wait for authentication support (Phase 2)

### Problem: Audit stuck in "queued"

**Cause**: Worker not running or Temporal connection issue

**Solutions**:
```bash
# Check worker status
docker compose logs tron-worker --tail=50

# Check Temporal connection
docker compose exec temporal tctl cluster health

# Restart worker
docker compose restart tron-worker
```

### Problem: "No findings" on vulnerable code

**Cause**: Repository may have no analyzable files, or agents filtered it out

**Solutions**:
1. Check file types in repository (must be in ANALYZABLE_EXTENSIONS)
2. Verify repository isn't mostly binary/media files
3. Check audit logs: `docker compose logs tron-api --tail=100`

### Problem: "429 Too Many Requests" from OpenAI

**Cause**: Rate limiting during cross-validation

**Solution**: This is non-blocking. Audit completes without cross-validation. Consider:
- Upgrading OpenAI API tier
- Disabling cross-validation for non-critical findings
- Using only Anthropic (no cross-validation)

---

## Cost Estimation

### Per-Audit Costs

| Component | Cost | Notes |
|-----------|------|-------|
| Repository clone | $0 | Git is free |
| Static analysis (Bandit/Semgrep) | $0 | Free tools |
| LLM analysis (Claude 3 Haiku) | ~$0.0015 | ~12K tokens @ $0.25/$1.25 per 1M |
| Cross-validation (OpenAI GPT-4o) | ~$0.0005 | Optional, critical only |
| Infrastructure | ~$0.0001 | Amortized |
| **Total** | **~$0.002** | Per audit |

### Monthly Estimates

| Scenario | Audits/Month | Monthly Cost |
|----------|--------------|--------------|
| Small team | 100 | ~$0.20 + $90 infra = **$90** |
| Medium team | 1,000 | ~$2 + $90 infra = **$92** |
| Large team | 10,000 | ~$20 + $180 infra = **$200** |

---

## Next Steps

1. **Scan your first repository**: Use the quick start above
2. **Review findings**: Understand severity and categories
3. **Integrate into CI/CD**: See `docs/operations/RUNBOOKS.md`
4. **Monitor via Temporal**: Track workflow execution in real-time
5. **Export results**: Use API to export findings to your tools

For detailed architecture and implementation details, see:
- **Full Documentation**: http://localhost:8080
- **API Reference**: http://localhost:13000/docs
- **Architecture Docs**: `docs/architecture/`
- **Workflow Details**: `TEMPORAL_DEPLOYMENT_COMPLETE.md`

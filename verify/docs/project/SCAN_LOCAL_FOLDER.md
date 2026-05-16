# Scanning Local Folders with Tron

**Guide for running Tron against local projects on your filesystem**

---

## Quick Start

### Scan Any Local Folder

```bash
# Scan a local project
scripts/scan_local_folder.sh /path/to/your/project

# With custom project name
scripts/scan_local_folder.sh /path/to/your/project "My Application"

# Examples
scripts/scan_local_folder.sh ~/code/my-webapp "Production Web App"
scripts/scan_local_folder.sh ./my-api-server
scripts/scan_local_folder.sh /Users/me/projects/backend "Backend API v2"
```

**What it does:**
1. ✅ Creates temporary Git repository from your folder
2. ✅ Respects your `.gitignore` (if present)
3. ✅ Excludes common build artifacts automatically
4. ✅ Scans with full Tron pipeline (3 agents)
5. ✅ Shows real-time progress
6. ✅ Displays findings by severity
7. ✅ Cleans up temporary files automatically

---

## How It Works

### Step-by-Step Process

1. **Validation**
   - Checks if Tron services are running
   - Verifies source directory exists
   - Fetches API key from KMac Vault

2. **Repository Creation**
   - Copies your project to `/tmp/tron-scan-*`
   - Respects `.gitignore` patterns
   - Excludes: `node_modules/`, `venv/`, `dist/`, `build/`, `.git/`
   - Initializes Git repo
   - Creates bare clone (simulates remote)

3. **Tron Scan**
   - Creates project in Tron database
   - Starts audit with `file://` URL
   - Monitors progress in real-time
   - Retrieves findings

4. **Cleanup**
   - Removes temporary repositories
   - Keeps results in Tron database
   - No trace left on filesystem

---

## Example Output

```bash
$ scripts/scan_local_folder.sh ~/code/my-webapp "My Web App"

╔════════════════════════════════════════════════════════╗
║       Tron Local Folder Scanner                       ║
╚════════════════════════════════════════════════════════╝

Source Directory: /Users/me/code/my-webapp
Project Name: My Web App

[1/7] Checking Tron services...
✓ Tron services are running

[2/7] Fetching API key...
✓ API key retrieved

[3/7] Creating temporary git repository...
Copying files (respecting .gitignore)...
✓ Temporary repo created: /tmp/tron-scan-1713000000

[4/7] Setting up scan repository...
✓ Scan repository ready

[5/7] Creating Tron project...
✓ Project created: d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a

[6/7] Starting audit...
✓ Audit started: a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d

[7/7] Monitoring audit progress...
Analyzing your code (this may take 60-90 seconds)...

⏳ Progress: 20% | Findings: 2
⏳ Progress: 50% | Findings: 8
⏳ Progress: 85% | Findings: 15
✅ Audit completed | Findings: 18

╔════════════════════════════════════════════════════════╗
║              Audit Complete - Summary                 ║
╚════════════════════════════════════════════════════════╝

Project:    My Web App
Source:     /Users/me/code/my-webapp
Project ID: d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a
Audit ID:   a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d

Findings by Severity:
  🔴 Critical: 3
  🟠 High:     7
  🟡 Medium:   6
  🟢 Low:      2
  ═══════════
  📊 Total:    18

Critical Findings:
  • SQL Injection in User Query Handler
    File: src/api/users.js:42
    Category: injection
    
  • Hardcoded Database Password
    File: config/database.js:8
    Category: cryptography
    
  • Authentication Bypass Vulnerability
    File: middleware/auth.js:25
    Category: authentication

High Severity Findings:
  • XSS Vulnerability in Comment Rendering
    File: components/Comment.jsx:18
  • Missing CSRF Protection
    File: routes/api.js:35

Next Steps:
  📖 View all findings:
     curl http://localhost:13000/api/audits/a1b2c3d4.../findings -H 'X-API-Key: ...' | jq .
     
  💾 Export to file:
     curl -s http://localhost:13000/api/audits/a1b2c3d4.../findings -H 'X-API-Key: ...' > findings.json
     
  🌐 View in Temporal UI:
     open http://localhost:13008

Cleaning up temporary files...
✓ Cleanup complete
```

---

## What Gets Scanned

### ✅ Included Files

**Source Code:**
- Python: `.py`, `.pyi`
- JavaScript/TypeScript: `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`
- Java: `.java`, `.kt`, `.scala`
- Go: `.go`
- Rust: `.rs`
- C/C++: `.c`, `.cpp`, `.h`, `.hpp`
- C#: `.cs`
- Ruby: `.rb`, `.erb`
- PHP: `.php`
- Swift: `.swift`, `.m`
- Shell: `.sh`, `.bash`, `.zsh`

**Configuration:**
- `.yml`, `.yaml`, `.json`, `.toml`, `.ini`, `.cfg`
- `Dockerfile`, `docker-compose.yml`
- `.env.example`, `.env.sample`
- Terraform: `.tf`, `.hcl`

**Web:**
- `.html`, `.css`, `.scss`, `.less`
- `.sql`, `.xml`, `.proto`

### ❌ Automatically Excluded

**Dependencies (always skipped):**
- `node_modules/`
- `vendor/`
- `.venv/`, `venv/`, `env/`
- `__pycache__/`

**Build Output:**
- `dist/`, `build/`, `target/`, `out/`
- `.next/`, `.nuxt/`

**Version Control:**
- `.git/`, `.svn/`, `.hg/`

**Binary/Media:**
- `.exe`, `.dll`, `.so`, `.pyc`, `.class`, `.jar`
- `.png`, `.jpg`, `.mp4`, `.pdf`

**Lock Files:**
- `package-lock.json`, `yarn.lock`, `Pipfile.lock`

### 📏 Size Limits

- **Per file**: 512 KB max
- **Total scan**: 20 MB max
- **File count**: 500 files max

---

## Advanced Usage

### Use Your `.gitignore`

If your project has a `.gitignore`, the script automatically respects it:

```bash
# Your .gitignore
node_modules/
dist/
.env
*.log

# These will be excluded from scan
scripts/scan_local_folder.sh ./my-project
```

### Scan Specific Subdirectories

```bash
# Scan only backend code
scripts/scan_local_folder.sh ./my-monorepo/backend "Backend Only"

# Scan specific service
scripts/scan_local_folder.sh ./microservices/auth-service "Auth Service"

# Scan frontend
scripts/scan_local_folder.sh ./web/frontend "Frontend App"
```

### Monitor with WebSocket

```bash
# Start scan
scripts/scan_local_folder.sh ./my-project

# In another terminal, monitor real-time
# (Use the audit ID from scan output)
scripts/monitor_audit.py <audit-id> <api-key>
```

### Compare Scans Over Time

```bash
# Scan before changes
scripts/scan_local_folder.sh ./my-app "My App - Before Refactor"
# Note the audit ID

# Make changes to code
vim ./my-app/src/security.js

# Scan after changes
scripts/scan_local_folder.sh ./my-app "My App - After Refactor"
# Note the new audit ID

# Compare findings
curl http://localhost:13000/api/audits/<before-id>/findings -H "X-API-Key: $API_KEY" > before.json
curl http://localhost:13000/api/audits/<after-id>/findings -H "X-API-Key: $API_KEY" > after.json
diff before.json after.json
```

---

## Integration with Development Workflow

### Pre-Commit Hook

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Run Tron scan before commit

echo "Running Tron security scan..."
~/Projects/Tron/scripts/scan_local_folder.sh . "Pre-commit Scan"

# Get last audit findings
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')

CRITICAL=$(curl -s http://localhost:13000/api/audits?limit=1 -H "X-API-Key: $API_KEY" | \
  jq -r '.items[0].findings_critical')

if [ "$CRITICAL" -gt "0" ]; then
    echo "❌ Commit blocked: $CRITICAL critical findings detected"
    echo "Run: curl http://localhost:13000/api/audits/\$(latest_id)/findings -H 'X-API-Key: $API_KEY'"
    exit 1
fi

echo "✅ No critical findings, proceeding with commit"
```

### CI/CD Integration

**GitHub Actions:**

```yaml
name: Tron Security Scan

on: [push, pull_request]

jobs:
  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Run Tron Scan
        run: |
          # Start Tron services (assume Docker)
          docker compose up -d
          
          # Wait for services
          sleep 30
          
          # Run scan
          scripts/scan_local_folder.sh . "CI Scan - ${{ github.sha }}"
          
          # Check for critical findings
          CRITICAL=$(curl -s http://localhost:13000/api/audits?limit=1 \
            -H "X-API-Key: ${{ secrets.TRON_API_KEY }}" | \
            jq -r '.items[0].findings_critical')
          
          if [ "$CRITICAL" -gt "0" ]; then
            echo "::error::$CRITICAL critical security findings"
            exit 1
          fi
```

### VS Code Task

Add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Tron Security Scan",
      "type": "shell",
      "command": "~/Projects/Tron/scripts/scan_local_folder.sh ${workspaceFolder} '${workspaceFolderBasename}'",
      "problemMatcher": [],
      "group": {
        "kind": "test",
        "isDefault": true
      }
    }
  ]
}
```

Then run: `Cmd+Shift+P` → "Tasks: Run Task" → "Tron Security Scan"

---

## Troubleshooting

### Problem: "Directory not found"

**Cause:** Path doesn't exist or has typo

**Solution:**
```bash
# Use absolute path
scripts/scan_local_folder.sh $(pwd)/my-project

# Or relative to current directory
cd /path/to/projects
scripts/scan_local_folder.sh ./my-project
```

### Problem: "Tron API is not running"

**Cause:** Docker services not started

**Solution:**
```bash
cd ~/Projects/Tron
docker compose up -d
docker compose ps  # Verify all services are "Up (healthy)"
```

### Problem: "No findings" on code with issues

**Possible causes:**
1. Project only contains excluded file types
2. All files filtered by `.gitignore`
3. Project is very small

**Solution:**
```bash
# Check what files would be scanned
cd /path/to/your/project
find . -name "*.py" -o -name "*.js" -o -name "*.ts" | \
  grep -v node_modules | grep -v venv | head -20

# If no files match, your project may not have scannable code
```

### Problem: Scan takes too long

**Cause:** Large project with many files

**Solution:**
```bash
# Scan specific subdirectory instead
scripts/scan_local_folder.sh ./my-project/src "Source Code Only"

# Or add more exclusions to .gitignore
echo "tests/" >> .gitignore
echo "docs/" >> .gitignore
```

### Problem: "Failed to create project"

**Cause:** API authentication or database issue

**Solution:**
```bash
# Test API connection
curl http://localhost:13000/health

# Test API key
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')
echo "API Key: $API_KEY"

# Check API logs
docker compose logs tron-api --tail=50
```

---

## Security & Privacy

### What Happens to Your Code?

1. **Temporary Copy**: Code copied to `/tmp/tron-scan-*`
2. **Local Processing**: All analysis happens on your machine
3. **LLM Calls**: Code snippets sent to Anthropic/OpenAI for analysis
4. **Storage**: Findings stored in local PostgreSQL database
5. **Cleanup**: Temporary files deleted after scan

### Data Retention

- **Temporary repos**: Deleted immediately after scan
- **Findings**: Stored in PostgreSQL until you delete the project
- **LLM providers**: May retain data per their policies

### Best Practices

**Don't scan sensitive files:**
- Add to `.gitignore`: `.env`, `secrets.json`, `*.pem`, `*.key`
- Tron respects `.gitignore` automatically

**For proprietary code:**
- Self-host LLM models (Ollama support coming)
- Use air-gapped deployment
- Review findings before sharing

---

## Limitations

### Current Limitations

1. **No incremental scanning**: Each scan is full project
2. **No blame information**: Can't show who introduced issues
3. **No fix application**: Findings are informational only
4. **LLM dependency**: Requires internet for Anthropic/OpenAI

### Workarounds

**For large projects:**
- Scan subdirectories individually
- Use `.gitignore` to exclude non-critical paths

**For offline use:**
- Static analysis (Bandit/Semgrep) works offline
- LLM analysis requires internet (Ollama support coming)

**For private code:**
- All processing local except LLM calls
- Consider self-hosted LLM option (roadmap)

---

## Next Steps

1. **Scan your first project:**
   ```bash
   scripts/scan_local_folder.sh ~/code/my-app
   ```

2. **View detailed findings:**
   ```bash
   curl http://localhost:13000/api/audits/<audit-id>/findings \
     -H "X-API-Key: $API_KEY" | jq . > findings.json
   ```

3. **Integrate into workflow:**
   - Add pre-commit hook
   - Configure CI/CD
   - Set up VS Code task

4. **Monitor in Temporal:**
   ```bash
   open http://localhost:13008
   ```

For more details, see:
- **Full documentation**: http://localhost:8080
- **API reference**: http://localhost:13000/docs
- **GitHub scanning**: `scripts/scan_repository.sh --help`

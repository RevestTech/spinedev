# Monday Morning: Complete Layer 3

**Goal:** Finish Layer 3 execution verification (4-5 hours)  
**Status:** Scaffold complete, integration pending

---

## Quick Commands

### 1. Start Sandbox Service (30 min)

```bash
cd ~/Projects/Tron

# Build sandbox image
docker compose build tron-sandbox

# Start service
docker compose up -d tron-sandbox

# Verify it's running
docker compose ps tron-sandbox
docker compose logs tron-sandbox | tail -20

# Should see: "Sandbox service ready on port 50051"
```

### 2. Create Sandbox Client (2 hours)

Create `tron/services/sandbox_client.py`:

```python
"""Sandbox Client - Execute code safely in Docker containers."""

import docker
import asyncio
from typing import Dict

class SandboxClient:
    """Client for running code in isolated Docker containers"""
    
    def __init__(self):
        self.docker_client = docker.from_env()
    
    async def run_python(
        self,
        script: str,
        timeout: int = 10,
        network_mode: str = "none"
    ) -> Dict:
        """Execute Python script in sandbox."""
        try:
            container = self.docker_client.containers.run(
                image="python:3.11-slim",
                command=["python", "-c", script],
                network_mode=network_mode,
                mem_limit="128m",
                cpu_quota=50000,
                detach=True,
                remove=True
            )
            
            result = container.wait(timeout=timeout)
            logs = container.logs().decode("utf-8")
            
            return {
                "exit_code": result["StatusCode"],
                "output": logs,
                "error": None
            }
        except Exception as e:
            return {
                "exit_code": -1,
                "output": "",
                "error": str(e)
            }
```

### 3. Enable Full Verification (1 hour)

In `tron/workflows/activities.py`, find `verify_findings_with_sandbox()` and:

1. Import SandboxClient:
   ```python
   from tron.services.sandbox_client import SandboxClient
   ```

2. Replace the placeholder code with the commented implementation

3. Initialize sandbox client:
   ```python
   sandbox_client = SandboxClient()
   verifier = ExecutionVerifier(
       sandbox_client=sandbox_client,
       logger=activity.logger
   )
   ```

### 4. Test End-to-End (1 hour)

```bash
# Run test audit
API_KEY=$(curl -s -H "Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)" \
  http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')

# Create test project
PROJECT_ID=$(curl -s -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Layer 3 Test",
    "repo_url": "https://github.com/juice-shop/juice-shop.git",
    "default_branch": "master"
  }' | jq -r '.id')

# Run audit
AUDIT_ID=$(curl -s -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\"}" | jq -r '.id')

# Watch Layer 3 logs
docker compose logs -f tron-worker | grep "Layer 3"

# Check results (after ~60s)
curl -s "http://localhost:13000/api/audits/$AUDIT_ID" \
  -H "X-API-Key: $API_KEY" | jq '{
    status,
    findings_total,
    findings_critical,
    findings_high
  }'

# Check verified findings
curl -s "http://localhost:13000/api/audits/$AUDIT_ID/findings" \
  -H "X-API-Key: $API_KEY" | \
  jq '.items[] | select(.sandbox_verified == true) | {
    category,
    severity,
    confidence,
    sandbox_verified
  }'
```

---

## Expected Results

### Before Layer 3 (Current)
- **Findings:** 14 (includes false positives)
- **Verified:** 0 (no sandbox testing)

### After Layer 3 (Tomorrow EOD)
- **Findings:** 8-10 (4-6 false positives rejected)
- **Verified:** 2-4 critical/high findings
- **Logs show:**
  ```
  Layer 3: Verifying hardcoded_secrets in .github/FUNDING.yml:2
  Layer 3: Secret test REJECTED - key invalid (false positive)
  Layer 3: Verifying hardcoded_secrets in config/jwt.yml:5
  Layer 3: Secret test VERIFIED - token valid (+0.15 confidence)
  Layer 3 complete: 2 verified, 4 rejected, 3 unverified, 5 skipped
  ```

---

## Troubleshooting

### Issue: Sandbox service won't start
```bash
# Check logs
docker compose logs tron-sandbox

# Common fixes:
docker compose down
docker compose up -d --build tron-sandbox
```

### Issue: "Cannot connect to Docker daemon"
```bash
# Verify Docker socket mounted
docker compose config | grep docker.sock
# Should see: /var/run/docker.sock:/var/run/docker.sock
```

### Issue: Verification timeout
```python
# In execution_verifier.py, increase timeout:
result = await self._execute_in_sandbox(
    script=test_script,
    timeout=30,  # Was 10
    network_mode="restricted"
)
```

---

## Success Checklist

- [ ] Sandbox service running (`docker compose ps` shows healthy)
- [ ] SandboxClient module created
- [ ] Full verification logic enabled (no placeholder)
- [ ] Test audit completes successfully
- [ ] Logs show Layer 3 verification attempts
- [ ] Some findings marked as `sandbox_verified: true`
- [ ] False positives rejected (findings_total reduced)
- [ ] No workflow errors

---

## If You Get Stuck

**Skip sandbox for now, continue to Week 2:**

The Layer 3 scaffold is complete and the workflow won't break. If sandbox integration takes longer than expected, you can:

1. Keep the placeholder (all findings marked "skipped")
2. Move to Layers 5-6 (standards + calibration)
3. Come back to Layer 3 in Week 3

**The architecture is sound - you can build in any order.**

---

## Files to Work On Tomorrow

1. `tron/services/sandbox_client.py` - **CREATE**
2. `tron/workflows/activities.py` - **MODIFY** (uncomment verification code)
3. `docker-compose.yml` - **VERIFY** (sandbox service defined)

---

**Total time: 4-5 hours**  
**Outcome: Layer 3 operational, precision +10-15%**  

Let's do this! 🚀

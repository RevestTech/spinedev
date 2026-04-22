# Tron Build Completion Plan

**Goal:** Complete the 7-layer verification pipeline and remaining ISO agents  
**Start Date:** April 13, 2026  
**Target:** 100% accurate findings, zero hallucinations

---

## Current State

### Working ✅
- AUDIT mode operational
- 3 agents active (Security, Builder, Performance)
- Layers 1-2 working (Deterministic tools, Schema validation)
- Layer 4 partial (Cross-validation implemented but rate-limited)
- FastAPI + Temporal + PostgreSQL + Redis
- WebSocket streaming
- Basic frontend

### Missing ❌
- Layer 3: Execution verification (sandbox integration)
- Layer 5: Blueprint-scoped tasks (standards hierarchy)
- Layer 6: Calibrated confidence (golden test suite)
- Layer 7: Prompt regression testing
- QAISO agent (commented out)
- Memory agent (defined but unused)
- PLAN, BUILD, FIX modes (not started)

---

## Build Order: Priority Sequence

### Phase 1: Complete Verification Pipeline (Weeks 1-3)
**Goal:** Get to 98% precision with all 7 layers working

### Phase 2: Activate All Agents (Week 4)
**Goal:** 5 ISO agents operational

### Phase 3: Clean Up Infrastructure (Week 5)
**Goal:** All services healthy and utilized

### Phase 4: Additional Modes (Weeks 6-10)
**Goal:** PLAN, BUILD, FIX modes operational

---

## Phase 1: Complete 7-Layer Verification Pipeline

### Week 1: Layer 3 - Execution Verification

**What it does:** Run exploits in sandbox to verify findings are real

**Implementation:**

1. **Fix tron-sandbox service**
   ```yaml
   # docker-compose.yml
   tron-sandbox:
     build: docker/Dockerfile.sandbox
     networks:
       - tron-network
     security_opt:
       - no-new-privileges:true
     cap_drop:
       - ALL
     read_only: true
     tmpfs:
       - /tmp:size=100M,mode=1777
     cpus: 0.5
     mem_limit: 512m
   ```

2. **Create sandbox integration module**
   ```python
   # tron/verification/execution_verifier.py
   
   class ExecutionVerifier:
       """Layer 3: Verify findings by executing exploits in sandbox"""
       
       async def verify_finding(self, finding: Finding) -> VerificationResult:
           """
           Attempts to exploit the vulnerability in isolated sandbox.
           Returns: verified, unverified, or rejected
           """
           if finding.category == "hardcoded_secrets":
               return await self._verify_secret(finding)
           elif finding.category == "sql_injection":
               return await self._verify_sql_injection(finding)
           elif finding.category == "command_injection":
               return await self._verify_command_injection(finding)
           else:
               return VerificationResult(status="unverified", reason="no_test")
       
       async def _verify_secret(self, finding: Finding) -> VerificationResult:
           """Test if secret is valid by attempting to use it"""
           secret = finding.code_snippet
           
           # Run in sandbox
           test_script = f"""
           import requests
           try:
               # Attempt to use secret
               response = requests.get(
                   'https://api.example.com/test',
                   headers={{'Authorization': f'Bearer {secret}'}}
               )
               if response.status_code == 200:
                   exit(0)  # Secret works - TRUE POSITIVE
               else:
                   exit(1)  # Secret doesn't work - DOWNGRADE
           except:
               exit(2)  # Can't test - UNVERIFIED
           """
           
           result = await self.sandbox_executor.run(
               script=test_script,
               timeout=10,
               network_mode="restricted"
           )
           
           if result.exit_code == 0:
               return VerificationResult(
                   status="verified",
                   method="execution_test",
                   confidence_boost=0.15
               )
           elif result.exit_code == 1:
               return VerificationResult(
                   status="rejected",
                   reason="secret_invalid",
                   confidence_penalty=-0.3
               )
           else:
               return VerificationResult(
                   status="unverified",
                   reason="test_failed"
               )
   ```

3. **Integrate with workflow**
   ```python
   # tron/workflows/activities/audit_activities.py
   
   @activity.defn
   async def verify_findings_execution(findings: list[Finding]) -> list[Finding]:
       """Layer 3: Execute verification tests in sandbox"""
       verifier = ExecutionVerifier(sandbox_client=docker_client)
       
       verified_findings = []
       for finding in findings:
           if finding.severity in ["critical", "high"]:
               # Verify critical/high findings
               result = await verifier.verify_finding(finding)
               
               if result.status == "verified":
                   finding.verified = True
                   finding.confidence += result.confidence_boost
               elif result.status == "rejected":
                   # False positive detected - skip
                   continue
               else:
                   finding.verified = False
           
           verified_findings.append(finding)
       
       return verified_findings
   ```

4. **Update audit workflow**
   ```python
   # tron/workflows/audit_workflow.py
   
   @workflow.defn
   class AuditWorkflow:
       @workflow.run
       async def run(self, audit_run_id: str) -> AuditResult:
           # ... existing code ...
           
           # Layer 1-2: Existing
           findings = await workflow.execute_activity(
               run_agents,
               audit_run_id,
               start_to_close_timeout=timedelta(minutes=10)
           )
           
           # Layer 3: NEW - Execution verification
           findings = await workflow.execute_activity(
               verify_findings_execution,
               findings,
               start_to_close_timeout=timedelta(minutes=5)
           )
           
           # Layer 4: Cross-validation (existing)
           findings = await workflow.execute_activity(
               cross_validate_findings,
               findings,
               start_to_close_timeout=timedelta(minutes=5)
           )
           
           # Continue...
   ```

**Deliverable:** Layer 3 operational, reduces false positives by 10-15%

---

### Week 2: Layers 5-6 - Blueprint Scoping & Calibration

#### Layer 5: Blueprint-Scoped Tasks

**What it does:** Filter findings by project standards and quality gates

**Implementation:**

1. **Standards loader**
   ```python
   # tron/services/standards_loader.py
   
   class StandardsLoader:
       """Load and merge standards hierarchy"""
       
       async def load_effective_standards(
           self,
           project_id: str
       ) -> EffectiveStandards:
           """
           Loads: Default → Company → Project
           Returns merged standards with precedence
           """
           # Load from database
           default = await self._load_default_standards()
           company = await self._load_company_standards(project_id)
           project = await self._load_project_standards(project_id)
           
           # Merge with precedence (project > company > default)
           return self._merge_standards([default, company, project])
   ```

2. **Quality gate evaluator**
   ```python
   # tron/verification/quality_gate_evaluator.py
   
   class QualityGateEvaluator:
       """Layer 5: Filter findings by quality gates"""
       
       async def filter_by_gates(
           self,
           findings: list[Finding],
           standards: EffectiveStandards
       ) -> list[Finding]:
           """
           Filter findings based on project quality gates
           Examples:
           - Ignore test files if gate says "test_coverage_optional"
           - Downgrade severities based on project context
           - Skip findings for excluded paths
           """
           filtered = []
           
           for finding in findings:
               # Check if finding is in scope
               if self._is_in_scope(finding, standards):
                   # Apply severity adjustments
                   finding = self._adjust_severity(finding, standards)
                   filtered.append(finding)
           
           return filtered
   ```

#### Layer 6: Calibrated Confidence

**What it does:** Ensure confidence scores match actual accuracy

**Implementation:**

1. **Golden test suite database**
   ```sql
   -- tron/database/migrations/add_golden_suite.sql
   
   CREATE TABLE golden_test_cases (
       id UUID PRIMARY KEY,
       test_name VARCHAR(255) NOT NULL,
       category VARCHAR(100) NOT NULL,
       file_content TEXT NOT NULL,
       expected_findings JSONB NOT NULL,
       severity VARCHAR(50) NOT NULL,
       true_positive BOOLEAN NOT NULL,
       created_at TIMESTAMP DEFAULT NOW()
   );
   
   CREATE TABLE confidence_calibration_metrics (
       id UUID PRIMARY KEY,
       confidence_band VARCHAR(20) NOT NULL,  -- e.g. "0.85-0.95"
       total_cases INT NOT NULL,
       correct_predictions INT NOT NULL,
       accuracy FLOAT NOT NULL,
       last_updated TIMESTAMP DEFAULT NOW()
   );
   ```

2. **Calibration engine**
   ```python
   # tron/verification/confidence_calibrator.py
   
   class ConfidenceCalibrator:
       """Layer 6: Calibrate confidence scores"""
       
       async def calibrate_findings(
           self,
           findings: list[Finding]
       ) -> list[Finding]:
           """
           Adjust confidence scores based on historical accuracy
           """
           calibration_metrics = await self._load_calibration_metrics()
           
           for finding in findings:
               band = self._get_confidence_band(finding.confidence)
               metric = calibration_metrics.get(band)
               
               if metric and metric.total_cases >= 50:
                   # Adjust confidence to match actual accuracy
                   finding.confidence = metric.accuracy
                   finding.calibration_applied = True
           
           return findings
       
       async def update_calibration(self, ground_truth: list[GroundTruth]):
           """Update calibration metrics with verified results"""
           for truth in ground_truth:
               band = self._get_confidence_band(truth.stated_confidence)
               await self._update_band_metric(
                   band=band,
                   correct=truth.actual_outcome == truth.predicted_outcome
               )
   ```

**Deliverable:** Layers 5-6 operational, confidence scores trustworthy

---

### Week 3: Layer 7 - Prompt Regression Testing

**What it does:** Detect when prompts degrade over time

**Implementation:**

1. **Regression test suite**
   ```python
   # tron/verification/prompt_regression_tester.py
   
   class PromptRegressionTester:
       """Layer 7: Detect prompt degradation"""
       
       async def run_regression_suite(
           self,
           agent_name: str
       ) -> RegressionReport:
           """
           Run agent against known test cases
           Compare to baseline results
           """
           test_cases = await self._load_regression_suite(agent_name)
           baseline = await self._load_baseline_results(agent_name)
           
           current_results = []
           for case in test_cases:
               result = await self._run_agent_on_case(agent_name, case)
               current_results.append(result)
           
           # Compare to baseline
           drift_score = self._calculate_drift(baseline, current_results)
           
           if drift_score > 0.05:  # 5% drift threshold
               await self._alert_prompt_degradation(agent_name, drift_score)
           
           return RegressionReport(
               agent=agent_name,
               drift_score=drift_score,
               passed=drift_score <= 0.05
           )
   ```

2. **Automated regression testing**
   ```python
   # tron/workflows/regression_workflow.py
   
   @workflow.defn
   class RegressionTestWorkflow:
       """Run nightly regression tests"""
       
       @workflow.run
       async def run(self) -> RegressionReport:
           """Test all agents against regression suite"""
           agents = ["SecurityISO", "BuilderISO", "PerformanceISO", "QAISO"]
           
           reports = []
           for agent in agents:
               report = await workflow.execute_activity(
                   run_regression_suite,
                   agent,
                   start_to_close_timeout=timedelta(minutes=30)
               )
               reports.append(report)
           
           # Alert if any agent has >5% drift
           failing_agents = [r for r in reports if not r.passed]
           if failing_agents:
               await workflow.execute_activity(
                   send_drift_alert,
                   failing_agents
               )
           
           return RegressionReport.aggregate(reports)
   ```

3. **Schedule nightly runs**
   ```python
   # tron/worker.py
   
   @worker.defn
   async def start_worker():
       # ... existing code ...
       
       # Schedule regression tests (nightly at 2 AM)
       await worker.run(
           workflows=[RegressionTestWorkflow],
           schedules=[
               {
                   "workflow": RegressionTestWorkflow,
                   "schedule": "0 2 * * *",  # Cron: 2 AM daily
                   "args": []
               }
           ]
       )
   ```

**Deliverable:** Layer 7 operational, prompt drift detected automatically

---

## Phase 2: Activate All Agents (Week 4)

### Task 1: Uncomment QAISO

```python
# tron/services/audit_executor.py

def _register_agents(self):
    # ... existing agents ...
    
    # UNCOMMENT THIS:
    manager.register_agent(
        QAISO(
            llm_client=self.llm_client,
            logger=self.logger
        )
    )
```

### Task 2: Implement Memory Agent

**Purpose:** Track findings across audits, detect regressions

```python
# tron/agents/memory.py

class Memory:
    """Memory ISO: Tracks findings across audits"""
    
    async def analyze(self, context: AgentContext) -> list[Finding]:
        """
        Compare current findings to previous audits
        Detect: New issues, Fixed issues, Recurring issues
        """
        current_audit = context.audit_run_id
        previous_audits = await self._get_previous_audits(context.project_id)
        
        findings = []
        
        # Find regressions (issues that were fixed but came back)
        regressions = await self._detect_regressions(
            current_audit,
            previous_audits
        )
        
        for regression in regressions:
            findings.append(Finding(
                category="regression",
                severity="high",
                title=f"Regression: {regression.title}",
                description=f"This issue was fixed in audit {regression.fixed_in} but has returned",
                file_path=regression.file_path,
                line_number=regression.line_number,
                confidence=0.95
            ))
        
        return findings
```

### Task 3: Fix Cross-Validation Rate Limiting

**Current issue:** OpenAI 429 errors block validation

**Solution:** Implement retry with exponential backoff

```python
# tron/services/llm_client.py

class LLMClient:
    async def complete(
        self,
        messages: list[dict],
        **kwargs
    ) -> str:
        """Add retry logic for rate limits"""
        max_retries = 5
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                return await self._complete_internal(messages, **kwargs)
            except RateLimitError as e:
                if attempt == max_retries - 1:
                    raise
                
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Rate limited, retrying in {delay}s...")
                await asyncio.sleep(delay)
```

**Deliverable:** 5 agents operational, cross-validation reliable

---

## Phase 3: Clean Up Infrastructure (Week 5)

### Task 1: Remove Unused Services

**Remove from docker-compose.yml:**
- prometheus (not running)
- grafana (not running)
- loki (not running)
- tempo (not running)
- alertmanager (not running)
- otel-collector (not running)
- nginx (not needed yet)
- tron-backup (not implemented)

**Keep:**
- postgres, redis, temporal, temporal-ui
- tron-api, tron-worker
- tron-sandbox (now integrated)
- minio, pgbouncer (fix health checks)

### Task 2: Fix Service Health Checks

```yaml
# docker-compose.yml

minio:
  # ... existing config ...
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s

pgbouncer:
  # ... existing config ...
  healthcheck:
    test: ["CMD", "pg_isready", "-h", "localhost", "-p", "6432"]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 10s
```

### Task 3: Consolidate Frontends

**Decision:** Keep `frontend/` as main UI, remove others

```bash
# Remove admin-ui (unclear purpose)
rm -rf admin-ui/

# Keep docs/website (documentation site)
# Keep frontend/ (main application UI)
```

**Deliverable:** Clean infrastructure, all services healthy

---

## Phase 4: Additional Modes (Weeks 6-10)

### Week 6-7: FIX Mode

**What it does:** Apply fixes in sandbox, verify they work

```python
# tron/workflows/fix_workflow.py

@workflow.defn
class FixWorkflow:
    """FIX mode: Apply and verify fixes"""
    
    @workflow.run
    async def run(
        self,
        finding_id: str,
        fix_strategy: str
    ) -> FixResult:
        """
        1. Generate fix (LLM)
        2. Apply in sandbox
        3. Run verification
        4. If verified, return patch
        """
        finding = await workflow.execute_activity(
            load_finding,
            finding_id
        )
        
        # Generate fix
        fix = await workflow.execute_activity(
            generate_fix,
            finding,
            fix_strategy
        )
        
        # Apply in sandbox
        result = await workflow.execute_activity(
            apply_fix_in_sandbox,
            finding,
            fix
        )
        
        if result.success:
            return FixResult(
                status="verified",
                patch=result.patch,
                verification=result.verification
            )
        else:
            return FixResult(
                status="failed",
                error=result.error
            )
```

### Week 8-9: PLAN Mode (Partial)

**What it does:** Generate quality gates before building

```python
# tron/workflows/plan_workflow.py

@workflow.defn
class PlanWorkflow:
    """PLAN mode: Generate project blueprint"""
    
    @workflow.run
    async def run(
        self,
        project_id: str,
        requirements: dict
    ) -> ProjectBlueprint:
        """
        1. Analyze requirements
        2. Generate quality gates
        3. Create test specifications
        4. Define standards
        """
        # Generate quality gates
        gates = await workflow.execute_activity(
            generate_quality_gates,
            requirements
        )
        
        # Generate test specs
        tests = await workflow.execute_activity(
            generate_test_specifications,
            requirements
        )
        
        # Store blueprint
        blueprint = ProjectBlueprint(
            quality_gates=gates,
            test_specifications=tests,
            standards=requirements.get("standards", {})
        )
        
        await workflow.execute_activity(
            store_blueprint,
            project_id,
            blueprint
        )
        
        return blueprint
```

### Week 10: BUILD Mode (Deferred)

**Decision:** Defer BUILD mode - most complex, highest LLM cost

**Rationale:**
- AUDIT + FIX provides value
- PLAN defines objectives
- BUILD is nice-to-have, not critical path

**If needed later:** Model after Stripe Minions approach

---

## Success Metrics

### Phase 1 Complete (Week 3)
- ✅ All 7 layers operational
- ✅ Precision ≥98% (measured on golden suite)
- ✅ False positive rate ≤2%
- ✅ Sandbox integrated and working

### Phase 2 Complete (Week 4)
- ✅ 5 agents active (Security, Builder, Performance, QA, Memory)
- ✅ Cross-validation reliable (no rate limit failures)
- ✅ Regression detection working

### Phase 3 Complete (Week 5)
- ✅ 8 services running, all healthy
- ✅ Infrastructure clean (no unused services)
- ✅ Single frontend UI

### Phase 4 Complete (Week 10)
- ✅ AUDIT + FIX + PLAN modes operational
- ✅ Can generate fixes and verify them
- ✅ Can generate quality gates for new projects

---

## Implementation Order: Day by Day

### Week 1: Layer 3 (Execution Verification)

**Monday:**
- Fix tron-sandbox Dockerfile
- Add sandbox health check
- Test sandbox isolation

**Tuesday:**
- Implement ExecutionVerifier class
- Add secret verification tests
- Add SQL injection tests

**Wednesday:**
- Add command injection tests
- Implement sandbox executor
- Integration testing

**Thursday:**
- Update audit workflow
- Add Layer 3 to pipeline
- End-to-end testing

**Friday:**
- Measure precision improvement
- Document Layer 3 behavior
- Deploy to dev environment

### Week 2: Layers 5-6

**Monday-Tuesday:**
- Implement standards loader
- Add quality gate evaluator
- Database migrations for standards

**Wednesday-Thursday:**
- Implement confidence calibrator
- Create golden test suite (50 cases)
- Database migrations for calibration

**Friday:**
- Integration testing
- Measure calibration accuracy
- Deploy

### Week 3: Layer 7

**Monday-Tuesday:**
- Implement regression tester
- Create regression test suite
- Build 30 regression test cases

**Wednesday:**
- Implement drift detection
- Add alerting for degradation

**Thursday:**
- Schedule nightly regression runs
- Test automated alerts

**Friday:**
- Full 7-layer integration test
- Measure final precision
- Document complete pipeline

### Week 4: Agents

**Monday:**
- Uncomment QAISO
- Fix any QAISO bugs
- Test QAISO findings

**Tuesday:**
- Implement Memory agent
- Test regression detection

**Wednesday:**
- Fix cross-validation rate limiting
- Implement retry logic with backoff

**Thursday:**
- Test all 5 agents together
- Measure finding distribution

**Friday:**
- Load testing
- Performance optimization

### Week 5: Infrastructure

**Monday:**
- Remove unused services from docker-compose
- Update docker-compose.yml

**Tuesday:**
- Fix minio health check
- Fix pgbouncer health check

**Wednesday:**
- Remove admin-ui directory
- Consolidate to single frontend

**Thursday:**
- Documentation update
- Architecture diagrams update

**Friday:**
- Clean deployment testing
- Infrastructure validation

---

## Next Steps: Start Today

### Immediate Action (Today - Sunday)

**Create Layer 3 scaffold:**

```bash
# Create execution verifier module
mkdir -p tron/verification
touch tron/verification/__init__.py
touch tron/verification/execution_verifier.py
```

### Monday Morning

**Task 1:** Fix tron-sandbox service (2 hours)
**Task 2:** Implement ExecutionVerifier class skeleton (4 hours)
**Task 3:** Write first verification test (secret validation) (2 hours)

### This Week Goal

**By Friday:** Layer 3 operational, measurable precision improvement

---

## Questions for You

Before we start building:

1. **Priority confirmation:** Is completing the 7-layer pipeline the #1 priority?
2. **Resource check:** Can you commit ~40 hours/week for next 5 weeks?
3. **Measurement:** Will you manually verify findings to calculate actual precision?
4. **Timeline:** Is 5 weeks acceptable to complete Phases 1-3?

---

**Bottom line:** We have a clear 5-week plan to complete:
- ✅ All 7 verification layers
- ✅ All 5 ISO agents
- ✅ Clean infrastructure
- ✅ AUDIT + FIX + PLAN modes

**Ready to start building?**

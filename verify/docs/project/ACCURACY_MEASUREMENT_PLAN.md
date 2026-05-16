# Tron Accuracy Measurement Plan

**Purpose:** Validate that 7-layer verification pipeline is necessary to achieve 98% precision target

**Date:** April 13, 2026

---

## Current State: 3 of 7 Layers Operational

### Implemented Layers ✅

**Layer 1: Deterministic Tools First**
- ✅ Bandit (Python security)
- ✅ Semgrep (pattern matching)
- ✅ Status: Working

**Layer 2: Schema-Enforced Output**
- ✅ Pydantic validation
- ✅ Field type enforcement
- ✅ Status: Working

**Layer 4: Multi-Agent Cross-Validation** (Partial)
- ⚠️ OpenAI validation (rate-limited, non-blocking)
- ⚠️ Status: Implemented but unreliable

### Missing Layers ❌

**Layer 3: Execution Verification**
- ❌ Sandbox not integrated
- ❌ Fix application testing
- ❌ Impact: Can't verify if findings are exploitable

**Layer 5: Blueprint-Scoped Tasks**
- ❌ Quality gates not implemented
- ❌ Standards hierarchy not enforced
- ❌ Impact: Can't scope findings to project context

**Layer 6: Calibrated Confidence**
- ❌ Golden test suite not built
- ❌ Confidence calibration not implemented
- ❌ Impact: Can't trust confidence scores

**Layer 7: Prompt Regression Testing**
- ❌ Regression suite not built
- ❌ Drift detection not implemented
- ❌ Impact: Can't catch prompt degradation

---

## Measurement Protocol

### Phase 1: Baseline Accuracy (Current 3 Layers)

**Goal:** Measure actual precision with current system

**Method:**
1. **Select Test Repos (5 repositories)**
   - ✅ Juice Shop (already scanned)
   - WebGoat (OWASP training app)
   - NodeGoat (Node.js vulnerabilities)
   - Clean repo 1 (no known issues)
   - Clean repo 2 (no known issues)

2. **Run Full Scans**
   - Record all findings
   - Capture confidence scores
   - Note which layer produced each finding

3. **Manual Verification (Ground Truth)**
   - For each finding:
     - ✅ **True Positive:** Real issue, correctly identified
     - ❌ **False Positive:** Not an issue or incorrect
     - ⚠️ **Uncertain:** Needs expert review
   - Record time to verify (cost metric)

4. **Calculate Metrics**
   ```
   Precision = True Positives / (True Positives + False Positives)
   False Positive Rate = False Positives / Total Findings
   Accuracy by Confidence Band (0.5-0.7, 0.7-0.85, 0.85-0.95, 0.95+)
   ```

**Expected Outcome:** Baseline precision with 3 layers (likely 80-90%)

---

### Phase 2: Incremental Layer Validation

**Goal:** Measure precision gain per layer

**Method:** Add one layer at a time, re-measure

**Layer 3: Execution Verification**
1. Integrate sandbox (tron-sandbox)
2. Run execution tests on findings
3. Mark findings as:
   - ✅ Verified (exploit succeeded)
   - ⚠️ Unverified (exploit failed or N/A)
   - ❌ Rejected (false positive detected)
4. Re-measure precision

**Expected Gain:** +5-10% precision (reduces false positives for exploitability claims)

**Layer 5: Blueprint-Scoped Tasks**
1. Implement standards hierarchy
2. Load quality gates
3. Filter findings by project context
4. Re-measure precision

**Expected Gain:** +3-5% precision (reduces false positives from out-of-scope findings)

**Layer 6: Calibrated Confidence**
1. Build golden test suite (200+ cases)
2. Calibrate confidence scores
3. Adjust thresholds
4. Re-measure precision

**Expected Gain:** +2-3% precision (better confidence → better filtering)

**Layer 7: Prompt Regression Testing**
1. Build regression suite
2. Detect drift
3. Re-measure precision

**Expected Gain:** +1-2% precision (prevents degradation over time)

---

## Evidence Table

### Test Results Template

| Repository | Total Findings | True Positives | False Positives | Precision | FP Rate |
|------------|----------------|----------------|-----------------|-----------|---------|
| Juice Shop | 14 | ? | ? | ? | ? |
| WebGoat | ? | ? | ? | ? | ? |
| NodeGoat | ? | ? | ? | ? | ? |
| Clean Repo 1 | ? | 0 | ? | N/A | 100% |
| Clean Repo 2 | ? | 0 | ? | N/A | 100% |
| **TOTAL** | ? | ? | ? | **?%** | **?%** |

**Target:** ≥98% precision, ≤2% FP rate

---

## Critical Questions to Answer

### 1. What's the current precision?

**Hypothesis:** 80-90% with 3 layers  
**Test:** Manual verification of Juice Shop findings  
**Decision:** If <90%, then Layer 3-7 are justified

### 2. Which layer provides the most value?

**Hypothesis:** Layer 3 (execution) is most critical  
**Test:** Compare precision before/after Layer 3  
**Decision:** Prioritize high-impact layers

### 3. Can you hit 98% without all 7 layers?

**Hypothesis:** Maybe 6 layers is enough  
**Test:** Incremental measurement  
**Decision:** Build only what's proven necessary

### 4. What's the cost of each layer?

**Measurement:**
- Development time (weeks)
- Execution latency (seconds per audit)
- Infrastructure cost ($ per month)
- Maintenance burden (complexity)

**Trade-off:** Precision gain vs. cost

---

## Immediate Action: Verify Juice Shop Findings

### Manual Verification Protocol

**For each of the 14 Juice Shop findings:**

1. **Open the file in GitHub**
   - Example: `.github/FUNDING.yml` line 2
   - Verify file exists at that path
   - Verify line number is correct

2. **Assess if it's a real issue**
   - ✅ True Positive: Real vulnerability (e.g., hardcoded token)
   - ❌ False Positive: Not an issue (e.g., public info, test data)
   - ⚠️ Debatable: Context-dependent (e.g., development-only code)

3. **Record verification**
   ```json
   {
     "finding_id": "...",
     "file": ".github/FUNDING.yml",
     "line": 2,
     "claimed_issue": "hardcoded_secrets",
     "verification": "true_positive",
     "notes": "GitHub username is public info - FALSE POSITIVE",
     "verifier": "human",
     "verification_date": "2026-04-13"
   }
   ```

4. **Calculate actual precision**
   ```
   If 12 of 14 are true positives:
   Precision = 12/14 = 85.7%
   FP Rate = 2/14 = 14.3%
   
   This is BELOW target (98%), justifying additional layers.
   ```

---

## Example: Layer 3 (Execution) Value Prop

**Claim:** "Hardcoded secrets in config file"

**Without Layer 3 (current):**
- LLM sees: `API_KEY = "sk-test-..."`
- Flags as: High severity hardcoded secret
- Result: Reported to user

**Potential False Positive:**
- Key is test/example key (not real)
- Key is development-only (not production)
- File is documentation/example

**With Layer 3 (sandbox execution):**
- Attempt to use key in API call
- If key works → True positive
- If key fails → Downgrade to medium or reject
- Result: Higher precision

**Value:** Reduces false positives on example/test secrets

---

## Example: Layer 6 (Calibration) Value Prop

**Claim:** Confidence score 0.92 on finding

**Without Layer 6 (current):**
- LLM outputs: `"confidence": 0.92`
- System accepts at face value
- User trusts it

**Potential Issue:**
- Actual accuracy at 0.92 confidence is only 78%
- Overconfident LLM

**With Layer 6 (calibration):**
- Measure actual accuracy per confidence band
- Find: 0.92 confidence → 78% actual accuracy
- Adjust: Downgrade display confidence to 0.78
- Result: Honest confidence scores

**Value:** Users can trust confidence scores

---

## Success Criteria

### Phase 1 Baseline (2 weeks)

✅ **Measured:**
- Precision of current system (3 layers)
- False positive rate
- Breakdown by confidence band
- Verification time per finding

✅ **Decision Point:**
- If precision ≥95%: Maybe 3 layers is enough?
- If precision 85-95%: Layer 3-4 likely sufficient
- If precision <85%: All 7 layers justified

### Phase 2 Incremental (6 weeks)

✅ **Built & Measured:**
- Layer 3: Execution verification
- Layer 5: Blueprint scoping
- Layer 6: Confidence calibration
- Layer 7: Regression testing

✅ **Outcome:**
- Precision curve (3→4→5→6→7 layers)
- Cost curve (latency, infrastructure)
- ROI analysis (precision gain vs. cost)

---

## Expected Results

### Conservative Estimate

| Configuration | Precision | FP Rate | Justification |
|---------------|-----------|---------|---------------|
| 3 layers (current) | 85% | 15% | Deterministic + LLM + Schema |
| + Layer 3 (execution) | 91% | 9% | Verify exploitability |
| + Layer 4 (cross-val) | 94% | 6% | Multi-LLM consensus |
| + Layer 5 (blueprint) | 96% | 4% | Context filtering |
| + Layer 6 (calibration) | 97.5% | 2.5% | Confidence tuning |
| + Layer 7 (regression) | 98%+ | <2% | Prevent drift |

**Conclusion:** All 7 layers needed to hit 98% target

### Optimistic Estimate

| Configuration | Precision | FP Rate | Justification |
|---------------|-----------|---------|---------------|
| 3 layers (current) | 92% | 8% | Current system is better than expected |
| + Layer 3 (execution) | 96% | 4% | Big gain from execution tests |
| + Layer 4 (cross-val) | 98% | 2% | Hit target at Layer 4 |
| + Layer 5-7 | 98.5% | 1.5% | Marginal gains |

**Conclusion:** Layers 5-7 optional (diminishing returns)

---

## Decision Framework

### If Current Precision ≥95%

**Action:** Ship current system, add layers only if precision drops

**Reasoning:**
- Already exceeding most tools (SonarQube ~80-85%)
- Diminishing returns
- Focus on adoption

### If Current Precision 85-95%

**Action:** Build Layer 3 (execution), re-measure

**Reasoning:**
- Layer 3 has highest expected impact
- Can hit 95%+ with 4 layers
- Layers 5-7 can be deferred

### If Current Precision <85%

**Action:** Build all 7 layers as planned

**Reasoning:**
- Significant precision gap
- Multiple layers needed
- Original architecture validated

---

## Immediate Next Steps

### Week 1: Manual Verification

**Task:** Verify Juice Shop findings
1. Open each of 14 findings in GitHub
2. Classify: True positive / False positive / Uncertain
3. Calculate actual precision
4. Document reasoning

**Deliverable:** `JUICE_SHOP_VERIFICATION.md` with ground truth

### Week 2: Additional Test Repos

**Task:** Scan 4 more repos (2 vulnerable, 2 clean)
1. WebGoat: Expected ~20-30 findings
2. NodeGoat: Expected ~15-25 findings
3. Clean repo 1: Expected 0 findings (false positive test)
4. Clean repo 2: Expected 0 findings (false positive test)

**Deliverable:** 
- Baseline precision across 5 repos
- False positive rate on clean code
- Confidence in current accuracy

### Week 3-4: Layer 3 Prototype

**Task:** Integrate sandbox for execution testing
1. Fix tron-sandbox health
2. Integrate with workflow
3. Test exploit execution
4. Measure precision gain

**Deliverable:** 
- Working Layer 3
- Measured precision improvement
- Decision on Layers 5-7

---

## Conclusion

**Your argument is valid IF:**
1. Current precision is measured at <95%
2. Each layer provides measurable precision gain
3. Cost is justified by precision improvement

**My recommendation:**
1. ✅ **Measure first** (2 weeks)
2. ✅ **Build incrementally** (6 weeks)
3. ✅ **Validate each layer** (prove necessity)

**Don't guess - measure.** If you hit 98% at Layer 4, you can defer Layers 5-7. If you need all 7, you'll have proof.

---

**Bottom Line:** You're right that 100% quality justifies comprehensive verification. But measure current accuracy first to know which layers are critical vs. nice-to-have.
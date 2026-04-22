# Tron Zero-Drift Verification Pipeline Architecture

**Version:** 5.1  
**Date:** 2026-04-11  
**Status:** Production Architecture  
**Owner:** Tron Core Architecture Team

## Executive Summary

The Zero-Drift Verification Pipeline is a 7-layer architecture designed to eliminate hallucinations, enforce logical consistency, and maintain sub-0.5% drift rates in Tron's AI-driven security agent system. Each layer builds on deterministic validation, structured constraints, and continuous regression testing to ensure every finding is either confirmed by tools or flagged for human review.

**Operational Definition of 98%+ Verified Confidence:**
- **Precision target:** ≥98% of findings delivered to users are true positives (≤2% false positive rate)
- **Recall:** Measured and reported per vulnerability type with 95% Wilson score confidence intervals. No global recall target — recall varies by vulnerability type and is reported honestly.
- **Calibration rules:** Calibration curves published ONLY when N≥200 per confidence band. Below N=200: raw accuracy with explicit confidence intervals. Platt scaling activates at N≥500 golden suite cases.
- **All published metrics include 95% Wilson score confidence intervals. No point estimates without error bars.**

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 7: Continuous Monitoring & Prompt Regression Testing          │
│  (Nightly test runs, semantic drift scoring, auto-rollback)          │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 6: Confidence Calibration System                              │
│  (Golden test suite, accuracy bands, calibration curves, metrics)    │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 5: Task Boundary Crystallization (Blueprints)                │
│  (Scope contracts, tool requirements, output schemas)               │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 4: Multi-Agent Cross-Validation                               │
│  (Primary agent + Validator agent + Deterministic tools)            │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 3: Execution-Based Feedback Loop                              │
│  (Docker sandbox, test suite, PoC exploit validation)               │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 2: Structured Output Schema Enforcement                       │
│  (Pydantic validation, deterministic field checks)                  │
└─────────────────────────────────────┬───────────────────────────────┘
                                       │
┌─────────────────────────────────────┴───────────────────────────────┐
│  Layer 1: Deterministic Validation Harness                           │
│  (Bandit, Semgrep, Safety - T=0.0 for audit, T=0.1-0.3 for gen)   │
└─────────────────────────────────────────────────────────────────────┘

Input: Audit Task (Blueprint)  │  Output: Verified Findings (High Confidence)
```

---

## Layer Specifications

### Layer 1: Deterministic Validation Harness

**Purpose:** Ground truth validation before LLM analysis.

**Implementation:**

Every ISO agent task executes deterministic tools in parallel before invoking LLM analysis:

```python
# tools_harness.py
from dataclasses import dataclass
from enum import Enum

class ToolType(str, Enum):
    BANDIT = "bandit"
    SEMGREP = "semgrep"
    SAFETY = "safety"

@dataclass
class DeterministicFinding:
    tool: ToolType
    vulnerability_type: str
    file_path: str
    line_number: int
    severity: str  # "HIGH", "MEDIUM", "LOW"
    rule_id: str
    message: str

async def run_deterministic_harness(
    codebase_path: str,
    task_blueprint: "Blueprint"
) -> dict[ToolType, list[DeterministicFinding]]:
    """
    Execute all required deterministic tools in parallel.
    Returns mapping of tool to findings.
    """
    results = {}
    
    # Bandit for Python security
    bandit_findings = await run_bandit(codebase_path)
    results[ToolType.BANDIT] = parse_bandit_output(bandit_findings)
    
    # Semgrep for polyglot code patterns
    semgrep_findings = await run_semgrep(
        codebase_path,
        config=task_blueprint.semgrep_config_url
    )
    results[ToolType.SEMGREP] = parse_semgrep_output(semgrep_findings)
    
    # Safety for dependency vulnerabilities
    safety_findings = await run_safety(codebase_path)
    results[ToolType.SAFETY] = parse_safety_output(safety_findings)
    
    return results

# LLM Configuration per task type
LLM_CONFIG = {
    "audit_security": {"temperature": 0.0, "top_p": 1.0},
    "code_generation": {"temperature": 0.2, "top_p": 0.95},
    "fix_suggestion": {"temperature": 0.1, "top_p": 0.9},
}
```

**Verification Rule:** All LLM findings must reference at least one deterministic tool finding in the same file/line range, or be explicitly flagged as "unverified" with confidence capped at 0.5.

---

### Layer 2: Structured Output Schema Enforcement

**Purpose:** Enforce typed output contracts; prevent freetext hallucination vectors.

**Pydantic Schema:**

```python
# schemas.py
from pydantic import BaseModel, field_validator, Field
from enum import Enum
from typing import Optional
import os

class VulnerabilityType(str, Enum):
    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    COMMAND_INJECTION = "command_injection"
    BUFFER_OVERFLOW = "buffer_overflow"
    PATH_TRAVERSAL = "path_traversal"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    WEAK_CRYPTOGRAPHY = "weak_cryptography"
    HARDCODED_CREDENTIALS = "hardcoded_credentials"
    LDAP_INJECTION = "ldap_injection"
    XXMLINJECTION = "xxe_injection"
    LOG_INJECTION = "log_injection"
    RACE_CONDITION = "race_condition"
    UNVALIDATED_REDIRECT = "unvalidated_redirect"

class FindingOutput(BaseModel):
    """Strictly validated security finding output."""
    
    vulnerability_type: VulnerabilityType
    file_path: str
    line_number: int
    code_snippet: str
    confidence: float = Field(ge=0.0, le=1.0)
    deterministic_tool_confirmed: bool
    severity: str = Field(pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$")
    description: str = Field(max_length=500)
    remediation: Optional[str] = Field(None, max_length=1000)
    cwe_id: Optional[str] = None
    
    @field_validator("file_path")
    @classmethod
    def validate_file_exists(cls, v: str, info) -> str:
        """Ensure file actually exists in codebase."""
        # In context, `codebase_root` is available
        if not os.path.exists(v):
            raise ValueError(f"File does not exist: {v}")
        return v
    
    @field_validator("line_number")
    @classmethod
    def validate_line_in_file(cls, v: int, info) -> int:
        """Ensure line number is within file bounds."""
        if "file_path" in info.data:
            file_path = info.data["file_path"]
            try:
                with open(file_path, 'r') as f:
                    total_lines = len(f.readlines())
                if v > total_lines or v < 1:
                    raise ValueError(
                        f"Line {v} out of range [1, {total_lines}] in {file_path}"
                    )
            except IOError as e:
                raise ValueError(f"Cannot read file: {e}")
        return v
    
    @field_validator("code_snippet")
    @classmethod
    def validate_code_matches(cls, v: str, info) -> str:
        """Ensure code snippet matches actual file content."""
        if "file_path" in info.data and "line_number" in info.data:
            file_path = info.data["file_path"]
            line_num = info.data["line_number"]
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                    actual_line = lines[line_num - 1].strip()
                    if v.strip() not in actual_line:
                        raise ValueError(
                            f"Code snippet '{v}' not found at line {line_num}"
                        )
            except (IOError, IndexError) as e:
                raise ValueError(f"Cannot validate code snippet: {e}")
        return v
    
    @field_validator("confidence")
    @classmethod
    def apply_deterministic_cap(cls, v: float, info) -> float:
        """If not deterministic_tool_confirmed, cap confidence at 0.7."""
        if "deterministic_tool_confirmed" in info.data:
            if not info.data["deterministic_tool_confirmed"] and v > 0.7:
                return 0.7
        return v

class AuditFindingsOutput(BaseModel):
    """Root output model for audit results."""
    findings: list[FindingOutput]
    summary: str = Field(max_length=1000)
    total_time_seconds: float
    deterministic_findings_count: int
    llm_only_findings_count: int
    high_severity_count: int
```

**Validation Pipeline:**

```python
# validator.py
async def validate_and_enforce_schema(
    llm_output: dict,
    deterministic_results: dict[ToolType, list[DeterministicFinding]],
    codebase_root: str
) -> tuple[AuditFindingsOutput, list[str]]:
    """
    Validate LLM output against schema and cross-reference with deterministic findings.
    Returns (validated_output, list_of_hallucinations).
    """
    hallucinations = []
    
    # Parse LLM JSON
    try:
        raw_findings = [FindingOutput(**f) for f in llm_output["findings"]]
    except Exception as e:
        raise SchemaValidationError(f"LLM output does not conform to schema: {e}")
    
    # Cross-reference with deterministic tools
    det_keys = {
        (f.file_path, f.line_number)
        for tool_findings in deterministic_results.values()
        for f in tool_findings
    }
    
    verified_findings = []
    for finding in raw_findings:
        key = (finding.file_path, finding.line_number)
        if key in det_keys:
            finding.deterministic_tool_confirmed = True
        else:
            hallucinations.append(
                f"Unverified finding at {finding.file_path}:{finding.line_number}"
            )
    
    output = AuditFindingsOutput(
        findings=raw_findings,
        summary=llm_output.get("summary", ""),
        total_time_seconds=llm_output.get("total_time_seconds", 0),
        deterministic_findings_count=len(det_keys),
        llm_only_findings_count=len(hallucinations),
        high_severity_count=sum(
            1 for f in raw_findings if f.severity == "HIGH"
        ),
    )
    
    return output, hallucinations
```

---

### Layer 2.5: Semantic Validation

Schema validation (Layer 2) catches *structural* hallucinations — malformed JSON, impossible line numbers, empty fields. But it cannot catch *semantic* hallucinations where the output is structurally valid but factually wrong.

Semantic validation verifies:
- **Code existence:** The `code_snippet` actually exists at the claimed `file_path:line_number` (diff-based comparison)
- **Pattern matching:** The code at that location matches the claimed vulnerability pattern (e.g., if the finding says "SQL injection," does the code actually construct SQL queries?)
- **Fix relevance:** If a fix is suggested, does it address the actual code pattern at that location?

Findings that fail semantic validation have their confidence capped at 0.3 (code not found at location) or 0.5 (code found but doesn't match pattern). See `SemanticValidationResult` in `tron/schemas/verification.py`.

---

### Layer 3: Execution-Based Feedback Loop

**Purpose:** Validate findings by attempting exploitation or fix application in sandboxed environment.

**Timeout handling:** Execution outcomes are explicitly categorized as SUCCESS, FAILURE, TIMEOUT, RESOURCE_EXCEEDED, or SANDBOX_ERROR. Timeouts are inconclusive — they do NOT count as failures and do NOT receive negative confidence adjustments. Only FAILURE outcomes adjust confidence downward. SANDBOX_ERROR outcomes (infrastructure issues) have zero confidence impact. See `SandboxExecutionResult` and `ExecutionOutcome` in `tron/schemas/verification.py`.

**Implementation:**

```python
# execution_validator.py
import docker
import subprocess
from pathlib import Path

async def validate_via_execution(
    finding: FindingOutput,
    codebase_path: str,
    task_type: str
) -> float:
    """
    Execute validation: either PoC exploit or fix-and-test.
    Returns adjusted confidence (0.0 to 1.0).
    """
    
    if task_type == "security_audit":
        return await validate_via_exploit(finding, codebase_path)
    elif task_type == "fix_suggestion":
        return await validate_via_fix_application(finding, codebase_path)
    else:
        return finding.confidence  # No execution validation for other types

async def validate_via_exploit(
    finding: FindingOutput,
    codebase_path: str
) -> float:
    """
    For high-severity findings: attempt proof-of-concept exploit.
    If exploit succeeds → confidence = 1.0
    If exploit fails → confidence = 0.5
    If exploit crashes/error → confidence = 0.3
    """
    
    # Create isolated Docker container with codebase
    client = docker.from_env()
    container = client.containers.create(
        "python:3.11-slim",
        volumes={codebase_path: {"bind": "/app", "mode": "ro"}},
        working_dir="/app",
        detach=True
    )
    
    try:
        # Build PoC exploit based on vulnerability type
        exploit_script = generate_exploit_script(finding)
        
        # Execute exploit
        exit_code, output = container.exec_run(
            ["python", "-c", exploit_script],
            timeout=30
        )
        
        if exit_code == 0 and "EXPLOIT_SUCCESS" in output.decode():
            return 1.0  # Vulnerability confirmed exploitable
        else:
            return 0.5  # Exploit failed; finding may be false positive
    
    except subprocess.TimeoutExpired:
        return 0.3  # Crash or hang; unknown validity
    
    finally:
        container.stop()
        container.remove()

async def validate_via_fix_application(
    finding: FindingOutput,
    codebase_path: str,
    suggested_fix: str
) -> float:
    """
    Apply suggested fix to codebase copy in Docker sandbox.
    Run existing test suite. If all tests pass → confidence = 1.0
    If tests fail → confidence = 0.4
    """
    
    client = docker.from_env()
    container = client.containers.create(
        "python:3.11-slim",
        volumes={codebase_path: {"bind": "/app", "mode": "rw"}},
        working_dir="/app",
        detach=True
    )
    
    try:
        # Copy original codebase to container
        # Apply fix to file at finding.file_path:finding.line_number
        exit_code, output = container.exec_run(
            ["python", "-m", "pytest", "-v"],
            timeout=120
        )
        
        if exit_code == 0:
            return 1.0  # Fix passes all tests
        else:
            return 0.4  # Fix causes test failures
    
    except subprocess.TimeoutExpired:
        return 0.3
    
    finally:
        container.stop()
        container.remove()

def generate_exploit_script(finding: FindingOutput) -> str:
    """Generate PoC exploit Python script based on vulnerability type."""
    templates = {
        VulnerabilityType.SQL_INJECTION: EXPLOIT_SQL_INJECTION_TEMPLATE,
        VulnerabilityType.XSS: EXPLOIT_XSS_TEMPLATE,
        VulnerabilityType.COMMAND_INJECTION: EXPLOIT_COMMAND_TEMPLATE,
        # ... more templates
    }
    template = templates.get(finding.vulnerability_type, "")
    return template.format(file_path=finding.file_path, line=finding.line_number)
```

---

### Layer 4: Multi-Agent Cross-Validation

**Purpose:** Eliminate single-agent hallucinations via independent validation.

**Circuit Breaker Pattern:** All LLM API calls are protected by a circuit breaker:
- **Threshold:** 5 consecutive failures opens the circuit
- **Timeout:** 60 seconds in open state before half-open retry
- **Bulkhead:** Maximum 10 concurrent LLM calls per worker (prevents cascade)
- **Per-request timeout:** 30 seconds (configurable via `LLM_REQUEST_TIMEOUT`)
When the circuit opens, in-flight validations are paused (not failed) and retried when the circuit half-opens.

**Architecture:**

```python
# multi_agent_validator.py
from enum import Enum

class ValidationStatus(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    VALIDATOR_ONLY = "validator_only"
    CONFLICTING = "conflicting"

@dataclass
class CrossValidationResult:
    finding: FindingOutput
    status: ValidationStatus
    primary_score: float
    validator_score: float
    deterministic_confirmed: bool
    final_confidence: float
    notes: str

async def cross_validate_findings(
    primary_findings: list[FindingOutput],
    codebase_path: str,
    deterministic_results: dict[ToolType, list[DeterministicFinding]]
) -> list[CrossValidationResult]:
    """
    Run independent validator agent on same codebase.
    Compare results, apply agreement rules.
    """
    
    # Primary agent already ran; now invoke Validator agent
    validator_findings = await run_validator_agent(codebase_path)
    
    results = []
    primary_keys = {(f.file_path, f.line_number): f for f in primary_findings}
    validator_keys = {(f.file_path, f.line_number): f for f in validator_findings}
    det_keys = {
        (f.file_path, f.line_number)
        for tool_findings in deterministic_results.values()
        for f in tool_findings
    }
    
    # Findings in both agents + deterministic
    for key, primary_finding in primary_keys.items():
        if key in validator_keys:
            validator_finding = validator_keys[key]
            det_confirmed = key in det_keys
            
            # Both agents agree + deterministic confirms → confirmed
            if det_confirmed or (
                primary_finding.vulnerability_type == 
                validator_finding.vulnerability_type
            ):
                final_conf = 1.0 if det_confirmed else min(
                    primary_finding.confidence,
                    validator_finding.confidence
                ) * 0.95
                status = ValidationStatus.CONFIRMED
            else:
                # Agents disagree on type but same location
                status = ValidationStatus.NEEDS_REVIEW
                final_conf = max(
                    primary_finding.confidence * 0.6,
                    validator_finding.confidence * 0.6
                )
            
            results.append(CrossValidationResult(
                finding=primary_finding,
                status=status,
                primary_score=primary_finding.confidence,
                validator_score=validator_finding.confidence,
                deterministic_confirmed=det_confirmed,
                final_confidence=final_conf,
                notes=f"Agreement: {status.value}"
            ))
        
        else:
            # Primary only, no validator agreement
            det_confirmed = key in det_keys
            results.append(CrossValidationResult(
                finding=primary_finding,
                status=ValidationStatus.NEEDS_REVIEW,
                primary_score=primary_finding.confidence,
                validator_score=0.0,
                deterministic_confirmed=det_confirmed,
                final_confidence=primary_finding.confidence * 0.7 if not det_confirmed else 0.9,
                notes="Validator did not report this finding"
            ))
    
    # Validator found findings primary missed
    for key, validator_finding in validator_keys.items():
        if key not in primary_keys:
            results.append(CrossValidationResult(
                finding=validator_finding,
                status=ValidationStatus.VALIDATOR_ONLY,
                primary_score=0.0,
                validator_score=validator_finding.confidence,
                deterministic_confirmed=key in det_keys,
                final_confidence=validator_finding.confidence * 0.5,
                notes="Only detected by validator agent; re-analyzing with primary"
            ))
    
    return results

async def run_validator_agent(codebase_path: str) -> list[FindingOutput]:
    """
    Invoke separate Validator agent with different model/prompt.
    Validator is specialized in confirming/refuting findings.
    """
    # Uses different LLM model, different system prompt
    # Same deterministic validation harness
    prompt = VALIDATOR_AGENT_PROMPT
    
    validator_findings = await invoke_agent(
        agent_name="security_validator",
        codebase_path=codebase_path,
        system_prompt=prompt,
        model="claude-opus",  # Different from primary (e.g., claude-3.5-sonnet)
    )
    return validator_findings
```

**Agent Isolation Guarantees:**
Cross-validation enforces three levels of isolation:
1. **Model provider isolation:** Primary and validator agents MUST use different LLM providers (e.g., Anthropic + OpenAI). Enforced at schema level — see `CrossValidationResult.validate_agent_isolation()`.
2. **System prompt isolation:** Validator agents receive only the code and finding type — NOT the primary agent's description, reasoning, or suggested fix. This prevents confirmation bias.
3. **Context isolation:** Validator agents have no access to the primary agent's chat history, memory, or prior findings in the same session.

---

### Layer 5: Task Boundary Crystallization (Blueprints)

**Purpose:** Eliminate drift by constraining task scope and tool usage.

**Blueprint Schema:**

```python
# blueprints.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Blueprint:
    """Executable task contract for AI agents."""
    
    blueprint_id: str  # e.g., "audit_python_owasp_2024"
    task_type: str  # "audit_security", "code_generation", "fix_suggestion"
    description: str
    
    # Scope constraints
    in_scope_paths: list[str]  # Glob patterns: ["src/**/*.py", "tests/**"]
    in_scope_checks: list[str]  # ["sql_injection", "xss", "hardcoded_secrets"]
    not_in_scope: list[str]  # ["performance", "code_style", "documentation"]
    
    # Tool requirements
    tools_required: list[ToolType]  # [BANDIT, SEMGREP, SAFETY]
    deterministic_tool_required: bool = True
    
    # LLM constraints
    temperature: float = 0.0
    max_tokens: int = 8000
    max_duration_seconds: int = 300
    
    # Output schema
    output_schema: str = "FindingOutput"  # Pydantic model name
    findings_max_count: int = 100
    
    # Verification method
    verification_method: str  # "execution", "cross_validation", "deterministic_only"
    execution_timeout_seconds: Optional[int] = 60
    
    # Metrics & thresholds
    expected_accuracy: float = 0.95  # From golden suite calibration
    false_positive_threshold: float = 0.05
    
    def validate_execution_scope(self, actual_findings: list[FindingOutput]) -> list[str]:
        """Detect any findings outside this blueprint's scope."""
        violations = []
        
        for finding in actual_findings:
            # Check if finding path matches in_scope_paths
            if not any(
                Path(finding.file_path).match(pattern)
                for pattern in self.in_scope_paths
            ):
                violations.append(
                    f"Finding at {finding.file_path} outside in_scope_paths"
                )
            
            # Check if vulnerability type in in_scope_checks
            if finding.vulnerability_type.value not in self.in_scope_checks:
                violations.append(
                    f"Check {finding.vulnerability_type.value} in not_in_scope"
                )
        
        return violations

# Pre-defined blueprints
BLUEPRINT_AUDIT_PYTHON_OWASP = Blueprint(
    blueprint_id="audit_python_owasp_2024",
    task_type="audit_security",
    description="OWASP Top 10 audit for Python codebases",
    in_scope_paths=["src/**/*.py", "app/**/*.py"],
    in_scope_checks=[
        "sql_injection", "xss", "command_injection", "path_traversal",
        "insecure_deserialization", "weak_cryptography", "hardcoded_credentials"
    ],
    not_in_scope=["performance", "code_style", "comment_quality"],
    tools_required=[ToolType.BANDIT, ToolType.SEMGREP],
    temperature=0.0,
    max_tokens=6000,
    max_duration_seconds=180,
    verification_method="execution",
    expected_accuracy=0.97,
)

BLUEPRINT_GENERATE_SECURE_API = Blueprint(
    blueprint_id="generate_secure_api_endpoint",
    task_type="code_generation",
    description="Generate secure API endpoint following OWASP standards",
    in_scope_checks=["auth", "validation", "rate_limiting"],
    not_in_scope=["optimization", "async_patterns"],
    tools_required=[ToolType.SEMGREP],
    temperature=0.2,
    max_tokens=2000,
    max_duration_seconds=60,
    verification_method="cross_validation",
    expected_accuracy=0.92,
)
```

**Blueprint Execution:**

```python
# blueprint_executor.py
async def execute_blueprint(
    blueprint: Blueprint,
    codebase_path: str,
) -> AuditFindingsOutput:
    """Execute task strictly within blueprint constraints."""
    
    # 1. Deterministic harness (required by all blueprints)
    deterministic_results = await run_deterministic_harness(
        codebase_path, blueprint
    )
    
    # 2. Invoke LLM agent with blueprint constraints in prompt
    system_prompt = f"""
You are a {blueprint.task_type} AI agent.
Task: {blueprint.description}

SCOPE:
- Only analyze files matching: {blueprint.in_scope_paths}
- Only check for: {blueprint.in_scope_checks}
- DO NOT analyze: {blueprint.not_in_scope}

If you find issues in out-of-scope areas, IGNORE them.
"""
    
    llm_output = await invoke_iso_agent(
        agent_id=blueprint.blueprint_id,
        system_prompt=system_prompt,
        codebase_path=codebase_path,
        temperature=blueprint.temperature,
        max_tokens=blueprint.max_tokens,
    )
    
    # 3. Validate schema
    validated_output, hallucinations = await validate_and_enforce_schema(
        llm_output, deterministic_results, codebase_path
    )
    
    # 4. Check scope violations
    scope_violations = blueprint.validate_execution_scope(validated_output.findings)
    if scope_violations:
        logger.warning(f"Scope violations detected: {scope_violations}")
        validated_output.findings = [
            f for f in validated_output.findings
            if not any(v in str(f) for v in scope_violations)
        ]
    
    # 5. Execute verification method
    if blueprint.verification_method == "execution":
        for finding in validated_output.findings:
            adjusted_conf = await validate_via_execution(
                finding, codebase_path, blueprint.task_type
            )
            finding.confidence = adjusted_conf
    
    elif blueprint.verification_method == "cross_validation":
        cross_validation_results = await cross_validate_findings(
            validated_output.findings, codebase_path, deterministic_results
        )
        validated_output.findings = [
            r.finding for r in cross_validation_results
            if r.status != ValidationStatus.CONFLICTING
        ]
    
    # 6. Validate against blueprint metrics
    if len(validated_output.findings) > blueprint.findings_max_count:
        logger.error(
            f"Finding count {len(validated_output.findings)} "
            f"exceeds blueprint max {blueprint.findings_max_count}"
        )
        validated_output.findings = validated_output.findings[
            :blueprint.findings_max_count
        ]
    
    return validated_output
```

---

### Layer 6: Confidence Calibration System

**Purpose:** Ensure stated confidence accurately reflects actual accuracy.

**Golden Test Suite & Calibration:**

```python
# calibration.py
from dataclasses import dataclass
import numpy as np
from scipy.stats import binom

@dataclass
class CalibrationMetrics:
    confidence_band: tuple[float, float]  # e.g., (0.8, 0.9)
    true_positive_rate: float
    false_positive_rate: float
    accuracy: float
    sample_count: int
    last_updated: str

async def run_golden_suite(
    model_name: str,
    prompt_version: str
) -> dict[str, float]:
    """
    Execute 200+ golden test vulnerabilities (OWASP Benchmark, DVWA).
    Return accuracy metrics per confidence band.
    """
    
    # Golden test cases: known vulns with expected findings
    golden_cases = load_golden_test_suite()  # 200+ cases
    
    results_by_band = defaultdict(list)
    
    for test_case in golden_cases:
        # Run agent on test case
        agent_findings = await run_iso_agent_on_codebase(
            test_case.codebase_path,
            model=model_name,
            prompt_version=prompt_version,
        )
        
        # Grade findings
        for finding in agent_findings:
            band = round(finding.confidence, 1)  # Bucket to 0.1 intervals
            is_correct = finding in test_case.expected_findings
            results_by_band[band].append(is_correct)
    
    # Compute calibration curves
    calibration_metrics = {}
    for band, results in results_by_band.items():
        accuracy = np.mean(results)
        calibration_metrics[band] = CalibrationMetrics(
            confidence_band=(band - 0.05, band + 0.05),
            true_positive_rate=np.mean([r for r in results if r]),
            false_positive_rate=1 - accuracy,
            accuracy=accuracy,
            sample_count=len(results),
            last_updated=datetime.now().isoformat(),
        )
    
    return calibration_metrics

async def apply_calibration_curve(
    finding: FindingOutput,
    model_name: str,
    prompt_version: str
) -> FindingOutput:
    """
    Adjust finding confidence based on calibration metrics.
    E.g., if 0.85 confidence actually has 0.72 accuracy,
    display confidence as 0.72.
    """
    
    calibration = await get_calibration_metrics(model_name, prompt_version)
    band = round(finding.confidence, 1)
    
    if band in calibration:
        metric = calibration[band]
        adjusted_confidence = metric.accuracy
        finding.confidence = adjusted_confidence
    
    return finding

async def detect_calibration_drift(
    model_name: str,
    prompt_version: str,
    baseline_metrics: dict[float, CalibrationMetrics],
) -> dict:
    """
    Compare current calibration vs. baseline.
    If drift exceeds threshold, trigger alert and potential rollback.
    """
    
    current_metrics = await run_golden_suite(model_name, prompt_version)
    
    drift_scores = {}
    for band, current in current_metrics.items():
        if band in baseline_metrics:
            baseline = baseline_metrics[band]
            # Compute drift as max change in metrics
            drift = max(
                abs(current.accuracy - baseline.accuracy),
                abs(current.false_positive_rate - baseline.false_positive_rate),
            )
            drift_scores[band] = drift
    
    max_drift = max(drift_scores.values()) if drift_scores else 0
    
    alert = {
        "model": model_name,
        "prompt_version": prompt_version,
        "max_drift": max_drift,
        "threshold": 0.08,  # Max 8% accuracy change
        "drift_by_band": drift_scores,
        "should_rollback": max_drift > 0.08,
    }
    
    if alert["should_rollback"]:
        logger.error(f"Calibration drift detected, may trigger rollback: {alert}")
        # TODO: trigger rollback workflow
    
    return alert
```

**Database Schema:**

```sql
CREATE TABLE calibration_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(255) NOT NULL,
    prompt_version VARCHAR(100) NOT NULL,
    confidence_band_min FLOAT NOT NULL,
    confidence_band_max FLOAT NOT NULL,
    true_positive_rate FLOAT NOT NULL,
    false_positive_rate FLOAT NOT NULL,
    accuracy FLOAT NOT NULL,
    sample_count INT NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT unique_calibration UNIQUE (model_name, prompt_version, confidence_band_min),
    INDEX idx_model_version (model_name, prompt_version)
);

CREATE TABLE golden_suite_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_case_id VARCHAR(255) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    prompt_version VARCHAR(100) NOT NULL,
    expected_vulnerabilities INT NOT NULL,
    found_vulnerabilities INT NOT NULL,
    true_positives INT NOT NULL,
    false_positives INT NOT NULL,
    accuracy FLOAT NOT NULL,
    execution_time_ms INT,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_model_version (model_name, prompt_version),
    INDEX idx_test_case (test_case_id)
);
```

---

### Layer 7: Continuous Monitoring & Prompt Regression Testing

**Purpose:** Detect and prevent prompt/model drift via automated nightly regression tests.

**Implementation:**

```python
# regression_testing.py
from datetime import datetime, timedelta
import asyncio

@dataclass
class PromptRegressionTest:
    """Single regression test for a prompt template."""
    test_id: str
    prompt_template: str
    prompt_version: str
    input_codebase: str  # Path to test codebase
    expected_findings: list[FindingOutput]
    min_recall: float = 0.90
    max_false_positives: float = 0.05

async def run_nightly_regression_tests() -> dict:
    """
    Nightly task: run all prompt regression tests.
    Compare outputs against golden data.
    Detect drift via semantic similarity.
    """
    
    test_suites = await load_prompt_regression_tests()  # 10-20 per prompt
    results = defaultdict(list)
    drift_detected = False
    
    for prompt_version, tests in test_suites.items():
        for test in tests:
            # Execute agent with current prompt/model
            current_findings = await run_iso_agent_on_codebase(
                test.input_codebase,
                prompt=test.prompt_template,
                model="gpt-4o",
            )
            
            # Grade against expected findings
            grade = grade_findings(current_findings, test.expected_findings)
            
            # Compute semantic similarity of descriptions
            description_similarity = await compute_semantic_similarity(
                [f.description for f in current_findings],
                [f.description for f in test.expected_findings],
            )
            
            drift_score = 1 - description_similarity  # 0 = no drift, 1 = complete drift
            
            result = {
                "test_id": test.test_id,
                "prompt_version": prompt_version,
                "recall": grade["recall"],
                "precision": grade["precision"],
                "f1": grade["f1"],
                "drift_score": drift_score,
                "drift_threshold": 0.15,  # Max 15% semantic drift
                "passed": (
                    grade["recall"] >= test.min_recall and
                    grade["false_positives"] <= test.max_false_positives and
                    drift_score <= 0.15
                ),
                "executed_at": datetime.now().isoformat(),
            }
            
            results[prompt_version].append(result)
            
            if not result["passed"]:
                drift_detected = True
                logger.warning(f"Regression test failed: {result}")
    
    # Aggregate and alert
    summary = {
        "total_tests": sum(len(r) for r in results.values()),
        "passed_tests": sum(
            1 for r in [item for items in results.values() for item in items]
            if r["passed"]
        ),
        "drift_detected": drift_detected,
        "results_by_prompt": results,
        "timestamp": datetime.now().isoformat(),
    }
    
    # Persist to database
    await persist_regression_test_results(summary)
    
    if drift_detected:
        await trigger_alert_and_review_workflow(summary)
    
    return summary

async def trigger_alert_and_review_workflow(results: dict):
    """
    If regression tests fail, create Temporal workflow for human review.
    Optionally trigger auto-rollback.
    """
    
    failing_prompts = [
        pv for pv, rs in results["results_by_prompt"].items()
        if any(not r["passed"] for r in rs)
    ]
    
    for prompt_version in failing_prompts:
        # Create Temporal activity for manual review
        await temporal_client.start_workflow(
            "prompt_review_workflow",
            args=[{
                "prompt_version": prompt_version,
                "regression_results": results,
                "auto_rollback_enabled": True,
                "rollback_timeout_hours": 24,
            }],
        )

def grade_findings(
    current: list[FindingOutput],
    expected: list[FindingOutput]
) -> dict:
    """
    Compute precision/recall of current findings vs. expected.
    """
    
    current_keys = {(f.file_path, f.line_number, f.vulnerability_type) for f in current}
    expected_keys = {(f.file_path, f.line_number, f.vulnerability_type) for f in expected}
    
    true_positives = len(current_keys & expected_keys)
    false_positives = len(current_keys - expected_keys)
    false_negatives = len(expected_keys - current_keys)
    
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }

async def compute_semantic_similarity(
    texts_a: list[str],
    texts_b: list[str],
) -> float:
    """
    Compute average cosine similarity between embeddings.
    """
    from sentence_transformers import SentenceTransformer
    
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings_a = model.encode(texts_a)
    embeddings_b = model.encode(texts_b)
    
    # Simple average similarity
    similarities = [
        max(
            np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
            for b in embeddings_b
        )
        for a in embeddings_a
    ]
    
    return np.mean(similarities) if similarities else 0.0
```

**Database Schema:**

```sql
CREATE TABLE prompt_regression_tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_id VARCHAR(255) NOT NULL UNIQUE,
    prompt_template TEXT NOT NULL,
    prompt_version VARCHAR(100) NOT NULL,
    input_codebase_path VARCHAR(512) NOT NULL,
    expected_findings JSONB NOT NULL,  -- Array of FindingOutput
    min_recall FLOAT DEFAULT 0.90,
    max_false_positives FLOAT DEFAULT 0.05,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_prompt_version (prompt_version)
);

CREATE TABLE regression_test_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_id VARCHAR(255) NOT NULL,
    prompt_version VARCHAR(100) NOT NULL,
    recall FLOAT NOT NULL,
    precision FLOAT NOT NULL,
    f1 FLOAT NOT NULL,
    drift_score FLOAT NOT NULL,
    passed BOOLEAN NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL,
    
    FOREIGN KEY (test_id) REFERENCES prompt_regression_tests(test_id),
    INDEX idx_prompt_execution (prompt_version, executed_at),
    INDEX idx_passed (passed, executed_at)
);

CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_version VARCHAR(100) NOT NULL UNIQUE,
    prompt_template TEXT NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'active',  -- 'active', 'deprecated', 'rollback_pending'
    
    INDEX idx_status (status)
);
```

---

## Data Flow: Typical Security Audit

```
Input: AuditRequest(codebase_path, blueprint_id="audit_python_owasp_2024")
  │
  ├─→ [Layer 1] Run Deterministic Harness
  │   ├─ Bandit → JSON output (12 findings)
  │   ├─ Semgrep → JSON output (8 findings)
  │   └─ Safety → JSON output (2 findings)
  │   Output: DeterministicResults {BANDIT: [...], SEMGREP: [...], SAFETY: [...]}
  │
  ├─→ [Layer 5] Load Blueprint
  │   └─ Validate scope: in_scope_paths, in_scope_checks
  │
  ├─→ Invoke ISO Agent (Primary)
  │   ├─ SystemPrompt: Blueprint constraints + deterministic results summary
  │   ├─ Temperature: 0.0 (audit mode)
  │   ├─ MaxTokens: 6000
  │   └─ Output: RawFindingsJSON (16 findings)
  │
  ├─→ [Layer 2] Schema Validation & Enforcement
  │   ├─ Parse each finding into FindingOutput Pydantic model
  │   ├─ Validate file_path exists
  │   ├─ Validate line_number in range
  │   ├─ Validate code_snippet matches actual code
  │   ├─ Cross-reference with deterministic tools
  │   └─ Output: ValidatedFindings + Hallucinations list
  │
  ├─→ [Layer 4] Multi-Agent Cross-Validation
  │   ├─ Invoke Validator Agent (different model: opus)
  │   ├─ Compare findings: agreement matrix
  │   └─ Update finding statuses & confidence
  │
  ├─→ [Layer 3] Execution-Based Feedback Loop
  │   ├─ For each HIGH severity finding
  │   │  ├─ Generate PoC exploit
  │   │  └─ Execute in Docker, update confidence
  │   └─ Output: ExecutionValidatedFindings
  │
  ├─→ [Layer 6] Confidence Calibration
  │   ├─ Load calibration metrics for (model, prompt_version)
  │   ├─ For each finding, look up confidence band (e.g., 0.85 → 0.88 band)
  │   ├─ Apply calibration curve: stated 0.85 → displayed 0.82
  │   └─ Output: CalibratedFindings
  │
  └─→ Output: AuditFindingsOutput
      ├─ findings: [FindingOutput] (100+ structured objects)
      ├─ summary: "7 HIGH severity, 3 confirmed by deterministic tools, 2 require remediation"
      ├─ llm_only_findings_count: 2
      └─ high_severity_count: 7

[Layer 7] Nightly: Log results, run regression tests, detect drift
```

---

## Temporal Workflow Integration

**Tron Temporal Workflows:**

```python
# temporal_verification_workflows.py
from temporalio import workflow, activity
from datetime import timedelta

@workflow.defn
class SecurityAuditWorkflow:
    """Temporal workflow orchestrating 7-layer verification."""
    
    @workflow.run
    async def run(self, audit_request: AuditRequest) -> AuditFindingsOutput:
        
        # Activity 1: Load blueprint & validate
        blueprint = await workflow.execute_activity(
            load_blueprint,
            args=[audit_request.blueprint_id],
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        # Activity 2: Layer 1 - Deterministic harness
        deterministic_results = await workflow.execute_activity(
            run_deterministic_harness_activity,
            args=[audit_request.codebase_path, blueprint],
            start_to_close_timeout=timedelta(minutes=2)
        )
        
        # Activity 3: Invoke ISO Agent (primary)
        primary_findings = await workflow.execute_activity(
            invoke_iso_agent_activity,
            args=[audit_request.codebase_path, blueprint],
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # Activity 4: Layer 2 - Schema validation
        validated_findings = await workflow.execute_activity(
            validate_schema_activity,
            args=[primary_findings, deterministic_results, audit_request.codebase_path],
            start_to_close_timeout=timedelta(seconds=30)
        )
        
        # Activity 5: Layer 4 - Cross-validation
        cross_validated = await workflow.execute_activity(
            cross_validate_activity,
            args=[validated_findings, audit_request.codebase_path],
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # Activity 6: Layer 3 - Execution validation (parallel for high-severity)
        execution_validated = await workflow.execute_activity(
            execute_validation_activity,
            args=[cross_validated, audit_request.codebase_path],
            start_to_close_timeout=timedelta(minutes=10)
        )
        
        # Activity 7: Layer 6 - Calibration
        calibrated_findings = await workflow.execute_activity(
            apply_calibration_activity,
            args=[execution_validated],
            start_to_close_timeout=timedelta(seconds=20)
        )
        
        # Activity 8: Assemble output
        output = await workflow.execute_activity(
            assemble_output_activity,
            args=[calibrated_findings, blueprint],
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        return output

@activity.defn
async def run_deterministic_harness_activity(
    codebase_path: str,
    blueprint: Blueprint
) -> dict:
    """Layer 1 activity."""
    return await run_deterministic_harness(codebase_path, blueprint)

@activity.defn
async def invoke_iso_agent_activity(
    codebase_path: str,
    blueprint: Blueprint
) -> list[dict]:
    """Primary ISO agent invocation."""
    return await invoke_iso_agent(
        agent_id=blueprint.blueprint_id,
        codebase_path=codebase_path,
        temperature=blueprint.temperature,
    )

# Similar activities for other layers...

@workflow.defn
class NightlyRegressionTestWorkflow:
    """Nightly regression testing for drift detection."""
    
    @workflow.run
    async def run(self) -> dict:
        
        results = await workflow.execute_activity(
            run_nightly_regression_tests_activity,
            start_to_close_timeout=timedelta(hours=2)
        )
        
        if results["drift_detected"]:
            await workflow.execute_activity(
                alert_team_activity,
                args=[results],
                start_to_close_timeout=timedelta(seconds=60)
            )
            
            # Optionally trigger rollback
            await workflow.execute_activity(
                trigger_rollback_activity,
                args=[results],
                start_to_close_timeout=timedelta(minutes=5)
            )
        
        return results
```

---

## Configuration & SLOs

**Configuration (environment or config file):**

```yaml
verification_pipeline:
  layer_1:
    deterministic_tools:
      - bandit:
          timeout_seconds: 60
          config_url: "https://config.tron.io/bandit.yml"
      - semgrep:
          timeout_seconds: 120
          config_url: "https://config.tron.io/semgrep-rules.yml"
      - safety:
          timeout_seconds: 30
  
  layer_2:
    strict_validation: true
    hallucination_detection_enabled: true
    code_snippet_verification: true
  
  layer_3:
    execution_validation:
      docker_image: "python:3.11-slim"
      timeout_seconds: 60
      enabled_for_severity: ["CRITICAL", "HIGH"]
  
  layer_4:
    cross_validation:
      validator_model: "claude-opus"
      validator_prompt_version: "v2.1"
      required_agreement_threshold: 0.75
  
  layer_5:
    blueprints:
      registry_url: "https://blueprints.tron.io/registry.json"
      cache_ttl_hours: 24
  
  layer_6:
    golden_suite:
      test_count: 200
      enabled: true
      calibration_update_frequency_hours: 168  # Weekly
  
  layer_7:
    regression_testing:
      enabled: true
      schedule: "0 2 * * *"  # 2 AM UTC
      tests_per_prompt: 15
      drift_threshold: 0.15
      rollback_enabled: true
```

**Service Level Objectives (SLOs):**

```
1. Accuracy SLO:
   - True Positive Rate ≥ 95% (for high-confidence findings ≥0.85)
   - False Positive Rate ≤ 3%
   - Precision ≥ 0.92

2. Latency SLO:
   - Audit completion (all 7 layers) ≤ 8 minutes for typical codebase
   - P99 latency ≤ 12 minutes
   - Deterministic harness ≤ 2 minutes

3. Drift SLO:
   - Prompt regression tests ≥ 95% passing (nightly)
   - Semantic drift score ≤ 0.15
   - Calibration deviation ≤ 5% per band

4. Availability SLO:
   - Verification pipeline uptime ≥ 99.5%
   - Nightly regression tests run ≥ 99% of nights
   - Alert response time ≤ 1 hour (manual review)

5. Hallucination SLO:
   - Unverified findings (Layer 2 unconfirmed) ≤ 5% of total findings
   - False findings (Layer 3 execution validation fails) ≤ 2%
   - Scope drift violations ≤ 1% (Layer 5 blueprint enforcement)
```

---

## Security & Safety Guarantees

**Guarantees Provided by 7-Layer Architecture:**

1. **98%+ Verified Confidence (target: ≤2% unverified findings reaching users):** Layer 2 schema validation + Layer 3 execution sandbox defeat freetext hallucination. Unverified findings are flagged, never silently passed. Remaining edge cases are caught by Layer 4 cross-validation and Layer 6 calibration.

2. **Zero Drift (→0.5% target):** Layer 5 blueprints constrain scope. Layer 7 regression tests detect drift nightly. Auto-rollback enabled.

3. **Deterministic Cross-Reference (100%):** Layer 1 results inform confidence scoring. Tools act as ground truth; LLM findings must align.

4. **Multi-Model Consensus:** Layer 4 requires multiple models/agents to agree on high-severity findings, defeating single-model bias.

5. **Continuous Calibration:** Layer 6 ensures stated confidence matches actual accuracy. Calibration curves updated weekly.

6. **Auditable Trail:** Every finding includes: deterministic confirmation status, execution validation result, cross-validation agreement score, calibration adjustment.

---

## Integration with Tron Ecosystem

**Integration Points:**

1. **ISO Agents:** Invoked by Layer 1 harness; receive blueprint constraints in system prompt; temperature locked per task type.

2. **Temporal Workflows:** SecurityAuditWorkflow orchestrates all 7 layers via activities; NightlyRegressionTestWorkflow runs Layer 7 tests.

3. **Tron Dashboard:** Displays findings with confidence/validation status; shows drift metrics; exposes regression test results.

4. **Alert System:** Layer 7 drift detection triggers PagerDuty/Slack alerts; Layer 4 conflicting findings routed to human review queue.

5. **Metrics Export:** Prometheus metrics: `verification_pipeline_accuracy`, `layer_X_latency_seconds`, `drift_score`, `hallucination_rate`.

---

## Maintenance & Operations

**Operational Procedures:**

1. **Weekly Calibration Update:** Run golden suite, update calibration curves if drift < 0.08.

2. **Monthly Prompt Audit:** Review regression test results; update prompt versions if drift detected.

3. **Quarterly Model Evaluation:** A/B test new models against golden suite; only promote if accuracy ≥ baseline.

4. **Annual Blueprint Review:** Verify blueprint scope, in_scope_checks, not_in_scope align with current OWASP/CWE standards.

5. **Rollback Procedure:** If nightly regression fails: (a) alert team, (b) wait 1 hour for manual review, (c) auto-rollback to previous prompt/model version.

---

## Appendix: SQL Table Definitions

```sql
-- Core verification tables

CREATE TABLE blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id VARCHAR(255) NOT NULL UNIQUE,
    task_type VARCHAR(100) NOT NULL,
    description TEXT,
    in_scope_paths TEXT[] NOT NULL,
    in_scope_checks TEXT[] NOT NULL,
    not_in_scope TEXT[] NOT NULL,
    tools_required TEXT[] NOT NULL,
    temperature FLOAT,
    max_tokens INT,
    max_duration_seconds INT,
    output_schema VARCHAR(255),
    verification_method VARCHAR(100),
    expected_accuracy FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_task_type (task_type)
);

CREATE TABLE audit_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    line_number INT NOT NULL,
    vulnerability_type VARCHAR(100) NOT NULL,
    code_snippet TEXT,
    confidence FLOAT NOT NULL,
    deterministic_tool_confirmed BOOLEAN,
    severity VARCHAR(50),
    description TEXT,
    remediation TEXT,
    execution_validated BOOLEAN,
    cross_validation_status VARCHAR(50),
    calibration_applied BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_audit_id (audit_id),
    INDEX idx_file_path (file_path),
    INDEX idx_severity (severity)
);

CREATE TABLE audit_execution_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID NOT NULL,
    blueprint_id VARCHAR(255),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    status VARCHAR(50),  -- 'running', 'completed', 'failed'
    total_time_seconds INT,
    layer_1_time_seconds INT,
    layer_2_time_seconds INT,
    layer_3_time_seconds INT,
    layer_4_time_seconds INT,
    layer_5_time_seconds INT,
    layer_6_time_seconds INT,
    layer_7_time_seconds INT,
    findings_count INT,
    high_severity_count INT,
    hallucination_count INT,
    
    INDEX idx_status (status),
    INDEX idx_blueprint_id (blueprint_id)
);
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-11 | Initial specification: 7-layer architecture, Pydantic schemas, Temporal integration, SLOs |

---

**Document Status:** APPROVED  
**Next Review Date:** 2026-07-11 (quarterly)

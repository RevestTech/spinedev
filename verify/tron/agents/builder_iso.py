"""
BuilderISO — Build & dependency-focused ISO agent.

Analyzes Dockerfiles, CI/CD configs, dependency manifests, and build
configurations for misconfigurations, outdated dependencies, and supply
chain risks. Uses pip-audit/npm-audit as deterministic pre-pass, then
LLM analysis for config logic issues tools can't catch.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1.3
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tron.agents.base import (
    BaseISO,
    ISOConfig,
    ISOSpecialization,
    ToolResult,
)
from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest
from tron.services.threat_intel import ThreatIntelService
from tron.schemas.verification import (
    Blueprint,
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)


# ── File classifications ──────────────────────────────────────────────

# Files BuilderISO specifically targets
BUILD_FILE_PATTERNS = {
    "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
    "docker-compose.dev.yml", "docker-compose.prod.yml",
    ".dockerignore",
    "Makefile",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    ".github/workflows",
    "Procfile",
    "requirements.txt", "requirements-dev.txt",
    "setup.py", "setup.cfg", "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "build.gradle", "build.gradle.kts",
    "pom.xml",
    "CMakeLists.txt",
    "Gemfile",
    "tsconfig.json",
    "webpack.config.js", "webpack.config.ts",
    "vite.config.ts", "vite.config.js",
    ".eslintrc.json", ".eslintrc.js",
    ".babelrc",
    "babel.config.js",
    "nginx.conf",
    "terraform.tfvars",
}


def _is_build_file(path: str) -> bool:
    """Check if a file is build/config related."""
    filename = path.rsplit("/", 1)[-1] if "/" in path else path
    # Direct match
    if filename in BUILD_FILE_PATTERNS:
        return True
    # Pattern match
    lower = filename.lower()
    return (
        lower.startswith("dockerfile")
        or lower.endswith((".yml", ".yaml")) and any(
            kw in lower for kw in ("ci", "deploy", "build", "docker", "compose")
        )
        or lower.endswith((".tf", ".hcl"))
        or "github/workflows" in path.lower()
    )


class BuilderISO(BaseISO):
    """Build & dependency-specialized ISO agent.

    Pipeline:
        1. pip-audit / npm-audit — deterministic dependency vulnerability scan
        2. LLM analysis of Dockerfiles, CI configs, and dependency manifests
        3. Cross-reference: tool-confirmed dep vulns get full confidence
    """

    SPECIALIZATION = ISOSpecialization.BUILDER
    DEFAULT_TOOLS = ()  # pip-audit/npm-audit are optional; run if manifests exist

    SYSTEM_PROMPT = """\
You are BuilderISO, a build and infrastructure analysis agent in the Tron \
zero-drift verification pipeline. You analyze Dockerfiles, CI/CD configs, \
dependency manifests, and build configurations for misconfigurations.

CRITICAL: You MUST respond with ONLY a JSON array. Do NOT include any \
explanatory text, markdown formatting, or preamble. Your response must \
start with '[' and end with ']'.

RULES:
1. Only report real issues with clear impact. No style nits.
2. For each finding, provide: vulnerability type, severity, exact file \
and line, the problematic snippet, description, and a fix.
3. Focus on issues that matter for production:
   - Dockerfiles: running as root, unpinned base images, secrets in layers, \
missing health checks, unnecessary packages, exposed debug ports
   - Dependencies: known CVEs in direct OR deep packages (recursive dependencies \
resolved via PyPI, NPM, etc. that may have vulnerabilities), wildcard versions, \
unnecessary dev deps in prod, supply chain risks
   - CI/CD: secrets in plain text, missing artifact verification, \
insecure registry configs, missing branch protection
   - Build configs: debug mode in production, permissive CORS, \
insecure default settings, general cybersecurity weaknesses
4. Do NOT report: cosmetic issues, missing comments, style preferences.

OUTPUT FORMAT (pure JSON array, NO other text):
[
  {
    "vulnerability_type": "<one of: security_misconfiguration, \
dependency_vulnerability, hardcoded_secrets, command_injection, other>",
    "severity": "<critical|high|medium|low|info>",
    "file_path": "<relative path>",
    "line_number": <int>,
    "line_end": <int or null>,
    "code_snippet": "<the problematic code>",
    "description": "<what the issue is and its production impact>",
    "fix_suggestion": "<how to fix it with a concrete example>",
    "confidence": <float 0.0-1.0>
  }
]

If you find no issues, return: []

Remember: ONLY JSON. No preamble, no explanation, no markdown.
"""

    def __init__(
        self,
        config: ISOConfig,
        secrets: Dict[str, str],
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        super().__init__(config, secrets)
        self._threat_intel = ThreatIntelService()
        if llm_client:
            self._llm = llm_client
        else:
            self._llm = LLMClient(
                anthropic_key=secrets.get("llm/anthropic-key"),
                openai_key=secrets.get("llm/openai-key"),
            )

    # ── Core Analysis ──────────────────────────────────────────────

    async def _analyze(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> List[FindingOutput]:
        """Run LLM build/config analysis with Threat Intel integration."""

        # Real-time threat sweep
        dependencies = []
        for tool_res in tool_results.values():
            for f in tool_res.raw_findings:
                if f.get("package") and f.get("version"):
                    dependencies.append({
                        "name": f["package"],
                        "version": f["version"],
                        "ecosystem": "PyPI" if tool_res.tool_name == "pip-audit" else "NPM"
                    })
        
        threats = await self._threat_intel.batch_check_dependencies(dependencies)
        malicious_warnings = []
        for pkg, vulns in threats.items():
            malicious_warnings.extend(self._threat_intel.identify_malicious_patterns(vulns))

        if self._metrics and malicious_warnings:
            self._metrics.threat_intel_alerts.extend(malicious_warnings)

        # Filter to build-relevant files, plus include a sample of other
        # files for context (the LLM needs to see what language the project uses)
        build_files = {
            p: c for p, c in file_contents.items() if _is_build_file(p)
        }
        # If no build files found, include all files (small projects)
        if not build_files:
            build_files = file_contents

        budget = blueprint.max_tokens - 1500
        trimmed = self._truncate_to_budget(build_files, max(budget, 500))

        prompt = self._build_prompt(blueprint, trimmed, tool_results, malicious_warnings)

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ],
            model=self.config.model_name,
            temperature=blueprint.temperature,
            max_tokens=4096,  # LLM *output* limit (Haiku max); file budget is separate
            json_mode=True,
        )

        response = await self._llm.complete(request)

        if self._metrics:
            self._metrics.llm_calls += 1
            self._metrics.llm_tokens_used += response.total_tokens
            self._metrics.llm_cost_usd += response.cost_usd

        return self._parse_llm_response(response.content, blueprint)

    # ── Prompt Construction ────────────────────────────────────────

    def _build_prompt(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
        malicious_warnings: Optional[List[str]] = None,
    ) -> str:
        """Build prompt with build files and dependency tool results."""
        parts: List[str] = []

        if malicious_warnings:
            parts.append("## CRITICAL THREAT INTELLIGENCE ALERTS")
            parts.append("The following packages have LIVE ADVISORIES indicating malicious backdoors:")
            for warn in malicious_warnings:
                parts.append(f"  - {warn}")
            parts.append("PROMPT: Analyze these packages with extreme scrutiny. Flag them if they are in the dependency manifests.")
            parts.append("")

        parts.append(f"## Blueprint: {blueprint.name}")
        parts.append(f"Description: {blueprint.description}")
        parts.append(f"Languages: {', '.join(blueprint.scope.languages)}")
        parts.append("")

        # Tool results (pip-audit, npm-audit, etc.)
        if tool_results:
            parts.append("## Dependency Audit Results")
            for tool_name, result in tool_results.items():
                parts.append(f"### {tool_name} (exit code: {result.exit_code})")
                if result.findings_count > 0:
                    parts.append(f"Found {result.findings_count} vulnerabilities:")
                    for tf in result.raw_findings[:30]:
                        parts.append(
                            f"  - {tf.get('package', '?')} {tf.get('version', '?')}: "
                            f"{tf.get('description', tf.get('advisory', ''))[:120]}"
                        )
                else:
                    parts.append("No vulnerabilities found.")
                parts.append("")

        # Build/config files
        parts.append("## Build & Configuration Files to Analyze")
        for path, content in file_contents.items():
            parts.append(f"### {path}")
            parts.append("```")
            parts.append(content)
            parts.append("```")
            parts.append("")

        parts.append(
            "Analyze the build configurations, Dockerfiles, CI/CD pipelines, "
            "and dependency manifests above. Return a JSON array of findings."
        )

        return "\n".join(parts)

    # ── Response Parsing ───────────────────────────────────────────

    def _parse_llm_response(
        self,
        raw_response: str,
        blueprint: Blueprint,
    ) -> List[FindingOutput]:
        """Parse LLM JSON response into FindingOutput objects."""
        text = raw_response.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Strip preamble text before JSON
        for i, char in enumerate(text):
            if char in ("[", "{"):
                text = text[i:]
                break

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("BuilderISO: failed to parse LLM response: %s", exc)
            return []

        if not isinstance(data, list):
            if isinstance(data, dict) and "findings" in data:
                data = data["findings"]
            else:
                logger.warning("BuilderISO: LLM response is not a list")
                return []

        findings: List[FindingOutput] = []

        for i, item in enumerate(data):
            try:
                # Map vulnerability types, with fallback
                vuln_type_str = item.get("vulnerability_type", "other")
                try:
                    vuln_type = VulnerabilityType(vuln_type_str)
                except ValueError:
                    vuln_type = VulnerabilityType.OTHER

                finding = FindingOutput(
                    id=uuid4(),
                    vulnerability_type=vuln_type,
                    severity=SeverityLevel(item.get("severity", "medium")),
                    file_path=item.get("file_path", "unknown"),
                    line_number=max(1, int(item.get("line_number", 1))),
                    line_end=item.get("line_end"),
                    code_snippet=item.get("code_snippet", "# no snippet"),
                    description=item.get("description", ""),
                    fix_suggestion=item.get("fix_suggestion"),
                    confidence=min(float(item.get("confidence", 0.5)), 0.7),
                    deterministic_tool_confirmed=False,
                    agent_id=self.config.agent_id,
                    blueprint_id=blueprint.id,
                    finding_fingerprint="pending",
                    cross_validation_status=CrossValidationStatus.PENDING,
                )
                findings.append(finding)
            except Exception as exc:
                logger.warning("BuilderISO: skipping finding #%d: %s", i, exc)
                continue

        logger.info("BuilderISO: parsed %d findings", len(findings))
        return findings

    # ── Deterministic Tool Execution ───────────────────────────────

    async def _execute_tool(
        self,
        tool_name: str,
        workspace_root: str,
    ) -> ToolResult:
        """Execute pip-audit or npm-audit."""
        if tool_name == "pip-audit":
            return await self._run_pip_audit(workspace_root)
        elif tool_name == "npm-audit":
            return await self._run_npm_audit(workspace_root)
        else:
            return await super()._execute_tool(tool_name, workspace_root)

    async def _run_pip_audit(self, workspace_root: str) -> ToolResult:
        """Run pip-audit for Python dependency vulnerabilities."""
        cmd = [
            "pip-audit",
            "-r", f"{workspace_root}/requirements.txt",
            "-f", "json",
            "--progress-spinner", "off",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )
        except (asyncio.TimeoutError, FileNotFoundError) as exc:
            return ToolResult(
                tool_name="pip-audit",
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_seconds=0.0,
            )

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        raw_findings: List[Dict[str, Any]] = []
        try:
            if stdout_str.strip():
                audit_data = json.loads(stdout_str)
                for dep in audit_data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        raw_findings.append({
                            "package": dep.get("name", ""),
                            "version": dep.get("version", ""),
                            "vuln_id": vuln.get("id", ""),
                            "description": vuln.get("description", ""),
                            "fix_versions": vuln.get("fix_versions", []),
                            "file": "requirements.txt",
                            "line": 0,
                        })
        except json.JSONDecodeError:
            logger.warning("pip-audit output was not valid JSON")

        return ToolResult(
            tool_name="pip-audit",
            exit_code=proc.returncode or 0,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_seconds=0.0,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

    async def _run_npm_audit(self, workspace_root: str) -> ToolResult:
        """Run npm audit for Node.js dependency vulnerabilities."""
        cmd = [
            "npm", "audit",
            "--json",
            "--prefix", workspace_root,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )
        except (asyncio.TimeoutError, FileNotFoundError) as exc:
            return ToolResult(
                tool_name="npm-audit",
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_seconds=0.0,
            )

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        raw_findings: List[Dict[str, Any]] = []
        try:
            if stdout_str.strip():
                audit_data = json.loads(stdout_str)
                for name, advisory in audit_data.get("vulnerabilities", {}).items():
                    raw_findings.append({
                        "package": name,
                        "severity": advisory.get("severity", ""),
                        "advisory": advisory.get("title", ""),
                        "via": str(advisory.get("via", "")),
                        "file": "package.json",
                        "line": 0,
                    })
        except json.JSONDecodeError:
            logger.warning("npm audit output was not valid JSON")

        return ToolResult(
            tool_name="npm-audit",
            exit_code=proc.returncode or 0,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_seconds=0.0,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

"""
SecurityISO — Security-focused ISO agent.

Runs Bandit + Semgrep as deterministic pre-pass, then uses an LLM to
analyze code for vulnerabilities that static tools miss (logic bugs,
auth flaws, business-logic vulns). Findings from deterministic tools
get elevated confidence; LLM-only findings are capped at 0.7 per the
verification schema.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1.2
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tron.agents.base import (
    BaseISO,
    ISOConfig,
    ISOSpecialization,
    ToolResult,
)
from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest
from tron.schemas.verification import (
    Blueprint,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
    CrossValidationStatus,
)

logger = logging.getLogger(__name__)


# ── Bandit severity/confidence mapping ─────────────────────────────────

BANDIT_SEVERITY_MAP = {
    "HIGH": SeverityLevel.HIGH,
    "MEDIUM": SeverityLevel.MEDIUM,
    "LOW": SeverityLevel.LOW,
    "UNDEFINED": SeverityLevel.INFO,
}

BANDIT_VULN_TYPE_MAP = {
    "B101": VulnerabilityType.OTHER,                    # assert
    "B102": VulnerabilityType.COMMAND_INJECTION,        # exec
    "B103": VulnerabilityType.SECURITY_MISCONFIGURATION,# chmod
    "B104": VulnerabilityType.SECURITY_MISCONFIGURATION,# bind 0.0.0.0
    "B105": VulnerabilityType.HARDCODED_SECRETS,        # hardcoded password
    "B106": VulnerabilityType.HARDCODED_SECRETS,        # hardcoded password arg
    "B107": VulnerabilityType.HARDCODED_SECRETS,        # hardcoded password default
    "B108": VulnerabilityType.PATH_TRAVERSAL,           # hardcoded tmp
    "B110": VulnerabilityType.OTHER,                    # try-except-pass
    "B112": VulnerabilityType.OTHER,                    # try-except-continue
    "B201": VulnerabilityType.COMMAND_INJECTION,        # flask debug
    "B301": VulnerabilityType.INSECURE_DESERIALIZATION, # pickle
    "B302": VulnerabilityType.INSECURE_DESERIALIZATION, # marshal
    "B303": VulnerabilityType.SECURITY_MISCONFIGURATION,# md5/sha1
    "B304": VulnerabilityType.SECURITY_MISCONFIGURATION,# insecure cipher
    "B305": VulnerabilityType.SECURITY_MISCONFIGURATION,# insecure cipher mode
    "B306": VulnerabilityType.SECURITY_MISCONFIGURATION,# mktemp
    "B307": VulnerabilityType.COMMAND_INJECTION,        # eval
    "B308": VulnerabilityType.XSS,                      # mark_safe
    "B310": VulnerabilityType.SSRF,                     # urllib urlopen
    "B311": VulnerabilityType.SECURITY_MISCONFIGURATION,# random
    "B312": VulnerabilityType.SSRF,                     # telnet
    "B313": VulnerabilityType.XSS,                      # xml parse
    "B320": VulnerabilityType.XSS,                      # lxml
    "B321": VulnerabilityType.SECURITY_MISCONFIGURATION,# ftp
    "B323": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssl unverified
    "B324": VulnerabilityType.SECURITY_MISCONFIGURATION,# hashlib insecure
    "B501": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssl no verify
    "B502": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssl bad version
    "B503": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssl bad defaults
    "B504": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssl no cert verify
    "B505": VulnerabilityType.SECURITY_MISCONFIGURATION,# weak crypto key
    "B506": VulnerabilityType.SECURITY_MISCONFIGURATION,# yaml load
    "B507": VulnerabilityType.SECURITY_MISCONFIGURATION,# ssh no host key
    "B601": VulnerabilityType.COMMAND_INJECTION,        # paramiko shell
    "B602": VulnerabilityType.COMMAND_INJECTION,        # subprocess shell
    "B603": VulnerabilityType.COMMAND_INJECTION,        # subprocess no shell
    "B604": VulnerabilityType.COMMAND_INJECTION,        # any other function
    "B605": VulnerabilityType.COMMAND_INJECTION,        # os.system
    "B606": VulnerabilityType.COMMAND_INJECTION,        # os.popen
    "B607": VulnerabilityType.COMMAND_INJECTION,        # partial path
    "B608": VulnerabilityType.SQL_INJECTION,            # sql injection
    "B609": VulnerabilityType.COMMAND_INJECTION,        # wildcard injection
    "B610": VulnerabilityType.SQL_INJECTION,            # django extra
    "B611": VulnerabilityType.SQL_INJECTION,            # django raw sql
    "B701": VulnerabilityType.XSS,                      # jinja2 autoescape
    "B702": VulnerabilityType.XSS,                      # mako templates
    "B703": VulnerabilityType.XSS,                      # django mark_safe
}


# ── SecurityISO Agent ──────────────────────────────────────────────────


class SecurityISO(BaseISO):
    """Security-specialized ISO agent.

    Pipeline:
        1. Bandit (Python security linter) — deterministic
        2. Semgrep (multi-language patterns) — deterministic
        3. LLM analysis with tool results as context
        4. Cross-reference: LLM findings confirmed by tools get full confidence
    """

    SPECIALIZATION = ISOSpecialization.SECURITY
    # Safety runs only when a Python requirements manifest is in the file set;
    # ESLint runs only when JS/TS files are present (closes the long-standing
    # "Python-only deterministic baseline" gap). Bandit + Semgrep run on every
    # SecurityISO invocation; the runners themselves no-op when they have
    # nothing to scan.
    DEFAULT_TOOLS = ("bandit", "semgrep", "safety", "eslint")

    SYSTEM_PROMPT = """\
You are SecurityISO, a security-focused code analysis agent in the Tron \
zero-drift verification pipeline. Your role is to identify security \
vulnerabilities in source code with high precision, hack-proofing the \
system against advanced cybersecurity threats.

CRITICAL: You MUST respond with ONLY a JSON array. Do NOT include any \
explanatory text, markdown formatting, or preamble. Your response must \
start with '[' and end with ']'.

RULES:
1. Only report vulnerabilities you are confident about. False positives \
erode trust.
2. For each finding, provide: vulnerability type, severity, exact file \
and line, the vulnerable code snippet, a clear description, and a fix.
3. You will receive results from Bandit and Semgrep. Cross-reference \
your findings with theirs. If a tool already found it, note that.
4. Focus on vulnerabilities that static tools MISS: logic bugs, auth \
bypass, business logic flaws, race conditions, TOCTOU issues.
5. Additionally scrutinize patterns associated with **insider threats, \
backdoors, and supply-chain abuse** when evidenced in code: e.g. suspicious \
dynamic execution or decoding of payloads; unexplained outbound URLs or IPs; \
credential exfiltration patterns; persistence hooks unrelated to product \
features; typosquatted imports or dependency gates—report only when you \
can point to concrete lines (avoid paranoid noise).
6. Do NOT report style issues, performance issues, or non-security \
concerns.

OUTPUT FORMAT (pure JSON array, NO other text):
[
  {
    "vulnerability_type": "<one of: sql_injection, xss, hardcoded_secrets, \
insecure_deserialization, broken_auth, security_misconfiguration, ssrf, \
path_traversal, command_injection, open_redirect, insufficient_logging, \
dependency_vulnerability, other>",
    "severity": "<critical|high|medium|low|info>",
    "file_path": "<relative path>",
    "line_number": <int>,
    "line_end": <int or null>,
    "code_snippet": "<the vulnerable code>",
    "description": "<what the vulnerability is and why it matters>",
    "fix_suggestion": "<how to fix it>",
    "confidence": <float 0.0-1.0>
  }
]

If you find no vulnerabilities, return: []

Remember: ONLY JSON. No preamble, no explanation, no markdown.
"""

    def __init__(
        self,
        config: ISOConfig,
        secrets: Dict[str, str],
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        super().__init__(config, secrets)
        # Use injected client or create one
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
        """Run LLM security analysis with tool results as context."""

        # Fit file contents within token budget (reserve ~1500 for prompt + tools)
        budget = blueprint.max_tokens - 1500
        trimmed_files = self._truncate_to_budget(file_contents, max(budget, 500))

        prompt = self._build_prompt(blueprint, trimmed_files, tool_results)

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

        # Track metrics
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
    ) -> str:
        """Build the user prompt with file contents and tool results."""
        parts: List[str] = []

        # Blueprint context
        parts.append(f"## Blueprint: {blueprint.name}")
        parts.append(f"Description: {blueprint.description}")
        parts.append(
            f"Check types: {', '.join(ct.value for ct in blueprint.scope.check_types)}"
        )
        parts.append(
            f"Languages: {', '.join(blueprint.scope.languages)}"
        )

        not_in_scope = self._format_not_in_scope_instruction(blueprint)
        if not_in_scope:
            parts.append(not_in_scope)

        parts.append("")

        # Deterministic tool results
        if tool_results:
            parts.append("## Deterministic Tool Results")
            for tool_name, result in tool_results.items():
                parts.append(f"### {tool_name} (exit code: {result.exit_code})")
                if result.findings_count > 0:
                    parts.append(f"Found {result.findings_count} issues:")
                    # Include a summary of tool findings (not full output)
                    for tf in result.raw_findings[:50]:  # Cap at 50
                        parts.append(
                            f"  - {tf.get('file', '?')}:{tf.get('line', '?')} "
                            f"[{tf.get('test_id', tf.get('rule_id', '?'))}] "
                            f"{tf.get('issue_text', tf.get('message', ''))[:120]}"
                        )
                else:
                    parts.append("No issues found.")
                parts.append("")

        # Source code
        parts.append("## Source Code to Analyze")
        for path, content in file_contents.items():
            parts.append(f"### {path}")
            parts.append("```")
            parts.append(content)
            parts.append("```")
            parts.append("")

        parts.append(
            "Analyze the code above for security vulnerabilities. "
            "Return a JSON array of findings."
        )

        return "\n".join(parts)

    # ── Response Parsing ───────────────────────────────────────────

    def _parse_llm_response(
        self,
        raw_response: str,
        blueprint: Blueprint,
    ) -> List[FindingOutput]:
        """Parse the LLM JSON response into FindingOutput objects."""
        text = raw_response.strip()

        # Handle markdown code blocks
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
            logger.warning(
                "SecurityISO: failed to parse LLM response as JSON: %s", exc
            )
            logger.debug("Raw response: %s", raw_response[:500])
            return []

        if not isinstance(data, list):
            # Maybe the LLM wrapped it in an object
            if isinstance(data, dict) and "findings" in data:
                data = data["findings"]
            else:
                logger.warning("SecurityISO: LLM response is not a list")
                return []

        findings: List[FindingOutput] = []

        for i, item in enumerate(data):
            try:
                finding = FindingOutput(
                    id=uuid4(),
                    vulnerability_type=VulnerabilityType(
                        item.get("vulnerability_type", "other")
                    ),
                    severity=SeverityLevel(
                        item.get("severity", "medium")
                    ),
                    file_path=item.get("file_path", "unknown"),
                    line_number=max(1, int(item.get("line_number", 1))),
                    line_end=item.get("line_end"),
                    code_snippet=item.get("code_snippet", "# no snippet"),
                    description=item.get("description", ""),
                    fix_suggestion=item.get("fix_suggestion"),
                    confidence=min(
                        float(item.get("confidence", 0.5)), 0.7
                    ),  # Cap at 0.7 — not yet tool-confirmed
                    deterministic_tool_confirmed=False,
                    agent_id=self.config.agent_id,
                    blueprint_id=blueprint.id,
                    finding_fingerprint="pending",  # Set in post-process
                    cross_validation_status=CrossValidationStatus.PENDING,
                )
                findings.append(finding)

            except Exception as exc:
                logger.warning(
                    "SecurityISO: skipping malformed finding #%d: %s", i, exc
                )
                continue

        logger.info(
            "SecurityISO: parsed %d findings from LLM response", len(findings)
        )
        return findings

    # ── Deterministic Tool Execution ───────────────────────────────

    async def _execute_tool(
        self,
        tool_name: str,
        workspace_root: str,
        file_contents: Optional[Dict[str, str]] = None,
    ) -> ToolResult:
        """Execute Bandit / Semgrep / Safety / ESLint in the sandbox."""
        if tool_name not in ("bandit", "semgrep", "safety", "eslint"):
            return await super()._execute_tool(tool_name, workspace_root, file_contents)

        # To run Bandit/Semgrep, we need actual files on disk.
        # In isolated container mode, we write the provided file_contents
        # to a temporary directory and use that as the sandbox workdir.
        if not file_contents:
            logger.warning("SecurityISO: No file_contents for %s, skipping tool", tool_name)
            return ToolResult(
                tool_name=tool_name,
                exit_code=-1,
                stdout="",
                stderr="No file_contents provided",
                duration_seconds=0.0,
            )

        temp_dir = tempfile.mkdtemp(prefix=f"tron-security-{tool_name}-")
        try:
            # Write files to temp dir
            for rel_path, content in file_contents.items():
                p = Path(temp_dir) / rel_path.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8", errors="replace")

            if tool_name == "bandit":
                return await self._run_bandit(temp_dir)
            elif tool_name == "semgrep":
                return await self._run_semgrep(temp_dir)
            elif tool_name == "safety":
                return await self._run_safety(temp_dir, file_contents or {})
            else:  # eslint
                return await self._run_eslint(temp_dir, file_contents or {})

        except Exception as exc:
            logger.exception("SecurityISO: Failed to prepare files for %s", tool_name)
            return ToolResult(
                tool_name=tool_name,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_seconds=0.0,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _run_bandit(self, workspace_root: str) -> ToolResult:
        """Run Bandit Python security scanner via sandbox."""
        cmd = [
            "bandit",
            "-r", ".",
            "-f", "json",
            "--severity-level", "low",
            "--confidence-level", "low",
            "-q",
        ]
        bash_cmd = " ".join(cmd)

        sandbox = await self._get_sandbox()
        start_time = asyncio.get_event_loop().time()
        
        # Execute via SandboxClient
        result = await sandbox.run_bash(bash_cmd, workdir=workspace_root)
        duration = asyncio.get_event_loop().time() - start_time

        # Parse Bandit JSON output
        raw_findings: List[Dict[str, Any]] = []
        try:
            if result.stdout.strip():
                bandit_data = json.loads(result.stdout)
                for res in bandit_data.get("results", []):
                    raw_findings.append({
                        "file": res.get("filename", ""),
                        "line": res.get("line_number", 0),
                        "test_id": res.get("test_id", ""),
                        "issue_text": res.get("issue_text", ""),
                        "severity": res.get("issue_severity", ""),
                        "confidence": res.get("issue_confidence", ""),
                        "code": res.get("code", ""),
                    })
        except json.JSONDecodeError:
            if result.exit_code != 0:
                logger.warning("Bandit failed (exit %d): %s", result.exit_code, result.stderr)
            else:
                logger.warning("Bandit output was not valid JSON")

        return ToolResult(
            tool_name="bandit",
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

    async def _run_semgrep(self, workspace_root: str) -> ToolResult:
        """Run Semgrep security scanner via sandbox."""
        cmd = [
            "semgrep",
            "--config", "auto",
            "--json",
            "--quiet",
            ".",
        ]
        bash_cmd = " ".join(cmd)

        sandbox = await self._get_sandbox()
        start_time = asyncio.get_event_loop().time()
        
        # Execute via SandboxClient
        result = await sandbox.run_bash(bash_cmd, workdir=workspace_root)
        duration = asyncio.get_event_loop().time() - start_time

        # Parse Semgrep JSON output
        raw_findings: List[Dict[str, Any]] = []
        try:
            if result.stdout.strip():
                semgrep_data = json.loads(result.stdout)
                for res in semgrep_data.get("results", []):
                    raw_findings.append({
                        "file": res.get("path", ""),
                        "line": res.get("start", {}).get("line", 0),
                        "rule_id": res.get("check_id", ""),
                        "message": res.get("extra", {}).get("message", ""),
                        "severity": res.get("extra", {}).get("severity", ""),
                        "metadata": res.get("extra", {}).get("metadata", {}),
                    })
        except json.JSONDecodeError:
            if result.exit_code != 0:
                logger.warning("Semgrep failed (exit %d): %s", result.exit_code, result.stderr)
            else:
                logger.warning("Semgrep output was not valid JSON")

        return ToolResult(
            tool_name="semgrep",
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

    async def _run_safety(
        self,
        workspace_root: str,
        file_contents: Dict[str, str],
    ) -> ToolResult:
        """Run pyup.io's `safety` against any Python requirements manifest in
        the scanned tree. Reports known-vulnerable dependency versions.

        Behaviour:
          * No requirements*.txt / Pipfile / pyproject.toml in the file set
            → return an empty ToolResult with exit_code=0 (silent no-op).
          * One or more manifests → run ``safety check --file <path> --json``
            for each, accumulate the JSON vulnerabilities into raw_findings.
          * Unparseable JSON or missing binary → log + return exit_code=-1
            with the stderr captured. We still continue the audit; Safety
            is augmentative, not gating.
        """
        # Find Python dependency manifests in the scanned files.
        manifests = [
            p for p in file_contents.keys()
            if (
                p.endswith("requirements.txt")
                or p.endswith("requirements-dev.txt")
                or p.endswith("requirements-prod.txt")
                or p.split("/")[-1].startswith("requirements") and p.endswith(".txt")
            )
        ]
        if not manifests:
            # Pure no-op — Safety only makes sense with a Python deps file.
            # Return a clean 0-exit so downstream code doesn't treat the
            # absence as an error.
            return ToolResult(
                tool_name="safety",
                exit_code=0,
                stdout="",
                stderr="(no Python requirements manifest in scope)",
                duration_seconds=0.0,
                findings_count=0,
                raw_findings=[],
            )

        sandbox = await self._get_sandbox()
        start_time = asyncio.get_event_loop().time()

        # safety v3 uses ``scan``; v2 uses ``check``. We invoke through bash
        # so we can fall back transparently if the installed version is
        # different on the sandbox image.
        commands = " || ".join(
            f"safety check --file {m} --json --disable-optional-telemetry"
            for m in manifests
        )
        result = await sandbox.run_bash(commands, workdir=workspace_root)
        duration = asyncio.get_event_loop().time() - start_time

        raw_findings: List[Dict[str, Any]] = []
        try:
            stdout = result.stdout.strip() or "[]"
            payload = json.loads(stdout)
            # Safety v3 returns a dict with "vulnerabilities"; v2 returns a list.
            vulns = (
                payload.get("vulnerabilities", [])
                if isinstance(payload, dict)
                else payload
            )
            for v in vulns:
                raw_findings.append({
                    "package": v.get("package_name") or v.get("package", ""),
                    "installed_version": v.get("analyzed_version")
                        or v.get("installed_version", ""),
                    "vulnerability_id": v.get("vulnerability_id")
                        or v.get("id", ""),
                    "advisory": v.get("advisory")
                        or v.get("vulnerable_spec", ""),
                    "cve": v.get("CVE") or v.get("cve", ""),
                    "more_info_url": v.get("more_info_url", ""),
                })
        except (json.JSONDecodeError, TypeError):
            # Safety exits non-zero when vulns are found — not an error per
            # se. Only warn if BOTH the parse failed AND exit was non-zero
            # AND stderr looks like a real failure.
            if result.exit_code != 0 and result.stderr:
                logger.warning(
                    "Safety check returned non-JSON (exit %d): %s",
                    result.exit_code,
                    result.stderr[:200],
                )

        return ToolResult(
            tool_name="safety",
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

    async def _run_eslint(
        self,
        workspace_root: str,
        file_contents: Dict[str, str],
    ) -> ToolResult:
        """Run ESLint with security-focused rulesets against JS/TS files.

        Closes the long-standing Python-only deterministic baseline gap.
        Behaviour mirrors `_run_safety`: silent no-op when no JS/TS files
        are in scope, doesn't raise when the binary is missing, parses
        ESLint's JSON output into ``raw_findings`` keyed for downstream
        confirmation matching.

        Configuration:
          * ``--no-eslintrc`` — ignore any project-side ``.eslintrc`` so
            consumers don't accidentally inherit rules they didn't ask for.
          * ``--rule`` flags load ``eslint-plugin-security`` rules
            individually, which means we don't need that plugin installed
            on the sandbox image to run *some* of the checks (security/...
            rules are optional and only fire when the plugin is present;
            absent plugin = those rules silently no-op, which is what we
            want).
          * ``--format json`` — machine-readable output.
          * ``--ext .js,.jsx,.ts,.tsx,.mjs,.cjs`` — scoped extensions.
        """
        js_files = [
            p for p in file_contents.keys()
            if any(
                p.endswith(ext)
                for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
            )
        ]
        if not js_files:
            return ToolResult(
                tool_name="eslint",
                exit_code=0,
                stdout="",
                stderr="(no JS/TS files in scope)",
                duration_seconds=0.0,
                findings_count=0,
                raw_findings=[],
            )

        sandbox = await self._get_sandbox()
        start_time = asyncio.get_event_loop().time()

        # ``|| true`` so ESLint's non-zero "lint errors found" exit doesn't
        # short-circuit the bash chain. We read the JSON regardless.
        bash_cmd = (
            "eslint --no-eslintrc --format json "
            "--ext .js,.jsx,.ts,.tsx,.mjs,.cjs "
            "--plugin security "
            "--rule 'security/detect-eval-with-expression: error' "
            "--rule 'security/detect-non-literal-fs-filename: error' "
            "--rule 'security/detect-non-literal-regexp: warn' "
            "--rule 'security/detect-non-literal-require: warn' "
            "--rule 'security/detect-object-injection: warn' "
            "--rule 'security/detect-unsafe-regex: error' "
            "--rule 'security/detect-buffer-noassert: error' "
            "--rule 'security/detect-child-process: warn' "
            "--rule 'security/detect-disable-mustache-escape: error' "
            "--rule 'security/detect-no-csrf-before-method-override: error' "
            "--rule 'security/detect-possible-timing-attacks: warn' "
            "--rule 'security/detect-pseudoRandomBytes: warn' "
            ". || true"
        )
        result = await sandbox.run_bash(bash_cmd, workdir=workspace_root)
        duration = asyncio.get_event_loop().time() - start_time

        raw_findings: List[Dict[str, Any]] = []
        try:
            stdout = (result.stdout or "").strip() or "[]"
            payload = json.loads(stdout)
            # ESLint JSON: list of {filePath, messages: [{ruleId, severity,
            # message, line, column, ...}]}
            for file_entry in payload:
                file_path = file_entry.get("filePath", "")
                # Strip the temp-dir prefix so file_path matches what the
                # LLM saw — confirmation matching depends on exact paths.
                if file_path.startswith(workspace_root):
                    file_path = file_path[len(workspace_root):].lstrip("/")
                for msg in file_entry.get("messages", []):
                    raw_findings.append({
                        "file": file_path,
                        "line": msg.get("line", 0),
                        "column": msg.get("column", 0),
                        "rule_id": msg.get("ruleId", ""),
                        "severity": msg.get("severity", 0),  # 1=warn, 2=error
                        "message": msg.get("message", ""),
                        "fixable": bool(msg.get("fix")),
                    })
        except (json.JSONDecodeError, TypeError):
            # ESLint not installed on the sandbox image, or JSON malformed.
            # Don't gate the audit on ESLint availability.
            if result.exit_code not in (0, 1, 2) and result.stderr:
                logger.warning(
                    "ESLint returned non-JSON (exit %d): %s",
                    result.exit_code,
                    result.stderr[:200],
                )

        return ToolResult(
            tool_name="eslint",
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            findings_count=len(raw_findings),
            raw_findings=raw_findings,
        )

    # ── Tool Confirmation Override ─────────────────────────────────

    def _check_tool_confirmation(
        self,
        finding: FindingOutput,
        tool_results: Dict[str, ToolResult],
    ) -> List[str]:
        """Enhanced tool confirmation with Bandit/Semgrep-specific matching."""
        confirming: List[str] = []

        for tool_name, result in tool_results.items():
            if not result.success and result.exit_code not in (0, 1):
                # Bandit/Semgrep return 1 when findings exist — that's OK
                continue

            for tf in result.raw_findings:
                tool_file = str(tf.get("file", tf.get("path", "")))
                tool_line = int(tf.get("line", tf.get("line_number", 0)))

                if not self._paths_match(finding.file_path, tool_file):
                    continue

                # Line proximity check (tools sometimes report ±5 lines)
                if abs(finding.line_number - tool_line) <= 5:
                    confirming.append(tool_name)
                    break

        return confirming

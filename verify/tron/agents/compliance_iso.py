"""ComplianceISO — regulatory / policy alignment heuristics (LLM-assisted)."""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional
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
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)

COMP_MAP = {
    "soc2": VulnerabilityType.SECURITY_MISCONFIGURATION,
    "iso27001": VulnerabilityType.SECURITY_MISCONFIGURATION,
    "hipaa": VulnerabilityType.SECURITY_MISCONFIGURATION,
    "pci": VulnerabilityType.SECURITY_MISCONFIGURATION,
    "privacy": VulnerabilityType.INSUFFICIENT_LOGGING,
    "audit_logging": VulnerabilityType.INSUFFICIENT_LOGGING,
    "data_retention": VulnerabilityType.OTHER,
    "other": VulnerabilityType.OTHER,
}


class ComplianceISO(BaseISO):
    """Compliance-oriented findings (policies, logging, data handling hints)."""

    SPECIALIZATION = ISOSpecialization.COMPLIANCE
    DEFAULT_TOOLS = ()

    SYSTEM_PROMPT = """\
You are ComplianceISO in the Tron verification pipeline. Flag likely \
compliance and governance gaps (audit logging, PII handling, retention, \
access controls described in code/docs). This is heuristic — not legal advice.

CRITICAL: Respond with ONLY a JSON array. Start with '[' end with ']'.

RULES:
1. Only report issues with a clear code or config reference.
2. Map to compliance_category: soc2|iso27001|hipaa|pci|privacy|audit_logging|data_retention|other
3. severity: critical|high|medium|low|info
4. confidence max 0.65 (LLM-only).

OUTPUT FORMAT:
[
  {
    "vulnerability_type": "security_misconfiguration",
    "compliance_category": "<category>",
    "severity": "medium",
    "file_path": "path",
    "line_number": 1,
    "line_end": null,
    "code_snippet": "snippet",
    "description": "why this may violate common control themes",
    "fix_suggestion": "concrete mitigation",
    "confidence": 0.5
  }
]

If none: []
"""

    def __init__(
        self,
        config: ISOConfig,
        secrets: Dict[str, str],
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        super().__init__(config, secrets)
        self._llm = llm_client or LLMClient(
            anthropic_key=secrets.get("llm/anthropic-key"),
            openai_key=secrets.get("llm/openai-key"),
        )

    async def _analyze(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> List[FindingOutput]:
        code_files = {p: c for p, c in file_contents.items() if _is_code(p)}
        if not code_files:
            code_files = file_contents
        budget = blueprint.max_tokens - 1500
        trimmed = self._truncate_to_budget(code_files, max(budget, 500))
        prompt = self._build_prompt(blueprint, trimmed, tool_results)
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ],
            model=self.config.model_name,
            temperature=blueprint.temperature,
            max_tokens=4096,
            json_mode=True,
        )
        response = await self._llm.complete(request)
        if self._metrics:
            self._metrics.llm_calls += 1
            self._metrics.llm_tokens_used += response.total_tokens
            self._metrics.llm_cost_usd += response.cost_usd
        return self._parse_llm_response(response.content, blueprint)

    def _build_prompt(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> str:
        cref = (self.config.compliance_reference_context or "").strip()
        parts: list[str] = [
            f"## Blueprint: {blueprint.name}",
            blueprint.description or "",
            f"Languages: {', '.join(blueprint.scope.languages)}",
            "",
        ]
        if cref:
            parts.extend(["## Reference context", cref, ""])
        parts.append("## Source")
        for path, content in file_contents.items():
            parts.extend([f"### {path}", "```", content[:120000], "```", ""])
        parts.append("Return JSON array only.")
        return "\n".join(parts)

    def _parse_llm_response(self, raw: str, blueprint: Blueprint) -> List[FindingOutput]:
        text = raw.strip()
        if text.startswith("```"):
            lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        for i, c in enumerate(text):
            if c in "[{":
                text = text[i:]
                break
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict) and "findings" in data:
            data = data["findings"]
        if not isinstance(data, list):
            return []
        out: List[FindingOutput] = []
        for item in data:
            try:
                cat = item.get("compliance_category", "other")
                vt = COMP_MAP.get(cat, VulnerabilityType.OTHER)
                desc = item.get("description", "")
                if cat:
                    desc = f"[{cat}] {desc}"
                out.append(
                    FindingOutput(
                        id=uuid4(),
                        vulnerability_type=vt,
                        severity=SeverityLevel(item.get("severity", "medium")),
                        file_path=item.get("file_path", "unknown"),
                        line_number=max(1, int(item.get("line_number", 1))),
                        line_end=item.get("line_end"),
                        code_snippet=item.get("code_snippet", "# n/a"),
                        description=desc,
                        fix_suggestion=item.get("fix_suggestion"),
                        confidence=min(float(item.get("confidence", 0.5)), 0.65),
                        deterministic_tool_confirmed=False,
                        agent_id=self.config.agent_id,
                        blueprint_id=blueprint.id,
                        finding_fingerprint="pending",
                        cross_validation_status=CrossValidationStatus.PENDING,
                    )
                )
            except Exception as exc:
                logger.warning("ComplianceISO skip: %s", exc)
        return out


def _is_code(path: str) -> bool:
    ext = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".php",
        ".md", ".yml", ".yaml", ".json",
    }
    return any(path.lower().endswith(e) for e in ext)

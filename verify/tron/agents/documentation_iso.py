"""DocumentationISO — API/docs drift and missing documentation signals."""

from __future__ import annotations

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
from tron.schemas.verification import (
    Blueprint,
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)

DOC_MAP = {
    "missing_readme": VulnerabilityType.OTHER,
    "stale_comment": VulnerabilityType.OTHER,
    "undocumented_public_api": VulnerabilityType.OTHER,
    "broken_example": VulnerabilityType.OTHER,
    "other": VulnerabilityType.OTHER,
}


class DocumentationISO(BaseISO):
    SPECIALIZATION = ISOSpecialization.DOCUMENTATION
    DEFAULT_TOOLS = ()

    SYSTEM_PROMPT = """\
You are DocumentationISO. Find documentation gaps: missing README sections, \
undocumented exported/public functions, misleading comments, TODO drift.

CRITICAL: ONLY JSON array. No markdown fences or preamble.

[
  {
    "vulnerability_type": "other",
    "documentation_category": "undocumented_public_api",
    "severity": "low",
    "file_path": "src/api.py",
    "line_number": 10,
    "line_end": null,
    "code_snippet": "...",
    "description": "Public handler lacks docstring",
    "fix_suggestion": "Add docstring",
    "confidence": 0.55
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
        files = {p: c for p, c in file_contents.items() if _doc_relevant(p)}
        if not files:
            files = file_contents
        budget = blueprint.max_tokens - 1500
        trimmed = self._truncate_to_budget(files, max(budget, 500))
        prompt = self._build_prompt(blueprint, trimmed, tool_results)
        resp = await self._llm.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                model=self.config.model_name,
                temperature=blueprint.temperature,
                max_tokens=4096,
                json_mode=True,
            )
        )
        if self._metrics:
            self._metrics.llm_calls += 1
            self._metrics.llm_tokens_used += resp.total_tokens
            self._metrics.llm_cost_usd += resp.cost_usd
        return self._parse_llm_response(resp.content, blueprint)

    def _build_prompt(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> str:
        parts = [f"## {blueprint.name}", blueprint.description or "", ""]
        for p, c in file_contents.items():
            parts.extend([f"### {p}", "```", c[:100000], "```", ""])
        parts.append("Return JSON array only.")
        return "\n".join(parts)

    def _parse_llm_response(self, raw: str, blueprint: Blueprint) -> List[FindingOutput]:
        t = raw.strip()
        if t.startswith("```"):
            t = "\n".join(
                x for x in t.split("\n") if not x.strip().startswith("```")
            ).strip()
        for i, c in enumerate(t):
            if c in "[{":
                t = t[i:]
                break
        try:
            data = json.loads(t)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict) and "findings" in data:
            data = data["findings"]
        if not isinstance(data, list):
            return []
        out: List[FindingOutput] = []
        for item in data:
            try:
                dc = item.get("documentation_category", "other")
                vt = DOC_MAP.get(dc, VulnerabilityType.OTHER)
                d = item.get("description", "")
                if dc:
                    d = f"[{dc}] {d}"
                out.append(
                    FindingOutput(
                        id=uuid4(),
                        vulnerability_type=vt,
                        severity=SeverityLevel(item.get("severity", "low")),
                        file_path=item.get("file_path", "unknown"),
                        line_number=max(1, int(item.get("line_number", 1))),
                        line_end=item.get("line_end"),
                        code_snippet=item.get("code_snippet", "# n/a"),
                        description=d,
                        fix_suggestion=item.get("fix_suggestion"),
                        confidence=min(float(item.get("confidence", 0.5)), 0.65),
                        deterministic_tool_confirmed=False,
                        agent_id=self.config.agent_id,
                        blueprint_id=blueprint.id,
                        finding_fingerprint="pending",
                        cross_validation_status=CrossValidationStatus.PENDING,
                    )
                )
            except Exception as e:
                logger.warning("DocumentationISO skip: %s", e)
        return out


def _doc_relevant(path: str) -> bool:
    pl = path.lower()
    if pl.endswith((".md", ".rst", ".txt")):
        return True
    return any(
        pl.endswith(x)
        for x in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java")
    )

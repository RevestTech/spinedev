"""Per-role daemon hooks that invoke the KG MCP tools before/after sealing.

Implements STORY-7.3.1 (engineer → ``impact_radius``), STORY-7.3.2 (operator
→ ``who_owns``), and STORY-7.3.3 (datawright → register Document outputs).
Backlog EPIC-7.3 / PRD §FR-4 (REQ-INIT-7 §7.5).

The role prompts (``lib/role-prompts/{engineer,operator,datawright}.md``)
instruct the LLM agent to call these tools. The hooks here are the
*daemon-level* enforcement so the BuildArtifact's ``kg_impact`` is populated
even when the agent forgets. Tool resolution per call: ``mcp`` CLI subprocess
first (matches v1 bridge convention) then in-process import of
``shared.mcp.tools.kg``. Both paths swallow exceptions — daemons never crash.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.build.build_artifact import CodeChange, KGImpactNode

logger = logging.getLogger(__name__)
_FORBID = ConfigDict(extra="forbid")


class _Owner(BaseModel):
    """Slim local mirror of ``shared.mcp.tools.kg.Owner`` (avoid hard import)."""
    model_config = _FORBID
    owner_type: str
    owner_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    via: str


def _call_via_mcp_cli(tool: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """``mcp call <tool> --json``; returns parsed ``.data`` or ``None`` on miss."""
    if shutil.which("mcp") is None:
        return None
    try:
        proc = subprocess.run(["mcp", "call", tool, "--json", json.dumps(payload)],
                              capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("kg_caller_mcp_cli_failed", extra={"tool": tool, "err": str(exc)})
        return None
    if proc.returncode != 0:
        return None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return parsed.get("data", parsed) if isinstance(parsed, dict) else None


def _call_via_import(tool: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Fall back to direct in-process call to ``shared.mcp.tools.kg``."""
    try:
        from shared.mcp.tools import kg as kg_mod
    except Exception as exc:  # noqa: BLE001 — never crash the daemon
        logger.warning("kg_caller_import_failed", extra={"tool": tool, "err": str(exc)})
        return None
    try:
        if tool == "impact_radius":
            resp = kg_mod.impact_radius(kg_mod.ImpactRadiusInput(**payload))
        elif tool == "who_owns":
            resp = kg_mod.who_owns(kg_mod.WhoOwnsInput(**payload))
        else:
            return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("kg_caller_invoke_failed", extra={"tool": tool, "err": str(exc)})
        return None
    return getattr(resp, "data", None) or {}


def _invoke_kg_tool(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Try CLI → in-process import; return ``{}`` if both fail."""
    data = _call_via_mcp_cli(tool, payload)
    if data is None:
        data = _call_via_import(tool, payload)
    return data or {}


class EngineerKGHook:
    """Pre-seal hook for the engineer daemon (STORY-7.3.1).

    Calls ``impact_radius`` once per changed file (``target_type='file'``),
    unions + dedupes the results, and emits ``KGImpactNode`` rows whose
    ``impact_distance`` mirrors what the KG returned — the auditor uses that
    field to detect under-claimed scope (STORY-7.4.3).
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def compute_kg_impact(self, code_changes: list[CodeChange], repo: str, *,
                          commit_sha: str | None = None,
                          include_tests: bool = True) -> list[KGImpactNode]:
        """Return one ``KGImpactNode`` per impacted graph node (de-duplicated)."""
        if not code_changes:
            return []
        seen: dict[str, KGImpactNode] = {}
        for change in code_changes:
            data = _invoke_kg_tool("impact_radius", {
                "project_id": self.project_id, "target": change.path,
                "target_type": "file", "repo": repo,
                "include_tests": include_tests, "commit_sha": commit_sha})
            for raw in (data.get("impacted") or []):
                if not isinstance(raw, dict):
                    continue
                node_id = raw.get("node_id") or ""
                if not node_id:
                    continue
                try:
                    node = KGImpactNode(node_id=node_id,
                        node_type=raw.get("type") or "Unknown",
                        impact_distance=int(raw.get("impact_distance", 0) or 0))
                except Exception:
                    continue
                # Keep smallest impact_distance when same node turns up via
                # multiple changed files (matches auditor's union semantics).
                prev = seen.get(node_id)
                if prev is None or node.impact_distance < prev.impact_distance:
                    seen[node_id] = node
        return list(seen.values())


class OperatorKGHook:
    """Pre-action hook for the operator daemon (STORY-7.3.2).

    Operator mutates infra; the daemon consults ``who_owns(target)`` first so
    approval is routed correctly. Operator never writes ``kg_impact`` (no
    code_changes by definition), so this hook returns owners rather than nodes.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def find_owner(self, target: str, repo: str, *,
                   commit_sha: str | None = None) -> list[_Owner]:
        """Return parsed Owner rows; empty list when nothing is known."""
        data = _invoke_kg_tool("who_owns", {"project_id": self.project_id,
            "target": target, "repo": repo, "commit_sha": commit_sha})
        out: list[_Owner] = []
        for raw in (data.get("owners") or []):
            if not isinstance(raw, dict):
                continue
            try:
                out.append(_Owner(**{k: raw.get(k) for k in
                    ("owner_type", "owner_id", "confidence", "via")}))
            except Exception:
                continue
        return out

    def warn_if_no_owner(self, target: str, repo: str, *,
                         commit_sha: str | None = None) -> str | None:
        """Return human-readable warning when no owner is registered."""
        if self.find_owner(target, repo, commit_sha=commit_sha):
            return None
        return (f"no owner found for `{target}` in repo `{repo}` — "
                "route approval to the project owner")


class DatawrightKGHook:
    """Post-output hook for the datawright daemon (STORY-7.3.3).

    When a pipeline produces an output (parquet, dataset, model, doc), insert
    a ``Document`` node into ``spine_kg.kg_node`` and ``PRODUCED_BY`` edges
    from each source data node to the new output. Returns the new ``node_id``.
    Stable shape: ``datawright:output:<repo>:<output_path>`` (idempotent).
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def register_output(self, output_path: str, source_data_nodes: list[str],
                        repo: str, *, commit_sha: str = "HEAD",
                        subtype: str = "pipeline-output") -> str:
        """Insert ``Document`` node + ``PRODUCED_BY`` edges; return new node_id."""
        node_id = f"datawright:output:{repo}:{output_path}"
        sql = (
            "WITH ins AS ("
            "  INSERT INTO spine_kg.kg_node "
            "    (node_id, type, subtype, repo, commit_sha, path, name, properties)"
            "  VALUES (:'nid', 'Document', :'subtype', :'repo', :'sha', :'path',"
            "          :'path', :'props'::jsonb) "
            "  ON CONFLICT (node_id) DO UPDATE SET properties = EXCLUDED.properties "
            "  RETURNING id), "
            "src AS (SELECT id FROM spine_kg.kg_node "
            "  WHERE node_id = ANY(:'srcs'::text[]) "
            "    AND (valid_to IS NULL OR valid_to > now())) "
            "INSERT INTO spine_kg.kg_edge (from_node_id, to_node_id, type, commit_sha) "
            "SELECT src.id, ins.id, 'PRODUCED_BY', :'sha' FROM src, ins "
            "ON CONFLICT DO NOTHING;")
        srcs_lit = "{" + ",".join(s.replace('"', '\\"') for s in source_data_nodes) + "}"
        props = json.dumps({"produced_by": "datawright",
            "project_id": self.project_id, "source_count": len(source_data_nodes)})
        try:
            self._psql_exec(sql, {"nid": node_id, "subtype": subtype, "repo": repo,
                "sha": commit_sha, "path": output_path,
                "srcs": srcs_lit, "props": props})
        except Exception as exc:  # noqa: BLE001
            logger.warning("datawright_register_output_failed",
                           extra={"output": output_path, "err": str(exc)})
        return node_id

    @staticmethod
    def _psql_exec(sql: str, params: dict[str, Any]) -> None:
        """Run a write via ``psql``; mirrors ``shared/mcp/tools/kg.py`` convention."""
        url = os.environ.get("SPINE_DB_URL")
        if not url:
            raise RuntimeError("SPINE_DB_URL not set; datawright KG hook requires it")
        cmd = ["psql", url, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
        for k, v in params.items():
            cmd.extend(["-v", f"{k}={v}"])
        cmd.extend(["-c", sql])
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"psql exit {proc.returncode}: {proc.stderr.strip()}")


__all__ = ["EngineerKGHook", "OperatorKGHook", "DatawrightKGHook"]

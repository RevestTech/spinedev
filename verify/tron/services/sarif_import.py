"""SARIF 2.1 import — convert runs[].results to DB-ready finding payloads (SEC-1)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


def _level_to_severity(level: Optional[str]) -> str:
    m = (level or "warning").lower()
    if m in ("error",):
        return "high"
    if m in ("warning", "warn"):
        return "medium"
    if m in ("note", "none", "info"):
        return "low"
    return "medium"


def _fingerprint(rule_id: str, uri: str, line: int) -> str:
    base = f"sarif:{rule_id}|{uri}|{line}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _message_text(res: dict) -> str:
    m = res.get("message") or {}
    t = m.get("text")
    if t:
        return str(t)[:4000]
    if m.get("id") is not None and isinstance(res.get("messageStrings"), dict):
        return str(res.get("messageStrings", {}))[:2000]
    return "SARIF result"


def _location_uri_start(res: dict) -> Tuple[str, int]:
    locs = res.get("locations") or []
    if not locs:
        return ("unknown", 1)
    phys = (locs[0] or {}).get("physicalLocation") or {}
    art = phys.get("artifactLocation") or {}
    uri = art.get("uri") or "unknown"
    if isinstance(uri, str) and uri.startswith("file://"):
        uri = uri[7:].lstrip("/")
    region = phys.get("region") or {}
    start = int(region.get("startLine") or 1)
    return (str(uri), max(1, start))


def parse_sarif_to_rows(
    sarif: dict, project_id: str, audit_run_id: str
) -> List[Dict[str, Any]]:
    """
    Return dicts suitable for :class:`tron.domain.models.Finding` (column names, not ORM).
    Merges all runs' results. ``rule_id`` is SARIF result.ruleId or ``sarif/unknown``.
    """
    if not isinstance(sarif, dict):
        raise ValueError("SARIF root must be a JSON object")
    runs = sarif.get("runs") or []
    rows: List[Dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results") or []
        for res in results:
            if not isinstance(res, dict):
                continue
            rule = res.get("ruleId") or "sarif/unknown"
            uri, line = _location_uri_start(res)
            sev = _level_to_severity(res.get("level"))
            fp = _fingerprint(str(rule), uri, line)
            title = f"{rule}: {uri}:{line}"
            desc = _message_text(res)
            rows.append(
                {
                    "audit_run_id": audit_run_id,
                    "project_id": project_id,
                    "fingerprint": fp,
                    "rule_id": str(rule)[:255],
                    "file_path": uri,
                    "line_start": line,
                    "line_end": line,
                    "severity": sev,
                    "category": "sarif",
                    "title": title[:2000],
                    "description": desc,
                    "suggested_fix": None,
                    "status": "open",
                    "code_snippet": None,
                    "confidence": None,
                    "deterministic_tool_confirmed": True,
                    "layer3_execution": "not_applicable",
                    "confirming_tools_json": ["sarif"],
                    "path_role": None,
                    "follow_up_recommended": False,
                    "evidence_source": "sarif",
                }
            )
    return rows


def load_sarif_from_bytes(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))

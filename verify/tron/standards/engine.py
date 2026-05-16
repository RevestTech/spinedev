"""Merge and evaluate quality gates against audit metrics."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from tron.standards.defaults import DEFAULT_QUALITY_GATES


def _merge_sections(base: dict, override: Optional[dict]) -> dict:
    """Shallow-merge top-level sections; dict values deep-merge one level."""
    if not override:
        return base
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            merged = {**out[key], **val}
            out[key] = merged
        else:
            out[key] = val
    return out


def merge_quality_gates(
    project_override: Optional[dict] = None,
    *,
    company_override: Optional[dict] = None,
) -> dict:
    """
    Proposal order: DEFAULT → COMPANY → PROJECT.

    Back-compat: single positional arg is treated as project-only override.
    """
    gates = copy.deepcopy(DEFAULT_QUALITY_GATES)
    gates = _merge_sections(gates, company_override)
    gates = _merge_sections(gates, project_override)
    return gates


def evaluate_quality_gates(
    gates: dict,
    *,
    findings_total: int,
    findings_critical: int,
    findings_high: int,
    findings_medium: int,
    findings_low: int,
    coverage_percent: Optional[float] = None,
    finding_rows: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[dict]]:
    """
    Returns (all_passed, list of criterion results).
    Unknown criteria are skipped (not failed).
    """
    results: List[dict] = []
    all_passed = True
    rows = finding_rows or []

    def _hardcoded_secret_hits() -> int:
        n = 0
        for r in rows:
            rid = (r.get("rule_id") or "").lower()
            cat = (r.get("category") or "").lower()
            title = (r.get("title") or "").lower()
            if (
                cat == "hardcoded_secrets"
                or "hardcoded_secrets" in rid
                or "secret" in rid
                or "hardcod" in title
            ):
                n += 1
        return n

    def _dependency_high_hits() -> int:
        n = 0
        for r in rows:
            if (r.get("severity") or "").lower() != "high":
                continue
            rid = (r.get("rule_id") or "").lower()
            cat = (r.get("category") or "").lower()
            if "depend" in rid or "depend" in cat or "vuln" in rid:
                n += 1
        return n

    security = gates.get("security") or {}
    for crit in security.get("criteria") or []:
        check = crit.get("check")
        if check == "no_critical_findings":
            ok = findings_critical <= int(crit.get("max_count", 0))
            results.append({"section": "security", "check": check, "passed": ok})
            all_passed &= ok
        elif check == "max_high_severity":
            ok = findings_high <= int(crit.get("max_count", 999))
            results.append({"section": "security", "check": check, "passed": ok})
            all_passed &= ok
        elif check == "no_hardcoded_secrets":
            ok = _hardcoded_secret_hits() <= int(crit.get("max_count", 0))
            results.append({"section": "security", "check": check, "passed": ok})
            all_passed &= ok
        elif check == "dependency_vulnerabilities":
            ok = _dependency_high_hits() <= int(crit.get("max_high", 999))
            results.append({"section": "security", "check": check, "passed": ok})
            all_passed &= ok

    testing = gates.get("testing") or {}
    for crit in testing.get("criteria") or []:
        check = crit.get("check")
        if check == "min_coverage_percent" and coverage_percent is not None:
            ok = coverage_percent >= float(crit.get("min_percentage", 0))
            results.append({"section": "testing", "check": check, "passed": ok})
            all_passed &= ok
        elif check == "all_endpoints_tested":
            # Without coverage data, skip (neutral pass)
            results.append(
                {
                    "section": "testing",
                    "check": check,
                    "passed": True,
                    "note": "skipped_no_endpoint_coverage_signal",
                }
            )

    compliance = gates.get("compliance") or {}
    for crit in compliance.get("criteria") or []:
        check = crit.get("check")
        if check == "max_compliance_high":
            max_allowed = int(crit.get("max_count", 999))
            hits = 0
            for r in rows:
                sev = (r.get("severity") or "").lower()
                cat = (r.get("category") or "").lower()
                if sev == "high" and cat in (
                    "soc2",
                    "iso27001",
                    "hipaa",
                    "pci",
                    "privacy",
                    "audit_logging",
                    "data_retention",
                ):
                    hits += 1
            ok = hits <= max_allowed
            results.append({"section": "compliance", "check": check, "passed": ok})
            all_passed &= ok

    return all_passed, results

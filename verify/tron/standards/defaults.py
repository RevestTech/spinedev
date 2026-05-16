"""Built-in default quality gates (objective checks)."""

from __future__ import annotations

from typing import Any, Dict

# Mirrors proposal example shape; evaluated by `engine.evaluate_quality_gates`.
DEFAULT_QUALITY_GATES: Dict[str, Any] = {
    "version": 1,
    "security": {
        "required": True,
        "criteria": [
            {"check": "no_critical_findings", "severity": "critical", "max_count": 0},
            {"check": "max_high_severity", "severity": "high", "max_count": 5},
            {"check": "no_hardcoded_secrets", "max_count": 0},
            {"check": "dependency_vulnerabilities", "max_high": 5},
        ],
    },
    "testing": {
        "required": False,
        "criteria": [
            {"check": "min_coverage_percent", "min_percentage": 0},
        ],
    },
    "compliance": {
        "required": False,
        "criteria": [
            {"check": "max_compliance_high", "max_count": 10},
        ],
    },
}

# Optional second tier — set per deployment via API `company_quality_gates_json`.
COMPANY_QUALITY_GATES_TEMPLATE: Dict[str, Any] = {}

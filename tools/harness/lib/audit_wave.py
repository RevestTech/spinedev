#!/usr/bin/env python3
"""Harness Lite audit-wave — Phase 1 read-only scanners (ADR-008).

Runs deterministic repo checks per QA gate and writes structured findings
JSON under ``.spine/harness/findings/``. Skips gates already ``green`` unless
``--all`` is passed.

No Hub/LLM required. Complements agent-driven ``harness-audit-wave`` skill.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_state import GATE_NAMES, harness_dir, read_state, write_state

SPINE_HOME = Path(os.environ.get("SPINE_HOME", Path(__file__).resolve().parents[3]))

Finding = dict[str, Any]
ScanFn = Callable[[Path], list[Finding]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(
    gate: str,
    severity: str,
    location: str,
    claim: str,
    actual: str,
    recommendation: str,
    owner_file: str | None = None,
) -> Finding:
    file_part, _, line_part = location.partition(":")
    row: Finding = {
        "severity": severity,
        "location": location,
        "claim": claim,
        "actual": actual,
        "recommendation": recommendation,
    }
    if owner_file:
        row["owner_file"] = owner_file
    elif file_part and not line_part:
        row["owner_file"] = file_part
    elif file_part:
        row["owner_file"] = file_part
    return row


def _run_cmd(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 124, str(exc)


def scan_docs(project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    docs_roots = [project_root / "docs", project_root / "Handoff.md"]
    md_files = list((project_root / "docs").rglob("*.md")) if (project_root / "docs").is_dir() else []
    if (project_root / "Handoff.md").is_file():
        md_files.append(project_root / "Handoff.md")
    for md in md_files:
        if "_archived/chatsession" in str(md):
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in link_re.finditer(text):
            target = "".join(match.group(1).split())
            if not target or target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target_path = (md.parent / target.split("#")[0]).resolve()
            if not target_path.exists():
                rel = md.relative_to(project_root)
                findings.append(
                    _finding(
                        "docs",
                        "medium",
                        f"{rel}:{text[:match.start()].count(chr(10)) + 1}",
                        f"Markdown link resolves: {target}",
                        "Target path missing",
                        "Fix link or restore referenced file",
                        owner_file=str(rel),
                    )
                )
    if not findings:
        findings.append(
            _finding(
                "docs",
                "info",
                "docs/",
                "Internal markdown links resolve",
                "No broken relative links in docs/ scan",
                "None",
            )
        )
    return findings


def scan_drift(project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    py = project_root / ".venv" / "bin" / "python"
    if not py.is_file():
        py = Path(sys.executable)
    gate = project_root / "tools" / "openapi-drift-gate.py"
    if gate.is_file():
        code, out = _run_cmd([str(py), str(gate)], project_root)
        if code != 0:
            tail = "\n".join(out.splitlines()[-8:])
            findings.append(
                _finding(
                    "drift",
                    "high" if code == 1 else "medium",
                    "tools/openapi-drift-gate.py:1",
                    "OpenAPI snapshot matches live spec",
                    f"Drift gate exit {code}",
                    "Refresh openapi-sample.json or fix live spec",
                    owner_file="shared/ui/spa/scripts/openapi-sample.json",
                )
            )
            if tail:
                findings[-1]["actual"] += f" — {tail[:200]}"
    canon = [
        "docs/SPINE_MASTER.md",
        "docs/PRD.md",
        "docs/ARCHITECTURE.md",
        "plan/artifacts/sdlc-pipeline-default.yaml",
        "orchestrator/state/phases.yaml",
    ]
    for rel in canon:
        if not (project_root / rel).is_file():
            findings.append(
                _finding(
                    "drift",
                    "high",
                    rel,
                    "Canonical SDLC artifact present",
                    "File missing",
                    f"Restore or update references to {rel}",
                    owner_file=rel,
                )
            )
    if not findings:
        findings.append(
            _finding(
                "drift",
                "info",
                "orchestrator/state/phases.yaml",
                "Canonical artifacts + OpenAPI drift",
                "Clean",
                "None",
            )
        )
    return findings


def scan_security(project_root: Path) -> list[Finding]:
    script = project_root / "tools" / "audit-secrets.sh"
    if not script.is_file():
        return [
            _finding(
                "security",
                "medium",
                "tools/audit-secrets.sh",
                "Secret-value grep audit available",
                "Script missing",
                "Restore tools/audit-secrets.sh",
            )
        ]
    code, out = _run_cmd(["bash", str(script)], project_root)
    if code != 0:
        return [
            _finding(
                "security",
                "critical" if code == 1 else "high",
                "tools/audit-secrets.sh:1",
                "No secret values in committed code (#9)",
                out.splitlines()[0] if out else f"exit {code}",
                "Move secrets to vault; keep path references only",
                owner_file="tools/audit-secrets.sh",
            )
        ]
    return [
        _finding(
            "security",
            "info",
            "tools/audit-secrets.sh",
            "No secret values in committed code",
            "Clean",
            "None",
        )
    ]


def scan_requirements(project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    required = [
        ("docs/PRD.md", "PRD acceptance criteria documented"),
        ("docs/SPINE_MASTER.md", "Master vision and gap matrix"),
        ("todo/BACKLOG.md", "Operational backlog"),
    ]
    for rel, claim in required:
        if not (project_root / rel).is_file():
            findings.append(
                _finding(
                    "requirements",
                    "high",
                    rel,
                    claim,
                    "Missing",
                    f"Add or restore {rel}",
                    owner_file=rel,
                )
            )
    master = project_root / "docs" / "SPINE_MASTER.md"
    if master.is_file():
        text = master.read_text(encoding="utf-8", errors="replace")
        if "Harness Lite" not in text:
            findings.append(
                _finding(
                    "requirements",
                    "low",
                    "docs/SPINE_MASTER.md",
                    "SPINE_MASTER reflects Harness Lite initiative",
                    "No Harness Lite mention in master doc",
                    "Add Harness Lite to component registry when shipping",
                    owner_file="docs/SPINE_MASTER.md",
                )
            )
    if not findings:
        findings.append(
            _finding(
                "requirements",
                "info",
                "docs/PRD.md",
                "Core requirement artifacts present",
                "Clean",
                "None",
            )
        )
    return findings


def scan_compliance(project_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not (project_root / ".markdownlint.json").is_file():
        findings.append(
            _finding(
                "compliance",
                "low",
                ".markdownlint.json",
                "Markdown lint config present",
                "Missing",
                "Add .markdownlint.json for doc consistency",
            )
        )
    conflicted = list(project_root.rglob("*conflicted*"))
    if conflicted:
        for p in conflicted[:5]:
            findings.append(
                _finding(
                    "compliance",
                    "high",
                    str(p.relative_to(project_root)),
                    "No iCloud/sync conflict artifacts",
                    "Conflicted copy present",
                    "Remove or merge conflicted file (ADR-008 rule 6)",
                    owner_file=str(p.relative_to(project_root)),
                )
            )
    if not findings:
        findings.append(
            _finding(
                "compliance",
                "info",
                ".markdownlint.json",
                "Hygiene checks",
                "Clean",
                "None",
            )
        )
    return findings


def scan_tests(project_root: Path) -> list[Finding]:
    """Lightweight signal only — full QA via verify --run-qa."""
    smoke = project_root / "tools" / "smoke-test.sh"
    if not smoke.is_file():
        return [
            _finding(
                "tests",
                "high",
                "tools/smoke-test.sh",
                "Smoke test contract available",
                "Missing",
                "Restore tools/smoke-test.sh",
            )
        ]
    return [
        _finding(
            "tests",
            "info",
            "tools/smoke-test.sh",
            "Full test gate",
            "Run: spine harness verify --run-qa (needs Postgres/Docker)",
            "Use verify-wave for exit-code evidence",
        )
    ]


SCANNERS: dict[str, ScanFn] = {
    "docs": scan_docs,
    "drift": scan_drift,
    "security": scan_security,
    "requirements": scan_requirements,
    "compliance": scan_compliance,
    "tests": scan_tests,
}


def gates_to_audit(state: dict[str, Any], *, audit_all: bool) -> list[str]:
    if audit_all:
        return list(GATE_NAMES)
    gates = state.get("gates") or {}
    return [g for g in GATE_NAMES if gates.get(g) != "green"]


def severity_rank(sev: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(sev, 5)


def gate_status_from_findings(findings: list[Finding]) -> str:
    sevs = [f.get("severity", "info") for f in findings]
    if any(s in ("critical", "high") for s in sevs):
        return "red"
    if any(s == "medium" for s in sevs):
        return "yellow"
    if all(s == "info" for s in sevs):
        return "green"
    return "yellow"


def write_findings_file(
    project_root: Path,
    gate: str,
    findings: list[Finding],
    wave_id: str,
) -> Path:
    out_dir = harness_dir(project_root) / "findings"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().replace(":", "").replace("-", "")
    path = out_dir / f"{gate}-{ts}.json"
    payload = {
        "version": 1,
        "gate": gate,
        "wave": "audit",
        "wave_id": wave_id,
        "generated_at": _utc_now(),
        "findings": findings,
        "summary": f"{len(findings)} finding(s); worst={min((severity_rank(f.get('severity','info')) for f in findings), default=4)}",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def cmd_audit(args: argparse.Namespace) -> int:
    project_root = Path(args.project).resolve()
    state = read_state(project_root)
    wave_id = f"audit-{_utc_now().replace(':', '').replace('-', '')}"
    state["wave"] = "audit"
    write_state(project_root, state)

    requested = [g.strip() for g in args.gates.split(",") if g.strip()]
    if requested == ["all"]:
        targets = list(GATE_NAMES)
    elif requested:
        targets = [g for g in requested if g in GATE_NAMES]
    else:
        targets = gates_to_audit(state, audit_all=args.all)

    if not targets:
        print(json.dumps({"message": "all gates green", "wave_id": wave_id}))
        state = read_state(project_root)
        state["wave"] = None
        write_state(project_root, state)
        return 0

    results: dict[str, Any] = {}
    exit_code = 0
    for gate in targets:
        scanner = SCANNERS.get(gate)
        if not scanner:
            continue
        findings = scanner(project_root)
        path = write_findings_file(project_root, gate, findings, wave_id)
        status = gate_status_from_findings(findings)
        results[gate] = {
            "findings_file": str(path),
            "count": len(findings),
            "proposed_status": status,
        }
        if status in ("red", "yellow") and any(
            f.get("severity") in ("critical", "high") for f in findings
        ):
            exit_code = 1

    state = read_state(project_root)
    for gate, meta in results.items():
        if args.update_gates:
            state["gates"][gate] = meta["proposed_status"]
    state["wave"] = "fix" if exit_code else None
    write_state(project_root, state)

    out = {"wave_id": wave_id, "gates": results, "next_wave": state.get("wave")}
    if args.markdown:
        lines = ["# Harness Lite audit-wave", "", f"- **Wave ID:** `{wave_id}`", ""]
        for gate, meta in results.items():
            lines.append(f"## {gate} → `{meta['proposed_status']}`")
            lines.append(f"- Findings: `{meta['findings_file']}` ({meta['count']})")
            lines.append("")
        print("\n".join(lines))
    else:
        print(json.dumps(out, indent=2))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness Lite audit-wave (Phase 1)")
    parser.add_argument("--project", default=".")
    parser.add_argument(
        "--gates",
        default="",
        help="Comma-separated gates or 'all' (default: non-green from state)",
    )
    parser.add_argument("--all", action="store_true", help="Audit all gates")
    parser.add_argument(
        "--update-gates",
        action="store_true",
        default=True,
        help="Update state.json gate statuses (default on)",
    )
    parser.add_argument(
        "--no-update-gates",
        action="store_false",
        dest="update_gates",
    )
    parser.add_argument("--markdown", action="store_true")
    parser.set_defaults(func=cmd_audit)
    args = parser.parse_args(argv)
    os.environ.setdefault("SPINE_HOME", str(SPINE_HOME))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

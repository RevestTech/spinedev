#!/usr/bin/env python3
"""Harness Lite verify-wave — Phase 3 gate runner (ADR-008).

Runs trimmed charter evals (offline stub) and optional QA command from
``pm.config.json``. Updates ``.spine/harness/state.json`` and writes
``.spine/harness/reports/latest.md``.

No Hub/Postgres required for ``--lite`` (default).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Harness state helpers (same package dir)
# Fix harness_state import when verify_wave is executed directly
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_state import (
    GATE_NAMES,
    GATE_LABELS,
    harness_dir,
    read_state,
    render_status_markdown,
    write_state,
)

DEFAULT_LITE_ROLES = ("qa", "auditor")
DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "charter_evals"
SPINE_HOME = Path(os.environ.get("SPINE_HOME", Path(__file__).resolve().parents[3]))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_verify_path() -> None:
    verify_root = str(SPINE_HOME / "verify")
    spine_root = str(SPINE_HOME)
    if spine_root not in sys.path:
        sys.path.insert(0, spine_root)
    if verify_root not in sys.path:
        sys.path.insert(1, verify_root)


def load_pm_qa_command(project_root: Path) -> str | None:
    cfg_path = project_root / "pm.config.json"
    if not cfg_path.is_file():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    qa = cfg.get("qa") or {}
    cmd = qa.get("command")
    return str(cmd) if cmd else None


@dataclass(frozen=True)
class QaRunResult:
    command: str
    exit_code: int
    skipped: bool
    reason: str = ""
    tail: str = ""


@dataclass(frozen=True)
class CharterRoleResult:
    role: str
    exit_code: int
    overall_green: bool
    markdown: str
    eval_count: int


def run_qa_command(project_root: Path, command: str, timeout_s: int) -> QaRunResult:
    if not command.strip():
        return QaRunResult(command="", exit_code=0, skipped=True, reason="empty command")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        tail = "\n".join(combined.splitlines()[-30:])
        return QaRunResult(
            command=command,
            exit_code=proc.returncode,
            skipped=False,
            tail=tail,
        )
    except subprocess.TimeoutExpired:
        return QaRunResult(
            command=command,
            exit_code=124,
            skipped=False,
            reason=f"timeout after {timeout_s}s",
        )
    except OSError as exc:
        return QaRunResult(
            command=command,
            exit_code=127,
            skipped=True,
            reason=str(exc),
        )


def run_charter_role(
    role: str,
    *,
    callable_name: str = "fixture",
    fixture_root: Path | None = None,
) -> CharterRoleResult:
    _ensure_verify_path()
    from verify.charter_evals.harness import evaluate_charter, load_evals_for_role
    from verify.charter_evals.role_callables import (
        fixture_role_callable_from_dir,
        stub_role_callable,
    )
    from verify.charter_evals.run import render_report_markdown

    evals = load_evals_for_role(role, root=SPINE_HOME / "verify" / "charter_evals")
    if not evals:
        md = f"# Charter eval report — {role}\n\n> No evals found (skipped)\n"
        return CharterRoleResult(
            role=role,
            exit_code=2,
            overall_green=False,
            markdown=md,
            eval_count=0,
        )
    if callable_name == "stub":
        role_callable = stub_role_callable
    elif callable_name == "fixture":
        root = fixture_root or (DEFAULT_FIXTURE_ROOT / role)
        if not root.is_dir():
            md = f"# Charter eval report — {role}\n\n> Fixture root missing: `{root}`\n"
            return CharterRoleResult(
                role=role,
                exit_code=2,
                overall_green=False,
                markdown=md,
                eval_count=len(evals),
            )
        role_callable = fixture_role_callable_from_dir(root)
    else:
        raise ValueError(f"unsupported callable: {callable_name!r} (use fixture or stub)")
    report = evaluate_charter(role, evals, role_callable)
    md = render_report_markdown(report)
    code = 0 if report.overall_meets_target else 1
    return CharterRoleResult(
        role=role,
        exit_code=code,
        overall_green=report.overall_meets_target,
        markdown=md,
        eval_count=len(report.per_eval),
    )


def derive_gates(
    qa: QaRunResult | None,
    charter: list[CharterRoleResult],
) -> dict[str, str]:
    gates: dict[str, str] = {}
    by_role = {r.role: r for r in charter}

    if qa and not qa.skipped:
        gates["tests"] = "green" if qa.exit_code == 0 else "red"
    elif by_role.get("qa") and by_role["qa"].eval_count > 0:
        gates["tests"] = "green" if by_role["qa"].overall_green else "red"

    if by_role.get("auditor") and by_role["auditor"].eval_count > 0:
        gates["security"] = (
            "green" if by_role["auditor"].overall_green else "red"
        )

    if by_role.get("qa") and by_role["qa"].eval_count > 0:
        gates["compliance"] = (
            "green" if by_role["qa"].overall_green else "yellow"
        )

    if qa and qa.exit_code not in (0, 124) and not qa.skipped:
        gates["drift"] = "yellow"

    return gates


def build_report(
    project_root: Path,
    qa: QaRunResult | None,
    charter: list[CharterRoleResult],
    gates: dict[str, str],
) -> str:
    lines = [
        "# Harness Lite verify-wave report",
        "",
        f"- **Generated:** {_utc_now()}",
        f"- **Project:** `{project_root}`",
        f"- **Mode:** verify (ADR-008 Phase 3)",
        "",
        "## Gate rollup",
        "",
        "| Gate | Status |",
        "|------|--------|",
    ]
    for gate in GATE_NAMES:
        lines.append(f"| {GATE_LABELS[gate]} | `{gates.get(gate, 'unknown')}` |")
    lines.extend(["", "## QA command", ""])
    if qa is None:
        lines.append("_Not run (use `--run-qa` to execute pm.config.json qa.command)_")
    elif qa.skipped:
        lines.append(f"- Skipped: {qa.reason or 'n/a'}")
    else:
        lines.extend(
            [
                f"- **Command:** `{qa.command}`",
                f"- **Exit code:** {qa.exit_code}",
            ]
        )
        if qa.reason:
            lines.append(f"- **Note:** {qa.reason}")
        if qa.tail:
            lines.extend(["", "### Tail (last 30 lines)", "", "```", qa.tail, "```"])
    lines.extend(["", "## Charter evals (lite / fixture)", ""])
    for result in charter:
        lines.append(f"### Role: `{result.role}`")
        lines.append("")
        lines.append(result.markdown)
        lines.append("")
    lines.extend(
        [
            "## References",
            "",
            "- `verify/charter_evals/harness.py`",
            "- `docs/QA-READINESS-STANDARD.md`",
            "- `docs/adr/ADR-008-sprint-cleanup-methodology.md`",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_verify(args: argparse.Namespace) -> int:
    project_root = Path(args.project).resolve()
    state = read_state(project_root)
    state["wave"] = "verify"
    write_state(project_root, state)

    qa_result: QaRunResult | None = None
    if args.run_qa:
        cmd = args.qa_command or load_pm_qa_command(project_root)
        if cmd:
            qa_result = run_qa_command(project_root, cmd, args.qa_timeout)
        else:
            qa_result = QaRunResult(
                command="",
                exit_code=0,
                skipped=True,
                reason="no qa.command in pm.config.json",
            )

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    fixture_root = Path(args.fixture_root).resolve() if args.fixture_root else None
    charter_results = [
        run_charter_role(
            role,
            callable_name=args.callable,
            fixture_root=fixture_root / role if fixture_root else None,
        )
        for role in roles
    ]
    gates = derive_gates(qa_result, charter_results)

    report_path = harness_dir(project_root) / "reports" / "latest.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = build_report(project_root, qa_result, charter_results, gates)
    report_path.write_text(report_text, encoding="utf-8")

    state = read_state(project_root)
    for gate, status in gates.items():
        state["gates"][gate] = status
    state["last_report"] = str(report_path)
    state["wave"] = None
    write_state(project_root, state)

    if args.markdown:
        print(report_text)
    else:
        print(
            json.dumps(
                {
                    "report": str(report_path),
                    "gates": gates,
                    "charter_roles": [
                        {
                            "role": r.role,
                            "green": r.overall_green,
                            "exit_code": r.exit_code,
                        }
                        for r in charter_results
                    ],
                    "qa": None
                    if qa_result is None
                    else {
                        "command": qa_result.command,
                        "exit_code": qa_result.exit_code,
                        "skipped": qa_result.skipped,
                    },
                },
                indent=2,
            )
        )
    if args.write_status:
        print(render_status_markdown(state, project_root))

    charter_ok = all(r.exit_code == 0 for r in charter_results if r.eval_count > 0)
    qa_ok = qa_result is None or qa_result.skipped or qa_result.exit_code == 0
    return 0 if (charter_ok and qa_ok) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness Lite verify-wave (Phase 3)")
    parser.add_argument("--project", default=".", help="Target project root")
    parser.add_argument(
        "--roles",
        default=",".join(DEFAULT_LITE_ROLES),
        help=f"Comma-separated charter roles (default: {','.join(DEFAULT_LITE_ROLES)})",
    )
    parser.add_argument(
        "--callable",
        default="fixture",
        choices=("fixture", "stub"),
        help="Charter eval callable (default: fixture — offline golden responses)",
    )
    parser.add_argument(
        "--fixture-root",
        default="",
        help="Override fixture root (expects <root>/<role>/<eval-name>.txt)",
    )
    parser.add_argument(
        "--run-qa",
        action="store_true",
        help="Run pm.config.json qa.command (may require Postgres/Docker)",
    )
    parser.add_argument("--qa-command", default="", help="Override QA shell command")
    parser.add_argument(
        "--qa-timeout",
        type=int,
        default=600,
        help="QA command timeout seconds (default 600)",
    )
    parser.add_argument("--markdown", action="store_true", help="Print report markdown")
    parser.add_argument(
        "--write-status",
        action="store_true",
        help="Also print harness status markdown after update",
    )
    parser.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    os.environ.setdefault("SPINE_HOME", str(SPINE_HOME))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

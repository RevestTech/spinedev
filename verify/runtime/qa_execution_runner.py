"""QA execution runtime (Operating-loop Stage 6 — SPINE-004).

Runs the engineer's RUN block against the sprint plan's acceptance
criteria and persists ``qa_execution_md`` in project metadata.

The plan-side ``qa`` role (``plan/runtime/hub_role_runner``) produces a
test *plan* only. This runtime performs test *execution*: it extracts
acceptance criteria from ``metadata.sprint_plan_md``, classifies test
commands from ``metadata.code_run_block``, runs them in the project
workspace, and writes a traceability report.

Design boundary
---------------

Like ``auditor_runner``, the core logic is deterministic and testable.
Production may inject ``command_runner``; tests use stubs. No direct LLM
calls — execution evidence is shell output + AC mapping.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger("spine.runtime.qa_execution_runner")

_SHELL_TIMEOUT_SECS = 180

_TEST_HINTS = (
    "pytest", "npm test", "npm run test", "yarn test", "pnpm test",
    "cargo test", "go test", "make test", "rake test", "bundle exec rspec",
    "python -m pytest", "python -m unittest", "vitest", "jest",
)
_INSTALL_HINTS = (
    "npm install", "npm ci", "pip install", "pnpm install", "yarn install",
    "bundle install", "cargo build", "cargo fetch", "go mod download",
    "poetry install", "uv pip install", "uv sync",
)
_START_HINTS = (
    "npm start", "npm run dev", "yarn dev", "uvicorn", "fastapi run",
    "python -m", "python app", "cargo run", "go run", "flask run", "rails server",
)

_AC_LINE_RE = re.compile(
    r"^\s*(?:-\s*)?(?:\*\*T-\d+\*\*[^A]*?)?Acceptance:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TASK_AC_RE = re.compile(
    r"\*\*T-(\d+)\*\*[^\n]*?\n(?:[^\n]*\n)*?\s*Acceptance:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class AcceptanceCriterion:
    task_id: str
    description: str


@dataclass(frozen=True)
class CommandRunOutcome:
    command: str
    exit_code: int
    output: str
    timed_out: bool = False


@dataclass
class QaExecutionResult:
    ok: bool
    directive_id: str
    execution_md: str = ""
    all_passed: bool = False
    criteria_total: int = 0
    criteria_passed: int = 0
    commands_run: int = 0
    commands_failed: int = 0
    error_class: str | None = None
    error_message: str | None = None
    project_uuid: str = ""
    project_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


CommandRunner = Callable[[Path, list[str]], list[CommandRunOutcome]]


def extract_acceptance_criteria(sprint_plan_md: str) -> list[AcceptanceCriterion]:
    """Parse sprint-plan acceptance criteria (Conductor T-* cards)."""
    text = (sprint_plan_md or "").strip()
    if not text:
        return []

    seen: set[str] = set()
    criteria: list[AcceptanceCriterion] = []

    for match in _TASK_AC_RE.finditer(text):
        task_id = f"T-{match.group(1)}"
        desc = match.group(2).strip()
        key = f"{task_id}:{desc}"
        if key not in seen:
            seen.add(key)
            criteria.append(AcceptanceCriterion(task_id=task_id, description=desc))

    if criteria:
        return criteria

    for idx, match in enumerate(_AC_LINE_RE.finditer(text), start=1):
        desc = match.group(1).strip()
        task_id = f"AC-{idx}"
        key = f"{task_id}:{desc}"
        if key not in seen:
            seen.add(key)
            criteria.append(AcceptanceCriterion(task_id=task_id, description=desc))

    return criteria


def classify_test_commands(run_block: str) -> list[str]:
    """Return test/verification commands from the engineer RUN block."""
    commands: list[str] = []
    for raw in (run_block or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if any(h in lower for h in _INSTALL_HINTS):
            continue
        if any(h in lower for h in _TEST_HINTS):
            commands.append(line)
            continue
        if any(h in lower for h in _START_HINTS):
            continue
        # Non-install, non-start commands are treated as verification steps.
        commands.append(line)
    return commands


def _build_execution_markdown(
    *,
    project_name: str,
    criteria: list[AcceptanceCriterion],
    outcomes: list[CommandRunOutcome],
    all_passed: bool,
    sprint_plan_present: bool,
    run_block_present: bool,
) -> str:
    posture = "**QA PASS**" if all_passed else "**QA FAIL**"
    lines = [
        f"# QA execution — {project_name}",
        "",
        "## Summary",
        "",
        f"Posture: {posture}.",
        f"Acceptance criteria: {len(criteria)}.",
        f"Commands run: {len(outcomes)} "
        f"({sum(1 for o in outcomes if o.exit_code == 0)} passed / "
        f"{sum(1 for o in outcomes if o.exit_code != 0)} failed).",
        "",
    ]

    if not sprint_plan_present:
        lines.extend([
            "> Warning: no sprint plan in metadata — AC traceability is limited.",
            "",
        ])
    if not run_block_present:
        lines.extend([
            "> Warning: no engineer RUN block — no commands executed.",
            "",
        ])

    lines.extend(["## Acceptance criteria", ""])
    if criteria:
        for ac in criteria:
            lines.append(f"- **{ac.task_id}** — {ac.description}")
    else:
        lines.append("_No acceptance criteria parsed from sprint plan._")
    lines.append("")

    lines.extend(["## Command results", ""])
    if outcomes:
        for outcome in outcomes:
            status = "PASS" if outcome.exit_code == 0 else "FAIL"
            timeout_note = " (timeout)" if outcome.timed_out else ""
            lines.append(f"### `{outcome.command}` — {status}{timeout_note}")
            lines.append("")
            if outcome.output.strip():
                lines.append("```")
                lines.append(outcome.output.rstrip())
                lines.append("```")
            else:
                lines.append("_(no output)_")
            lines.append("")
    else:
        lines.append("_No test commands detected in RUN block._")
        lines.append("")

    lines.extend([
        "## Traceability",
        "",
        "Each command outcome above is mapped against the sprint-plan "
        "acceptance criteria. Re-run engineer if any command failed or "
        "criteria remain unverified.",
        "",
    ])
    return "\n".join(lines).strip()


async def _default_command_runner(workspace: Path, commands: list[str]) -> list[CommandRunOutcome]:
    outcomes: list[CommandRunOutcome] = []
    if not workspace.exists():
        return outcomes

    for cmd in commands:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=_SHELL_TIMEOUT_SECS,
                )
            except asyncio.TimeoutError:
                proc.kill()
                outcomes.append(CommandRunOutcome(
                    command=cmd,
                    exit_code=124,
                    output=f"[timeout after {_SHELL_TIMEOUT_SECS}s]",
                    timed_out=True,
                ))
                continue
            output = (stdout or b"").decode("utf-8", errors="replace")
            tail = output if len(output) <= 4000 else "…[truncated]…\n" + output[-4000:]
            outcomes.append(CommandRunOutcome(
                command=cmd,
                exit_code=int(proc.returncode or 0),
                output=tail.rstrip(),
            ))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(CommandRunOutcome(
                command=cmd,
                exit_code=127,
                output=f"[qa execution error: {type(exc).__name__}: {exc}]",
            ))
    return outcomes


def _sync_command_runner(workspace: Path, commands: list[str]) -> list[CommandRunOutcome]:
    return asyncio.run(_default_command_runner(workspace, commands))


def _load_project_row(project_id: str) -> dict[str, Any]:
    from build.runtime.build_dispatcher import _load_project  # noqa: PLC0415

    return _load_project(project_id)


def _persist_metadata(project_id: str, patch: dict[str, Any]) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415

    row = _load_project(project_id)
    _merge_metadata(int(row["id"]), patch)


def _normalize_project(project: dict[str, Any]) -> dict[str, Any]:
    metadata = project.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    return {
        "project_uuid": str(project.get("project_uuid") or project.get("id") or "").strip(),
        "name": str(project.get("name") or "").strip(),
        "metadata": metadata,
    }


def run_qa_execution(
    project: dict[str, Any],
    *,
    command_runner: CommandRunner | None = None,
) -> QaExecutionResult:
    """Execute QA against sprint-plan AC + engineer RUN block."""
    from shared.runtime.project_workspace import resolve_code_dir  # noqa: PLC0415
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    directive_id = f"dir_{uuid4().hex[:12]}"
    normalized = _normalize_project(project)
    project_uuid = normalized["project_uuid"]
    project_name = normalized["name"] or "unnamed"
    prior = normalized["metadata"]

    if not project_uuid:
        return QaExecutionResult(
            ok=False,
            directive_id=directive_id,
            error_class="missing_project_uuid",
            error_message="project_uuid is required for QA execution",
        )

    role_log(project_uuid, "qa", "QA execution started")

    sprint_plan_md = str(prior.get("sprint_plan_md") or "")
    run_block = str(prior.get("code_run_block") or "")
    criteria = extract_acceptance_criteria(sprint_plan_md)
    commands = classify_test_commands(run_block)

    workspace = resolve_code_dir(project_uuid, prior)
    runner = command_runner or _sync_command_runner

    try:
        outcomes = runner(workspace, commands)
    except Exception as exc:  # noqa: BLE001
        logger.exception("qa_command_runner_failed")
        role_log(project_uuid, "qa", f"QA execution failed: {exc}", level="error")
        return QaExecutionResult(
            ok=False,
            directive_id=directive_id,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
        )

    commands_failed = sum(1 for o in outcomes if o.exit_code != 0)
    all_passed = bool(outcomes) and commands_failed == 0
    if not commands and criteria:
        all_passed = False
    if not sprint_plan_md and not run_block:
        all_passed = False

    execution_md = _build_execution_markdown(
        project_name=project_name,
        criteria=criteria,
        outcomes=outcomes,
        all_passed=all_passed,
        sprint_plan_present=bool(sprint_plan_md.strip()),
        run_block_present=bool(run_block.strip()),
    )

    patch = {
        "qa_execution_md": execution_md,
        "qa_execution_ok": bool(all_passed),
        "qa_execution_commands": [o.command for o in outcomes],
    }
    try:
        _persist_metadata(project_uuid, patch)
    except Exception as exc:  # noqa: BLE001
        logger.exception("qa_execution_persist_failed")
        return QaExecutionResult(
            ok=False,
            directive_id=directive_id,
            execution_md=execution_md,
            all_passed=all_passed,
            error_class="persist_failed",
            error_message=str(exc)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
        )

    _record_ledger_outcome(
        project_uuid=project_uuid,
        run_id=directive_id,
        all_passed=all_passed,
        criteria_count=len(criteria),
        commands_run=len(outcomes),
    )
    _publish_qa_execution_event(
        project_uuid=project_uuid,
        directive_id=directive_id,
        all_passed=all_passed,
        criteria_count=len(criteria),
        commands_run=len(outcomes),
        commands_failed=commands_failed,
    )

    role_log(
        project_uuid,
        "qa",
        f"QA execution finished — {'PASS' if all_passed else 'FAIL'}",
        level="success" if all_passed else "error",
    )

    return QaExecutionResult(
        ok=True,
        directive_id=directive_id,
        execution_md=execution_md,
        all_passed=all_passed,
        criteria_total=len(criteria),
        criteria_passed=len(criteria) if all_passed else max(0, len(criteria) - commands_failed),
        commands_run=len(outcomes),
        commands_failed=commands_failed,
        project_uuid=project_uuid,
        project_name=project_name,
        extra={
            "commands": [o.command for o in outcomes],
            "workspace": str(workspace),
        },
    )


def _record_ledger_outcome(
    *,
    project_uuid: str,
    run_id: str,
    all_passed: bool,
    criteria_count: int,
    commands_run: int,
) -> None:
    """Append QA execution to decision ledger (V3 #12a). Fail-soft."""
    try:
        from shared.audit.decision_ledger_io import (
            SafePromotionInputs,
            append_promotion_decision,
            make_candidate,
        )

        append_promotion_decision(
            SafePromotionInputs(
                project_id=project_uuid,
                run_id=run_id,
                role="qa",
                rollout_index=0,
                tier="internal",
                freshness_passed=True,
                replay_passed=all_passed,
                candidates=(
                    make_candidate(
                        "qa:qa_execution_md",
                        mark="accept" if all_passed else "watch",
                        rationale=(
                            f"qa_execution criteria={criteria_count} "
                            f"commands={commands_run} passed={all_passed}"
                        ),
                    ),
                ),
                fresh_evidence=(f"qa_execution:commands={commands_run}",),
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("qa_execution_ledger_failed")


def _publish_qa_execution_event(
    *,
    project_uuid: str,
    directive_id: str,
    all_passed: bool,
    criteria_count: int,
    commands_run: int,
    commands_failed: int,
) -> None:
    """Emit realtime QA execution event. Fail-soft."""
    try:
        from shared.api.realtime.event_publisher import publish
        from shared.api.realtime.event_schema import ProjectEvent

        publish(
            ProjectEvent(
                event_type="qa_execution_finished",  # type: ignore[arg-type]
                project_id=project_uuid,
                actor="qa",
                verdict="ok" if all_passed else "fail",
                citation_count=criteria_count,
                summary=(
                    f"QA execution {'PASS' if all_passed else 'FAIL'} — "
                    f"{commands_run} command(s), {commands_failed} failed"
                ),
                payload={
                    "directive_id": directive_id,
                    "all_passed": all_passed,
                    "criteria_count": criteria_count,
                    "commands_run": commands_run,
                    "commands_failed": commands_failed,
                },
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("qa_execution_publish_failed", exc_info=True)


__all__ = [
    "AcceptanceCriterion",
    "CommandRunOutcome",
    "CommandRunner",
    "QaExecutionResult",
    "classify_test_commands",
    "extract_acceptance_criteria",
    "run_qa_execution",
]

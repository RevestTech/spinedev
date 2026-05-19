"""Post-ack side-effect hooks for the SDLC chain.

When a user acks a decision card, this module dispatches the next role
in the SDLC pipeline based on the card's metadata.kind:

  prd_approval     → advance to phase=plan, dispatch architect for TRD
  trd_approval     → advance to phase=build, dispatch engineer for impl
  impl_approval    → advance to phase=verify, dispatch qa for test plan
  qa_approval      → advance to phase=release, mark project complete

Each role call is a real LLM dispatch using the role's charter from
shared/charters/<role>.md. Output gets persisted to project.metadata
and pushed as the next approval card.

All work runs as fire-and-forget asyncio tasks so the ack response
lands fast. Failures are logged but never raise out of this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os as _os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from shared.llm import LLMRequest, Message, call_async

logger = logging.getLogger("spine.api.post_ack")

_CHARTERS_DIR = Path(__file__).resolve().parents[1].parent / "charters"

import os as _os
_DEFAULT_MODEL = _os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        return f"# Charter for {role} (not found at {path})"
    return path.read_text(encoding="utf-8")


async def _load_project_full(project_id: str) -> Optional[dict[str, Any]]:
    """Fetch the project row + metadata (incl. prior artifacts)."""
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return None
    where_clause = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT id, project_uuid::text AS project_uuid, name, project_type, "
            f"current_phase, metadata FROM spine_lifecycle.project WHERE {where_clause}",
            arg,
        )
    if row is None:
        return None
    metadata = row["metadata"]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}
    return {
        "id": int(row["id"]),
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "metadata": metadata or {},
    }


async def _persist_metadata_patch(project_id: str, patch: dict[str, Any]) -> None:
    """Merge `patch` into project.metadata via JSONB ||."""
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE spine_lifecycle.project SET metadata = "
            f"COALESCE(metadata, '{{}}'::jsonb) || $1::jsonb, updated_at = now() "
            f"WHERE {where_clause}",
            json.dumps(patch), arg,
        )


async def _advance_phase(project_id: str, target_phase: str) -> None:
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"UPDATE spine_lifecycle.project SET current_phase = $1, updated_at = now() "
                f"WHERE {where_clause} RETURNING id",
                target_phase, arg,
            )
            if row is None:
                return
            await conn.execute(
                "INSERT INTO spine_lifecycle.phase_history "
                "(project_id, phase, entered_at) VALUES ($1, $2, now())",
                int(row["id"]), target_phase,
            )


def _enqueue(card_kwargs: dict[str, Any]) -> None:
    from shared.api.routes.decisions import DecisionCard, enqueue_decision
    card = DecisionCard(decision_id=str(uuid.uuid4()), **card_kwargs)
    enqueue_decision(card)
    logger.info("post_ack_card_enqueued", extra={
        "decision_id": card.decision_id,
        "kind": card_kwargs.get("metadata", {}).get("kind"),
    })


# ---------------------------------------------------------------------------
# Role dispatchers
# ---------------------------------------------------------------------------


_PLANNER_PROMPT = """
You are the Spine **planner** role (PMBOK 7-anchored). The PRD has
just been approved. Produce a project roadmap in markdown.

ROADMAP structure (start with `# Roadmap — <Project Name>`):
  1. **Sprint breakdown** — split the PRD into 1-3 sprints with names
     + clear sprint goals. PMBOK iteration-planning discipline.
  2. **Critical path** — ordered list of milestone artifacts and their
     dependencies. Identify the MVP cut.
  3. **RACI snapshot** — for each PRD FR, name the role responsible
     (architect / engineer / qa / devops) and the consulted/informed roles.
  4. **Risks + mitigations** — top 3 schedule/scope risks with explicit
     mitigations (per PMBOK risk register format).
  5. **Definition of Done (project-level)** — checklist the
     release_manager will reference at ship gate.

Output ONLY the markdown.
""".strip()


_CONDUCTOR_PROMPT = """
You are the Spine **conductor** role (Scrum master + SAFe anchored).
The TRD has just been approved. Produce a sprint plan that the
engineer role can execute against.

SPRINT PLAN structure (start with `# Sprint plan — <Project Name>`):
  1. **Sprint goal** — one sentence: what shipped at the end of this
     sprint proves the PRD's desired outcome.
  2. **Task breakdown** — for each TRD build-sequence item, define
     story-card-sized tasks (1-2 day chunks). Format:
       - **T-1** Title — description (1-2 lines).
         Acceptance: <testable criteria>
         Files touched: <path>, <path>
         Estimate: <S/M/L>
  3. **Definition of Done (sprint-level)** — concrete pass/fail.
  4. **Standups + ceremonies** — propose cadence: daily standup
     summary format, sprint review, retro.
  5. **Impediment log** — placeholders the scrum master will fill in
     during execution.

Output ONLY the markdown.
""".strip()


_RELEASE_MANAGER_PROMPT = """
You are the Spine **release_manager** role (ITIL change-management
anchored). QA signed off. Produce a ship gate + concrete cloud-deploy
options. The user picks one target post-approval.

SHIP GATE structure (start with `# Ship gate — <Project Name>`):
  1. **Release scope** — one-paragraph summary of what's shipping.
  2. **Go / no-go checklist** — explicit boxes:
     - [ ] PRD signed off
     - [ ] TRD signed off
     - [ ] Code review complete
     - [ ] Test plan executed; coverage threshold met
     - [ ] No P0/P1 defects open
     - [ ] Rollback plan documented
     - [ ] Monitoring + alerting in place
     - [ ] Runbook for ops linked
  3. **Rollback plan** — concrete steps if launch fails.
  4. **Comms plan** — who gets notified pre/post launch, in what
     order, via what channel.
  5. **Cloud deploy options** — for the stack the architect chose,
     give the user 3-4 viable targets with the **exact shell commands**
     they'd run from the project workspace. Examples:
       * Vercel (Next.js / Vite SPA): `vercel deploy` + env-var setup
       * Railway (any stack with a Procfile or Dockerfile)
       * Fly.io (Dockerfile)
       * Render (web service from Git)
       * Cloudflare Workers / Pages (static + serverless)
     For each, include:
       - One-time setup commands (account/CLI install)
       - Deploy command
       - Env-var configuration
       - Custom-domain + TLS notes
     Recommend ONE as the default with a one-line justification.
  6. **Post-launch retro framing** — 3 questions the team should
     answer 1 week post-launch.

Output ONLY the markdown.
""".strip()


_ARCHITECT_PROMPT = """
You are the Spine **architect** role. The PRD has just been approved.
Produce a Technical Requirements Document (TRD) in markdown.

TRD structure (start with `# TRD — <Project Name>`):
  1. **Overview** — one paragraph mapping the PRD's desired outcome to
     a system shape (web app / API / job / etc).
  2. **Architecture** — components + data flow. Use a small ASCII or
     bullet diagram. Identify external dependencies.
  3. **Stack decision** — language, framework, datastore, hosting.
     Justify each in ONE sentence; reference TOGAF / PEAF principles
     where relevant.
  4. **Data model** — key tables / collections, fields, relationships.
  5. **Interfaces** — public API surface (REST endpoints / events).
  6. **Non-functional plan** — how the TRD meets each PRD NFR.
  7. **Build sequence** — ordered list of work items (3-8 items) the
     engineer role will implement. Each item: name, scope (1-2 lines),
     acceptance criteria.
  8. **Open architectural risks** — top 3, with mitigation.

Output ONLY the TRD markdown. No preamble. Mark inferred assumptions
with `[INFERRED]`.
""".strip()


_ENGINEER_PROMPT = """
You are the Spine **engineer** role. The sprint plan has been
approved. Produce REAL code that the user can run.

OUTPUT FORMAT — strict. Your entire reply must be ONLY:
  1. One short markdown intro (3-6 lines) explaining what you built +
     a tree diagram of the files.
  2. One file block per file you're creating. Each block is exactly:

        ===== FILE: <relative/path/from/project/root> =====
        <verbatim file contents — no markdown fences>
        ===== END FILE =====

  3. One closing block exactly:

        ===== RUN =====
        <bash commands the user runs locally to install + start>
        ===== END RUN =====

Hard rules:
  - Use the stack the architect chose in the TRD. Do not introduce
    new languages / frameworks.
  - Files must be CONSISTENT — every import resolves to a file you
    also produced.
  - Cover the MVP scope from the sprint plan's task list. If you
    can't fit everything, prioritize the critical path and note
    deferrals in the closing markdown.
  - Aim for 5-15 files. Bigger projects can split across sprints.
  - Include a README.md with one-paragraph project description +
    setup steps.
  - Include configuration files the stack needs (package.json,
    requirements.txt, Cargo.toml, etc.) with REAL dependency
    versions.
  - Tests: include ONE smoke test that exercises the critical path.
    Full coverage lives in the QA pass.
  - Do NOT include explanatory comments in code beyond what makes
    the code clear; Clean Code conventions apply.

If you cannot fit the project, output a minimal "hello world"-level
working version of the critical path and clearly mark what's missing.
""".strip()


_FILE_BLOCK_RE = re.compile(
    r"^=====\s*FILE:\s*([^\s=]+)\s*=====\s*$(.*?)^=====\s*END FILE\s*=====\s*$",
    re.MULTILINE | re.DOTALL,
)
_RUN_BLOCK_RE = re.compile(
    r"^=====\s*RUN\s*=====\s*$(.*?)^=====\s*END RUN\s*=====\s*$",
    re.MULTILINE | re.DOTALL,
)
_WORKSPACE_ROOT = Path(_os.environ.get("SPINE_PROJECTS_ROOT", "/var/lib/spine/projects"))


def _parse_engineer_output(text: str) -> tuple[str, list[tuple[str, str]], str]:
    """Parse engineer output into (intro_md, [(path, content), ...], run_block)."""
    files: list[tuple[str, str]] = []
    for m in _FILE_BLOCK_RE.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        # Strip the leading newline that follows the FILE marker.
        if content.startswith("\n"):
            content = content[1:]
        # Strip the trailing newline that precedes the END FILE marker.
        if content.endswith("\n"):
            content = content[:-1]
        # Reject path-traversal attempts.
        if ".." in path.split("/") or path.startswith("/"):
            continue
        files.append((path, content))
    run_m = _RUN_BLOCK_RE.search(text)
    run_block = run_m.group(1).strip() if run_m else ""
    # Intro = whatever comes before the first FILE marker.
    first_file_idx = text.find("===== FILE:")
    intro = text[:first_file_idx].strip() if first_file_idx >= 0 else text.strip()
    return intro, files, run_block


def _write_workspace_files(project_uuid: str, files: list[tuple[str, str]]) -> int:
    """Write each (path, content) tuple under <SPINE_PROJECTS_ROOT>/<uuid>/.

    Returns the count written. Skips any path that escapes the project
    root after resolve(); the parser already filters traversal but
    belt-and-suspenders.
    """
    project_dir = (_WORKSPACE_ROOT / project_uuid).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for path, content in files:
        target = (project_dir / path).resolve()
        try:
            target.relative_to(project_dir)
        except ValueError:
            logger.warning("workspace_path_escape", extra={"path": path})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    return written


_QA_PROMPT = """
You are the Spine **qa** role. The implementation plan has been
approved. Produce a test plan in markdown.

QA plan structure (start with `# Test plan — <Project Name>`):
  1. **Test pyramid** — unit / integration / e2e counts + rationale.
  2. **Per-FR coverage** — for each PRD FR, name the tests that cover
     it (cite by name). ISTQB traceability.
  3. **Risk-based testing** — top risks from PRD + TRD, how each is
     mitigated in the test plan.
  4. **Acceptance gates** — what passing means; coverage thresholds;
     who signs off.
  5. **Out of scope (this pass)** — accessibility / load / etc to
     defer.

Output ONLY the markdown.
""".strip()


async def _dispatch_role(
    *,
    role: str,
    project: dict[str, Any],
    role_prompt: str,
    artifact_key: str,
    next_phase: str,
    approval_card_kind: str,
    extra_context: str = "",
) -> None:
    """Generic dispatcher: load charter, call LLM, persist, push approval."""
    project_id = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata", {})
    try:
        charter = _load_charter(role)
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md") and role != "architect":
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("impl_md") and role == "qa":
            context_blocks.append("## Approved implementation plan\n\n" + prior["impl_md"])
        if extra_context:
            context_blocks.append(extra_context)
        system = (
            role_prompt
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n"
            + f"- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Your charter\n\n"
            + charter
            + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Produce your output for {project_name} now.")],
            system=system,
            max_tokens=8000,
            temperature=0.3,
        ))
        artifact_md = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("role_dispatch_failed",
                         extra={"project_id": project_id, "role": role})
        artifact_md = (
            f"# {role.title()} output — {project_name}\n\n"
            f"_Role dispatch failed: {type(exc).__name__}_\n\n"
            f"Check the Hub logs and re-run the dispatcher."
        )

    await _persist_metadata_patch(project_id, {artifact_key: artifact_md})

    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"Approve {role.upper()} output — {project_name}",
        "body": (
            f"The {role} role produced this artifact. Approve to advance "
            f"to the **{next_phase}** phase and dispatch the next role. "
            f"Reject to send the {role} back for another pass.\n\n"
            f"---\n\n" + artifact_md
        ),
        "severity": "info",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": approval_card_kind,
            "project_name": project_name,
            "project_uuid": project_id,
            "advances_phase_to": next_phase,
            "produced_by": role,
        },
    })


# ---------------------------------------------------------------------------
# DevOps stand-up — runs the engineer's install commands inside the
# project workspace, captures output, pushes a card with the result.
# ---------------------------------------------------------------------------


_INSTALL_HINTS = ("npm install", "npm ci", "pip install", "pnpm install",
                  "yarn install", "yarn", "bundle install", "cargo build",
                  "cargo fetch", "go mod download", "poetry install",
                  "uv pip install", "uv sync")
_DEVOPS_SHELL_TIMEOUT_SECS = 180


def _classify_run_block(run_block: str) -> tuple[list[str], list[str]]:
    """Split bash commands into (install_steps, start_steps).

    Lines that look like long-running servers (npm start / uvicorn /
    python -m / cargo run / etc) go to start_steps; everything else
    treated as install. Heuristic — not a full bash parser.
    """
    install: list[str] = []
    start: list[str] = []
    for raw in run_block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if any(h in lower for h in _INSTALL_HINTS):
            install.append(line)
            continue
        # Long-running server starts
        if any(tok in lower for tok in ("npm start", "npm run dev", "yarn dev",
                                        "uvicorn", "fastapi run", "python -m",
                                        "python app", "cargo run", "go run",
                                        "flask run", "rails server")):
            start.append(line)
            continue
        # Mkdir / cd / cp / echo etc → treat as install (cheap setup).
        install.append(line)
    return install, start


async def _dispatch_devops_install(*, project: dict[str, Any]) -> None:
    project_id = project["project_uuid"]
    project_name = project["name"]
    workspace = (_WORKSPACE_ROOT / project_id).resolve()
    if not workspace.exists():
        logger.warning("devops_no_workspace", extra={"project_id": project_id})
        # Fall back: skip devops, jump to qa.
        await _advance_phase(project_id, "verify")
        proj = (await _load_project_full(project_id)) or project
        await _dispatch_role(role="qa", project=proj, role_prompt=_QA_PROMPT,
                             artifact_key="qa_md", next_phase="verify",
                             approval_card_kind="qa_approval")
        return

    run_block = (project.get("metadata", {}) or {}).get("code_run_block") or ""
    install, start = _classify_run_block(run_block)

    log_chunks: list[str] = []
    all_ok = True
    for cmd in install:
        log_chunks.append(f"$ {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(),
                                                   timeout=_DEVOPS_SHELL_TIMEOUT_SECS)
            except asyncio.TimeoutError:
                proc.kill()
                log_chunks.append(f"[timeout after {_DEVOPS_SHELL_TIMEOUT_SECS}s]")
                all_ok = False
                break
            output = (stdout or b"").decode("utf-8", errors="replace")
            # Keep last ~4 KB of output per command so the card stays readable.
            tail = output if len(output) <= 4000 else "…[truncated]…\n" + output[-4000:]
            log_chunks.append(tail.rstrip())
            log_chunks.append(f"[exit={proc.returncode}]")
            if proc.returncode != 0:
                all_ok = False
                break
        except Exception as exc:  # noqa: BLE001
            log_chunks.append(f"[devops error: {type(exc).__name__}: {exc}]")
            all_ok = False
            break

    install_log = "\n".join(log_chunks) if log_chunks else "_(no install commands detected)_"
    start_cmd_md = "\n".join(f"  $ {s}" for s in start) if start else "  _(none — engineer didn't emit a start command)_"

    await _persist_metadata_patch(project_id, {
        "devops_install_log": install_log,
        "devops_install_ok": bool(all_ok),
        "devops_start_cmds": start,
    })

    status_line = "✅ install completed cleanly" if all_ok else "❌ install FAILED — reject to send back to engineer"
    body = (
        f"DevOps ran the engineer's install commands inside the project "
        f"workspace (`/var/lib/spine/projects/{project_id}/`).\n\n"
        f"**Status:** {status_line}\n\n"
        f"## Install log\n\n```\n{install_log}\n```\n\n"
        f"## To run locally\n\n"
        f"1. Click **Download .zip** on the workspace page (or the link above).\n"
        f"2. Unzip; cd into it.\n"
        f"3. Run the start commands:\n\n```bash\n"
        + ("\n".join(start) if start else "# (no start command — see engineer intro)")
        + "\n```\n\n"
        f"Approve when the app runs as expected. Reject (with feedback in "
        f"the next iteration) to send the engineer back for a fix."
    )

    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"DevOps stand-up — {project_name}",
        "body": body,
        "severity": "info" if all_ok else "warning",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": "devops_approval",
            "project_name": project_name,
            "project_uuid": project_id,
            "install_ok": bool(all_ok),
            "advances_phase_to": "verify",
            "produced_by": "devops",
        },
    })


# ---------------------------------------------------------------------------
# Engineer code-gen dispatcher — produces real files, writes to workspace,
# pushes a code_approval card with intro + file tree + RUN block summary.
# ---------------------------------------------------------------------------


async def _dispatch_engineer_codegen(*, project: dict[str, Any]) -> None:
    project_id = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata", {})
    try:
        charter = _load_charter("engineer")
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md"):
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("sprint_plan_md"):
            context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
        system = (
            _ENGINEER_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Your charter\n\n" + charter
            + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Generate the code for {project_name} now.")],
            system=system,
            max_tokens=16000,
            temperature=0.2,
        ))
        raw = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("engineer_codegen_failed", extra={"project_id": project_id})
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Engineer dispatch FAILED — {project_name}",
            "body": f"_Engineer LLM call raised {type(exc).__name__}: {exc!s}_\n\nReject + re-run.",
            "severity": "warning",
            "actions": ["ack", "reject"],
            "metadata": {"kind": "code_approval", "project_uuid": project_id,
                         "project_name": project_name, "error": str(exc)[:200]},
        })
        return

    intro_md, files, run_block = _parse_engineer_output(raw)
    written = _write_workspace_files(project_id, files)

    # Persist artifact metadata.
    await _persist_metadata_patch(project_id, {
        "code_intro_md": intro_md,
        "code_files": [{"path": p, "bytes": len(c)} for p, c in files],
        "code_run_block": run_block,
        "code_workspace": str((_WORKSPACE_ROOT / project_id).resolve()),
    })

    # Build card body: intro + file tree + run block.
    tree_lines = [f"  - `{p}` ({len(c):,} bytes)" for p, c in files]
    tree_md = "\n".join(tree_lines) if tree_lines else "  _(no files parsed — engineer output didn't follow the FILE block format)_"
    body = (
        f"The engineer role generated **{written}** files. Approve to advance "
        f"to the **verify** phase and dispatch the qa role for testing.\n\n"
        f"---\n\n{intro_md}\n\n"
        f"## Generated files\n\n{tree_md}\n\n"
        f"## Local run\n\n```bash\n{run_block or '# (no RUN block produced)'}\n```\n\n"
        f"## Workspace location\n\n"
        f"```\n{_WORKSPACE_ROOT / project_id}\n```"
    )
    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"Approve CODE output — {project_name}",
        "body": body,
        "severity": "info",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": "code_approval",
            "project_name": project_name,
            "project_uuid": project_id,
            "files_written": written,
            "advances_phase_to": "verify",
            "produced_by": "engineer",
        },
    })


# ---------------------------------------------------------------------------
# Hook entry point
# ---------------------------------------------------------------------------


async def on_decision_acked(card: Any, *, actor: str) -> None:
    """Top-level hook called from the ack handler. Idempotent in that
    re-acking the same card re-fires the side-effect; the caller is
    expected to gate via the card's status transition first.
    """
    md = getattr(card, "metadata", {}) or {}
    kind = md.get("kind")
    # Card.project_id is a TEXT field on the model but a BIGINT column in
    # spine_lifecycle.decision_card (V36). The DB persistence drops the
    # UUID string. Recover from metadata.project_uuid that the enqueueing
    # site is now responsible for setting.
    project_id = getattr(card, "project_id", None) or md.get("project_uuid")
    if not project_id:
        logger.warning("post_ack_no_project_id",
                       extra={"decision_id": getattr(card, "decision_id", None),
                              "kind": kind, "metadata_keys": list(md.keys())})
        return

    logger.info("post_ack_dispatch", extra={"kind": kind, "project_id": project_id, "actor": actor})

    if kind == "intake_briefing":
        # The seed card from project_create — user confirmed scope; nothing
        # downstream to do here, the intake chat is already running.
        return

    project = await _load_project_full(project_id)
    if project is None:
        logger.warning("post_ack_project_missing", extra={"project_id": project_id})
        return

    if kind == "prd_approval":
        await _advance_phase(project_id, "plan")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_role(
            role="planner", project=project, role_prompt=_PLANNER_PROMPT,
            artifact_key="roadmap_md", next_phase="plan",
            approval_card_kind="roadmap_approval",
        )
        return

    if kind == "roadmap_approval":
        await _dispatch_role(
            role="architect", project=project, role_prompt=_ARCHITECT_PROMPT,
            artifact_key="trd_md", next_phase="plan",
            approval_card_kind="trd_approval",
        )
        return

    if kind == "trd_approval":
        await _dispatch_role(
            role="conductor", project=project, role_prompt=_CONDUCTOR_PROMPT,
            artifact_key="sprint_plan_md", next_phase="plan",
            approval_card_kind="sprint_plan_approval",
        )
        return

    if kind == "sprint_plan_approval":
        await _advance_phase(project_id, "build")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_engineer_codegen(project=project)
        return

    if kind == "code_approval":
        # DevOps role exec's the install commands inside the project
        # workspace + pushes a stand-up card. User then runs locally
        # (download zip) + approves once verified.
        await _dispatch_devops_install(project=project)
        return

    if kind == "devops_approval":
        await _advance_phase(project_id, "verify")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_role(
            role="qa", project=project, role_prompt=_QA_PROMPT,
            artifact_key="qa_md", next_phase="verify",
            approval_card_kind="qa_approval",
        )
        return

    if kind == "qa_approval":
        await _dispatch_role(
            role="release_manager", project=project,
            role_prompt=_RELEASE_MANAGER_PROMPT,
            artifact_key="release_gate_md", next_phase="release",
            approval_card_kind="release_gate_approval",
        )
        return

    if kind == "release_gate_approval":
        await _advance_phase(project_id, "release")
        # Final card — celebrate; no further dispatch.
        _enqueue({
            "decision_class": "briefing",
            "project_id": project_id,
            "title": f"Project ready to ship — {project['name']}",
            "body": (
                f"All seven roles signed off on **{project['name']}**.\n\n"
                f"- Artifacts in `metadata`: prd_md, roadmap_md, trd_md, "
                f"sprint_plan_md, code_intro_md, qa_md, release_gate_md.\n"
                f"- Generated code lives at /var/lib/spine/projects/"
                f"`{project_id}`/ inside the Hub container.\n"
                f"- Next: a human pushes the code to git, runs the "
                f"approved test plan, then executes the deploy plan from "
                f"the release gate.\n"
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "project_complete",
                "project_name": project["name"],
                "project_uuid": project_id,
            },
        })
        return

    logger.debug("post_ack_no_handler", extra={"kind": kind, "project_id": project_id})


async def on_decision_rejected(card: Any, *, actor: str, reason: str = "") -> None:
    """Reject-side hook: route to the engineer fix-loop when the
    rejected card is in the build / verify lane.

    Supported kinds:
      code_approval    → engineer re-codes with prior code + reason
      devops_approval  → engineer re-codes with install-failure log
      qa_approval      → engineer re-codes with QA findings
    """
    md = getattr(card, "metadata", {}) or {}
    kind = md.get("kind")
    project_id = getattr(card, "project_id", None) or md.get("project_uuid")
    if not project_id:
        return
    if kind not in ("code_approval", "devops_approval", "qa_approval"):
        return
    project = await _load_project_full(project_id)
    if project is None:
        return
    logger.info("post_ack_reject_dispatch",
                extra={"kind": kind, "project_id": project_id, "actor": actor})
    feedback_block = (
        f"## Rejection feedback\n\n"
        f"The {md.get('produced_by','prior')} role's output was REJECTED by "
        f"`{actor}`{f' with: {reason}' if reason else ''}. "
        f"The previous output below has issues you must address in this revision."
    )
    prior = project.get("metadata") or {}
    extra_ctx_blocks = [feedback_block]
    if kind == "devops_approval" and prior.get("devops_install_log"):
        extra_ctx_blocks.append("## Prior install log (the issue is in here)\n\n```\n"
                                + prior["devops_install_log"][:6000] + "\n```")
    if prior.get("code_intro_md"):
        extra_ctx_blocks.append("## Prior engineer intro\n\n" + prior["code_intro_md"])

    project["_fix_loop_context"] = "\n\n---\n\n".join(extra_ctx_blocks)
    await _dispatch_engineer_codegen_with_feedback(project=project)


async def _dispatch_engineer_codegen_with_feedback(*, project: dict[str, Any]) -> None:
    """Re-run engineer with the rejection feedback prepended to the
    user prompt. Same output flow as the first pass.
    """
    project_id = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata", {}) or {}
    feedback = project.get("_fix_loop_context", "")
    try:
        charter = _load_charter("engineer")
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md"):
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("sprint_plan_md"):
            context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
        if feedback:
            context_blocks.append(feedback)
        system = (
            _ENGINEER_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Your charter\n\n" + charter
            + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Re-generate the code for {project_name}, addressing the rejection feedback.")],
            system=system, max_tokens=16000, temperature=0.2,
        ))
        raw = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("engineer_codegen_retry_failed", extra={"project_id": project_id})
        return

    intro_md, files, run_block = _parse_engineer_output(raw)
    written = _write_workspace_files(project_id, files)

    await _persist_metadata_patch(project_id, {
        "code_intro_md": intro_md,
        "code_files": [{"path": p, "bytes": len(c)} for p, c in files],
        "code_run_block": run_block,
        "code_workspace": str((_WORKSPACE_ROOT / project_id).resolve()),
        "code_fix_iteration": int(prior.get("code_fix_iteration", 0)) + 1,
    })

    tree_lines = [f"  - `{p}` ({len(c):,} bytes)" for p, c in files]
    tree_md = "\n".join(tree_lines) if tree_lines else "  _(no files parsed)_"
    iter_num = int(prior.get("code_fix_iteration", 0)) + 1
    body = (
        f"Engineer re-generated **{written}** files (fix iteration #{iter_num}). "
        f"Approve to advance; reject again to send back with another round of feedback.\n\n"
        f"---\n\n{intro_md}\n\n## Generated files\n\n{tree_md}\n\n"
        f"## Local run\n\n```bash\n{run_block or '# (no RUN block produced)'}\n```"
    )
    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"Approve CODE output (fix #{iter_num}) — {project_name}",
        "body": body,
        "severity": "info",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": "code_approval",
            "project_name": project_name,
            "project_uuid": project_id,
            "files_written": written,
            "fix_iteration": iter_num,
            "advances_phase_to": "verify",
            "produced_by": "engineer",
        },
    })


__all__ = ["on_decision_acked", "on_decision_rejected"]

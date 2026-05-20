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


def _load_enterprise_directives() -> str:
    """Read shared/charters/enterprise_directives.md once per call.

    The doc is the binding enterprise-grade SDLC contract every Spine
    role that touches production code must follow. Injected verbatim
    into the engineer + code_review system prompts.
    """
    path = _CHARTERS_DIR / "enterprise_directives.md"
    if not path.exists():
        return ""
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


def _emit(event_type: str, *, project_uuid: str, role: str, **extra: Any) -> None:
    """Broadcast a role-activity event onto the decisions SSE stream
    so the workspace's live-feed sees real-time progress."""
    try:
        from shared.api.routes.decisions import publish_event
        import time as _time
        publish_event({
            "type": event_type,
            "role": role,
            "project_uuid": project_uuid,
            "ts": _time.time(),
            **extra,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_failed", extra={"event": event_type, "error": str(exc)})


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


_CODE_REVIEW_PROMPT = """
You are the Spine **security_engineer** + **auditor** role performing
a real code review on what the engineer just produced. Anchor in:
OWASP Top 10, CWE catalog, NIST 800-53 control families,
language-specific best practices (Clean Code, secure-by-default), AND
Spine's enterprise SDLC directives (loaded into your context — treat
each numbered directive as a checklist item).

For each directive (1-15), state PASS / FAIL / N/A with one-line
evidence (file:line or "no relevant code"). Any FAIL on directives
1-9 or 11-13 is an automatic REVIEW BLOCK. Directives 10/14/15
without evidence is REVIEW BLOCK if the project ships money or PII.

You will receive every generated file (path + contents) plus the PRD,
TRD, and sprint plan as context.

Required output — strict markdown structure starting with
`# Code review — <Project Name>`:

  ## Summary
    One-paragraph posture + counts: N critical / N high / N medium / N low.
    State explicitly: **REVIEW PASS** or **REVIEW BLOCK**.
    Rule: any CRITICAL or HIGH finding → REVIEW BLOCK.

  ## Critical findings
    For each:
      - **Title** — short imperative summary.
      - **File:line** — `path/to/file.ext:NN-NN`
      - **What** — what the code does (1-2 lines).
      - **Why bad** — concrete attack scenario or compliance violation.
      - **Fix** — exact patch (allowlist, parameterize, etc).
      - **CWE / OWASP ref** — e.g. CWE-89 SQLi, OWASP A03.
    If none, write "_None._"

  ## High findings (same per-item shape)

  ## Medium findings (same)

  ## Low findings (same)

  ## Recommended fix order
    Numbered list — fix critical first, in dependency order.

Be ruthless. Look specifically for:
  - Mass assignment / privilege escalation in update endpoints
  - SQL string interpolation (Object.keys → SQL, parameterized vs raw)
  - Auth-bypass / weak middleware (token presence vs verification)
  - Race conditions (SELECT-then-INSERT, non-atomic uniqueness)
  - HTML/email injection (unescaped DB strings in templates)
  - Rate-limit spoofing (trusting X-Forwarded-For without proxy chain)
  - Unbounded fetch (no AbortSignal/timeout)
  - Env-var assertions at module load vs startup validation
  - Stripe/payment + DB orphans (PaymentIntent outside transaction)
  - Missing CSRF on state-changing endpoints
  - Cookie/SameSite/Secure flags

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
approved. Produce REAL code that the user can run AND that complies
with Spine's enterprise SDLC directives (loaded into your context
below). Read those directives first; treat them as binding.

Hard contract drawn from the directives:
  - No mass-assignment. Every mutator takes an explicit field
    allowlist as a `const` array.
  - No SQL string interpolation — always parameterize.
  - `z.number()` banned. Use `z.number().finite().safe()` with min/max.
  - No `!` non-null assertions outside tests. No `as` past validation.
  - Middleware does FULL JWT verify; cookie-presence is NOT auth.
  - External side-effects (Stripe / email / webhook) use idempotency
    keys + outbox pattern. Never inside a DB transaction holding
    locks.
  - Every route file starts with a `const AUTH = {...}` declarative
    block.
  - Every function ships with a `// Failure modes:` comment listing
    timeout / partial write / concurrent caller / malformed input /
    downstream 5xx and the code's behavior for each.
  - Env validated at boot via a Zod schema in `env.ts`; fail-fast.
    No `process.env.X!` at module scope elsewhere.
  - Structured JSON logs with trace_id / user_id / request_id; no
    `console.log`; no `catch {}` swallows.

Runtime-compat rules (so the local deploy actually boots):
  - Next.js: config file MUST be `next.config.mjs` (NOT `.ts` — Next
    14 rejects a TypeScript config and crashes on boot). Pin `next`
    to a real published version.
  - Provide a `dev` script. Local deploy runs `npm run dev` with
    host/port flags injected — read `process.env.PORT`, don't
    hardcode.
  - Every import resolves to a file you produced OR a real published
    dependency listed in package.json.

If a directive CAN'T be satisfied in a given file (legit reason),
emit on its own line in that file:
    // BLOCKED: <directive #> — <one-line reason + escalation path>
The security review reads these — either accepts with documented
reason or rejects + sends back. Do NOT silently violate.

After writing each file, run an adversarial-review pass on it (10
attack scenarios — SQL injection / XSS / IDOR / race / replay / mass
assignment / privesc / rate-limit spoof / orphan side-effect / DoS).
Fix the failures BEFORE finalizing the file.

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
_WORKSPACE_ROOT_HOST = _os.environ.get("SPINE_PROJECTS_DIR_HOST", str(_WORKSPACE_ROOT))


def _workspace_host_path(project_uuid: str) -> str:
    """Equivalent host path for a project's workspace dir.

    Inside the container we always use /var/lib/spine/projects/<uuid>;
    on the host the bind-mount target is whatever
    SPINE_PROJECTS_DIR resolved to in tools/hub-up.sh (default
    ~/spine-projects). The workspace UI shows THIS path so the user
    knows where their files actually are.
    """
    host = _WORKSPACE_ROOT_HOST.rstrip("/")
    if host.startswith("~"):
        host = _os.path.expanduser(host)
    return f"{host}/{project_uuid}"


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
    _emit("role_started", project_uuid=project_id, role=role,
          artifact_key=artifact_key, message=f"{role} role thinking…")
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
        _emit("role_finished", project_uuid=project_id, role=role,
              artifact_key=artifact_key, artifact_chars=len(artifact_md))
    except Exception as exc:  # noqa: BLE001
        logger.exception("role_dispatch_failed",
                         extra={"project_id": project_id, "role": role})
        _emit("role_failed", project_uuid=project_id, role=role,
              error=f"{type(exc).__name__}: {exc}")
        # Push a FIX-REQUIRED card with kind=role_failure (NOT the
        # forward-chain approval_card_kind). User must resolve the
        # root cause + re-ack the upstream card to retry. Prevents
        # an auto-ack storm where every downstream role also fails
        # and the chain blasts through to "release" with empty
        # artifacts.
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"{role.upper()} role FAILED — {project_name}",
            "body": (
                f"The **{role}** role raised an exception during LLM "
                f"dispatch. Approving this card is a no-op (chain will "
                f"NOT advance). Fix the root cause first, then re-ack "
                f"the upstream card to retry.\n\n"
                f"**Error:** `{type(exc).__name__}: {str(exc)[:500]}`\n\n"
                f"## Common causes\n\n"
                f"- `AuthenticationError 401` → `ANTHROPIC_API_KEY` is "
                f"missing or invalid in the Hub container env. Re-export "
                f"and `bash tools/hub-up.sh --rebuild`.\n"
                f"- `ProviderConfigError` → SDK not installed.\n"
                f"- Timeout / rate limit → wait, retry.\n\n"
                f"## To retry\n\n"
                f"1. Fix the root cause.\n"
                f"2. Re-ack the previous role's approval card (it stays "
                f"in the queue history; status flips back to acked + "
                f"refires `on_decision_acked`)."
            ),
            "severity": "critical",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "role_failure",
                "project_uuid": project_id,
                "project_name": project_name,
                "failed_role": role,
                "error_class": type(exc).__name__,
                "error_message": str(exc)[:500],
            },
        })
        return  # IMPORTANT: stop here. Do NOT chain forward.

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
# Code review — security_engineer/auditor inspects engineer output.
# Critical/High findings BLOCK the chain and trigger engineer fix-loop;
# medium/low findings flow through as advisory.
# ---------------------------------------------------------------------------


async def _dispatch_code_review(*, project: dict[str, Any]) -> None:
    project_id = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata", {}) or {}
    _emit("role_started", project_uuid=project_id, role="security_engineer",
          message="security_engineer reviewing generated code…")
    workspace = (_WORKSPACE_ROOT / project_id).resolve()
    code_blocks: list[str] = []
    if workspace.exists():
        for f in sorted(workspace.rglob("*")):
            if f.is_file() and f.stat().st_size <= 80_000:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    rel = f.relative_to(workspace)
                    code_blocks.append(f"### `{rel}`\n```\n{content}\n```")
                except Exception:  # noqa: BLE001
                    continue
    code_dump = "\n\n".join(code_blocks)
    # Trim to a reasonable LLM input ceiling (~120 KB of code text).
    if len(code_dump) > 120_000:
        code_dump = code_dump[:120_000] + "\n\n[truncated — review focuses on shown files]"

    try:
        sec_charter = _load_charter("security_engineer")
        aud_charter = _load_charter("auditor")
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md"):
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("sprint_plan_md"):
            context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
        context_blocks.append("## Generated code files\n\n" + code_dump)
        directives = _load_enterprise_directives()
        system = (
            _CODE_REVIEW_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Spine enterprise SDLC directives (binding checklist)\n\n" + directives
            + "\n\n---\n\n## security_engineer charter\n\n" + sec_charter
            + "\n\n---\n\n## auditor charter\n\n" + aud_charter
            + "\n\n---\n\n" + "\n\n---\n\n".join(context_blocks)
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Review {project_name} now.")],
            system=system, max_tokens=12000, temperature=0.1,
        ))
        review_md = resp.content.strip()
        _emit("role_finished", project_uuid=project_id, role="security_engineer",
              artifact_chars=len(review_md))
    except Exception as exc:  # noqa: BLE001
        logger.exception("code_review_failed", extra={"project_id": project_id})
        _emit("role_failed", project_uuid=project_id, role="security_engineer",
              error=f"{type(exc).__name__}: {exc}")
        review_md = f"# Code review — {project_name}\n\n_Dispatch failed: {type(exc).__name__}_"

    blocked = "REVIEW BLOCK" in review_md.upper() or "## Critical findings" in review_md and "_None._" not in review_md.split("## Critical findings", 1)[1].split("##", 1)[0]

    await _persist_metadata_patch(project_id, {
        "code_review_md": review_md,
        "code_review_blocked": bool(blocked),
    })

    if blocked:
        # Auto-trigger engineer fix-loop with the review findings as feedback.
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Code review BLOCKED — {project_name}",
            "body": (
                f"The **security_engineer** role flagged critical or high "
                f"findings. The engineer will re-code with these findings as "
                f"feedback as soon as you approve this card.\n\n"
                f"Reject to skip the fix-loop and proceed anyway (NOT "
                f"recommended).\n\n---\n\n" + review_md
            ),
            "severity": "critical",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "code_review_blocked",
                "project_uuid": project_id,
                "project_name": project_name,
                "produced_by": "security_engineer",
            },
        })
    else:
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Code review PASS — {project_name}",
            "body": (
                f"No critical/high findings. Approve to advance to "
                f"**devops install + smoke**.\n\n---\n\n" + review_md
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "code_review_pass",
                "project_uuid": project_id,
                "project_name": project_name,
                "produced_by": "security_engineer",
            },
        })


# ---------------------------------------------------------------------------
# Local deploy — starts the engineer's project as a managed subprocess
# inside the Hub container, binding to a free port from the published
# 9000-9019 range so the user can hit it from their browser.
# ---------------------------------------------------------------------------


_DEPLOY_PORT_MIN = 18000
_DEPLOY_PORT_MAX = 18019
_DEPLOY_PIDS: dict[str, dict[str, Any]] = {}  # project_uuid → {pid, port, cmd, started}


def _pick_free_port() -> Optional[int]:
    import socket as _sock
    taken = {info["port"] for info in _DEPLOY_PIDS.values() if info.get("port")}
    for port in range(_DEPLOY_PORT_MIN, _DEPLOY_PORT_MAX + 1):
        if port in taken:
            continue
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            return port
        except OSError:
            continue
    return None


def get_deployment(project_uuid: str) -> Optional[dict[str, Any]]:
    return _DEPLOY_PIDS.get(project_uuid)


async def stop_deployment(project_uuid: str) -> bool:
    info = _DEPLOY_PIDS.get(project_uuid)
    if not info:
        return False
    proc = info.get("proc")
    if proc is not None:
        try:
            proc.kill()
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass
    _DEPLOY_PIDS.pop(project_uuid, None)
    _emit("deploy_stopped", project_uuid=project_uuid, role="devops_release")
    return True


async def _dispatch_local_deploy(*, project: dict[str, Any]) -> None:
    project_id = project["project_uuid"]
    project_name = project["name"]
    _emit("role_started", project_uuid=project_id, role="devops_release",
          message="standing up local deployment…")
    workspace = (_WORKSPACE_ROOT / project_id).resolve()
    if not workspace.exists():
        logger.warning("local_deploy_no_workspace", extra={"project_id": project_id})
        return

    md = project.get("metadata", {}) or {}
    start_cmds: list[str] = md.get("devops_start_cmds") or []
    # For local review we ALWAYS prefer the dev server over a prod start
    # (prod `next start` / `vite preview` need a build first). Detect the
    # framework from package.json scripts + pick the dev script.
    pkg_path = workspace / "package.json"
    if pkg_path.exists():
        try:
            import json as _json
            scripts = (_json.loads(pkg_path.read_text()).get("scripts") or {})
        except Exception:  # noqa: BLE001
            scripts = {}
        if "dev" in scripts:
            # Next.js / Vite / Astro all expose `dev`; force dev for review.
            start_cmds = ["npm run dev"]
        elif not start_cmds:
            start_cmds = ["npm start"]
    if not start_cmds:
        if (workspace / "app.py").exists() or (workspace / "main.py").exists():
            start_cmds = ["python app.py" if (workspace / "app.py").exists() else "python main.py"]
        else:
            _emit("role_failed", project_uuid=project_id, role="devops_release",
                  error="no start command in metadata or detectable entry point")
            _enqueue({
                "decision_class": "approval",
                "project_id": project_id,
                "title": f"Local deploy FAILED — {project_name}",
                "body": "Couldn't find a start command. Engineer didn't emit one and "
                        "no `package.json` / `app.py` / `main.py` in workspace.",
                "severity": "warning", "actions": ["ack", "reject"],
                "metadata": {"kind": "deploy_status", "project_uuid": project_id,
                             "project_name": project_name, "deploy_ok": False},
            })
            return

    # Stop any prior deployment for this project before starting a new one.
    if project_id in _DEPLOY_PIDS:
        await stop_deployment(project_id)

    port = _pick_free_port()
    if port is None:
        _emit("role_failed", project_uuid=project_id, role="devops_release",
              error="no free port in 9000-9019 range")
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Local deploy FAILED — {project_name}",
            "body": "No free port in the 18000-18019 range — stop another deployment first.",
            "severity": "warning", "actions": ["ack", "reject"],
            "metadata": {"kind": "deploy_status", "project_uuid": project_id,
                         "project_name": project_name, "deploy_ok": False},
        })
        return

    # Force-bind to 0.0.0.0 inside the container so the subprocess is
    # reachable through the published port mapping. Most frameworks
    # default to 127.0.0.1 which would 404 from the host.
    env = {
        **_os.environ,
        "PORT": str(port),
        "HOST": "0.0.0.0",          # Next.js, Astro, Vite
        "HOSTNAME": "0.0.0.0",      # Next.js standalone
        "BIND_ADDR": "0.0.0.0",
        "FLASK_RUN_HOST": "0.0.0.0",
        "FASTAPI_HOST": "0.0.0.0",
        "UVICORN_HOST": "0.0.0.0",
        # Tighten common npm scripts that hardcode --port or
        # --hostname=localhost. We can't rewrite arbitrary commands,
        # but env-driven frameworks above cover ~90% of the stacks
        # Spine generates.
    }

    is_next = (workspace / "next.config.ts").exists() or (workspace / "next.config.js").exists() \
        or (workspace / "next.config.mjs").exists()

    def _harden(cmd: str) -> str:
        """Append host/port flags the framework's CLI actually wants.
        Best-effort string mutation; env vars cover the rest."""
        lower = cmd.lower()
        if "npm run dev" in lower or "npm start" in lower:
            if is_next:
                # Next.js dev/start: -H hostname, -p port (NOT --host).
                cmd = cmd + f" -- -H 0.0.0.0 -p {port}"
            elif "--host" not in lower:
                # Vite / Astro accept --host + --port after `--`.
                cmd = cmd + f" -- --host 0.0.0.0 --port {port}"
        elif "vite" in lower or "astro dev" in lower:
            if "--host" not in lower:
                cmd = cmd + f" --host 0.0.0.0 --port {port}"
        elif "flask run" in lower and "--host" not in lower:
            cmd = cmd + f" --host 0.0.0.0 --port {port}"
        elif "uvicorn" in lower and "--host" not in lower:
            cmd = cmd + f" --host 0.0.0.0 --port {port}"
        return cmd

    hardened = [_harden(c) for c in start_cmds]
    # Auto-install deps if missing — deploys often run after a Hub
    # rebuild wiped node_modules (it lives in the bind-mounted workspace
    # but npm install may never have run, or a fresh clone needs it).
    prelude: list[str] = []
    if (workspace / "package.json").exists() and not (workspace / "node_modules").exists():
        prelude.append("npm install --no-audit --no-fund")
    elif (workspace / "requirements.txt").exists():
        prelude.append("pip install -q -r requirements.txt")
    full_cmd = " && ".join(prelude + hardened)
    try:
        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_deploy_spawn_failed", extra={"project_id": project_id})
        _emit("role_failed", project_uuid=project_id, role="devops_release",
              error=f"{type(exc).__name__}: {exc}")
        return

    import time as _time
    started = _time.time()
    _DEPLOY_PIDS[project_id] = {
        "proc": proc, "pid": proc.pid, "port": port,
        "cmd": full_cmd, "started": started,
        "url": f"http://localhost:{port}",
    }

    # Background log tail — keeps last 4KB so the UI can show recent output.
    async def _tail_logs() -> None:
        chunks: list[bytes] = []
        chunk_total = 0
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                chunks.append(line)
                chunk_total += len(line)
                if chunk_total > 8192:
                    chunks = chunks[-50:]
                    chunk_total = sum(len(c) for c in chunks)
                info = _DEPLOY_PIDS.get(project_id)
                if info is not None:
                    info["log_tail"] = b"".join(chunks).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.debug("deploy_tail_failed", extra={"project_id": project_id, "error": str(exc)})

    asyncio.create_task(_tail_logs())

    # Wait briefly for the server to come up + emit running event.
    await asyncio.sleep(3.0)
    still_running = proc.returncode is None

    await _persist_metadata_patch(project_id, {
        "deploy_local_url": f"http://localhost:{port}",
        "deploy_local_port": port,
        "deploy_local_started": started,
        "deploy_local_running": bool(still_running),
    })

    _emit("role_finished", project_uuid=project_id, role="devops_release",
          deploy_url=f"http://localhost:{port}", running=still_running)

    status_line = (
        f"✅ Live at [http://localhost:{port}](http://localhost:{port})"
        if still_running else
        f"❌ Process exited (rc={proc.returncode}) — see log tail"
    )
    info = _DEPLOY_PIDS.get(project_id, {})
    log_tail = info.get("log_tail", "")[:2000]

    body = (
        f"DevOps started the project locally. {status_line}\n\n"
        f"## Command\n\n```bash\n{full_cmd}\n```\n\n"
        f"**Port:** {port} (range 18000-18019 published from Hub container)  \n"
        f"**Workspace:** `/var/lib/spine/projects/{project_id}/`  \n"
        f"**PID:** {proc.pid}\n\n"
        f"## Recent stdout/stderr\n\n```\n{log_tail or '(no output yet)'}\n```\n\n"
        f"Approve to keep running. Reject to stop the process (engineer can iterate)."
    )
    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"Local deployment — {project_name}",
        "body": body,
        "severity": "info" if still_running else "warning",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": "deploy_status",
            "project_uuid": project_id,
            "project_name": project_name,
            "deploy_ok": bool(still_running),
            "deploy_url": f"http://localhost:{port}",
            "deploy_port": port,
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
    _emit("role_started", project_uuid=project_id, role="devops",
          message="devops running install commands…")
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
    _emit("role_finished", project_uuid=project_id, role="devops",
          install_ok=bool(all_ok), commands=len(install))

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
    _emit("role_started", project_uuid=project_id, role="engineer",
          message="engineer role generating code…")
    try:
        charter = _load_charter("engineer")
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md"):
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("sprint_plan_md"):
            context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
        directives = _load_enterprise_directives()
        system = (
            _ENGINEER_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Spine enterprise SDLC directives (binding)\n\n" + directives
            + "\n\n---\n\n## Your charter\n\n" + charter
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
    _emit("role_finished", project_uuid=project_id, role="engineer",
          files_written=written, total_chars=sum(len(c) for _, c in files))

    # Persist artifact metadata.
    await _persist_metadata_patch(project_id, {
        "code_intro_md": intro_md,
        "code_files": [{"path": p, "bytes": len(c)} for p, c in files],
        "code_run_block": run_block,
        "code_workspace": str((_WORKSPACE_ROOT / project_id).resolve()),
        "code_workspace_host": _workspace_host_path(project_id),
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

    if kind == "role_failure":
        # Acking a failure card is a no-op — chain does NOT advance.
        # User must fix root cause + re-ack upstream card to retry.
        logger.info("role_failure_acked", extra={"project_id": project_id,
                                                  "failed_role": md.get("failed_role")})
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
        # Insert security_engineer + auditor code-review BEFORE devops.
        # Critical/High findings block the chain + trigger engineer
        # fix-loop. Clean review → user acks pass card → devops runs.
        await _dispatch_code_review(project=project)
        return

    if kind == "code_review_pass":
        # User confirmed the review's recommendation to proceed.
        await _dispatch_devops_install(project=project)
        return

    if kind == "code_review_blocked":
        # User acked the block → fire engineer fix-loop with the review
        # findings as feedback. Engineer re-codes addressing each one.
        review_md = (project.get("metadata") or {}).get("code_review_md", "")
        project["_fix_loop_context"] = (
            "## Code review found CRITICAL/HIGH issues\n\n"
            "The security_engineer role found problems with the engineer's "
            "prior code. Address each finding in this revision; the same "
            "review will run again on the new code.\n\n"
            + review_md
        )
        await _dispatch_engineer_codegen_with_feedback(project=project)
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

    if kind == "local_deploy_prompt":
        await _dispatch_local_deploy(project=project)
        return

    if kind == "host_deploy_prompt":
        md_proj = project.get("metadata", {}) or {}
        start_cmds = md_proj.get("devops_start_cmds") or []
        start_block = "\n".join(start_cmds) if start_cmds else "# (no explicit start command)"
        zip_url = f"/api/v2/projects/{project_id}/workspace/zip"
        _enqueue({
            "decision_class": "briefing",
            "project_id": project_id,
            "title": f"Host run instructions — {project['name']}",
            "body": (
                f"**Step 1.** Download the project zip:\n\n"
                f"  → [{zip_url}]({zip_url})\n\n"
                f"**Step 2.** Unzip it and `cd` into the directory.\n\n"
                f"**Step 3.** Run these commands (the engineer's start "
                f"block):\n\n```bash\n{start_block}\n```\n\n"
                f"**Step 4.** Open the project URL it prints (usually "
                f"`http://localhost:3000` for Node, `http://localhost:5173` "
                f"for Vite, `http://localhost:8000` for Python).\n\n"
                f"Need to iterate? Reject any prior decision card with "
                f"feedback — engineer re-codes on rejection."
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "host_deploy_instructions",
                "project_uuid": project_id,
                "project_name": project["name"],
            },
        })
        return

    if kind == "deploy_status":
        # User acked a successful local deploy — leave running.
        return

    if kind == "host_deploy_instructions":
        return

    if kind == "release_gate_approval":
        await _advance_phase(project_id, "release")
        # Offer the user TWO deploy paths — Container or Host — plus
        # cloud is documented in release_gate_md (manual paste for now;
        # automated cloud-deploy lands when vault-stored creds wire up).
        md_proj = project.get("metadata", {}) or {}
        start_cmds = md_proj.get("devops_start_cmds") or []
        start_block = "\n".join(start_cmds) if start_cmds else "# (no explicit start command; check engineer intro)"
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Deploy IN HUB CONTAINER — {project['name']}",
            "body": (
                f"Approve to stand the project up **inside this Hub's "
                f"container**. Devops runs the engineer's commands, binds "
                f"to a free port in 18000-18019, and gives you a clickable "
                f"`http://localhost:NNNNN`.\n\n"
                f"Good when:\n"
                f"  - You want to click and see it work immediately\n"
                f"  - You don't have the project's stack installed on your "
                f"machine (node / python / etc.)\n"
                f"  - Hub container already has node/npm/python/git\n\n"
                f"Less good when:\n"
                f"  - You want to edit + iterate on the code locally\n"
                f"  - The project needs hardware Hub can't see (GPU / Bluetooth / etc.)\n\n"
                f"Reject this card if you prefer the **Run on your machine** "
                f"option below."
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "local_deploy_prompt",
                "project_uuid": project_id,
                "project_name": project["name"],
                "deploy_target": "container",
            },
        })
        _enqueue({
            "decision_class": "approval",
            "project_id": project_id,
            "title": f"Run ON YOUR MACHINE — {project['name']}",
            "body": (
                f"Approve to get the **download-and-run script** for your "
                f"laptop. The Hub will hand you:\n\n"
                f"  1. A zip of the project workspace (link in the artifacts "
                f"panel above)\n"
                f"  2. The exact commands to run after you unzip:\n\n"
                f"```bash\n{start_block}\n```\n\n"
                f"Good when:\n"
                f"  - You want the code in your editor + run it under your "
                f"dev tooling\n"
                f"  - You need real localhost (Hub-bound ports are isolated)\n"
                f"  - You'll iterate + push to your own git remote\n\n"
                f"Reject this card if you want the **Run in Hub container** "
                f"option above instead. Cloud-target deploy commands are in "
                f"the `release_gate_md` artifact (run them yourself for now; "
                f"automated cloud-deploy lands when we wire vault-stored "
                f"provider creds — coming next)."
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "host_deploy_prompt",
                "project_uuid": project_id,
                "project_name": project["name"],
                "deploy_target": "host",
            },
        })
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
    if kind == "deploy_status":
        # Reject means "stop the deployment"
        project_id_md = md.get("project_uuid") or getattr(card, "project_id", None)
        if project_id_md:
            await stop_deployment(project_id_md)
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
        directives = _load_enterprise_directives()
        system = (
            _ENGINEER_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Spine enterprise SDLC directives (binding)\n\n" + directives
            + "\n\n---\n\n## Your charter\n\n" + charter
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
        "code_workspace_host": _workspace_host_path(project_id),
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

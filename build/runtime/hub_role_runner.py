"""Hub-facing build-phase role execution (engineer, security review, devops).

Called from ``build_dispatch`` MCP when the orchestrator routes through
``router.sh``. Replaces inline LLM / shell dispatch in ``_post_ack.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.llm import LLMRequest, Message, stream_async
from shared.runtime.project_workspace import (
    bootstrap_project_git_repo,
    commit_workspace,
    projects_root,
    repo_slug_for_project,
    resolve_code_dir,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHARTERS_DIR = _REPO_ROOT / "shared" / "charters"
_DEFAULT_MODEL = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")
_DEVOPS_SHELL_TIMEOUT_SECS = 180
_INSTALL_HINTS = (
    "npm install", "npm ci", "pip install", "pnpm install", "yarn install",
    "yarn", "bundle install", "cargo build", "cargo fetch", "go mod download",
    "poetry install", "uv pip install", "uv sync",
)

_FILE_BLOCK_RE = re.compile(
    r"^=====\s*FILE:\s*([^\s=]+)\s*=====\s*$(.*?)^=====\s*END FILE\s*=====\s*$",
    re.MULTILINE | re.DOTALL,
)
_RUN_BLOCK_RE = re.compile(
    r"^=====\s*RUN\s*=====\s*$(.*?)^=====\s*END RUN\s*=====\s*$",
    re.MULTILINE | re.DOTALL,
)
_IMPL_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".cs", ".swift", ".vue", ".svelte",
})
_MAX_EXTRA_CONTEXT_CHARS = 8000
_ENGINEER_MAX_TOKENS = 32000
_FORMAT_RETRY_USER = (
    "Your previous reply did not contain any parseable "
    "===== FILE: <path> ===== ... ===== END FILE ===== blocks. "
    "Regenerate NOW using the exact OUTPUT FORMAT from your instructions. "
    "Emit the primary implementation files the sprint plan requires "
    "(not docs-only)."
)


@dataclass
class HubBuildRoleResult:
    ok: bool
    role: str
    directive_id: str
    result_kind: str = "artifact"
    artifact_key: str = ""
    artifact_md: str = ""
    error_class: str | None = None
    error_message: str | None = None
    project_uuid: str = ""
    project_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _workspace_root() -> Path:
    return projects_root()


def _workspace_host_path(project_uuid: str, metadata: dict[str, Any] | None = None) -> str:
    from shared.runtime.project_workspace import workspace_host_path  # noqa: PLC0415

    return workspace_host_path(project_uuid, metadata)


def _load_project(project_id: str) -> dict[str, Any]:
    from build.runtime.build_dispatcher import _load_project as load  # noqa: PLC0415

    row = load(project_id)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata or "{}")
    return {
        "id": row["id"],
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row.get("work_item_type") or "feature",
        "current_phase": row["current_phase"],
        "metadata": metadata,
    }


def _persist_metadata(project_id: str, patch: dict[str, Any]) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415

    row = _load_project(project_id)
    _merge_metadata(int(row["id"]), patch)


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    return path.read_text(encoding="utf-8") if path.exists() else f"# Charter for {role}"


def _load_enterprise_directives() -> str:
    path = _CHARTERS_DIR / "enterprise_directives.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _engineer_prompt_text() -> str:
    from shared.api.routes._post_ack import _ENGINEER_PROMPT  # noqa: PLC0415

    return _ENGINEER_PROMPT


def _has_implementation_files(files: list[tuple[str, str]]) -> bool:
    for path, _content in files:
        rel = path.strip().replace("\\", "/")
        if rel.startswith("docs/"):
            continue
        suffix = Path(rel).suffix.lower()
        if suffix in _IMPL_SUFFIXES:
            return True
        if rel in ("package.json", "Cargo.toml", "go.mod", "pyproject.toml", "requirements.txt"):
            return True
    return False


def _truncate_extra_context(text: str, *, max_len: int = _MAX_EXTRA_CONTEXT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 40].rstrip() + "\n\n…[context truncated for engineer]…"


def _parse_engineer_output(text: str) -> tuple[str, list[tuple[str, str]], str]:
    files: list[tuple[str, str]] = []
    for m in _FILE_BLOCK_RE.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        if content.startswith("\n"):
            content = content[1:]
        if content.endswith("\n"):
            content = content[:-1]
        if ".." in path.split("/") or path.startswith("/"):
            continue
        files.append((path, content))
    run_m = _RUN_BLOCK_RE.search(text)
    run_block = run_m.group(1).strip() if run_m else ""
    first_file_idx = text.find("===== FILE:")
    intro = text[:first_file_idx].strip() if first_file_idx >= 0 else text.strip()
    return intro, files, run_block


def _write_workspace_files(code_dir: Path, files: list[tuple[str, str]]) -> int:
    code_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for path, content in files:
        target = (code_dir / path).resolve()
        try:
            target.relative_to(code_dir)
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    return written


def _classify_run_block(run_block: str) -> tuple[list[str], list[str]]:
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
        if any(tok in lower for tok in (
            "npm start", "npm run dev", "yarn dev", "uvicorn", "fastapi run",
            "python -m", "python app", "cargo run", "go run", "flask run", "rails server",
        )):
            start.append(line)
            continue
        install.append(line)
    return install, start


async def _run_engineer(
    project: dict[str, Any],
    extra_context: str = "",
    *,
    directive: str = "PRODUCE_CODE",
    actor: str = "orchestrator",
) -> HubBuildRoleResult:
    from shared.runtime.kg_role_context import retrieve_kg_context_for_dispatch
    from shared.runtime.role_runtime import (
        append_directive_context,
        begin_directive,
        complete_directive,
        fail_directive,
    )

    handle = begin_directive(
        project["project_uuid"],
        "engineer",
        directive,
        actor,
    )
    directive_id = handle.directive_id
    role = "engineer"
    project_uuid = project["project_uuid"]
    project_name = project["name"]
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    role_log(project_uuid, role, f"Directive {directive_id} started ({directive})")
    prior = project.get("metadata") or {}
    code_dir = resolve_code_dir(project_uuid, prior)
    kg_repo = str(prior.get("repo") or repo_slug_for_project(project_uuid, prior))

    kg_block = retrieve_kg_context_for_dispatch(
        project_id=project_uuid,
        repo=kg_repo,
        role=role,
        phase=str(project.get("current_phase") or "build_in_progress"),
        directive=directive,
        project_name=project_name,
        commit_sha=prior.get("last_commit_sha"),
    )
    if kg_block:
        append_directive_context(handle, kg_block)
        extra_context = f"{extra_context}\n\n{kg_block}".strip() if extra_context else kg_block
        role_log(project_uuid, role, f"Loaded KG context ({len(kg_block):,} chars)")

    directives = _load_enterprise_directives()
    context_blocks: list[str] = []
    if prior.get("prd_md"):
        context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
    if prior.get("trd_md"):
        context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
    if prior.get("sprint_plan_md"):
        context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
    if extra_context:
        context_blocks.append(_truncate_extra_context(extra_context))
        if "REMEDIATE" in directive.upper() or "review" in extra_context.lower()[:200]:
            role_log(project_uuid, role, "Applying code-review remediation feedback")

    system = (
        _engineer_prompt_text()
        + "\n\n---\n\n## Spine enterprise SDLC directives\n\n" + directives
        + "\n\n---\n\n## Your charter\n\n" + _load_charter("engineer")
        + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
    )
    user_msg = f"Generate the code for {project_name} now."

    from build.runtime.engineer_hybrid import (
        executor_available,
        hybrid_enabled,
        run_hybrid_engineer,
    )
    from build.runtime.engineer_squad import run_engineer_squad, squad_enabled

    async def _llm_engineer(user: str) -> str:
        role_log(project_uuid, role, f"Calling LLM ({_DEFAULT_MODEL})…")
        parts: list[str] = []
        chars = 0
        last_emit = time.monotonic()
        async for chunk in stream_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=user)],
            system=system,
            max_tokens=_ENGINEER_MAX_TOKENS,
            temperature=0.2,
        )):
            delta = chunk.content or ""
            if not delta:
                continue
            parts.append(delta)
            chars += len(delta)
            now = time.monotonic()
            if now - last_emit >= 2.5:
                role_log(project_uuid, role, f"Generating code… {chars:,} chars received")
                last_emit = now
        text = "".join(parts).strip()
        role_log(
            project_uuid,
            role,
            f"LLM response complete ({chars:,} chars)",
            level="success" if text else "warn",
        )
        return text

    raw = ""
    hybrid_used = False
    squad_used = False
    squad_intro = ""
    llm_used = False
    if hybrid_enabled() and executor_available():
        role_log(project_uuid, role, "Trying hybrid engineer (local executor)…")
        hybrid = run_hybrid_engineer(
            prompt=system + "\n\n---\n\n## Task\n\n" + user_msg,
            workspace=code_dir,
        )
        if hybrid.ok and hybrid.output.strip():
            raw = hybrid.output.strip()
            hybrid_used = True
            role_log(project_uuid, role, "Hybrid engineer returned output", level="success")

    if not raw and squad_enabled():
        role_log(project_uuid, role, "Running engineer squad…")
        squad = await run_engineer_squad(
            system_base=system,
            user_msg=user_msg,
            project_name=project_name,
        )
        if squad.raw_combined.strip():
            raw = squad.raw_combined.strip()
            squad_intro = squad.intro_md
            squad_used = True
            role_log(project_uuid, role, "Engineer squad finished", level="success")

    if not raw:
        try:
            raw = await _llm_engineer(user_msg)
            llm_used = True
        except Exception as exc:  # noqa: BLE001
            role_log(project_uuid, role, f"Engineer failed: {type(exc).__name__}: {exc}", level="error")
            fail_directive(handle, str(exc))
            return HubBuildRoleResult(
                ok=False, role=role, directive_id=directive_id,
                result_kind="code_approval",
                error_class=type(exc).__name__, error_message=str(exc)[:500],
                project_uuid=project_uuid, project_name=project_name,
            )

    intro_md, files, run_block = _parse_engineer_output(raw)
    role_log(project_uuid, role, f"Parsed {len(files)} file block(s) from model output")
    if llm_used and not _has_implementation_files(files):
        role_log(project_uuid, role, "No implementation files found — retrying with format hint", level="warn")
        try:
            retry_raw = await _llm_engineer(_FORMAT_RETRY_USER)
            retry_intro, retry_files, retry_run = _parse_engineer_output(retry_raw)
            if _has_implementation_files(retry_files):
                raw = retry_raw
                intro_md, files, run_block = retry_intro, retry_files, retry_run
            elif retry_files and not files:
                raw = retry_raw
                intro_md, files, run_block = retry_intro, retry_files, retry_run
        except Exception as exc:  # noqa: BLE001
            fail_directive(handle, str(exc))
            return HubBuildRoleResult(
                ok=False, role=role, directive_id=directive_id,
                result_kind="code_approval",
                error_class=type(exc).__name__, error_message=str(exc)[:500],
                project_uuid=project_uuid, project_name=project_name,
            )
    if squad_used:
        intro_md = squad_intro or (
            intro_md[:4000] + ("…" if len(intro_md) > 4000 else "")
            if intro_md else "Engineer squad completed; see generated files."
        )
    elif squad_intro:
        intro_md = squad_intro if not intro_md else f"{squad_intro}\n\n---\n\n{intro_md}"
    for path, _content in files[:10]:
        role_log(project_uuid, role, f"Writing {path}")
    if len(files) > 10:
        role_log(project_uuid, role, f"… and {len(files) - 10} more file(s)")
    written = _write_workspace_files(code_dir, files)
    if written == 0 or not _has_implementation_files(files):
        msg = (
            "Engineer produced no parseable implementation files "
            f"(parsed={len(files)}, written={written}). "
            "Output must use ===== FILE: ... ===== END FILE ===== blocks."
        )
        fail_directive(handle, msg)
        role_log(project_uuid, role, msg, level="error")
        return HubBuildRoleResult(
            ok=False, role=role, directive_id=directive_id,
            result_kind="code_approval",
            error_class="engineer_no_code",
            error_message=msg[:500],
            project_uuid=project_uuid, project_name=project_name,
        )
    if not (code_dir / ".git").exists():
        bootstrap_project_git_repo(project_uuid, project_name, cold_index=False, metadata=prior)
    commit = commit_workspace(project_uuid, f"engineer: {directive_id}", metadata=prior)
    role_log(
        project_uuid,
        role,
        f"Wrote {written} file(s) to workspace"
        + (f" · commit {commit.commit_sha[:12]}" if commit.commit_sha else ""),
        level="success",
    )
    patch = {
        "code_intro_md": intro_md,
        "code_files": [{"path": p, "bytes": len(c)} for p, c in files],
        "code_run_block": run_block,
        "code_workspace": str(code_dir),
        "code_workspace_host": _workspace_host_path(project_uuid, prior),
        "repo": kg_repo,
    }
    if commit.commit_sha:
        patch["last_commit_sha"] = commit.commit_sha
    if commit.files_indexed:
        patch["kg_last_index_files"] = commit.files_indexed
    _persist_metadata(project_uuid, patch)
    report = intro_md or f"Wrote {written} file(s)."
    complete_directive(
        handle,
        report,
        ok=True,
        extra={"files_written": written, "commit_sha": commit.commit_sha, "hybrid": hybrid_used, "squad": squad_used},
    )
    return HubBuildRoleResult(
        ok=True, role=role, directive_id=directive_id,
        result_kind="code_approval",
        artifact_key="code_intro_md",
        artifact_md=intro_md,
        project_uuid=project_uuid,
        project_name=project_name,
        extra={
            "files_written": written,
            "run_block": run_block,
            "file_tree": files,
            "hybrid": hybrid_used,
            "squad": squad_used,
        },
    )


async def _run_devops_install(project: dict[str, Any]) -> HubBuildRoleResult:
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    directive_id = f"dir_{uuid4().hex[:12]}"
    role = "devops"
    project_uuid = project["project_uuid"]
    project_name = project["name"]
    role_log(project_uuid, role, "DevOps install started")
    prior = project.get("metadata") or {}
    workspace = resolve_code_dir(project_uuid, prior)
    run_block = prior.get("code_run_block") or ""
    install, start = _classify_run_block(run_block)

    log_chunks: list[str] = []
    all_ok = True
    if workspace.exists():
        for cmd in install:
            log_chunks.append(f"$ {cmd}")
            role_log(project_uuid, role, f"$ {cmd}")
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=str(workspace),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    stdout, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=_DEVOPS_SHELL_TIMEOUT_SECS,
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    log_chunks.append(f"[timeout after {_DEVOPS_SHELL_TIMEOUT_SECS}s]")
                    all_ok = False
                    break
                output = (stdout or b"").decode("utf-8", errors="replace")
                tail = output if len(output) <= 4000 else "…[truncated]…\n" + output[-4000:]
                log_chunks.append(tail.rstrip())
                log_chunks.append(f"[exit={proc.returncode}]")
                if proc.returncode != 0:
                    role_log(project_uuid, role, f"Command failed (exit {proc.returncode})", level="error")
                    all_ok = False
                    break
                role_log(project_uuid, role, f"Command ok (exit 0)", level="success")
            except Exception as exc:  # noqa: BLE001
                log_chunks.append(f"[devops error: {type(exc).__name__}: {exc}]")
                all_ok = False
                break

    install_log = "\n".join(log_chunks) if log_chunks else "_(no install commands detected)_"
    role_log(
        project_uuid,
        role,
        "Install finished — ok" if all_ok else "Install finished — failed",
        level="success" if all_ok else "error",
    )
    _persist_metadata(project_uuid, {
        "devops_install_log": install_log,
        "devops_install_ok": bool(all_ok),
        "devops_start_cmds": start,
    })
    return HubBuildRoleResult(
        ok=True, role=role, directive_id=directive_id,
        result_kind="devops_approval",
        artifact_key="devops_install_log",
        artifact_md=install_log,
        project_uuid=project_uuid,
        project_name=project_name,
        extra={"install_ok": bool(all_ok), "start_cmds": start},
    )


def run_build_hub_role(
    *,
    project_id: str,
    role: str,
    directive: str,
    actor: str = "orchestrator",
    extra_context: str = "",
) -> HubBuildRoleResult:
    """Sync entry for MCP ``build_dispatch``."""
    _ = actor
    project = _load_project(project_id)
    upper = directive.upper()

    if role == "engineer" or "PRODUCE_CODE" in upper or "REMEDIATE" in upper:
        return asyncio.run(_run_engineer(
            project,
            extra_context=extra_context,
            directive=directive,
            actor=actor,
        ))

    if role in ("devops", "devops_release") or "INSTALL" in upper or "DEPLOY" in upper or "OPERATE" in upper:
        if "DEPLOY" in upper or role == "devops_release" or "OPERATE" in upper:
            from devops.runtime.hub_deploy_runner import run_devops_hub_role  # noqa: PLC0415

            dep = run_devops_hub_role(
                project_id=project["project_uuid"],
                role=role,
                directive=directive,
                actor=actor,
            )
            return HubBuildRoleResult(
                ok=dep.ok,
                role=dep.role,
                directive_id=dep.directive_id,
                result_kind="deploy",
                error_class=dep.error_class,
                error_message=dep.error_message,
                project_uuid=project["project_uuid"],
                project_name=project["name"],
                extra=dep.extra,
            )
        return asyncio.run(_run_devops_install(project))

    if role == "qa" and ("EXECUTE" in upper or "RUN_TESTS" in upper):
        try:
            from verify.runtime.qa_execution_runner import run_qa_execution  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            return HubBuildRoleResult(
                ok=False,
                role=role,
                directive_id=f"dir_{uuid4().hex[:12]}",
                result_kind="qa_execution",
                error_class="qa_execution_runtime_unavailable",
                error_message=f"verify.runtime.qa_execution_runner import failed: {exc}",
                project_uuid=project["project_uuid"],
                project_name=project["name"],
            )
        result = run_qa_execution(project)
        return HubBuildRoleResult(
            ok=result.ok,
            role=role,
            directive_id=result.directive_id,
            result_kind="qa_execution",
            artifact_key="qa_execution_md",
            artifact_md=result.execution_md,
            error_class=result.error_class,
            error_message=result.error_message,
            project_uuid=project["project_uuid"],
            project_name=project["name"],
            extra={
                "all_passed": result.all_passed,
                "commands_run": result.commands_run,
                "commands_failed": result.commands_failed,
                "criteria_total": result.criteria_total,
            },
        )

    if role in ("security_engineer", "auditor") or "CODE_REVIEW" in upper:
        # V3 #12 Cite-or-Refuse contract — routes through the new
        # auditor runtime (D2 gap-analysis slate #1, 2026-05-30).
        # Evidence pointers come from extra_context if the caller has
        # already pulled audit_hash / kg_node references.
        try:
            from verify.runtime.auditor_runner import run_auditor  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            return HubBuildRoleResult(
                ok=False,
                role=role,
                directive_id=f"dir_{uuid4().hex[:12]}",
                result_kind="code_review",
                error_class="auditor_runtime_unavailable",
                error_message=f"verify.runtime.auditor_runner import failed: {exc}",
                project_uuid=project["project_uuid"],
                project_name=project["name"],
            )
        directive_id = f"dir_{uuid4().hex[:12]}"
        artifact_subject = (
            project.get("metadata", {}).get("last_commit_sha", "")
            or project.get("metadata", {}).get("build_brief", {}).get("brief_id", "")
            or directive
        )
        envelope = run_auditor(
            project=project,
            role=role,
            artifact_subject=str(artifact_subject),
            evidence_pointers=(),  # extra_context-based wiring lands in slate #2
        )
        ok = envelope.status == "ok"
        result_kind = "code_review"
        artifact_md = ""
        if isinstance(envelope.data, dict):
            artifact_md = str(envelope.data.get("findings_markdown") or "")
        return HubBuildRoleResult(
            ok=ok,
            role=role,
            directive_id=directive_id,
            result_kind=result_kind,
            artifact_key="audit_md",
            artifact_md=artifact_md,
            error_class=None if ok else (
                envelope.error.code if envelope.error else "auditor_refused"
            ),
            error_message=(
                envelope.summary
                if not ok
                else envelope.summary
            ),
            project_uuid=project["project_uuid"],
            project_name=project["name"],
            extra={
                "envelope_status": envelope.status,
                "citation_count": len(envelope.citation),
                "summary": envelope.summary,
                "next_actions": list(envelope.next_actions),
            },
        )

    return HubBuildRoleResult(
        ok=False,
        role=role,
        directive_id=f"dir_{uuid4().hex[:12]}",
        error_class="unsupported_role",
        error_message=f"build hub runner does not support role={role!r} directive={directive!r}",
        project_uuid=project["project_uuid"],
        project_name=project["name"],
    )


__all__ = ["HubBuildRoleResult", "run_build_hub_role"]

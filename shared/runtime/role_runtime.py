"""Per-role directive/worker runtime under ``.spine/work/`` (SPINE_MASTER §4 P0).

Each orchestrator dispatch gets a durable directive workspace:
``.spine/work/<project_uuid>/directives/<directive_id>/`` with ``directive.md``,
``report.md``, and ``status.json``. Replaces deleted Wave-6 bash daemons with
a minimal Python file-bus.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger("spine.runtime.role_runtime")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class DirectiveHandle:
    directive_id: str
    project_uuid: str
    role: str
    directive: str
    workspace: Path


def _directives_root() -> Path:
    return _REPO_ROOT / ".spine" / "work"


def _validate_id(value: str, label: str) -> str:
    if not _RUN_ID_RE.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def begin_directive(
    project_uuid: str,
    role: str,
    directive: str,
    actor: str = "orchestrator",
    *,
    directive_id: str | None = None,
) -> DirectiveHandle:
    """Create directive workspace and write initial status."""
    _validate_id(project_uuid, "project_uuid")
    did = directive_id or f"dir_{uuid4().hex[:12]}"
    _validate_id(did, "directive_id")

    ws = (_directives_root() / project_uuid / "directives" / did).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    meta = {
        "directive_id": did,
        "project_uuid": project_uuid,
        "role": role,
        "directive": directive,
        "actor": actor,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (ws / "status.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (ws / "directive.md").write_text(
        f"# Directive {did}\n\n"
        f"- **Role:** {role}\n"
        f"- **Directive:** {directive}\n"
        f"- **Actor:** {actor}\n",
        encoding="utf-8",
    )
    logger.info("role_directive_begin", extra={"directive_id": did, "role": role})
    return DirectiveHandle(
        directive_id=did,
        project_uuid=project_uuid,
        role=role,
        directive=directive,
        workspace=ws,
    )


def append_directive_context(handle: DirectiveHandle, markdown: str) -> None:
    """Append extra context (e.g. KG retrieve block) to directive.md."""
    path = handle.workspace / "directive.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + markdown.strip() + "\n", encoding="utf-8")


def complete_directive(
    handle: DirectiveHandle,
    report_md: str,
    *,
    ok: bool = True,
    extra: dict[str, Any] | None = None,
) -> None:
    """Mark directive done and write report.

    Also records an :mod:`learning.instinct` observation on successful
    completion so Smart Spine (#27, B3) accumulates a per-project corpus
    of "this role did this kind of thing successfully" patterns. Failures
    don't generate instincts — corroboration is for successful behavior.
    Instinct write is fail-soft: any error swallowed; the directive
    completion is the source of truth.
    """
    status_path = handle.workspace / "status.json"
    meta = json.loads(status_path.read_text(encoding="utf-8"))
    meta["status"] = "done" if ok else "failed"
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    if extra:
        meta["extra"] = extra
    status_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (handle.workspace / "report.md").write_text(report_md.strip() + "\n", encoding="utf-8")
    logger.info(
        "role_directive_complete",
        extra={"directive_id": handle.directive_id, "ok": ok},
    )
    if ok:
        _record_directive_instinct(handle)


def _record_directive_instinct(handle: DirectiveHandle) -> None:
    """Fail-soft instinct observation. Never raises."""
    try:
        from learning.instinct import Instinct, InstinctRecord, InstinctStore

        trigger = _summarise_directive_intent(handle.directive)
        pattern = f"{handle.role} completed directive"
        store = InstinctStore(
            project_id=handle.project_uuid,
            run_id=handle.directive_id,
        )
        store.record(
            InstinctRecord(
                instinct=Instinct(
                    pattern=pattern,
                    trigger=trigger,
                    rationale=(
                        f"role={handle.role} successfully completed a "
                        f"directive matching this trigger"
                    ),
                ),
                project_id=handle.project_uuid,
                run_id=handle.directive_id,
                actor=handle.role,
            )
        )
    except Exception:  # noqa: BLE001 — fail-soft per #27
        logger.warning(
            "instinct_record_failed",
            extra={"directive_id": handle.directive_id},
        )


def _summarise_directive_intent(directive: str) -> str:
    """Compact first-line summary used as the instinct trigger."""
    cleaned = (directive or "").strip()
    if not cleaned:
        return "directive: <empty>"
    first = cleaned.splitlines()[0].strip()
    if len(first) > 200:
        first = first[:200].rstrip() + "…"
    return f"directive: {first}"


def fail_directive(handle: DirectiveHandle, error: str) -> None:
    """Mark directive failed with error report."""
    complete_directive(
        handle,
        f"# Failed\n\n{error.strip()}\n",
        ok=False,
        extra={"error": error[:500]},
    )


__all__ = [
    "DirectiveHandle",
    "append_directive_context",
    "begin_directive",
    "complete_directive",
    "fail_directive",
]

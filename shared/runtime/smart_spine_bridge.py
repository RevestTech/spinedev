"""Smart Spine bridge — record role outcomes into learning tiers (#27).

Best-effort hook from orchestrator dispatch success. Never raises into
the golden path; failures are logged at debug level.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("spine.runtime.smart_spine")


def smart_spine_enabled() -> bool:
    return os.environ.get("SPINE_SMART_SPINE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def record_role_outcome(
    *,
    project_id: str,
    role: str,
    directive: str,
    artifact_key: str = "",
    artifact_preview: str = "",
    actor: str = "orchestrator",
    hub_id: str | None = None,
) -> None:
    """Promote a concise lesson from a successful role dispatch."""
    if not smart_spine_enabled():
        return
    preview = (artifact_preview or "").strip()
    if len(preview) > 400:
        preview = preview[:400] + "…"
    lesson = (
        f"Role **{role}** completed directive `{directive}` "
        f"for project `{project_id}`."
    )
    if artifact_key:
        lesson += f" Artifact: `{artifact_key}`."
    if preview:
        lesson += f"\n\n{preview}"

    try:
        from learning.contribute import LessonPayload, contribute_lesson  # noqa: PLC0415
        from learning.scope import ScopeContext  # noqa: PLC0415

        ctx = ScopeContext(
            hub_id=hub_id or os.environ.get("SPINE_HUB_ID", "local"),
            project_id=project_id,
        )
        contribute_lesson(LessonPayload(lesson_text=lesson), ctx)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "smart_spine_record_skipped",
            extra={"project_id": project_id, "role": role, "error": str(exc)},
        )


__all__ = ["record_role_outcome", "smart_spine_enabled"]

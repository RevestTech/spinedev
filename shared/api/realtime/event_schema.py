"""Wire shape for realtime project-scoped events.

Every channel that publishes into :mod:`shared.api.realtime.event_publisher`
emits a :class:`ProjectEvent`. The SSE endpoint serializes the event with
``model_dump_json`` and sends it as an ``event: <type>`` + ``data: <json>``
SSE frame; the SPA's ``projectEvents`` store parses it back via the same
schema.

The schema is deliberately permissive in ``payload``: each event type
owns its own payload shape, validated at the publish site, not here.
That keeps the wire frozen even when downstream channels evolve.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


ProjectEventType = Literal[
    "ledger_append",
    "directive_complete",
    "instinct_recorded",
    "auditor_verdict",
    "auditor_refusal",
    "audit_event",
    "charter_eval_run",
    "operate_plane_status",
    "envelope_warning",
]
"""Closed set of event types the SPA knows how to render.

  * ``ledger_append``      — every successful decision-ledger write
                             (V3 #12a, B1). Carries the verdict +
                             reasons + content_hash.
  * ``directive_complete`` — successful role directive completion
                             from ``role_runtime.complete_directive``.
  * ``instinct_recorded``  — Smart Spine instinct write (#27, B3).
  * ``auditor_verdict``    — auditor verdict envelope; non-zero
                             citation count required (V3 #12).
  * ``auditor_refusal``    — auditor refusal envelope; carries the
                             refusal reason.
  * ``audit_event``        — ``spine_audit.event`` row written; the
                             chain content_hash is the canonical id.
  * ``charter_eval_run``   — pass@k regression run (B6 / V3 #7a).
  * ``operate_plane_status`` — one per control plane during
                               ``run_operate`` plus a final rollup.
  * ``envelope_warning``   — V3 #30a observation convention warning
                             (e.g. ``missing_summary``); informational
                             for the live feed.
"""


PROJECT_EVENT_TYPES: tuple[str, ...] = (
    "ledger_append",
    "directive_complete",
    "instinct_recorded",
    "auditor_verdict",
    "auditor_refusal",
    "audit_event",
    "charter_eval_run",
    "operate_plane_status",
    "envelope_warning",
)
"""Tuple mirror of :data:`ProjectEventType` for runtime iteration."""


def _utcnow() -> datetime:
    """Timezone-aware UTC ``datetime`` factory."""
    return datetime.now(timezone.utc)


class ProjectEvent(BaseModel):
    """Single realtime event scoped to one project.

    Fields:
        event_id: server-generated UUID; the SPA uses it to dedupe
            on reconnect.
        event_type: closed-set type discriminator; SPA renders by
            colour + icon keyed on this.
        project_id: the project_uuid the event belongs to. SSE
            subscribers filter by this.
        occurred_at: wall-clock UTC at publish time.
        actor: role / subsystem / user that produced the event.
        payload: type-specific body. Permissive — validated by the
            publishing channel, not by this schema.
        verdict: optional verdict string (allowed | denied | refused
            | passed | failed | warning). Pre-extracted so the SPA
            can colour the row without parsing ``payload``.
        citation_count: optional integer; pre-extracted for the same
            reason. Defaults to 0.
        summary: optional one-line, role-readable summary. Used as
            the SPA timeline row title.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: ProjectEventType
    project_id: str = Field(..., min_length=1)
    occurred_at: datetime = Field(default_factory=_utcnow)
    actor: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    verdict: str | None = Field(default=None)
    citation_count: int = Field(default=0, ge=0)
    summary: str | None = Field(default=None)


__all__ = [
    "PROJECT_EVENT_TYPES",
    "ProjectEvent",
    "ProjectEventType",
]

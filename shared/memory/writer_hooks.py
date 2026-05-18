"""Memory writer hooks — Wave 1 substrate wiring (per V3 #27).

Wires the 7 R4 trigger points (audit events) into ``spine_memory.lesson``
writes via the ``shared.audit.audit_record`` persistence path.

Trigger points (must stay 1:1 with V3_BUILD_SEQUENCE Wave 1):

    1. verify.passed          — verify_audit returned pass_fail='pass'
    2. verify.failed          — verify_audit returned pass_fail='fail'
    3. approval.granted       — approval_granted action persisted
    4. approval.rejected      — approval_rejected action persisted
    5. phase.advance.success  — phase_advanced action persisted
    6. build.completed        — build_completed action persisted
    7. incident.resolved      — incident_resolved action persisted

Wiring contract
---------------

* ``register_hook(event_key, extractor)`` adds an extractor. An extractor
  takes a serialised audit_record dict and returns a ``LessonDraft`` or
  ``None`` (skip).
* ``dispatch(record_dict)`` is called from inside
  ``shared.audit.audit_record.write_via_psql`` *after* the row has been
  committed; each matching hook fires once.
* ``flush_pending(...)`` writes pending drafts as
  ``spine_memory.lesson`` rows using the same ``psql`` subprocess pattern
  the rest of the package uses. Tests can swap the writer for in-memory.

The dispatch path is intentionally side-effect-isolated: any hook that
raises is logged + swallowed so writer hooks can never break the audit
write path (per V3 #27 risk: "must not block commits").
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"

# Canonical 7 trigger point keys. Anything else is invalid.
EVENT_KEYS: tuple[str, ...] = (
    "verify.passed",
    "verify.failed",
    "approval.granted",
    "approval.rejected",
    "phase.advance.success",
    "build.completed",
    "incident.resolved",
)

# Stable role bucket used when emitting hook-produced lessons. The
# extractor may override per-record but this is the default for the
# 7 trigger points.
DEFAULT_HOOK_ROLE = "spine"


# ─── Models ──────────────────────────────────────────────────────────


@dataclass
class LessonDraft:
    """One pending lesson row produced by a writer hook.

    Mirrors the columns of ``spine_memory.lesson`` (V20) that hook output
    is allowed to populate. ``embedding`` is intentionally NOT here
    (lazy embed on first recall, per STORY-4.2.2).
    """
    role: str
    lesson_text: str
    source_path: str
    tags: list[str] = field(default_factory=list)
    scope: str = "project"  # 'project' | 'cross_project'
    project_id: Optional[int] = None
    line_in_source: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def text_hash(self) -> str:
        return hashlib.sha256(self.lesson_text.encode("utf-8")).hexdigest()


HookExtractor = Callable[[dict[str, Any]], Optional[LessonDraft]]
"""Signature for a writer-hook extractor."""


# ─── Registry ────────────────────────────────────────────────────────


_REGISTRY: dict[str, list[HookExtractor]] = {k: [] for k in EVENT_KEYS}
_DRAFT_QUEUE: "queue.Queue[LessonDraft]" = queue.Queue()
_REGISTERED_DEFAULTS = False
_REGISTRY_LOCK = threading.Lock()


def register_hook(event_key: str, extractor: HookExtractor) -> None:
    """Register an extractor for one of the 7 canonical trigger points.

    Multiple extractors per key are allowed; they all fire on dispatch.
    """
    if event_key not in EVENT_KEYS:
        raise ValueError(
            f"event_key {event_key!r} not in canonical set: {EVENT_KEYS}"
        )
    with _REGISTRY_LOCK:
        _REGISTRY[event_key].append(extractor)


def clear_hooks() -> None:
    """Reset registered extractors. Test-only helper."""
    global _REGISTERED_DEFAULTS
    with _REGISTRY_LOCK:
        for k in EVENT_KEYS:
            _REGISTRY[k] = []
        _REGISTERED_DEFAULTS = False
    # Drain pending drafts so tests start clean.
    while not _DRAFT_QUEUE.empty():
        try:
            _DRAFT_QUEUE.get_nowait()
        except queue.Empty:
            break


def registered_event_keys() -> tuple[str, ...]:
    """Return the canonical event keys (introspection)."""
    return EVENT_KEYS


def pending_drafts() -> list[LessonDraft]:
    """Snapshot pending drafts (non-destructive). Tests use this."""
    items: list[LessonDraft] = []
    snapshot: list[LessonDraft] = []
    while not _DRAFT_QUEUE.empty():
        try:
            d = _DRAFT_QUEUE.get_nowait()
        except queue.Empty:
            break
        snapshot.append(d)
        items.append(d)
    # Put them back in original order.
    for d in snapshot:
        _DRAFT_QUEUE.put(d)
    return items


# ─── Dispatch ────────────────────────────────────────────────────────


def _classify(record: dict[str, Any]) -> Optional[str]:
    """Map an audit_record dict to one of the 7 canonical event keys.

    Returns ``None`` if the record is not one of the 7 trigger points.
    Classification is conservative: action + pass_fail metadata + subsystem.
    """
    action = (record.get("action") or "").lower()
    meta = record.get("metadata") or {}
    if action == "verify_audit":
        pf = (meta.get("pass_fail") or "").lower()
        if pf == "pass":
            return "verify.passed"
        if pf == "fail":
            return "verify.failed"
        return None  # 'needs_user_review' → no hook
    if action == "approval_granted":
        return "approval.granted"
    if action == "approval_rejected":
        return "approval.rejected"
    if action == "phase_advanced":
        # Only success path — failed phase advances do not write lessons.
        if meta.get("status", "success") == "success":
            return "phase.advance.success"
        return None
    if action == "build_completed":
        return "build.completed"
    if action == "incident_resolved":
        return "incident.resolved"
    return None


def dispatch(record: dict[str, Any]) -> list[LessonDraft]:
    """Fire any registered extractors that match the record's event key.

    Called from ``shared.audit.audit_record.write_via_psql`` after the row
    is persisted. Returns the list of drafts produced for the call (also
    enqueued for downstream batch indexing).

    Hard contract: this function MUST NOT raise — caller hot-path must
    not be broken by a buggy extractor.
    """
    try:
        _ensure_defaults_registered()
        event_key = _classify(record)
        if event_key is None:
            return []
        produced: list[LessonDraft] = []
        with _REGISTRY_LOCK:
            extractors = list(_REGISTRY.get(event_key) or [])
        for fn in extractors:
            try:
                draft = fn(record)
            except Exception:
                logger.exception(
                    "writer_hooks: extractor raised on %s; skipping",
                    event_key,
                )
                continue
            if draft is None:
                continue
            produced.append(draft)
            _DRAFT_QUEUE.put(draft)
        return produced
    except Exception:  # pragma: no cover — last-resort isolation
        logger.exception("writer_hooks: dispatch failed; isolated")
        return []


# ─── Default extractors (7) ──────────────────────────────────────────


def _short(s: Optional[str], n: int = 80) -> str:
    """Truncate and squash whitespace for a one-line lesson."""
    if not s:
        return ""
    one = " ".join(str(s).split())
    return one if len(one) <= n else one[: n - 1] + "…"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id(record: dict[str, Any]) -> Optional[int]:
    pid = record.get("project_id")
    try:
        return int(pid) if pid is not None else None
    except (TypeError, ValueError):
        return None


def _extractor_verify_passed(record: dict[str, Any]) -> Optional[LessonDraft]:
    meta = record.get("metadata") or {}
    band = meta.get("calibration_band") or "unknown"
    crit = meta.get("critical_count", 0)
    high = meta.get("high_count", 0)
    rationale = _short(record.get("rationale"))
    text = (
        f"verify pass on artifact {meta.get('artifact_uuid', '?')[:8]} "
        f"(band={band}, crit={crit}, high={high})"
    )
    if rationale:
        text += f" — {rationale}"
    return LessonDraft(
        role=record.get("actor") or DEFAULT_HOOK_ROLE,
        lesson_text=text,
        source_path=f"audit://verify.passed/{record.get('event_uuid', _ts())}",
        tags=["verify", "passed", "cite-tier"],
        project_id=_project_id(record),
        metadata={"event_key": "verify.passed", "cite_tier": band},
    )


def _extractor_verify_failed(record: dict[str, Any]) -> Optional[LessonDraft]:
    meta = record.get("metadata") or {}
    reason = (
        meta.get("error_code")
        or meta.get("reason_class")
        or meta.get("pass_fail")
        or "unknown"
    )
    crit = meta.get("critical_count", 0)
    high = meta.get("high_count", 0)
    text = (
        f"verify FAIL on artifact {meta.get('artifact_uuid', '?')[:8]} "
        f"(reason={reason}, crit={crit}, high={high})"
    )
    return LessonDraft(
        role=record.get("actor") or DEFAULT_HOOK_ROLE,
        lesson_text=text,
        source_path=f"audit://verify.failed/{record.get('event_uuid', _ts())}",
        tags=["verify", "failed", str(reason)],
        project_id=_project_id(record),
        metadata={"event_key": "verify.failed", "reason_class": reason},
    )


def _extractor_approval_granted(record: dict[str, Any]) -> Optional[LessonDraft]:
    rationale = _short(record.get("rationale")) or "(no rationale)"
    subj = record.get("subject_id") or "?"
    text = f"approval GRANTED on {subj}: {rationale}"
    return LessonDraft(
        role=record.get("actor") or DEFAULT_HOOK_ROLE,
        lesson_text=text,
        source_path=f"audit://approval.granted/{record.get('event_uuid', _ts())}",
        tags=["approval", "granted"],
        project_id=_project_id(record),
        metadata={"event_key": "approval.granted", "rationale": rationale},
    )


def _extractor_approval_rejected(record: dict[str, Any]) -> Optional[LessonDraft]:
    rationale = _short(record.get("rationale")) or "(no reason)"
    subj = record.get("subject_id") or "?"
    text = f"approval REJECTED on {subj}: {rationale}"
    return LessonDraft(
        role=record.get("actor") or DEFAULT_HOOK_ROLE,
        lesson_text=text,
        source_path=f"audit://approval.rejected/{record.get('event_uuid', _ts())}",
        tags=["approval", "rejected"],
        project_id=_project_id(record),
        metadata={"event_key": "approval.rejected", "reason": rationale},
    )


def _extractor_phase_advance(record: dict[str, Any]) -> Optional[LessonDraft]:
    meta = record.get("metadata") or {}
    from_p = meta.get("from_phase") or "?"
    to_p = meta.get("to_phase") or "?"
    metrics = meta.get("metrics") or {}
    metric_blurb = ", ".join(f"{k}={v}" for k, v in sorted(metrics.items())) or "n/a"
    text = f"phase {from_p} → {to_p} advanced (metrics: {metric_blurb})"
    return LessonDraft(
        role="orchestrator",
        lesson_text=text,
        source_path=f"audit://phase.advance.success/{record.get('event_uuid', _ts())}",
        tags=["phase", "advance", str(to_p)],
        project_id=_project_id(record),
        metadata={
            "event_key": "phase.advance.success",
            "from": from_p,
            "to": to_p,
            "metrics": metrics,
        },
    )


def _extractor_build_completed(record: dict[str, Any]) -> Optional[LessonDraft]:
    meta = record.get("metadata") or {}
    quality = meta.get("quality_signals") or {}
    sig_blurb = ", ".join(f"{k}={v}" for k, v in sorted(quality.items())) or "n/a"
    artifact = meta.get("artifact_uuid") or record.get("subject_id") or "?"
    text = f"build completed on {str(artifact)[:8]} (quality: {sig_blurb})"
    return LessonDraft(
        role=record.get("actor") or "engineer",
        lesson_text=text,
        source_path=f"audit://build.completed/{record.get('event_uuid', _ts())}",
        tags=["build", "completed"],
        project_id=_project_id(record),
        metadata={"event_key": "build.completed", "quality_signals": quality},
    )


def _extractor_incident_resolved(record: dict[str, Any]) -> Optional[LessonDraft]:
    meta = record.get("metadata") or {}
    root_cause = _short(meta.get("root_cause")) or "(unknown root cause)"
    severity = meta.get("severity") or "unspecified"
    subj = record.get("subject_id") or "?"
    text = (
        f"incident {subj} resolved (severity={severity}); root cause: {root_cause}"
    )
    return LessonDraft(
        role="operator",
        lesson_text=text,
        source_path=f"audit://incident.resolved/{record.get('event_uuid', _ts())}",
        tags=["incident", "resolved", str(severity)],
        project_id=_project_id(record),
        metadata={
            "event_key": "incident.resolved",
            "root_cause": root_cause,
            "severity": severity,
        },
    )


_DEFAULT_EXTRACTORS: dict[str, HookExtractor] = {
    "verify.passed": _extractor_verify_passed,
    "verify.failed": _extractor_verify_failed,
    "approval.granted": _extractor_approval_granted,
    "approval.rejected": _extractor_approval_rejected,
    "phase.advance.success": _extractor_phase_advance,
    "build.completed": _extractor_build_completed,
    "incident.resolved": _extractor_incident_resolved,
}


def _register_default_hooks() -> None:
    """Idempotent install of the 7 canonical extractors."""
    global _REGISTERED_DEFAULTS
    with _REGISTRY_LOCK:
        if _REGISTERED_DEFAULTS:
            return
        for key, fn in _DEFAULT_EXTRACTORS.items():
            _REGISTRY[key].append(fn)
        _REGISTERED_DEFAULTS = True


def _ensure_defaults_registered() -> None:
    """Lazily register defaults the first time dispatch fires."""
    if not _REGISTERED_DEFAULTS:
        _register_default_hooks()


# ─── Persistence ─────────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _pg_text_array(items: list[str]) -> str:
    return (
        "ARRAY[" + ",".join(_q(s) for s in items) + "]::text[]"
        if items
        else "ARRAY[]::text[]"
    )


def _psql(sql: str, db_url: str) -> str:
    """Subprocess psql writer; mirrors shared/memory/lesson_indexer._psql."""
    r = subprocess.run(
        [
            "psql", db_url, "-At", "-F", "\x1f",
            "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def flush_pending(
    *,
    db_url: Optional[str] = None,
    writer: Optional[Callable[[LessonDraft, str], None]] = None,
) -> int:
    """Drain queued drafts into ``spine_memory.lesson``.

    ``writer`` lets tests inject a fake. Returns rows written.
    """
    url = db_url or os.environ.get("SPINE_DB_URL") or os.environ.get(
        "DATABASE_URL"
    ) or DEFAULT_DB_URL
    written = 0
    while True:
        try:
            draft = _DRAFT_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            if writer is not None:
                writer(draft, url)
            else:
                _default_writer(draft, url)
            written += 1
        except Exception:
            logger.exception(
                "writer_hooks: flush failed for draft %s; dropped",
                draft.source_path,
            )
    return written


def _default_writer(draft: LessonDraft, db_url: str) -> None:
    """Insert one draft into ``spine_memory.lesson``."""
    pid_sql = "NULL" if draft.project_id is None else str(int(draft.project_id))
    line_sql = (
        "NULL" if draft.line_in_source is None else str(int(draft.line_in_source))
    )
    sql = (
        "INSERT INTO spine_memory.lesson (role, scope, project_id, lesson_text, "
        "source_path, line_in_source, tags, text_hash) VALUES ("
        f"{_q(draft.role)}, {_q(draft.scope)}, {pid_sql}, {_q(draft.lesson_text)}, "
        f"{_q(draft.source_path)}, {line_sql}, {_pg_text_array(draft.tags)}, "
        f"{_q(draft.text_hash())});"
    )
    _psql(sql, db_url)


__all__ = [
    "EVENT_KEYS",
    "HookExtractor",
    "LessonDraft",
    "clear_hooks",
    "dispatch",
    "flush_pending",
    "pending_drafts",
    "register_hook",
    "registered_event_keys",
]

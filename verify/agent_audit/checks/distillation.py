"""L04 — audit-ledger distillation / summary integrity check.

Distillation failure mode in Spine: summary blobs (lesson rollups,
audit-rollup metadata) re-entering the hash-chained ledger as if they
were primary evidence. That breaks citation integrity (#12) because a
verify-class consumer can't tell a primary event from a derived one.

``signals['audit_summary']`` is the shape:

    {
        "events_in_window":   int,
        "rollup_events":      int,
        "rollups":            list[dict],  # each may carry source_audit_record_id
    }

Missing signal -> ``instrumentation_pending``. Rollup ratio > 25% ->
``warning``. Any rollup missing ``source_audit_record_id`` ->
``regressed``. Missing ``shared/audit/exporter.py`` or
``shared/audit/audit_record.py`` -> ``regressed`` (critical).
"""
from __future__ import annotations

from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding


_LAYER = "L04_distillation"
_RATIO_THRESHOLD = 0.25
_REQUIRED_FILES: tuple[tuple[str, ...], ...] = (
    ("shared", "audit", "audit_record.py"),
    ("shared", "audit", "exporter.py"),
)


def check_distillation_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L04 — audit-ledger distillation integrity."""
    missing_files = [
        str(Path(*parts)) for parts in _REQUIRED_FILES
        if not (repo_root / Path(*parts)).is_file()
    ]
    if missing_files:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"{len(missing_files)} audit-ledger module(s) missing — "
                "distillation chain cannot be validated"
            ),
            severity="critical",
            evidence=tuple(missing_files),
        )

    summary = signals.get("audit_summary")
    if summary is None:
        return LayerFinding(
            layer=_LAYER,
            status="instrumentation_pending",
            summary=(
                "no audit_summary signal supplied (pipe in rollup/event "
                "counts from shared.audit aggregation)"
            ),
            severity="low",
        )

    if not isinstance(summary, dict):
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"audit_summary signal is not a dict "
                f"(got {type(summary).__name__})"
            ),
            severity="high",
        )

    rollups = summary.get("rollups") or ()
    unprovenanced = [
        idx for idx, rollup in enumerate(rollups)
        if not isinstance(rollup, dict)
        or not rollup.get("source_audit_record_id")
    ]
    if unprovenanced:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"{len(unprovenanced)} rollup event(s) lack "
                "source_audit_record_id — unprovenanced summary in chain"
            ),
            severity="high",
            evidence=tuple(f"rollup[{i}]" for i in unprovenanced),
            next_actions=(
                "stamp every rollup event with the originating "
                "source_audit_record_id before re-chaining",
            ),
        )

    events = int(summary.get("events_in_window", 0) or 0)
    rollup_count = int(summary.get("rollup_events", 0) or 0)
    if events <= 0:
        return LayerFinding(
            layer=_LAYER,
            status="instrumentation_pending",
            summary="audit_summary events_in_window is 0",
            severity="low",
        )

    ratio = rollup_count / events
    if ratio > _RATIO_THRESHOLD:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                f"rollup ratio {ratio:.0%} ({rollup_count}/{events}) "
                f"exceeds {_RATIO_THRESHOLD:.0%} — summaries dominating "
                "the chain"
            ),
            severity="medium",
            evidence=(
                f"rollup_events={rollup_count}",
                f"events_in_window={events}",
            ),
            next_actions=(
                "investigate whether a rollup writer is over-emitting or "
                "primary events have dropped off",
            ),
        )

    return LayerFinding(
        layer=_LAYER,
        status="clean",
        summary=(
            f"rollup ratio {ratio:.0%} within bound; "
            "all rollups carry source_audit_record_id"
        ),
    )


__all__ = ["check_distillation_layer"]

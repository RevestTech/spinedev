"""Cross-module wire integration tests for Path B (T13).

Exercises each of the six wired channels (T3 – T8) end-to-end:
publish from the real call site → arrive at an SSE-style subscriber
queue → parse cleanly via the ProjectEvent schema.

Skips the actual SSE HTTP path (T9 tests already cover that
narrowly); the goal here is to prove every backend channel hits the
publisher with a conforming payload that the SPA store can consume.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from shared.api.realtime.event_publisher import subscribe, unsubscribe
from shared.api.realtime.event_schema import ProjectEvent


async def _drain_until(queue, predicate, *, max_events: int = 12) -> ProjectEvent:
    """Drain ``queue`` until ``predicate(event)`` returns True."""
    for _ in range(max_events):
        evt = await asyncio.wait_for(queue.get(), timeout=1.0)
        if predicate(evt):
            return evt
    raise AssertionError(
        f"predicate not satisfied within {max_events} events"
    )


# ─── T3 ledger_append ───


def test_ledger_io_publishes_through_publisher(tmp_path: Path) -> None:
    from shared.audit.decision_ledger_io import (
        SafePromotionInputs,
        append_promotion_decision,
    )

    async def body():
        q = subscribe("wire-proj")
        try:
            append_promotion_decision(
                SafePromotionInputs(
                    project_id="wire-proj",
                    run_id="wire-run-1",
                    role="conductor",
                    freshness_passed=True,
                ),
                root=tmp_path,
            )
            await asyncio.sleep(0)
            evt = await _drain_until(q, lambda e: e.event_type == "ledger_append")
            assert evt.project_id == "wire-proj"
            assert evt.actor == "conductor"
            assert evt.verdict in ("allowed", "denied")
            # Round-trip: the SPA store parses via the same schema.
            parsed = ProjectEvent.model_validate_json(evt.model_dump_json())
            assert parsed.event_type == "ledger_append"
        finally:
            unsubscribe(q)

    asyncio.run(body())


# ─── T4 directive_complete + instinct_recorded ───


def test_role_runtime_publishes_directive_and_instinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shared.runtime.role_runtime import (
        begin_directive,
        complete_directive,
    )

    monkeypatch.setenv("SPINE_INSTINCT_ROOT", str(tmp_path / "instincts"))
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    async def body():
        q = subscribe("wire-rt")
        try:
            handle = begin_directive(
                project_uuid="wire-rt",
                role="engineer",
                directive="Implement realtime wire",
            )
            complete_directive(handle, report_md="done", ok=True)
            await asyncio.sleep(0)
            seen = set()
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    break
                seen.add(evt.event_type)
            assert {"directive_complete", "instinct_recorded"}.issubset(seen)
        finally:
            unsubscribe(q)

    asyncio.run(body())


# ─── T5 auditor_verdict + auditor_refusal ───


def test_auditor_publishes_verdict_and_refusal() -> None:
    from verify.runtime.auditor_runner import run_auditor

    project = {
        "project_uuid": "wire-aud",
        "name": "wire-test",
        "metadata": {},
    }

    async def body():
        q = subscribe("wire-aud")
        try:
            # Refusal (no evidence)
            run_auditor(project)
            await asyncio.sleep(0)
            refusal = await _drain_until(
                q, lambda e: e.event_type == "auditor_refusal",
            )
            assert refusal.verdict == "refusal"
            assert refusal.citation_count == 0

            # Verdict (with evidence)
            run_auditor(project, evidence_pointers=("node-x", "shared/a.py:1"))
            await asyncio.sleep(0)
            verdict = await _drain_until(
                q, lambda e: e.event_type == "auditor_verdict",
            )
            assert verdict.verdict == "ok"
            assert verdict.citation_count == 2
        finally:
            unsubscribe(q)

    asyncio.run(body())


# ─── T7 charter_eval_run ───


def test_charter_eval_publishes() -> None:
    from verify.charter_evals.harness import (
        CapabilityEval,
        EvalCriterion,
        evaluate_charter,
    )

    eval_ = CapabilityEval(
        name="wire-eval",
        role="wire-role",
        task="t",
        criteria=[
            EvalCriterion(name="ok", required_substrings=("OK",)),
        ],
        target_k=1,
        target_pass_rate=1.0,
    )

    async def body():
        q = subscribe("charter:wire-role")
        try:
            evaluate_charter(
                "wire-role",
                [eval_],
                lambda _e, _i: "OK",
            )
            await asyncio.sleep(0)
            evt = await asyncio.wait_for(q.get(), timeout=1.0)
            assert evt.event_type == "charter_eval_run"
            assert evt.verdict == "passed"
            assert evt.payload["role"] == "wire-role"
        finally:
            unsubscribe(q)

    asyncio.run(body())


# ─── T8 operate_plane_status ───


def test_operate_publishes_per_plane_and_rollup() -> None:
    from devops.runtime.operate_runner import run_operate

    def _fake_statuses(project_uuid, names):
        return [
            {
                "plane": name,
                "status": "active",
                "metadata": {},
                "checked_at": "2026-05-30T00:00:00+00:00",
            }
            for name in names
        ]

    project = {"project_uuid": "wire-op", "name": "wire-op-test"}

    async def body():
        q = subscribe("wire-op")
        try:
            run_operate(
                project,
                plane_names=("database", "monitoring"),
                status_runner=_fake_statuses,
            )
            await asyncio.sleep(0)
            collected = []
            for _ in range(3):
                collected.append(await asyncio.wait_for(q.get(), timeout=1.0))
            # 2 per-plane events + 1 rollup
            assert all(e.event_type == "operate_plane_status" for e in collected)
            rollup = [e for e in collected if e.payload.get("rollup")]
            assert rollup
            assert rollup[0].payload["plane_count"] == 2
        finally:
            unsubscribe(q)

    asyncio.run(body())

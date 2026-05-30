"""Tests for the auditor runtime (V3 #12 / operating-loop slate #1)."""
from __future__ import annotations

from typing import Any

import pytest

from shared.mcp.schemas import Citation
from verify.runtime.auditor_runner import (
    AuditorBriefing,
    AuditorOutcome,
    run_auditor,
)


def _project(**overrides: Any) -> dict[str, Any]:
    base = {
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "test-project",
        "metadata": {},
    }
    base.update(overrides)
    return base


# ─── Refusal envelope shape ───


def test_missing_project_uuid_yields_refusal() -> None:
    response = run_auditor(_project(project_uuid=""))
    assert response.status == "refusal"
    assert response.error is not None
    assert response.error.code == "cite_or_refuse_refused"
    assert "missing_project_uuid" in (response.data or {}).get(
        "refusal_reason", ""
    )


def test_stub_refuses_when_no_evidence_pointers() -> None:
    response = run_auditor(_project())
    assert response.status == "refusal"
    assert response.error is not None
    assert response.error.code == "cite_or_refuse_refused"
    assert response.citation == []


def test_unsupported_role_raises() -> None:
    with pytest.raises(ValueError, match="unsupported auditor role"):
        run_auditor(_project(), role="planner")


# ─── Verdict envelope shape ───


def test_evidence_pointers_yield_verdict_with_citations() -> None:
    response = run_auditor(
        _project(),
        evidence_pointers=("node-auth-design", "shared/auth.py:42"),
    )
    assert response.status == "ok"
    assert response.summary
    assert len(response.citation) == 2
    types = {c.type for c in response.citation}
    assert types == {"kg_node", "file_line"}
    assert response.artifacts
    assert response.artifacts[0].type == "run_id"
    # Audit findings markdown surfaces in data.
    assert "verdict" in (response.data or {})


def test_security_engineer_role_supported() -> None:
    response = run_auditor(
        _project(),
        role="security_engineer",
        evidence_pointers=("node-x",),
    )
    assert response.status == "ok"
    assert (response.data or {}).get("role") == "security_engineer"


# ─── Callable injection ───


def test_callable_can_force_refusal() -> None:
    def refuser(briefing: AuditorBriefing) -> AuditorOutcome:
        return AuditorOutcome(
            verdict="refused",
            summary="callable refused",
            refusal_reason="custom_reason",
        )

    response = run_auditor(
        _project(),
        evidence_pointers=("node-1",),
        audit_callable=refuser,
    )
    assert response.status == "refusal"
    assert (response.data or {}).get("refusal_reason") == "custom_reason"


def test_callable_returning_citations_passes_through() -> None:
    def passer(briefing: AuditorBriefing) -> AuditorOutcome:
        return AuditorOutcome(
            verdict="passed",
            summary="all good",
            citations=(Citation(type="audit_hash", ref="abc123"),),
            findings_markdown="# All good\n",
        )

    response = run_auditor(
        _project(),
        evidence_pointers=("node-1",),
        audit_callable=passer,
    )
    assert response.status == "ok"
    assert len(response.citation) == 1
    assert response.citation[0].type == "audit_hash"


def test_callable_exception_becomes_refusal() -> None:
    def boom(_briefing: AuditorBriefing) -> AuditorOutcome:
        raise RuntimeError("LLM down")

    response = run_auditor(
        _project(),
        evidence_pointers=("node-1",),
        audit_callable=boom,
    )
    assert response.status == "refusal"
    assert response.error is not None
    assert "callable_exception" in (response.data or {}).get("refusal_reason", "")


# ─── Verdict-without-citations is still rejected ───


async def _drain_for(q, expected_type: str, max_events: int = 4):
    """Drain the queue until an event of ``expected_type`` arrives.

    Auditor calls also publish a ledger_append event (from T3), so the
    auditor event is preceded by sibling events in the same publish
    fan-out. Tests filter to the type they care about.
    """
    import asyncio

    for _ in range(max_events):
        evt = await asyncio.wait_for(q.get(), timeout=1.0)
        if evt.event_type == expected_type:
            return evt
    raise AssertionError(
        f"never received event_type={expected_type!r} (drained {max_events})"
    )


def test_realtime_verdict_event_publishes() -> None:
    import asyncio

    from shared.api.realtime.event_publisher import subscribe, unsubscribe

    async def body():
        q = subscribe("11111111-1111-1111-1111-111111111111")
        try:
            run_auditor(
                _project(),
                evidence_pointers=("node-auth", "shared/auth.py:42"),
            )
            await asyncio.sleep(0)
            evt = await _drain_for(q, "auditor_verdict")
            assert evt.verdict == "ok"
            assert evt.citation_count == 2
        finally:
            unsubscribe(q)

    asyncio.run(body())


def test_realtime_refusal_event_publishes() -> None:
    import asyncio

    from shared.api.realtime.event_publisher import subscribe, unsubscribe

    async def body():
        q = subscribe("11111111-1111-1111-1111-111111111111")
        try:
            run_auditor(_project())  # no evidence → refusal
            await asyncio.sleep(0)
            evt = await _drain_for(q, "auditor_refusal")
            assert evt.verdict == "refusal"
            assert evt.citation_count == 0
            assert evt.payload["refusal_reason"] == "no_evidence_pointers"
        finally:
            unsubscribe(q)

    asyncio.run(body())


def test_callable_passing_without_citations_yields_refusal() -> None:
    def naked(_briefing: AuditorBriefing) -> AuditorOutcome:
        return AuditorOutcome(
            verdict="passed",
            summary="trust me",
            citations=(),  # naked verdict — V3 #12 violation
        )

    response = run_auditor(
        _project(),
        evidence_pointers=("node-1",),  # we have pointers but callable returns 0 cites
        audit_callable=naked,
    )
    assert response.status == "refusal"
    assert response.error is not None
    assert response.error.code == "cite_or_refuse_refused"
    assert (response.data or {}).get("refusal_reason") == "no_citations"

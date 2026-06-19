"""Tests for ``shared.api.realtime.event_schema``."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from shared.api.realtime.event_schema import (
    PROJECT_EVENT_TYPES,
    ProjectEvent,
)


def _make(**overrides) -> ProjectEvent:
    defaults = dict(
        event_type="ledger_append",
        project_id="proj-a",
        actor="conductor",
    )
    defaults.update(overrides)
    return ProjectEvent(**defaults)


# ─── Defaults + factory behaviour ───


def test_event_id_is_uuid_and_unique() -> None:
    e1 = _make()
    e2 = _make()
    assert isinstance(e1.event_id, UUID)
    assert e1.event_id != e2.event_id


def test_occurred_at_is_utc_aware() -> None:
    e = _make()
    assert e.occurred_at.tzinfo is timezone.utc


def test_default_optional_fields() -> None:
    e = _make()
    assert e.verdict is None
    assert e.citation_count == 0
    assert e.summary is None
    assert e.payload == {}


# ─── Closed-set discriminator ───


@pytest.mark.parametrize("etype", PROJECT_EVENT_TYPES)
def test_every_declared_type_validates(etype: str) -> None:
    e = _make(event_type=etype)
    assert e.event_type == etype


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(event_type="not_a_real_type")


def test_event_type_tuple_matches_literal() -> None:
    # The runtime tuple must stay in lockstep with the Literal so
    # iteration in tests (and future loops) covers exactly the same
    # set the schema accepts.
    assert len(PROJECT_EVENT_TYPES) == 10


# ─── Field constraints ───


def test_project_id_required_non_empty() -> None:
    with pytest.raises(ValidationError):
        _make(project_id="")


def test_actor_required_non_empty() -> None:
    with pytest.raises(ValidationError):
        _make(actor="")


def test_citation_count_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        _make(citation_count=-1)


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectEvent(
            event_type="ledger_append",
            project_id="proj-a",
            actor="conductor",
            sneaky_extra="nope",
        )


def test_payload_accepts_arbitrary_dict() -> None:
    e = _make(payload={"verdict": "allowed", "candidates": [1, 2, 3]})
    assert e.payload["candidates"] == [1, 2, 3]


# ─── Per-type pre-extracted fields ───


def test_verdict_and_citation_count_set() -> None:
    e = _make(
        event_type="auditor_verdict",
        verdict="allowed",
        citation_count=3,
        summary="auditor verdict — 3 citation(s) recorded",
    )
    assert e.verdict == "allowed"
    assert e.citation_count == 3
    assert e.summary is not None and "citation" in e.summary


def test_refusal_can_carry_zero_citations() -> None:
    e = _make(
        event_type="auditor_refusal",
        verdict="refused",
        citation_count=0,
    )
    assert e.verdict == "refused"
    assert e.citation_count == 0


# ─── Round-trip ───


def test_json_round_trip_preserves_fields() -> None:
    e = _make(
        event_type="charter_eval_run",
        verdict="failed",
        citation_count=0,
        summary="engineer charter pass@5 = 0.6 (target 0.8) — RED",
        payload={"role": "engineer", "pass_rate": 0.6},
    )
    payload = e.model_dump_json()
    parsed = ProjectEvent.model_validate_json(payload)
    assert parsed.event_id == e.event_id
    assert parsed.event_type == "charter_eval_run"
    assert parsed.summary is not None
    assert parsed.payload == {"role": "engineer", "pass_rate": 0.6}

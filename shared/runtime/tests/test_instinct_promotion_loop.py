"""Tests for instinct promotion loop (SPINE-006)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from learning.instinct import CONFIDENCE_FLOOR, InstinctStore, check_promotion
from shared.runtime.instinct_promotion_loop import (
    collect_project_fingerprints,
    instinct_promotion_tick,
    promotion_loop_enabled,
    sweep_project_promotions,
)


def _record(
    *,
    project_id: str = "proj-a",
    run_id: str = "run-1",
    confidence: float = CONFIDENCE_FLOOR,
):
    from learning.instinct import Instinct, InstinctRecord  # noqa: PLC0415

    return InstinctRecord(
        instinct=Instinct(
            pattern="use fixture X for Y",
            trigger="when editing tests",
            rationale="keeps tests stable",
            confidence=confidence,
        ),
        project_id=project_id,
        run_id=run_id,
        actor="qa",
    )


def test_promotion_loop_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPINE_INSTINCT_PROMOTION", raising=False)
    assert promotion_loop_enabled() is False
    monkeypatch.setenv("SPINE_INSTINCT_PROMOTION", "1")
    assert promotion_loop_enabled() is True
    monkeypatch.setenv("SPINE_INSTINCT_PROMOTION", "off")
    assert promotion_loop_enabled() is False


def test_collect_project_fingerprints_reads_jsonl(tmp_path: Path) -> None:
    InstinctStore(project_id="proj-a", run_id="run-1", root=tmp_path).record(
        _record(run_id="run-1", confidence=0.6),
    )
    InstinctStore(project_id="proj-a", run_id="run-2", root=tmp_path).record(
        _record(run_id="run-2", confidence=0.7),
    )
    fps = collect_project_fingerprints("proj-a", root=tmp_path)
    assert len(fps) == 1
    assert next(iter(fps)) == _record().instinct.fingerprint


def test_collect_project_fingerprints_empty_when_missing_dir(tmp_path: Path) -> None:
    assert collect_project_fingerprints("missing", root=tmp_path) == set()


def test_sweep_project_promotions_finds_eligible(tmp_path: Path) -> None:
    InstinctStore(project_id="proj-a", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-a", run_id="r1", confidence=0.6),
    )
    InstinctStore(project_id="proj-b", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-b", run_id="r1", confidence=0.8),
    )
    eligible = sweep_project_promotions(["proj-a", "proj-b"], root=tmp_path)
    assert len(eligible) == 1
    fp = _record().instinct.fingerprint
    assert eligible[0]["fingerprint"] == fp
    assert eligible[0]["decision"].eligible_for_promotion is True
    assert check_promotion(fp, root=tmp_path).eligible_for_promotion is True


def test_sweep_project_promotions_dedupes_fingerprints(tmp_path: Path) -> None:
    InstinctStore(project_id="proj-a", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-a", run_id="r1", confidence=0.6),
    )
    InstinctStore(project_id="proj-b", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-b", run_id="r1", confidence=0.8),
    )
    eligible = sweep_project_promotions(["proj-a", "proj-b", "proj-a"], root=tmp_path)
    assert len(eligible) == 1


def test_instinct_promotion_tick_uses_active_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    InstinctStore(project_id="proj-a", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-a", run_id="r1", confidence=0.6),
    )
    InstinctStore(project_id="proj-b", run_id="r1", root=tmp_path).record(
        _record(project_id="proj-b", run_id="r1", confidence=0.8),
    )
    monkeypatch.setattr(
        "shared.runtime.instinct_promotion_loop.fetch_active_project_ids",
        AsyncMock(return_value=["proj-a"]),
    )
    monkeypatch.setattr(
        "learning.instinct.default_instinct_root",
        lambda: tmp_path,
    )
    count = asyncio.run(instinct_promotion_tick())
    assert count == 1

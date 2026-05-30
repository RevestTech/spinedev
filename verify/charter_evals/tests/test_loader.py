"""Tests for the YAML loader + the starter eval YAMLs themselves.

Covers:
  * ``load_evals_for_role`` walks ``<root>/<role>/*.yaml`` and
    constructs :class:`CapabilityEval` objects.
  * Missing or empty role dirs return an empty list (no error).
  * A YAML whose ``role`` field disagrees with the directory name is
    rejected (catches accidental file moves).
  * The shipped starter evals load cleanly and satisfy the V3 #7a
    minimum (≥ 3 evals per role) so the gate can be turned on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.charter_evals.harness import (
    CapabilityEval,
    load_evals_for_role,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = REPO_ROOT / "verify" / "charter_evals"


# ─── Loader behaviour ────────────────────────────────────────────────


def test_loader_returns_empty_for_missing_role(tmp_path: Path) -> None:
    assert load_evals_for_role("nobody", root=tmp_path) == []


def test_loader_rejects_role_mismatch(tmp_path: Path) -> None:
    role_dir = tmp_path / "engineer"
    role_dir.mkdir()
    (role_dir / "bad.yaml").write_text(
        "name: x\n"
        "role: architect\n"  # disagrees with parent dir
        "task: t\n"
        "criteria:\n"
        "  - name: ok\n"
        "    required_substrings:\n"
        "      - X\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="declares role="):
        load_evals_for_role("engineer", root=tmp_path)


def test_loader_returns_pydantic_models(tmp_path: Path) -> None:
    role_dir = tmp_path / "engineer"
    role_dir.mkdir()
    (role_dir / "one.yaml").write_text(
        "name: small\n"
        "role: engineer\n"
        "task: t\n"
        "criteria:\n"
        "  - name: ok\n"
        "    required_substrings:\n"
        "      - present\n",
        encoding="utf-8",
    )
    evals = load_evals_for_role("engineer", root=tmp_path)
    assert len(evals) == 1
    assert isinstance(evals[0], CapabilityEval)
    assert evals[0].name == "small"


# ─── Shipped starter evals ───


def test_engineer_starter_evals_load_cleanly() -> None:
    evals = load_evals_for_role("engineer", root=EVAL_ROOT)
    assert len(evals) >= 3, "V3 #7a requires ≥ 3 starter evals to enforce gate"
    names = {e.name for e in evals}
    assert "engineer-cites-req-id-in-report" in names
    assert "engineer-declares-implementer-kind" in names
    assert "engineer-honours-search-first-contract" in names
    for e in evals:
        assert e.role == "engineer"


def test_architect_starter_evals_load_cleanly() -> None:
    evals = load_evals_for_role("architect", root=EVAL_ROOT)
    assert len(evals) >= 3, "V3 #7a requires ≥ 3 starter evals to enforce gate"
    names = {e.name for e in evals}
    assert "architect-cites-kg-node-id" in names
    assert "architect-declares-reversibility" in names
    assert "architect-anchors-in-recognised-methodology" in names
    for e in evals:
        assert e.role == "architect"


def test_every_starter_eval_has_useful_criteria() -> None:
    for role in ("engineer", "architect"):
        for ev in load_evals_for_role(role, root=EVAL_ROOT):
            assert ev.criteria, f"{ev.name} has no criteria"
            for crit in ev.criteria:
                assert crit.required_substrings or crit.forbidden_substrings, (
                    f"{ev.name}/{crit.name} has empty substring set"
                )

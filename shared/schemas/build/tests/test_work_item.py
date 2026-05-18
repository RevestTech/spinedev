"""Unit tests for ``shared.schemas.build.work_item`` (Wave-2 Squad-2, #19).

Exercises every one of the 7 subclasses, the discriminator helper, and
the type-set invariants that keep this module in lock-step with the V28
migration seed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from shared.schemas.build.work_item import (
    BugWorkItem,
    ComplianceWorkItem,
    FeatureWorkItem,
    IncidentWorkItem,
    InfraWorkItem,
    RefactorWorkItem,
    SupportWorkItem,
    WORK_ITEM_TYPES,
    WorkItem,
    work_item_from_dict,
)

# ── Invariants ─────────────────────────────────────────────────────────


def test_seven_canonical_types_in_seed_order() -> None:
    """The tuple must contain exactly the 7 V28 types in seed order."""
    assert WORK_ITEM_TYPES == (
        "feature", "bug", "incident", "support",
        "refactor", "infra", "compliance",
    )


# ── 7 subclasses ───────────────────────────────────────────────────────


def _base_kwargs() -> dict:
    return {
        "title": "x", "description": "y", "created_by": "alice",
    }


def test_feature_work_item_constructs() -> None:
    f = FeatureWorkItem(**_base_kwargs(), target_users="SMBs",
                        success_metric="DAU > 100", must_should_could="M: x")
    assert f.work_item_type == "feature"
    assert f.priority == "P2"          # default
    assert isinstance(f.created_at, datetime)
    assert f.created_at.tzinfo is not None


def test_bug_work_item_requires_severity_and_repro() -> None:
    b = BugWorkItem(**_base_kwargs(), severity="sev2",
                    reproduction_steps="1. do a\n2. expect b",
                    affected_versions=["1.0.0"])
    assert b.work_item_type == "bug"
    assert b.severity == "sev2"
    with pytest.raises(ValidationError):
        BugWorkItem(**_base_kwargs(), reproduction_steps="x")  # missing severity


def test_incident_work_item_root_cause_default_unknown() -> None:
    i = IncidentWorkItem(**_base_kwargs(), severity="sev1",
                         blast_radius="all customers in us-east-1")
    assert i.work_item_type == "incident"
    assert i.root_cause_status == "unknown"
    assert i.time_to_acknowledge is None


def test_support_work_item_requires_customer_id() -> None:
    s = SupportWorkItem(**_base_kwargs(), customer_id="acme-corp",
                        sla_target="P1 1h", escalated_from="zendesk")
    assert s.work_item_type == "support"
    with pytest.raises(ValidationError):
        SupportWorkItem(**_base_kwargs())  # missing customer_id


def test_refactor_work_item_requires_rationale_and_scope() -> None:
    r = RefactorWorkItem(**_base_kwargs(),
                         rationale="reduce cognitive load",
                         scope_summary="shared/notify/")
    assert r.work_item_type == "refactor"
    with pytest.raises(ValidationError):
        RefactorWorkItem(**_base_kwargs(), rationale="x")  # missing scope_summary


def test_infra_work_item_requires_cloud_target_and_blast_radius() -> None:
    inf = InfraWorkItem(**_base_kwargs(),
                        cloud_target="aws/us-east-1",
                        blast_radius="staging only")
    assert inf.work_item_type == "infra"
    with pytest.raises(ValidationError):
        InfraWorkItem(**_base_kwargs(), cloud_target="aws/us-east-1")  # missing blast_radius


def test_compliance_work_item_with_audit_deadline() -> None:
    c = ComplianceWorkItem(**_base_kwargs(),
                           framework="SOC2", control_id="CC6.1",
                           evidence_required=["access_review.csv"],
                           audit_deadline=date(2026, 6, 30))
    assert c.work_item_type == "compliance"
    assert c.audit_deadline == date(2026, 6, 30)
    with pytest.raises(ValidationError):
        ComplianceWorkItem(**_base_kwargs(), framework="SOC2")  # missing control_id


# ── Common base behaviour ──────────────────────────────────────────────


def test_base_rejects_extra_fields_via_FORBID() -> None:
    with pytest.raises(ValidationError):
        FeatureWorkItem(**_base_kwargs(), bogus_field=1)


def test_created_at_must_be_tz_aware() -> None:
    with pytest.raises(ValidationError):
        FeatureWorkItem(**_base_kwargs(), created_at=datetime(2026, 1, 1))


def test_priority_enum_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        FeatureWorkItem(**_base_kwargs(), priority="P9")  # type: ignore[arg-type]


# ── Discriminator helper ──────────────────────────────────────────────


def test_work_item_from_dict_routes_each_type() -> None:
    payloads = [
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "feature"}, FeatureWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "bug", "severity": "sev3",
          "reproduction_steps": "1. step"}, BugWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "incident", "severity": "sev2",
          "blast_radius": "scope"}, IncidentWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "support", "customer_id": "c"}, SupportWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "refactor", "rationale": "r" * 20,
          "scope_summary": "mod"}, RefactorWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "infra", "cloud_target": "aws/us",
          "blast_radius": "staging"}, InfraWorkItem),
        ({"title": "a", "description": "b", "created_by": "u",
          "work_item_type": "compliance", "framework": "SOC2",
          "control_id": "CC6.1"}, ComplianceWorkItem),
    ]
    for payload, expected_cls in payloads:
        item = work_item_from_dict(payload)
        assert isinstance(item, expected_cls), payload
        assert isinstance(item, WorkItem)


def test_work_item_from_dict_raises_on_missing_type() -> None:
    with pytest.raises(KeyError):
        work_item_from_dict({"title": "x"})


def test_work_item_from_dict_raises_on_unknown_type() -> None:
    with pytest.raises(ValueError):
        work_item_from_dict({"title": "x", "description": "y",
                             "created_by": "u", "work_item_type": "epic"})


def test_subclass_literal_is_pinned() -> None:
    """Each subclass must pin work_item_type to its own value (no cross-set)."""
    with pytest.raises(ValidationError):
        FeatureWorkItem(**_base_kwargs(), work_item_type="bug")  # type: ignore[arg-type]

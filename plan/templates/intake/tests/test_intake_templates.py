"""Validates the 6 new intake YAML templates conform to their declared schema.

Wave-2 Squad-2 deliverable. Walks each template under
``plan/templates/intake/`` whose ``type_id`` is one of the new 6 work-item
types and checks: (1) YAML safe-loadable, (2) required top-level keys
present, (3) ``default_pipeline`` + ``default_role_set`` match the V28
fallback, (4) the ``example_completed_intake`` round-trips through the
matching Pydantic subclass via ``work_item_from_dict``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from build.runtime.build_dispatcher import (
    _TYPE_PIPELINE_FALLBACK,
    _TYPE_ROLE_FALLBACK,
)
from shared.schemas.build.work_item import WORK_ITEM_TYPES, work_item_from_dict

TEMPLATES_DIR = Path(__file__).resolve().parents[1]

# The 6 NEW templates this squad authored. `feature` predates this squad and
# lives under a different YAML shape; it is intentionally excluded here.
NEW_TYPES = ("bug", "incident", "support", "refactor", "infra", "compliance")

REQUIRED_TOP_LEVEL_KEYS = {
    "type_id", "default_pipeline", "default_role_set",
    "required_fields", "validation_rules", "example_completed_intake",
}


def _load(type_id: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{type_id}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── Existence ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_template_file_exists(type_id: str) -> None:
    assert (TEMPLATES_DIR / f"{type_id}.yaml").is_file(), \
        f"missing intake template plan/templates/intake/{type_id}.yaml"


# ── YAML loadability ─────────────────────────────────────────────────


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_template_yaml_safe_loads(type_id: str) -> None:
    doc = _load(type_id)
    assert isinstance(doc, dict), f"{type_id}.yaml top-level must be a mapping"


# ── Shape ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_template_has_required_top_level_keys(type_id: str) -> None:
    doc = _load(type_id)
    missing = REQUIRED_TOP_LEVEL_KEYS - set(doc)
    assert not missing, f"{type_id}.yaml missing keys: {missing}"


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_type_id_matches_enum(type_id: str) -> None:
    doc = _load(type_id)
    assert doc["type_id"] == type_id
    assert doc["type_id"] in WORK_ITEM_TYPES


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_required_fields_is_nonempty_list_of_dicts(type_id: str) -> None:
    doc = _load(type_id)
    rf = doc["required_fields"]
    assert isinstance(rf, list) and rf, f"{type_id}.required_fields must be a non-empty list"
    for f in rf:
        assert isinstance(f, dict)
        assert "id" in f and "prompt" in f and "why_asked" in f


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_validation_rules_is_list(type_id: str) -> None:
    rules = _load(type_id)["validation_rules"]
    assert isinstance(rules, list) and rules


# ── Alignment with V28 seed (via dispatcher fallback) ─────────────────


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_default_pipeline_matches_v28_seed(type_id: str) -> None:
    doc = _load(type_id)
    assert doc["default_pipeline"] == _TYPE_PIPELINE_FALLBACK[type_id], \
        f"{type_id}.default_pipeline drifted from V28 seed / dispatcher fallback"


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_default_role_set_matches_v28_seed(type_id: str) -> None:
    doc = _load(type_id)
    assert list(doc["default_role_set"]) == list(_TYPE_ROLE_FALLBACK[type_id]), \
        f"{type_id}.default_role_set drifted from V28 seed / dispatcher fallback"


# ── Example round-trips through the Pydantic schema ───────────────────


@pytest.mark.parametrize("type_id", NEW_TYPES)
def test_example_intake_round_trips_through_schema(type_id: str) -> None:
    """The example_completed_intake should be a valid payload for its work-item type.

    We synthesize the WorkItem by combining intake-form answers with the
    minimum constructor fields (title/description/created_by). The intake
    template only carries domain-specific fields (severity, framework, …);
    the work-item constructor needs the common base fields too.
    """
    doc = _load(type_id)
    example = doc["example_completed_intake"]
    assert isinstance(example, dict) and example, \
        f"{type_id}.example_completed_intake must be a non-empty mapping"

    # Discard intake-only fields that aren't part of the WorkItem schema.
    # (Templates can ask additional questions for context that don't map 1:1
    #  onto the schema field set.)
    schema_only_extras = {
        "bug": set(),
        "incident": {"detection_source"},
        "support": {"customer_request", "requested_outcome"},
        "refactor": {"backout_plan"},
        "infra": {"change_type", "rollback_plan"},
        "compliance": {"current_state"},
    }
    cleaned = {k: v for k, v in example.items() if k not in schema_only_extras[type_id]}

    # The WorkItem subclass needs title/description/created_by. The intake
    # YAML always asks for `title`; we synthesize the other two so the
    # example is constructable in isolation.
    cleaned.setdefault("title", example.get("title", f"example {type_id}"))
    cleaned.setdefault("description", "Example payload from intake template.")
    cleaned.setdefault("created_by", "intake-template-test")
    cleaned["work_item_type"] = type_id

    item = work_item_from_dict(cleaned)
    assert item.work_item_type == type_id

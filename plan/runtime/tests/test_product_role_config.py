"""Tests for the V3 D2 slate #6 product runner registration.

The product role's actual LLM-driven generation is exercised through
the existing _run_text_role path; here we only assert the registration
+ prompt content so downstream roles can consume prd_md and the
prompt enforces the discoverer-not-order-taker discipline (#7
charter anchor).
"""
from __future__ import annotations

from plan.runtime.hub_role_runner import _PRODUCT_PROMPT, _ROLE_CONFIG


def test_product_role_registered() -> None:
    assert "product" in _ROLE_CONFIG
    prompt, artifact_key = _ROLE_CONFIG["product"]
    assert artifact_key == "prd_md"
    assert prompt is _PRODUCT_PROMPT


def test_product_prompt_carries_canonical_prd_sections() -> None:
    # The prompt must direct the role to produce the PRDv1 canonical
    # sections so downstream consumers (planner, architect, conductor,
    # qa) can rely on them.
    for section in (
        "Problem statement",
        "Users / stakeholders",
        "In scope",
        "Out of scope",
        "Goals",
        "Acceptance criteria",
        "Open questions",
    ):
        assert section in _PRODUCT_PROMPT, f"missing section: {section!r}"


def test_product_prompt_enforces_discoverer_discipline() -> None:
    # SVPG / Cagan + JTBD anchors. The prompt should reject
    # order-taking + invented requirements.
    assert "discoverer" in _PRODUCT_PROMPT.lower()
    assert "open_question" in _PRODUCT_PROMPT
    assert "do not invent" in _PRODUCT_PROMPT.lower()


def test_product_prompt_disallows_code_fences() -> None:
    assert "code fences" in _PRODUCT_PROMPT.lower()


def test_role_config_exposes_six_roles() -> None:
    # Confirms the product registration didn't accidentally replace
    # one of the existing roles.
    assert set(_ROLE_CONFIG) == {
        "product", "planner", "architect",
        "conductor", "qa", "release_manager",
    }

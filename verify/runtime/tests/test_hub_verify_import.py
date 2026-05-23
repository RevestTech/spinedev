"""Verify runtime package is importable in Hub image layout."""

from __future__ import annotations


def test_hub_verify_runner_importable() -> None:
    from verify.runtime.hub_verify_runner import run_hub_code_review

    assert callable(run_hub_code_review)

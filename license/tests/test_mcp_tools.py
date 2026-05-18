"""Tests for ``shared.mcp.tools.license`` (Wave 4 Squad B)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from license import bundle_verifier
from license.bundle_verifier import ActiveBundle
from shared.mcp.tools import TOOL_REGISTRY, discover_tools
from shared.schemas.license import FeatureFlag, LicenseBundlePayload


@pytest.fixture(autouse=True)
def _discover() -> None:
    discover_tools()  # idempotent


def _install_bundle(*, signature_ok: bool = True) -> None:
    payload = LicenseBundlePayload(
        customer="acme", tier="team", bundle_id="bundle-mcp-test",
        issued_at=datetime.now(timezone.utc),
        feature_flags=[
            FeatureFlag(flag_name="federation", enabled=True),
            FeatureFlag(flag_name="role_devops", enabled=True,
                        quota_value=100, quota_unit="agents_per_month"),
        ],
    )
    bundle_verifier.set_active_bundle(
        ActiveBundle(payload=payload, signature_ok=signature_ok),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_three_license_tools_registered() -> None:
    assert "license_get_status" in TOOL_REGISTRY
    assert "license_get_usage" in TOOL_REGISTRY
    assert "license_verify_bundle" in TOOL_REGISTRY


def test_verify_bundle_is_citation_required() -> None:
    """Per V3 #12, license_verify_bundle is verify-class — must cite."""
    spec = TOOL_REGISTRY["license_verify_bundle"]
    assert spec.requires_citation is True


def test_status_and_usage_are_not_citation_required() -> None:
    """Read-only status/usage tools are not verify-class."""
    assert TOOL_REGISTRY["license_get_status"].requires_citation is False
    assert TOOL_REGISTRY["license_get_usage"].requires_citation is False


# ---------------------------------------------------------------------------
# license_get_status
# ---------------------------------------------------------------------------


def test_get_status_with_bundle_installed() -> None:
    _install_bundle()
    from shared.mcp.tools.license import LicenseGetStatusInput, license_get_status
    resp = license_get_status(LicenseGetStatusInput(project_id="p1", actor="test"))
    assert resp.status == "ok"
    assert resp.data["tier"] == "team"
    assert resp.data["loaded"] is True
    assert any(f["flag_name"] == "federation" for f in resp.data["flags"])


def test_get_status_with_no_bundle() -> None:
    bundle_verifier.set_active_bundle(None)
    from shared.mcp.tools.license import LicenseGetStatusInput, license_get_status
    resp = license_get_status(LicenseGetStatusInput(project_id="p1"))
    assert resp.status == "ok"
    assert resp.data["loaded"] is False


# ---------------------------------------------------------------------------
# license_get_usage
# ---------------------------------------------------------------------------


def test_get_usage_with_no_pool_returns_empty() -> None:
    from license import feature_flags
    feature_flags.set_pool(None)
    from shared.mcp.tools.license import LicenseGetUsageInput, license_get_usage
    resp = license_get_usage(LicenseGetUsageInput(project_id="p1"))
    assert resp.status == "ok"
    assert resp.data["items"] == []


def test_get_usage_returns_rows_from_pool(mock_pool) -> None:
    from shared.mcp.tools.license import LicenseGetUsageInput, license_get_usage
    period_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    mock_pool.script_rows([
        {"flag_name": "role_devops", "period_start": period_start,
         "period_end": period_end, "used_value": 42, "ledger_anchor": b"\x01" * 32},
    ])
    resp = license_get_usage(LicenseGetUsageInput(project_id="p1"))
    assert resp.status == "ok"
    assert len(resp.data["items"]) == 1
    assert resp.data["items"][0]["used_value"] == 42
    assert resp.data["items"][0]["ledger_anchor_hex"] == "01" * 32


# ---------------------------------------------------------------------------
# license_verify_bundle — must produce citation per #12
# ---------------------------------------------------------------------------


def test_verify_bundle_returns_citation(mock_pool) -> None:
    """Even when verification cannot happen end-to-end the response must cite.

    With no signing-key mock available, signature_ok will be False, but
    the Cite-or-Refuse contract REQUIRES at least one Citation when the
    envelope's status is ``ok``.
    """
    _install_bundle()
    # No scripted rows → empty distinct-flag list → no chain replay needed.
    from shared.mcp.tools.license import (
        LicenseVerifyBundleInput,
        license_verify_bundle,
    )
    resp = license_verify_bundle(
        LicenseVerifyBundleInput(project_id="p1", verify_quota_chain=False),
    )
    assert resp.status == "ok"
    assert len(resp.citation) >= 1
    assert resp.citation[0].type in {"audit_hash", "file_line", "kg_node"}
    # The data envelope carries the verdict shape.
    assert "signature_ok" in resp.data
    assert resp.data["tier"] == "team"
    assert resp.data["bundle_id"] == "bundle-mcp-test"


def test_verify_bundle_with_no_bundle_still_cites(mock_pool) -> None:
    bundle_verifier.set_active_bundle(None)
    from shared.mcp.tools.license import (
        LicenseVerifyBundleInput,
        license_verify_bundle,
    )
    resp = license_verify_bundle(
        LicenseVerifyBundleInput(project_id="p1", verify_quota_chain=False),
    )
    assert resp.status == "ok"
    assert len(resp.citation) >= 1
    assert resp.data["signature_ok"] is False

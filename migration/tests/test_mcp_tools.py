"""Tests for ``shared.mcp.tools.migration``."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.mcp.tools import TOOL_REGISTRY, discover_tools


@pytest.fixture(autouse=True)
def _discover() -> None:
    discover_tools()  # idempotent


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    from shared.mcp.tools.migration import clear_runtime
    clear_runtime()
    yield
    clear_runtime()


# ---------------------------------------------------------------------------
# Registration + Cite-or-Refuse tags
# ---------------------------------------------------------------------------


def test_four_migration_tools_registered() -> None:
    for name in (
        "migration_export",
        "migration_import",
        "migration_onboarding_dispatch",
        "migration_version_upgrade",
    ):
        assert name in TOOL_REGISTRY, f"missing tool {name!r}"


def test_destructive_tools_are_citation_required() -> None:
    """Per #12 — destructive ops cite or refuse."""
    assert TOOL_REGISTRY["migration_import"].requires_citation is True
    assert TOOL_REGISTRY["migration_version_upgrade"].requires_citation is True


def test_read_only_tools_are_not_citation_required() -> None:
    assert TOOL_REGISTRY["migration_export"].requires_citation is False
    assert TOOL_REGISTRY["migration_onboarding_dispatch"].requires_citation is False


# ---------------------------------------------------------------------------
# migration_export
# ---------------------------------------------------------------------------


def test_export_stub_when_no_runtime() -> None:
    from shared.mcp.tools.migration import (
        MigrationExportInput,
        migration_export,
    )
    resp = migration_export(MigrationExportInput(
        project_id="p1", out_path="/tmp/nope.tar", bundle_id="b1",
    ))
    assert resp.status == "stub_implementation"


def test_export_calls_through_when_runtime_installed(
    tmp_path: Path, mock_reader, mock_signer,
) -> None:
    from shared.mcp.tools.migration import (
        MigrationExportInput,
        migration_export,
        set_runtime,
    )
    set_runtime(export_reader=mock_reader, export_signer=mock_signer)
    out = tmp_path / "out.tar"
    resp = migration_export(MigrationExportInput(
        project_id="p1", out_path=str(out), bundle_id="b1",
    ))
    assert resp.status == "ok"
    assert resp.data["bundle_id"] == "b1"
    assert set(resp.data["schema_row_counts"].keys()) == set(
        resp.data["schemas"],
    )


# ---------------------------------------------------------------------------
# migration_import
# ---------------------------------------------------------------------------


def test_import_stub_carries_citation_even_when_skipped() -> None:
    """Cite-or-Refuse requires at least one citation on every response."""
    from shared.mcp.tools.migration import (
        MigrationImportInput,
        migration_import,
    )
    resp = migration_import(MigrationImportInput(
        project_id="p1", in_path="/tmp/nope.tar",
    ))
    assert resp.status == "stub_implementation"
    assert len(resp.citation) >= 1
    assert resp.citation[0].type == "audit_hash"


def test_import_round_trip_via_mcp_tool(
    tmp_path: Path, mock_reader, mock_signer, mock_verifier, mock_writer,
) -> None:
    from migration.export import export_state
    from shared.mcp.tools.migration import (
        MigrationImportInput,
        migration_import,
        set_runtime,
    )
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt-mcp", when=datetime(2026, 5, 17, tzinfo=timezone.utc))

    set_runtime(import_verifier=mock_verifier, import_writer=mock_writer)
    resp = migration_import(MigrationImportInput(
        project_id="p1", in_path=str(out),
    ))
    assert resp.status == "ok"
    assert resp.data["all_ok"] is True
    assert resp.data["signature_ok"] is True
    assert resp.data["audit_chain_ok"] is True
    assert len(resp.citation) >= 1


def test_import_bad_signature_cites_refusal(
    tmp_path: Path, mock_reader, mock_signer, mock_writer,
) -> None:
    """A refusal MUST still ship a citation; refusal is itself audited."""
    from migration.export import export_state
    from shared.mcp.tools.migration import (
        MigrationImportInput,
        migration_import,
        set_runtime,
    )
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt-bad", when=datetime(2026, 5, 17, tzinfo=timezone.utc))

    # Build a verifier with a DIFFERENT keypair.
    import hashlib as _h
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = Ed25519PrivateKey.generate()
    other_pub = other.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    from migration.tests.conftest import InMemoryVerifier, _Keypair
    bad = InMemoryVerifier(_Keypair(
        private=other, public_bytes=other_pub,
        fingerprint=_h.sha256(other_pub).hexdigest(),
    ))
    set_runtime(import_verifier=bad, import_writer=mock_writer)
    resp = migration_import(MigrationImportInput(
        project_id="p1", in_path=str(out),
    ))
    assert resp.status == "error"
    assert resp.error.code == "fingerprint_mismatch"
    assert len(resp.citation) >= 1


# ---------------------------------------------------------------------------
# migration_onboarding_dispatch
# ---------------------------------------------------------------------------


def test_onboarding_dispatch_runs_github_and_linear(
    mock_http, mock_sink, stub_token_loader,
) -> None:
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [
        {"id": 1, "number": 1, "title": "GH", "body": "", "labels": [],
         "state": "open", "html_url": "x", "created_at": "", "updated_at": "",
         "assignee": None},
    ])
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i1", "identifier": "LIN-1", "title": "Lin", "description": "",
                 "state": {"name": "Todo", "type": "unstarted"}, "url": "x",
                 "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "L", "name": "L"}},
            ],
        }},
    })

    # Token loader patches the connector default at the secret-loader level.
    # Since the MCP tool path constructs connectors itself, we monkeypatch
    # shared.secrets.get_secret to short-circuit token fetches.
    import shared.secrets as _secrets

    async def _patched(path: str) -> str:
        return f"token-for-{path}"
    original = _secrets.get_secret
    _secrets.get_secret = _patched  # type: ignore[assignment]
    try:
        from shared.mcp.tools.migration import (
            MigrationOnboardingDispatchInput,
            migration_onboarding_dispatch,
            set_runtime,
            _ConnectorSpec,
        )
        set_runtime(onboarding_http=mock_http, onboarding_sink=mock_sink)
        resp = migration_onboarding_dispatch(MigrationOnboardingDispatchInput(
            project_id="p1",
            connectors=[
                _ConnectorSpec(kind="github", org_or_workspace="acme"),
                _ConnectorSpec(kind="linear", org_or_workspace="acme"),
            ],
        ))
    finally:
        _secrets.get_secret = original  # type: ignore[assignment]
    assert resp.status == "ok"
    assert resp.data["total_work_items"] == 2
    assert {p["connector"] for p in resp.data["per_connector"]} == {"github", "linear"}


def test_onboarding_rejects_unknown_connector_kind() -> None:
    from shared.mcp.tools.migration import (
        MigrationOnboardingDispatchInput,
        migration_onboarding_dispatch,
        set_runtime,
        _ConnectorSpec,
    )
    # Set a runtime so we get past the stub gate.
    set_runtime(onboarding_http=object(), onboarding_sink=object())
    resp = migration_onboarding_dispatch(MigrationOnboardingDispatchInput(
        project_id="p1",
        connectors=[_ConnectorSpec(kind="jira", org_or_workspace="acme")],
    ))
    assert resp.status == "error"
    assert resp.error.code == "unknown_connector_kind"


# ---------------------------------------------------------------------------
# migration_version_upgrade
# ---------------------------------------------------------------------------


def test_version_upgrade_noop_path_ok() -> None:
    from shared.mcp.tools.migration import (
        MigrationVersionUpgradeInput,
        migration_version_upgrade,
    )
    resp = migration_version_upgrade(MigrationVersionUpgradeInput(
        project_id="p1", from_version="1.0", to_version="1.0",
        approved_by="admin@acme.com",
    ))
    assert resp.status == "ok"
    assert resp.data["all_ok"] is True
    assert len(resp.citation) >= 1


def test_version_upgrade_downgrade_blocked_cites_refusal() -> None:
    from shared.mcp.tools.migration import (
        MigrationVersionUpgradeInput,
        migration_version_upgrade,
    )
    resp = migration_version_upgrade(MigrationVersionUpgradeInput(
        project_id="p1", from_version="1.2", to_version="1.0",
        approved_by="admin@acme.com",
    ))
    assert resp.status == "error"
    assert resp.error.code == "downgrade_blocked"
    assert len(resp.citation) >= 1


def test_version_upgrade_dry_run_records_steps() -> None:
    from shared.mcp.tools.migration import (
        MigrationVersionUpgradeInput,
        migration_version_upgrade,
    )
    resp = migration_version_upgrade(MigrationVersionUpgradeInput(
        project_id="p1", from_version="1.0", to_version="1.2",
        dry_run=True, approved_by="admin@acme.com",
    ))
    assert resp.status == "ok"
    assert resp.data["step_count"] > 0
    statuses = {o["status"] for o in resp.data["outcomes"]}
    assert statuses == {"skipped"}

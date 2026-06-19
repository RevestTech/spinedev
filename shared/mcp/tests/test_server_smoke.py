"""Smoke tests for the unified Spine MCP server scaffolding.

These tests verify the static shape of the tool registry without booting a
real MCP runtime. They are safe to run in CI without the ``mcp`` SDK present
(the server module imports the SDK lazily).

Counts expected — updated post-v3 module split (Wave 2 housekeeping). The
pre-split layout (17 tools across 6 modules) was outdated as soon as
``iso.py``, ``sandbox.py``, and ``auditor.py`` were extracted from
``verify.py`` and ``kg.py`` gained two more tools. Reality on
2026-05 is 27 tools across 9 modules:

* orchestrator.py — 4  (project_create, project_status, phase_advance, approval_grant)
* plan.py         — 1  (plan_dispatch)
* build.py        — 2  (build_dispatch, build_completed)
* verify.py       — 2  (verify_audit, verify_hub_review)
* iso.py          — 7  (iso_invoke + 6 *_iso_scan convenience tools)
* sandbox.py      — 1  (sandbox_run)
* auditor.py      — 1  (verify_build_artifact)
* kg.py           — 9  (graph_query, find_callers, code_neighborhood, impact_radius,
                        doc_for_region, who_owns, hybrid_search, find_by_satisfies,
                        trace_dependency)
* standards.py    — 1  (org_standards_get)

Total: 27 tools.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import BaseModel

EXPECTED_TOOL_COUNT: int = 56

EXPECTED_TOOLS_BY_MODULE: dict[str, set[str]] = {
    "shared.mcp.tools.orchestrator": {
        "project_create",
        "project_status",
        "phase_advance",
        "approval_grant",
    },
    "shared.mcp.tools.plan": {"plan_dispatch"},
    "shared.mcp.tools.build": {"build_dispatch", "build_completed"},
    "shared.mcp.tools.verify": {"verify_audit", "verify_hub_review"},
    "shared.mcp.tools.iso": {
        "iso_invoke",
        "security_iso_scan",
        "builder_iso_scan",
        "qa_iso_scan",
        "performance_iso_scan",
        "compliance_iso_scan",
        "documentation_iso_scan",
    },
    "shared.mcp.tools.sandbox": {"sandbox_run"},
    "shared.mcp.tools.auditor": {"verify_build_artifact"},
    "shared.mcp.tools.kg": {
        "graph_query",
        "find_callers",
        "code_neighborhood",
        "impact_radius",
        "doc_for_region",
        "who_owns",
        "hybrid_search",
        "find_by_satisfies",
        "trace_dependency",
    },
    "shared.mcp.tools.standards": {"org_standards_get"},
    # Wave 4 BUILD-NEW (2026-05-18):
    "shared.mcp.tools.federation": {
        "federation_register_child",
        "federation_grant_consent",
        "federation_push_update",
        "federation_pull_updates",
    },
    "shared.mcp.tools.license": {
        "license_get_status",
        "license_get_usage",
        "license_verify_bundle",
    },
    "shared.mcp.tools.evidence": {
        "evidence_collect",
        "evidence_export",
        "evidence_status",
        "evidence_attestation_verify",
    },
    "shared.mcp.tools.learning": {
        "learning_contribute",
        "learning_query",
        "learning_grant_cross_org_consent",
        "learning_revoke_cross_org_consent",
    },
    # Wave 5 BUILD-NEW (2026-05-18):
    "shared.mcp.tools.recovery": {
        "recovery_snapshot",
        "recovery_restore",
        "recovery_test",
        "recovery_health",
        "recovery_runbook_export",
    },
    "shared.mcp.tools.migration": {
        "migration_export",
        "migration_import",
        "migration_onboarding_dispatch",
        "migration_version_upgrade",
    },
    # Wave 6 BUILD-NEW (2026-05-18):
    "shared.mcp.tools.integrations": {
        "integrations_list",
        "integrations_test_connection",
        "integrations_configure",
    },
    "shared.mcp.tools.role_chat": {"role_chat"},
}


@pytest.fixture(scope="module")
def registry() -> dict:
    """Import the server + all tool modules; return the populated registry."""
    # Importing server triggers nothing on its own (lazy MCP import); we
    # explicitly call discover_tools to populate the registry.
    server_mod = importlib.import_module("shared.mcp.server")
    tools_pkg = importlib.import_module("shared.mcp.tools")
    tools_pkg.discover_tools("shared.mcp.tools")
    # Touch the server module so it counts toward "imports successfully".
    assert hasattr(server_mod, "SpineMcpServer")
    return dict(tools_pkg.TOOL_REGISTRY)


def test_server_module_imports() -> None:
    """The server module must import cleanly without the mcp SDK present."""
    mod = importlib.import_module("shared.mcp.server")
    assert hasattr(mod, "SpineMcpServer")
    assert hasattr(mod, "main")
    assert callable(mod.configure_logging)


def test_envelopes_module_imports() -> None:
    """Shared envelopes module must import cleanly and expose the public API."""
    envelopes = importlib.import_module("shared.mcp.schemas.envelopes")
    for name in ("ToolRequest", "ToolResponse", "ToolError"):
        assert hasattr(envelopes, name), f"missing envelope: {name}"
        assert issubclass(getattr(envelopes, name), BaseModel)


def test_every_tool_module_imports() -> None:
    """Every tool module must be importable in isolation."""
    for module in EXPECTED_TOOLS_BY_MODULE:
        importlib.import_module(module)


def test_registry_has_expected_total_count(registry: dict) -> None:
    """Total registered tool count must equal the documented catalog size."""
    assert len(registry) == EXPECTED_TOOL_COUNT, (
        f"Expected {EXPECTED_TOOL_COUNT} tools; got {len(registry)}: {sorted(registry)}"
    )


def test_registry_has_expected_tools_per_module(registry: dict) -> None:
    """Each tool module must register exactly the tools the catalog lists."""
    by_module: dict[str, set[str]] = {}
    for name, spec in registry.items():
        by_module.setdefault(spec.module, set()).add(name)
    for module, expected_names in EXPECTED_TOOLS_BY_MODULE.items():
        assert by_module.get(module) == expected_names, (
            f"{module} tool set mismatch: got {by_module.get(module)}, expected {expected_names}"
        )


def test_no_duplicate_tool_names(registry: dict) -> None:
    """Registry keys are unique by construction; double-check via spec.name."""
    names = [spec.name for spec in registry.values()]
    assert len(names) == len(set(names)), f"Duplicate tool names detected: {names}"


def test_each_tool_input_model_is_pydantic(registry: dict) -> None:
    """Every registered tool must declare a Pydantic v2 ``BaseModel`` input."""
    for name, spec in registry.items():
        assert isinstance(spec.input_model, type), f"{name}: input_model is not a class"
        assert issubclass(spec.input_model, BaseModel), (
            f"{name}: input_model {spec.input_model!r} is not a Pydantic BaseModel subclass"
        )


def test_each_tool_function_is_callable(registry: dict) -> None:
    """Every registered tool must expose a callable function."""
    for name, spec in registry.items():
        assert callable(spec.fn), f"{name}: fn is not callable"


def test_each_tool_has_implementing_story(registry: dict) -> None:
    """Every registered tool must declare an implementing story for traceability.

    Wave 4 (2026-05-18) added subsystems that ship as ``WAVE-4.<squad>.N``
    story IDs rather than the v2 ``STORY-X.Y.Z`` format. Both prefixes are
    accepted; the assertion only enforces non-empty traceability.
    """
    for name, spec in registry.items():
        assert spec.story and (
            spec.story.startswith("STORY-") or spec.story.startswith("WAVE-")
        ), (
            f"{name}: story {spec.story!r} must look like 'STORY-X.Y.Z' "
            f"or 'WAVE-N.<squad>.M' (Wave 4+ convention)"
        )


def test_spine_mcp_server_load_tools(registry: dict) -> None:
    """SpineMcpServer.load_tools must return the same catalog the registry holds."""
    server_mod = importlib.import_module("shared.mcp.server")
    server = server_mod.SpineMcpServer()
    loaded = server.load_tools()
    assert set(loaded) == set(registry)
    assert set(server.tools) == set(registry)

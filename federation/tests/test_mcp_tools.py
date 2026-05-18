"""
federation/tests/test_mcp_tools.py
==================================

Smoke tests for the 4 MCP tools in `shared.mcp.tools.federation`:

* Tool registration (4 tools land in `TOOL_REGISTRY`)
* requires_citation correctness (`register_child` + `push_update` only)
* Stub responses when deps are not wired
* End-to-end with injected deps (`set_federation_deps`)
"""

from __future__ import annotations

import asyncio
import unittest
from uuid import uuid4

from federation.consent import ConsentEngine
from federation.hub_registry import HubRegistry
from federation.tests._mock_pool import make_pool, new_uuid
from federation.update_cascade import UpdateCascade

# Importing the module registers the 4 tools as a side effect.
from shared.mcp.tools import TOOL_REGISTRY
from shared.mcp.tools.federation import (  # noqa: F401 - registers tools
    clear_federation_deps,
    federation_grant_consent,
    federation_pull_updates,
    federation_push_update,
    federation_register_child,
    GrantConsentIn,
    PullUpdatesIn,
    PushUpdateIn,
    RegisterChildIn,
    set_federation_deps,
)
from shared.schemas.federation import (
    ConsentGrantV1,
    HubRegistrationV1,
    UpdateCascadePullV1,
    UpdateCascadePushV1,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestRegistration(unittest.TestCase):
    def test_four_tools_registered(self):
        names = {
            "federation_register_child",
            "federation_grant_consent",
            "federation_push_update",
            "federation_pull_updates",
        }
        for n in names:
            self.assertIn(n, TOOL_REGISTRY, f"{n} missing from TOOL_REGISTRY")

    def test_requires_citation_flags(self):
        self.assertTrue(TOOL_REGISTRY["federation_register_child"].requires_citation)
        self.assertTrue(TOOL_REGISTRY["federation_push_update"].requires_citation)
        self.assertFalse(TOOL_REGISTRY["federation_grant_consent"].requires_citation)
        self.assertFalse(TOOL_REGISTRY["federation_pull_updates"].requires_citation)


class TestStubResponses(unittest.TestCase):
    def setUp(self):
        clear_federation_deps()

    def test_register_child_returns_stub(self):
        inp = RegisterChildIn(
            payload=HubRegistrationV1(
                child_hub_id=uuid4(),
                parent_hub_id=uuid4(),
                name="child",
                base_url="https://child",
                public_key="pk",
                rationale="org expansion",
            )
        )
        resp = federation_register_child(inp)
        self.assertEqual(resp.status, "stub_implementation")

    def test_pull_updates_returns_stub(self):
        inp = PullUpdatesIn(
            payload=UpdateCascadePullV1(target_hub_id=uuid4()),
        )
        resp = federation_pull_updates(inp)
        self.assertEqual(resp.status, "stub_implementation")


class TestWiredTools(unittest.TestCase):
    def setUp(self):
        clear_federation_deps()
        self.pool = make_pool()
        self.parent_id = new_uuid()
        self.registry = HubRegistry(self.pool)

        async def boot():
            await self.registry.bootstrap_local_hub(
                hub_id=self.parent_id, name="p",
                base_url="https://parent", public_key="pk",
            )

        _run(boot())
        self.engine = ConsentEngine(pool=self.pool)

        class _FakeRouter:
            def __init__(self_inner, reg):
                self_inner._registry = reg

            async def call_child(self_inner, *a, **kw):
                return {"ok": True}

        self.cascade = UpdateCascade(
            pool=self.pool,
            local_hub_id=self.parent_id,
            downstream_router=_FakeRouter(self.registry),
            consent_engine=self.engine,
        )
        set_federation_deps(
            hub_registry=self.registry,
            consent_engine=self.engine,
            update_cascade=self.cascade,
            local_hub_id=self.parent_id,
        )

    def tearDown(self):
        clear_federation_deps()

    def test_register_child_happy(self):
        child = uuid4()
        inp = RegisterChildIn(
            payload=HubRegistrationV1(
                child_hub_id=child,
                parent_hub_id=self.parent_id,
                name="child-1",
                base_url="https://child-1",
                public_key="pk-c",
                rationale="onboarding",
            ),
            actor="opsbot",
        )
        resp = federation_register_child(inp)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["hub_id"], str(child))
        # #12 — citation present
        self.assertTrue(len(resp.citation) >= 1)
        self.assertEqual(resp.citation[0].type, "audit_hash")

    def test_grant_consent_happy(self):
        child = uuid4()
        # First register
        _run(
            self.registry.register_child(
                child_hub_id=child, name="c", base_url="x", public_key="pk",
                parent_hub_id=self.parent_id,
            )
        )
        inp = GrantConsentIn(
            payload=ConsentGrantV1(
                child_hub_id=child,
                parent_hub_id=self.parent_id,
                consent_class="telemetry",
                granted_by="alice",
                rationale="observability rollup",
            ),
            actor="alice",
        )
        resp = federation_grant_consent(inp)
        self.assertEqual(resp.status, "ok")
        # consent now applies
        self.assertTrue(_run(self.engine.is_allowed(child, "telemetry")))

    def test_push_update_no_match_errors(self):
        inp = PushUpdateIn(
            payload=UpdateCascadePushV1(
                bundle_version="v9.9.9",
                signature_b64="sig",
                source_hub_id=uuid4(),
                rationale="hot patch",
            ),
            approved_by="opsbot",
        )
        resp = federation_push_update(inp)
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error.code, "federation_no_pending_match")

    def test_pull_updates_returns_items(self):
        # Seed one pending row
        async def seed():
            async with self.pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid4(), uuid4(), self.parent_id, "v1.0.0", b"sig",
                )

        _run(seed())
        inp = PullUpdatesIn(
            payload=UpdateCascadePullV1(target_hub_id=self.parent_id),
        )
        resp = federation_pull_updates(inp)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(len(resp.data["items"]), 1)
        self.assertEqual(resp.data["items"][0]["bundle_version"], "v1.0.0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""
federation/tests/test_update_cascade.py
=======================================

Unit tests for `federation.update_cascade.UpdateCascade`:

* `pull_pending` returns only pending rows targeting the local Hub
* `approve_and_apply` happy-path: status→completed, child rows inserted
* `approve_and_apply` rejects empty approver / rationale (#16)
* Sanity-smoke failure transitions to `failed`
* `reject` flips status to `rolled_back`
* Cascade respects child consent_status + consent_engine gating

A trivial fake DownstreamRouter records `call_child` invocations
instead of opening real httpx clients.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from federation.consent import ConsentEngine
from federation.hub_registry import HubRegistry
from federation.tests._mock_pool import make_pool, new_uuid
from federation.update_cascade import (
    ApprovalRequired,
    CascadeError,
    UpdateCascade,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeRouter:
    """Just enough router surface for the cascade to use it.

    Stores `call_child` invocations so tests can assert which children
    were notified.
    """

    def __init__(self, registry: HubRegistry) -> None:
        self._registry = registry
        self.calls: list[dict] = []

    async def call_child(self, child_hub_id, *, method, path, consent_class, json):
        self.calls.append(
            {
                "child_hub_id": child_hub_id,
                "method": method,
                "path": path,
                "consent_class": consent_class,
                "json": json,
            }
        )
        return {"ok": True}


def _build(parent_id, children_status, consent_classes):
    """Build (pool, registry, engine, router, cascade) for a topology.

    `children_status` = list of (child_uuid, status)
    `consent_classes` = list of (child_uuid, parent_uuid, class)
    """
    pool = make_pool()
    reg = HubRegistry(pool)
    eng = ConsentEngine(pool=pool)

    async def setup():
        await reg.bootstrap_local_hub(
            hub_id=parent_id, name="parent",
            base_url="https://parent", public_key="pk",
        )
        for cid, status in children_status:
            await reg.register_child(
                child_hub_id=cid, name=f"child-{cid}",
                base_url=f"https://{cid}",
                public_key="pk-c",
                parent_hub_id=parent_id,
                initial_status=status,
            )
        for cid, pid, cls in consent_classes:
            await eng.grant(
                child_hub_id=cid,
                parent_hub_id=pid,
                consent_class=cls,
                granted_by="ops",
            )

    _run(setup())
    router = _FakeRouter(reg)
    cas = UpdateCascade(
        pool=pool,
        local_hub_id=parent_id,
        downstream_router=router,
        consent_engine=eng,
    )
    return pool, reg, eng, router, cas


class TestPullPending(unittest.TestCase):
    def test_returns_only_pending_for_us(self):
        parent_id = new_uuid()
        pool, _, _, _, cas = _build(parent_id, [], [])
        # Insert: one pending for us, one for someone else
        other = new_uuid()

        async def go():
            async with pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid4(), uuid4(), parent_id, "v1.0.0", b"sig",
                )
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid4(), uuid4(), other, "v1.0.0", b"sig",
                )
            pending = await cas.pull_pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].target_hub_id, parent_id)
            self.assertEqual(pending[0].bundle_version, "v1.0.0")

        _run(go())


class TestApproveAndApply(unittest.TestCase):
    def test_requires_approved_by(self):
        parent_id = new_uuid()
        _, _, _, _, cas = _build(parent_id, [], [])
        self.assertRaises(
            ApprovalRequired,
            _run,
            cas.approve_and_apply(uuid4(), approved_by="", rationale="r"),
        )

    def test_requires_rationale(self):
        parent_id = new_uuid()
        _, _, _, _, cas = _build(parent_id, [], [])
        self.assertRaises(
            ApprovalRequired,
            _run,
            cas.approve_and_apply(uuid4(), approved_by="op", rationale=""),
        )

    def test_happy_path_cascades_to_consenting_active_children(self):
        parent_id = new_uuid()
        child_active_consent = new_uuid()
        child_active_no_consent = new_uuid()
        child_suspended = new_uuid()
        pool, _, _, router, cas = _build(
            parent_id,
            [
                (child_active_consent, "active"),
                (child_active_no_consent, "active"),
                (child_suspended, "suspended"),
            ],
            [(child_active_consent, parent_id, "update_push")],
        )
        uid = uuid4()

        async def go():
            async with pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uid, uuid4(), parent_id, "v1.1.0", b"sig",
                )
            outcome = await cas.approve_and_apply(
                uid, approved_by="opsbot", rationale="sec patch"
            )
            self.assertEqual(outcome.local_status, "completed")
            # only the active+consenting child got an attempt
            self.assertEqual(outcome.children_attempted, 1)
            self.assertEqual(outcome.children_succeeded, 1)
            self.assertEqual(outcome.children_failed, 0)
            self.assertEqual(len(router.calls), 1)
            self.assertEqual(
                router.calls[0]["child_hub_id"], child_active_consent
            )
            # local row marked completed + approved_by recorded
            self.assertEqual(pool.store.updates[uid]["rollout_status"], "completed")
            self.assertEqual(pool.store.updates[uid]["approved_by"], "opsbot")

        _run(go())

    def test_sanity_smoke_failure_marks_failed(self):
        parent_id = new_uuid()
        pool, _, eng, router, _ = _build(parent_id, [], [])

        async def smoke_false(bundle_version):
            return False

        cas = UpdateCascade(
            pool=pool,
            local_hub_id=parent_id,
            downstream_router=router,
            consent_engine=eng,
            sanity_smoke=smoke_false,
        )
        uid = uuid4()

        async def go():
            async with pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uid, uuid4(), parent_id, "v2.0.0", b"sig",
                )
            try:
                await cas.approve_and_apply(
                    uid, approved_by="op", rationale="r"
                )
                self.fail("expected CascadeError")
            except CascadeError:
                pass
            self.assertEqual(pool.store.updates[uid]["rollout_status"], "failed")

        _run(go())

    def test_reject_marks_rolled_back(self):
        parent_id = new_uuid()
        pool, _, _, _, cas = _build(parent_id, [], [])
        uid = uuid4()

        async def go():
            async with pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uid, uuid4(), parent_id, "v3.0.0", b"sig",
                )
            outcome = await cas.reject(
                uid, rejected_by="opsbot", rationale="risk too high"
            )
            self.assertEqual(outcome.local_status, "rolled_back")
            self.assertEqual(
                pool.store.updates[uid]["rollout_status"], "rolled_back"
            )

        _run(go())

    def test_reject_requires_rejected_by_and_rationale(self):
        parent_id = new_uuid()
        _, _, _, _, cas = _build(parent_id, [], [])
        self.assertRaises(
            ApprovalRequired,
            _run,
            cas.reject(uuid4(), rejected_by="", rationale="r"),
        )
        self.assertRaises(
            ApprovalRequired,
            _run,
            cas.reject(uuid4(), rejected_by="op", rationale=""),
        )

    def test_non_pending_update_refuses_approve(self):
        parent_id = new_uuid()
        pool, _, _, _, cas = _build(parent_id, [], [])
        uid = uuid4()

        async def go():
            async with pool.acquire() as c:
                await c.execute(
                    "INSERT INTO spine_federation.update_distribution "
                    "  (id, source_hub_id, target_hub_id, bundle_version, signature) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uid, uuid4(), parent_id, "v4.0.0", b"sig",
                )
                # flip status to completed first
                await c.execute(
                    "UPDATE spine_federation.update_distribution "
                    "SET rollout_status = $1 WHERE id = $2",
                    "completed", uid,
                )
            try:
                await cas.approve_and_apply(
                    uid, approved_by="op", rationale="r"
                )
                self.fail("expected CascadeError")
            except CascadeError as exc:
                self.assertIn("status='completed'", str(exc))

        _run(go())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

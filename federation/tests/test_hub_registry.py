"""
federation/tests/test_hub_registry.py
=====================================

Unit tests for `federation.hub_registry`:

* `read_hub_id_file` — file-backed UUID reader
* `HubRegistry.bootstrap_local_hub` — idempotency
* `HubRegistry.register_child` + `list_children`
* `HubRegistry.set_consent_status` — happy + HubNotFound

No asyncpg / network — uses `_MockPool`.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from federation.hub_registry import (
    HubIdFileMissing,
    HubNotFound,
    HubRegistry,
    read_hub_id_file,
)
from federation.tests._mock_pool import make_pool, new_uuid


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestReadHubIdFile(unittest.TestCase):
    def test_missing_file_raises(self):
        with TemporaryDirectory() as d:
            self.assertRaises(
                HubIdFileMissing, read_hub_id_file, Path(d) / "nope.txt"
            )

    def test_empty_file_raises(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hub_id.txt"
            p.write_text("\n", encoding="utf-8")
            self.assertRaises(HubIdFileMissing, read_hub_id_file, p)

    def test_invalid_uuid_raises(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hub_id.txt"
            p.write_text("not-a-uuid", encoding="utf-8")
            self.assertRaises(ValueError, read_hub_id_file, p)

    def test_valid_uuid_round_trips(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hub_id.txt"
            u = uuid4()
            p.write_text(str(u), encoding="utf-8")
            self.assertEqual(read_hub_id_file(p), u)


class TestBootstrapLocalHub(unittest.TestCase):
    def test_inserts_on_first_call(self):
        pool = make_pool()
        reg = HubRegistry(pool)
        hub_id = new_uuid()

        async def go():
            rec = await reg.bootstrap_local_hub(
                hub_id=hub_id,
                name="local",
                base_url="https://local.example",
                public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----",
            )
            self.assertEqual(rec.hub_id, hub_id)
            self.assertEqual(rec.consent_status, "active")
            # Row durable in mock store
            self.assertIn(hub_id, pool.store.hubs)

        _run(go())

    def test_idempotent_on_second_call(self):
        pool = make_pool()
        reg = HubRegistry(pool)
        hub_id = new_uuid()

        async def go():
            await reg.bootstrap_local_hub(
                hub_id=hub_id, name="a",
                base_url="https://a.example",
                public_key="pk",
            )
            # Second call with different name MUST NOT mutate
            rec = await reg.bootstrap_local_hub(
                hub_id=hub_id, name="b",
                base_url="https://b.example",
                public_key="pk-different",
            )
            self.assertEqual(rec.name, "a")
            self.assertEqual(rec.public_key, "pk")
            self.assertEqual(len(pool.store.hubs), 1)

        _run(go())


class TestChildRegistration(unittest.TestCase):
    def test_register_and_list_children(self):
        pool = make_pool()
        reg = HubRegistry(pool)
        parent_id = new_uuid()
        child_a = new_uuid()
        child_b = new_uuid()

        async def go():
            await reg.bootstrap_local_hub(
                hub_id=parent_id, name="parent",
                base_url="https://parent", public_key="pk",
            )
            await reg.register_child(
                child_hub_id=child_a, name="child-a",
                base_url="https://child-a", public_key="pk-a",
                parent_hub_id=parent_id,
            )
            await reg.register_child(
                child_hub_id=child_b, name="child-b",
                base_url="https://child-b", public_key="pk-b",
                parent_hub_id=parent_id,
                initial_status="active",
            )
            kids = await reg.list_children(parent_id)
            self.assertEqual({k.hub_id for k in kids}, {child_a, child_b})
            statuses = {k.hub_id: k.consent_status for k in kids}
            self.assertEqual(statuses[child_a], "pending")
            self.assertEqual(statuses[child_b], "active")

        _run(go())

    def test_set_consent_status_happy(self):
        pool = make_pool()
        reg = HubRegistry(pool)
        parent_id = new_uuid()
        child_a = new_uuid()

        async def go():
            await reg.bootstrap_local_hub(
                hub_id=parent_id, name="p", base_url="x", public_key="pk",
            )
            await reg.register_child(
                child_hub_id=child_a, name="c",
                base_url="x", public_key="pk",
                parent_hub_id=parent_id,
            )
            await reg.set_consent_status(child_a, "active")
            rec = await reg.get_by_hub_id(child_a)
            assert rec is not None
            self.assertEqual(rec.consent_status, "active")

        _run(go())

    def test_set_consent_status_unknown_raises(self):
        pool = make_pool()
        reg = HubRegistry(pool)

        async def go():
            await reg.set_consent_status(new_uuid(), "active")

        self.assertRaises(HubNotFound, _run, go())

    def test_set_consent_status_invalid_value_raises(self):
        pool = make_pool()
        reg = HubRegistry(pool)
        with self.assertRaises(ValueError):
            _run(reg.set_consent_status(new_uuid(), "bogus"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

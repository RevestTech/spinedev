"""Outbound audit webhook tests (#7).

Three things the test pass MUST cover:

1. Payload shape stays stable across releases (it's a public contract
   for customer integrations).
2. HMAC signature is correct and verifiable with stdlib hmac.
3. Delivery never raises into the audit pipeline — webhook problems
   stay webhook problems.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from tron.services import audit_webhook as wh
from tron.services.audit_webhook import (
    SCHEMA_VERSION,
    _build_payload,
    fire_audit_webhook,
    make_test_signature,
)


def _make_audit(**overrides):
    base = dict(
        id=uuid4(),
        status="completed",
        started_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 24, 10, 0, 30, tzinfo=timezone.utc),
        findings_total=5,
        findings_critical=1,
        findings_high=2,
        findings_medium=1,
        findings_low=1,
        diff_files_json=None,
        diff_base_ref=None,
        diff_head_ref=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_project(**overrides):
    base = dict(
        id=uuid4(),
        name="acme",
        audit_webhook_url="https://example.com/hook",
        audit_webhook_secret_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Payload shape ─────────────────────────────────────────────────────────


class TestPayloadShape:
    def test_payload_includes_versioned_envelope(self):
        audit = _make_audit()
        project = _make_project()
        payload = _build_payload(event="audit.completed", audit=audit, project=project)

        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["event"] == "audit.completed"
        assert payload["audit_run_id"] == str(audit.id)
        assert payload["project_id"] == str(project.id)
        assert payload["project_name"] == "acme"
        assert payload["status"] == "completed"
        assert payload["duration_seconds"] == 30.0

    def test_findings_section_is_complete(self):
        audit = _make_audit(
            findings_total=10,
            findings_critical=3,
            findings_high=4,
            findings_medium=2,
            findings_low=1,
        )
        payload = _build_payload(
            event="audit.completed", audit=audit, project=_make_project()
        )
        assert payload["findings"] == {
            "total": 10, "critical": 3, "high": 4, "medium": 2, "low": 1,
        }

    def test_diff_block_present_only_for_diff_audits(self):
        full = _build_payload(
            event="audit.completed", audit=_make_audit(),
            project=_make_project(),
        )
        assert full["diff"] is None

        diff = _build_payload(
            event="audit.completed",
            audit=_make_audit(
                diff_files_json=["src/a.py", "src/b.py"],
                diff_base_ref="main",
                diff_head_ref="feature/x",
            ),
            project=_make_project(),
        )
        assert diff["diff"] == {
            "base_ref": "main", "head_ref": "feature/x", "files_count": 2,
        }

    def test_findings_default_to_zero_when_columns_are_none(self):
        # Defensive: a row written by an older code path may have NULLs
        # in the count columns. Webhook should not crash.
        audit = _make_audit(
            findings_total=None, findings_critical=None,
            findings_high=None, findings_medium=None, findings_low=None,
        )
        payload = _build_payload(
            event="audit.failed", audit=audit, project=_make_project()
        )
        assert payload["findings"]["total"] == 0


# ── HMAC signing ──────────────────────────────────────────────────────────


class TestSigning:
    def test_signature_is_deterministic_and_verifiable(self):
        secret = "shared-secret-abc"
        body = b'{"hello": "world"}'

        sig = make_test_signature(body, secret)
        assert sig.startswith("sha256=")

        # Receiver-side verification using stdlib only.
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(sig, expected)

    def test_signature_changes_with_body(self):
        s1 = make_test_signature(b"a", "secret")
        s2 = make_test_signature(b"b", "secret")
        assert s1 != s2

    def test_signature_changes_with_secret(self):
        s1 = make_test_signature(b"hello", "secret-1")
        s2 = make_test_signature(b"hello", "secret-2")
        assert s1 != s2


# ── Delivery + retry behaviour ────────────────────────────────────────────


class TestDelivery:
    @pytest.mark.asyncio
    async def test_no_url_means_silent_skip(self):
        # Project without audit_webhook_url returns False with no I/O.
        project = _make_project(audit_webhook_url=None)
        ok = await fire_audit_webhook(
            event="audit.completed",
            audit=_make_audit(),
            project=project,
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_2xx_returns_true(self):
        project = _make_project()

        async def fake_post(self, url, content, headers):
            return httpx.Response(204)

        with patch.object(httpx.AsyncClient, "post", new=fake_post):
            ok = await fire_audit_webhook(
                event="audit.completed",
                audit=_make_audit(),
                project=project,
            )
        assert ok is True

    @pytest.mark.asyncio
    async def test_4xx_does_not_retry(self):
        project = _make_project()
        call_count = {"n": 0}

        async def fake_post(self, url, content, headers):
            call_count["n"] += 1
            return httpx.Response(400, text="bad request")

        with patch.object(httpx.AsyncClient, "post", new=fake_post):
            ok = await fire_audit_webhook(
                event="audit.completed",
                audit=_make_audit(),
                project=project,
            )
        assert ok is False
        # 4xx is the receiver's fault — single attempt.
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_signature_added_when_secret_present(self):
        captured_headers = {}

        async def fake_post(self, url, content, headers):
            captured_headers.update(headers)
            return httpx.Response(200)

        project = _make_project(audit_webhook_secret_id="hooks/audit-signing")

        with patch.object(httpx.AsyncClient, "post", new=fake_post), \
             patch.object(wh, "_REQUEST_TIMEOUT_SECONDS", 1.0):
            ok = await fire_audit_webhook(
                event="audit.completed",
                audit=_make_audit(),
                project=project,
                secrets={"hooks/audit-signing": "the-shared-secret"},
            )

        assert ok is True
        assert captured_headers.get("X-Tron-Signature", "").startswith("sha256=")
        assert captured_headers.get("X-Tron-Event") == "audit.completed"
        assert captured_headers.get("X-Tron-Schema-Version") == str(SCHEMA_VERSION)

    @pytest.mark.asyncio
    async def test_missing_secret_delivers_unsigned_with_warning(self, caplog):
        # Configured to sign but secret not in dict — better delivered
        # unsigned than dropped. Loud warning so ops can fix the misconfig.
        import logging

        captured_headers = {}

        async def fake_post(self, url, content, headers):
            captured_headers.update(headers)
            return httpx.Response(200)

        project = _make_project(audit_webhook_secret_id="hooks/missing")

        # Pin the level on the specific logger so caplog catches it under
        # pytest's default WARNING capture configuration.
        with caplog.at_level(logging.WARNING, logger="tron.services.audit_webhook"), \
             patch.object(httpx.AsyncClient, "post", new=fake_post):
            ok = await fire_audit_webhook(
                event="audit.completed",
                audit=_make_audit(),
                project=project,
                secrets={},  # no entry for hooks/missing
            )

        assert ok is True
        assert "X-Tron-Signature" not in captured_headers
        # Either "UNSIGNED" appears in a warning OR the no-signature header
        # outcome alone is enough proof.
        # Belt-and-braces: assert at least one warning was emitted.
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("UNSIGNED" in m for m in warning_msgs), (
            f"expected UNSIGNED warning, got warnings: {warning_msgs!r}"
        )

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_false(self):
        # Anything that raises must NOT propagate into the audit flow.
        async def boom(self, url, content, headers):
            raise RuntimeError("network died")

        project = _make_project()
        with patch.object(httpx.AsyncClient, "post", new=boom):
            ok = await fire_audit_webhook(
                event="audit.completed",
                audit=_make_audit(),
                project=project,
            )
        assert ok is False

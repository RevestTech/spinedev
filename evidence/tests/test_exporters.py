"""Exporter tests — credentials mocked, no real HTTP."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from evidence._types import EvidencePayload
from evidence.exporters.drata import DrataExporter
from evidence.exporters.secureframe import SecureframeExporter
from evidence.exporters.strikegraph import StrikeGraphExporter
from evidence.exporters.thoropass import ThoropassExporter
from evidence.exporters.tugboat import TugboatExporter
from evidence.exporters.vanta import VantaExporter


_TS = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


def _payload(framework="SOC2", control_id="CC6.1", evidence_type="access_review"):
    return EvidencePayload(
        framework=framework, control_id=control_id, evidence_type=evidence_type,
        source_audit_record_id="11111111-1111-1111-1111-111111111111",
        collected_at=_TS, body={"k": "v"},
    )


def _fake_http_factory(status: int = 202):
    """Returns an http_client that captures the (url, body, headers, timeout)."""
    captured = {}

    def _client(url, body, headers, timeout):
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        captured["timeout"] = timeout
        return status, b""

    return _client, captured


def _fake_secret_factory(api_key: str = "test-key"):
    """Return only the api_key path; raise for the optional api_url path
    so the exporter falls back to DEFAULT_URL (matches typical setup
    where the URL override is absent from the vault)."""

    def _fetch(path: str) -> str:
        if path.endswith("/api_url"):
            raise RuntimeError("no url override in test vault")
        return api_key

    return _fetch


class VantaExporterTests(unittest.TestCase):
    def test_send_success_with_mocked_secret_and_http(self):
        exp = VantaExporter()
        client, captured = _fake_http_factory(202)
        with mock.patch("evidence.exporters._base._fetch_secret",
                        side_effect=_fake_secret_factory("vanta-key")), \
             mock.patch("evidence.exporters._base._log_export"):
            result = exp.send([_payload()], http_client=client)
        self.assertTrue(result.success)
        self.assertEqual(result.records_count, 1)
        self.assertEqual(result.response_status, 202)
        self.assertEqual(result.exporter, "vanta")
        # Confirm we fell back to DEFAULT_URL (test vault has no override).
        self.assertEqual(result.target_url, VantaExporter.DEFAULT_URL)
        # Confirm Bearer auth + JSON content type.
        self.assertEqual(captured["headers"]["Authorization"], "Bearer vanta-key")
        self.assertIn("application/json", captured["headers"]["Content-Type"])
        # Confirm the body uses camelCase keys per Vanta convention.
        body = json.loads(captured["body"])
        self.assertIn("evidence_records", body)
        self.assertEqual(body["evidence_records"][0]["controlId"], "CC6.1")

    def test_send_http_error_records_failure(self):
        exp = VantaExporter()
        client, _ = _fake_http_factory(500)
        with mock.patch("evidence.exporters._base._fetch_secret",
                        side_effect=_fake_secret_factory("vanta-key")), \
             mock.patch("evidence.exporters._base._log_export"):
            result = exp.send([_payload()], http_client=client)
        self.assertFalse(result.success)
        self.assertEqual(result.response_status, 500)


class DrataExporterTests(unittest.TestCase):
    def test_drata_body_shape(self):
        exp = DrataExporter()
        client, captured = _fake_http_factory(200)
        with mock.patch("evidence.exporters._base._fetch_secret",
                        side_effect=_fake_secret_factory("drata-key")), \
             mock.patch("evidence.exporters._base._log_export"):
            result = exp.send([_payload()], http_client=client)
        self.assertTrue(result.success)
        body = json.loads(captured["body"])
        self.assertIn("evidence", body)
        self.assertEqual(body["evidence"][0]["control_id"], "CC6.1")


class SecureframeExporterTests(unittest.TestCase):
    def test_groups_by_framework_control(self):
        exp = SecureframeExporter()
        client, captured = _fake_http_factory(201)
        payloads = [_payload(control_id="CC6.1"),
                    _payload(control_id="CC6.1"),
                    _payload(control_id="CC1.4")]
        with mock.patch("evidence.exporters._base._fetch_secret",
                        side_effect=_fake_secret_factory("sf-key")), \
             mock.patch("evidence.exporters._base._log_export"):
            result = exp.send(payloads, http_client=client)
        self.assertTrue(result.success)
        body = json.loads(captured["body"])
        # Two collections (one per control_id) — confirms grouping logic.
        collections = body["evidence_collections"]
        self.assertEqual(len(collections), 2)
        sizes = sorted(len(c["items"]) for c in collections)
        self.assertEqual(sizes, [1, 2])


class StubExporterTests(unittest.TestCase):
    """Tugboat / Strike Graph / Thoropass must refuse send() at v1.0."""

    def test_tugboat_send_refuses(self):
        with mock.patch("evidence.exporters._base._fetch_secret",
                        return_value="key"):
            with self.assertRaises(NotImplementedError) as cm:
                TugboatExporter().send([_payload()])
        self.assertIn("v1.1+", str(cm.exception))

    def test_strikegraph_send_refuses(self):
        with mock.patch("evidence.exporters._base._fetch_secret",
                        return_value="key"):
            with self.assertRaises(NotImplementedError):
                StrikeGraphExporter().send([_payload()])

    def test_thoropass_send_refuses(self):
        with mock.patch("evidence.exporters._base._fetch_secret",
                        return_value="key"):
            with self.assertRaises(NotImplementedError):
                ThoropassExporter().send([_payload()])

    def test_stubs_still_have_default_url_and_render(self):
        """Confirms the vault + render plumbing IS wired at v1.0."""
        for cls in (TugboatExporter, StrikeGraphExporter, ThoropassExporter):
            exp = cls()
            self.assertTrue(exp.DEFAULT_URL.startswith("https://"))
            body = exp._render_batch([_payload()])
            decoded = json.loads(body)
            self.assertIn("evidence", decoded)
            self.assertTrue(decoded["spine_meta"]["stub"])

    def test_vault_path_convention(self):
        """Each stub points at the canonical evidence/<name>/api_key path."""
        for cls, name in ((TugboatExporter, "tugboat"),
                          (StrikeGraphExporter, "strikegraph"),
                          (ThoropassExporter, "thoropass")):
            exp = cls()
            self.assertEqual(exp.vault_prefix, f"evidence/{name}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""
Unit tests for Alertmanager → Slack webhook receiver (tron.api.routes.alerts).

Covers:
  - Webhook URL resolution: env var wins, then vault, then neither.
  - Payload translation: severity inference, emoji/color, label fields.
  - Route dispatch: /alerts, /alerts/critical, /alerts/warning pick the right
    severity.
  - Graceful degradation: returns 200 with forwarded=False when no webhook is
    configured (so Alertmanager doesn't retry-storm).
  - Graceful degradation: non-JSON / non-object bodies return 200.
  - Forwarder uses the resolved URL and tolerates non-2xx / exceptions.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from tron.api.routes import alerts as alerts_module


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(alerts_module.router)
    return app


def _sample_am_payload(
    *,
    status: str = "firing",
    alertname: str = "HighErrorRate",
    severity: str | None = "critical",
    extra_labels: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    labels: Dict[str, str] = {"alertname": alertname}
    if severity is not None:
        labels["severity"] = severity
    if extra_labels:
        labels.update(extra_labels)
    return {
        "version": "4",
        "status": status,
        "receiver": "default",
        "groupLabels": {"alertname": alertname},
        "commonLabels": labels,
        "commonAnnotations": {"summary": "error rate spiked"},
        "alerts": [
            {
                "status": status,
                "labels": labels,
                "annotations": {"summary": "error rate spiked"},
                "startsAt": "2026-04-23T10:00:00Z",
            }
        ],
    }


@pytest.fixture(autouse=True)
def _reset_alerts_state():
    """Each test starts with a clean webhook-cache + HTTP client slot."""
    alerts_module._reset_cache_for_tests()
    alerts_module._http_client = None
    yield
    alerts_module._reset_cache_for_tests()
    alerts_module._http_client = None


# ── Webhook URL resolution ───────────────────────────────────────────


class TestResolveSlackWebhookUrl:

    async def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/env")
        # Vault call must not happen when the env var is set.
        with patch.object(alerts_module, "get_secret", new_callable=AsyncMock) as mock_vault:
            url = await alerts_module._resolve_slack_webhook_url()
        assert url == "https://hooks.slack.test/env"
        mock_vault.assert_not_called()

    async def test_falls_back_to_vault(self, monkeypatch):
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        with patch.object(
            alerts_module,
            "get_secret",
            new=AsyncMock(return_value="https://hooks.slack.test/vault"),
        ):
            url = await alerts_module._resolve_slack_webhook_url()
        assert url == "https://hooks.slack.test/vault"

    async def test_vault_missing_returns_none(self, monkeypatch):
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        with patch.object(
            alerts_module,
            "get_secret",
            new=AsyncMock(side_effect=KeyError("alerts/slack-webhook")),
        ):
            url = await alerts_module._resolve_slack_webhook_url()
        assert url is None

    async def test_vault_unexpected_error_is_swallowed(self, monkeypatch):
        """Unknown vault errors must not prevent the API from booting."""
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        with patch.object(
            alerts_module,
            "get_secret",
            new=AsyncMock(side_effect=RuntimeError("vault down")),
        ):
            url = await alerts_module._resolve_slack_webhook_url()
        assert url is None

    async def test_cache_prevents_repeated_lookups(self, monkeypatch):
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        mock_vault = AsyncMock(return_value="https://hooks.slack.test/vault")
        with patch.object(alerts_module, "get_secret", new=mock_vault):
            await alerts_module._resolve_slack_webhook_url()
            await alerts_module._resolve_slack_webhook_url()
            await alerts_module._resolve_slack_webhook_url()
        assert mock_vault.await_count == 1


# ── Payload translation ──────────────────────────────────────────────


class TestBuildSlackPayload:

    def test_header_uses_group_alertname_and_status(self):
        p = _sample_am_payload(alertname="DiskFull", severity="warning", status="firing")
        out = alerts_module._build_slack_payload(p)
        assert "FIRING" in out["text"]
        assert "DiskFull" in out["text"]

    def test_route_severity_wins_over_label_severity(self):
        p = _sample_am_payload(severity="info")
        out = alerts_module._build_slack_payload(p, route_severity="critical")
        # Critical severity → red attachment color
        assert out["attachments"][0]["color"] == alerts_module._SEVERITY_COLOR["critical"]
        assert alerts_module._SEVERITY_EMOJI["critical"] in out["text"]

    def test_label_severity_used_when_no_route_severity(self):
        p = _sample_am_payload(severity="warning")
        out = alerts_module._build_slack_payload(p, route_severity=None)
        assert out["attachments"][0]["color"] == alerts_module._SEVERITY_COLOR["warning"]

    def test_infers_worst_alert_severity_when_group_lacks_one(self):
        p = _sample_am_payload(severity=None)
        # Replace alerts list with mixed severities.
        p["alerts"] = [
            {"labels": {"alertname": "a", "severity": "info"}, "annotations": {}},
            {"labels": {"alertname": "b", "severity": "warning"}, "annotations": {}},
            {"labels": {"alertname": "c", "severity": "critical"}, "annotations": {}},
        ]
        out = alerts_module._build_slack_payload(p, route_severity=None)
        assert out["attachments"][0]["color"] == alerts_module._SEVERITY_COLOR["critical"]

    def test_defaults_to_info_when_nothing_known(self):
        p = _sample_am_payload(severity=None)
        # No alerts at all — must not crash, must default to info.
        p["alerts"] = []
        out = alerts_module._build_slack_payload(p, route_severity=None)
        assert out["attachments"] == []
        # Header still uses the info emoji fallback.
        assert alerts_module._SEVERITY_EMOJI["info"] in out["text"]

    def test_attachment_includes_useful_label_fields(self):
        p = _sample_am_payload(
            severity="critical",
            extra_labels={"instance": "api-1", "job": "tron-api", "service": "alerts"},
        )
        out = alerts_module._build_slack_payload(p, route_severity="critical")
        att = out["attachments"][0]
        field_titles = {f["title"] for f in att["fields"]}
        assert {"severity", "instance", "job", "service"}.issubset(field_titles)

    def test_missing_annotations_does_not_crash(self):
        p = {
            "status": "firing",
            "groupLabels": {"alertname": "X"},
            "alerts": [{"labels": {"alertname": "X"}}],  # no annotations key
        }
        out = alerts_module._build_slack_payload(p, route_severity=None)
        assert out["attachments"][0]["text"] == ""


# ── Route dispatch + graceful degradation ────────────────────────────


class TestRouteDispatch:

    def test_default_route_returns_200_and_forwards(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/x")
        app = _make_app()

        mock_resp = MagicMock(status_code=200, text="ok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch.object(alerts_module, "_get_http", new=AsyncMock(return_value=mock_http)):
            with TestClient(app) as c:
                r = c.post("/alerts", json=_sample_am_payload())

        assert r.status_code == 200
        assert r.json() == {"status": "ok", "forwarded": True}
        mock_http.post.assert_awaited_once()
        # URL used must be the env var value
        args, kwargs = mock_http.post.call_args
        assert args[0] == "https://hooks.slack.test/x"
        # And the body must be the Slack-formatted dict, not the raw AM payload
        assert "attachments" in kwargs["json"]

    def test_critical_route_passes_route_severity(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/x")
        app = _make_app()

        captured: Dict[str, Any] = {}

        async def fake_forward(payload):
            captured["payload"] = payload
            return True

        with patch.object(alerts_module, "_forward_to_slack", new=fake_forward):
            with TestClient(app) as c:
                # Even with no severity on the alert, the /critical route must
                # colour it critical.
                r = c.post("/alerts/critical", json=_sample_am_payload(severity=None))

        assert r.status_code == 200
        assert captured["payload"]["attachments"][0]["color"] == alerts_module._SEVERITY_COLOR["critical"]

    def test_warning_route_passes_route_severity(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/x")
        app = _make_app()

        captured: Dict[str, Any] = {}

        async def fake_forward(payload):
            captured["payload"] = payload
            return True

        with patch.object(alerts_module, "_forward_to_slack", new=fake_forward):
            with TestClient(app) as c:
                r = c.post("/alerts/warning", json=_sample_am_payload(severity=None))

        assert r.status_code == 200
        assert captured["payload"]["attachments"][0]["color"] == alerts_module._SEVERITY_COLOR["warning"]

    def test_missing_webhook_returns_200_not_forwarded(self, monkeypatch, caplog):
        """Misconfig must not cause Alertmanager to retry-storm."""
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        app = _make_app()

        with patch.object(
            alerts_module,
            "get_secret",
            new=AsyncMock(side_effect=KeyError("alerts/slack-webhook")),
        ):
            with TestClient(app) as c:
                with caplog.at_level("WARNING", logger=alerts_module.logger.name):
                    r = c.post("/alerts", json=_sample_am_payload())

        assert r.status_code == 200
        assert r.json() == {"status": "ok", "forwarded": False}
        # Verified in logs so the drop is visible (see alerts.py docstring).
        assert any(
            "no Slack webhook configured" in rec.getMessage()
            for rec in caplog.records
        )

    def test_invalid_json_returns_200_ignored(self):
        app = _make_app()
        with TestClient(app) as c:
            r = c.post(
                "/alerts",
                data="not-json",
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ignored"
        assert body["reason"] == "invalid_json"

    def test_non_object_body_returns_200_ignored(self):
        app = _make_app()
        with TestClient(app) as c:
            r = c.post("/alerts", json=["not", "an", "object"])
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ignored"
        assert body["reason"] == "not_object"


# ── Forwarder behaviour ──────────────────────────────────────────────


class TestForwardToSlack:

    async def test_returns_false_when_slack_rejects(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/x")

        mock_resp = MagicMock(status_code=500, text="slack exploded")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        with patch.object(alerts_module, "_get_http", new=AsyncMock(return_value=mock_http)):
            ok = await alerts_module._forward_to_slack({"text": "x"})

        assert ok is False

    async def test_returns_false_on_exception(self, monkeypatch):
        monkeypatch.setenv("TRON_ALERT_SLACK_WEBHOOK", "https://hooks.slack.test/x")

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=RuntimeError("network down"))

        with patch.object(alerts_module, "_get_http", new=AsyncMock(return_value=mock_http)):
            ok = await alerts_module._forward_to_slack({"text": "x"})

        assert ok is False

    async def test_returns_false_when_no_webhook(self, monkeypatch):
        monkeypatch.delenv("TRON_ALERT_SLACK_WEBHOOK", raising=False)
        with patch.object(
            alerts_module,
            "get_secret",
            new=AsyncMock(side_effect=KeyError("alerts/slack-webhook")),
        ):
            ok = await alerts_module._forward_to_slack({"text": "x"})
        assert ok is False

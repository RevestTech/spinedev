"""Wave-1 (v3) channel tests for shared/notify/channels.py.

Covers:
  * Vault-only credential resolution (no env-var fallback).
  * Slack constructor pulls from vault path notify/slack/webhook_url.
  * Scaffold channels (SMS / WhatsApp / Teams / PagerDuty) construct
    cleanly + raise NotImplementedError from send().
  * Persistent rate-limit helpers are exposed via shared.notify.rate_limit.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from shared.notify import channels
from shared.notify.channels import (EmailChannel, NoOpChannel, PagerDutyChannel,
                                    SlackChannel, SMSChannel, TeamsChannel,
                                    WhatsAppChannel)
from shared.notify.notifier import NotificationEvent


def _event() -> NotificationEvent:
    return NotificationEvent(
        event_type="verify_failed", project_id="1",
        project_name="test", phase="intake", summary="x",
    )


class VaultResolutionTests(unittest.TestCase):
    """Channel constructors must use shared.secrets paths, not env vars
    or ~/.spine/*.yaml files."""

    def test_slack_pulls_webhook_from_vault(self) -> None:
        with patch.object(channels, "_fetch_secret",
                          return_value="https://hooks.slack.test/abc") as m:
            ch = SlackChannel()
        self.assertEqual(ch.webhook_url, "https://hooks.slack.test/abc")
        m.assert_called_once_with("notify/slack/webhook_url")

    def test_slack_explicit_kwarg_wins_over_vault(self) -> None:
        with patch.object(channels, "_fetch_secret",
                          return_value="https://vault.slack.test/xyz") as m:
            ch = SlackChannel(webhook_url="https://explicit.test/q")
        self.assertEqual(ch.webhook_url, "https://explicit.test/q")
        m.assert_not_called()

    def test_email_password_resolves_from_vault(self) -> None:
        with patch.object(channels, "_fetch_secret",
                          return_value="hunter2") as m:
            ch = EmailChannel(host="smtp.test", username="u", sender="s",
                              recipients=["a@b.test"])
        self.assertEqual(ch.password, "hunter2")
        m.assert_called_once_with("notify/smtp/password")

    def test_email_does_not_load_yaml_file(self) -> None:
        """The legacy ~/.spine/notify-smtp.yaml loader is gone."""
        # No reference to a YAML file reader should exist in this code path
        # (we patch _fetch_secret to return None to simulate missing creds).
        with patch.object(channels, "_fetch_secret", return_value=None):
            ch = EmailChannel(host="smtp.test", username="u", sender="s",
                              recipients=["a@b.test"])
        self.assertIsNone(ch.password)


class ScaffoldChannelTests(unittest.TestCase):
    """SMS / WhatsApp / Teams / PagerDuty are config-only Wave-1 scaffolds."""

    def setUp(self) -> None:
        # Suppress real vault calls for every scaffold ctor.
        patcher = patch.object(channels, "_fetch_secret", return_value=None)
        self.mock_fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def test_sms_construct_and_send_raises(self) -> None:
        ch = SMSChannel(recipients=["+15551112222"])
        self.assertEqual(ch.name, "sms")
        self.assertEqual(ch.recipients, ["+15551112222"])
        with self.assertRaises(NotImplementedError) as ctx:
            ch.send(_event())
        self.assertIn("v1.1+", str(ctx.exception))

    def test_whatsapp_construct_and_send_raises(self) -> None:
        ch = WhatsAppChannel(recipients=["whatsapp:+15551112222"])
        self.assertEqual(ch.name, "whatsapp")
        with self.assertRaises(NotImplementedError):
            ch.send(_event())

    def test_teams_construct_and_send_raises(self) -> None:
        ch = TeamsChannel()
        self.assertEqual(ch.name, "teams")
        with self.assertRaises(NotImplementedError):
            ch.send(_event())

    def test_pagerduty_construct_and_send_raises(self) -> None:
        ch = PagerDutyChannel(dedup_strategy="event_then_project")
        self.assertEqual(ch.name, "pagerduty")
        self.assertEqual(ch.dedup_strategy, "event_then_project")
        with self.assertRaises(NotImplementedError):
            ch.send(_event())

    def test_sms_vault_paths(self) -> None:
        """All three Twilio creds resolve via shared.secrets paths."""
        with patch.object(channels, "_fetch_secret",
                          side_effect=lambda path: f"VAL:{path}") as m:
            ch = SMSChannel()
        # from_number, account_sid, auth_token all fetched.
        called = {c.args[0] for c in m.call_args_list}
        self.assertIn("notify/twilio/from_number", called)
        self.assertIn("notify/twilio/account_sid", called)
        self.assertIn("notify/twilio/auth_token", called)
        self.assertEqual(ch.account_sid, "VAL:notify/twilio/account_sid")

    def test_pagerduty_vault_path(self) -> None:
        with patch.object(channels, "_fetch_secret",
                          return_value="32-char-hex-key") as m:
            ch = PagerDutyChannel()
        m.assert_called_once_with("notify/pagerduty/routing_key")
        self.assertEqual(ch.routing_key, "32-char-hex-key")


class RateLimitModuleTests(unittest.TestCase):
    """The persistent rate-limit module exposes check/mark."""

    def test_module_importable(self) -> None:
        from shared.notify import rate_limit
        self.assertTrue(callable(rate_limit.check))
        self.assertTrue(callable(rate_limit.mark))

    def test_check_returns_false_when_db_unreachable(self) -> None:
        """Fail-open posture: DB error -> permissive (don't suppress send)."""
        from shared.notify import rate_limit
        with patch.object(rate_limit, "_psql_bound",
                          side_effect=RuntimeError("no db")):
            self.assertFalse(
                rate_limit.check(
                    channel="slack", event_type="verify_failed",
                    key="x", window_seconds=300,
                ),
            )

    def test_mark_swallows_db_errors(self) -> None:
        from shared.notify import rate_limit
        with patch.object(rate_limit, "_psql_bound",
                          side_effect=RuntimeError("no db")):
            # Should not raise.
            rate_limit.mark(
                channel="slack", event_type="verify_failed",
                key="x", window_seconds=300,
            )

    def test_flag_name_shape(self) -> None:
        from shared.notify.rate_limit import _flag_name
        self.assertEqual(
            _flag_name("slack", "verify_failed"),
            "notify.slack.verify_failed",
        )

    def test_period_bucket_aligns(self) -> None:
        """Two ``now`` values inside the same window land in the same bucket."""
        from datetime import datetime, timezone, timedelta

        from shared.notify.rate_limit import _period_for

        t0 = datetime(2026, 5, 17, 12, 0, 5, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=200)  # still inside a 300s window
        s0, e0 = _period_for(t0, 300)
        s1, e1 = _period_for(t1, 300)
        self.assertEqual(s0, s1)
        self.assertEqual(e0, e1)


class FactoryDispatchTests(unittest.TestCase):
    """``_build_channel`` recognises the new scaffold kinds."""

    def test_factory_dispatches_to_new_channels(self) -> None:
        from shared.notify.notifier import _build_channel

        with patch.object(channels, "_fetch_secret", return_value=None):
            for kind, expected in (
                ("sms", "sms"),
                ("whatsapp", "whatsapp"),
                ("teams", "teams"),
                ("pagerduty", "pagerduty"),
            ):
                ch = _build_channel({"type": kind, "enabled": True})
                self.assertIsNotNone(ch, f"factory dropped kind={kind!r}")
                self.assertEqual(ch.name, expected)


if __name__ == "__main__":
    unittest.main()

"""Compatibility-shim regression tests for ``shared/integrations/`` FIX2.

Asserts that downstream callers — ``voice/twilio_adapter.py``,
``migration/onboarding.py``, ``shared/notify/channels.py``,
``evidence/exporters/_base.py`` — keep working unchanged after the
canonical extraction. The hard constraint stated in Wave 3.5 FIX2 was
ZERO public API breakage.

If any of these assertions fail it means a downstream caller's import
path got broken by the extraction; the offending callsite must be
restored before merging the FIX2 work.
"""

from __future__ import annotations

import asyncio


# ---------------------------------------------------------------------------
# voice/twilio_adapter.py — preserved imports for voice/ tests
# ---------------------------------------------------------------------------


def test_voice_shim_exposes_all_voice_tests_imports() -> None:
    """voice/tests/test_voice_scaffold.py imports these by name."""
    from voice.twilio_adapter import (  # noqa: F401
        EMPTY_TWIML,
        TwilioVoiceAdapter,
        TwilioVoiceConfig,
        VAULT_PATH_ACCOUNT_SID,
        VAULT_PATH_AUTH_TOKEN,
        VAULT_PATH_FROM_NUMBER,
        VAULT_PATH_INCIDENT_NUMBER,
    )

    # They must be the SAME objects as the canonical module exports
    # (re-export, not a parallel implementation).
    from shared.integrations import twilio as canonical

    assert TwilioVoiceAdapter is canonical.TwilioVoiceAdapter
    assert TwilioVoiceConfig is canonical.TwilioVoiceConfig
    assert EMPTY_TWIML == canonical.EMPTY_TWIML
    assert VAULT_PATH_ACCOUNT_SID == canonical.VAULT_PATH_ACCOUNT_SID
    assert VAULT_PATH_AUTH_TOKEN == canonical.VAULT_PATH_AUTH_TOKEN
    assert VAULT_PATH_FROM_NUMBER == canonical.VAULT_PATH_FROM_NUMBER
    assert VAULT_PATH_INCIDENT_NUMBER == canonical.VAULT_PATH_INCIDENT_NUMBER


def test_voice_shim_route_call_still_raises_v1_1_notimpl() -> None:
    """The voice/ scaffold must keep its v1.1+ contract."""
    import pytest

    from voice.twilio_adapter import TwilioVoiceAdapter

    adapter = TwilioVoiceAdapter()
    with pytest.raises(NotImplementedError) as exc:
        adapter.route_call({"CallSid": "CA1"})
    assert "v1.1+" in str(exc.value)


# ---------------------------------------------------------------------------
# migration/onboarding.py — preserved imports for migration/ tests
# ---------------------------------------------------------------------------


def test_onboarding_shim_exposes_connectors() -> None:
    """migration/tests/test_onboarding.py imports these by name."""
    from migration.onboarding import (  # noqa: F401
        GitHubConnector,
        HttpClient,
        LinearConnector,
        OnboardingDispatcher,
        WorkItemMapping,
        WorkItemSink,
    )

    from shared.integrations import github as gh_mod
    from shared.integrations import linear as lin_mod

    # GitHubConnector + LinearConnector are now thin re-exports.
    assert GitHubConnector is gh_mod.GitHubConnector
    assert LinearConnector is lin_mod.LinearConnector


def test_onboarding_dispatcher_unchanged() -> None:
    """OnboardingDispatcher + WorkItemMapping stay in migration/."""
    from migration.onboarding import OnboardingDispatcher, WorkItemMapping

    # These types continue to live in migration/onboarding (they're the
    # Spine-internal sink contract, not connector plumbing).
    assert OnboardingDispatcher.__module__ == "migration.onboarding"
    assert WorkItemMapping.__module__ == "migration.onboarding"


# ---------------------------------------------------------------------------
# shared/notify/channels.py — preserved channel surface
# ---------------------------------------------------------------------------


def test_notify_channels_still_export_scaffold_classes() -> None:
    """shared/notify/tests/test_channels_v3.py imports these by name."""
    from shared.notify.channels import (  # noqa: F401
        PagerDutyChannel,
        SMSChannel,
        TeamsChannel,
        WhatsAppChannel,
    )

    # Construction must still work without raising (vault paths are stubs).
    import unittest.mock
    import shared.notify.channels as ch_mod

    with unittest.mock.patch.object(ch_mod, "_fetch_secret", return_value=None):
        assert SMSChannel().name == "sms"
        assert WhatsAppChannel().name == "whatsapp"
        assert TeamsChannel().name == "teams"
        assert PagerDutyChannel().name == "pagerduty"


def test_notify_channels_send_still_raises_v1_1_notimpl() -> None:
    """Scaffold contract — send() raises NotImplementedError until v1.1+."""
    import unittest.mock

    import pytest

    import shared.notify.channels as ch_mod
    from shared.notify.channels import SMSChannel
    from shared.notify.notifier import NotificationEvent

    with unittest.mock.patch.object(ch_mod, "_fetch_secret", return_value=None):
        ch = SMSChannel(recipients=["+15551112222"])
    with pytest.raises(NotImplementedError) as exc:
        ch.send(NotificationEvent(
            event_type="verify_failed", project_id="1",
            project_name="x", phase="intake", summary="y",
        ))
    assert "v1.1+" in str(exc.value)


# ---------------------------------------------------------------------------
# evidence/exporters/_base.py — preserved exporter base
# ---------------------------------------------------------------------------


def test_evidence_base_exporter_still_importable() -> None:
    """evidence/tests/test_exporters.py constructs BaseExporter subclasses."""
    from evidence.exporters._base import BaseExporter, EVIDENCE_VAULT_PREFIX

    assert EVIDENCE_VAULT_PREFIX == "evidence"
    # The class API is unchanged (subclasses set EXPORTER_NAME / DEFAULT_URL).
    assert hasattr(BaseExporter, "send")
    assert hasattr(BaseExporter, "_api_key")
    assert hasattr(BaseExporter, "_target_url")
    assert hasattr(BaseExporter, "_render_batch")


# ---------------------------------------------------------------------------
# shared/mcp/tools/integrations.py — dispatch path still works
# ---------------------------------------------------------------------------


def test_mcp_tool_dispatch_finds_canonical_adapter(monkeypatch) -> None:
    """The MCP test_connection tool should find ``shared.integrations.<name>``."""
    import importlib

    import shared.integrations.base as base_mod

    async def _fake(path: str) -> str:
        return "secret-value"

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)

    # The MCP tool imports adapter modules dynamically; force-resolve all 5.
    for name in ("twilio", "teams", "pagerduty", "github", "linear"):
        mod = importlib.import_module(f"shared.integrations.{name}")
        probe = getattr(mod, "test_connection", None)
        assert callable(probe)
        result = asyncio.run(probe())
        assert result.name == name

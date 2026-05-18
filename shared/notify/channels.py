"""Notification channel implementations (STORY-1.4.7).

Each channel exposes ``name`` + ``send(event) -> NotifyResult``. Transports
are lazy-imported inside ``send()`` so importing this module is cheap and
optional deps (``requests``, ``smtplib``, ``notify-send``/``osascript``) are
only required for channels actually used. Missing deps raise
``ChannelError`` with a remediation message — the Notifier turns that into
a per-channel failure without breaking the fan-out.

Wave 1 (v3) changes:

  * **Vault-only credentials (per V3 #9).** Channel credentials no longer
    come from ``~/.spine/notify-*.yaml`` files OR environment variables.
    Every secret value is fetched via ``shared.secrets.get_secret`` from
    the path scheme ``notify/<channel>/<field>`` — e.g.
    ``notify/slack/webhook_url``, ``notify/smtp/password``,
    ``notify/twilio/auth_token``. Non-secret config (host, port, sender,
    recipients) continues to live in the channel constructor kwargs OR
    in the org bundle's ``notification.channels`` block.

  * **Persistent rate-limit ledger (per V3 #6).** The legacy in-memory
    ``Notifier._rate_log`` dict only survived for the life of a daemon
    process — federation needs cross-process awareness. The new module
    ``rate_limit`` writes rate-limit checks/marks into
    ``spine_license.quota_usage`` (no new schema, no V33 migration). Each
    rate-limit key becomes a ``flag_name`` of the form
    ``notify.<channel>.<event_type>``; the period is the rate-limit
    window. Channels remain ignorant of this — the Notifier core handles
    the bookkeeping.

  * **New channel scaffolds (per V3 #6 — multi-medium fan-out).**
    SMS (Twilio), WhatsApp (Twilio), Teams, and PagerDuty have been
    added. The classes are wired (config + auth-via-vault + name +
    construction) but ``send()`` raises ``NotImplementedError('v1.1+')``
    for these four pending the production transport work. SMS/WhatsApp
    map to the same Twilio account; Teams uses Microsoft webhook URLs;
    PagerDuty uses the Events v2 API.

Wave 3.5 FIX2 — per-vendor vault paths + auth primitives now live at
:mod:`shared.integrations.{twilio,teams,pagerduty}`. The channel classes
below import those constants (rather than re-hardcoding them) so a
single grep across the repo shows every consumer of a given Twilio /
Teams / PagerDuty secret. The ``send()`` orchestration stays in this
module because it's notification-domain logic, not integration plumbing.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared.notify.notifier import NotificationEvent, NotifyResult

_log = logging.getLogger("spine.notify.channels")
_SEV = {"info": "[INFO]", "warning": "[WARN]", "critical": "[CRIT]"}


class ChannelError(RuntimeError):
    """Raised by channels for transport/config issues; surfaced by Notifier
    as ``NotifyResult(sent=False, error=...)``."""


def _fmt(event: NotificationEvent) -> str:
    line = (f"{_SEV.get(event.severity, '[?]')} {event.event_type}"
            f" project={event.project_name} ({event.project_id})"
            f" phase={event.phase}")
    if event.actor: line += f" actor={event.actor}"
    line += f" :: {event.summary}"
    if event.detail_url: line += f" [{event.detail_url}]"
    return line


def _fetch_secret(path: str) -> str | None:
    """Synchronous wrapper around ``shared.secrets.get_secret``.

    Channel constructors are sync (they may run inside an event loop in
    some daemons OR at module-import time in CLI scripts). When a default
    adapter is not configured, returns ``None`` rather than raising — the
    channel decides whether the missing credential is fatal.
    """
    try:
        from shared.secrets import SecretBackendError, SecretNotFound, get_secret
    except Exception as exc:  # noqa: BLE001
        _log.debug("shared.secrets unavailable: %s", exc)
        return None

    async def _go() -> str | None:
        try:
            return await get_secret(path)
        except SecretNotFound:
            return None
        except SecretBackendError as exc:
            _log.debug("no secret adapter for %s: %s", path, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — never crash channel ctor
            _log.warning("vault read failed for %s: %s", path, exc)
            return None

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Channel ctor invoked from inside a running loop — cannot
            # nest asyncio.run; return None and surface a clearer error
            # at send() time if the credential turns out to be required.
            _log.debug(
                "skipping vault fetch for %s — running event loop",
                path,
            )
            return None
    except RuntimeError:
        pass
    return asyncio.run(_go())


class StdoutChannel:  # debug / CI
    name = "stdout"
    def __init__(self, *, stream: str = "stdout") -> None:
        self._fh = sys.stderr if stream == "stderr" else sys.stdout
    def send(self, event: NotificationEvent) -> NotifyResult:
        print(_fmt(event), file=self._fh, flush=True)
        return NotifyResult(channel=self.name, sent=True)

class FileChannel:  # append-only JSONL log
    name = "file"
    def __init__(self, *, path: str | None = None) -> None:
        # File path is config, not a secret — non-vault path acceptable.
        # Default location stays under SPINE_HOME for visibility.
        self.path = Path(path or os.environ.get(
            "SPINE_NOTIFY_LOG",
            str(Path.home() / ".spine" / "notifications.jsonl"))).expanduser()
    def send(self, event: NotificationEvent) -> NotifyResult:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        except OSError as e:
            raise ChannelError(f"could not write {self.path}: {e}") from e
        return NotifyResult(channel=self.name, sent=True)

class SlackChannel:
    """Webhook URL resolves from arg → vault path ``notify/slack/webhook_url``."""
    name = "slack"
    def __init__(self, *, webhook_url: str | None = None,
                 timeout_seconds: int = 5) -> None:
        self.timeout = int(timeout_seconds)
        self.webhook_url = webhook_url or _fetch_secret("notify/slack/webhook_url")
    def send(self, event: NotificationEvent) -> NotifyResult:
        if not self.webhook_url:
            raise ChannelError(
                "slack: no webhook_url (arg or vault path "
                "notify/slack/webhook_url)")
        try: import requests  # noqa: PLC0415
        except ImportError as e:
            raise ChannelError("slack: `pip install requests` required") from e
        payload: dict[str, Any] = {"text": _fmt(event), "attachments": [{
            "color": {"info": "#36a64f", "warning": "#f2b400",
                      "critical": "#d50000"}.get(event.severity, "#888"),
            "fields": [{"title": "Project", "value": event.project_name, "short": True},
                       {"title": "Phase", "value": event.phase, "short": True}]}]}
        if event.detail_url:
            payload["attachments"][0]["title_link"] = event.detail_url
        try: resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            raise ChannelError(f"slack POST failed: {e}") from e
        if resp.status_code >= 300:
            raise ChannelError(f"slack non-2xx: {resp.status_code} {resp.text[:200]}")
        return NotifyResult(channel=self.name, sent=True)


class EmailChannel:
    """SMTP creds come from vault paths under ``notify/smtp/*``.

    Non-secret config (host, port, sender, recipients, use_tls) may be
    passed as kwargs OR read from the org bundle's notification block.
    Only ``password`` is treated as a vault-bound secret.
    """
    name = "email"
    def __init__(self, *, host: str | None = None, port: int = 587,
                 username: str | None = None, password: str | None = None,
                 sender: str | None = None, recipients: list[str] | None = None,
                 use_tls: bool = True, timeout_seconds: int = 10) -> None:
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password or _fetch_secret("notify/smtp/password")
        self.sender = sender or self.username
        self.recipients = list(recipients or [])
        self.use_tls = bool(use_tls)
        self.timeout = int(timeout_seconds)
    def send(self, event: NotificationEvent) -> NotifyResult:
        if not (self.host and self.sender and self.recipients):
            raise ChannelError(
                "email: host/sender/recipients required (constructor kwargs "
                "or org-bundle notification.channels block); password via "
                "vault path notify/smtp/password")
        import smtplib  # noqa: PLC0415
        from email.message import EmailMessage  # noqa: PLC0415
        msg = EmailMessage()
        msg["Subject"] = f"[spine/{event.severity}] {event.event_type}: {event.project_name}"
        msg["From"], msg["To"] = self.sender, ", ".join(self.recipients)
        msg.set_content(_fmt(event) + "\n\n" + json.dumps(event.metadata, indent=2))
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                if self.use_tls: s.starttls()
                if self.username and self.password:
                    s.login(self.username, self.password)
                s.send_message(msg)
        except Exception as e:  # noqa: BLE001
            raise ChannelError(f"smtp send failed: {e}") from e
        return NotifyResult(channel=self.name, sent=True)


class SystemChannel:  # macOS osascript / Linux notify-send / stdout fallback
    name = "system"
    def __init__(self, *, timeout_seconds: int = 5) -> None:
        self.timeout, self.os = int(timeout_seconds), platform.system().lower()
    def send(self, event: NotificationEvent) -> NotifyResult:
        title = f"Spine: {event.event_type}"
        body = f"{event.project_name} [{event.phase}] — {event.summary}"
        try:
            if self.os == "darwin":
                script = (f"display notification {shlex.quote(body)} "
                          f"with title {shlex.quote(title)}")
                subprocess.run(["osascript", "-e", script], check=True,
                               timeout=self.timeout, capture_output=True)
            elif self.os == "linux":
                subprocess.run(["notify-send", title, body], check=True,
                               timeout=self.timeout, capture_output=True)
            else:
                print(_fmt(event), file=sys.stdout, flush=True)
        except FileNotFoundError as e:
            raise ChannelError(f"system: missing helper for {self.os} "
                               "(install osascript / notify-send)") from e
        except subprocess.CalledProcessError as e:
            raise ChannelError(f"system notification failed: {e}") from e
        return NotifyResult(channel=self.name, sent=True)


class WebhookChannel:  # SIEM, custom destinations
    """Generic webhook with optional Bearer-token auth via vault.

    Pass ``auth_secret_path=`` to source the bearer token from
    ``shared.secrets`` (e.g. ``notify/webhook/<name>/token``).
    """
    name = "webhook"
    def __init__(self, *, url: str, headers: dict[str, str] | None = None,
                 method: str = "POST", timeout_seconds: int = 5,
                 auth_secret_path: str | None = None) -> None:
        if not url: raise ChannelError("webhook: `url` is required")
        self.url, self.headers = url, dict(headers or {})
        self.method, self.timeout = method.upper(), int(timeout_seconds)
        if auth_secret_path:
            token = _fetch_secret(auth_secret_path)
            if token:
                self.headers.setdefault("Authorization", f"Bearer {token}")
    def send(self, event: NotificationEvent) -> NotifyResult:
        try: import requests  # noqa: PLC0415
        except ImportError as e:
            raise ChannelError("webhook: `pip install requests` required") from e
        try:
            resp = requests.request(self.method, self.url,
                                    json=json.loads(event.model_dump_json()),
                                    headers=self.headers, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            raise ChannelError(f"webhook {self.method} failed: {e}") from e
        if resp.status_code >= 300:
            raise ChannelError(f"webhook non-2xx: {resp.status_code}")
        return NotifyResult(channel=self.name, sent=True)


class NoOpChannel:  # testing
    name = "noop"
    def __init__(self, *, label: str = "noop") -> None:
        self.name = label; self.events: list[NotificationEvent] = []
    def send(self, event: NotificationEvent) -> NotifyResult:
        self.events.append(event)
        return NotifyResult(channel=self.name, sent=True)


# ──────────────────────────────────────────────────────────────────────
# Wave-1 channel scaffolds (per V3 #6 + #29) — config-only; send() is
# deferred to v1.1+ pending the full provider transport implementation.
# ──────────────────────────────────────────────────────────────────────


class _ScaffoldChannel:
    """Base class for v1.1+ channel scaffolds.

    Subclasses fill ``name`` + provider-specific config / vault paths
    in ``__init__`` so credentials are wired (provable in tests) and
    surface a clear ``NotImplementedError`` from ``send()`` until the
    transport ships.
    """
    name = "scaffold"
    _impl_version = "v1.1+"

    def send(self, event: NotificationEvent) -> NotifyResult:  # noqa: ARG002
        raise NotImplementedError(
            f"channel {self.name!r} is a Wave-1 scaffold; transport "
            f"deferred to {self._impl_version}"
        )


# Vault-path constants imported from the canonical integration modules
# so a single grep across the repo shows every consumer (per V3 Part 1.1).
from shared.integrations.pagerduty import VAULT_PATH_ROUTING_KEY as _PD_ROUTING_KEY
from shared.integrations.teams import VAULT_PATH_WEBHOOK_URL as _TEAMS_WEBHOOK_URL
from shared.integrations.twilio import (
    VAULT_PATH_ACCOUNT_SID as _TW_ACCOUNT_SID,
    VAULT_PATH_AUTH_TOKEN as _TW_AUTH_TOKEN,
    VAULT_PATH_FROM_NUMBER as _TW_FROM_NUMBER,
)

_TW_WHATSAPP_FROM = "notify/twilio/whatsapp_from"


class SMSChannel(_ScaffoldChannel):
    """Twilio Programmable SMS scaffold (per V3 #29 — voice/phone Twilio stub).

    Vault paths:
        notify/twilio/account_sid
        notify/twilio/auth_token
        notify/twilio/from_number   (E.164, e.g. +14155551212)

    ``recipients`` is a list of E.164 numbers passed at construction time
    OR injected from the per-user comm-preferences resolver.

    Vault-path constants are sourced from ``shared.integrations.twilio``
    so a single grep across the codebase shows every consumer of these
    Twilio secrets.
    """
    name = "sms"
    def __init__(self, *, recipients: list[str] | None = None,
                 from_number: str | None = None,
                 timeout_seconds: int = 10) -> None:
        self.recipients = list(recipients or [])
        self.from_number = from_number or _fetch_secret(_TW_FROM_NUMBER)
        self.account_sid = _fetch_secret(_TW_ACCOUNT_SID)
        self.auth_token = _fetch_secret(_TW_AUTH_TOKEN)
        self.timeout = int(timeout_seconds)


class WhatsAppChannel(_ScaffoldChannel):
    """Twilio WhatsApp Business scaffold (per V3 #6).

    Shares the Twilio account_sid / auth_token with SMSChannel; the
    sender number must be a WhatsApp-enabled Twilio number formatted
    as ``whatsapp:+E.164``.

    Vault paths:
        notify/twilio/account_sid
        notify/twilio/auth_token
        notify/twilio/whatsapp_from   (e.g. whatsapp:+14155238886)
    """
    name = "whatsapp"
    def __init__(self, *, recipients: list[str] | None = None,
                 from_number: str | None = None,
                 timeout_seconds: int = 10) -> None:
        self.recipients = list(recipients or [])
        self.from_number = (
            from_number or _fetch_secret(_TW_WHATSAPP_FROM)
        )
        self.account_sid = _fetch_secret(_TW_ACCOUNT_SID)
        self.auth_token = _fetch_secret(_TW_AUTH_TOKEN)
        self.timeout = int(timeout_seconds)


class TeamsChannel(_ScaffoldChannel):
    """Microsoft Teams Incoming Webhook scaffold (per V3 #6).

    Teams uses connector-card webhooks (one URL per channel). Treat the
    URL itself as the credential — it embeds an unguessable token.

    Vault path:
        notify/teams/webhook_url  (sourced from shared.integrations.teams)
    """
    name = "teams"
    def __init__(self, *, webhook_url: str | None = None,
                 timeout_seconds: int = 5) -> None:
        self.webhook_url = (
            webhook_url or _fetch_secret(_TEAMS_WEBHOOK_URL)
        )
        self.timeout = int(timeout_seconds)


class PagerDutyChannel(_ScaffoldChannel):
    """PagerDuty Events API v2 scaffold for incident-class routing
    (per V3 #6 + #11 — incident control plane).

    Vault paths:
        notify/pagerduty/routing_key   (32-char hex per service integration)

    Routing logic (when implemented): events with severity=='critical'
    OR event_type in {'verify_failed', 'project_blocked',
    'incident_pageout'} → ``trigger`` action; everything else → either
    no-op or ``acknowledge`` per bundle policy.
    """
    name = "pagerduty"
    def __init__(self, *, routing_key: str | None = None,
                 dedup_strategy: str = "event_then_project",
                 timeout_seconds: int = 5) -> None:
        self.routing_key = (
            routing_key or _fetch_secret(_PD_ROUTING_KEY)
        )
        self.dedup_strategy = dedup_strategy
        self.timeout = int(timeout_seconds)


__all__ = [
    "ChannelError",
    "EmailChannel",
    "FileChannel",
    "NoOpChannel",
    "PagerDutyChannel",
    "SlackChannel",
    "SMSChannel",
    "StdoutChannel",
    "SystemChannel",
    "TeamsChannel",
    "WebhookChannel",
    "WhatsAppChannel",
]

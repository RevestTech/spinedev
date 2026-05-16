"""Notification channel implementations (STORY-1.4.7).

Each channel exposes `name` + `send(event) -> NotifyResult`. Transports
are lazy-imported inside `send()` so importing this module is cheap and
optional deps (`requests`, `smtplib`, `notify-send`/`osascript`) are
only required for channels actually used. Missing deps raise
`ChannelError` with a remediation message — the Notifier turns that into
a per-channel failure without breaking the fan-out.
"""
from __future__ import annotations
import json, logging, os, platform, shlex, subprocess, sys
from pathlib import Path
from typing import Any

from shared.notify.notifier import NotificationEvent, NotifyResult

_log = logging.getLogger("spine.notify.channels")
_SEV = {"info": "[INFO]", "warning": "[WARN]", "critical": "[CRIT]"}


class ChannelError(RuntimeError):
    """Raised by channels for transport/config issues; surfaced by Notifier
    as `NotifyResult(sent=False, error=...)`."""


def _fmt(event: NotificationEvent) -> str:
    line = (f"{_SEV.get(event.severity, '[?]')} {event.event_type}"
            f" project={event.project_name} ({event.project_id})"
            f" phase={event.phase}")
    if event.actor: line += f" actor={event.actor}"
    line += f" :: {event.summary}"
    if event.detail_url: line += f" [{event.detail_url}]"
    return line


def _load_yaml(filename: str) -> dict[str, Any]:
    path = Path.home() / ".spine" / filename
    if not path.is_file(): return {}
    try:
        import yaml  # noqa: PLC0415 — lazy
        return yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}


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
    """`webhook_url` arg → `SLACK_WEBHOOK_URL` env → `~/.spine/notify-slack.yaml`."""
    name = "slack"
    def __init__(self, *, webhook_url: str | None = None,
                 timeout_seconds: int = 5) -> None:
        self.timeout = int(timeout_seconds)
        self.webhook_url = (webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
                            or _load_yaml("notify-slack.yaml").get("webhook_url"))
    def send(self, event: NotificationEvent) -> NotifyResult:
        if not self.webhook_url:
            raise ChannelError("slack: no webhook_url (arg/env/notify-slack.yaml)")
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
    """Kwargs override `~/.spine/notify-smtp.yaml`; password also via
    `SPINE_SMTP_PASSWORD` env."""
    name = "email"
    def __init__(self, *, host: str | None = None, port: int = 587,
                 username: str | None = None, password: str | None = None,
                 sender: str | None = None, recipients: list[str] | None = None,
                 use_tls: bool = True, timeout_seconds: int = 10) -> None:
        cfg = _load_yaml("notify-smtp.yaml")
        self.host = host or cfg.get("host")
        self.port = int(port or cfg.get("port", 587))
        self.username = username or cfg.get("username")
        self.password = (password or cfg.get("password")
                         or os.environ.get("SPINE_SMTP_PASSWORD"))
        self.sender = sender or cfg.get("sender") or self.username
        self.recipients = recipients or cfg.get("recipients") or []
        self.use_tls = bool(use_tls if use_tls is not None
                            else cfg.get("use_tls", True))
        self.timeout = int(timeout_seconds)
    def send(self, event: NotificationEvent) -> NotifyResult:
        if not (self.host and self.sender and self.recipients):
            raise ChannelError("email: host/sender/recipients required "
                               "(kwargs or ~/.spine/notify-smtp.yaml)")
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


class WebhookChannel:  # SIEM, PagerDuty, custom
    name = "webhook"
    def __init__(self, *, url: str, headers: dict[str, str] | None = None,
                 method: str = "POST", timeout_seconds: int = 5) -> None:
        if not url: raise ChannelError("webhook: `url` is required")
        self.url, self.headers = url, dict(headers or {})
        self.method, self.timeout = method.upper(), int(timeout_seconds)
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


__all__ = ["ChannelError", "EmailChannel", "FileChannel", "NoOpChannel",
           "SlackChannel", "StdoutChannel", "SystemChannel", "WebhookChannel"]

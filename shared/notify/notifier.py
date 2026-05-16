"""Multi-channel notifier (STORY-1.4.7; REQ-INIT-1 FR-5).

Fans an event out to N channels (email / Slack / desktop / webhook /
stdout / file). Pure orchestration — every transport implementation
lives in `channels.py` so this file stays small + import-light.

Integration:
    * orchestrator/lib/gate.sh → "approval_pending", "approval_granted",
      "approval_rejected"
    * shared/cost/router.py    → "budget_warning", "budget_exceeded"
    * verify dispatcher        → "verify_failed"
    * orchestrator transitions → "phase_advanced", "project_blocked"

Rate limiting: per (event_type, project_id, recipient) → at most one
notification per `rate_limit_window_seconds` (default 300 = 5 min).
The window is in-memory only — the Notifier is meant to live for the
life of a daemon process. A persistence layer (V22+) can replace
`_rate_log` later without changing the public API.
"""
from __future__ import annotations
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict, Field

_PYD_CONFIG = ConfigDict(protected_namespaces=(), arbitrary_types_allowed=True)
_log = logging.getLogger("spine.notify")

EventType = Literal["approval_pending", "approval_granted", "approval_rejected",
                    "verify_failed", "project_blocked", "budget_warning",
                    "budget_exceeded", "phase_advanced"]
Severity = Literal["info", "warning", "critical"]

SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
DEFAULT_CONFIG_PATH = SPINE_HOME / "notify.yaml"
DEFAULT_RATE_LIMIT_SECONDS = 300


# ── Models ───────────────────────────────────────────────────────────────────
class NotificationEvent(BaseModel):
    """One notification's payload. Channels render this however they like.

    `summary` is short body text (≤ 200 chars target — fits Slack + OS toast).
    `detail_url` deep-links into the dashboard; channels may render as
    a button (Slack), link (email), or omit (system toast). `metadata`
    is free-form — surface anything channel-specific here."""
    model_config = _PYD_CONFIG
    event_type: EventType
    project_id: str
    project_name: str
    phase: str
    actor: str | None = None
    summary: str = Field(min_length=1)
    detail_url: str | None = None
    severity: Severity = "info"
    metadata: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotifyResult(BaseModel):
    """One channel's send outcome. Aggregated by Notifier.notify()."""
    model_config = _PYD_CONFIG
    channel: str
    sent: bool
    error: str | None = None
    duration_ms: int = 0
    rate_limited: bool = False


@runtime_checkable
class NotifyChannel(Protocol):
    """Channel transport protocol. Each implementation is a separate class
    in `channels.py`; they need only expose `name` + `send()`."""
    name: str
    def send(self, event: NotificationEvent) -> NotifyResult: ...  # noqa: E704


# ── Notifier core ────────────────────────────────────────────────────────────
class Notifier:
    """Fan-out engine. Constructed with a list of channels; rate-limits
    duplicate events per recipient; logs every dispatch attempt."""

    def __init__(self, channels: list[NotifyChannel], *,
                 rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_SECONDS):
        self.channels: list[NotifyChannel] = list(channels)
        self.rate_limit_window_seconds = int(rate_limit_window_seconds)
        # (event_type, project_id, recipient) -> last_sent_epoch
        self._rate_log: dict[tuple[str, str, str], float] = {}

    def _rate_key(self, event: NotificationEvent, recipient: str
                  ) -> tuple[str, str, str]:
        return (event.event_type, event.project_id, recipient)

    def _is_rate_limited(self, key: tuple[str, str, str]) -> bool:
        last = self._rate_log.get(key)
        if last is None:
            return False
        return (time.time() - last) < self.rate_limit_window_seconds

    def _mark_sent(self, key: tuple[str, str, str]) -> None:
        self._rate_log[key] = time.time()

    def notify(self, event: NotificationEvent, *,
               audience: list[str] | None = None) -> list[NotifyResult]:
        """Fan out `event` to every configured channel. If `audience` is
        provided, the rate-limit key uses each recipient; otherwise we
        rate-limit on channel-name. Channel failures are caught and
        reported in the result list — one bad channel never breaks the
        rest of the fan-out."""
        recipients = audience if audience else [c.name for c in self.channels]
        results: list[NotifyResult] = []

        for ch in self.channels:
            # Rate-limit per (event_type, project, recipient). If audience
            # was explicit we test against each recipient; else we test
            # against the channel name only.
            rkey = self._rate_key(event,
                                  recipients[0] if len(recipients) == 1 else ch.name)
            if self._is_rate_limited(rkey):
                results.append(NotifyResult(channel=ch.name, sent=False,
                                            error="rate_limited",
                                            rate_limited=True))
                _log.debug("rate-limited: %s -> %s", event.event_type, ch.name)
                continue

            start = time.time()
            try:
                result = ch.send(event)
                # Normalise: channels may return a partial result; backfill duration.
                if result.duration_ms == 0:
                    result = result.model_copy(update={
                        "duration_ms": int((time.time() - start) * 1000)})
                if result.sent:
                    self._mark_sent(rkey)
                results.append(result)
                _log.info("notify %s -> %s sent=%s err=%s",
                          event.event_type, ch.name, result.sent, result.error)
            except Exception as e:  # noqa: BLE001 — channel must never break fanout
                results.append(NotifyResult(
                    channel=ch.name, sent=False,
                    error=f"{type(e).__name__}: {e}",
                    duration_ms=int((time.time() - start) * 1000)))
                _log.warning("notify %s -> %s FAILED: %s",
                             event.event_type, ch.name, e)

        return results

    def add_channel(self, channel: NotifyChannel) -> None:
        """For dynamic registration (e.g. test wiring)."""
        self.channels.append(channel)

    def clear_rate_log(self) -> None:
        """Test helper. Drops the in-memory rate-limit history."""
        self._rate_log.clear()


# ── Config loading ───────────────────────────────────────────────────────────
def _build_channel(spec: dict[str, Any]) -> NotifyChannel | None:
    """Build one channel from a YAML spec block. Unknown / disabled
    channels return None (skipped). Lazy-imports keep the dep surface
    small — channels.py modules import their transports only at send()."""
    from shared.notify.channels import (EmailChannel, FileChannel, NoOpChannel,
                                        SlackChannel, StdoutChannel,
                                        SystemChannel, WebhookChannel)
    kind = (spec or {}).get("type", "").strip().lower()
    if not kind or not spec.get("enabled", True):
        return None
    cls: dict[str, type[NotifyChannel]] = {
        "email": EmailChannel, "slack": SlackChannel, "system": SystemChannel,
        "webhook": WebhookChannel, "stdout": StdoutChannel,
        "file": FileChannel, "noop": NoOpChannel,
    }.get(kind)  # type: ignore[assignment]
    if cls is None:
        _log.warning("unknown notify channel type: %s", kind)
        return None
    cfg = {k: v for k, v in spec.items() if k not in {"type", "enabled"}}
    try:
        return cls(**cfg)  # type: ignore[call-arg]
    except Exception as e:  # noqa: BLE001
        _log.warning("failed to construct %s channel: %s", kind, e)
        return None


def from_config(config_path: Path | None = None) -> Notifier:
    """Load channels from `~/.spine/notify.yaml`. Returns a stdout-only
    notifier if the file is missing or unparsable (fail-soft — never
    block on misconfiguration)."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.is_file():
        from shared.notify.channels import StdoutChannel
        return Notifier([StdoutChannel()])
    try:
        cfg = yaml.safe_load(path.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        _log.warning("could not parse %s: %s — falling back to stdout", path, e)
        from shared.notify.channels import StdoutChannel
        return Notifier([StdoutChannel()])

    chans = [c for c in (_build_channel(s) for s in (cfg.get("channels") or []))
             if c is not None]
    window = int(cfg.get("rate_limit_window_seconds", DEFAULT_RATE_LIMIT_SECONDS))
    if not chans:
        from shared.notify.channels import StdoutChannel
        chans = [StdoutChannel()]
    return Notifier(chans, rate_limit_window_seconds=window)


def from_org_bundle(bundle: dict[str, Any]) -> Notifier:
    """Load channels from an org bundle's `notification.channels` block.
    Org bundles can ship a default notifier policy (e.g., 'always Slack +
    file log for regulated tenants'). Falls back to stdout if unset."""
    notif = ((bundle or {}).get("notification") or {})
    chans = [c for c in (_build_channel(s) for s in (notif.get("channels") or []))
             if c is not None]
    window = int(notif.get("rate_limit_window_seconds",
                          DEFAULT_RATE_LIMIT_SECONDS))
    if not chans:
        from shared.notify.channels import StdoutChannel
        chans = [StdoutChannel()]
    return Notifier(chans, rate_limit_window_seconds=window)


__all__ = ["NotificationEvent", "NotifyResult", "NotifyChannel", "Notifier",
           "EventType", "Severity", "from_config", "from_org_bundle",
           "DEFAULT_CONFIG_PATH", "DEFAULT_RATE_LIMIT_SECONDS"]

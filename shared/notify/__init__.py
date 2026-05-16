"""Spine multi-channel notification system (STORY-1.4.7; REQ-INIT-1 FR-5).

Public surface re-exports so callers can `from shared.notify import Notifier,
NotificationEvent` without poking into submodules. See notifier.py / channels.py.
"""
from shared.notify.notifier import (NotificationEvent, Notifier, NotifyResult,
                                    from_config, from_org_bundle)
from shared.notify.channels import (EmailChannel, FileChannel, NoOpChannel,
                                    SlackChannel, StdoutChannel, SystemChannel,
                                    WebhookChannel, ChannelError)

__all__ = ["NotificationEvent", "Notifier", "NotifyResult",
           "from_config", "from_org_bundle",
           "EmailChannel", "FileChannel", "NoOpChannel", "SlackChannel",
           "StdoutChannel", "SystemChannel", "WebhookChannel", "ChannelError"]

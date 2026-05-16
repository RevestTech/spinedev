# Spine Notifier — `shared/notify/`

Multi-channel notification fan-out for approval-pending alerts, budget
warnings, verify failures, and project lifecycle events.

Implements **`STORY-1.4.7`** (REQ-INIT-1 §1.5 FR-5 — "user must know when an
approval is pending").

## What it ships

| File              | Role                                                    |
|-------------------|---------------------------------------------------------|
| `notifier.py`     | `Notifier` (fan-out + rate-limit) + `NotificationEvent` |
| `channels.py`     | 7 channel types — email / Slack / system / webhook / stdout / file / noop |
| `__init__.py`     | Re-exports the public surface                           |

## Channels

| Type      | Class            | Optional dep         | Config source                     |
|-----------|------------------|----------------------|------------------------------------|
| email     | `EmailChannel`   | stdlib (`smtplib`)   | kwargs / `~/.spine/notify-smtp.yaml` |
| slack     | `SlackChannel`   | `requests`           | kwargs / `SLACK_WEBHOOK_URL` env / `~/.spine/notify-slack.yaml` |
| system    | `SystemChannel`  | `osascript` (macOS) / `notify-send` (Linux) | — |
| webhook   | `WebhookChannel` | `requests`           | kwargs                             |
| stdout    | `StdoutChannel`  | —                    | kwargs                             |
| file      | `FileChannel`    | —                    | kwargs / `SPINE_NOTIFY_LOG` env    |
| noop      | `NoOpChannel`    | —                    | kwargs (test fixture)              |

All deps are **lazy-imported inside `send()`** — `import shared.notify` never
pulls `requests` / `smtplib`. Missing deps raise `ChannelError` with a remediation
hint; the `Notifier` records it as one channel failure and keeps fanning out.

## Event types

`approval_pending` · `approval_granted` · `approval_rejected` · `verify_failed` ·
`project_blocked` · `budget_warning` · `budget_exceeded` · `phase_advanced`.
Severity is one of `info` / `warning` / `critical`.

## Rate limiting

Per `(event_type, project_id, recipient)` → at most one notification per
`rate_limit_window_seconds` (default **300s / 5 min**). In-memory only;
suited to a long-lived daemon. A future story can swap in a persistent
store without changing the public API.

## Integration points

| Caller                                     | Event emitted              |
|--------------------------------------------|----------------------------|
| `orchestrator/lib/gate.sh::gate_approve`   | `approval_granted`         |
| `orchestrator/lib/gate.sh::gate_reject`    | `approval_rejected`        |
| `orchestrator/lib/gate.sh::gate_request_changes` | `approval_pending`   |
| `shared/cost/router.py::route` (cap warn)  | `budget_warning`           |
| `shared/cost/router.py::route` (blocked)   | `budget_exceeded`          |
| `verify/` dispatcher                       | `verify_failed`            |
| `orchestrator/lib/transition.sh`           | `phase_advanced`           |

These callers are **not** modified by this story — the Notifier is a
library; wiring lives in a follow-up integration story.

## Setup — `~/.spine/notify.yaml`

```yaml
rate_limit_window_seconds: 300
channels:
  - type: stdout
  - type: file
    path: ~/.spine/notifications.jsonl
  - type: slack
    webhook_url: https://example.invalid/webhooks/slack/docs-example
  - type: email
    host: smtp.acme.com
    port: 587
    sender: spine@acme.com
    recipients: [eng-leads@acme.com]
  - type: system    # desktop toast (dev workstations only)
```

## Quick usage

```python
from shared.notify import NotificationEvent, from_config

notifier = from_config()  # reads ~/.spine/notify.yaml
notifier.notify(NotificationEvent(
    event_type="approval_pending", project_id="42",
    project_name="Acme Web", phase="prd_review",
    actor="cto@acme.com",
    summary="PRD draft awaiting your sign-off",
    detail_url="https://spine.acme.com/approvals/42",
    severity="warning"))
```

## Cross-refs

* `docs/BACKLOG.md` → STORY-1.4.7
* `docs/PRD.md` → REQ-INIT-1 §1.5 FR-5
* `orchestrator/lib/gate.sh` (caller wiring — follow-up story)
* `shared/standards/bundle-schema.yaml` (org bundles may declare `notification.channels`)

# shared/integrations/

**Canonical home for external-system connector plumbing** (V3 Part 1.1).

Per the LOCKED top-level layout in `docs/V3_BUILD_SEQUENCE.md` Part 1.1,
this package houses **per-vendor authentication, connection, and base
API clients** for every external system Spine talks to. The per-domain
*use* of an integration (voice routing, SMS sending, issue import,
GRC evidence push) lives in the owning subsystem and consumes the
plumbing exported here.

This package was added by **Wave 3.5 FIX2** to close the HIGH-severity
drift finding flagged in `docs/STATUS.md`: the layout doc declared
`shared/integrations/` as NEW and 4 different design docs referenced
it as if it existed, but it had never been created. Integration code
was scattered across `voice/`, `shared/notify/channels.py`,
`migration/onboarding.py`, and `evidence/exporters/`.

## What lives here vs what lives in the consuming subsystem

| Concern | Lives in `shared/integrations/` | Lives in consuming subsystem |
|---|---|---|
| Vault path constants | yes | no — imports from here |
| Credential dataclass | yes | no — imports from here |
| Vendor SDK auth init | yes | no — imports from here |
| Signature validation | yes | no (e.g. Twilio HMAC-SHA1) |
| Base HTTP client | yes | no |
| `test_connection()` probe | yes (uniform envelope) | no — dispatches here |
| **Domain use** — voice routing, SMS send, GitHub repo import, Vanta evidence push | no | yes |

The pattern: subsystems own *how* the integration is used; this package
owns *how* it authenticates and where its secrets come from.

## Per-integration vault path conventions (per #9 — vault-only)

| Adapter | Vault path scheme |
|---|---|
| `twilio` | `notify/twilio/{account_sid,auth_token,from_number,whatsapp_from}` + `voice/twilio/incident_call_number` |
| `teams` | `notify/teams/webhook_url` |
| `pagerduty` | `notify/pagerduty/routing_key` |
| `github` | `integration/github/<org>/token` |
| `linear` | `integration/linear/<workspace>/api_key` |

Vault path constants are exposed as module-level `VAULT_PATH_*`
identifiers per adapter so a single grep across the codebase shows
every consumer of a given secret.

## Public API

```python
from shared.integrations import (
    IntegrationKind,            # enum of 6 categories
    TestConnectionResult,       # uniform probe envelope
    BaseIntegrationAdapter,     # concrete base class
    IntegrationAdapter,         # abstract Protocol
    fetch_secret,               # async vault fetch (the ONLY way)
    fetch_secret_sync,          # sync wrapper for channel constructors
    get_adapter,                # registry lookup by name
    known_adapters,             # sorted list of registered names
)
```

Per-adapter modules expose:

* A `<Vendor>Adapter` class subclassing `BaseIntegrationAdapter`.
* A module-level `test_connection()` coroutine for MCP dispatch.
* Vault-path constants.
* Domain-specific helpers (e.g. `validate_twilio_signature`,
  `GitHubConnector`, `LinearConnector`).

## Adding a new integration

1. Create `shared/integrations/<vendor>.py` next to this README.
2. Subclass `BaseIntegrationAdapter` with `name`, `kind`, `vault_path`.
3. Override `test_connection()` if a real HTTP probe is available;
   otherwise leave the inherited vault-presence probe.
4. Expose `test_connection()` at module scope so MCP can dispatch.
5. Call `register_adapter(name, factory)` at import time.
6. Add the import to `shared/integrations/__init__.py` so the side-effect
   registration runs.
7. Add tests under `shared/integrations/tests/test_<vendor>.py`.
8. If the integration is consumed by an existing subsystem
   (`voice/`, `shared/notify/`, `migration/`, `evidence/`), update
   the existing site to import from here instead of inline definition.

## Compatibility shims

Pre-existing callsites keep working unchanged via thin re-export shims:

* `voice/twilio_adapter.py` → re-exports
  `TwilioVoiceAdapter` / `TwilioVoiceConfig` /
  `validate_twilio_signature` from `shared.integrations.twilio`.
* `migration/onboarding.py` → re-exports `GitHubConnector` /
  `LinearConnector` / `HttpClient` from `shared.integrations.{github,linear}`.
* `shared/notify/channels.py` → `SMSChannel` / `WhatsAppChannel` /
  `TeamsChannel` / `PagerDutyChannel` read their vault paths from
  the canonical adapter modules.
* `evidence/exporters/_base.py` → `_fetch_secret` delegates to
  `shared.integrations.fetch_secret` (sync wrapped).

These shims may be removed in v1.1+ once every caller has migrated to
the canonical import path.

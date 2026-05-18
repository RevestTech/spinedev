# status.spine.dev — setup guide

Operator runbook for the public status page that customers + design
partners watch when something feels off. This doc walks the why, the
what to surface, and the wire-up of each component to the page.

> **Scope reminder.** Per design decision #15, the Hub is **self-hosted
> at every tier**. The status page communicates the health of the
> *Spine-operated surfaces* only — not Customer Hub deployments
> running on Customer infrastructure. Make this distinction loud on
> the page itself; otherwise customers will (rightly) ask "why does
> Spine show green when my Hub is red?"

---

## 1. What to surface

Five Spine-operated components. Each gets its own row on the status
page with independent health, history, and incident timeline:

| # | Component | What "up" means | Failure blast radius |
|---|-----------|-----------------|----------------------|
| 1 | **License bundle service** | Existing licenses verify + new license issuance succeeds (Ed25519 signing path per #23) | New installs cannot complete Day-0 wizard; existing Hubs continue serving (license bundle is cached locally + re-verified periodically — graceful) |
| 2 | **License heartbeat ingest** | Hubs can POST heartbeat metadata + receive ack | Hubs continue serving; back-pressure builds in client retry queues |
| 3 | **Telemetry ingest** (opt-in customers only) | Smart Spine 3-tier loop ingest endpoint receiving + persisting | Opt-in customers' learning loop pauses; no Hub functional impact |
| 4 | **Federation registry** | Discovery + handshake for Hub-to-Hub federation per #10 + #16 | New federation links cannot bootstrap; existing federation links operate peer-to-peer |
| 5 | **Evidence exporters** (Vanta / Drata / Secureframe upstream) | Spine-side export queues processing | Compliance evidence flows lag; no Hub functional impact |

A sixth row, **`docs.spine.dev` + `spine.dev` marketing site**, is
optional but recommended — customers conflate "the docs are down" with
"the product is down" if you don't separate them.

---

## 2. What NOT to surface

- **Customer Hub deployments.** Per #15 we don't have visibility into
  them and shouldn't claim to. If a customer Hub goes down, the
  customer's own monitoring is the source of truth.
- **Specific customer license state.** Status page is public — don't
  leak license counts, customer names, or per-customer health.
- **Internal CI / dev infra.** Customers don't care that your nightly
  build red. They care that the things they pay for are working.

---

## 3. Provider choice

`// TODO: ops` — pick one. Recommend evaluating:

| Provider | Pros | Cons |
|----------|------|------|
| **Statuspage.io** (Atlassian) | Mature, deep integrations, subscriber notifications, audit log | Expensive at scale, no self-host |
| **Instatus** | Cheaper, faster page, good DX | Smaller integration set |
| **BetterStack Status** | Bundled with their uptime monitoring + log mgmt | Lock-in to their broader suite |
| **Cachet** (self-hosted) | Self-hosted (consistent with our posture) | More ops burden; we'd run the thing meant to alert us when things break |

Per the brand consistency angle (we sell self-hosted), Cachet is the
on-message choice. Per the ops-burden + alerting paradox angle
(running your own status page is a circular-dependency hazard),
Statuspage.io is the pragmatic choice. Default recommendation:
**Statuspage.io**, with a one-line callout on the page that the
product itself is self-hosted on Customer infra.

---

## 4. Wire-up — checks per component

### 4a. License bundle service

- **Endpoint:** `GET https://license.spine.dev/healthz`
- **Probe:** HTTP 200 with body `{"status":"ok","sig":"…"}` —
  validate the `sig` against `TRUSTED_VENDOR_FINGERPRINT` to catch
  cases where the service responds but the signing key is unavailable
  (degraded-but-not-down).
- **Cadence:** 60s
- **Alert on:** 2 consecutive failures + sig mismatch is its own
  alert (page Spine on-call immediately — signing key compromise is
  the highest-severity incident shape)

### 4b. License heartbeat ingest

- **Endpoint:** `POST https://heartbeat.spine.dev/v1/heartbeat`
  (synthetic check posts a known-good test license; should ack)
- **Probe:** HTTP 202 + JSON `{"received":true,"counter":<int>}`
- **Cadence:** 60s
- **Alert on:** 2 consecutive failures OR p95 latency > `[2s]` for
  > `[5 minutes]`

### 4c. Telemetry ingest

- **Endpoint:** `POST https://telemetry.spine.dev/v1/tier1/healthz`
  (HEAD-style check; no payload)
- **Probe:** HTTP 200
- **Cadence:** 60s
- **Alert on:** 5 consecutive failures (less critical; opt-in
  customers tolerate brief outages)

### 4d. Federation registry

- **Endpoint:** `GET https://federation.spine.dev/v1/registry/health`
- **Probe:** HTTP 200 + registry size > 0
- **Cadence:** 120s
- **Alert on:** 2 consecutive failures

### 4e. Evidence exporters

- **Endpoint:** synthetic export to a Spine-owned test tenant in
  each of `[Vanta / Drata / Secureframe]`, run hourly
- **Probe:** export queue drains successfully
- **Cadence:** 3600s (hourly synthetic; underlying queue depth metric
  scraped every 60s into a separate component if exposed)
- **Alert on:** synthetic export failure OR queue depth > `[1000]`
  for > `[10 minutes]`

---

## 5. Maintenance windows

- **Default cadence:** `[2nd Tuesday of each month, 0300-0500 UTC]`
- **Communication:** announce on status page + email subscribers
  `[7 days]` in advance, again `[24 hours]` in advance, again at
  start
- **Hub deployments** are unaffected by maintenance windows on the
  Spine-operated surfaces (license bundles continue to work for
  `[N hours]` of disconnect per #23 graceful-degradation)

---

## 6. Incident response

- **Severity definitions:** see `docs/SECURITY_GUIDE.md` Section
  `[X]`. Status-page-visible incidents map to SEV-1 (major outage),
  SEV-2 (partial degradation), SEV-3 (minor / single component),
  SEV-4 (informational).
- **Incident manager** opens an incident on the status page at the
  moment of confirmation, not after triage. Vague is OK
  ("investigating elevated error rates on heartbeat ingest").
  Specific is good once known.
- **Update cadence:**
  - SEV-1: every 30 minutes until resolved
  - SEV-2: every 60 minutes until resolved
  - SEV-3 / 4: at start, end, and material status changes
- **Postmortems** for any SEV-1 or SEV-2 published within `[5
  business days]` to `docs/incidents/` (link from the resolved
  incident on the status page).

---

## 7. Subscribers + integrations

- **Subscribers.** Allow email + webhook + RSS subscriptions
  per-component. Enterprise customers get the option to add their
  oncall paging webhook (Spine-side subscribes; no Customer Hub
  involvement).
- **Hub-side integration.** The Hub admin UI's "About / System"
  panel fetches `https://status.spine.dev/api/v2/status.json` on
  page-load and shows a small green/yellow/red dot. Failure to fetch
  → show "unknown", don't show false-positive red.
  `// TODO: implement` — issue tracker, post-v1.0 nice-to-have.

---

## 8. Pre-launch checklist

- [ ] Provider account created + paid
- [ ] DNS: `status.spine.dev` → provider per `[provider DNS docs]`
- [ ] TLS cert (typically provider-managed)
- [ ] Five components created with the names + descriptions in §1
- [ ] Synthetic checks wired per §4 + dry-run-tested
- [ ] Alert routing: page Spine on-call for SEV-1; email for SEV-2+
- [ ] Subscriber form embedded
- [ ] About page describes self-hosted posture + what we monitor vs
      what Customer monitors
- [ ] Linked from `spine.dev` footer + `docs.spine.dev` footer + Hub
      admin UI "About / System" panel (post-v1.0)
- [ ] Soft-launched with one announcement on `[Slack community
      channel]` before going on marketing site

---

## 9. Related docs

- `docs/SECURITY_GUIDE.md` — severity definitions, incident response
- `docs/HUB_OPERATIONS_GUIDE.md` — Customer-side operational guide
  (Customer monitors their own Hub)
- `docs/DR_RUNBOOK.md` — 12-layer disaster recovery procedure
- `docs/legal/DPA_TEMPLATE.md` §11 — Personal Data Breach notification
  timing (72h)
- `docs/V1_SHIP_CHECKLIST.md` §3 — DNS + TLS + email infra for
  `spine.dev` / `try.spine.dev` / `status.spine.dev`

---

**Owner:** `[role: SRE lead / founder]`
**Last updated:** `[YYYY-MM-DD]`

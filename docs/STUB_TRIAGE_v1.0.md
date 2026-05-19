# v1.0 Stub Triage — what's deferred and why

> **TL;DR:** Walked every `NotImplementedError` / `STUB_V1_1=True` /
> "deferred to v1.1+" site in the codebase. **Zero need graduation to
> v1.0.** Each is either (a) explicitly enumerated as v1.1+ in the
> design decisions, (b) gated behind a feature flag that is off by
> default for v1.0 license bundles, or (c) a scaffold that ships
> surfacing-only (registration + audit + envelope) with downstream
> implementation deferred.
>
> Date: 2026-05-18

---

## Method

```
grep -rnE 'NotImplementedError|STUB_V1_1' --include='*.py' \
  shared/ devops/ recovery/ migration/ mobile/ voice/ \
  federation/ license/ evidence/ learning/ hub/
```

48 sites surfaced. Triaged below by subsystem.

---

## Categorized findings

### 1. DevOps control planes (8 planes × multiple actions) — DEFERRED

**Files:** `devops/planes/{ci_cd, deployment, monitoring, infrastructure,
database, networking, secrets, alerting}.py`

**What ships in v1.0:** the 8-plane dispatcher per V3 #11
(`OperateRole.dispatch()` routes by `(plane, action)`), the envelope
schema, the audit-event chain on every dispatch, role registration via
the `devops` charter.

**What's deferred:** the per-(plane, action) implementations themselves
(PyGithub for `ci_cd.create_pr`, Terraform SDK for
`infrastructure.apply`, Prometheus client for `monitoring.alert`,
PagerDuty for `alerting.page`, etc.). All raise
`NotImplementedError("v1.1+")` with a clear message.

**Why this is not a v1.0 blocker:** per
`devops/planes/__init__.py:27` — *"For v1.0 the deeper action handlers
raise NotImplementedError('v1.1+'); the dispatcher + audit + role
charter ship now so operators have the surface to call against."* The
Hub serves the routes, the registry advertises the operator role, the
audit chain captures every attempt. Real action wiring is a focused
v1.1+ work item per the canonical backlog in `V1_SHIP_CHECKLIST.md §8`.

---

### 2. Mobile + Voice (scaffolds) — DEFERRED per #28 + #29

**Files:** `mobile/__init__.py`, `voice/__init__.py`,
`shared/api/routes/mobile.py`, `shared/api/routes/voice.py`,
`shared/integrations/twilio.py`

**What ships in v1.0:** API routes registered (so the SPA admin panel
can list them as "available — not configured"); Twilio adapter base
class with signature verification per
`shared/integrations/twilio.py:_verify_signature`; mobile + voice MCP
tools registered in the catalog.

**What's deferred:** native iOS + Android client apps; actual
TwiML production from Twilio webhook bodies; `voice_approve_decision`
MCP tool.

**Why this is not a v1.0 blocker:** per V3 design decisions #28
(mobile-responsive on Day 1 via SvelteKit SPA viewport) + #29 (voice
adapter scaffolded; not Day-1 surface). SPA panels render correctly on
mobile browsers; voice routing is a v1.1 capability per #29 framing.

---

### 3. Evidence exporters (3 of 6) — DEFERRED per #24

**Files:** `evidence/exporters/{tugboat, strikegraph, thoropass}.py`

**What ships in v1.0:** the exporter base class
(`evidence/exporters/_base.py`) + `STUB_V1_1=True` flag + the three
PRIMARY exporters fully implemented:

  - `vanta.py` (production)
  - `drata.py` (production)
  - `secureframe.py` (production)

**What's deferred:** Tugboat, StrikeGraph, Thoropass —
secondary-market compliance platforms. All three set `STUB_V1_1=True`
and refuse `send()` with a `NotImplementedError("v1.1+")` clearly
labeled per V3 #24 ("ship the three primaries first; expand as design
partners ask").

**Why this is not a v1.0 blocker:** the 3 primaries cover the majority
of compliance-tooling market share. Tugboat / StrikeGraph / Thoropass
graduate to real impls when a paying customer asks (small focused PR
per vendor; `_render_batch` is the only abstract method to fill in).

---

### 4. Notification channels (4 of N) — SCAFFOLDED per #5/#27

**Files:** `shared/notify/channels.py`,
`shared/integrations/{teams.py, pagerduty.py}`,
`shared/integrations/twilio.py`

**What ships in v1.0:** the notifier base class
(`shared/notify/notifier.py`) + vault-wired channel config +
test-connection adapters (slack / email / sms / whatsapp / teams /
pagerduty / twilio). Every channel advertises its capabilities to the
integrations panel.

**What's deferred:** the `send()` method on slack/email/sms/whatsapp/
teams/pagerduty/twilio raises `NotImplementedError("v1.1+")`.

**Why this is not a v1.0 blocker:** per V3 #5 the primary
decision-delivery surface is the in-Hub decision queue (not
push-notification fan-out). The audit ledger captures every event;
operators see them in the SPA without channel send-out. Push-out to
external channels is v1.1+ enhancement, not a Day-1 capability.

---

### 5. Cross-region active-active DR — FLAG-GATED per #32

**File:** `recovery/cross_region.py`

**What ships in v1.0:** the flag-gating logic + same NotImplementedError
stub.

**Implementation:** if the `dr.cross_region` feature flag is off
(default for Solo + Startup tiers), the module is a no-op. If on
(Enterprise tier opt-in), it raises NotImplementedError pointing to
v1.1+.

**Why this is not a v1.0 blocker:** layer 7 of the 12-layer DR
framework is explicitly enterprise-tier per #32 framing
("multi-region active-passive lands v1.0; multi-region active-active
lands v1.1+ pending CAP-theorem operator decision"). Layer 7 is
off-by-default for all v1.0 license bundles.

---

### 6. Onboarding connectors — DEFERRED per migration scope

**File:** `migration/onboarding.py`

**What ships in v1.0:** the onboarding flow itself + connectors for
the 6 documented BYOC clouds (AWS / Azure / GCP / Railway / Fly / DO).

**What's deferred:** Asana / Jira / GitLab project-import connectors
(the "bring your existing workflow" enhancements).

**Why this is not a v1.0 blocker:** onboarding ships fully for the
cloud-deployment side. Workflow-tool import is v1.1+ — the lever there
is reading existing Jira tickets to seed the Hub's plan/intake
state, not bringing the Hub up.

---

## Cross-check against V1_SHIP_CHECKLIST.md §8

Every site triaged above is enumerated in §8 ("v1.1+ deferred —
post-launch backlog — DO NOT block ship on these"). The grep above
surfaced zero stubs that were NOT already in §8.

That's the trust signal we want: the code's stubs and the checklist's
"deferred" list are the SAME list. No silent half-finished surprises.

---

## Conclusion

**Zero stubs need to be graduated to v1.0.** v1.0 ships with the
surface every design decision committed to + clear `v1.1+`
demarcation everywhere expansion lives. Operators see clean refusals
(audit-logged) rather than silent failures.

V1_SHIP_CHECKLIST.md §8 remains the canonical post-v1.0 backlog.
Stub graduation triage gate closed.

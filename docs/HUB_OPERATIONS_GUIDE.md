# Hub Operations Guide

> Day-to-day running of a Spine Hub. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#3** (Hub-as-product), **#5** (active push), **#6** (comm channels), **#21** (AI-drivable everything), **#34** (workspace hygiene).
>
> **Audience:** Hub admin, devops on-call, anyone running Spine in production.

The Hub is the **primary management surface** of Spine (#3) — not a template, not a CLI. This guide assumes the Hub is up (`make hub-up` succeeded, `/healthz` green). For Day-0 install, see [`INSTALL.md`](../INSTALL.md).

---

## 1. The 9 Hub surfaces

The Hub web SPA exposes 9 enumerated surfaces (per `docs/V3_DESIGN_DECISIONS.md` cross-decision pattern #4):

| Surface | URL path | What you do here |
|---|---|---|
| Dashboard | `/` | KPIs, recent decisions, active projects, cost meter |
| Decision queue | `/decisions` | All open decision cards — approve / defer / redirect / request-changes |
| Master roles | `/masters` | Director-level role per discipline — chat / re-task / read briefings |
| Registry | `/registry` | All projects, all federated Hubs, all integrations |
| Audit | `/audit` | Hash-chained ledger view + search + Vanta/Drata push status |
| Vault config | `/vault` | Adapter status, rotation schedule, access audit |
| Integrations | `/integrations` | GitHub / Linear / Jira / Slack / PagerDuty / Twilio / Teams / clouds / GRC — connect / test / disable |
| Talk to a role | `/chat` | Chat surface to any Master role |
| Federation hub-switcher | `/hubs` | Drop-down: switch between team / division / enterprise / corporate Hub context |

License flags (#23) gate visibility — surfaces whose flag is OFF render an "Upgrade to unlock" CTA, not a blank space.

---

## 2. Day-2 ops — the rhythm

Spine **actively pushes** (#5). You don't watch a dashboard; the Hub pings you when a decision needs you. The on-call rhythm:

| Cadence | What happens | Where |
|---|---|---|
| **Continuous** | Decision cards land in your channels (Slack / email / SMS / WhatsApp / Teams / PagerDuty for incidents) | Per `shared/notify/` per #6 per-user prefs |
| **Daily** | Master roles send daily briefings (configurable per-role, per-user) | Slack / email |
| **Weekly** | Weekly briefings + DR test results + license utilization | Hub UI Dashboard tab |
| **Per-incident** | PagerDuty pages, Hub auto-creates incident work-item, security_engineer + devops roles dispatched | Hub UI Decision Queue |
| **Per-release** | Vendor publishes signed Hub release; admin approves cascade (#16) | Hub UI Decision Queue card |

If you're not getting pinged: see §6 troubleshooting.

---

## 3. Manage projects

```text
Hub UI → Registry → "New Project"
```

Or via CLI / MCP:

```bash
spine project new "Migrate auth from cookies to OAuth2" --type refactor --tier team
# Hub fires Master Product → 5-move intake → PRD card lands in Decision Queue
```

7 work-item types Day 1 (#19): `feature` / `bug` / `incident` / `support` / `refactor` / `infra` / `compliance`. Each has its own intake template + phase pipeline + role-charter responsibilities + UX surface + integration set.

To pause a project: Hub UI → Registry → project → "Pause" (stops daemons, preserves state).
To export a project: Hub UI → Registry → project → "Export" (signed tarball per #33 B).
To archive: "Archive" — moves to `spine_lifecycle.archived_at`; soft-delete with 7d retention per DR layer 9.

---

## 4. Manage roles

19 role charters Day 1 (#7 + #19):

| Charter family | Roles |
|---|---|
| Product + planning | product, planner, architect, conductor |
| Execution | engineer, ux, qa, datawright, researcher |
| Operate (6th corner) | operator (Spine-internal), devops (customer-facing per #11) |
| Meta | seer, auditor, memory |
| New for v3 (per #19) | customer_support, compliance_officer, security_engineer, tech_writer, release_manager |

Each charter is anchored in industry standard (Scrum Guide / PMBOK / ITIL / NIST / SRE handbook / TOGAF / Clean Code / etc.). Edit a charter:

```text
Hub UI → Master roles → <role> → "Edit charter" (requires can_modify_charter capability per bundle)
```

Charter edits are versioned in `shared/standards/` bundle and distributed via federation update flow (#16) — child Hubs see the change as a pending update card.

---

## 5. Manage comm channels (#6)

Per-user, per-decision-class, per-medium preferences:

```text
Hub UI → /profile → Notifications
```

Sets per-user override of bundle defaults. Tested via:

```bash
spine notify test --user khash@example.com --channel slack
# Sends a test decision-card to your configured Slack DM
```

Channels Day 1: web / Slack / email / SMS (Twilio) / WhatsApp (Twilio) / Teams / PagerDuty (incident class only). Voice (Twilio scaffold, #29) and mobile push (#28 scaffold; mobile-responsive web works today) land v1.1+.

**Credentials always in vault** (#9). To rotate a channel cred:

```bash
spine vault rotate slack/webhook --confirm
# Hub re-reads from vault; no restart needed
```

---

## 6. Troubleshooting

### Decision-card notifications not arriving

```bash
# 1. Is the Hub's notify worker alive?
spine status notify

# 2. Are vault creds for the channel valid?
spine vault test slack/webhook

# 3. Are user prefs configured?
spine user show khash@example.com | grep notify

# 4. Tail the notify log
spine logs notify --tail 100
```

### A Master role hasn't briefed in 24h+

```bash
# Briefing schedule + last_brief_at per role
spine role briefings --role product

# Force a brief now (won't reset cadence)
spine role brief --role product --now
```

### Workspace hygiene blocking project completion (#34)

The Conductor refuses to mark a project done if uncleaned workspace state exists:

```bash
# What's uncleaned?
spine hygiene status --project <name>

# Sweep (interactive — preview, then confirm)
make hygiene

# Or per-project nuclear (with confirmation)
spine hygiene sweep --project <name> --nuclear
```

Bundle policy declares retention windows + sweep cadence + acceptable workspace patterns. Customer can tune for their environment (`learning.workspace_retention_days: 30` etc.).

### License flag refusing to enable a feature

```bash
# Show current license bundle + flag state
spine license show

# Verify bundle signature against trusted vendor fingerprint
spine license verify

# If flag exists in your tier but is gated — license is correct, contact admin
# If flag should be ON in your tier — check bundle hasn't expired or been revoked
```

Detail: [`LICENSING_GUIDE.md`](LICENSING_GUIDE.md).

### Hub UI unreachable

```bash
make hub-status         # docker compose ps
make hub-logs           # tail container logs
curl -k $(cat _state/hub_url)/healthz
spine hub doctor        # runs preflight: vault reachable, keycloak reachable, pg reachable, migrations up-to-date
```

If still wedged: see [`DR_RUNBOOK.md`](DR_RUNBOOK.md) for restore-from-backup procedure.

---

## 7. Update path (#16)

When the vendor publishes a new Hub release:

1. Decision card lands in Hub UI Decision Queue: *"Update available: spine/hub v1.0.3 — security patch (low risk)"*
2. Card includes: changelog, risk notes, recommended-rollout-cadence, impact preview, backup status
3. Admin approves / defers / rejects
4. On approve: Hub takes a fresh backup (DR layer 12 verification), pulls signed image, validates fingerprint, restarts under new version
5. Audit chain records: who approved + when + reason
6. If federated: same card fires at child Hubs after parent approves (cascade per #16)

**Auto-push is never an option.** Bundle policy may declare `auto_approve_security_patches: true` if you trust the vendor for sec-only patches — but admin still sees the audit entry post-fact.

To roll back an update: Hub UI → Audit → release event → "Rollback". Migrations are forward-only by Flyway convention; rollback restores Postgres to pre-update snapshot per DR layer 9.

---

## 8. Run a healthy Hub — checklist

| Frequency | Task |
|---|---|
| Daily | Skim Decision Queue for stuck cards (`status=pending > 48h`); page approver |
| Daily | Skim `/audit` for unusual subsystem activity (audit-chain integrity check runs auto every hour) |
| Weekly | Confirm DR test ran + passed (Dashboard tab "DR" widget) |
| Weekly | Review license utilization vs quotas (`spine license usage`) |
| Weekly | Skim Master role briefings — anything anomalous? |
| Monthly | Rotate Hub admin Keycloak credentials (`keycloak/init-bootstrap.sh --rotate-admin`) |
| Monthly | Review vault access audit log (who accessed which secret when) |
| Quarterly | Update Spine Hub to latest signed release (vendor release advisory) |
| Quarterly | Test cross-region failover (`tools/dr-test.sh --cross-region`) |
| Annually | Independent pen-test — Spine vendor publishes summary; review against your posture |

---

## 9. AI-drivable everything (#21)

Every Hub operation has a flag-driven CLI / MCP equivalent. An AI agent can:

- Run the Day-0 wizard non-interactively: `bash hub/wizard/init.sh --no-interactive --shape laptop --vault openbao --keycloak bundled --llm anthropic --admin-email a@b.c`
- Approve a decision card via MCP: `mcp call decision_approve --card-id <uuid> --rationale "..."`
- Run a DR test: `bash tools/dr-test.sh --weekly`
- Rotate a vault secret: `spine vault rotate <path>`
- Federate a child Hub: `spine federation register-child --invite <file>`
- Update bundle policy: `spine bundle apply --file <bundle.yaml>`

This is the "Spine built by Spine" pattern (#21) made operational. The vendor's own Hub runs entirely this way — Khash approves decision cards; AI does the rest.

---

## 10. Related artifacts

- [`INSTALL.md`](../INSTALL.md) — Day-0 install across all 4 shapes
- [`docs/DEPLOYMENT_SHAPES.md`](DEPLOYMENT_SHAPES.md) — per-shape operational detail
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) — parent/child Hub setup + update cascade
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) — vault posture + identity + audit-chain integrity
- [`docs/LICENSING_GUIDE.md`](LICENSING_GUIDE.md) — flags + bundles + quotas
- [`docs/DR_RUNBOOK.md`](DR_RUNBOOK.md) — 12-layer DR operationally
- `hub/README.md` — Hub subsystem internals
- `hub/wizard/init.sh` — Day-0 wizard (the 7 steps)

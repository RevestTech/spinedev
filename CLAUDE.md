# Spine — Claude Code primer

This file orients Claude Code (and other agentic IDE tools) to the Spine
repository as it stands today.

> **Read first:** [`docs/SPINE_MASTER.md`](docs/SPINE_MASTER.md) — single
> source of truth for what Spine must do, component registry, gap matrix,
> and doc hierarchy. Origin: [`docs/_archived/chatsession-2026-05-17.md`](docs/_archived/chatsession-2026-05-17.md).
>
> **Status as of 2026-05-21.** v3 **scaffolding** is largely built; the
> **operating company loop** (orchestrator + role daemons + KG wiring) is
> still unwired — see SPINE_MASTER §4. Launch ops gates:
> [`docs/V1_SHIP_CHECKLIST.md`](docs/V1_SHIP_CHECKLIST.md). v1/v2 file-bus
> framing is historical; do not extend it.

---

## What Spine is

**Spine is "an AI software company in a box"** — a containerized **Hub**
(per [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) **#3**)
that runs on a laptop / customer-cloud (BYOC) / customer-K8s / on-prem and
gives one solo founder or one enterprise org a full AI engineering
organization with audit trail, vault-only secrets, hash-chained ledger,
federation, licensing, DR, and migration tooling.

**The Hub IS the product (#3).** It is NOT a developer framework you drop
into your project. It is NOT a SaaS coding agent (per **#15** — explicitly
not SaaS). It is NOT a vibecoder one-off generator (per **#1** positioning).

**Self-hosted at every tier.** Vendor never holds customer secrets,
customer code, or customer audit trail. The closest thing to a hosted
product is `try.spine.dev` — a demo sandbox only (#15).

---

## Repository layout (top-level)

```
hub/                      # Containerized Hub product (Day-0 wizard + Dockerfile + compose)
vault/                    # OpenBao container subsystem (Day-0 default; per #9)
keycloak/                 # Keycloak container subsystem (Day-0 default IdP; per #25)
federation/               # Hub-to-Hub federation (#10/#16): registry + upstream/downstream
license/                  # Feature-flag licensing (#23): Ed25519 verifier + quota ledger + Shamir
evidence/                 # Evidence Store (#24): collectors + Vanta/Drata/Secureframe exporters
learning/                 # Smart Spine 3-tier loop (#27): scope resolver + consent + anonymizer
devops/                   # Operate subsystem (#11): 8 control planes
recovery/                 # 12-layer DR (#31/#32): backups + restore + heartbeat + runbook
migration/                # Migration tooling (#33): onboarding + portability + version migrator
mobile/                   # Mobile scaffold (#28): API routes + iOS/Android placeholders
voice/                    # Voice scaffold (#29): Twilio webhook + adapter

shared/                   # Cross-cutting libraries
├── secrets/              # Vault adapter library (#9) — vault-only, no exceptions
├── llm/                  # Single LLM call surface (#2) — 7 providers, retry, streaming
├── identity/             # Keycloak OIDC client (#25)
├── runtime/              # Migrated cross-cutting helpers (vitals/heartbeat/watchdog/notify/
│                         # executor/usage-parsers/file-lock/updater/db-outbox/hygiene)
├── charters/             # 18 industry-anchored role charters (#7) — the canonical home
└── integrations/         # IntegrationAdapter base + twilio/teams/pagerduty/github/linear/...

shared/api/               # FastAPI REST (OIDC + feature-flag middleware + rate limit)
shared/mcp/               # MCP server + 54 tools + remote transport (mTLS + bearer)
shared/audit/             # Hash-chained audit ledger
shared/calibration/       # Platt + banded calibration
shared/standards/         # Bundle schema + validator + injector + drift detector
shared/notify/            # Multi-channel notifier (vault-wired)
shared/ui/                # SvelteKit Hub SPA (Wave 3 part 2)

verify/                   # TRON (git subtree); LLM bridged through shared/llm per Wave 3.5 FIX1

orchestrator/             # Lifecycle state machine + CLI
plan/                     # Plan subsystem (intake / PRD / TRD / Roadmap / Tech Review Swarm)
build/                    # Build subsystem (KG + extractors + indexer + runtime hooks)

db/flyway/sql/            # V1–V36 migrations
tools/                    # smoke-test.sh + bootstrap.sh + license-sign.sh + byoc/ + dr-test.sh

docs/                     # Canonical product/architecture docs

.spine/work/              # Per-agent workspace dirs (#34) — sweep with `make hygiene`
.spine/archive/           # Compressed completed-run archives
```

**Subsystem rules:**

- Top-level subsystems are LOCKED per V3 Part 1.1. Adding another requires a #34-eligible decision.
- Cross-cutting concerns live in `shared/`, never inlined into a single subsystem.
- TRON lives under `verify/` via `git subtree`. Treat as read-only from Spine; route LLM/secrets/identity through `shared/`.

---

## Core architectural commitments

These are stable. Do not relax them without an explicit ratification in
`docs/V3_DESIGN_DECISIONS.md`.

1. **Bash core preserved; Python wrappers layered (#7 / #11 / Wave 3 Squad A).** The historical bash daemons retired in Wave 6, but `shared/runtime/` still ships the 9 keeper bash helpers. New scripting that's purely operational (heartbeats, watchdog, hygiene sweeps) stays bash; new product surfaces are Python / SvelteKit.
2. **SvelteKit for the Hub SPA (Part 4.1).** Smallest bundle; closest-to-vanilla ergonomics. Don't introduce React/Vue/Solid for new panels without ratifying.
3. **Vault-only secrets (#9).** No `env://`. No `.env` containing real values. Every secret comes from a vault adapter in `shared/secrets/`. Final grep audit is in `V1_SHIP_CHECKLIST.md` §4 — it must return zero hits for secret VALUES (vault-path references are OK).
4. **All AI all the time (#21).** Spine is built by Spine — every line of code, every architectural decision, every PR has an audit trail. **The audit chain is the trust mechanism.** No "let me hand-author this PR to bypass" shortcuts.
5. **LLM-agnostic by architecture (#2).** Every LLM call goes through `shared/llm/`. Provider-specific features (like Anthropic prompt caching) become provider traits, never top-level dependencies.
6. **Cite-or-Refuse for verify roles (#12).** Auditor / QA / Verify tools must cite (KG node id / file:line / prior audit hash) or refuse to act. Refusal is itself an audit event.
7. **Industry-anchored role charters (#7).** Every charter is grounded in a recognized methodology (Scrum / PMBOK / SRE / ITIL / NIST / TOGAF / Clean Code / ISTQB / Nielsen / WCAG / DAMA-DMBOK / Kimball / IDEO / NN/g / etc.). No "we made this up" charters.
8. **Workspace hygiene as architectural concern (#34).** Per-run workspace under `.spine/work/<run_id>/`; promote final artifacts explicitly; archive on completion to `.spine/archive/`; Conductor gate refuses to mark a project done if uncleaned workspace state exists; `make hygiene` sweeps.

---

## Common operations

### Smoke test contract

**`bash tools/smoke-test.sh` must hit 99 PASS / 0 FAIL / 1 WARN / 0 SKIP /
3 INFO.** Anything else is a regression. The 1 WARN is `env.yq missing`
(harmless — awk fallback handles all manifests). The 3 INFO are
correctly-reported optional deps (yq / fastapi / doctor's optional probe).

```bash
bash tools/smoke-test.sh         # 7-phase end-to-end check
make smoke                        # convenience wrapper
```

CI must run `bash tools/smoke-test.sh --ci` on every PR; failing PR cannot
merge.

### Workspace hygiene

```bash
make hygiene                      # sweeps /tmp/spine-* + .spine/archive past N days +
                                  # stale workspaces + __pycache__ + repo-root scratch
```

`make hygiene` is the **Conductor gate** — a project cannot be marked
done by the Conductor role if `make hygiene` would have anything to clean
for that project (#34).

### Bootstrap a fresh clone

```bash
git clone && make bootstrap       # preflight → venv → pip → spine pg → tron pg →
                                  # flyway → alembic → smoke
```

Idempotent; re-runs in seconds when nothing changed.

### Run the Hub locally

```bash
docker compose -f hub/docker-compose.yml up    # spins up hub + vault + keycloak + postgres
# Hub at http://localhost:8090
# Day-0 wizard runs on first boot (7 steps, fully flag-driven for AI)
```

---

## How to add a new role charter

Per **#7** (industry-anchored) + **#19** (work-item type coverage):

1. **Pick an industry anchor.** Every charter must cite a recognized methodology. Look at existing examples in `shared/charters/`: architect→TOGAF, auditor→NIST 800-53, conductor→Scrum+SAFe, product→Inspired+JTBD, qa→ISTQB, ux→Nielsen+WCAG 2.2, etc.
2. **Add the charter file** at `shared/charters/<role>.md`. Section structure: identity / authority / inputs / outputs / contract / industry anchors / cite-or-refuse posture (if verify-class per #12).
3. **Register** in `shared/charters/__init__.py` and add to `EXPECTED_CHARTER_COUNT` in the relevant test.
4. **Wire in the dispatcher** if the role is dispatchable from `build_dispatcher.py` or routes from a work-item type per **#19**.
5. **Update `docs/V3_DESIGN_DECISIONS.md` quick index** if this is a new top-level role concern. Most aren't.
6. **Master roles** are Director-level (per **#8** two-tier hybrid authority) — they aggregate across project Spines within a Hub. Don't conflate Master roles with project-level roles.
7. **Do NOT add role prompts under a legacy `lib/` tree** — canonical charters live in `shared/charters/`.

---

## How to add a new MCP tool

Per **#12** (Cite-or-Refuse for verify-class) + **#30** (API+MCP heavier scaffold):

1. **Add the tool function** under the appropriate module in `shared/mcp/tools/`: orchestrator / plan / build / verify / kg / iso / sandbox / standards / auditor / devops / federation / license / evidence / learning / recovery / migration / mobile / voice / integrations.
2. **Decorate with `@register_tool`** (or the module's pattern) — sets metadata + adds to `TOOL_REGISTRY`.
3. **If verify-class, set `requires_citation=True`.** The Cite-or-Refuse middleware enforces this: tool must accept `citations: list[Citation]` and refuse (audit-logged) if citations are missing or unverifiable.
4. **Bump `EXPECTED_TOOL_COUNT`** in `shared/mcp/tests/test_server_smoke.py`. Current count: **54** (v3 Wave 6). If you forget, the smoke test will catch it.
5. **Add to OpenAPI spec** if the tool also surfaces via the public REST API at `/api/v2/...` — see `shared/api/openapi_spec.py` + `shared/api/versioning.py`.
6. **Add a feature flag** if the tool should be gated per **#23**. The flag goes in `KNOWN_FEATURE_FLAGS` and is checked via `license.is_enabled(...)` before the tool dispatches. Gracefully fail with an "upgrade to unlock" envelope.
7. **Rate-limit if appropriate** per **#30** — `shared/api/rate_limit.py` exposes a per-(org, flag) token bucket sourced from `spine_license.feature_flag`.

---

## Doc hierarchy (read these before changing architecture)

| Doc | Purpose |
|---|---|
| [`docs/SPINE_MASTER.md`](docs/SPINE_MASTER.md) | **Start here.** Vision, golden path, component registry, gap matrix, hygiene rules. |
| [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) | 34 locked decisions. If anything else conflicts, this wins until ratified. |
| [`docs/PRD.md`](docs/PRD.md) | REQ-level acceptance criteria. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Subsystem boundaries and data flow. |
| [`docs/V3_TRIAGE.md`](docs/V3_TRIAGE.md) | Per-artifact KEEP / REFACTOR / REBUILD marks (historical triage). |
| [`docs/V3_BUILD_SEQUENCE.md`](docs/V3_BUILD_SEQUENCE.md) | 7-wave execution plan (historical). |
| [`docs/V1_SHIP_CHECKLIST.md`](docs/V1_SHIP_CHECKLIST.md) | Customer launch gate (operational only). |
| [`docs/STATUS.md`](docs/STATUS.md) | Wave commit log — not the "what to build next" list. |

Supporting (per-subsystem READMEs, operational guides, runbooks):

- `hub/README.md` / `vault/README.md` / `keycloak/README.md` / each subsystem ships its own README.
- `docs/HUB_OPERATIONS_GUIDE.md` / `docs/DEPLOYMENT_SHAPES.md` / `docs/FEDERATION_GUIDE.md` / `docs/SECURITY_GUIDE.md` / `docs/LICENSING_GUIDE.md` / `docs/DR_RUNBOOK.md` — landed in Wave 5 Squad G.
- `docs/PRD.md` / `docs/positioning.md` / `docs/ARCHITECTURE.md` — REBUILT in Wave 5 Squad G; v1/v2 versions archived.

---

## Historical / deprecated framings

**Pre-v3 docs preserved for reference:** see `docs/_archived/` (`v1-PROTOCOL.md`,
`v1-REQUIREMENTS.md`, `v1-IMPROVEMENT_CHECKLIST.md`, `v1-PRACTICES.md`, `v2-*.md`, design session).
These describe the v1/v2 file-bus orchestration framework + the
`scripts/roles.sh` 15-manager roster + the `.planning/orchestration/`
directory contract. **They are not the v3 product.** If you find yourself
about to extend any of these to add functionality, stop and route through
the v3 doc trinity instead.

**`lib/` is fully retired.** Wave 6 (`19f745f`) deleted the file-bus daemons;
the remaining `lib/role-prompts/` reference tree was removed once
`shared/charters/` became canonical. Canonical role charters now live in
`shared/charters/`.

---

## Tone

- No emojis in code or docs unless the user explicitly asks.
- Prefer the dedicated tools (Read / Edit / Write) over `cat` / `sed` / `echo`.
- Use absolute paths in bash invocations; avoid `cd`.
- Run independent commands in parallel.
- When a smoke regression appears, the bar is "fix, don't suppress" — the 99 PASS / 0 FAIL contract is the architectural quality gate.

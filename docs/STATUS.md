# Spine — Status & Handoff

> **Last updated:** 2026-05-18 (Wave 0 complete — v3 rebuild started)
> **Branch:** `main`
> **For:** anyone picking up Spine development.

---

## v3 status (current)

**v3 rebuild is in flight.** 34 design decisions locked
(`docs/V3_DESIGN_DECISIONS.md`); full codebase triage shipped across 6
subsystems (`docs/V3_TRIAGE.md`); 7-wave dependency-ordered execution
plan (`docs/V3_BUILD_SEQUENCE.md`).

### Wave 0 — Foundations: COMPLETE 2026-05-18

7 focused commits:

| Commit | Subsystem | Scope |
|---|---|---|
| `3bc6805` | `shared/secrets/` | 15 files / 2288 lines — vault adapter library + InMemoryAdapter + cli wrapper |
| `7a34d58` | `shared/llm/` | 19 files / 2984 lines — 7 provider adapters + retry + streaming |
| `882b8a6` | `shared/identity/` | 11 files / 2144 lines — Keycloak OIDC client + 5-tier matrix |
| `a756b2f` | `vault/` | 14 files / 1658 lines — OpenBao container + Day-0 wizard + 5 unseal/DR runbooks |
| `1a96a41` | `keycloak/` | 15 files / 1723 lines — Keycloak container + 5 IdP presets |
| `5c17e7a` | `db/flyway/sql/V22-V32` | 11 files / 1129 lines — 11 new schemas (license / federation / hub / evidence / identity / devops / workitem / learning / provider / cloud / dr) |
| `2212742` | Pass 2 refactors | 10 files / +933 −131 — 5 vault violations closed + verify/.env vault-refs + downstream fixups (InMemoryAdapter / orchestrator.py / smoke-test.sh) |

**Total Wave 0:** ~12858 net lines added, 0 vault violations remaining.

**Validation:** smoke test 99 PASS / 0 FAIL / 1 WARN / 0 SKIP — same as
pre-Wave-0 baseline. V22-V32 applied clean against live Postgres
transactionally.

**Rotation required before v1.0** (#9 no-exceptions): TRON
Postgres / Redis / MinIO / Grafana passwords were `tron_dev_only` in
old `verify/.env` (single commit `493b07c`). Rotate when wiring real
TRON deploy.

### Open Part 4 decisions (resolved autonomously during overnight run)

| # | Choice | Notes |
|---|---|---|
| 4.1 | Svelte for Wave 3 Hub SPA | smallest bundle; closest-to-vanilla ergonomics |
| 4.2 | Fly.io as 5th cloud Day 1 | better modern API + edge network |
| 4.3 | Vendor vault + Shamir 3-of-5 recovery for license keys | HashiCorp Enterprise pattern |
| 4.4 | DR cross-region default-OFF | enterprise feature flag `dr.cross_region` |
| 4.5 | TRON license audit deferred to Wave 5 dedicated subagent | per build sequence |
| 4.6 | `#34` workspace hygiene at `shared/runtime/hygiene.py` | cross-cutting library per Part 1.1 |
| 4.7 | Hosted demo sandbox deferred (pre-launch) | not blocking any wave |
| 4.8 | Air-gapped v1.1 deferral holds | per #17 |

### Wave 6 — Mobile/Voice/API scaffolds + lib/ retirement: COMPLETE 2026-05-18

3 commits:

| Commit | Stream | Scope |
|---|---|---|
| `a75e6a4` | H+I mobile+voice | mobile/api/routes (Bearer-auth compact JSON for approvals/briefings/status + APNs/FCM action endpoint) + mobile/ios + mobile/android placeholders with vault-referenced signing + voice/api/routes (Twilio webhook with real HMAC-SHA1 signature validation) + voice/twilio_adapter + scaffolds. +1928 lines / 29 tests |
| `3be6c70` | J API+MCP heavier | shared/api/openapi_spec (OpenAPI 3.1 + 4 server templates + reusable Citation schema + error envelopes + Keycloak security schemes) + shared/api/versioning (v2 current; v1→v2 redirect with RFC 8594 Sunset header) + shared/api/rate_limit (per-(org,flag) token bucket from spine_license.feature_flag) + envelopes REFACTOR (feature_flag_required + actor_token_claims) + shared/mcp/tools/integrations (3 MCP tools) + EXPECTED_TOOL_COUNT 42→54. +2749 lines / 50 tests |
| `19f745f` | K lib/ retirement | DELETE 17 lib/* files (dashboard.html 1262 LOC + team-agent-daemon.sh 1001 + team.sh 1087 + 14 others) + Makefile / db/Makefile / shared/runtime/watchdog.sh updates removing references. Kept lib/role-prompts/ per shared/charters/README.md documented intent. +235 -3519 lines |

**Total Wave 6:** -607 net lines (1928+2749-3519+235), 79 new tests passing, **54 MCP tools** registered, smoke test 99 PASS / 0 FAIL maintained. lib/ shrunk from 34 files / ~8000 LOC to 17 files / 1095 LOC (all deprecated role-prompts).

---

### Wave 3 part 2 — Hub SPA + remote MCP: COMPLETE 2026-05-18

7 commits:

| Commit | Scope |
|---|---|
| `480c90b` | Drift fixes (4 stale deletes + recovery path + #34 hygiene Makefile target) |
| `e8d83d2` | Squad SPA1 — SvelteKit 2 + Svelte 4 + Tailwind scaffold + 2 example panels (decision-queue + role-chat) + login UI + 9 reusable components + Hub Dockerfile + FastAPI mount. +2782 lines |
| `e32e283` | Squad SPA4 — `shared/mcp/server_remote.py` remote MCP transport (mTLS + bearer via vault) + 30 new tests. Unlocks federation tool delegation. +1880 lines |
| `f132103` | Squad SPA2 — 5 panels (master-roles / registry / audit / vault-config / integrations) + 12 new types. +1772 lines |
| `6da82c9` | Squad SPA3 — 3 panels (federation / license / kg-search) + `shared/api/routes/kg.py` NEW REST backend (8 tests) + OpenAPI→TS codegen pipeline + types.ts façade. +2355 −121 lines |
| (sidebar+STATUS) | Sidebar: all 10 panels flipped to `shipped: true`; STATUS update |

**Total Wave 3 part 2:** +12780 net lines, 173+ new tests passing, all 10 Hub surfaces shipped, smoke test 99 PASS / 0 FAIL maintained.

### 5 backend gaps surfaced by SPA squads (Wave 4 follow-ups)

1. `registry.py` RoleEntry lacks runtime fields (status/last_decision_card_pushed/current_responsibility)
2. `audit.py` requires project_id; lacks subsystem/role/action filters; no cursor pagination
3. `vault_config.py` `/vault/status` lacks per-path last-rotation timestamps
4. `integrations.py` IntegrationDetail.status lacks `disabled` enum value
5. Decisions store + federation graph still in-process (Wave 3 Squad C deferral)

### 2 high-severity drift findings still need dedicated work

- **Finding 1 (HIGH):** TRON LLM bypasses `shared/llm/` — Part 1.4 #6 commitment never fulfilled across 40 commits. `verify/tron/infra/llm/client.py` defines own Provider enum
- **Finding 2 (HIGH):** `shared/integrations/` package never created (layout violation). Twilio in `voice/`, GitHub/Linear inline in `migration/onboarding.py`, no central package — **CLOSED by Wave 3.5 FIX2** (see below).

### Wave 3.5 FIX2 — shared/integrations/ extraction: COMPLETE 2026-05-18

Closed HIGH-severity Finding 2 above. Created the canonical `shared/integrations/` package per V3 Part 1.1 (LOCKED top-level layout):

- `shared/integrations/__init__.py` + `base.py` (IntegrationAdapter / IntegrationKind / TestConnectionResult / fetch_secret / registry helpers) + `README.md` (vault-path conventions per adapter)
- `shared/integrations/twilio.py` — canonical home for Twilio auth + signature validation; voice adapter relocated here
- `shared/integrations/teams.py` + `pagerduty.py` — vault-path + adapter scaffolds
- `shared/integrations/github.py` + `linear.py` — GitHubConnector / LinearConnector relocated from `migration/onboarding.py`
- 5 test files (`test_base`, `test_twilio`, `test_github`, `test_linear`, `test_compat_shims`) — 59 tests, all green

Re-export shims keep ZERO public API breakage:
- `voice/twilio_adapter.py` → re-exports from `shared.integrations.twilio`
- `migration/onboarding.py` → re-exports `GitHubConnector` / `LinearConnector`
- `shared/notify/channels.py` → imports `VAULT_PATH_*` constants from canonical modules
- `evidence/exporters/_base.py` → `_fetch_secret` delegates to `shared.integrations.fetch_secret`
- `shared/mcp/tools/integrations.py` → updated to dispatch via canonical adapters and accept both `TestConnectionResult` and legacy tuple shapes

**Validation:** 198 tests passing across `shared/integrations/` + `voice/tests/` + `shared/notify/tests/` + `migration/tests/` + `evidence/tests/` + `shared/mcp/tests/test_integrations_tools.py`. Smoke test 99 PASS / 0 FAIL maintained.

---

## v3 BUILD COMPLETE 🎉 — 2026-05-18

**All 7 waves shipped. v3 is ready for v1.0 ship pending the v1.1 follow-up backlog accumulated across each wave.**

### v3 cumulative totals

| Metric | Value |
|---|---|
| Commits (since v3 start `1da7148`) | 33 |
| Net lines added | ~85,000+ across all subsystems |
| New top-level subsystems | 10 (hub, federation, devops, vault, keycloak, license, evidence, learning, recovery, migration) |
| New shared libraries | 6 (shared/{secrets, llm, identity, runtime, charters, integrations}) |
| New Flyway migrations | 14 (V22-V35) |
| New MCP tools | **54 registered** (was 27 v2 → 54 v3) |
| New role charters | 19 industry-anchored (6 new in Wave 2 + 13 REBUILT in Wave 3) |
| New tests | 700+ (across all waves) |
| Smoke test | **99 PASS / 0 FAIL** maintained throughout |
| lib/ retirement | 34 files / ~8000 LOC → 17 files / 1095 LOC (all deprecated role-prompts) |
| Landing docs | All 7 v1-framing docs REBUILT + 6 NEW operational guides |
| 34 design decisions | All locked + implemented (or explicitly stub'd per scaffold framing) |
| Drift audits | Run at Wave 1, Wave 2+3 milestones — ON-TRACK both times |

### What v1.0 needs before customer-facing ship

| Item | Source | Notes |
|---|---|---|
| Hub SPA panels (10) | Wave 3 part 2 | Svelte per Part 4.1; routes from Wave 3 Squad C ready |
| Real-MCP federation transport | Wave 3 part 2 | shared/mcp/server_remote.py with mTLS + bearer |
| Real Twilio voice routing | v1.1+ per #29 | TwiML for Master CTO callable-for-incidents |
| Native mobile apps | v1.1+ per #28 | SwiftUI / Compose; signing wired |
| Tugboat/StrikeGraph/Thoropass compliance | v1.1+ per #24 | exporters stubbed |
| Real per-cloud BYOC provisioners | v1.1 | tools/byoc-provision.sh + per-cloud runbook |
| Postgres-backed decisions store | Wave 3 Squad C deferred | in-process today; spine_lifecycle.decision_card schema needed |
| Real upgrade executors | Wave 5 Squad F deferred | Flyway / bundle / charter / vault-namespace / KG runners |
| Vendor signing key Shamir reconstructor | Wave 4 Squad B deferred | pyshamir/sslib dep |
| Rotation operationally | Per #9 | TRON dev passwords from old verify/.env (commit 493b07c) — rotate vault paths |

### Open Part 4 decisions resolved autonomously (need user ratification)

| # | Choice | Rationale |
|---|---|---|
| 4.1 | Svelte for Hub SPA | smallest bundle; closest-to-vanilla ergonomics |
| 4.2 | Fly.io as 5th cloud | modern API + edge network |
| 4.3 | Vendor vault + Shamir 3-of-5 | HashiCorp Enterprise pattern |
| 4.4 | DR cross-region default-OFF | enterprise tier feature flag `dr.cross_region` |
| 4.5 | TRON license audit deferred | Wave 5 dedicated subagent (still TODO per #18 closed-source ship gate) |
| 4.6 | `#34` hygiene at `shared/runtime/hygiene.py` | cross-cutting library per Part 1.1 hybrid placement |
| 4.7 | Demo sandbox deferred | pre-launch only |
| 4.8 | Air-gapped v1.1 deferral holds | per #17 |

---

### Wave 5 — DR + Migration + Landing-docs big-bang: COMPLETE 2026-05-18

3 commits:

| Commit | Squad | Scope |
|---|---|---|
| `7a4c3ce` | F migration | `migration/` (#33 A+B+D): GitHub+Linear onboarding + signed-tarball portability (round-trip property PROVEN: byte-identical export A→import→export B) + spine_version migrator with N-2 cross-version compat + downgrades BLOCKED + 4 MCP tools + lib/spine-migrate.py moved to `migration/_v1_v2_migrator_legacy.py`. +4388 lines / 48 tests |
| `6138a11` | E recovery | `recovery/` 12-layer DR (#31, #32): WAL+snapshot backups to S3/GCS/Azure/MinIO/Wasabi via CLI subprocess + tested restore + heartbeat + cross-region STUB v1.0 (default-OFF per Part 4.4) + auto-recovery via watchdog adapter + auto-generated DR runbook + tools/dr-test.sh + 5 MCP tools. +5116 lines / 97 tests |
| `9728427` | G landing-docs | T6 highest-leverage UX bug: REBUILT all 7 v1-framing landing docs (README/INSTALL/install.sh/PRD/positioning/ARCHITECTURE [REFRESH]/db/README) + 6 NEW operational guides (HUB_OPERATIONS_GUIDE/DEPLOYMENT_SHAPES/FEDERATION_GUIDE/SECURITY_GUIDE/LICENSING_GUIDE/DR_RUNBOOK). v2 archived. +6399 −2105 lines |

**Total Wave 5:** +13798 net lines, 145 new tests passing, smoke test 99 PASS / 0 FAIL maintained. T6 highest-leverage UX bug closed.

### Wave 4 — Federation + License + Evidence + Learning: COMPLETE 2026-05-18

5 commits:

| Commit | Squad | Scope |
|---|---|---|
| `118688d` | D learning | Smart Spine 3-tier loop (#27): scope resolver + 3-tier contribute gates + cross-org consent registry + k=5 anonymizer + vendor self-improvement Tier 3 hook + 4 MCP tools. +2795 lines / 61 tests |
| `64db848` | A federation | Hub-to-Hub (#4/#10/#16): hub_registry (consumes hub/_state/hub_id.txt) + upstream_client (mTLS+bearer via vault) + downstream_router + update_cascade (signed bundle distribution + per-tier approval gate) + consent engine + 4 MCP tools. +3425 lines / 35 tests |
| `f366a11` | C evidence | Evidence Store (#24): 5 collectors (audit_chain/role_decision/vault_access/deploy/approval) + 3 real exporters (Vanta/Drata/Secureframe) + 3 v1.1 stubs (Tugboat/StrikeGraph/Thoropass) + two-party SHA-256 attestation per V25 + 4 MCP tools. +2583 lines / 46 tests |
| `c96f23a` | B license | Feature-flag licensing (#23): Ed25519 signed bundle verifier with TRUSTED_VENDOR_FINGERPRINT trust anchor + periodic re-verify + feature_flags evaluator + hash-chained quota ledger + tools/license-sign.sh (vendor-side per Part 4.3 Shamir 3-of-5) + 3 MCP tools. +2787 lines / 47 tests |
| (next) | housekeeping | test_server_smoke EXPECTED_TOOL_COUNT 27→42 + WAVE-* story-id prefix accepted alongside STORY-* |

**Total Wave 4:** +11590 net lines, 189 new tests passing, 15 new MCP tools (federation/license/evidence/learning × 4-4-4-3), smoke test 99 PASS / 0 FAIL maintained.

### Wave 3 part 1 — Hub product + runtime migration + charter REBUILDs + API expansion: COMPLETE 2026-05-18

5 commits:

| Commit | Scope |
|---|---|
| `18a82d7` | Squad A — `shared/runtime/` migration from `lib/` (9 keeper bash files: vitals/heartbeat/watchdog/notify/executor/usage-parsers/file-lock/updater/db-outbox) + `ALLOWED_SUBSYSTEMS` 'devops' extension + V35 Flyway DB CHECK extension (applied LIVE). +3852 lines |
| `2f02370` | Squad B — `hub/` containerized product subsystem (multi-arch Dockerfile + docker-compose with vault+keycloak+pg+flyway + entrypoint with wait-for-X + Day-0 wizard with 7 steps fully flag-driven for AI + smoke test). +2052 lines |
| `ec112df` | Squad D — 13 existing charter REBUILDs against industry standards (architect→TOGAF, auditor→NIST 800-53+Cite-or-Refuse, conductor→Scrum+SAFe, datawright→DAMA+Kimball, engineer→#13 tier-bifurcation+Clean Code, operator→SRE-internal-variant+12-factor, planner→PMBOK 7, product→Inspired+JTBD, qa→ISTQB, researcher→#12 Cite-or-Refuse+IDEO+NN/g, ux→Nielsen+WCAG 2.2). +2562 lines |
| `496962f` | Squad C — `shared/api/` REBUILD: `dependencies.py` now uses `shared.identity.current_user` + asyncpg pool (vault DSN) + remote-MCP placeholder; 7 NEW routes (decisions/role_chat/registry/vault_config/integrations/federation/license); 3 NEW middleware (OIDC cookie/session, feature-flag enforcement). +3545 lines, 52 new tests |
| `d52e107` | Hygiene cleanup — populate `.deprecated` marker + relocate `chatsession.md` → `docs/_archived/` (drift+hygiene audit findings) |

**Total Wave 3 part 1:** +12011 net lines, 79+ new tests passing, smoke test 99 PASS / 0 FAIL maintained.

**Wave 3 part 2 deferred** (depends on Squad C routes; can run when context permits):
- 10 Svelte SPA panels consuming Squad C routes (decision-queue, master-roles, registry, audit, vault-config, integrations, role-chat, federation, license, kg-search)
- `shared/ui/dashboard/responsive.css` per #28
- `shared/ui/login/` OIDC flow integration
- `shared/mcp/server_remote.py` (mTLS + bearer)
- Wave 6 `lib/` daemon deletions (12 files: team.sh, team-agent-daemon.sh, dashboard.html, engagement-hook.sh, etc.)

### Wave 2 — Work-item types + charters + devops/: COMPLETE 2026-05-18

5 commits:

| Commit | Scope |
|---|---|
| `cfc23e0` | Squad 1 — 6 NEW industry-anchored charters (devops/customer_support/compliance_officer/security_engineer/tech_writer/release_manager) + `lib/role-prompts/` deprecation notice. +1498 lines |
| `282f7d2` | Squad 3 — `devops/` top-level subsystem with 8 control planes + dispatcher + 3 MCP tools. +1912 lines, 21/21 tests |
| `d9c65f3` | Squad 2 — 7 work-item type schemas + 6 intake YAML templates + `build_dispatcher.py` routing + `ProjectType` Literal 4→7 + `#13` implementer_kind + autonomy_tier. +1381 lines, 92 tests |
| `4d46484` | Squad 4 — V33 audit_subsystem CHECK extension (applied LIVE) + V34 cross_llm provider backfill + stale tool-catalog test fix + auditor `requires_citation=True` tag + smoke-test ProjectType fixup |

**Total Wave 2:** +5200 net lines, 119 new tests passing, smoke test 99 PASS / 0 FAIL maintained.

**13 charter REBUILDs deferred to Wave 3** per Squad 1 Wave 3 handoff (architect→TOGAF+arc42, auditor→Cite-or-Refuse+NIST 800-53, conductor→Scrum+SAFe, datawright→DAMA-DMBOK+Kimball, engineer→#13 tier-bifurcation+Clean Code, operator→SRE-internal-platform-variant+12-factor, planner→PMBOK 7+Scrum, product→Inspired+Continuous Discovery+JTBD, qa→ISTQB, researcher→Cite-or-Refuse+IDEO+NN/g, ux→Nielsen+WCAG 2.2). `memory.md` + `seer.md` recommended DELETE (become Hub features per #3 + #27).

### Wave 1 — Substrate wiring: COMPLETE 2026-05-18

4 commits:

| Commit | Scope |
|---|---|
| `e6e54d2` | Drift correction — delete 3 `lib/*` files contradicting triage DELETE marking (Squad C audit caught) |
| `7c55e37` | Squad C — relocate `verify/docker-compose.override.yml` → `tools/verify-overrides/` (TRON subtree-pull conflict prevention) |
| `dc26c42` | Squad A — memory writer hooks (7 trigger points) + KG indexer (3 entry points) + calibration sink + Cite-or-Refuse middleware. +2682 lines, 51 new tests |
| `dc5a99d` | Squad B — cross_llm Provider Literal → 7 providers + notify vault wiring + 4 stub channels + 4 quiet-bug fixes + `shared/runtime/hygiene.py` (#34) + delete `shared/cost/prompt_cache.py`. +2220 −447 lines, 57 new tests |

**Total Wave 1:** +4902 net lines, 108 new tests passing, smoke test 99 PASS / 0 FAIL maintained.

Drift audit (Squad C) ran post-Wave-0; caught 3 lib/* files Pass 2 rebuilt-in-place that triage said DELETE — corrected in commit `e6e54d2` before Wave 1 dispatched.

### Next waves (per `docs/V3_BUILD_SEQUENCE.md`)

- **Wave 1** — substrate wiring (memory writer hooks + KG indexer + calibration sink + Cite-or-Refuse middleware + cross_llm/notify/memory refactors + 4 quiet-bug fixes) — **COMPLETE**
- **Wave 2** — work-item types + 6 new role charters
- **Wave 3** — Hub product (container + SPA + `lib/` retirement)
- **Wave 4** — federation + license + evidence + learning (4 parallel squads)
- **Wave 5** — DR + migration + landing-docs (3 parallel squads)
- **Wave 6** — mobile/voice/API scaffolds + `lib/` retirement complete

---

## v2 status (historical — superseded by v3)

The sections below describe the v2 state at the end of v2 wave 9. Most
of v2 is KEEP or REFACTOR for v3 (per `docs/V3_TRIAGE.md`). The dominant
subtraction is `lib/` (file-bus daemon system) which retires in Wave 3 +
Wave 6. The landing-docs big-bang rewrite (README / INSTALL / ARCHITECTURE
/ PRD / positioning) happens in Wave 5.

---

This is the single doc for "where are we, what's next, what to test." Complements (not replaces) `docs/BACKLOG.md` (the per-story tracker) and `docs/ARCHITECTURE.md` (the architecture plan).

---

## TL;DR

- **8 parallel-agent waves shipped** (Aug 16, 2026), unifying Spine + TRON into a single product
- **~131 of 180 backlog stories Done** (73%)
- **~296 files / ~40,200 LOC** added across 10 commits
- **All major subsystems exist**: Plan / Build / Verify / Orchestrator / Shared + cross-cutting (KG, MCP, cost router, audit, calibration, eval, skills, memory, validation, reproducibility, notifications)
- **TRON is integrated** under `verify/` via git subtree (full history preserved); adapters wired to real TRON code in waves 5-6
- **Smoke test status:** see §5 below

## 1. Architecture map (where the code lives)

```
spine/                                    # repo root
├── orchestrator/                         # central lifecycle state machine
│   ├── lib/                              # transition.sh, gate.sh, router.sh,
│   │                                       remediation.sh, portfolio.sh,
│   │                                       rollback.sh, build_failure_router.sh,
│   │                                       verify_dispatcher.sh, approval.py, ...
│   ├── state/                            # phases.yaml, V14 SQL
│   └── bin/                              # spine CLI (orchestrator/bin/spine)
│
├── plan/                                 # Plan subsystem
│   ├── artifacts/                        # PRD/TRD/Roadmap Pydantic; sdlc-pipeline
│   ├── templates/intake/                 # 6 project-type intake YAML
│   ├── swarm/                            # Tech Review Swarm (LangGraph)
│   ├── decomposer/                       # Roadmap decomposer
│   └── pipeline/                         # Manifest loader + capability + versioning
│                                          + project lock + phase evolution
│
├── build/                                # Build subsystem
│   ├── kg/                               # Knowledge Graph
│   │   ├── extractors/                   # tree-sitter extractor configs
│   │   ├── indexer/                      # cold-start + incremental indexer
│   │   ├── doc_parser/                   # markdown + REQ/PRD/TRD/role parsers
│   │   └── embeddings/                   # 3-provider embedder
│   ├── runtime/                          # per-role KG hooks + enrich_artifact
│   ├── bridge/                           # v1 daemon bridge (drains lib/)
│   └── migration/                        # 6-phase toolkit to move lib/ daemons
│
├── verify/                               # TRON, integrated (post `git subtree add`)
│   ├── tron/                             # TRON application code (preserved)
│   ├── alembic/, frontend/, ...          # TRON's existing layout
│   └── SUBSYSTEM_BOUNDARY.md             # Spine-side boundary doc
│
├── shared/                               # cross-cutting modules
│   ├── api/                              # FastAPI REST API
│   ├── audit/                            # audit log + exporter + redactor
│   ├── calibration/                      # Platt + banded calibration
│   ├── cost/                             # router, classifier, complexity scorer,
│   │                                       team_router, prompt_cache, user_override,
│   │                                       budget_rollup
│   ├── eval/                             # eval harness (loader, runner, scorer)
│   ├── mcp/                              # unified MCP server + 25+ tools
│   ├── memory/                           # vector-backed lessons
│   ├── notify/                           # 7-channel notifier
│   ├── reproducibility/                  # run manifest + replay + diff
│   ├── skills/                           # auto-triggering skills (5 ship)
│   ├── standards/                        # org bundle schema + validator + injector
│   │                                       + drift detector + 2 reference bundles
│   ├── ui/                               # approval queue UI + dashboard
│   └── validation/                       # cross-LLM consensus
│
├── lite/                                 # Claude-Code-plugin-only install path
│
├── db/flyway/sql/                        # V1-V21 migrations
│   (V1__init_core_schema through V21__spine_verify_schemas)
│
├── tools/                                # boundary check + Jira CSV converter
│
└── docs/
    ├── ARCHITECTURE.md                   # unified architecture (read first)
    ├── PRD.md                            # all REQ-INIT-N PRDs
    ├── BACKLOG.md                        # 9 INITs, 180 stories, sprint plan
    ├── PRACTICES.md                      # operating practices
    ├── STATUS.md                         # ← this file
    ├── positioning.md                    # one-page positioning
    ├── comparison.md                     # vs competitors
    ├── naming-decision.md                # naming ADR (recommends "Spine")
    ├── landing/                          # public landing page
    ├── research/                         # competitive landscape
    ├── diagrams/lifecycle.md             # ASCII + mermaid diagrams
    ├── reqs/                             # (removed — merged into PRD.md)
    └── IMPROVEMENT_CHECKLIST.md          # maintenance checklist (separate scope)
```

## 2. What's Done vs Pending (49 stories remain)

| INIT | Done | Total | % |
|---|---|---|---|
| INIT-1 Plan | 28 | 38 | 74% |
| INIT-2 Standards | 7 | 21 | 33% ← **biggest gap** |
| INIT-3 Trust | 21 | 23 | 91% |
| INIT-4 Absorption | 11 | 13 | 85% |
| INIT-5 GTM | 7 | 9 | 78% |
| INIT-6 KG | 19 | 28 | 68% |
| INIT-7 Build | 10 | 14 | 71% |
| INIT-8 Verify/TRON | 13+TRON | 22 | ~64% |
| INIT-9 Orchestrator | 20 | 26 | 77% |
| **Overall** | **~131** | **180** | **73%** |

For per-story detail: `grep -c '· `Done`' docs/BACKLOG.md` and similar greps.

## 3. The most important remaining stories

- **INIT-2 EPIC-2.2 individual MCP tool real impls** — STORY-2.2.2 through 2.2.6 (currently stubs in `shared/mcp/tools/orchestrator.py`)
- **INIT-2 EPIC-2.3 budget enforcement runtime detail** — admin override flow + per-role/project rollups (parts shipped)
- **INIT-6 EPIC-6.6.5/6** — planner + memory role-prompt KG integration (the runtime; the role prompts have the text)
- **INIT-8 EPIC-8.2 cross-cutting moves** — physically move `tron/standards/` → `shared/standards/`, etc. (the *plans* exist; the moves are operational)
- **INIT-3 EPIC-3.4.5** — eval dashboard view (small frontend story)
- **STORY-6.7.4** — KG embedding PII redactor
- **STORY-9.7.3** — audit query API specifics (largely done via REST API)
- **STORY-3.6.5** — calibration UI surface

## 4. To pick up: 3 likely next paths

1. **Integration smoke test** (you're here, per §5 below) — find what breaks when wired together
2. **Wave 9 design** — close remaining 49 stories in parallel
3. **Real-world dogfood** — use Spine to drive a small actual project; surface UX bugs

## 5. Smoke test — results 2026-05-16

**Goal:** stand up Postgres + run migrations + import code + dispatch a transition. Document each break.

**Verdict:** Core architecture sound. ~6 real integration bugs found, most are 1-line fixes. Schema + Pydantic + MCP registry + skills + CLI scaffolding all import cleanly. The DB layer works at the SQL level; the bash glue layer needs config + parsing fixes.

### Environment pre-check
- ✅ Docker available + Postgres + spine_watcher running (3-day uptime)
- ✅ Python 3.14.5
- ✅ 21 Flyway migrations on disk

### Results

| # | Step | Result | Finding |
|---|---|---|---|
| 1.1 | Flyway info | ⚠️ V1-V13 applied; V2 ignored (out-of-order); V14-V21 pending | F1 |
| 1.2 | `flyway migrate` | ❌ Refused: checksum mismatches on V1-V13 (pre-existing edits) | F2 |
| 1.3 | V2 via direct psql | ❌ `pgvector` extension not installed | **F3 (REAL)** |
| 1.4 | V14-V21 via direct psql | ✅ **All 6 schemas + 1 view applied** (V20 partial: schema OK, embedding table needs pgvector) | — |
| 2.1 | `from shared.mcp.tools import TOOL_REGISTRY; discover_tools()` | ✅ **27 tools register cleanly** across orchestrator/plan/build/verify/kg/iso/sandbox/standards/auditor modules | — |
| 2.2 | `shared.api.app` import | ❌ `ModuleNotFoundError: fastapi` | **F4** (expected: Python dep optional) |
| 2.3 | `shared.skills.registry.discover_skills()` | ✅ **5 skills load** with correct trigger metadata (priorities 150-250) | — |
| 2.4 | All 7 Pydantic schemas import | ✅ PRD, TRD, Roadmap, BuildArtifact, AuditRecord, router, classifier all clean | — |
| 3.1 | `BuildArtifact(...)` happy path | ⚠️ `metadata` field required without default (smoke test missed it) | **F5** (minor: schema should ship default factory for metadata) |
| 3.2 | `BuildArtifact` refuse-to-seal validator | ✅ **Fires correctly** on engineer+sealed+empty kg_impact with non-empty code_changes | — |
| 4.1 | `spine doctor` | ⚠️ Reports "postgres unreachable" — connection string wrong | **F6** |
| 4.2 | Project insert via psql | ❌ `pipeline_manifest_path` NOT NULL — original test omitted it | F7 (works after fix) |
| 4.3 | Project insert with all required fields | ✅ Project id=2 created at phase=intake | — |
| 5.1 | `transition.sh validate` (default conn) | ❌ Conn refused on port `33000` (mapped to **33001** per .env) | **F8 (REAL)** |
| 5.2 | `transition.sh execute` (SPINE_DB_URL=correct port) | ❌ Password auth failed: scripts default `spine:spine` but .env has real password | **F9 (REAL)** |
| 5.3 | `transition.sh execute` (full correct URL) | ❌ Rejects valid `intake → plan_in_progress` — awk fallback can't parse YAML inline arrays | **F10 (REAL)** |
| 5.4 | `gate.sh status` | ❌ `plan: unbound variable` from router.sh:31 | **F11 (REAL)** |
| 5.5 | Direct SQL transition (bypass bash) | ✅ **Project 2 advanced intake → plan_in_progress cleanly**, transition row written | — |

### Real bugs to fix (priority order)

**Tier 1 — Blocks runtime end-to-end (must fix before wave 9 or any dogfood):**

- **F3: pgvector extension missing.** V2 + V20 embedding tables silently skipped. Fix: change `db/docker-compose.yml` image from `postgres:16-alpine` to `pgvector/pgvector:pg16` (one-line change; container recreate). Or install via `CREATE EXTENSION` after `apt install postgresql-16-pgvector` in container.
- **F8: Bash scripts hardcode port `33000`.** Actual mapping per `.env` is `33001`. Fix: have bash scripts read `POSTGRES_HOST_PORT` from `db/.env` or accept `SPINE_DB_URL` override consistently. Affects `transition.sh`, `gate.sh`, `router.sh`, `remediation.sh`, `portfolio.sh`, `rollback.sh`, `build_failure_router.sh`, `verify_dispatcher.sh`, the spine CLI.
- **F9: Default `spine:spine` password mismatch.** Same root cause as F8. Fix: load `.env` automatically.
- **F10: transition.sh can't parse inline YAML arrays.** `next: [plan_in_progress]` reads as empty when yq isn't installed. Fix: install yq as hard runtime dep OR rewrite awk fallback to handle inline arrays OR convert `phases.yaml` to multi-line list syntax.
- **F11: `gate.sh` triggers unbound-variable in `router.sh:31`.** Bash bug from sourcing chain. Fix: trace the var, add `: ${plan:=}` default OR initialize before source.

**Tier 2 — Quality of life:**

- **F2: Flyway checksum mismatches.** Pre-existing modifications to V1-V13. Run `flyway repair` once to align. Then future migrations apply cleanly via `make migrate`.
- **F4: FastAPI not installed.** Document Python deps in install.sh or add per-subsystem `pyproject.toml` (most should already have one).
- **F5: BuildArtifact requires metadata.** Add `default_factory=ArtifactMetadata.now` for ergonomics.
- **F6: `spine doctor` connection probe** uses default URL even when env override exists — same fix as F8/F9.
- **F7: pipeline_manifest_path NOT NULL** is correct schema behavior, but `spine project new` CLI should default it from active manifest if not provided.

### Tier 1 fix budget

All 5 Tier 1 fixes are bash/yaml line-level changes. **Recommended wave 9** = these 5 fixes + a smoke-test harness as `tools/smoke-test.sh` that runs this exact sequence and reports pass/fail. ~1 agent for fixes + 1 agent for harness = 2 agents.

### Wave 9 outcome (2026-05-16)

All 5 Tier 1 fixes shipped + smoke harness automates the §5 sequence.

| Fix | Status | Where |
|---|---|---|
| F3 pgvector | ✅ | `db/docker-compose.yml` → `pgvector/pgvector:pg16`; rationale in `db/PGVECTOR_NOTE.md` |
| F8 hardcoded port | ✅ | New `orchestrator/lib/_env_loader.sh`; 13 scripts source it instead of defaulting `SPINE_DB_URL` |
| F9 default password | ✅ | Same `_env_loader.sh` reads `db/.env` |
| F10 awk inline-array | ✅ | `transition.sh` `_phase_field_list` rewritten — one item per line; `_in_list` IFS hardened; `gate.sh` call sites adjusted (`head -n1` / `tr '\n' ' '`) |
| F11 unbound `plan` | ✅ | `router.sh` array switched from inline `[plan]=…` literal to per-key assignment (set -u + source-time safe) |
| Smoke harness | ✅ | `tools/smoke-test.sh` (373 lines, 7 phases, text/json/junit, exit codes 0/1/2/3/64) + `tools/smoke-test_README.md` |

**To verify:** `bash tools/smoke-test.sh` (after `make up` if not running). Tier 2 (F2/F4/F5/F6/F7) still pending — non-blocking.

### Wave 9 verification run (2026-05-16, post-pgvector swap)

After `docker compose down && docker compose up -d postgres` (image now `pgvector/pgvector:pg16`) + manual `psql -f db/flyway/sql/V2__spine_kg_schema.sql` + same for `V20__spine_memory_schema.sql`:

```
PASS=39  FAIL=0  WARN=1  SKIP=0  INFO=3   (43 total checks)
```

- The single WARN is `env.yq missing` — purely informational; the awk fallback (F10 wave 9 fix) handles the manifests.
- All 3 INFO are correctly-reported optional deps (yq, fastapi, doctor's optional probe).
- Two harness portability bugs surfaced + fixed in commit `2b7308d`: `declare -A` → parallel indexed arrays (bash 3.2 compatible), and the schema-loop `for sch in $schemas` was bitten by file-level `IFS=$'\n\t'` — converted to a real array.

**F2 follow-up created by this run:** Flyway history is now further out-of-sync — V2 + V14-V21 are applied at the DB level but not in `flyway_schema_history`. `flyway repair` cleared V1-V13 checksums; pending work is to `INSERT` history rows for the manually-applied versions (or `flyway baseline -baselineVersion=21`) so the in-compose `flyway` service stops erroring and `docker compose up watcher` no longer needs `--no-deps`.

## 6. First dogfood — 2026-05-16

**Target:** drive a fresh project ("downloads-organizer") through `spine project new` → intake → PRD → roadmap to see where the human-facing flow breaks.

**Verdict:** Backend is more real than the front door. 22 of 27 MCP tools have actual implementations (all of KG, all ISO scanners, sandbox, verify, standards, plan/build dispatch). The 5 stubs are exactly the orchestrator front-door tools that the CLI calls — so the user-facing flow is gated by a wall before it touches any of the real code.

### Bugs surfaced (in the order they hit)

| # | Where | Bug |
|---|---|---|
| D1 | `orchestrator/bin/spine` | Shipped without exec bit — `./spine help` permission-denied; needs `chmod +x` |
| D2 | `spine doctor` | Warns "no mcp transport found" but `project new` plows ahead with HTTP POST anyway and dies |
| D3 | `install.sh` | Doesn't install the `mcp` Python SDK or any other Python deps |
| D4 | `install.sh` | Doesn't set up a Python venv; PEP 668 system Python refuses `pip install` |
| D5 | `shared/mcp/server.py:128/133` | `logger.info(..., extra={"name": ...})` — `name` is a reserved LogRecord field; Python 3.14+ raises **(fixed in this commit)** |
| D6 | `shared/mcp/server.py:138` | `FastMCP.run(host=, port=)` — current SDK signature has no host/port; takes them at construction, transport is `"streamable-http"` not `"http"` **(fixed in this commit)** |
| D7 | `orchestrator/bin/spine` `_mcp_call` HTTP fallback | POSTs raw to `/tools/<name>` with no session handshake; FastMCP Streamable-HTTP needs `initialize` → session-id → POST `/mcp`. The CLI was written against a REST-style endpoint that doesn't exist. Needs full rewrite as a Streamable-HTTP client OR an in-process Python fallback |
| D8 | `shared/mcp/tools/orchestrator.py` | **Critical:** `project_create`, `project_status`, `phase_advance`, `approval_grant` are all stubs returning `status="stub_implementation"` — no DB write, no transition, no token. Smoke test passes because tools register and Pydantic validates, but no project ever lands |
| D9 | CLI `spine project new --type cli` | CLI accepts any `--type` string; backend Literal is `greenfield|evolve|audit_only|operate`. No client-side validation |

### Stub map — what's still needed

| Tool | Module | Underlying real code that already exists |
|---|---|---|
| `project_create` | `orchestrator.py` | `INSERT INTO spine_lifecycle.project` + audit row + initial phase=intake (see smoke test SQL for shape) |
| `project_status` | `orchestrator.py` | `SELECT FROM spine_lifecycle.project` + `phase_history` |
| `phase_advance` | `orchestrator.py` | `orchestrator/lib/transition.sh execute` already works; needs HMAC verify via `approval.py` |
| `approval_grant` | `orchestrator.py` | `orchestrator/lib/approval.py` already has HMAC sign/verify; needs persistence |
| `graph_query` | `kg.py` | The 8 other KG tools work; this one is the open-ended Cypher-ish query |

### Highest-leverage next step

**Implement the 4 orchestrator front-door stubs** (STORY-9.9.1 / 9.2.1 / 9.3.2 from the original backlog). All four wrap code that already exists and is tested — they're glue, not new features. Estimated 1 small agent / a few hours. After that, also either:
- add an in-process Python fallback to `orchestrator/bin/spine` (cheapest), OR
- write a proper Streamable-HTTP MCP client into `_mcp_call`, OR
- replace the bash CLI with a Python `spine.cli` that calls tools in-process.

The bash CLI rewrite (option C) is the highest-leverage long term but the most invasive. Option A unblocks dogfood tomorrow.

### Cleanup

Smoke-test artifacts left in DB:
- `spine_lifecycle.project` row id=2 (`smoke-test-001`)
- 1 row in `spine_lifecycle.transition` for that project
- All 9 schemas created (`spine_audit`, `spine_calibration`, `spine_eval`, `spine_kg`, `spine_lifecycle`, `spine_memory`, `spine_recording`, `spine_verify_audit`, `spine_verify_threat_intel`)

Run `DELETE FROM spine_lifecycle.project WHERE name='smoke-test-001'` to reset. Schemas can stay.

---

## 7. Bootstrap closed — 2026-05-17

**Goal:** make a fresh clone runnable in one command (was ~7 manual steps across two databases, two migration tools, a venv, and pip installs).

**Verdict:** Done. `git clone && make bootstrap` brings the whole v2 stack up; `bash tools/smoke-test.sh` is the acceptance gate.

### What landed

| File | Purpose | LOC |
|---|---|---|
| `tools/bootstrap.sh` | One-command cold-start (preflight → venv → pip → spine pg → tron pg → flyway → alembic → smoke). Idempotent: re-runs in seconds when nothing changed. | ~190 |
| `tools/spine-flyway-sync.sh` | Reconciles `flyway_schema_history` with the actual DB (the F2 follow-up — V2 + V14-V21 were applied via direct psql during wave 9 and the history was never updated). Inserts the missing rows with flyway-compatible CRC32 checksums. Idempotent and no-op on a clean DB. | ~150 |
| `requirements.txt` (new, root) | The actual Spine v2 runtime pip set — MCP/FastAPI/pydantic/SQLAlchemy[asyncio]/asyncpg/temporalio/bandit/alembic/psycopg2/pyyaml/etc. Curated subset of `verify/requirements.txt`'s 84 deps + Spine-specific. | ~45 |
| `Makefile` (top-level, extended) | New targets: `bootstrap`, `bootstrap-clean`, `nuke`, `doctor`, `smoke`, `flyway-sync`. All previous targets preserved. | +35 |
| `orchestrator/bin/spine` (`cmd_doctor` rewrite) | Was 3 checks; now 9 sections: host binaries, venv + imports, spine pg, spine schemas, tron pg, TRON AuditManager constructable, MCP transport, bundle, API keys. `--verbose` adds remediation hints. Exits 0/1/4. | +120 |
| `tools/smoke-test.sh` (phase 12) | New "bootstrap artifacts" phase — structural checks (Makefile has `bootstrap` target, `requirements.txt` exists, `tools/bootstrap.sh` exists, `make help` parses). Does *not* invoke bootstrap itself (circular). | +25 |

### F2 cleanup

Before: `flyway info` showed V2 = `Ignored`, V14-V21 = `Pending`, even though all 9 schemas + tables existed in the DB. `docker compose up watcher` failed its `flyway: service_completed_successfully` dependency.

After: `tools/spine-flyway-sync.sh` (called from `tools/bootstrap.sh` as step 6) inserts the missing rows with correct CRC32 checksums; `flyway -outOfOrder=true migrate` is then a no-op; `flyway info` shows all migrations as `Success`. `docker compose up watcher` no longer needs `--no-deps`.

### What's left

- **`spine doctor`** is now a real surface — extend further as new subsystems land (KG ingestion, audit query API, calibration UI, etc.).
- **CI**: a GitHub Actions workflow that runs `make bootstrap && bash tools/smoke-test.sh --ci` on every PR. Out of scope for this pass; the pieces are in place.
- **Real MCP tool stubs** (`graph_query`, `iso_invoke`, `org_standards_get`) — explicitly out of scope here; tracked in the §6 stub map.

---

## 8. Sandbox additionalDirectories gotcha — for future dogfooders

Spine v2 dogfood is an "external implementer" model: Spine produces a Build Brief, you (or an agent — typically a Claude Code subagent via the Agent tool) build the artifact *somewhere else*, then `spine build report` ingests it back. The boundary matters because the implementer process is sandboxed differently than the parent Spine session.

**The trap.** When the implementer is a Claude Code subagent launched via the Agent tool, that subagent does **not** inherit `/add-dir` directories from the parent session. It gets:
- the parent session's `additionalDirectories` array from `settings.json` (if set), plus
- the `permissions.allow` entries in `.claude/settings.local.json`.

That's it. Any directory the parent added live via `/add-dir` is invisible to the child.

**For build agents that need to write outside the Spine repo (the faithful workflow), do one of:**
- (a) Add explicit `Bash`/`Write`/`Edit` permission entries to `.claude/settings.local.json` for the target paths *before* spawning the subagent, **or**
- (b) Build inside a subpath under an already-allowed dir — e.g. we used `~/Projects/downloads-organizer/.dogfood-scratch/` as the scratch target because `~/Projects/downloads-organizer/**` was already approved.

**Concrete bug we hit.** `/tmp/dogfood-downloads/**` allow rules in `settings.local.json` did **not** take effect for `Bash` invocations from subagents, even with broad `Bash(touch *)` patterns. Likely harness-specific (Claude Code v2.1.141). The workaround was option (b) — build under `~/Projects/<project-name>/.dogfood-scratch/` rather than `/tmp/`.

See commits `a347e37` through `dd2f1e4` for the full dogfood loop that surfaced this.

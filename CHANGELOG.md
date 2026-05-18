# Changelog

All notable changes to Spine will be documented in this file. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project loosely tracks semantic versioning (the v1 / v2 / v3 framings
below predate that convention and are preserved verbatim as historical
context).

> **Doc trinity.** For the canonical view of where Spine is today see
> [`docs/STATUS.md`](docs/STATUS.md), [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) (34 locked
> decisions), [`docs/V3_TRIAGE.md`](docs/V3_TRIAGE.md), [`docs/V3_BUILD_SEQUENCE.md`](docs/V3_BUILD_SEQUENCE.md), and
> [`docs/V1_SHIP_CHECKLIST.md`](docs/V1_SHIP_CHECKLIST.md). The CHANGELOG follows; it does not lead.

---

## [Unreleased] — v1.0 (target ship pending `docs/V1_SHIP_CHECKLIST.md` §0–§7)

This entry covers the full **v3 rebuild** (the "Hub-as-product" rewrite)
landed in 57 commits since `1da7148`. The product framing changed
materially: v1/v2 were a file-bus orchestration framework that teams
dropped into their own repos; v3 is a containerized **Hub** that
customers run on a laptop / BYOC cloud / their own K8s / on-prem and
operate as a managed AI engineering organization (per `docs/V3_DESIGN_DECISIONS.md` #3).

Code is feature-complete against the 34 locked decisions; remaining v1.0
work is operational (CI/CD pipeline, vendor vault, customer-facing
infra, deployment-shape rehearsals, launch artifacts) and tracked in
`docs/V1_SHIP_CHECKLIST.md` §0–§7.

### Added — Wave 0: Foundations (2026-05-18)

Substrate libraries + containerized prerequisites. 7 focused commits.

- `shared/secrets/` — vault adapter library + `InMemoryAdapter` + CLI wrapper (`3bc6805`). Closes #9 architectural primitive.
- `shared/llm/` — single LLM call surface, 7 provider adapters (Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / vLLM) + retry + streaming (`7a34d58`). Closes #2.
- `shared/identity/` — Keycloak OIDC client + 5-tier capability matrix (`882b8a6`). Closes #25.
- `vault/` — OpenBao container subsystem + Day-0 wizard + 5 unseal/DR runbooks (`a756b2f`). #9 Day-0 default.
- `keycloak/` — Keycloak container subsystem + 5 IdP presets (`1a96a41`). #25.
- `db/flyway/sql/V22–V32` — 11 new schemas (license / federation / hub / evidence / identity / devops / workitem / learning / provider / cloud / dr) (`5c17e7a`). Applied LIVE against the dev Postgres transactionally.
- Pass-2 refactors — closed 5 vault violations + `verify/.env` vault-refs + `InMemoryAdapter` / `orchestrator.py` / `smoke-test.sh` downstream fixups (`2212742`). #9 no-exceptions.

**Wave 0 totals:** ~12,858 net lines added, 0 vault violations remaining,
smoke test 99 PASS / 0 FAIL / 1 WARN / 0 SKIP maintained.

### Added — Wave 1: Substrate wiring (2026-05-18)

Cross-cutting hooks that every later wave depends on. 4 commits.

- Drift correction — deleted 3 `lib/*` files Pass-2 rebuilt-in-place that triage marked DELETE (`e6e54d2`). Caught by Squad C drift audit before Wave 1 dispatched.
- Relocated `verify/docker-compose.override.yml` → `tools/verify-overrides/` to prevent TRON subtree-pull conflicts (`7c55e37`).
- Squad A — memory writer hooks (7 trigger points per #27) + KG indexer (3 entry points) + calibration sink + Cite-or-Refuse middleware (`dc26c42`). Closes #12 + #27 substrate.
- Squad B — `cross_llm` Provider Literal → 7 providers + notify vault wiring + 4 stub channels + 4 quiet-bug fixes + `shared/runtime/hygiene.py` (`dc5a99d`). Closes #34.

**Wave 1 totals:** +4,902 net lines, 108 new tests passing.

### Added — Wave 2: Work-item types + new charters + Operate subsystem (2026-05-18)

7 work-item types end-to-end + 6 industry-anchored new role charters + the `devops/` subsystem. 5 commits.

- Squad 1 — 6 NEW industry-anchored charters: `devops` / `customer_support` / `compliance_officer` / `security_engineer` / `tech_writer` / `release_manager` + `lib/role-prompts/` deprecation notice (`cfc23e0`). Per #7 + #19.
- Squad 3 — `devops/` top-level subsystem with 8 control planes + dispatcher + 3 MCP tools (`282f7d2`). Closes #11.
- Squad 2 — 7 work-item type schemas + 6 intake YAML templates + `build_dispatcher.py` routing + `ProjectType` Literal 4→7 + `implementer_kind` + `autonomy_tier` fields (`d9c65f3`). Closes #19 + #13.
- Squad 4 — V33 audit_subsystem CHECK extension (applied LIVE) + V34 cross_llm provider backfill + stale tool-catalog test fix + auditor `requires_citation=True` tag + smoke-test ProjectType fixup (`4d46484`).
- Wave 2 STATUS section (`cb431a8`).

**Wave 2 totals:** +5,200 net lines, 119 new tests, smoke 99/0 maintained.

### Added — Wave 3 part 1: Hub product + runtime migration + charter REBUILDs + API expansion (2026-05-18)

5 commits.

- Squad A — `shared/runtime/` migration from `lib/` (9 keeper bash files: vitals / heartbeat / watchdog / notify / executor / usage-parsers / file-lock / updater / db-outbox) + `ALLOWED_SUBSYSTEMS` 'devops' extension + V35 Flyway DB CHECK extension applied LIVE (`18a82d7`).
- Squad B — `hub/` containerized product subsystem (multi-arch Dockerfile + docker-compose with vault+keycloak+pg+flyway + entrypoint with wait-for-X + Day-0 wizard with 7 steps fully flag-driven + smoke test) (`2f02370`). Closes #3.
- Squad D — 13 existing charter REBUILDs against industry standards: architect→TOGAF, auditor→NIST 800-53 + Cite-or-Refuse (#12), conductor→Scrum + SAFe, datawright→DAMA + Kimball, engineer→#13 tier-bifurcation + Clean Code, operator→SRE-internal-variant + 12-factor, planner→PMBOK 7, product→Inspired + JTBD, qa→ISTQB, researcher→#12 Cite-or-Refuse + IDEO + NN/g, ux→Nielsen + WCAG 2.2 (`ec112df`). Closes #7.
- Squad C — `shared/api/` REBUILD: `dependencies.py` now uses `shared.identity.current_user` + asyncpg pool (vault DSN) + remote-MCP placeholder; 7 NEW routes (decisions / role_chat / registry / vault_config / integrations / federation / license); 3 NEW middleware (OIDC cookie/session, feature-flag enforcement) (`496962f`).
- Hygiene cleanup — populated `.deprecated` marker + relocated `chatsession.md` → `docs/_archived/` (`d52e107`).
- Wave 3 part 1 STATUS (`1a83a63`).

**Wave 3 part 1 totals:** +12,011 net lines, 79+ new tests, smoke 99/0 maintained.

### Added — Wave 3 part 2: Hub SPA + remote MCP (2026-05-18)

7 commits.

- Drift fixes — 4 stale deletes + recovery path + `#34` hygiene Makefile target (`480c90b`).
- Squad SPA1 — SvelteKit 2 + Svelte 4 + Tailwind scaffold + 2 example panels (decision-queue + role-chat) + login UI + 9 reusable components + Hub Dockerfile + FastAPI mount (`e8d83d2`). Per Part 4.1 Svelte choice.
- Squad SPA4 — `shared/mcp/server_remote.py` remote MCP transport (mTLS + bearer via vault) + 30 new tests; unlocks federation tool delegation (`e32e283`).
- Squad SPA2 — 5 panels (master-roles / registry / audit / vault-config / integrations) + 12 new types (`f132103`).
- Squad SPA3 — 3 panels (federation / license / kg-search) + `shared/api/routes/kg.py` NEW REST backend + 8 tests + OpenAPI→TS codegen pipeline + types.ts façade (`6da82c9`).
- Sidebar: all 10 panels flipped to `shipped: true` + Wave 3 part 2 STATUS section (`4234ccf`).

**Wave 3 part 2 totals:** +12,780 net lines, 173+ new tests, all 10 Hub
surfaces shipped, smoke 99/0 maintained.

### Added — Wave 3.5: Drift remediation + ship-gate squads (2026-05-18)

3 high-leverage fixes closing audit findings + 3 ship-gate squads. 6 commits.

- **FIX3** — 5 backend gaps surfaced by SPA squads + V36 decisions schema (`668f102`). Closes registry runtime fields / audit filters+pagination / vault per-path rotation timestamps / IntegrationDetail `disabled` enum / decisions store gap.
- **FIX1** — routed TRON LLM through `shared/llm/` (`7896ca6`). Closes HIGH-severity drift Finding 1 (#6 commitment unfulfilled across 40 commits).
- **FIX2** — created canonical `shared/integrations/` package (`4ecae35`). Closes HIGH-severity drift Finding 2 (layout violation). New package: `base.py` / `twilio.py` / `teams.py` / `pagerduty.py` / `github.py` / `linear.py` + 5 test files / 59 tests. Re-export shims keep ZERO public-API breakage (`voice/twilio_adapter.py`, `migration/onboarding.py`, `shared/notify/channels.py`, `evidence/exporters/_base.py`, `shared/mcp/tools/integrations.py`).
- **OP1** — Shamir 3-of-5 reconstructor + splitter (`a93fa39`). Closes V1 ship gate #23 / Part 4.3.
- **OP3** — Wave 4 follow-ups convergence cleanup (`2dd15af`). Closes 6 items.
- **OP2** — per-cloud BYOC provisioners (`d42840a`). Closes #15 + #17 + #20.

### Added — Wave 4: Federation + License + Evidence + Learning (2026-05-18)

4 parallel squads + housekeeping. 5 commits.

- Squad D — Smart Spine 3-tier learning loop (`118688d`). Closes #27. scope resolver + 3-tier contribute gates + cross-org consent registry + k=5 anonymizer + vendor self-improvement Tier 3 hook + 4 MCP tools.
- Squad A — Hub-to-Hub federation (`64db848`). Closes #4 + #10 + #16. hub_registry (consumes `hub/_state/hub_id.txt`) + upstream_client (mTLS + bearer via vault) + downstream_router + update_cascade (signed bundle distribution + per-tier approval gate) + consent engine + 4 MCP tools.
- Squad C — Evidence Store (`f366a11`). Closes #24. 5 collectors (audit_chain / role_decision / vault_access / deploy / approval) + 3 real exporters (Vanta / Drata / Secureframe) + 3 v1.1 stubs (Tugboat / StrikeGraph / Thoropass) + two-party SHA-256 attestation per V25 + 4 MCP tools.
- Squad B — Feature-flag licensing (`c96f23a`). Closes #23. Ed25519 signed bundle verifier with `TRUSTED_VENDOR_FINGERPRINT` trust anchor + periodic re-verify + feature_flags evaluator + hash-chained quota ledger + `tools/license-sign.sh` (vendor-side per Part 4.3 Shamir 3-of-5) + 3 MCP tools.
- Housekeeping — `test_server_smoke` `EXPECTED_TOOL_COUNT` 27→42 + WAVE-* story-id prefix accepted alongside STORY-* (`7c3f8e0`).

**Wave 4 totals:** +11,590 net lines, 189 new tests, 15 new MCP tools.

### Added — Wave 5: DR + Migration + Landing-docs big-bang (2026-05-18)

3 commits.

- Squad F migration (`7a4c3ce`). Closes #33 A+B+D. `migration/` subsystem: GitHub+Linear onboarding + signed-tarball portability (round-trip property PROVEN: byte-identical export A→import→export B) + spine_version migrator with N-2 cross-version compat + downgrades BLOCKED + 4 MCP tools. `lib/spine-migrate.py` relocated to `migration/_v1_v2_migrator_legacy.py`.
- Squad E recovery (`6138a11`). Closes #31 + #32. `recovery/` 12-layer DR: WAL+snapshot backups to S3/GCS/Azure/MinIO/Wasabi via CLI subprocess + tested restore + heartbeat + cross-region STUB v1.0 (default-OFF per Part 4.4) + auto-recovery via watchdog adapter + auto-generated DR runbook + `tools/dr-test.sh` + 5 MCP tools.
- Squad G landing-docs (`9728427`). T6 highest-leverage UX bug: REBUILT all 7 v1-framing landing docs (`README` / `INSTALL` / `install.sh` / `docs/PRD.md` / `docs/positioning.md` / `docs/ARCHITECTURE.md` [REFRESH] / `db/README.md`) + 6 NEW operational guides (`HUB_OPERATIONS_GUIDE` / `DEPLOYMENT_SHAPES` / `FEDERATION_GUIDE` / `SECURITY_GUIDE` / `LICENSING_GUIDE` / `DR_RUNBOOK`). v2 framing archived.

**Wave 5 totals:** +13,798 net lines, 145 new tests, smoke 99/0 maintained.

### Added — Wave 6: Mobile / Voice / API+MCP scaffolds + `lib/` retirement (2026-05-18)

3 commits.

- Stream H+I mobile + voice (`a75e6a4`). Closes #28 + #29. `mobile/api/routes` (Bearer-auth compact JSON for approvals/briefings/status + APNs/FCM action endpoint) + `mobile/ios` + `mobile/android` placeholders with vault-referenced signing + `voice/api/routes` (Twilio webhook with real HMAC-SHA1 signature validation) + `voice/twilio_adapter` + scaffolds. +1,928 lines / 29 tests.
- Stream J API + MCP heavier (`3be6c70`). Closes #30. `shared/api/openapi_spec` (OpenAPI 3.1 + 4 server templates + reusable Citation schema + error envelopes + Keycloak security schemes) + `shared/api/versioning` (v2 current; v1→v2 redirect with RFC 8594 Sunset header) + `shared/api/rate_limit` (per-(org,flag) token bucket from `spine_license.feature_flag`) + envelopes REFACTOR (`feature_flag_required` + `actor_token_claims`) + `shared/mcp/tools/integrations` (3 MCP tools) + `EXPECTED_TOOL_COUNT` 42→54. +2,749 lines / 50 tests.

### Added — ship-gate audit fixes (2026-05-18)

- `8dec34b` — closed 3 must-fix gaps from the final `chatsession.md` audit.
- `d4c205d` — pinned `pyshamir>=1.0.0` in `requirements.txt`; activates Wave 3.5 OP1 Shamir tests in CI.
- `81fa03b` — closed 5 issues from local v1.0 checklist execution.
- `8eb55c9` — canonical `docs/V1_SHIP_CHECKLIST.md` published.

### Removed — `lib/` retirement (Wave 6, commit `19f745f`)

DELETE 17 `lib/*` files (1,262 LOC `dashboard.html` + 1,001 LOC
`team-agent-daemon.sh` + 1,087 LOC `team.sh` + 14 others) + Makefile /
`db/Makefile` / `shared/runtime/watchdog.sh` updates removing references.
Kept `lib/role-prompts/` per `shared/charters/README.md` documented intent
(deprecated; readable reference). `lib/` shrunk from 34 files / ~8,000 LOC
to 17 files / 1,095 LOC.

### Removed — drift correction (Wave 1, commit `e6e54d2`)

Deleted 3 `lib/*` files that Wave-0 Pass-2 rebuilt-in-place
contradicting the triage DELETE marking. Drift audit caught this before
Wave 1 dispatched.

### Changed

- All LLM calls now route through `shared/llm/` (Wave 0 + Wave 3.5 FIX1). Anthropic-only `prompt_cache.py` retired; provider-trait pattern installed.
- All secrets now route through `shared/secrets/` vault adapters (Wave 0 Pass 2). No `env://`; no built-in secret store. 5 prior vault violations closed (`approval.py`, `_env_loader.sh`, `share-pg.sh`, `run-standalone-watcher.sh`, `spine-connect.sh`).
- Identity now Keycloak-mediated end-to-end (Wave 0 + Wave 3 Squad C middleware). `shared/api/dependencies.py` resolves users via `shared.identity.current_user` + asyncpg pool.
- File-bus daemon framing (v1/v2) replaced with containerized Hub (Wave 3 Squad B + lib retirement). The Hub IS the product; the file-bus pattern is gone.
- 13 existing role charters REBUILT against industry standards (Wave 3 Squad D). `memory.md` + `seer.md` charters intentionally retired (become Hub features per #3 + #27).
- 10 cross-cutting bash helpers in `lib/` migrated to `shared/runtime/` (Wave 3 Squad A). Bash core preserved; Python wrappers layered.
- `EXPECTED_TOOL_COUNT` 27 (v2) → 54 (v3 Wave 6). MCP catalog: orchestrator / plan / build / verify / kg / iso / sandbox / standards / auditor / devops / federation / license / evidence / learning / recovery / migration / mobile / voice / integrations.

### Security

- **Vault-only secrets** per #9. No `env://`. No exceptions. `tools/byoc/*` + `shared/secrets/*` + Day-0 wizard all enforce this. Final grep audit listed in `V1_SHIP_CHECKLIST.md` §4.
- **License bundle Ed25519 signature verification** per #23. `license/bundle_verifier.py` enforces `TRUSTED_VENDOR_FINGERPRINT` baked at build time + periodic re-verify + feature-gate-time verify.
- **Shamir 3-of-5 key custody** for the vendor license signing key per Part 4.3. `tools/license-sign.sh shamir-split` + `shamir-recover` shipped; pyshamir>=1.0.0 pinned.
- **Hash-chained audit ledger** per #24. Every action writes a `spine_audit.audit_event` row chained to the prior row's SHA-256. Two-party attestation pattern (customer auditor + Vanta/Drata).
- **mTLS + bearer for federation** per #10 + #16. `shared/mcp/server_remote.py` validates both; vault paths `federation/mtls/<role>/{cert,key}` + `federation/bearer/<role>`.
- **Cite-or-Refuse** for verify-class roles per #12. Auditor / QA / Verify roles must cite KG node ID / file:line / prior audit row hash or refuse. Refusal is itself an audit event.
- **Rotation required before v1.0** per #9: TRON Postgres / Redis / MinIO / Grafana passwords were `tron_dev_only` in old `verify/.env` (single commit `493b07c`). Rotate vault paths per `V1_SHIP_CHECKLIST.md` §4.

### Deprecated

- `lib/role-prompts/*` — kept as readable reference for the v1/v2 file-bus framing; canonical charters now in `shared/charters/`. Will be `git rm`d post-v1.0.
- v1 file-bus orchestration pattern (managers + workers + `.planning/orchestration/`). Replaced by containerized Hub + project Spines. The 17 retired `lib/` files are listed in commit `19f745f`.
- `memory.md` + `seer.md` role charters intentionally retired (Wave 3 Squad D). Their responsibilities are now Hub features per #3 + #27 (Memory writer hooks + Decision queue + Master role aggregation).

### Migration notes (v1 → v2 → v3)

- **v1 → v2.** Captured in `migration/_v1_v2_migrator_legacy.py` (relocated from `lib/spine-migrate.py`); SQLite + dashboard snapshot conversion. Still works for legacy customers; not a primary path.
- **v2 → v3.** Use `migration/spine_version.py` per #33 D. N-2 cross-version compat commitment; downgrades BLOCKED. Wired into update-distribution flow per #16 with customer-admin approval gate per migration.
- **Customer Spine portability** per #33 B (signed-tarball export/import) is fully built Day 1. Round-trip byte-identical property PROVEN. Spine company's "no lock-in" claim is structurally true.

### v1.0 ship gate items (operational, not code)

Per `V1_SHIP_CHECKLIST.md` §0–§7. Not blocking the code-complete claim;
blocking the customer-facing ship:

- CI/CD pipeline (multi-arch Docker images for `hub`/`vault`/`keycloak` + Sigstore cosign + SLSA L2 provenance attestation; SPA build pipeline; Flyway migration gate; smoke test in CI; lint clean; `make hygiene` clean; OpenAPI snapshot drift gate).
- Vendor production setup (vendor vault with Shamir 3-of-5; license signing key generated + 5 custodians provisioned; rehearsal; vendor Keycloak; license-issuance audit chain; vendor SOC 2 pipeline; status page; vendor heartbeat).
- Customer-facing infra (`spine.dev` landing; `try.spine.dev` demo sandbox per #15; `status.spine.dev`; community server; docs site; DNS + TLS; email infrastructure).
- Closed-source security compensations per #18 (SOC 2 Type II observation start; independent pen test; source escrow; bug bounty; VDP; TRUSTED_VENDOR_FINGERPRINT verification; final secret-grep audit; TRON dev-password rotation; all vault paths populated with real values).
- Deployment-shape verification (laptop / BYOC AWS+Railway / customer K8s / on-prem K8s / DR drill).
- Customer onboarding flow end-to-end (sign-up; delegation; provisioning; wizard handoff; first decision card; license bundle issuance; first project create).
- Launch artifacts (3 design partners; case study drafts; founder presence; public roadmap; pricing decision deferred per #23 but feedback-collection plan locked; EULA/MSA/DPA drafts; support triage).

### v3 cumulative totals

| Metric | Value |
|---|---|
| Commits (since v3 start `1da7148`) | 57 |
| Net lines added | ~85,000+ across all subsystems |
| New top-level subsystems | 10 (hub / federation / devops / vault / keycloak / license / evidence / learning / recovery / migration) |
| New shared libraries | 6 (`shared/{secrets, llm, identity, runtime, charters, integrations}`) |
| New Flyway migrations | 15 (V22–V36) |
| MCP tools | 54 registered (was 27 v2 → 54 v3) |
| Role charters | 18 industry-anchored (6 NEW Wave 2 + 12 REBUILT Wave 3; `memory.md`+`seer.md` intentionally deprecated to Hub features per #3/#27 — net 18, not 19) |
| New tests | 700+ |
| Smoke test | **99 PASS / 0 FAIL** maintained throughout |
| `lib/` retirement | 34 files / ~8,000 LOC → 17 files / 1,095 LOC (all deprecated `role-prompts/`) |
| Landing docs | All 7 v1-framing docs REBUILT + 6 NEW operational guides |
| 34 design decisions | All locked + implemented (or explicitly stubbed per scaffold framing for #28/#29/#30) |
| Drift audits | Run at Wave 1 + Wave 2+3 milestones — ON-TRACK both times |

---

## [v1.4.5] — 2026-05-11

### Packaging & hygiene

- **`lib/spine-migrate.py`** — versioned in the bundle; **full `install.sh`** copies it to **`scripts/spine-migrate.py`** (v1→v2 SQLite + dashboard snapshot). Maintainers: edit **`lib/spine-migrate.py`** only; **`make db-migrate` / `db-watch`** keep using **`scripts/spine-migrate.py`** after install.
- **`lib/tests/test-lib-scripts-sync.sh`** — **`cmp`** parity now includes **`spine-migrate.py`** (when both **`lib/`** and **`scripts/`** copies exist).
- **Installer Makefile snippet** — appends **`dashboard-sync`** and **`db-migrate` / `db-reset` / `db-shell` / `db-watch`** targets (matches stock **`Makefile`**).
- **`install.sh`** — CLAUDE.md probe uses **`SpineDevelopment`** (drops legacy **`agent-team-template`** string).

### Documentation (ADR-001 alignment)

- **`README.md`**, **`PROTOCOL.md`**, **`INSTALL.md`**, **`docs/IMPROVEMENT_CHECKLIST.md`** — stock roster described as **13 managers / 130 worker slots**; **`engineering-*`** documented as **retired** top-level roles (**`engineer`** + **`workers/`** + ADR-001). Tier / REQ / playbook tables updated accordingly.
- **Removed** stale meta doc **`HANDOFF_FOR_AGENT.md`**.

### Polish

- **`lib/team.sh`** header comment — correct bring-up description (no "5 managers / 50 workers").

---

## [v1.4.4] — 2026-05-10

### Selftests

- **`make selftest`** — discovers and runs **`lib/tests/test-*.sh`** (`$(wildcard …)` — no Makefile churn when adding tests).
- **`lib/tests/test-costs-migrate.sh`** — **NF=9** check after **`costs-csv.sh`** migrate (sources **`lib/`** or **`scripts/`** helper per repo layout).
- **`lib/tests/test-roles-sh.sh`** — asserts **`SPINE_TEAM_ROLES`**, **`spine_role_valid product`**, rejects **`notarole`** (explicit **`if`** for invalid role — **`set -e`**-safe).
- **`lib/tests/test-daemon-stub-smoke.sh`** — end-to-end daemon path with **`EXECUTOR_KIND=generic`** (+ inline stub): **`long_job_extended`**, **`costs.csv`** **`pickup`** row with **`outcome`** (field **9**) exactly **`completed`**. When **`gtimeout`/GNU `timeout`** is on **`PATH`**, field **9** exactly **`timeout`** (**`INVOCATION_TIMEOUT_S=5`,** stub sleeps past wall). Leaves daemon running until **`costs.csv`** is written (stall watcher may sleep **~30s** after the agent exits); see **§13** cost-row timing.

### Daemon (stub executors + fresh logs)

- **`invoke_cursor`** — **`export DIRECTIVE_FILE`** so generic executor commands see the active directive path.
- After **`mkdir`** for logs — **`touch`** **`agent.log`** / **`daemon.log`** when missing so **`wc`** and first **`>>`** never fail on a fresh team tree.

### Installer

- Full **`install.sh`** copies **`lib/tests/*.sh`** → **`$TARGET/lib/tests/`** alongside **`scripts/`**.
- **`install.sh --help`** — documents skipped **`lib/tests/`** and selftest wiring; points to **PROTOCOL §10b**.

### Docs

- **`docs/EXTENSIONS.md`** §1 — design rationale for leaving planner manifest automation unshipped.
- **`PROTOCOL.md`** §10b — **`--pull-knowledge-only`** does not ship **`lib/tests/`** or **`make selftest`**; full install vs knowledge refresh; maintainer vs consumer expectations.
- **`PROTOCOL.md`** §13 — **`costs.csv`** append can lag agent exit by up to **~30s** (stall-watcher poll); poll, do not assume immediacy.

---

## [v1.4.3] — 2026-05-10

### Logging / migration hygiene

- **`scripts/costs-csv.sh`** — legacy 8-column **`costs.csv`** migration rewritten for **same-directory atomic `tmp` + `mv`** (no mixed-column append). **`make selftest`** (**v1.4.4**) runs **`lib/tests/test-costs-migrate.sh`** covering NF=9 post-migrate.

### Polish (pre-tag)

- **`## Long job:`** only **extends** **`INVOCATION_TIMEOUT_S`**; smaller hints are ignored (never stricter).
- **`outcome=timeout`** only when the daemon actually launched **`timeout`/`gtimeout`** *and* wait status **124/137**. Exit **137** without wrapper classifies **`killed`** (e.g. OOM). **`§13b`** documents residual ambiguity with wrapper vs OOM SIGKILL.

### Daemon & costs

- **`lib/team-agent-daemon.sh`** — **`## Long job:`** only when parsed wall budget **exceeds `INVOCATION_TIMEOUT_S`** (never stricter); stall scales **only** when that ceiling is raised; sources **`costs-csv.sh`**. **`outcome=timeout`** iff **`timeout`/`gtimeout`** wrapped the child **and** wait status is **124** or **137**; otherwise **`exit_code > 128` → `killed`**.
- **`costs.csv`** — trailing **`outcome`**; legacy eight-column logs are **fully rewritten atomically** (temp file next to the CSV + **`mv`**) **before** the next append; migrated data rows get **`outcome=unknown`**.
- **`lib/team.sh`** — **`budget` / `status` / `doctor`** flag reap outcomes and tolerate pre-migrate row widths.

### UX & docs

- **`lib/dashboard.html`** — recent cost table **`outcome`** column + KPI **`Daemon-reaped rows`** + highlighted reap rows.
- **`PROTOCOL.md`** — §§3e, **6**, **11 (logging)** — **`outcome`**, **`costs-csv.sh`**, extension-only **`## Long job:`**, **`§13` / §13b** limitations.

### Meta

- **`install.sh`** — ships **`costs-csv.sh`** beside other **`scripts/`** helpers.
- **`recipes/batch-process-data.md`** — example **`## Long job: 120`**.
- **`lib/role-prompts`** — **`## Long job default`** for **`datawright`**, **`operator`**, **`engineer`**, **`engineering-backend`**, **`engineering-frontend`**.
- **`docs/EXTENSIONS.md`** §5 / summary refreshed for shipped long-job behavior.
- **`docs/IMPROVEMENT_CHECKLIST.md`** — product-runtime rows for long-job hint + rc/outcome visibility closed.

---

## [v1.4.2] — 2026-05-10

### Documentation

- **`README.md`** — aligned intro, team tree, **Manager roles** tables, install steps, and `make team-up` line with **`scripts/roles.sh`** (15 × 10 workers + watchdog).
- **`INSTALL.md`** — verifying-the-install now quotes the real **`Starting agent team (N managers + …)`** line from `lib/team.sh`.
- **`lib/watchdog.sh`** — header comment matches **SPINE_TEAM_ROLES** iteration.
- **`PROTOCOL.md` §10** — explicit **manual** versioning note for maintainers (no auto-sync from `CHANGELOG`); **`CHANGELOG.md`** is not bundled in installed projects.
- **`docs/EXTENSIONS.md`** — reframed as **shipped vs partial vs not shipped** (Control Center, costs, stall/timeout, seer/auditor/memory, playbook, recipes); planner aggregation stays **not shipped**.
- **`docs/IMPROVEMENT_CHECKLIST.md`** — closed documentation/dashboard rows touched by this pass.
- **Release dates:** **`v1.4.0` → `2026-05-09`** fixes calendar ordering versus **`v1.4.1` (`2026-05-10`)**. If your **git tag** wall-clock says both minor releases landed the same local day, treat the dates as **ordering + documentation** — do not "fix" them back without checking tags.

---

## [v1.4.1] — 2026-05-10

### Dashboard

- **`lib/dashboard.html`** is now **Spine Control Center**: tabbed UI (Overview, costs & tiers, program templates, docs, help), role cards with filters, detail drawer (manager text, workers 01–10, per-role costs CSV, rollback stack), path presets + custom base (stored in `localStorage`), and safer polling (no per-role worker Slot fan-out on every refresh).
- **Doc fix:** serve **`.planning/orchestration`** (not only `dashboard/`) when using the default preset, so browser `fetch("../agent-handoff/...")` resolves to `/agent-handoff/...`.
- **`scripts/serve-dashboard.sh`** + **`make dashboard`** — start Python's static server from orchestration so the UI is not mistaken for your app's `/dashboard` API route (Fastify/Express JSON 404).
- Further **Control Center** tweaks: sticky header + tabs; sort roles (A–Z / state / cost rows); failure count KPI; approval hint on cards; **`memory.md`** in drawer + copy paths; refresh overlap guard + busy state; main-tab click handler scoped so drawer subtabs no longer steal clicks.

---

## [v1.4.0] — 2026-05-09

Program-delivery orchestration framework: expanded role roster, single-source role list, SDLC gates, squad fan-out parity, conductor vs planner separation.

### Roles (`lib/roles.sh` → `scripts/roles.sh`)

- Added managers: **`product`**, **`architect`**, **`conductor`**, **`engineering-backend`**, **`engineering-frontend`**, **`ux`**, **`qa`** (retains existing planner/researcher/engineer/operator/datawright/meta roles).
- **15 managers × 10 workers = 150 worker slots** per repo (+ watchdog).
- Daemon + watchdog + cleaner + installer all **source `roles.sh`** — no duplicated role arrays.

### Protocol

- **`PROTOCOL.md`** §1 rewritten for lifecycle ladder + squad recursion doctrine; **`planner` + `conductor` cross-writing** clarified (§5); **§§21–26** cover SDLC linkage, REQ blocks, conductor mandate, QA/auditor pairing.
- **`## Linked REQ`** contract for implementation directives (**§22**).

### Prompts & docs

- New role prompts under `lib/role-prompts/` for delivery squads / product / architecture / QA / UX / conductor.
- **`docs/PROGRAM_DELIVERY.md`** + **`templates/program/`** (`REQ_TEMPLATE.md`, `PROGRAM_PHASES.md`, `POLICY.stub.md`) shipped via installer into `.planning/orchestration/`.
- Planner + memory + seer prompts updated for expanded roster.

### Mechanics

- Git rollback snapshots now cover **`engineering-backend`** & **`engineering-frontend`** alongside `engineer`.
- **`lib/dashboard.html`** lists all canonical roles.

### Operational note

 Larger idle footprint — ensure hosts can tolerate `15` polling managers or trim unused roles in a fork **only after** adjusting `roles.sh` consistently.

---

## [v1.3.4] — 2026-05-10

The **documentation, context, and portable template** pass: align multi-agent practice with how teams actually avoid drift, make the installer support **knowledge refresh** without touching daemons, and generalize role prompts for any project.

### Installer

- **`--pull-knowledge-only`** (alias `--knowledge-only`) — copies protocol, requirements, `recipes/`, `docs/` (practices + checklist + extensions), `templates/orchestration/` (ADR scaffolds), and `role-prompt.md` files. **Does not** replace `scripts/*.sh`, dashboard HTML, Makefile, notification hook, or modify `CLAUDE.md`. Skips host preflight.
- **Full install** now also copies **recipes** and **orchestration docs/templates** into `.planning/orchestration/` (same overwrite rules as other optional files — use `--force` to replace in-repo customized copies).
- **`err()` helper** added for consistent preflight failure messages.

### Documentation & scaffolding

- New **`docs/SPINE_PRACTICES.md`** — goals (parallel roles, drift control, durable context), context stack order, architect habits, trust boundary.
- New **`docs/IMPROVEMENT_CHECKLIST.md`** — maintainer backlog.
- New **`templates/orchestration/DECISIONS.md`** and **`ADR_TEMPLATE.md`** — append-only ADR log scaffold + standalone template.

### Portable role prompts & playbooks

- **`lib/role-prompts/operator.md`** and **`lib/role-prompts/datawright.md`** rewritten to be **repository-agnostic** (discover compose stack, inference endpoints, and tables from *this* project instead of hard-coded product names).
- **`lib/playbook-defaults/`** — minor wording generalized for the same reason.
- **`recipes/host-side-llm-pipeline.md`**, **`safe-db-script.md`**, **`investigate-bug.md`** — intro lines no longer cite a single codebase by name.

### Protocol & README

- **`PROTOCOL.md`** — §8 bring-up text fixed **(8 managers + 80 workers + watchdog)**; §7 playbook table extended with seer / auditor / memory; **§10** document revision bumped to **v1.3** with pointer to SpineDevelopment `CHANGELOG`; new **§10b** describing `--pull-knowledge-only`.
- **`README.md`** — version headline delegated to **`CHANGELOG`**; lineage and "what you get" tree updated for practices docs and in-repo recipes; install steps expanded.

### No daemon behavior change

Shell daemons unchanged in this release (same timeouts, hashing, watchdog integration). Adjust `INVOCATION_TIMEOUT_S` for long batch work per v1.3.3 playbook guidance until a future directive-level hint ships.

---

## [v1.3.3] — 2026-05-08 (evening)

The "long-running batch jobs are different" pass. Triggered by a real datawright incident: an auto-labeling daemon was silently killed mid-run by the daemon's 25-minute `INVOCATION_TIMEOUT_S` while doing a ~46-minute full-archive labeling pass. Cursor exits cleanly under SIGTERM, so the daemon recorded `rc=0` even though the directive output was incomplete — a "successful failure" that's invisible without the watchdog.

### Operator playbook addition: long-running batch jobs

New section in `lib/playbook-defaults/operator.md` ("Long-running batch jobs (the 25-minute timeout trap)") with four lessons:

- **The 25-min `INVOCATION_TIMEOUT_S=1500` kills batch agent invocations.** Default is right for normal directives, wrong for full-archive labeling, large training runs, or per-doc enrichment of thousands of docs. Override per-process before kicking off: `INVOCATION_TIMEOUT_S=5400 nohup bash scripts/team-agent-daemon.sh <role> manager &`. Symptom of the trap: agent reports `rc=0` but the directive output is incomplete or absent.
- **A daemon killed silently is invisible without the watchdog.** Pre-v1.3 installs have no auto-restart. After bumping a timeout for batch work, also `bash scripts/team.sh status` periodically. v1.3+ projects: install `scripts/watchdog.sh` so dead managers get re-launched.
- **Design batch scripts to be resumable from checkpoint.** A 60-minute batch failing at the 55-min mark is wasted effort if the script can't resume. Pattern: per-N-row checkpoint markers, on script start read the marker and skip already-processed rows. The Kontract LABEL-AUTO-05 script had this and survived a daemon restart cleanly.
- **Schedule batch jobs around macOS sleep.** Laptop sleep mid-batch loses the host-side LLM, the worker container, and any host-side file-bus daemon. For overnight runs: `pmset -a sleep 0` (Mac plugged in, no sleep) before kicking off, restore after. Or run on a desktop / server.

### Validated by

The very incident that motivated this addition — a Kontract datawright daemon dying silently mid-run during LABEL-AUTO-05 (~1186 documents). The 25-min timeout assumption baked into v1.1 daemon hardening was correct for the v1.0 directive shape (one focused engineering task) but wrong for the v1.3 datawright batch shape. v1.3.3 captures the lesson so the next install starts knowing.

### No code changes

Pure playbook content. No daemon, executor, watchdog, or installer changes. Future v1.4 may consider a per-directive `## Tier hint: batch` mode that auto-bumps `INVOCATION_TIMEOUT_S` for the duration of the invocation, but that's a real change and goes through the v1.4 cycle.

---

## [v1.3.2] — 2026-05-08 (later same day)

The "second-round dogfood lessons" pass. Added while running multiple parallel directives in the Kontract project (Capability B template auto-tag + LABEL-AUTO Qwen prompt design). Pure additive — no breaking changes.

### New recipe: `recipes/host-side-llm-pipeline.md`

Codifies the multi-step pattern for moving an LLM service from in-Docker (CPU-only on macOS) to host-side (Metal-accelerated) while keeping the rest of the stack containerized. The full Kontract Ollama-on-Metal migration took ~3 hours of debugging in real-time; the recipe makes it a 30-minute walkthrough for the next person. Ten concrete moves covering: platform check, install, hunting respawning watchdog apps, 0.0.0.0 binding, model cache locations (no iCloud!), `host.docker.internal` config, `--force-recreate` not `restart`, profile-gating the Docker fallback, volume cleanup. Variants for Linux/CUDA and production K8s.

### New playbook: `lib/playbook-defaults/datawright.md`

Default lessons for the data/ML role, seeded into `~/.spine-development/playbook/datawright/lessons.md` on install. Topics:

- Local LLM operation (Ollama, llama.cpp, vLLM): cold-start vs steady-state, `eval_duration` vs wall-clock, OCR text trimming, JSON validation patterns, temperature semantics
- Prompt design: vocabulary control, few-shot leverage, disambiguation rule placement, "uncertain" as a feature, prompt versioning
- Auto-labeling at scale: sample-first validation, incremental persistence, idempotency via prompt-version skipping, spot-checking disagreements
- Training + fine-tuning: minimum data thresholds, class imbalance, checkpoint storage paths (no iCloud), training run registry
- Cost discipline: budget extrapolation from samples, parallelization patterns (workers vs model instances vs vLLM batching)
- Reporting: aggregate metrics + raw samples, always include wall-clock + disk usage

### Installer change

`install.sh` now seeds three playbooks (engineer, operator, datawright) on fresh installs. Re-running install never overwrites user customizations.

### Validated by

Real-time hardening during a live multi-directive dogfood run — engineer Phase 1 + Phase 2 of Capability B and datawright LABEL-AUTO-03 + LABEL-AUTO-04 all running in parallel under the older Kontract team install. Lessons captured here are the ones that emerged in real-time as we wrote / ran / read agent reports.

---

## [v1.3.1] — 2026-05-08

The "lessons from the first real dogfood run" pass. Pure additive — no breaking changes, no daemon/protocol updates. v1.3.1 takes the operational gotchas surfaced when running v1.3-style directives against a real Kontract project and bakes them into the template so future installs start with the wisdom built in.

### Pre-seeded playbook lessons (`lib/playbook-defaults/`)

New directory of default playbook lessons that the installer copies to `~/.spine-development/playbook/<role>/lessons.md` IF the user doesn't already have one. User customizations are never overwritten. Two seed files in this release:

- **engineer.md** — bash + psql gotchas (UUID command-tag capture, `ON CONFLICT` requires unique constraints, `--set ON_ERROR_STOP=on`, idempotency patterns, defensive bash, schema vs data separation, agent reporting style).
- **operator.md** — Docker on macOS (single-file mount inode bug, `restart` doesn't pick up env changes, `host.docker.internal` requires 0.0.0.0 binding, no Metal pass-through), respawning watchdog apps, compose hygiene, profile-gating opt-in services, iCloud-folder hostility to large local-only data.

These are battle-tested entries from real incidents (Kontract sponsor-archive linkage, Ollama Metal migration, dashboard mount-inode mystery). New projects starting fresh now inherit ~30 prevention rules instead of having to learn them by getting bitten.

### New recipe: `recipes/safe-db-script.md`

Codifies the script-hygiene patterns for any bash script that mutates a database. The cause of the 2026-05-08 sponsor-archive incident was a script that "looked right" — captured a UUID via `psql ... RETURNING id`, but the captured value also included `INSERT 0 1` on a separate line. The recipe enumerates seven required patterns:

1. `--set ON_ERROR_STOP=on` + check `$?` after every heredoc
2. Always extract returned values via shape-specific regex (UUID, integer, boolean)
3. `ON CONFLICT DO NOTHING` requires a real constraint — use SELECT-then-INSERT-if-empty otherwise
4. Idempotency MUST be tested by running the script twice
5. Pre-flight + post-flight counts as the cheapest correctness check
6. Quoting/escaping rules for shell-interpolated SQL (apostrophes break heredocs)
7. Defensive bash: no `set -e`, capture exit codes immediately, `set -uo pipefail` only

Engineer agents reading this recipe before writing a DB-interacting script avoid the entire class of bug.

### Installer change

`install.sh` now copies the playbook defaults during the cross-project playbook setup step (#4c). Idempotent — re-running install never overwrites user-edited lessons.

### Validated by

End-to-end dogfood through the v1.3 file-bus pattern in Kontract:

- Engineer daemon picked up a directive, executed a script, hit a bug, reported FAILED with clean diagnosis (no silent failure)
- Architect (chat) read the report, wrote a focused fix-it directive
- Engineer picked up the new directive, patched the script, cleaned up the orphaned data state, re-ran, verified, reported SUCCESS
- Two cycles, zero human babysitting on the actual fix work
- Surfaced the playbook entries above

This is the workflow we hoped the file-bus pattern would enable. v1.3.1 captures what we learned so v1.4 doesn't have to.

---

## [v1.3] — 2026-05-06 (same evening)

The "what does my computer actually need" + "stop being Cursor-only" pass.

### Pluggable AI executor (`lib/executor.sh`)

The daemon no longer hardcodes Cursor. It writes the prompt to a temp file and dispatches via `executor.sh`, which auto-detects the first installed CLI from this priority order:

1. `cursor-agent` (Cursor Agent)
2. `cursor` (Cursor)
3. `claude` (Anthropic Claude Code CLI)
4. `aider` (Aider)
5. `opencode` (OpenCode)
6. `codex` (OpenAI Codex CLI)

Each CLI's invocation pattern is encoded in the executor — claude uses `-p`, aider uses `--message ... --yes`, the rest take prompt as argv[1]. Override the choice with `EXECUTOR_KIND=cursor|claude|aider|opencode|codex|generic` or point at any custom CLI with `EXECUTOR_CMD=/path/to/your-cli`. `EXECUTOR_KIND=generic` pipes the prompt to your command's stdin for full custom control.

### Preflight check (`lib/preflight.sh`)

`bash scripts/preflight.sh` (or `make team-preflight`, or `team.sh preflight`) reports:

- Platform (macOS / Linux / Linux-WSL / Windows-Git-Bash / unknown)
- Required tools: bash, git, curl, tar, find/awk/sed/grep, pgrep, shasum/sha256sum, ln
- Recommended tools: timeout/gtimeout, stat, du/wc, osascript (mac) / notify-send (linux)
- Notification env vars armed: NTFY_TOPIC, SLACK_WEBHOOK, DISCORD_WEBHOOK, PUSHOVER_USER+TOKEN, NOTIFY_EMAIL_TO
- AI CLI detection (cursor-agent, cursor, claude, aider, opencode, codex, EXECUTOR_CMD)
- Per-platform `apt install ...` / `brew install ...` hints for missing pieces
- Exit codes: 0 = good, 1 = required missing (or with --strict, optional missing also fails)
- `--quiet` flag emits a one-liner (`PREFLIGHT: OK (Linux, agent=claude)`) for cron / CI

`install.sh` now runs preflight as step 0 and refuses to install if required tools are missing.

### REQUIREMENTS.md

New top-level doc covering:

- Platform support matrix (macOS ✓, Linux ✓, Windows-via-WSL2 ✓, Windows-Git-Bash partial, native PowerShell not yet)
- Required tools with per-platform install commands
- Recommended tools and what you lose without each
- Notification channel setup
- Network requirements
- Resource footprint (idle vs active)
- Common troubleshooting

Installer copies it into the target project as `.planning/orchestration/AGENT_TEAM_REQUIREMENTS.md`.

### New `team.sh` subcommand and Make target

- `team.sh preflight [--quiet|--strict]` → calls preflight.sh
- `make team-preflight` → same

### Honest Windows answer

WSL2 is the supported Windows path today. Native PowerShell port is a real undertaking (~800–1000 lines) and remains a future TODO. Documented clearly in REQUIREMENTS.md.

---

## [v1.2] — 2026-05-06 (later same day)

The "safe to leave it running while you sleep" pass. v1.1 made the team capable; v1.2 makes it accountable.

### Watchdog supervision (`lib/watchdog.sh`)

A single supervisor process auto-launched by `team up`. Each manager `touch`es `state/heartbeat` on every poll cycle (~8s). Watchdog wakes every 60s and checks heartbeat ages — if > 5 min stale, presumes manager dead and re-spawns it. Restarts fire a notification. Pid at `.planning/orchestration/agent-handoff/watchdog.pid`, log at `.../watchdog.log`. Tunables: `WATCHDOG_POLL_S`, `HEARTBEAT_TIMEOUT_S`.

### Architect approval gates

For directives that must NOT auto-run (prod deploys, schema migrations, destructive ops), declare `## Requires approval: yes` in the directive. Manager produces a Plan + Risks + Rollback document, marks the file `# Awaiting approval`, fires a notification, exits. Architect appends a `## Approved by: <name> @ <ts>` line to authorize. Daemon detects the new line, re-invokes manager in execute-after-approval mode. Plan must be executed as approved (no silent re-planning).

### Engineer rollback (`team.sh rollback engineer`)

Daemon takes a git snapshot before every engineer invocation: HEAD sha + `git stash create` of tracked changes + tarball of untracked files. All recorded to `teams/engineer/state/rollback-stack.csv`. Rollback command shows history, prompts for selection, runs `git reset --hard <head>` + `git stash apply <snapshot>` to restore. Snapshots are git-cheap (commit objects + tarballs); preserved until `team.sh clean nuclear`.

### Notification hook (`~/.spine-development/notify.sh`)

Default dispatcher installed to home dir. Channels: macOS notification (osascript), Slack webhook (`SLACK_WEBHOOK`), Discord webhook (`DISCORD_WEBHOOK`), email (`NOTIFY_EMAIL_TO`). Always appends to `~/.spine-development/notifications.log`. Customize freely — lives outside the repo. Daemon fires on: directive complete (success/failure), aggregate complete, awaiting-approval state, watchdog restart.

### Health check (`team.sh doctor` / `make team-doctor`)

Verifies: cursor-agent on PATH; each of 8 managers alive AND heartbeat fresh; watchdog up; notify hook installed; no cursor-agent runaway zombies (>16 = warn); team disk footprint (>100 MB = suggest clean). Exits non-zero if any check fails — usable in cron / CI.

### New Make targets

`team-doctor`, `team-rollback` added to the installer's Makefile snippet.

### PROTOCOL.md

Sections 16–20 added: approval gates, engineer rollback, watchdog, notifications, health check.

---

## [v1.1] — 2026-05-06

The "make it production-grade" pass. v1 worked for one project (Kontract); v1.1 closes the gaps that surfaced after two weeks of real use.

### File hygiene (the "no junk left behind" pass)

The single most-requested cleanup. AI agents drop fixture files, scratch scripts, `.bak` backups, and debug experiments everywhere by default. v1.1 makes this disallowed and gives agents a sanctioned alternative.

- **Per-daemon scratch dir** at `teams/<role>/scratch/<slot>/` — wiped by the daemon on every new directive. Agents are told via the prompt to use it for any temp work.
- **Per-daemon OS temp dir** at `/tmp/spine-<role>-<slot>/` — same lifecycle, for tools that demand `/tmp`.
- **Forbidden file patterns** named in the prompt: `*.bak`, `*.orig`, `*~`, `*.swp`, `tmp_*`, `debug_*`, `scratch.*`, any backup directory.
- **`## Files touched` report contract** — every report (manager and worker) must end with a list of every file created/modified outside the team dir. Auditor cross-references against `git status`.
- **Engineer pre-flight** — engineer role-prompt now requires `git status --short` review and stray-file deletion before writing the report.
- **Auditor stray-file scan** — auditor role checks for forbidden patterns and unlisted changes during audits.
- **Daemon-enforced log rotation** — every poll cycle, any `.log` file > 5 MB is truncated to last 5 MB. Configurable via `LOG_MAX_BYTES`.
- **`scripts/team-clean.sh`** — new helper with modes: `scratch` / `logs` / `archive` / `all` (safe defaults — preserves directives, memory, costs); `costs` / `memory` / `nuclear` (destructive); `footprint` (read-only); `dry-run <mode>` for preview.
- **`bash scripts/team.sh clean <mode>`** — top-level subcommand that calls team-clean.sh.
- **`make team-clean` / `make team-footprint`** — Makefile targets installed by the installer.
- **PROTOCOL.md Section 15** — full file-hygiene contract documented.

### New roles (3)

- **seer** — read-only observability. Produces a single-page status across all manager directives. `lib/seer-tick.sh` writes "Refresh status" into `seer/directive.md` every 5 minutes when seer is idle, so the dashboard is never stale.
- **auditor** — verification. Re-runs claims made in another role's report (lint, tests, smoke endpoints, file existence) and writes a PASS/FAIL audit. Catches "tests pass" claims where tests didn't actually run.
- **memory** — spine maintenance. Owns `DECISIONS.md`, `SESSION_HANDOFF.md`, `MASTER_TODO.md` updates, and writes lessons into per-role `memory.md` and the cross-project playbook.

### Cost discipline (model tiering)

- Directives can declare `## Tier hint: low | medium | high`.
- Daemon parses the hint and injects tier guidance into the agent prompt: "Use cheapest competent model" / "default tier" / "most capable model — only when justified".
- Per-role defaults: planner/engineer → medium; researcher/operator/seer/auditor/memory → low; datawright → low (varies).
- Every invocation logs a row to `teams/<role>/state/costs.csv`: timestamp, role, mode, slot, phase, tier, wall-seconds, exit-code.
- New `make team-budget` aggregates costs across all roles and shows totals + per-tier breakdown.
- Planner role prompt now propagates tier discipline — when planners decompose into sub-directives, each sub-directive gets its own tier hint based on what the work actually needs.

### Memory

- Per-role `memory.md` file at `teams/<role>/memory.md` — read by the daemon on every invocation, prepended to the agent prompt.
- Memory role maintains spine docs (DECISIONS.md, SESSION_HANDOFF.md, MASTER_TODO.md).
- Cross-project playbook at `~/.spine-development/playbook/<role>/lessons.md` — lessons that apply to every project, not just this one.
- New `bash scripts/team.sh learn "lesson text" --role engineer` command appends to the playbook.

### Daemon hardening

- **Hard timeout**: default 25 minutes per invocation (override with `MAX_INVOCATION_S`). Uses `gtimeout`/`timeout` with `--kill-after`.
- **Stall detection**: if `AGENT_LOG` doesn't grow for 8 minutes (override with `STALL_THRESHOLD_S`), background watcher kills the process.
- **Tier guidance injection**: every prompt gets a `# COST GUIDANCE` block matching the directive's tier hint.
- **Memory injection**: every prompt gets a `# MEMORY (this role)` block with the contents of `memory.md`.
- **Defensive bash throughout**: inner failures never kill the daemon loop.

### Conflict resolution

- New `lib/file-lock.sh` provides atomic file locks via `ln -s` (fails if target exists). Workers can `acquire`, `release`, `holder` for any path before editing.
- Engineer role prompt now requires the manager to declare per-worker file scope when fanning out, and workers must take a lock before editing files in someone else's scope.

### Observability

- New `lib/dashboard.html` — self-contained HTML dashboard. Fetches each role's `directive.md`, classifies state (idle / directive / plan / report / worker-directive / report / error), refreshes every 8 seconds. No build, no server, no dependencies.
- Installer drops it at `.planning/orchestration/dashboard/index.html` — open in a browser or serve with `python3 -m http.server`.

### Recipes

Six ready-to-paste directive templates in `recipes/`:

- `postmortem.md` — incident postmortem orchestrated across researcher + engineer + operator + memory.
- `refactor-plan.md` — plan-before-doing refactor (researcher maps state, engineer designs strategies, architect approves before code).
- `dependency-bump.md` — safe dep upgrade (engineer, low tier, with stop conditions for major migrations).
- `security-audit.md` — five-surface audit (deps, secrets, auth, infra, logging).
- `performance-investigation.md` — measure-before-fix perf workflow.

### Protocol

`PROTOCOL.md` updated to v1.1. Sections 11 (cost discipline), 12 (memory), 13 (timeouts and stall detection), 14 (conflict resolution) are new. Section 1 expanded from 5 roles to 8.

### Installer

- `install.sh` now provisions all 8 roles, all 4 helper scripts, the dashboard, and the cross-project playbook directory.
- Idempotent — safe to re-run. Existing files are preserved unless `--force` is passed.

---

## [v1.0] — 2026-04-22

Initial extraction from Kontract. Five-role topology (planner/researcher/engineer/operator/datawright) with the basic file-bus daemon pattern, manager + worker decomposition, and a thin install script.

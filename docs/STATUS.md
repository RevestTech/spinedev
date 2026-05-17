# Spine v2 — Status & Handoff

> **Last updated:** 2026-05-16 (end of wave 9 — Tier 1 bug fixes + smoke harness)
> **Branch:** `main`
> **Latest commit:** wave 9 (see `git log --oneline -15` for full history)
> **For: anyone picking up Spine v2 development.**

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

# `verify/` — Spine Verify Subsystem (TRON Integration)

> **Spine subsystem boundary doc.** Lives alongside TRON's own `verify/README.md` (TRON's project docs). This file describes the *Spine* role of this subsystem — what it owns, its contract to the Orchestrator, its stack, its boundary. Renamed from `README.md` to `SUBSYSTEM_BOUNDARY.md` to avoid clash with TRON's pre-existing README.md when integrated via `git subtree`.
>
> **Status:** TRON subtree-merged 2026-05-16 (Phase 1) from `/Users/khashsarrafi/Projects/Utilities/tron@main` (`adcebe33`).

## Purpose

The verification subsystem. Runs TRON's 7-layer verification pipeline on Build outputs: deterministic scanners (Bandit / Semgrep / ESLint / OSV) → schema-validated LLM ISO agents → execution sandbox → cross-LLM consensus → Platt-calibrated confidence → prompt regression CI. Returns `VerifyFindings` to the Orchestrator, which routes back to Build for remediation or surfaces to user for approval.

This is TRON, integrated as a first-class Spine subsystem.

## Boundary

**In scope:**
- ISO agents (SecurityISO, BuilderISO, QAISO, PerformanceISO, ComplianceISO, DocumentationISO) — live at `verify/tron/agents/`
- 7-layer verification pipeline — `verify/tron/verification/`
- Docker ephemeral sandbox + seccomp — `verify/tron/sandbox/`
- Temporal workflows — `verify/tron/workflows/`
- Platt-scaled confidence calibration
- FastAPI routes (verify-internal) — `verify/tron/api/`
- Verify-specific output templates (`verify/tron/agent_handoff_templates/`)

**Out of scope (cross-cutting; will move to `shared/` in Phase 2):**
- TRON's standards hierarchy → `shared/standards/` (`STORY-2.4.1`)
- TRON's MCP server → `shared/mcp/` (`STORY-8.2.2`)
- TRON's memory → `shared/memory/` (`STORY-8.2.3`)
- TRON's tree-sitter parsers → `build/kg/parsers/` (`STORY-8.2.4`)
- TRON's frontend → `shared/ui/` (`STORY-8.2.6`)
- TRON's infra (Vault, etc.) → `shared/infra/` (`STORY-8.2.5`)

These haven't moved yet — they're staged for Phase 2 per `docs/ARCHITECTURE.md §6`.

## Stack

- **Python 3.11+ + FastAPI + Temporal + Postgres + Docker** (TRON's existing stack, preserved)
- Talks to Orchestrator via MCP (`verify_audit(build_artifact, blueprint)` returns `VerifyFindings`)
- Postgres schemas: `spine_verify_*` (within the unified single Postgres instance)

## Sub-structure (post-Phase-1; per ARCHITECTURE.md §4)

```
verify/                       # ← Subtree merged from TRON 2026-05-16
├── README.md                 # TRON's own project README (preserved)
├── SUBSYSTEM_BOUNDARY.md     # ← this file — Spine boundary doc
├── AGENTS.md                 # TRON's agent context
├── tron/                     # TRON application code
│   ├── agents/               # ISO agents
│   ├── verification/         # 7-layer pipeline
│   ├── sandbox/              # Docker + seccomp
│   ├── workflows/            # Temporal
│   ├── api/                  # FastAPI
│   ├── schemas/              # Pydantic models
│   ├── services/             # ThreatIntel, handoff exports
│   ├── standards/            # → moves to shared/standards/ in Phase 2
│   ├── mcp/                  # → moves to shared/mcp/ in Phase 2
│   ├── memory/               # → moves to shared/memory/ in Phase 2
│   ├── parsers/              # → moves to build/kg/parsers/ in Phase 2
│   ├── infra/                # → moves to shared/infra/ in Phase 2
│   └── realtime/             # → moves to shared/realtime/ in Phase 2
├── frontend/                 # → moves to shared/ui/ in Phase 2
├── admin-ui/                 # → retires per TRON roadmap
├── alembic/                  # → migrates to Flyway in Phase 2 (shared/db/)
├── docker-compose.yml        # TRON dev stack
├── Makefile                  # TRON's per-subsystem targets
├── pyproject.toml
└── tests/                    # TRON's pytest suite
```

## Standalone deployability (hard requirement — G-8 in REQ-INIT-8)

`verify/` is designed to **still run standalone** after integration — preserves TRON's existing audit-only deployment model for orgs that want the verification product without the full Spine pipeline:

- `cd verify/ && docker compose up -d` runs TRON audit-only with no Orchestrator
- TRON's existing `tron` CLI continues to work standalone
- No env var, schema, or service from outside `verify/` is required to run TRON audit-only
- Phase 2 consolidation (shared Postgres, shared MCP) is **additive** — TRON's standalone compose still wires its own services if the umbrella isn't present

**Don't break this property when wiring to Orchestrator.**

## Backlog

- **INIT-8** Verify Subsystem (TRON Integration) — primary owner. 6 epics, ~22 stories. See `docs/BACKLOG.md`.
- **EPIC-3.5/6/7** — Sandbox / Calibration / Cross-LLM Validation lifted from TRON; some live here, some in `shared/`.
- **Sprint 2** includes `STORY-8.5.1` (orchestrator invokes TRON `AuditManager`).

## TRON startup (Spine-side)

What the Orchestrator needs running so `verify_audit` can hand a sealed
`BuildArtifact` to TRON's `AuditManager`. Standalone TRON deployment
(per G-8 above) is unchanged — these instructions are additive and only
apply when running TRON from inside Spine via `cd verify && docker compose …`.

### Service subset (first integration)

Only **postgres** is brought up. AuditManager runs in-process from
Spine's `shared/mcp/tools/verify.py` wrapper; deterministic scanners
(Bandit/Semgrep/etc.) shell out via TRON's `LocalSandbox`; LLM calls go
direct via httpx. We do **not** start tron-api, tron-worker, tron-sandbox,
temporal, redis, minio, pgbouncer, nginx, prometheus, grafana, tempo,
loki, otel-collector, or alertmanager. Each one is real cost (disk + RAM
+ port allocation); only postgres is needed so TRON's alembic schema
exists and async DB-bound code paths (LLM usage ledger, budget) have a
real target. Even those code paths skip cleanly when `_session_factory`
is `None` (i.e. when nobody has called `init_db()`), so postgres-down
is non-fatal — but with it up, future work that hits the DB will Just
Work without re-wiring.

Spine's overlay (materialized as `verify/docker-compose.override.yml` at
runtime — see "Spine override placement" below) does two things:
1. Renames containers to `spine_tron_*` so they don't collide with the
   pre-existing standalone TRON install (container names like
   `tron-postgres` belong to `/Users/.../Utilities/Tron`).
2. Adds host port `127.0.0.1:33010 → 5432` for postgres (Spine's own
   postgres owns 33001; we reserve 33xxx for Spine's stack).

### Spine override placement (T4 / Wave 1)

The canonical override file lives **outside the TRON subtree** at
`tools/verify-overrides/docker-compose.override.yml`. A small installer
symlinks it into `verify/docker-compose.override.yml` at runtime:

```bash
bash tools/verify-overrides/install.sh             # install symlink
bash tools/verify-overrides/install.sh --check     # report status
bash tools/verify-overrides/install.sh --uninstall # remove symlink
```

**Why outside `verify/`:** `verify/` is `git subtree`-merged from TRON's
upstream. Any Spine-authored file checked into `verify/` causes merge
conflicts on the next subtree pull. The override file is Spine policy
(container rename convention + Spine's `33xxx` port allocation), not TRON
code, so it must not live in TRON's tree. The symlink pattern cleanly
separates "Spine's verify integration" from "TRON's verify code":

- TRON's subtree pulls stay conflict-free — no Spine file in `verify/`.
- `verify/docker-compose.override.yml` still exists at compose-discovery
  time, so `docker compose up -d <service>` in `verify/` continues to
  auto-merge the overlay exactly as before.
- The installer is idempotent and refuses to clobber non-symlink content
  at the destination (defense against a hand-edit or a future TRON file
  with the same name).

Spine bootstrap / `tools/smoke-test.sh` phase 11 should invoke
`tools/verify-overrides/install.sh` before `docker compose up -d postgres`
in `verify/`.

### Bring it up

```bash
# 1. Install TRON deps into the project venv (one-time; size ~+85 MiB).
.venv/bin/pip install \
  'sqlalchemy[asyncio]>=2.0.36' temporalio bandit \
  alembic asyncpg psycopg2-binary

# 2. Materialize the Spine override symlink (idempotent), then start TRON's
#    postgres. The override file itself lives at tools/verify-overrides/
#    so TRON subtree pulls stay conflict-free; the symlink lets compose
#    discover it from verify/ at runtime. verify/.env.vault-refs is the
#    Spine-side secrets manifest (vault-only, per #9).
bash tools/verify-overrides/install.sh
cd verify && docker compose up -d postgres && cd ..

# 3. Apply TRON's alembic migrations (creates 14 tables).
.venv/bin/python tools/_tron_alembic_upgrade.py
# → "alembic upgrade head: OK"

# 4. Verify with the smoke harness — phase 11 covers all 4 acceptance checks.
bash tools/smoke-test.sh --phase 11
# Expected: 5 PASS, 0 FAIL
#   tron.import.manager        — tron.agents.manager imports
#   tron.import.wrapper_style  — verify.tron.agents.manager imports
#   tron.instantiate.empty     — AuditManager() with empty secrets OK
#   tron.bandit.runs           — Bandit subprocess + JSON parse
#   tron.db.reachable          — TRON postgres reachable + alembic at head
```

### Env vars

| Var | Default | When set |
|---|---|---|
| `POSTGRES_PASSWORD` | `tron_dev_only` | From `verify/.env` (already shipped) |
| `ANTHROPIC_API_KEY` | unset → `tron_keys_missing` error | When invoking `verify_audit` for real |
| `OPENAI_API_KEY` | unset | Alternative to anthropic key |
| `TRON_DATABASE_URL` | `postgresql://tron:tron_dev_only@127.0.0.1:33010/tron` | Smoke phase 11 override |
| `DATABASE_URL` | same | TRON alembic + runtime DB-bound paths |

### PYTHONPATH (the load-bearing gotcha)

TRON uses absolute `tron.*` imports throughout (preserves standalone
deployability — `tron/` is the package root inside `verify/`). For
Spine's in-process invocation, **both** of these must be on `sys.path`:

1. `<repo-root>` — for `shared.*`, `plan.*`, `build.*`, `orchestrator.*`
2. `<repo-root>/verify` — for TRON's absolute `tron.*` imports

Because `verify/` has no `__init__.py`, the Spine wrapper's
`verify.tron.X` imports also work, via PEP 420 implicit-namespace
packages. The two forms resolve to different module *objects* under the
hood (same source loaded twice) — that's a Python quirk, not a bug.

Wired in three places:
- `orchestrator/bin/spine` `_mcp_inprocess_call` heredoc — `sys.path.insert(0, SPINE_HOME); sys.path.insert(1, SPINE_HOME + "/verify")`
- `tools/smoke-test.sh` `phase11_tron` — `PYTHONPATH="$REPO_ROOT:$REPO_ROOT/verify"`
- Manual probes — `PYTHONPATH=.:verify .venv/bin/python …`

### Reproducible restart

```bash
cd verify && docker compose down && docker compose up -d postgres && cd ..
.venv/bin/python tools/_tron_alembic_upgrade.py    # idempotent
bash tools/smoke-test.sh --phase 11                # 5 PASS / 0 FAIL
```

### Known TRON-side issues (not patched from Spine)

None blocking. The audit pipeline runs end-to-end with valid API keys.
With invalid keys, the LLM 401's, the agent's exception is caught by
`AuditManager._dispatch_agents`, and `verify_audit` returns
`status=ok, pass_fail=pass, findings=[]` — the audit ran, layers 1+2
were exercised, just zero findings to surface. TRON's design treats
Bandit/Semgrep results as LLM context only (they don't auto-emit as
`FindingOutput`). Surfacing tool-only findings when LLM is unavailable
would be a TRON-side feature, not a Spine-side patch.

## See also

- `docs/ARCHITECTURE.md` §5 (full TRON → Spine code mapping)
- `docs/PRD.md#req-init-8` (Draft v1)
- `verify/README.md` — TRON's own project README (immediately below this file in the same dir)
- `verify/AGENTS.md` — TRON's agent context
- `verify/docs/BLUEPRINT.md` — TRON's canonical doc index
- Original TRON source (pre-subtree): `/Users/khashsarrafi/Projects/Utilities/tron`

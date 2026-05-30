# Session handoff — 2026-05-29

> **Resume here.** Authoritative live state for the current session.
> Updated continuously per [`spine_continuous_handoff` memory rule](../../.claude/projects/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/memory/feedback_continuous_handoff.md).
>
> **Operational queue:** [`MASTER_TODO.md`](MASTER_TODO.md) — current task table + statuses.
> **Strategic plan:** [`ECC_BORROWS.md`](ECC_BORROWS.md) — 9 borrows from `affaan-m/ecc` adapted into Spine.
> **Design decisions:** [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — `#7a`/`#7b`/`#12a`/`#30a` ratified this session.
> **Older context:** prior session (2026-05-23/24) notes archived inline below.

---

## Where we left off (2026-05-29, current session)

User asked Claude to look at `affaan-m/ecc` and identify what to borrow for
Spine. Outcome: 9 borrows identified, 4 V3 ratifications landed, P0s
implemented and tested. User reframed priorities: **Spine itself is the
product; Booger is disposable dogfood** — don't anchor the queue on Booger
unblock.

**Critical reminder from user:** keep this file + `MASTER_TODO.md` updated
continuously so an IDE crash doesn't lose progress. See
[`feedback_continuous_handoff`](../../.claude/projects/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/memory/feedback_continuous_handoff.md).

---

## Done this session (uncommitted)

### Docs
- `docs/ECC_BORROWS.md` — new design note, 9 borrows with target subsystem + ratification need
- `docs/V3_DESIGN_DECISIONS.md` — header note updated; quick index extended (`#7a`, `#7b`, `#12a`, `#30a`); four annotation sub-sections added inline

### P0 — B1 (recursive decision ledger + promotion gate)
- `shared/audit/decision_ledger.py` — new module: `LedgerEntry` (hash-chained JSONL), `PromotionGate.evaluate()` (default-deny; tiers paper/preview/internal/production/destructive), `DecisionLedger` API (append / tail / iter / verify_chain), shadow `AuditRecord` for chain-of-trust
- `shared/audit/tests/__init__.py` — new
- `shared/audit/tests/test_decision_ledger.py` — 14 tests covering append + hash chain + tamper detection + per-tier gate + ID validation + `SPINE_DECISION_LEDGER_ROOT` env override
- Storage default: `~/.spine/decision_ledger/<project_id>/<run_id>.jsonl`

### P0 — B2 (MCP tool response envelope)
- `shared/mcp/schemas/envelopes.py`:
  - `ToolStatus` extended → `ok | warning | error | refusal | stub_implementation`
  - New `Artifact` model + `ArtifactType` literal (`file_path | kg_node | run_id | audit_hash | url | ledger_entry`)
  - `ToolResponse` extended with `summary`, `next_actions`, `artifacts` (all additive — backcompat preserved)
  - `check_envelope_convention()` — soft validator returning violation list
- `shared/mcp/schemas/__init__.py` — exports updated

### P1 — B5 (spine status --markdown handoff generator)
- `orchestrator/cli/__init__.py` — new
- `orchestrator/cli/status_markdown.py` — new Python module: `collect_state` (git / db / ledger / smoke collectors with fail-soft degradation), `render_markdown` (handoff-shaped output), `compute_exit_code` (0 green / 1 warnings / 2 failures), `main` entry point
- `orchestrator/cli/tests/__init__.py` + `test_status_markdown.py` — 17 tests covering renderer sections, exit codes, collector injection, ledger walk, smoke parser
- `orchestrator/bin/spine` — `cmd_status` extended: `--markdown`, `--write PATH`, `--exit-code`, `--ledger-root R`. Default (terse phase-count) preserved. Help text updated.
- Env: `SPINE_DECISION_LEDGER_ROOT` documented

### P1 — B4 (bounded iterative retrieval)
- `shared/runtime/bounded_retrieval.py` — new module: `Need` / `ResolvedNeed` / `Seed` (immutable; `augment()` returns a new instance) / `RetrievalOutcome` / `run_bounded_retrieval()` (4-phase loop, default `max_cycles=3`, emits `cycle_exhausted` warning when bound is hit)
- Wire encoding: roles signal needs via B2 envelope's `next_actions` entries prefixed with `need:` (e.g. `need:kg_node:auth-design|context for AuthN`). Non-need lines pass through unchanged.
- Resolver-exception safe: a raising resolver records `ResolvedNeed(success=False, error=...)` and the loop continues — the role can decide whether to refuse (per #12) or carry on
- Provider-agnostic: the module never calls an LLM; `role_callable` is supplied by the caller (Claude Code / Cursor / charter daemon)
- `shared/runtime/tests/test_bounded_retrieval.py` — 11 tests covering encoding round-trip, immutability, loop bound, resolver failure, accumulation across cycles
- **Not yet wired into `build_dispatcher.py`** — the existing fat-brief path stays the default for backward compatibility; B4 is the opt-in contract every dispatcher (build / plan / verify) can compose with

### P1 — B3 (instinct schema for Smart Spine #27)
- `learning/instinct.py` — new module: `Instinct` (confidence bounded to `[CONFIDENCE_FLOOR=0.3, CONFIDENCE_CEILING=0.9]`; fingerprint = SHA-256 of normalised `pattern + trigger`), `InstinctRecord` (observation with project/run/actor/audit_hash chain link), `InstinctStore` (per-`(project, run)` JSONL, thread-safe append), `check_promotion()` (aggregates across projects; default threshold = 2 distinct projects + avg conf ≥ 0.5), `promote_to_lesson_payload()` (bridges to existing `learning.contribute_lesson` so Tier 1b/2 promotion still routes through the existing consent + anonymizer wiring)
- Storage: `~/.spine/instincts/<project_id>/<run_id>.jsonl` (mirrors B1 ledger shape); env override `SPINE_INSTINCT_ROOT`
- `learning/tests/test_instinct.py` — 13 tests covering confidence bounds, fingerprint stability under whitespace/case, store round-trip, promotion thresholds (project count + avg confidence), payload bridge to lesson

### P2 — B6 (pass@k eval contract for charter regressions)
- `verify/charter_evals/__init__.py` — public surface
- `verify/charter_evals/harness.py` — `CapabilityEval` (yaml-loadable), `EvalCriterion` (required/forbidden substrings), `run_capability_eval()` (N trials via injected `role_callable`), `pass_at_k()` (aggregate + meets_target boolean), `evaluate_charter()` (per-eval pass@k; overall fails on any regression — V3 #7a is a regression gate, not an average)
- Default targets: `target_k=5`, `target_pass_rate=0.8`
- Provider-agnostic; the harness never calls an LLM directly
- `verify/charter_evals/tests/test_harness.py` — 12 tests covering criterion shapes, trial run + failed-criteria recording, role exception handling, pass@k thresholds, role/charter mismatch rejection

### P2 — B7 (SPINE_HOOK_PROFILE runtime gating)
- `shared/runtime/hook_profile.py` — Python helper: `active_profile()` / `disabled_hooks()` / `is_hook_active(name, minimum_profile=...)` / `explain(...)`. Profile levels: `minimal=1 < standard=2 < strict=3`. Env vars: `SPINE_HOOK_PROFILE` and `SPINE_DISABLED_HOOKS` (csv).
- `tools/_hook_profile.sh` — bash counterpart with same semantics: `spine_hook_active_profile`, `spine_hook_is_active <name> [<min>]`, `spine_hook_explain`. Bash 3.2 safe.
- `shared/runtime/tests/test_hook_profile.py` — 16 tests covering env defaults, case-insensitivity, profile-level gating, disabled override, invalid input

### P2 — B8 (search-first contract in Engineer + Architect charters)
- `shared/charters/engineer.md` — new section `## Pre-implementation contract (V3 #7b)` after Hard Rules: 4-step preflight (tool-availability / parallel search / adopt-extend-build matrix / cite or refuse). `build-custom` without citation is a refusal-class event under #12.
- `shared/charters/architect.md` — same section adapted for ADR / TRD / interface-spec drafting (TOGAF Architecture Repository, prior ADRs, public reference architectures).
- Exempts trivial fixes, typo corrections, rollback / revert ops.

### P3 — B9 (Agentic-OS layer table in ARCHITECTURE.md)
- `docs/ARCHITECTURE.md` — new sub-section `### Layer model` under §2 listing the 7-layer Spine runtime model (Kernel / Charters / Commands / Daemons / Workspace / Audit / Instincts) with `Lives in` paths and persistence posture. Adapted from ECC `agentic-os` skill.

### Memory updates (auto-memory tree)
- `spine_booger_disposable.md` — Booger is throwaway; Spine is the product
- `ecc_borrows.md` — 9 borrows tracker
- `feedback_continuous_handoff.md` — keep handoff/todo files updated continuously
- `MEMORY.md` — index updated

---

## Verification (current state)

| Check | Result |
|-------|--------|
| `shared/audit/tests/test_decision_ledger.py` | **14 PASS** |
| `shared/mcp/tests/` (full suite) | **66 PASS** |
| `orchestrator/cli/tests/test_status_markdown.py` | **17 PASS** |
| `shared/runtime/tests/test_bounded_retrieval.py` | **11 PASS** |
| `learning/tests/test_instinct.py` | **13 PASS** |
| `shared/runtime/tests/test_hook_profile.py` | **16 PASS** |
| `verify/charter_evals/tests/test_harness.py` | **12 PASS** |
| **Full session sweep (P0 + P1 + P2 + P3)** | **149 PASS** |
| `spine status --markdown --write FILE --exit-code` (manual) | renders, writes, exits 1 (warnings, DB down) |
| `tools/smoke-test.sh` (Hub down) | 35 PASS / 4 FAIL — all 4 are Postgres-container-not-running; pre-existing, not caused by these changes |
| Git working tree | New + modified, **uncommitted** on `main` |

Full smoke (99 PASS contract) requires Hub up — run `bash tools/hub-up.sh`
then re-smoke before commit.

---

## V3 ratifications landed

| # | Theme | Source borrow |
|---|-------|---------------|
| `#7a` | Charters bind to pass@k regression evals when touched | B6 |
| `#7b` | Engineer + Architect bind to `search-first` pre-implementation contract | B8 |
| `#12a` | Recursive confidence ≠ live promotion; decision ledger + freshness/replay gates | B1 (implemented) |
| `#30a` | Typed MCP envelope (status/summary/next_actions/artifacts); verify-class extends with citations | B2 (implemented) |

---

## In progress

**Nothing in progress. All 9 borrows + 4 V3 ratifications + 3 follow-ups landed and committed.**

Follow-up status (all done):
1. **Committed the batch as 10 Conventional Commits on `main`** (8 in the borrows batch + 2 follow-ups; see `git log --oneline -10`).
2. **B4 wired into `build/runtime/build_dispatcher.py`** as opt-in `dispatch_build_bounded()`. Existing `dispatch_build()` path unchanged. 11 new dispatch tests.
3. **Starter capability evals landed** under `verify/charter_evals/engineer/` (3) and `verify/charter_evals/architect/` (3) + a YAML loader. #7a regression gate now has something to enforce.

**Test totals after follow-ups:** 189 tests pass (was 149 at end of borrow batch).

---

## Reboot routine (~2 min)

```bash
cd ~/Projects/Apps/SpineDevelopment

# Sanity — uncommitted state from this session
git status --short
git diff --stat \
  docs/ECC_BORROWS.md docs/V3_DESIGN_DECISIONS.md \
  shared/audit/decision_ledger.py shared/mcp/schemas/envelopes.py \
  orchestrator/cli/status_markdown.py orchestrator/bin/spine

# Re-run this session's tests (149 should pass)
.venv/bin/python -m pytest \
  shared/audit/tests \
  shared/mcp/tests \
  shared/runtime/tests/test_bounded_retrieval.py \
  shared/runtime/tests/test_hook_profile.py \
  orchestrator/cli/tests \
  learning/tests/test_instinct.py \
  verify/charter_evals/tests \
  -q

# Try the new handoff generator
bash orchestrator/bin/spine status --markdown --write /tmp/handoff.md --exit-code
echo "exit=$?  (1 expected when Hub is down)"

# (Optional, when Hub is back up) full smoke
bash tools/hub-up.sh
bash tools/smoke-test.sh          # target: 99 PASS / 0 FAIL / 1 WARN / 0 SKIP / 3 INFO
```

---

## Files touched this session

```
docs/ECC_BORROWS.md                                  # NEW — design note
docs/V3_DESIGN_DECISIONS.md                          # MODIFIED — #7a/#7b/#12a/#30a annotations
docs/SESSION_HANDOFF.md                              # THIS FILE
docs/MASTER_TODO.md                                  # MODIFIED — live task table
shared/audit/decision_ledger.py                      # NEW — B1
shared/audit/tests/__init__.py                       # NEW
shared/audit/tests/test_decision_ledger.py           # NEW — 14 tests
shared/mcp/schemas/envelopes.py                      # MODIFIED — B2
shared/mcp/schemas/__init__.py                       # MODIFIED — exports
orchestrator/cli/__init__.py                         # NEW — B5
orchestrator/cli/status_markdown.py                  # NEW — B5
orchestrator/cli/tests/__init__.py                   # NEW
orchestrator/cli/tests/test_status_markdown.py       # NEW — 17 tests
orchestrator/bin/spine                               # MODIFIED — wires --markdown / --write / --exit-code
shared/runtime/bounded_retrieval.py                  # NEW — B4
shared/runtime/tests/test_bounded_retrieval.py       # NEW — 11 tests
learning/instinct.py                                 # NEW — B3
learning/tests/test_instinct.py                      # NEW — 13 tests
verify/charter_evals/__init__.py                     # NEW — B6
verify/charter_evals/harness.py                      # NEW — B6
verify/charter_evals/tests/__init__.py               # NEW
verify/charter_evals/tests/test_harness.py           # NEW — 12 tests
shared/runtime/hook_profile.py                       # NEW — B7
shared/runtime/tests/test_hook_profile.py            # NEW — 16 tests
tools/_hook_profile.sh                               # NEW — B7 bash counterpart
shared/charters/engineer.md                          # MODIFIED — B8 pre-implementation contract
shared/charters/architect.md                         # MODIFIED — B8 pre-implementation contract
docs/ARCHITECTURE.md                                 # MODIFIED — B9 layer model table

# Auto-memory tree (outside repo)
~/.claude/projects/.../memory/MEMORY.md              # MODIFIED — index
~/.claude/projects/.../memory/spine_booger_disposable.md   # NEW
~/.claude/projects/.../memory/ecc_borrows.md               # NEW
~/.claude/projects/.../memory/feedback_continuous_handoff.md  # NEW
```

---

## Booger (downgraded to P3)

Per user 2026-05-29: "booger is just a test application... we need the spine
project to work." Booger is throwaway dogfood. State as of 2026-05-25 (from
prior session's notes):

| Field | Value |
|-------|--------|
| UUID | `c94d5f8c-5c7a-40a1-9da9-e25fcca63c88` |
| Phase | `build_in_progress` |
| Stuck | yes (`fix_loop_exhausted` + `no_pending_decisions`) |

Do **not** treat Booger unblock as gating. If a Spine capability gap surfaces
only by exercising Booger, fix the gap in `shared/`; don't ship Booger-only
patches.

---

## Prior session (2026-05-23/25) — archived inline

Project-scoped nav, intake transcript persistence, project CRUD, hung-site
performance fixes, workspace runtime refactor (`projectWorkspace.ts`,
`uiFrameScheduler.ts`, extracted leaf components), Playwright e2e for Booger
workspace. SPA unit tests `60 PASS` at end of that session. Full detail kept
in git history of this file before 2026-05-29.

---

*Last updated: 2026-05-29 (late) — all 9 ECC borrows + 4 V3 ratifications + 3 follow-ups (commit batch, B4 dispatcher wiring, starter evals) committed in one session. 189 tests pass; 10 new commits on main.*

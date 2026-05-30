# Master TODO — operational queue

> **Resume here.** Living task list for *what to do next* on Spine development.
> Last updated: **2026-05-29**
>
> **Related docs (do not duplicate their role):**
> - [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) — current-session state (authoritative on resume)
> - [`ECC_BORROWS.md`](ECC_BORROWS.md) — 9 borrows from `affaan-m/ecc` with target subsystem + ratification need
> - [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — locked decisions (incl. new #7a/#7b/#12a/#30a)
> - [`SPINE_MASTER.md`](SPINE_MASTER.md) — vision, gap matrix, execution tracker (§8)
> - [`BACKLOG.md`](BACKLOG.md) — strategic INIT / EPIC / STORY backlog
> - [`V1_SHIP_CHECKLIST.md`](V1_SHIP_CHECKLIST.md) — customer launch ops gates

---

## Active focus

**Spine capability — ECC borrows.** P0s (B1 decision ledger + B2 MCP
envelope) implemented and tested. P1s next. Per user 2026-05-29, Spine itself
is the product and Booger is disposable dogfood — do not gate the queue on
Booger.

---

## Live task table

| # | Task | Status | Builds on | Files |
|---|------|--------|-----------|-------|
| 1 | Draft ECC borrows design note | **DONE** | — | `docs/ECC_BORROWS.md` |
| 2 | **B1** — P0 decision ledger + promotion gate | **DONE** | — | `shared/audit/decision_ledger.py` (+ 14 tests) |
| 3 | **B2** — P0 MCP tool response envelope | **DONE** | — | `shared/mcp/schemas/envelopes.py` (+ exports) |
| 4 | **B3** — P1 instinct schema for Smart Spine #27 | **DONE** | B1 | `learning/instinct.py` (+ 13 tests) |
| 5 | **B4** — P1 bounded iterative retrieval | **DONE** | B2 | `shared/runtime/bounded_retrieval.py` (+ 11 tests) |
| 6 | **B5** — P1 `spine status --markdown` handoff generator | **DONE** | B1 | `orchestrator/cli/status_markdown.py` (+ 17 tests) + `orchestrator/bin/spine` |
| 7 | **B6** — P2 pass@k eval contract for charter regressions | **DONE** | B1 | `verify/charter_evals/harness.py` (+ 12 tests) |
| 8 | **B7** — P2 `SPINE_HOOK_PROFILE` runtime gating | **DONE** | — | `shared/runtime/hook_profile.py` (+ 16 tests) + `tools/_hook_profile.sh` |
| 9 | **B8** — P2 `search-first` step in Engineer + Architect charters | **DONE** | B1 | `shared/charters/{engineer,architect}.md` |
| 10 | **B9** — P3 Agentic-OS layer table in ARCHITECTURE.md | **DONE** | — | `docs/ARCHITECTURE.md` |
| 11 | Land V3 ratifications (#7a/#7b/#12a/#30a) | **DONE** | — | `docs/V3_DESIGN_DECISIONS.md` |

---

## Next up (priority order)

| P | Task | Status |
|---|------|--------|
| **P0** | Commit P0 + P1 batch (1 doc PR; 5 code PRs for B1, B2, B3, B4, B5) | Pending (you) |
| **P1** | **B3** instinct schema for #27 | **DONE** |
| **P1** | **B4** bounded retrieval contract (not yet wired into `build_dispatcher.py`) | **DONE (module)** |
| **P1** | **B5** `spine status --markdown` | **DONE** |
| **P2** | **B6** pass@k eval contract for charter regressions | **DONE** |
| **P2** | **B7** `SPINE_HOOK_PROFILE` runtime gating | **DONE** |
| **P2** | **B8** `search-first` step in Engineer + Architect charters | **DONE** |
| **P3** | **B9** ARCHITECTURE layer model | **DONE** |
| **F1** | Commit the batch (10 Conventional Commits on main) | **DONE** |
| **F2** | Wire B4 into `build/runtime/build_dispatcher.py` — opt-in `dispatch_build_bounded()` | **DONE** |
| **F3** | Starter capability evals under `verify/charter_evals/{engineer,architect}/` + YAML loader | **DONE** |
| **P2** | B6 / B7 / B8 (parallelisable) | Pending |
| **P3** | B9 ARCHITECTURE layer table | Pending |
| **P3** | Booger unblock — only if it exposes a Spine capability gap | Backlog (downgraded per user 2026-05-29) |

---

## Verification snapshot (2026-05-29)

| Check | Result |
|-------|--------|
| `shared/audit/tests/test_decision_ledger.py` | **14 PASS** |
| `shared/mcp/tests/` full suite | **66 PASS** |
| `orchestrator/cli/tests/test_status_markdown.py` | **17 PASS** |
| `shared/runtime/tests/test_bounded_retrieval.py` | **11 PASS** |
| `learning/tests/test_instinct.py` | **13 PASS** |
| `shared/runtime/tests/test_hook_profile.py` | **16 PASS** |
| `verify/charter_evals/tests/test_harness.py` | **12 PASS** |
| **Full session sweep** | **149 PASS** |
| `spine status --markdown` round-trip | renders / writes / exits 1 when DB down (expected) |
| `tools/smoke-test.sh` (Hub down) | 35 PASS / 4 FAIL — failures are Postgres-container-not-running, not caused by this session's changes |
| Git | working tree dirty; nothing from this session committed |

Full smoke requires `bash tools/hub-up.sh` first to reach the 99 PASS contract.

---

## Reboot / resume routine

```bash
cd ~/Projects/Apps/SpineDevelopment

# 1. See what's uncommitted from the last session
git status --short

# 2. Re-validate this session's work (149 tests should pass)
.venv/bin/python -m pytest \
  shared/audit/tests \
  shared/mcp/tests \
  shared/runtime/tests/test_bounded_retrieval.py \
  shared/runtime/tests/test_hook_profile.py \
  orchestrator/cli/tests \
  learning/tests/test_instinct.py \
  verify/charter_evals/tests \
  -q

# 3. Read the handoff (auto-generatable now: `spine status --markdown`)
bash orchestrator/bin/spine status --markdown --write /tmp/handoff.md --exit-code
cat docs/SESSION_HANDOFF.md

# 4. (When ready) bring Hub back up and confirm full smoke
bash tools/hub-up.sh
bash tools/smoke-test.sh
```

---

## Tier map (where bigger work lives)

| Tier | Doc | Use for |
|------|-----|---------|
| Operational queue | **This file** | What to do today / this session |
| Live session state | [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) | Mid-session checkpoint; resume after crash |
| Strategic borrows plan | [`ECC_BORROWS.md`](ECC_BORROWS.md) | 9 ECC borrows with sequencing |
| Execution tracker | `SPINE_MASTER.md` §8 | P0/P1 wiring checkboxes |
| Strategic backlog | `BACKLOG.md` | INIT / EPIC / STORY for releases |
| Launch gates | `V1_SHIP_CHECKLIST.md` | Customer ship ceremony |

---

*Update this file whenever a task closes, a new one is added, or focus shifts.
Keep in lockstep with the in-conversation TaskList so a crash recovers cleanly.*

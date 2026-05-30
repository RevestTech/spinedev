# Parallel work plan — 2026-05-29

> **Coordination contract for parallel sub-agents.** Read this fully
> before writing anything. Each agent owns exactly one file (or one
> tightly-scoped set of files) and **must not** touch any path outside
> its ownership. The main thread does the final wiring step serially
> after all agents return.

## Rules every agent follows

1. **Stay in your lane.** Only edit / create files under your `OWNS`
   list. Even if you see something broken nearby, flag it in your
   report — do not fix it. Conflict avoidance > opportunism.
2. **No churn on shared files.** `verify/agent_audit/twelve_layer.py`,
   `verify/charter_evals/harness.py`, `shared/runtime/bounded_retrieval.py`,
   `docs/SESSION_HANDOFF.md`, `docs/MASTER_TODO.md` are MAIN-THREAD-ONLY.
   Read them, do not write them.
3. **Match the existing style.** Pydantic v2 models with
   `ConfigDict(frozen=True, extra="forbid")`, dataclasses where
   immutability is sufficient, named exports via `__all__`, tests
   under `tests/` with `test_<topic>.py`.
4. **Write tests for everything new.** Aim for ≥ 80% coverage; mock
   external state with dependency-injected callables (see
   `verify/agent_audit/twelve_layer.py` `LayerCheck` for the pattern).
5. **Report compactly.** End your turn with a 5-line max summary:
   what you created, where, test count, anything that surprised you.
   Do **not** narrate.

## Layer check agents (Group A — B10 instrumentation)

Each fills in one of B10's `instrumentation_pending` layers. Each
follows the `LayerCheck` contract in
`verify/agent_audit/twelve_layer.py`. New files only — never edit
`twelve_layer.py`. The main thread wires the new check into
`DEFAULT_CHECKS` after you return.

| Agent | Layer | OWNS | Reads (don't write) |
|---|---|---|---|
| A1 | L02 session_history | `verify/agent_audit/checks/session_history.py` + `verify/agent_audit/checks/tests/test_session_history.py` | `.spine/work/`, `shared/runtime/role_runtime.py` |
| A2 | L04 distillation | `verify/agent_audit/checks/distillation.py` + matching test | `shared/audit/audit_record.py`, `shared/audit/exporter.py` |
| A3 | L05 active_recall | `verify/agent_audit/checks/active_recall.py` + matching test | `shared/runtime/kg_role_context.py` |
| A4 | L07 tool_execution | `verify/agent_audit/checks/tool_execution.py` + matching test | `shared/mcp/server.py`, `shared/mcp/cite_or_refuse.py` |
| A5 | L08 tool_interpretation | `verify/agent_audit/checks/tool_interpretation.py` + matching test | `shared/runtime/bounded_retrieval.py` |
| A6 | L10 transport | `verify/agent_audit/checks/transport.py` + matching test | `shared/api/`, `shared/ui/spa/` |

## Group B — new modules

| Agent | Scope | OWNS |
|---|---|---|
| B1 | B11 borrow: agent-introspection-debugging | `verify/agent_audit/introspection.py` + `verify/agent_audit/tests/test_introspection.py` |
| B2 | Anthropic-backed role_callable for charter evals | `verify/charter_evals/anthropic_callable.py` + `verify/charter_evals/tests/test_anthropic_callable.py` |

## Group C — capability eval expansion

Each lands 3 YAML capability evals in a new role directory under
`verify/charter_evals/`. No code changes — the loader handles any role
dir automatically. Use the existing engineer/architect YAMLs as shape
templates.

| Agent | Role | OWNS |
|---|---|---|
| C1 | qa | `verify/charter_evals/qa/*.yaml` (3 files) |
| C2 | planner | `verify/charter_evals/planner/*.yaml` (3 files) |
| C3 | auditor | `verify/charter_evals/auditor/*.yaml` (3 files) |

## Group D — design + ops (Plan-type)

| Agent | Scope | OWNS |
|---|---|---|
| D1 | Pgvector KG search design note | `docs/PGVECTOR_KG_DESIGN.md` |
| D2 | Operating company loop gap analysis (SPINE_MASTER §4) | `docs/OPERATING_LOOP_GAP.md` |
| D3 | Hub-up + full smoke triage | reports only — no files |

## Group E — waste/audit

| Agent | Scope | OWNS |
|---|---|---|
| E1 | Whole-codebase waste finder (read-only) | reports only — no files |

## Main-thread responsibilities (after agents return)

1. Wire new layer checks into `DEFAULT_CHECKS` in `twelve_layer.py`.
2. Wire new modules' exports into the relevant `__init__.py` files.
3. Run the full test suite; merge any new test files into the
   existing smoke command.
4. Commit per-agent (one Conventional Commit per agent) so the
   history reads cleanly.
5. Update `docs/SESSION_HANDOFF.md` + `docs/MASTER_TODO.md`.

---

*Filed 2026-05-29 — all agents dispatched in a single message after
this doc lands. Agents that finish without conflicts merge cleanly;
agents that report blockers escalate to the main thread.*

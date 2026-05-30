# Spine codebase waste audit — 2026-05-29

> **Source:** Agent E1 (read-only Explore subagent) in the parallel
> batch documented in `docs/PARALLEL_WORK_PLAN.md`. The user
> explicitly requested a whole-codebase waste sweep; findings are
> captured here so they survive future sessions and can be triaged
> over time. Each finding cites a file path so it is actionable
> without rerunning the audit.

## 1. Dead code

1. **high — `migration/_v1_v2_migrator_legacy.py`.** Orphaned v1→v2
   migration shim, already marked "do NOT call" per #33. Preserved
   only as a doc. Consider archiving to `docs/history/` instead of
   keeping the import overhead.
2. **low — `shared/api/routes/_pipeline_bridge.py:83-86`.**
   `workspace_host_path()` is a passthrough that re-imports and
   delegates to `shared.runtime.project_workspace.workspace_host_path()`;
   two definitions exist. Merge into one.

## 2. Duplication / cost-logic coverage gap

3. **high — `shared/cost/router.py` and siblings.** Six core cost
   modules (`classifier.py`, `router.py`, `team_router.py`,
   `user_override.py`, `model_selection_table.py`,
   `complexity_scorer.py`) carry zero test coverage. High-leverage
   for quota / budget enforcement and exactly the surface the user
   has previously been burned by parallel implementations on.
   Highest-priority test gap.

## 3. Bloat / monolith files

4. **critical — `shared/api/routes/_post_ack.py` (2237 lines).**
   Monolithic hook handler covering phase advance, dispatch bridge,
   error recovery, and inline LLM prompts for `product`,
   `conductor`, `release_manager`, `security_engineer` (this last
   bit is also flagged in `OPERATING_LOOP_GAP.md` §3). Suggested
   split: `phase_advance.py` + `dispatch_bridge.py` +
   `error_recovery.py`. Estimated effort: 4-6 hours.
5. **critical — `shared/mcp/tools/kg.py` (1832 lines).** Bundles 9
   graph queries plus hybrid_search plus ID resolvers. Suggested
   split: `kg_graph.py` + `kg_hybrid.py` + `kg_resolvers.py`.
   Estimated effort: 2-3 hours.
6. **high — `shared/api/routes/_post_ack.py` +
   `_pipeline_bridge.py` + `_role_dispatch_bridge.py`.** Phase
   transition, role dispatch, and approval gating spread across
   three interdependent files. Suggested consolidation to a new
   `shared/orchestration/` package (`dispatch.py` + `phase.py`).
7. **medium — `verify/tron/workflows/activities.py` (1942 lines).**
   Temporal activity swarm; split by domain
   (`iso_activities.py` + `sandbox_activities.py` +
   `validation_activities.py`).

## 4. Test gaps

8. **high — `shared/cost/*` (6 modules, 0 tests).** See finding #3.
9. **high — `shared/eval/*` (6 modules, 0 tests).** `runner.py`,
   `aggregator.py`, `reporter.py`, `loader.py`, `scorer.py`,
   `cli.py` carry zero test coverage.
10. **medium — `build/kg/*`.** Indexer + diff_engine +
    watcher_extension carry only 9 test files across the whole
    `build/kg/` subsystem.

## 5. MCP V3 #30a envelope adoption

11. **medium — 10 MCP tool modules still on the legacy envelope.**
    Adopted by `auditor`, `evidence`, `verify`, `sandbox`,
    `orchestrator`, `build`. Still on the pre-B2 shape (no
    `summary` / `next_actions` / `artifacts`): `plan.py`,
    `federation.py`, `license.py`, `learning.py`, `kg.py`,
    `iso.py`, `migration.py`, `integrations.py`, `standards.py`,
    `recovery.py`. The B10 L10 transport check independently
    flagged this from the SPA side (no consumer renders the new
    fields yet).

## 6. Stale TODOs

12. **medium — `shared/cost/router.py:6,275`.** TODOs for
    STORY-1.5.2 (per-turn classifier) and STORY-1.5.4 (prompt
    cache) marked in code but not tracked in
    `orchestrator/state/phases.yaml` or `docs/MASTER_TODO.md`.
    Confirm priority or move to backlog.
13. **low — `shared/mcp/server_remote.py:860`.** Vague "Wave 5+"
    TODO for `remote_mcp_event_publisher` registry. Clarify scope
    or move to `BACKLOG.md`.

## 7. UI/SPA prior-session debt

14. **low — `shared/ui/spa/` uncommitted from a prior session.**
    698 insertions across 13 files refactoring the project
    workspace into an isolated SSE store + child panels.
    `RoleTerminalLive.svelte` deleted; new components
    (`PipelineActivityLog`, `PipelineRecoveryControls`,
    `ProjectWorkspaceRuntime`, `ProjectWorkspaceTabs`,
    `PipelineRecoveryHeader`) are clean and follow the store
    isolation pattern. **Status: ready to commit, no abandoned
    code detected.** The earlier session crashed before commit and
    the work has been deferred ever since.

---

## Top 5 highest-leverage wins

1. **Split `shared/api/routes/_post_ack.py` (2237 lines)** into
   `phase_advance.py` + `dispatch_bridge.py` + `error_recovery.py`.
   Eliminates branching complexity, improves testability, reduces
   per-file cognitive load. Estimated effort: 4-6 hours.
2. **Add tests for `shared/cost/*`** — pytest fixtures for
   `router.py` / `classifier.py` / `team_router.py` integration
   tests (cost ledger mocking + budget gate scenarios).
   Estimated effort: 3-4 hours. Unblocks quota enforcement
   correctness.
3. **Split `shared/mcp/tools/kg.py` (1832 lines)** into `kg_graph.py`
   + `kg_hybrid.py` + `kg_resolvers.py`. Aligns with the tool-registry
   expectations and enables per-tool testing. Estimated effort:
   2-3 hours.
4. **Adopt the V3 #30a envelope on the 10 lagging MCP tools.** Adds
   `summary` / `next_actions` / `artifacts` to `plan.py`,
   `federation.py`, `license.py`, `learning.py`, `kg.py`, `iso.py`,
   `migration.py`, `integrations.py`, `standards.py`, `recovery.py`.
   Pairs with the L10 transport finding. Estimated effort: 1-2
   hours.
5. **Commit the prior-session SPA refactor (finding #14).** It is
   clean and complete; the only reason it remains uncommitted is
   the crash that triggered the very first message of this session.

---

*Filed 2026-05-29 by Agent E1. No code changes were made during the
audit — these are read-only findings for future triage.*

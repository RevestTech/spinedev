# Operating Loop Gap Analysis — SPINE_MASTER §4

> **Filed:** 2026-05-29 — Agent D2 (parallel batch).
> **Scope:** SPINE_MASTER §4 line *"the operating company loop is still
> unwired end-to-end."* This doc inventories the wirings missing
> between intake and operate, with concrete file + function targets.

**Sources read:** `docs/SPINE_MASTER.md` §1-§4 + §8;
`docs/V3_DESIGN_DECISIONS.md` #7/#7a/#11/#12/#12a/#19/#21/#27/#30a/#34;
`orchestrator/state/phases.yaml`; `orchestrator/lib/*.sh`;
`build/runtime/{hub_role_runner.py,build_dispatcher.py,engineer_squad.py,engineer_hybrid.py}`;
`plan/runtime/{intake_runner.py,hub_role_runner.py}`;
`verify/runtime/hub_verify_runner.py`;
`devops/runtime/hub_deploy_runner.py`;
`shared/runtime/{phase_watcher.py,role_runtime.py,smart_spine_bridge.py}`;
`shared/audit/decision_ledger.py`; `learning/instinct.py`;
`verify/charter_evals/harness.py`; `docs/MASTER_TODO.md`.

---

## 1. What works end-to-end today

Concrete pieces that *do* compose:

- **Phase machine.** `orchestrator/state/phases.yaml` is canonical and
  the orchestrator bash (`orchestrator/lib/router.sh`, `gate.sh`,
  `transition.sh`, `verify_dispatcher.sh`, `remediation.sh`,
  `rollback.sh`) reads it. Phase IDs run intake → plan_in_progress →
  plan_approved → build_in_progress → build_complete →
  verify_in_progress → verify_approved → acceptance → released →
  operate → retro.
- **Intake stage.** `plan/runtime/intake_runner.py.run_intake()` walks
  the YAML template, persists answers under `metadata.intake`, then
  drafts a `PRDv1`-validated PRD into `metadata.prd_draft` (audit rows
  `intake_started`, `prd_draft_persisted`).
- **Plan-class roles.** `plan/runtime/hub_role_runner.py._ROLE_CONFIG`
  wires planner → `roadmap_md`, architect → `trd_md`, conductor →
  `sprint_plan_md`, qa → `qa_md`, release_manager →
  `release_gate_md`. Each call retrieves KG context
  (`shared/runtime/kg_role_context.retrieve_kg_context_for_dispatch`),
  opens a directive (`shared/runtime/role_runtime.begin_directive`), and
  on success promotes artifacts to project git
  (`shared/runtime/project_workspace.promote_plan_artifacts`).
- **Architect swarm.** `plan/runtime/architect_swarm_runner.run_swarm`
  (LangGraph-backed) is dispatched on architect.
- **Build (engineer).** `build/runtime/hub_role_runner._run_engineer`
  runs hybrid (`engineer_hybrid.run_hybrid_engineer` via `executor.sh`)
  → squad (`engineer_squad.run_engineer_squad` for fe/be/db
  specialties) → LLM fallback, parses FILE/RUN blocks, writes to
  `resolve_code_dir`, bootstraps git via
  `project_workspace.bootstrap_project_git_repo`, commits via
  `commit_workspace`, persists `code_intro_md`, `last_commit_sha`,
  `kg_last_index_files`.
- **KG indexer.** `build/kg/indexer_commit_hook.py` installs a
  `post-commit` hook into each project's git repo on bootstrap;
  `build/kg/indexer/indexer.py` writes to `spine_kg.kg_node`/`kg_edge`.
  `build/kg/indexer_audit_subscriber.py` consumes audit events.
- **Verify (TRON).** `verify/runtime/hub_verify_runner.py` invokes the
  `verify_audit` MCP tool through
  `shared/runtime/mcp_invoke.invoke_mcp_tool`, classifies severity,
  persists `code_review_md`. Bash side:
  `orchestrator/lib/verify_dispatcher.sh` enforces the `verify_config`
  from `phases.yaml` (`auto_remediation_severity`, on_high →
  build_in_progress).
- **DevOps install + local deploy.**
  `build/runtime/hub_role_runner._run_devops_install` executes the
  engineer-emitted RUN block;
  `devops/runtime/hub_deploy_runner.run_devops_hub_role` proxies to
  `_post_ack._dispatch_local_deploy` for container deploy on the
  released gate.
- **Phase watcher.** `shared/runtime/phase_watcher.phase_watcher_tick`
  advances 6 transitions automatically (PRD→roadmap, roadmap→TRD,
  TRD→sprint plan, sprint plan→code, code→review, install→qa), polling
  every `SPINE_PHASE_WATCHER_POLL_SECS` (default 30s).
- **Audit + workspace.** Every directive writes
  `.spine/work/<project_uuid>/directives/<directive_id>/`
  (status.json, directive.md, report.md) via `role_runtime`.
  Hash-chained audit through `shared/audit/audit_record.write_via_psql`.
- **Smart Spine bridge (lessons only).**
  `shared/runtime/smart_spine_bridge.record_role_outcome` writes a
  one-line lesson into `learning.contribute_lesson` on successful
  dispatch.

That covers stages 1–6 happy path *for `feature`-class greenfield
projects* when an API key is present.

---

## 2. Gaps by loop stage

### Stage 1 — Intake → PRD

- **Stage/role:** Intake / product.
- **What's missing:** `plan/runtime/intake_runner.run_intake` is
  `stdin`-driven (`IntakeNotInteractive`). The hub UI chat does not
  call it; there is no `product` charter runtime (`product` is *not*
  in `plan/runtime/hub_role_runner._ROLE_CONFIG`). PRD is
  template-synthesized, not charter-prompted. Product role's 5-move
  protocol (SPINE_MASTER §2.1 step 2) is absent.
- **Where it should land:** new `plan/runtime/product_runner.py` with
  `run_product()` taking the intake answers and producing a
  charter-grounded PRD; add `"product": (_PRODUCT_PROMPT, "prd_md")`
  to `_ROLE_CONFIG`; add an HTTP path in `shared/api/routes/intake.py`
  that dispatches `product` instead of the bare template.
- **Proof test:** new test under
  `plan/runtime/tests/test_product_runner.py` that feeds intake
  answers and asserts PRD has all sections + product charter
  signature, and that the directive bus has a `product` row.
- **Effort:** M.

### Stage 2 — Architect TRD + ADRs

- **Stage/role:** Architect.
- **What's missing:** swarm runs but produces only `trd_md`; no ADR
  artifacts (#7 mentions charters anchored in TOGAF/PMBOK with ADR
  discipline). `search-first` charter contract (#7b) is not enforced
  at the runner — the architect prompt does not call `pip-index` /
  `npm view` / `gh search` preflight.
- **Where it should land:** extend
  `plan/runtime/architect_swarm_runner.py` to emit
  `adr_drafts: list[ADR]` and persist under `metadata.adr_drafts`;
  add `shared/runtime/search_first_preflight.py` that runs registry +
  MCP catalog probes and writes an entry to
  `shared.audit.decision_ledger` before the role completes.
- **Proof test:** unit test asserts ADR list is non-empty after a
  swarm run and that a decision-ledger entry with `prior accepted
  winner` mention exists for any "build-custom" decision.
- **Effort:** M.

### Stage 3 — Planner roadmap

- **Stage/role:** Planner. Currently wired — only gap is that planner
  does **not** consult prior project lessons
  (`learning.scope.ScopeContext.within_hub_lessons`). The roadmap is
  generated from PRD only.
- **Where it should land:** modify
  `plan/runtime/hub_role_runner._run_text_role` to retrieve top-K
  relevant lessons for the `planner` role via `learning.contribute`
  query path, append to `context_blocks`.
- **Proof test:** seed two prior project lessons; new planner
  directive references them in `extra_context`.
- **Effort:** S.

### Stage 4 — Conductor sprint plan

- **Stage/role:** Conductor.
- **What's missing:** Conductor currently produces `sprint_plan_md`
  directly from TRD; it does not enforce workspace hygiene (#34) —
  there is no per-project pre-check that
  `.spine/work/<uuid>/directives/` is clean before the conductor
  marks the sprint planned, and no `Conductor gate` that refuses done
  if uncleaned state exists. `shared/runtime/hygiene.py` exists but
  is not called by the conductor runner.
- **Where it should land:** wrap `_run_text_role` for `conductor` with
  a `hygiene.assert_workspace_clean(project_uuid)` call; new helper
  `shared/runtime/hygiene.assert_workspace_clean` that scans for
  orphaned `running` directives and stale `.spine/work` dirs.
- **Proof test:** sprint plan directive run against a project with a
  lingering `running` directive raises and surfaces a gap card.
- **Effort:** S.

### Stage 5 — Engineer implements

- Largely wired. Two open seams:
  1. **`build/runtime/hub_role_runner._run_engineer` does not append
     the search-first preflight result** before generating code (#7b).
     Engineer charter `B8` was added but the runtime does not enforce.
  2. **`dispatch_build_bounded` (B4 bounded retrieval) exists but no
     caller invokes it.** Only `dispatch_build` is wired into
     `_post_ack` / `hub_role_runner`.
- **Where it should land:**
  `build/runtime/hub_role_runner._run_engineer` — after KG context
  retrieval, call a new
  `shared/runtime/search_first_preflight.preflight_for_engineer(project)`
  and append to `extra_context`; introduce `SPINE_ENGINEER_BOUNDED=1`
  env flag to route through `dispatch_build_bounded`.
- **Proof test:** directive run carries the preflight block;
  `metadata.brief_mode == "bounded_retrieval"` when flag set.
- **Effort:** S.

### Stage 6 — QA + Auditor (Cite-or-Refuse)

- **Stage/role:** QA + Auditor.
- **What's missing:**
  - QA runner exists (`plan/runtime/hub_role_runner` qa entry) but
    lives on the *plan* side and produces a test *plan* only — there
    is no QA *execution* runner that runs the sprint plan's
    acceptance criteria against the engineer's commit.
  - **Auditor role is not wired into the build loop.**
    `build/runtime/hub_role_runner.run_build_hub_role` returns
    `error_class="not_implemented_in_runner"` for `auditor` and
    `security_engineer`. Code review still flows through
    `_post_ack.py` inline LLM despite the bridge being labelled
    wired.
  - **Cite-or-Refuse (#12) is not enforced.**
    `verify/runtime/hub_verify_runner` loads `auditor.md` as prompt
    text but never returns a `"refusal"` envelope (#30a) when
    citations are missing. `shared/mcp/cite_or_refuse.py` is not
    called from the verify runner.
- **Where it should land:**
  - new `verify/runtime/auditor_runner.py` with
    `run_auditor(project, citations_required=True)` that produces
    `audit_md` and emits an MCP-envelope refusal when citations are
    absent;
  - register `"auditor"` in
    `build/runtime/hub_role_runner.run_build_hub_role` to call it;
  - new `verify/runtime/qa_execution_runner.py` that drives the
    engineer's RUN block against the sprint plan's acceptance
    criteria, persists `qa_execution_md`;
  - add a watcher rule
    `(verify_approved, "metadata ? 'qa_md' AND NOT (metadata ? 'audit_md')", "auditor_approval")`
    to `shared/runtime/phase_watcher._WATCH_RULES`.
- **Proof test:** auditor directive with missing citations writes
  `status="refusal"` envelope (per #30a); MASTER_TODO refusal count
  increments; verify runner re-enters build_in_progress on auditor
  refusal.
- **Effort:** L.

### Stage 7 — DevOps deploy (#11 Operate)

- **Stage/role:** DevOps / release_manager / operator.
- **What's missing:**
  - `released → operate` transition has no runtime. `phases.yaml.operate`
    has `role_lead: operator` and no Python runner exists for it;
    `phase_watcher._WATCH_RULES` stops at `devops_install_ok`.
  - **8 control planes (#11) are scaffolded but not invoked.**
    `devops/mcp_tools.py` exposes operate-tagged tools but no
    dispatch path calls them on `released`.
  - **`release_manager` produces a Ship Gate markdown only**; nothing
    consumes its `Cloud deploy options` to actually invoke a chosen
    target.
- **Where it should land:**
  - new `devops/runtime/operate_runner.py` with `run_operate(project)`
    that exercises the 8 control planes' health endpoints (each plane
    gets its own check function reading `devops/planes/`);
  - extend `phase_watcher._WATCH_RULES` with
    `("released", "metadata ? 'deploy_result' AND NOT (metadata ? 'operate_started_at')", "operate_kickoff")`;
  - extend `devops/runtime/hub_deploy_runner.run_devops_hub_role` with
    an `OPERATE` directive branch.
- **Proof test:** operate runner posts heartbeat row for each of 8
  planes; transitioning `released → operate` is automatic.
- **Effort:** L.

### Stage 8 — Smart Spine learning (#27, B3-shaped)

- **Stage/role:** Cross-cutting on every successful directive.
- **What's missing:**
  - `shared/runtime/smart_spine_bridge.record_role_outcome` only
    writes **lessons** via `learning.contribute_lesson`. B3 atomic
    **instincts** (`learning/instinct.py.record_instinct`) are never
    called from any runner. So `spine_learning.instinct` JSONL stays
    empty; lesson promotion ladder never starts.
  - No `learning.instinct.check_promotion` call exists outside the
    test suite — no scheduled promotion sweep.
- **Where it should land:**
  - add `learning.instinct.record_instinct` call to
    `smart_spine_bridge.record_role_outcome` with a fingerprint built
    from `(role, directive)`;
  - new `shared/runtime/instinct_promotion_loop.py` mounted in Hub
    lifespan (sister to `phase_watcher`) that runs
    `check_promotion` per project per N minutes.
- **Proof test:** two synthetic dispatches with identical fingerprint
  → instinct count = 1; third dispatch crosses threshold → lesson
  appears in `learning.contribute_lesson` corpus.
- **Effort:** M.

### Stage 9 — Audit chain + decision ledger (#12a, B1)

- **What's missing:** B1 `shared/audit/decision_ledger.py` is fully
  implemented but **only `orchestrator/cli/status_markdown.py` reads it**.
  No runtime *writes* `LedgerEntry` rows on
  Conductor/Auditor/QA rollouts. `PromotionGate` is never invoked
  before `released → operate` or `acceptance → released`. The phase
  machine treats `gate: user_approval` as the only promotion check;
  freshness + replay gates from #12a are absent.
- **Where it should land:**
  - new helper
    `shared/audit/decision_ledger_io.append_promotion_decision(project_uuid, role, candidates, prior_winner, freshness_ok, replay_ok)`;
  - call site in `plan/runtime/hub_role_runner._run_text_role` for
    `conductor` and in new `verify/runtime/auditor_runner.run_auditor`;
  - phase-gate hook in `orchestrator/lib/gate.sh` (bash) that shells
    to `python -m shared.audit.decision_ledger_io check --project-id`
    and refuses transition if the latest ledger entry's
    `promotion_gate.verdict == "denied"`.
- **Proof test:** auditor refusal writes a ledger entry; `released`
  gate refuses to advance when promotion gate is denied.
- **Effort:** M.

---

## 3. Cross-cutting gaps

- **KG queryability.** `kg_role_context.retrieve_kg_context_for_dispatch`
  is called per role, but the queries are role-text-only (charter +
  phase). No role queries the KG for **its own prior artifacts**
  (planner doesn't pull prior roadmaps; auditor doesn't pull prior
  audit nodes). This breaks #27 Tier 1a.
- **Decision ledger consumption.** Even when ledger entries get
  written (after the above fix), no role reads them.
  Conductor/QA/Auditor charters should *cite* prior ledger entries to
  satisfy #12 + #12a coherence marks.
- **Charter eval enforcement (#7a).**
  `verify/charter_evals/harness.py` and `run.py` exist; suites are
  present for engineer/architect/qa/planner/auditor. But the CI gate
  that runs `evaluate_charter` when `shared/charters/*.md` changes is
  not wired in `tools/smoke-test.sh` or any pre-commit hook. Charter
  edits today silently merge.
- **Instinct capture in role runtime.** Per stage 8 above — every
  runner needs to emit at least one `record_instinct` call. The
  cleanest hook is inside
  `shared.runtime.role_runtime.complete_directive` so all six
  runtimes inherit it for free.
- **Workspace hygiene gate (#34).** `shared/runtime/hygiene.py` is
  not enforced anywhere. Conductor should refuse done if
  `.spine/work/<uuid>/` has stale `running` status. `make hygiene`
  exists but is manual.
- **MCP envelope conformance (#30a, B2).**
  `shared/mcp/schemas/envelopes.py` is implemented but only the new
  tools use it. Verify-class refusals from the auditor/QA path must
  return `status="refusal"` for the loop to detect them; today verify
  returns plain markdown.
- **`_post_ack.py` legacy fallback.** Several roles (`auditor`,
  `security_engineer` code review, product) still flow through inline
  `_ENGINEER_PROMPT` / `_RELEASE_PROMPT` constants in
  `shared/api/routes/_post_ack.py`. SPINE_MASTER §4 P0 says inline
  LLM fallback was removed, but the post_ack file still owns these
  prompts — the dispatch bridge falls back when the runner returns
  `not_implemented_in_runner`.

---

## 4. Recommended P0 wiring slate (5–7 items, dependency-ordered)

1. **Wire `auditor` runner in `build/runtime/hub_role_runner`.** New
   `verify/runtime/auditor_runner.py` with Cite-or-Refuse envelope.
   Removes the `not_implemented_in_runner` branch. Unlocks stage 6.
   *Effort: M.*
2. **Append decision-ledger entries on Conductor + Auditor + QA
   promotions.** New `shared/audit/decision_ledger_io.py`; call site
   in `plan/runtime/hub_role_runner._run_text_role` (conductor) and
   new auditor_runner. Required for #12a freshness/replay gates.
   *Effort: M.*
3. **Wire `record_instinct` into
   `shared/runtime/role_runtime.complete_directive`.** One call site,
   all 8 roles inherit. Connects B3 to the loop. *Effort: S.*
4. **Add watcher rules for
   `verify_approved → acceptance → released → operate`.** Extend
   `shared/runtime/phase_watcher._WATCH_RULES` (3 new rules).
   Without this the loop dead-ends at QA. *Effort: S.*
5. **Implement `devops/runtime/operate_runner.py` for the 8 control
   planes (#11).** Even a minimal heartbeat-and-status implementation
   closes the loop end-to-end. *Effort: L (but only need 1 plane
   fully wired and 7 stubbed for the slate).*
6. **Add `product_runner.py` and register `product` in
   `plan/runtime/hub_role_runner._ROLE_CONFIG`.** Replaces the
   template-only PRD path; lets the product charter actually drive
   intake → PRD. *Effort: M.*
7. **Enforce workspace hygiene gate in Conductor.** Smallest of the
   seven, gives #34 teeth and prevents stale directives from rotting
   through the loop. *Effort: S.*

After these seven, the loop runs end-to-end on a single greenfield
`feature` project with all-AI dispatch, decisions audited via #12a,
and instincts/lessons captured per #27.

---

## 5. What to skip / defer

- **Federation hub-to-hub propagation of operate-class events (#10).**
  Cross-org learning is gated on Tier 1b lesson promotion working
  first.
- **Bounded retrieval (`dispatch_build_bounded`).** Module exists;
  opt-in flag is fine for now. Not on the critical path until token
  cost becomes a binding constraint.
- **Charter eval pre-commit hook (#7a enforcement).** Defer to a
  CI-only check; running pass@k on every commit is too slow for the
  dogfood loop.
- **Voice / mobile scaffolds (#28/#29).** Scaffold-only per V3
  decisions; no operating-loop dependency.
- **DR layers 7 (cross-region replication) and 10 (vendor update
  infra DR).** Per #32 these are enterprise-tier; not required to
  validate the single-project end-to-end loop.
- **Cross-LLM consensus as learning signal (#27 item 11).** Useful,
  but a refinement on Smart Spine after the lesson/instinct loop is
  closed.
- **Master-role aggregation (#27 item 5).** Useful once two projects
  are running concurrently; one-project loop closure does not require
  it.

---

### Critical files for implementation

- `build/runtime/hub_role_runner.py`
- `plan/runtime/hub_role_runner.py`
- `verify/runtime/hub_verify_runner.py`
- `shared/runtime/phase_watcher.py`
- `shared/runtime/role_runtime.py`
- `shared/audit/decision_ledger.py`

---

*Filed by D2 in the parallel batch 2026-05-29. No code written; this
is a gap analysis. Implementation slate above is dependency-ordered
and ready to be split into 7 follow-up PRs.*

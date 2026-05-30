# Operating loop validation — 2026-05-30

> **Live run after slate #1-#7 landed.** Hub up, API keys live,
> smoke 99 PASS / 0 FAIL. Project
> `a81f7f2c-de77-480b-ac7d-76da78885d06` ("loop-validation-2026-05-30",
> id 48) is the validation artifact — left in the DB for next-session
> inspection.

## Validation matrix

| Layer | What | Result |
|---|---|---|
| Hub container | `spine-hub`, postgres, vault, keycloak | UP, healthy |
| API keys | ANTHROPIC + OPENAI | both set |
| Smoke | `bash tools/smoke-test.sh` | 99 PASS / 0 FAIL / 1 WARN / 3 INFO |
| B5 status CLI | `spine status --markdown` | 24 projects, chain integrity ok |
| Project create | `POST /api/v2/projects` | project 48 created cleanly |
| Slate #6 product role | LLM-driven intake chat | Live LLM responses, charter discipline visible (role refuses to draft PRD without substance per SVPG prompt) |
| Planner dispatch | recovery_dispatch → `_run_text_role` | roadmap_md persisted in ~40s |
| Slate #1 auditor refusal | `run_auditor(no evidence)` | `status=refusal`, code=`cite_or_refuse_refused`, reason=`no_evidence_pointers` |
| Slate #1 auditor verdict | `run_auditor(with evidence)` | `status=ok`, 2 citations of types {file_line, kg_node} |
| Slate #2 ledger writes | live filesystem | 2 new JSONL files appeared on disk |
| B1 chain integrity | `verify_chain()` on new entries | `chain_ok=True` for both runs |
| Promotion gate logic | both entries' `PromotionGate.evaluate()` | refusal → denied(freshness_stale, replay_failed); verdict → allowed (no reasons) |
| Slate #5 operate runner | `run_operate(3 planes)` | envelope ok, operate_started_at populated |
| B5 reads new entries | `spine status --markdown` post-run | both audit runs surface with verdict + chain status |

## Findings

### F1 — Intake transcript persistence requires client to echo prior turns
The `POST /api/v2/projects/{id}/intake/chat` endpoint persists what the
caller supplies. The SPA echoes back the prior transcript on every
turn; raw curl tests that omit the echo end up with only the latest
2 turns in DB. This is **by design** (the route honours its
`IntakeChatRequest.transcript` contract) but is a sharp edge for
operators using curl directly. Surface in `docs/HUB_OPERATIONS_GUIDE.md`.

### F2 — Control plane scaffolds return `status='unknown'`
`devops/planes/*` `status()` methods are stubs that return
`PlaneStatus(status='unknown')`. The operate runner correctly
translates this — but in production it means the operate report says
"0/8 planes active" until the planes' real backends are wired. Not a
bug in slate #5; flag for the existing `devops/planes/` backlog.

### F3 — Planner currently has no ledger write
Slate #2 wired Conductor + QA. Planner was deliberately excluded per
D2's analysis (planner's output is a roadmap, not a promotion gate).
If we later want planner regressions to surface in the decision
ledger, add it to the `if role in ("conductor", "qa")` branch in
`plan/runtime/hub_role_runner._run_text_role`.

## Conclusion

The operating loop is **wired end-to-end on a live Hub running
real LLM dispatches**. Every slate item produces the expected
on-disk effect (ledger entries, audit chain integrity, envelope
shape, charter discipline). Findings are operational, not
architectural.

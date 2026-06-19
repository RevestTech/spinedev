# TRD Data coverage — Spine

**Baseline date:** 2026-06-19  
**Schema source:** `db/flyway/sql/V1–V37`, `db/README.md`

## Summary

| Category | Spec entities | LIVE-USED | DRIFT | MISSING | Coverage % | Δ |
|----------|---------------|-----------|-------|---------|------------|---|
| Lifecycle (golden path) | 4 | 4 | 0 | 0 | **100%** | — |
| Platform schemas | 12 | 11 | 0 | 1 | 92% | — |
| **Golden path total** | 4 | 4 | 0 | 0 | **100%** | — |

**G5 threshold:** ≥ 90% LIVE-USED — **PASS**

## Golden-path entity matrix

| Entity / table | Migration | Used in code | Test | Status | Notes |
|----------------|-----------|--------------|------|--------|-------|
| `spine_lifecycle.project` | V14+ | `projects.py`, orchestrator | smoke, unit | LIVE-USED | Phase + metadata |
| `spine_lifecycle.route_history` | V14+ | `_role_dispatch_bridge.py` | golden path e2e | LIVE-USED | Watcher dedup |
| `spine_lifecycle.decision` | V36 | `decisions.py` | unit | LIVE-USED | Decision queue |
| `spine_audit.ledger` | V15+ | `shared/audit/` | smoke | LIVE-USED | Hash chain |

## Platform entities (Sprint 0)

| Entity / table | Migration | Status | Notes |
|----------------|-----------|--------|-------|
| `spine_kg.kg_node` / `kg_edge` | V2 | LIVE-USED | `kg_role_context.py` |
| `spine_federation.hub` | V23 | STUB | Registry; UX deferred |
| `spine_license.*` | V22 | LIVE-USED | Verifier in smoke |
| `spine_learning.*` | V29 | STUB | Smart Spine partial |
| `spine_evidence.*` | V25 | STUB | Collectors scaffold |

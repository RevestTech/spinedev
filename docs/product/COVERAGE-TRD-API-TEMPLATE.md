# TRD API coverage — Spine

**Baseline date:** YYYY-MM-DD  
**Spec source:** [TRD-API.md](./TRD-API.md) (or OpenAPI path)

## Summary

| Category | Spec count | SHIPPED-AND-USED | STUB | MISSING | Coverage % | Δ |
|----------|------------|------------------|------|---------|------------|---|
| Public | | | | | | |
| Authenticated | | | | | | |

**G5 threshold:** ≥ 90% SHIPPED-AND-USED

## Endpoint matrix

| Endpoint | Method | Spec status | Implementation | Used by UI | Test | Notes |
|----------|--------|-------------|----------------|------------|------|-------|
| `/api/v1/example` | GET | Required | SHIPPED / STUB / MISSING | yes/no | test file | |

## Status values

- **SHIPPED-AND-USED** — endpoint live and called from product UI or job
- **SHIPPED-UNUSED** — exists but no consumer (flag for review)
- **STUB** — returns placeholder; visible defer
- **MISSING** — not implemented

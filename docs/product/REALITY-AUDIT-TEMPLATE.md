# Reality audit — Spine

**Audit date:** YYYY-MM-DD  
**Auditor:**  
**Prior audit:** [REALITY-AUDIT-PRIOR-DATE.md](./REALITY-AUDIT-PRIOR-DATE.md) (or N/A)

## Method

Re-walk every **user-visible feature**, not every file. Rate each feature area independently.

## Rating definitions

| Rating | Meaning |
|--------|---------|
| **LIVE** | Real API + persistence, verified end-to-end |
| **FALLBACK** | API call with mock/degraded fallback, documented |
| **STUB** | Partial implementation, **visible** defer badge + ticket in UI |
| **FAKE** | Local-only / no-op — **must be zero at G5** or reclassified |
| **BROKEN** | Contract mismatch — **must be zero at G5** |

**Honesty bar:** Deferred work uses a visible badge + ticket reference (`WIRE-S*-###`). Silent no-ops are not acceptable.

## Summary

| Section / area | LIVE | FALLBACK | STUB | FAKE | BROKEN | Δ vs prior |
|----------------|------|----------|------|------|--------|------------|
| {{AREA_1}} | | | | | | |
| **Total** | | | | | | |

## Feature detail

| Feature | Route / entry | Rating | Evidence | Ticket if deferred |
|---------|---------------|--------|----------|-------------------|
| | | | | |

## Verdict

- [ ] FAKE + BROKEN = 0 OR all remaining have badge + ticket
- [ ] Independent re-audit completed (if this is a self-audit)
- [ ] Linked from [G5-release-ready.md](../../todo/gates/G5-release-ready.md)

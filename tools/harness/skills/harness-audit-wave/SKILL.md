---
name: harness-audit-wave
description: >-
  Harness Lite Phase 1 — read-only parallel audit fan-out. Produces structured
  drift tables (not prose) capped at 400 words per agent. ADR-008 audit before fix.
---

# Harness Audit Wave (Phase 1)

**READ-ONLY.** Never edit files in this wave. Output structured findings JSON.

## When to invoke

- Harness orchestrator enters `wave: audit`
- `sprint-close` or `release-gate` mode tick
- User requests drift audit without fixes

## Dimensions (parallel — one subagent each)

Dispatch **only gates not already green** in `state.json` (unless sprint-close):

| Gate key | Audit focus |
|----------|-------------|
| `tests` | type-check, test pass rate, build, skips |
| `requirements` | PRD/TRD/sprint claims vs delivered artifacts |
| `drift` | code ↔ spec ↔ DB three-way checks |
| `docs` | dead links, stale numbers, phantom paths |
| `security` | OWASP, secrets grep, auth parity |
| `compliance` | WCAG, commits, audit log writes |

## Output contract (mandatory)

Each subagent returns a **drift table**, not prose:

```
| Severity | File:line | Claim | Actual | Recommendation |
```

Compressed caveman form also accepted:

```
path:line: 🔴 critical: claim vs actual. recommendation.
```

**Cap: 400 words per agent report.**

## Subagent selection

- **Default:** `cavecrew-investigator` — locate/drift only
- **Avoid:** passing whole repo to builder agents
- **Parallel:** 2–3 investigators in one message when angles differ

## Persist findings

Write JSON to `.spine/harness/findings/<gate>-<ISO8601>.json`.

**CLI (deterministic scanners, no LLM):**

```bash
spine harness audit --project .
spine harness audit --gates docs,drift --markdown
```

Implementation: `tools/harness/lib/audit_wave.py`

Agent-driven audits still use this skill for subagent dispatch.

## Handoff to fix-wave

When all targeted gates have findings files:

1. Set `state.json` wave → `fix`
2. Invoke `harness-fix-wave` with findings paths
3. **Do not** mix audit and fix in the same wave (ADR-008 rule 1)

## Prompt template (≤400 words)

```
Audit gate: <gate>. READ-ONLY.
Scope: <files or subsystem>.
Compare: code ↔ spec ↔ DB where applicable.
Output: drift table only. Max 400 words.
Use cavecrew-investigator posture — cite path:line or refuse.
Sweep *conflicted* sync artifacts if present.
```

## References

- `docs/adr/ADR-008-sprint-cleanup-methodology.md` Phase 1
- `docs/QA-READINESS-STANDARD.md` — 6-gate definitions

# DEPRECATED — use `shared/charters/`

This directory is the v1/v2 home for Spine role prompts. It is **deprecated**
as of Spine v3 (design decision #7, ratified 2026-05-17) and will be removed
once every v2 prompt has been rebuilt as an industry-anchored charter under
`shared/charters/`.

The presence of the sibling `.deprecated` marker file in this directory is
machine-readable: future tooling (loader fallback, bundle build, CI gates)
greps for `lib/role-prompts/.deprecated` and emits a deprecation warning
whenever a v2 prompt is loaded instead of a v3 charter.

## What replaced this directory

`shared/charters/` (see `shared/charters/README.md`) holds every v3 role
charter. v3 charters cite a named industry standard (Scrum Guide, PMBOK,
ITIL, NIST, SRE handbook, OWASP, Diataxis, etc.) and conform to the
nine-section structure documented in the charter README.

## Migration status (per file)

The runtime loader prefers `shared/charters/<role>.md` when both exist;
when only the v2 prompt exists, it falls back with a deprecation warning.

| v2 prompt (this directory) | v3 home | Status |
|---|---|---|
| `architect.md` | `shared/charters/architect.md` | REBUILD pending (Wave 3) |
| `auditor.md` | `shared/charters/auditor.md` | REBUILD pending (Wave 3) — strict Cite-or-Refuse per #12 |
| `conductor.md` | `shared/charters/conductor.md` | REBUILD pending (Wave 3) |
| `datawright.md` | `shared/charters/datawright.md` | REBUILD pending (Wave 3) |
| `engineer.md` | `shared/charters/engineer.md` | REBUILD pending (Wave 3) — tier-bifurcation per #13 |
| `memory.md` | (likely DELETE — becomes a Hub feature per #3, #27) | TRIAGE pending (Wave 3) |
| `operator.md` | `shared/charters/operator.md` | REBUILD pending (Wave 3) — distinct from `devops` per #11 |
| `planner.md` | `shared/charters/planner.md` | REBUILD pending (Wave 3) |
| `product.md` | `shared/charters/product.md` | REBUILD pending (Wave 3) |
| `qa.md` | `shared/charters/qa.md` | REBUILD pending (Wave 3) |
| `researcher.md` | `shared/charters/researcher.md` | REBUILD pending (Wave 3) |
| `seer.md` | (likely DELETE — becomes a Hub feature per #3, #27) | TRIAGE pending (Wave 3) |
| `ux.md` | `shared/charters/ux.md` | REBUILD pending (Wave 3) |

## What v3 added (no v2 equivalent)

Six brand-new charters landed in Wave 2 directly under `shared/charters/`
with no v2 origin:

| New charter | Anchor | Driving decisions |
|---|---|---|
| `devops.md` | SRE handbook + DORA | #11 (Operate / 6th corner), #19 (`infra`) |
| `customer_support.md` | ITIL 4 Service Request | #19 (`support`) |
| `compliance_officer.md` | NIST CSF 2.0 + SOC 2 + ISO 27001 | #19 (`compliance`), #24 |
| `security_engineer.md` | OWASP ASVS + NIST SSDF | #19 (`incident`), #12 |
| `tech_writer.md` | Google Devdocs Style + Diataxis | #19 cross-cutting |
| `release_manager.md` | PMBOK + ITIL Release | #5, #19 (release flow), #16 |

## Why this directory still exists

The Wave 2 squad deliberately left the v2 prompt files in place rather than
deleting them in the same commit that introduced `shared/charters/`. This
preserves runtime continuity (the existing role daemons keep working) while
the per-role REBUILDs land incrementally in Wave 3 housekeeping. Each REBUILD
commit deletes the corresponding v2 prompt as it lands the v3 charter.

Once every v2 prompt has been replaced, this entire directory is removed and
the runtime loader's deprecation-fallback path is removed with it.

## Do NOT edit prompts in this directory

Edits to v2 prompts here are wasted work — they are overwritten by the Wave 3
REBUILD commits. If a v2 prompt has an urgent fix, file a `bug` work-item
against the v3 charter target (or land the v3 charter directly).

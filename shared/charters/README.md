# shared/charters/ — industry-anchored role charters

This directory is the v3 home for every Spine role charter. It replaces the
v1/v2 `lib/role-prompts/` directory, which is now deprecated (see
`lib/role-prompts/README.md` and `lib/role-prompts/.deprecated`).

Charters are the AUTHORITATIVE source of role obligations for the Spine
runtime. Every role daemon, MCP tool wrapper, Hub UI surface, and audit
event references the charter currently loaded for that role.

---

## Why charters (not prompts)

Per `docs/V3_DESIGN_DECISIONS.md` #7, every role in Spine is anchored in a
published industry standard or body of practice (Scrum Guide, PMBOK, ITIL,
SRE handbook, NIST CSF, OWASP ASVS, Diataxis, etc.). The v2 role-prompts
were excellent empirical playbooks but lacked named provenance. v3 charters
treat industry-standard provenance as a first-class contract:

- agents grep `## Charter anchor` lines to verify the charter cites a real,
  named, version-pinned standard
- auditors can challenge a role's behavior against the cited standard,
  rather than against bespoke prose
- customers can swap or extend a charter via their bundle while keeping the
  industry anchor intact (or replacing it with another named standard)

A charter is not a prompt. It is a CONTRACT describing what the role is
obligated to do, what it is forbidden from doing, and what it must emit.
The runtime is responsible for translating the contract into a model
prompt; the charter never embeds model-specific or vendor-specific text.

---

## Mandatory section structure

Every charter in this directory MUST contain the following sections, in
this order. Validation tooling enforces these section headers via
`grep -c` checks; missing sections fail the bundle build.

1. `# Charter — <role>` — H1 title only, no other content
2. `## Identity` — one paragraph stating role purpose, scope, and the kind
   of work-items (per design decision #19) this role acts on
3. `## Charter anchor` — at least one named citation
   (book / specification / RFC / standard) with version or edition;
   no URLs required, but the anchor MUST be recognizable to a
   practitioner. Multiple anchors are allowed when no single source
   covers the role.
4. `## You may` — bulleted list of explicitly permitted actions, surfaces,
   and authorities. Each bullet is a verbable obligation, not a wish.
5. `## You may NOT` — bulleted list of explicit prohibitions. Use hard,
   testable language ("never", "must not", "refuse"). The phrase
   "use judgment" is forbidden in this section.
6. `## Hard rules` — numbered list of behavioral rules. Each rule MUST
   cite the design-decision number(s) it derives from in parentheses,
   e.g. `(per #11, #12)`.
7. `## Output shape` — schema-like description of every emission this role
   produces. Each emission lists a name, type, and meaning, suitable for
   Pydantic model generation in a later wave.
8. `## Trigger contracts` — what events / work-items / audit signals cause
   this role to act, and what downstream consumers expect.
9. `## Failure modes` — 3 to 5 named failure modes the role is expected
   to recognize in itself, with the recovery action for each.

Charters MAY include additional sections (e.g. `## Control planes` for
`devops.md`) but the nine above are mandatory.

---

## Industry-anchor convention

Each `## Charter anchor` line names the standard, its publisher, and a
version or edition. Examples:

- "Google SRE handbook (Beyer et al., O'Reilly, 1st ed. 2016) + DORA
  State of DevOps Report (latest annual)"
- "ITIL 4 Foundation (AXELOS, 2019 edition) — Service Request Management
  practice"
- "NIST Cybersecurity Framework 2.0 (2024) + SOC 2 Trust Services
  Criteria (AICPA, 2017 revised 2022) + ISO/IEC 27001:2022"
- "OWASP Application Security Verification Standard 4.0.3 + NIST Secure
  Software Development Framework (SP 800-218 v1.1) + SANS CWE Top 25
  (latest annual)"
- "Google Developer Documentation Style Guide (current) + Diataxis
  framework (Procida, current)"
- "PMBOK Guide 7th Edition (PMI, 2021) — Release Management +
  ITIL 4 Release Management practice"

When an anchor is replaced (e.g. customer wants OpenAPI Spec instead of
Diataxis for tech writing), the bundle override declares the substitute
and the runtime loads the bundle-overridden charter — never edit the
canonical anchor in place.

---

## What this directory will hold at v1.0

Wave 2 (this commit): six NEW charters that have no v2 equivalent.

| File | Role |
|---|---|
| `devops.md` | DevOps engineer (customer-facing, 8 control planes per #11) |
| `customer_support.md` | Customer support / service-desk |
| `compliance_officer.md` | Compliance / GRC officer |
| `security_engineer.md` | Application + product security engineer |
| `tech_writer.md` | Technical writer / docs owner |
| `release_manager.md` | Release manager |

Wave 3 (housekeeping): 11 of the 13 existing role-prompts under
`lib/role-prompts/` (architect, conductor, datawright, engineer, operator,
planner, product, qa, ux, auditor, researcher) are REBUILT in this
directory per #7, one charter at a time. Until rewritten, the v2 prompt
files remain in `lib/role-prompts/` with the deprecation marker present.
The runtime loader prefers `shared/charters/<role>.md` when both exist;
if only the v2 prompt exists, it falls back with a deprecation warning.

This incremental approach lets us land Wave 2 work without blocking on
rewriting the entire v2 prompt set.

### Wave 3 DELETE recommendations (per Squad 1 + Squad D)

Two v2 role prompts do NOT become v3 charters and have no target file in
`shared/charters/`:

| v2 prompt | Recommendation | Rationale |
|---|---|---|
| `lib/role-prompts/memory.md` | DELETE — becomes a Hub feature, not a role | Per #3 (Hub-as-product) + #27 (Smart Spine 3-tier learning), memory is an architectural primitive of the Hub (memory writer hooks at 7 trigger points, memory retrieval at every role action, lesson promotion ladder), not a role's responsibility. Every role appends lessons to its own memory; the Hub aggregates and distributes via the federation tree. There is no "memory role" because memory is everyone's contract. |
| `lib/role-prompts/seer.md` | DELETE — becomes a Hub feature, not a role | Per #3 + #27, forecasting / observability / drift-detection are Hub-level surfaces (the dashboard observability panes, the calibration outcomes loop, the cross-LLM-disagreement-as-signal pipeline). These are platform features the Hub runs across all roles, not a single role's scope. The "seer" framing collapsed multiple architectural primitives into one nominal role; Spine v3 distributes them across the Hub's observability surface, `compliance_officer`'s evidence pipeline, and `auditor`'s cite-or-refuse loop. |

Wave 6 will `git rm` the two v2 files; Wave 3 leaves them in place under
the deprecation marker so the runtime loader's fallback continues to work
through the transition.

---

## Out of scope for charters

Charters describe ROLE OBLIGATIONS only. They do NOT contain:

- code snippets, CLI invocations, or shell examples
- embedded JSON / YAML / TOML configuration (those live in bundles)
- model-specific prompt fragments (those live in `shared/runtime/`)
- tool schemas (those live in `shared/mcp/tools/`)
- KG queries or SQL (those live in tool wrappers)

A charter that smells like a runbook needs to be split: the obligation
stays here, the executable runbook moves to the appropriate
operational directory.

---

## Validation

Every charter committed to this directory MUST pass:

```
grep -c "^## Charter anchor"    shared/charters/<file>.md   # == 1
grep -c "^## Failure modes"     shared/charters/<file>.md   # == 1
grep -c "^## You may NOT"       shared/charters/<file>.md   # == 1
grep -c "^## Hard rules"        shared/charters/<file>.md   # == 1
grep -c "^## Output shape"      shared/charters/<file>.md   # == 1
grep -c "^## Trigger contracts" shared/charters/<file>.md   # == 1
```

Wave 4 ships a real validator (`shared/standards/charter_lint.py`).
Until then, the grep counts are the contract.

# Spine auto-triggering skills (`shared/skills/`)

Implements **STORY-4.1.1** (skill auto-trigger mechanism), **STORY-4.1.2**
(verification-before-completion), **STORY-4.1.4** (brainstorming).
Pattern absorbed from `obra/superpowers` — see
`docs/research/COMPETITIVE_LANDSCAPE.md §3`.

## Why auto-triggering skills exist

A role's base prompt (e.g. `lib/role-prompts/engineer.md`) is the part the
agent *always* sees. Skills are the part it sees **only when the moment is
right** — e.g. `verification-before-completion` only matters when the
agent is about to seal a `BuildArtifact`; jamming it into the base prompt
on every invocation burns tokens and dilutes attention. Skills auto-fire
based on `(role, phase, directive content, artifact-about-to-be-emitted)`
and append themselves to the prompt only when they apply.

## File format

Each skill lives in `shared/skills/skills/<slug>/`:

```
shared/skills/skills/verification-before-completion/
  SKILL.yaml   ← trigger config + metadata (source of truth)
  SKILL.md     ← the prompt body injected when the skill fires
```

### `SKILL.yaml`
```yaml
slug: verification-before-completion        # required; matches dir name
name: "Verification before completion"
version: 1
trigger:
  applies_to_roles: [engineer, datawright]
  applies_to_phases: [build_in_progress]
  applies_to_directive_keywords: [implement, build, fix, refactor]
  applies_when:                              # AND across list
    - artifact_about_to_be_emitted: BuildArtifact
  applies_when_or:                           # OR across list (optional)
    - directive_contains: "vague"
priority: 200                                # higher fires first
max_token_overhead: 900                      # injection budget per skill
incompatible_with: []                        # other slugs that conflict
inherits_from: []                            # reserved for skill composition
metadata: { author: spine, source_pattern: obra/superpowers }
```

### `SKILL.md`
Plain markdown — the literal text appended to the role prompt when the
skill fires. Keep it focused on *what to do* (not *why it exists*); the
*why* belongs in `metadata.why` of the YAML so registry tooling can
surface it.

## Trigger evaluation algorithm

Given a `TriggerContext(role, phase, directive_text, artifact_type,
project_id, prior_skills_fired)`:

1. **Pre-filter** by `applies_to_roles` / `applies_to_phases` /
   `applies_to_directive_keywords`. Empty list = no constraint.
   Keywords are tried as regex first, then substring fallback
   (case-insensitive).
2. **Rule-match.** `applies_when` clauses are AND-across-list (every
   clause must match). `applies_when_or` clauses are OR-across-list (any
   one matching is enough). If **either** list passes, the skill matches —
   they are independent paths, not a conjunction. Both empty = match
   (relying purely on the pre-filters).
3. **Conflict filter.** Drop any skill whose slug appears in the
   `incompatible_with` of an already-fired skill (or any skill in
   `prior_skills_fired`).
4. **Sort + cap.** Sort surviving skills by `priority` desc. Append in
   order until the **total** injection (sum of
   `min(max_token_overhead, len(prompt))`) exceeds the budget (default
   `2000` chars, override via `compute_triggered_skills(..., token_budget=)`).
5. **Inject.** `inject_skill_prompts(base, fired)` appends fired skill
   bodies after the base role prompt with HTML-comment markers:

   ```
   ## SKILLS ACTIVE FOR THIS DIRECTIVE

   <!-- SPINE-SKILL: verification-before-completion -->
   ...body of SKILL.md...
   <!-- /SPINE-SKILL: verification-before-completion -->
   ```

   Markers make injection idempotent and easy to strip in logs/replay.

## How to add a new skill (3-step recipe)

1. `mkdir shared/skills/skills/<your-slug>`.
2. Write `SKILL.yaml` (trigger + metadata) and `SKILL.md` (prompt body).
3. `python -m shared.skills.cli validate` — fixes slug collisions, broken
   `incompatible_with` refs, missing prompt files, bad token budgets.

Then sanity-check the trigger:

```bash
python -m shared.skills.cli test --role engineer --phase build_in_progress \
    --directive "implement the new auth flow" --artifact-type BuildArtifact
```

## Conflict resolution (`incompatible_with`)

If two skills give overlapping or contradictory instructions, declare the
loser in the winner's `incompatible_with`. Firing order respects
`priority`, so the higher-priority skill fires first and *its*
`incompatible_with` list blocks the others. Symmetric incompatibility
(A blocks B and B blocks A) collapses to whichever fires first — usually
the higher-priority one.

## Token budget management

Two knobs:
- Per-skill: `max_token_overhead` caps how much *this* skill is allowed
  to contribute.
- Global: `compute_triggered_skills(token_budget=N)` caps the **sum**
  across all fired skills (default `2000` chars).

The engine uses the actual prompt length, not a tokenizer — chars are a
good-enough proxy and stay zero-dependency. If you need real token
counting, override the call-site.

## How role daemons consume

At directive start the role daemon does:

```python
from shared.skills import (TriggerContext, discover_skills,
                           compute_triggered_skills, inject_skill_prompts)

registry = discover_skills()                       # one-time per process
ctx = TriggerContext(role="engineer",
                     phase="build_in_progress",
                     directive_text=directive,
                     artifact_type="BuildArtifact",
                     project_id=project_id)
fired = compute_triggered_skills(ctx, registry)
prompt = inject_skill_prompts(base_role_prompt, fired)
# ...invoke the LLM with `prompt`; log fired slugs for audit
```

Logging the fired slugs lets the auditor + cost ledger attribute
follow-on quality (or follow-on cost) back to the skill that fired.

## Starter skills shipped

| Slug | Roles | Fires when | Story |
|---|---|---|---|
| `verification-before-completion` | engineer, datawright | About to emit a `BuildArtifact` | STORY-4.1.2 |
| `brainstorming` | product | Directive is short/vague (intake or planning) | STORY-4.1.4 |

## Cross-references

- `STORY-4.1.1` — this mechanism (registry + engine + CLI).
- `STORY-4.1.2` — `verification-before-completion` skill body.
- `STORY-4.1.4` — `brainstorming` skill body.
- `STORY-4.1.3` / `STORY-4.1.5` / `STORY-4.1.6` — future skills
  (worktrees, subagent-driven-development, systematic-debugging).
- `obra/superpowers` (193k★, MIT) — pattern origin.
- `REQ-INIT-1 §1.5 FR-2` — brainstorming overlaps the front-door
  interrogation requirement (STORY-1.1.4); dedupe at execution time, not
  at config time.
- `REQ-INIT-7 FR-3` — `BuildArtifact` refuse-to-emit rule the
  verification skill backs.
- Role-prompt integration is a **follow-up story** — this module does
  not edit `lib/role-prompts/*.md` files. Wire-in lives in the role
  daemon.

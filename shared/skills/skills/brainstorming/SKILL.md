# Skill — brainstorming (before commit)

The directive you just received is **vague**. A short message ("build me an
app", "fix it", "make it better", "something like X") is the canonical
shape of a brief that *cannot* be satisfied without interrogation. Do not
race ahead. Do not write code. Do not propose architecture. **Stop and
brainstorm.**

## The 5-move dialogue protocol

Run these moves in order — they are the body of
`shared/charters/product.md` and the schema-of-record for an intake
conversation. Announce each move out loud ("Move 2 — what did I get
wrong?") so the user can track where you are.

### Move 1 — Naive cast (strawman)
Make the most charitable guess at what the user wants and produce a
six-bullet strawman: project type, intended users (1-3 named personas),
3-5 acceptance criteria in Given/When/Then form, out-of-scope (3+ items
you assume they don't want), and your stated assumptions ("I'm assuming
web not mobile; auth is email/password; single-tenant…"). Keep it short
— the point is to give them something concrete to attack, not a finished
plan.

### Move 2 — Provoke correction
Ask **one** question at a time. The prompts:
- "What's wrong about this?"
- "What did I miss?"
- "Where does this not fit your situation?"
If the user says "looks good," push back once — *"what would your worst
critic say is missing?"* — before accepting the strawman.

### Move 3 — Reframe and rebuild
When the user corrects you, do **not** patch the strawman. Throw it out
and rebuild from the corrected frame. A good-sounding plan built on a
wrong premise is the single worst failure mode of intake — patching
preserves the wrong premise. Restate the corrected frame in one
sentence, wait for confirmation, then re-do Move 1 from scratch. Loop
back to Move 2. Stop looping when the user accepts a strawman without
substantive correction (cosmetic edits are fine).

### Move 4 — Tier the outputs (MUST / SHOULD / COULD / WON'T)
Force a prioritization. Load the matching template from
`plan/templates/intake/<type>.yaml` and run its `tier_forcer: true`
questions. Ask one tier-question at a time; read back the bucket
assignment after each answer. Every item ends up in **exactly one**
bucket. If the user wavers ("kind of a MUST"), force a decision: *"If I
cut this, do you ship?"* — if yes, it's SHOULD or lower. WON'T items
become `out_of_scope` entries in the PRD; confirm explicitly: *"We're
saying no to X. Yes?"*

### Move 5 — Seal the artifact
Render a `PRDv1` that validates against `plan/artifacts/prd_v1.py`.
Required fields: `project_id`, `project_name`, `project_type`,
`problem_statement` (not empty / not TBD), `users_stakeholders` (≥1),
`goals.must` (≥1), `in_scope` / `out_of_scope` (≥1 each, no TBD lines),
`acceptance_criteria` (≥1 each with a non-empty `then`). Write it to the
path the orchestrator handed you and request sign-off through the
Engagement protocol.

## Refuse-to-advance rule

A PRD cannot be sealed (`metadata.status = approved`) while any required
field is `TBD`, empty, or a placeholder sentinel. The schema's
`_refuse_to_advance` model-validator enforces this — do not try to fool
it with whitespace or "TODO later." If the user says *"let's just decide
that later,"* your reply is:

> *"That field blocks PRD sign-off. We can defer it as an
> `open_question` with a recommended default, or we can decide it now.
> Which?"*

An `OpenQuestion` with a `recommendation` is a legal way to record a
deferred decision; an empty required field is not.

## Why this skill fires (and why it's separate from the base prompt)

The product role already knows the 5-move protocol — it's in the base
prompt. But the failure mode is real: under time pressure, with a short
directive, the role can shortcut to "here's a PRD draft based on what I
guessed" without actually running the protocol. This skill fires
*specifically* when the directive looks vague (short, or contains hedge
words like "kind of", "not sure", "build me"), making the move-by-move
walk the **first** thing the role does, not an option it might skip.

Pattern source: `obra/superpowers` — `brainstorming` skill. Spine's
twist: the moves are typed (5 named moves) and the artifact is
schema-validated, so the dialogue cannot end with a vague PRD.

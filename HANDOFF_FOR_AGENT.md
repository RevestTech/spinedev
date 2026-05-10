# Handoff for the SpineDevelopment v1.3.4 / v1.4 agent

> **Public guidance:** Prefer [`docs/SPINE_PRACTICES.md`](docs/SPINE_PRACTICES.md), [`docs/IMPROVEMENT_CHECKLIST.md`](docs/IMPROVEMENT_CHECKLIST.md), and [`INSTALL.md`](INSTALL.md) for how to use and evolve the template. The sections below are an internal architect handoff and may name specific downstream repos.

Read this first. It's a self-contained context dump from the architect (Claude session that did the Kontract dogfooding). You should not need to interview Khash to start.

## What you're inheriting

You are taking over the **SpineDevelopment** package — a stencil-style scaffolding generator that bootstraps an "agent team" file-bus orchestration system into target projects. Lives at `~/Projects/Apps/SpineDevelopment/`. Currently at **v1.3.3** (CHANGELOG entry dated 2026-05-08 evening).

It serves as the meta-platform for these sibling projects:
`Adajoon, collegeOG, FlightPrep, Kontract, Mobile, plane, StableBank` (under `~/Projects/Apps/`).

Kontract is the primary dogfooding project — most lessons in the spine come from running the spine inside Kontract.

## How the spine works (tier model)

It's a stencil, not a library. `bash install.sh <target>` copies files into the target project. After install, the project owns its copies.

| Tier | What | Update characteristic |
|---|---|---|
| 1 | `lib/*.sh`, `lib/dashboard.html` | Behavioral changes — risky to update because projects may have local mods. |
| 2 | `templates/teams/*` | Scaffolding files; rarely re-pulled after first install. |
| 3 | `recipes/*.md`, `lib/playbook-defaults/*.md`, `lib/role-prompts/*.md` | Knowledge content; cheap and safe to evolve. **Most of the value flows through this tier.** |

Strategic implication: most of your value-add will be Tier 3 content. Each new recipe is purely additive — doesn't break installed projects, picks up by re-running `install.sh` (or future `--pull-knowledge-only` flag).

## What's currently in the spine

```
SpineDevelopment/
├── install.sh                # the entry point
├── README.md, INSTALL.md, PROTOCOL.md, REQUIREMENTS.md, CHANGELOG.md
├── lib/
│   ├── team-agent-daemon.sh  # the core file-bus daemon (per-role)
│   ├── team.sh               # up/down/status for the whole team
│   ├── team-clean.sh
│   ├── watchdog.sh           # auto-restart dead managers (added v1.3)
│   ├── executor.sh           # wraps cursor-agent invocations
│   ├── seer-tick.sh          # the 'seer' role's heartbeat
│   ├── preflight.sh
│   ├── notify.sh
│   ├── file-lock.sh
│   ├── dashboard.html        # 100-line minimal dashboard (NEEDS UPGRADE — see below)
│   ├── playbook-defaults/
│   │   ├── engineer.md
│   │   ├── operator.md       # has the "25-min timeout trap" v1.3.3 lesson
│   │   └── datawright.md     # has Ollama / fine-tune / batch lessons
│   └── role-prompts/
│       ├── auditor.md, datawright.md, engineer.md, memory.md,
│       └── operator.md, planner.md, researcher.md, seer.md
├── templates/
│   └── teams/                # currently empty / minimal
├── recipes/                  # 10 recipes
│   ├── batch-process-data.md, dependency-bump.md,
│   ├── host-side-llm-pipeline.md (added v1.3.2),
│   ├── investigate-bug.md, performance-investigation.md,
│   ├── postmortem.md, refactor-plan.md, safe-db-script.md,
│   ├── security-audit.md, ship-feature.md
└── docs/
```

## What the file-bus protocol looks like (so you don't have to reverse-engineer)

For each role (engineer, datawright, etc.), the daemon polls `teams/<role>/directive.md` every 8 seconds. The contract:

- **`# Directive — <task>`** as the first line means: pick this up, work on it.
- **`# Plan — <task>`** means: manager has decomposed into workers; workers are running.
- **`# Report — <task>`** means: done, idle.

For multi-worker decomposition, the manager writes per-worker directives at:
```
teams/<role>/workers/01-directive.md   ← FLAT FILE (not a subdirectory)
teams/<role>/workers/02-directive.md
...
teams/<role>/workers/10-directive.md
```

Worker files use the same `# Worker Directive` / `# Worker Report` first-line vocabulary.

The daemon writes per-slot logs to `teams/<role>/log/01-daemon.log`, `01-agent.log`, etc.

A subtle gotcha worth knowing about: in Kontract's dashboard backend, the path was wrongly `workers/<slot>/directive.md` (subdirectory pattern) instead of `workers/<slot>-directive.md` (flat file). The spine's daemon is correct; the bug was downstream. If you build dashboard tooling, mirror the daemon's flat-file pattern.

## Pending v1.3.4 / v1.4 work (the punch list)

These are the lessons from the last 48 hours of Kontract dogfooding that aren't in the spine yet. Khash wants them captured so future projects start with this wisdom baked in.

### TIER 3 (additive, low-risk — target v1.3.4)

**1. New recipe: `recipes/horizontal-platform-with-verticals.md`**

The pattern from Kontract ADR-018: when building a platform that serves multiple industries/customers, split the engine into:
- A **core layer** (vertical-neutral, trained on cross-vertical data, serves all customers)
- **Per-vertical refiners** (industry-specific, trained on that vertical's data, layered on top)

In Kontract's case: a structural classifier (8 universal classes: agreement, amendment, notice, letter, schedule_or_exhibit, form, memo, unknown) is the core; a retirement-plans refiner (5 vertical-specific document types) is layered on top. New verticals (signing-notary, real-estate, healthcare, etc.) ship their own refiner without retraining the core.

Anti-pattern this avoids: training one big classifier with a label space that mixes structural + vertical types. Looks fine for one customer, becomes unmaintainable at customer #2.

Reference: `~/Projects/Apps/Kontract/.planning/orchestration/DECISIONS.md` ADR-018.

**2. New recipe: `recipes/ml-artifact-naming.md`**

The naming convention from Kontract ADR-019:
```
{platform}-{function}-{scope}-v{semver}
```
Where:
- `platform` = the project brand (`kontract`, `adajoon`, `bioshign`, etc.)
- `function` = the kind of inference (`classify`, `extract`, `embed`, `sigdetect`, `fieldplace`, `visualdiff`, `semdiff`)
- `scope` = `core` for vertical-neutral models OR a vertical slug (`rp` = retirement-plans, `signing` = signing-notary, etc.)
- `semver` = MAJOR.MINOR (no patch). MAJOR bumps on label-space or architecture change. MINOR bumps on retrain with same setup.

Examples: `kontract-classify-core-v1.0`, `kontract-classify-rp-v1.0`, `kontract-extract-core-v1.0`.

Drift-prevention rules: closed function/scope enums; conversation can use casual names ("the classifier"), but code/logs/registry MUST use the canonical identifier; old snapshots stay loadable for forensic comparison.

Reference: `~/Projects/Apps/Kontract/.planning/orchestration/DECISIONS.md` ADR-019.

**3. New recipe: `recipes/autonomous-overnight-progress.md`**

The pattern from Kontract's overnight Stage 1 training: pre-stage the next directive(s) in `.planning/orchestration/queue/` while the current wave runs, then schedule Claude `scheduled-tasks` MCP checkpoints (e.g., +30min, +60min, +90min) that:
1. Read each team's `directive.md` to determine state
2. Check that dependency artifacts exist on disk
3. If team is idle (their directive starts with `# Report`), copy the next queued directive into place
4. Self-disable when all training has completed

Idempotent — re-running is safe (idle-team check makes it a no-op if work is already in flight). This lets the architect step away (sleep, dinner, whatever) and the platform keeps progressing.

Reference: `~/Projects/Apps/Kontract/.planning/OVERNIGHT-STATUS-2026-05-10.md` for the actual checkpoint prompts used.

**4. Datawright playbook additions (`lib/playbook-defaults/datawright.md`)**

Three new lessons captured from today:

**a. Macro-F1 lies when classes have zero validation support.**
If your label space has 8 classes but val data only covers 4 of them, sklearn's macro-F1 averages over all 8 — counting the 4 absent ones as F1=0. Your "weighted F1" can read 0.94 while macro reads 0.41 for the SAME model. Fix: ensure every class in the label space has non-zero val/test support, OR explicitly compute macro over populated classes only and document the choice.

**b. Multi-source training corpora need a unified text contract.**
When you assemble training data from N sources (FC archive + CUAD + EDGAR + synthetic in our case), DEFINE THE TEXT FIELD AT INGESTION TIME. Don't let some rows have `head_text + tail_text`, others have `text`, others rely on DB hydration of a `doc_id`. A loader that prefers `text` and silently falls back to DB lookup will skip every non-DB row. Symptom: training script reports "loaded 493 rows" instead of expected 1,400, and 4 of 8 classes have zero training support.

Pattern that works: at corpus assembly time, materialize a `text` field on every row using the source-appropriate path (file body for filesystem rows, head+tail concat for pre-truncated rows, DB join for DB-resident rows). Future loaders just read `text`. If a row has no usable text, RAISE — never silently drop.

**c. Don't train a label space wider than your data covers.**
If you decide your classifier should distinguish 8 classes but you only have data for 4, you don't have an 8-class classifier — you have a 4-class classifier wearing an 8-class label coat. The model can technically output 8 logits, but it has never seen the other 4 classes during training, so those heads are dead weights. Decide between: (a) restrict the label space to what you have data for, (b) source the missing classes (CUAD, EDGAR, synthesis), (c) accept the gap and document it. ADR-001 of the project should note which path was chosen and why.

**5. New template: `templates/orchestration/DECISIONS.md`**

Scaffold an empty ADR log so new projects start with the convention. Include:
- Frontmatter explaining the append-only rule
- Empty `## ADR-001: <First Decision>` placeholder with the standard fields (Date, Status, Deciders, Context, Decision, Consequences, Alternatives considered)

**6. New template: `templates/orchestration/ADR_TEMPLATE.md`**

The standalone ADR template (just the field structure) so engineers can copy-paste when adding the next ADR.

### TIER 1 (real changes — target v1.4, NOT v1.3.4)

**7. Dashboard upgrade — port from Kontract.**

`SpineDevelopment/lib/dashboard.html` is currently 100 lines and minimal. Kontract's dashboard (`~/Projects/Apps/Kontract/frontend/dashboard.html` + `dashboard-app.js` + the backend reader at `src/api/dashboard/routes.ts`) has:
- Live activity panel (team cards with click-to-expand drawer showing each worker's state)
- Batch jobs panel with action buttons (cleanup orphans, stop all)
- Host resources panel (CPU/MEM/GPU from a host-stats collector script)
- OCR backfill stats
- Stats bar pills with click-to-drawer

Backporting this is a substantial code change (TS routes, JS frontend, CSS, host-stats collector). Should be its own v1.4 milestone with engineer-team work, not a quick additive pass. Khash has it tracked as Kontract task #135.

**8. Optional: `## Tier hint: batch` directive annotation.**

Mentioned as a v1.4 candidate in the v1.3.3 changelog. Idea: a directive with `## Tier hint: batch` at the top auto-bumps `INVOCATION_TIMEOUT_S` for the duration. Avoids the manual `INVOCATION_TIMEOUT_S=5400 nohup ...` dance for batch work.

## How to ship v1.3.4

1. Add the 4 Tier-3 content items above (recipes + playbook additions + templates).
2. **Add a new `--pull-knowledge-only` flag to `install.sh`** so existing projects (Kontract, Adajoon, etc.) can pick up the lessons without overwriting their `lib/*.sh` daemons. Behavior: copy `recipes/`, `playbook-defaults/`, `role-prompts/` into the target. Leave `lib/*.sh` and `lib/dashboard.html` alone. Idempotent.
3. Update `CHANGELOG.md` with v1.3.4 entry — keep the same voice as v1.3.3 ("the X pass. Triggered by Y. Pure additive — no breaking changes.").
4. Tag and commit on the SpineDevelopment repo.
5. (Optional) Run `bash install.sh ~/Projects/Apps/Kontract --pull-knowledge-only` and `bash install.sh ~/Projects/Apps/StableBank --pull-knowledge-only` etc. to push the new lessons to existing installs. Khash decides whether to do this immediately or let them pull at their own cadence.

## Style notes for the v1.3.4 content

- Match the voice of existing v1.3.x content. Look at `playbook-defaults/datawright.md` and `recipes/host-side-llm-pipeline.md` for tone — direct, opinionated, anchored to a real incident, ends with "validated by" or "next pitfall to avoid" sections.
- Each recipe should be ~150-300 lines. Long enough to be useful, short enough to read.
- Cite the Kontract ADR / file path when something is sourced from a real decision. The reader should be able to follow the citation back to original context.
- No marketing voice. No "leverage" or "robust." This is engineering documentation, not a pitch deck.

## What I'm NOT handing you

- The Kontract project itself. Stay out of `~/Projects/Apps/Kontract/`. Khash is working there with another agent.
- Other sibling projects (Adajoon, etc.). Same — don't touch.
- The agent-team daemons themselves (`lib/team-agent-daemon.sh`, etc.). They're stable and work; don't refactor without a real reason.

## Memory files (if you have them)

If you have user-level memory (Khash's preferences across sessions), the relevant entries are:
- `kontract_classifier_split.md` — two-stage classifier decision (ADR-018)
- `kontract_model_naming.md` — naming convention (ADR-019)
- `feedback_educator_mode.md` — Khash wants concepts explained before decisions are presented; teach with live problems as cases
- `kontract_agent_team.md` — the agent team architecture
- `kontract_stack_control.md` — `kontract.sh` is the canonical control surface

These should inform tone but not require you to import them.

## First message you might send

Suggested opener for your first session with Khash:

> I'm the spine agent. Read HANDOFF_FOR_AGENT.md in SpineDevelopment. Want me to start with the v1.3.4 punch list? I'd propose tackling them in this order: [list 6 Tier-3 items]. Each is short — I'll write inline so you can review as I go. Sound right?

That's it. Good luck.

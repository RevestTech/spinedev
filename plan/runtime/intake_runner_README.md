# intake_runner — plan-phase Q&A loop

What it does: drives the interactive intake template for a project entering
`plan_in_progress`, persists answers + a draft PRD into
`spine_lifecycle.project.metadata`, and audits each step.

## Surface

`plan.runtime.intake_runner.run_intake(project_id, *, template=None, actor="product")`

- `project_id` — BIGINT id (int or str) or unique project `name`.
- `template`   — intake template name (matches a YAML in `plan/templates/intake/`);
  falls back to `project.metadata.intake_template`, then to
  `_DEFAULT_TEMPLATE_BY_PROJECT_TYPE`.
- Returns an `IntakeResult` with the answer dict + PRD-validation summary.

Raises:
- `IntakeNotInteractive` — stdin is not a tty. The MCP `plan_dispatch` tool
  maps this to `error_code=intake_requires_tty` so the user falls back to
  `spine intake <id>` in a real shell.
- `IntakeTemplateNotFound` — no YAML for the requested template.

## Persistence shape

```jsonc
project.metadata = {
  "intake": {
    "template": "cli-tool",
    "template_version": "mtime=...;size=...",
    "started_at":  "ISO-8601",
    "completed_at":"ISO-8601",
    "answers": { "<question_id>": <answer>, ... }
  },
  "prd_draft": { "version": "prd-v1", ... }  // PRDv1.model_dump(mode="json")
}
```

Existing keys are preserved (jsonb `||` merge); re-running intake clobbers
just `intake` and `prd_draft`.

## Audit trail

Four `spine_audit.audit_event` actions per run, all `subsystem=plan`,
`role=product`:

| action                       | when                          |
|------------------------------|-------------------------------|
| `intake_started`             | before the first question     |
| `intake_question_answered`   | once per question (granular!) |
| `intake_completed`           | after answers persist         |
| `prd_draft_persisted`        | after PRD draft persists      |

Audit-write failures are swallowed (the metadata write IS source of truth);
they're logged but never block the intake.

## How it'll be replaced

This is a deterministic v1: read template, ask, write. The LLM-driven runner
will live alongside (e.g. `plan.runtime.intake_runner_llm`) and:

- pre-fill answers from a description blob or repo scan,
- challenge weak answers via the 5-move dialogue protocol
  (see `docs/MASTER_BACKLOG.md` EPIC-1.1, "product role intake"),
- emit the same `metadata.intake.answers` shape so downstream consumers
  (PRD synth, swarm dispatch, roadmap) need no change.

The selector — deterministic vs LLM — will read a project setting; the
`spine intake` CLI flag is the override.

## What's intentionally NOT here

- Tech Review Swarm (`plan/swarm/`) — runs in `plan_review`, the next phase.
- Roadmap decomposer (`plan/decomposer/`) — phase after that.
- Per-question retry/undo — re-run intake to overwrite.
- Pydantic-sealed PRDs — drafts only; sealing happens in plan_approved.

# Spine Reproducible Builds (EPIC-3.2)

> A Spine directive run should be replayable from `directive + REQ + role-version
> + model-version`, the same way `docker build` is replayable from a Dockerfile +
> base image. — `docs/PRD.md` REQ-INIT-3.

Implements `STORY-3.2.1` (manifest format), `STORY-3.2.2` (`spine replay`),
`STORY-3.2.3` (diff two runs).

## Why

1. **Debugging.** "Yesterday's QA agent flagged a real bug. Today it doesn't.
   What changed?" Capture both manifests, run `diff_manifests` — the answer
   surfaces in seconds (role prompt edit, model swap, prd revision, etc.).
2. **Audit.** Compliance teams need bit-level provenance: "What model, what
   prompt, what input produced this artifact?" The manifest is the answer in
   a single file.
3. **Regression checks.** Pair with `shared/eval/runner.py` (EPIC-3.4): when
   a role prompt is edited, replay a corpus of historical manifests against
   the new prompt; flag outputs that drift from baseline.

## Capture

Two paths:

- **Automatic** (target — not yet wired): every directive completion writes
  a manifest to `~/.spine/manifests/<project_uuid>/<directive_id>.yaml` via
  an `audit_event` post-hook.
- **Manual** (today): `spine replay capture <directive_id>`. Best-effort —
  pulls what it can from `spine_lifecycle` + `spine_audit` + filesystem.

## Replay vs Validate

| Command | DB read | Dispatches | Use |
|---|---|---|---|
| `spine replay validate <m>` | yes | no | "Could I reproduce this run right now?" |
| `spine replay <m> --dry-run` | yes | no | "Show me the payload that would dispatch." |
| `spine replay <m>` | yes | YES | Actually run it; compare outputs. |
| `spine replay <m> --force-drift` | yes | YES | Replay despite critical drift. |

## Drift categories

`diff.py` classifies every field change into one tier:

- **critical** — role prompt, pipeline version, pipeline manifest, model id,
  any input sha. Critical drift means the new run is *not* reproducing the
  old run — it's a NEW run with different inputs.
- **minor** — temperature, max_tokens, lockfile shas, git dirty flag.
  Output may still match; usually safe.
- **informational** — branch name, role prompt path, anything else. Almost
  never affects output.
- **ignored** — `manifest_uuid`, `created_at`, `metadata`. Always differ.

`replay()` refuses to proceed on critical drift unless `--force-drift` is
set. `validate()` returns `(False, [...drift tags])` so CI gates can fail
on any drift.

## Use cases

- "Reproduce yesterday's bug." → `spine replay history <project_id>` →
  pick the manifest → `spine replay <path>`.
- "Did the prompt edit help?" → Capture before; edit prompt; replay against
  captured manifest with `--force-drift`; compare output hashes.
- "What model did this run use?" → `yq .runtime.model_id <manifest>`.
- "Same directive, different model — same output?" → Capture two manifests,
  `diff_outputs(a, b)` → compares hashes from the audit log.

## Cross-refs

- `docs/PRD.md` REQ-INIT-3 EPIC-3.2 — story specs.
- `docs/BACKLOG.md` STORY-3.2.1, 3.2.2, 3.2.3 — status + owners.
- `shared/audit/audit_record.py` — provides the output_hash this module
  reads back during diff.
- `shared/eval/runner.py` — related but distinct: eval *scores* outputs;
  replay *recreates* runs.
- `orchestrator/lib/router.sh` — single dispatch chokepoint; `replay()`
  invokes the SAME path, never a side channel.
- `db/flyway/sql/V14__spine_lifecycle_schema.sql` — provides
  `project.pipeline_version` and `route_history.directive_ref` that
  capture queries against.
- `manifest_schema.yaml` — human-readable schema; kept in sync with the
  Pydantic model in `manifest.py`.

## Constraints

- Pydantic v2 + PyYAML + stdlib. No DB driver dep (psql via subprocess).
- All git ops via subprocess (`git rev-parse`, `git status --porcelain`).
- Dispatch chokepoint: `orchestrator/lib/router.sh dispatch ...`. Never
  bypass.

## Known limitations

- Capture is best-effort: a manifest with `"unknown"` fields is still
  valid — it documents what was knowable at capture time.
- Replay against current code, not historical code. To replay the
  exact historical run, `git checkout <commit_sha>` first.
- Model nondeterminism: even identical inputs may produce different
  outputs. `diff_outputs` reports the drift, not the cause.

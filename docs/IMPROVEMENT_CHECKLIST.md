# Improvement checklist (maintainers)

> **v1.3.4 (2026-05-10):** Installer `--pull-knowledge-only`, orchestration docs + ADR templates on install, `docs/SPINE_PRACTICES.md`, portable operator/datawright prompts, PROTOCOL/README alignment. Remaining unchecked items below are still valid follow-ups.

Actionable items to keep the template healthy. Completion is optional; use as a roadmap.

## Documentation

- [ ] Keep `README.md` aligned with `CHANGELOG.md` for “current release” messaging (no stale single-version headline).
- [ ] Keep `PROTOCOL.md` §8 (scale) and §10 (revision) consistent with actual manager/worker counts and package history.
- [ ] Keep `INSTALL.md` examples aligned with `lib/team.sh` output (e.g. manager/worker counts).
- [ ] When adding features, update the “Files” table in `README.md` and, if needed, `REQUIREMENTS.md`.

## Installer

- [ ] Full install copies **recipes** into `.planning/orchestration/recipes/` and **orchestration templates** when absent.
- [ ] `--pull-knowledge-only` remains idempotent: never overwrite user `memory.md` or playbook lessons without `--force` where applicable.
- [ ] Document both install modes in `INSTALL.md` and installer usage text.

## Portability

- [ ] Role prompts (`lib/role-prompts/*.md`) stay **project-agnostic** or clearly marked as examples—no hard-coded single-product names.
- [ ] Recipes may mention real incidents in the abstract; avoid coupling the template to one codebase.

## Product / runtime

- [ ] Consider directive-level **long-job** / batch timeout hints to reduce manual `INVOCATION_TIMEOUT_S` overrides.
- [ ] Clarify in logs or report headers when an invocation ends `rc=0` but output may be incomplete (edge cases only).
- [ ] Dashboard: either commit to minimal static HTML or plan a larger milestone explicitly in `docs/EXTENSIONS.md`.

## Release hygiene

- [ ] Tag releases to match `CHANGELOG.md` entries when shipping.
- [ ] Run `bash lib/preflight.sh` (or target `team-preflight`) after installer changes.

## Security and ops

- [ ] Document trust boundaries for `.planning/orchestration/` (who may write directives).
- [ ] Recommend notification + approval gates for destructive operations in onboarding text.

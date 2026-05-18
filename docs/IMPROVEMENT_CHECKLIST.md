# Improvement checklist (maintainers)

> **Pre-v3 document — preserved for historical context.** This checklist tracked v1.x maintainer
> backlog items for the file-bus orchestration framework. The v3 product (containerized Hub) has its
> own canonical launch backlog at [`docs/V1_SHIP_CHECKLIST.md`](V1_SHIP_CHECKLIST.md) — see that
> file (not this one) for active v1.0 ship gating. For current Spine v3 status see
> [`STATUS.md`](STATUS.md); for design decisions see
> [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md).

> **v1.4.4:** **`make selftest`** + **`lib/tests/test-*.sh`**. **v1.4.3:** **`## Long job:`** extension-only + **`costs.csv` `outcome`**. **v1.4.2:** documentation + **`EXTENSIONS`**. **v1.4.0:** Program-delivery framework. **Post–ADR-001 (template):** **13-manager** roster (`engineering-*` top-level roles retired — use **`engineer`** + workers). **v1.3.4:** knowledge-only install + ADR scaffolding. Remaining checklist rows still apply for future hardening.

Actionable items to keep the template healthy. Completion is optional; use as a roadmap.

## Documentation

- [x] Keep `README.md` aligned with `CHANGELOG.md` for “current release” messaging (no stale single-version headline). *(Re-aligned for **13-manager** roster + ADR-001, 2026-05.)*
- [x] Keep `PROTOCOL.md` §8 (scale) and §10 (revision) consistent with actual manager/worker counts and package history. *(§10 manual-maintainer note in v1.4.2.)*
- [x] Keep `INSTALL.md` examples aligned with `lib/team.sh` output (e.g. manager/worker counts).
- [x] When adding features, update the “Files” tree in `README.md` and, if needed, `REQUIREMENTS.md`.

## Installer

- [ ] Full install copies **recipes** into `.planning/orchestration/recipes/` and **orchestration templates** when absent.
- [ ] `--pull-knowledge-only` remains idempotent: never overwrite user `memory.md` or playbook lessons without `--force` where applicable.
- [ ] Document both install modes in `INSTALL.md` and installer usage text.

## Portability

- [ ] Role prompts (`lib/role-prompts/*.md`) stay **project-agnostic** or clearly marked as examples—no hard-coded single-product names.
- [ ] Recipes may mention real incidents in the abstract; avoid coupling the template to one codebase.

## Product / runtime

- [x] Consider directive-level **long-job** / batch timeout hints to reduce manual `INVOCATION_TIMEOUT_S` overrides. *(**`## Long job:`** in v1.4.3 — **PROTOCOL** §13.)*
- [x] Clarify in logs or report headers when an invocation ends `rc=0` but output may be incomplete (edge cases only). *(**`outcome`** column + **`team status` / `doctor` / dashboard** in v1.4.3.)*
- [x] Dashboard: either commit to minimal static HTML or plan a larger milestone explicitly in `docs/EXTENSIONS.md`. *(Spine Control Center documented as shipped in v1.4.2; optional Tier-1 uplift remains out of scope for the template.)*

## Release hygiene

- [ ] Tag releases to match `CHANGELOG.md` entries when shipping.
- [x] Run `bash lib/preflight.sh` (or target `team-preflight`) after installer changes. *(Last run clean 2026-05-10; re-run whenever `install.sh` / `lib/*.sh` changes materially.)*

## Security and ops

- [ ] Document trust boundaries for `.planning/orchestration/` (who may write directives).
- [ ] Recommend notification + approval gates for destructive operations in onboarding text.

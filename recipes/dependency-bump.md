# Recipe — Bump a dependency safely (engineer)

Drop into `teams/engineer/directive.md`.

---

```markdown
# Directive — Bump <DEP NAME> from <CURRENT VERSION> to <TARGET VERSION>

## Tier hint: low

(Most dep bumps are mechanical. Escalate only if a major-version migration with breaking API changes.)

## Why now
<one line: security advisory / new feature needed / drift cleanup>

## Tasks
1. Read CHANGELOG / migration guide for `<dep>` between current and target version
2. Update package manifest (package.json / requirements.txt / Cargo.toml / etc)
3. Lock files refresh (npm install / pip-compile / etc)
4. Run lint + test — note which tests broke
5. If anything broke: apply minimal patches per the migration guide. Do NOT redesign anything beyond what the migration requires.
6. Run security audit (npm audit / pip-audit / cargo audit) — confirm no new high vulns

## Stop conditions (DO NOT continue if any of these hit)
- Test failures > 1% of suite without a clear migration-guide explanation
- Major API surface broke and the migration guide is silent about what to do
- A peer dep wants a different version than what we're targeting

If you stop, report what you tried + what's blocking, and recommend either pinning to an interim version or scoping a bigger migration.

## Report format
Replace this file with `# Report — <dep>@<version>` containing:
- Diff summary (package.json, lockfile delta in lines)
- Test counts before/after
- Audit results before/after
- Migration-guide compliance: which steps applied, which were N/A
- Anything broken or surprising
- Suggested next directive (if interim version)
```

# AI integration — fc-sdlc

> **For AI agents:** Read this before claiming gate sign-off, sprint close, or "tests pass."

## When to use fc-sdlc

| Situation | Action |
|-----------|--------|
| New FC greenfield repo | Ensure `init-sdlc.sh` ran; `todo/gates/` exists |
| Starting a task | Read `docs/fc-sdlc-STATUS.md`, then `todo/BACKLOG.md` |
| Before multi-agent wave | Read `docs/PARALLEL-BATCH-CHECKLIST.md` |
| Sprint end / pre-G4/G5 | Run `/sprint-cleanup`; write cleanup report |
| Claiming tests green | Run `npm run sdlc:run-qa` (or stack command); cite output |

## Bootstrap (human or agent)

```bash
/path/to/fc-sdlc/scripts/init-sdlc.sh \
  --target . \
  --name "My App" \
  --stack node \
  --prefix APP \
  --fc-sdlc-path ./vendor/fc-sdlc
```

## Agent check-in (when PM running)

```bash
npm run pm:checkin -- --agent <id> --role developer --status in_progress \
  --task APP-001 --message "Starting work"
```

One line only — do not break `--message` across lines.

## Validation commands

```bash
npm run sdlc:validate-gates
npm run sdlc:validate-gates -- --check-placeholders   # after Sprint 0
npm run sdlc:validate-gates -- --check-g5             # before G5 sign-off
npm run sdlc:run-qa                                   # evidence tests
```

## Source of truth (never violate)

1. `todo/BACKLOG.md` — work queue
2. `todo/gates/G*.md` — gate sign-offs
3. `docs/fc-sdlc-STATUS.md` — session resume / honest state (`docs/STATUS.md` is historical v3 wave log only)

Jira/Linear are mirrors only. See `docs/JIRA-LINEAR-MAPPING.md`.

## Brownfield

```bash
node vendor/fc-sdlc/scripts/migrate-brownfield.mjs --source todo.md --prefix APP
# Review output, merge into todo/BACKLOG.md
```

## PM dashboard

- Local only by default (`127.0.0.1:5190`)
- Docker: `npm run pm:up` with `PM_ALLOW_REMOTE=true` in compose

## Do not

- Mark gates signed without filled sign-off tables
- Claim QA green without running `sdlc:run-qa` in the same session
- Replace BACKLOG with Jira exports
- Skip `fc-sdlc-STATUS` update after material changes

## References

- [PLAYBOOK.md](./PLAYBOOK.md)
- [QA-READINESS-STANDARD.md](./QA-READINESS-STANDARD.md)
- `.cursor/rules/project-manager.mdc`

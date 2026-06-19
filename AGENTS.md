# Spine — agent context

Read this first when working in this repository.

## Workspace

| | Path |
|---|------|
| **Use for all dev** | `~/dev/SpineDevelopment` |
| iCloud mirror (sync only) | `~/Projects/Apps/SpineDevelopment` → resolves under `Library/CloudStorage/...` |

Set `SPINE_LOCAL_ROOT=~/dev/SpineDevelopment`. Cursor hooks block npm/Docker on iCloud paths.

## Product

Spine is a self-hosted AI engineering Hub (Docker). See `docs/SPINE_MASTER.md` and `CLAUDE.md`.

## This machine

- Hub: http://localhost:8090/spa/ — `bash tools/hub-up.sh`
- Smoke contract: `bash tools/smoke-test.sh` → 99 PASS / 0 FAIL
- Full QA: `bash tools/fc-sdlc/ci-test-full.sh`
- Harness Lite: `bash tools/harness/dogfood.sh` — see `Handoff.md`

## Cursor setup

| Asset | Location |
|-------|----------|
| Local dev rule | `.cursor/rules/local-dev-workspace.mdc` |
| PM check-in | `.cursor/rules/project-manager.mdc` |
| Skills | `.cursor/skills/spine-local-dev/`, `spine-harness-session/`, `harness-*` |
| Hooks | `.cursor/hooks.json` |
| Human doc | `LOCAL_DEV.md` |

## Agent protocol

1. `cd ~/dev/SpineDevelopment`
2. PM check-in (in_progress) — `npm run pm:checkin`
3. Do work; run evidenced QA before claiming pass
4. PM check-in (completed) with deliverable path

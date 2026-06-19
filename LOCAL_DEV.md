# Local development — Spine (this machine)

## Canonical workspace

Open **this folder** in Cursor:

```
~/dev/SpineDevelopment
```

| Path | Role |
|------|------|
| `~/dev/SpineDevelopment` | **Canonical** — git root, Docker, npm, agents |
| `~/Projects/Apps/SpineDevelopment` | Symlink → `~/dev/SpineDevelopment` (same tree) |

The old iCloud-synced duplicate (if any) is archived as `SpineDevelopment.icloud-archive-*` under `~/Projects/Apps/`.

## Services

| Service | URL |
|---------|-----|
| Hub SPA | http://localhost:8090/spa/ |
| PM dashboard | http://localhost:5190 |

Start Hub:

```bash
cd ~/dev/SpineDevelopment
bash tools/hub-up.sh
```

## One-shot setup

```bash
bash tools/local-dev-setup.sh
```

## Quality gates

```bash
bash tools/smoke-test.sh          # 99 PASS / 0 FAIL contract
bash tools/fc-sdlc/ci-test-full.sh
bash tools/harness/spine-harness verify --project . --run-qa
```

## Cursor integration

- Rules: `.cursor/rules/local-dev-workspace.mdc`
- Skills: `.cursor/skills/spine-local-dev/`, `spine-harness-session/`
- Hooks: `.cursor/hooks.json` (iCloud path guard, session context)

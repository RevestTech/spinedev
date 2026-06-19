---
name: spine-local-dev
description: >-
  Spine local development on this machine — canonical path ~/dev/SpineDevelopment,
  Hub/docker/npm rules, bootstrap, hub-up, smoke-test. Use when starting work,
  fixing env, or anything touches Docker, SPA, postgres, or vite.
---

# Spine local dev (this machine)

## Canonical workspace

```bash
cd ~/dev/SpineDevelopment
export SPINE_LOCAL_ROOT=~/dev/SpineDevelopment
```

Never run Node or Docker tooling from iCloud CloudStorage paths.

## First-time / repair setup

```bash
bash tools/local-dev-setup.sh
# or from iCloud copy:
bash tools/local-dev-setup.sh --from-icloud
```

## Daily loop

```bash
# Hub (if not running)
bash tools/hub-up.sh
curl -fsS http://localhost:8090/spa/ >/dev/null && echo hub_ok

# Python deps
.venv/bin/pip install -r requirements.txt

# SPA (only from local path)
cd shared/ui/spa && npm ci --ignore-scripts && npm run build

# Quality gates
bash tools/smoke-test.sh
bash tools/fc-sdlc/ci-test-full.sh
```

## Harness Lite (no Hub required)

```bash
bash tools/harness/dogfood.sh
bash tools/harness/spine-harness audit --project .
bash tools/harness/spine-harness verify --project . --run-qa
```

## Sync iCloud ↔ local

Prefer **git** for code. For uncommitted iCloud → local:

```bash
rsync -a --exclude node_modules --exclude .venv \
  ~/Projects/Apps/SpineDevelopment/ ~/dev/SpineDevelopment/
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `vite: command not found` / `ERR_INVALID_MODULE_SPECIFIER` | Wrong cwd — use `~/dev/SpineDevelopment` |
| Docker pull fails / no space | `docker builder prune -af`; need ~5GB free |
| Postgres connection refused | `bash tools/hub-up.sh` then wait ~30s |
| `pytest` missing | `.venv/bin/pip install -r requirements.txt` |

## References

- `LOCAL_DEV.md`
- `tools/local-dev-setup.sh`
- `docs/HUB_OPERATIONS_GUIDE.md`

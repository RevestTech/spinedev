# Operate acceptance (G5)

Read-only black-box checks for autonomous operate loop. **Do not** edit
`~/spine-projects/*` from this tooling.

## Prerequisites

- Hub running: `bash tools/hub-up.sh --rebuild`
- `SPINE_HUB_DEV=1` for local dev (recovery routes accept unauthenticated calls)
- Disposable project in **operate** phase with `feature_requests` queue

## Quick check

```bash
python3 tools/acceptance/operate_blackbox.py \
  --project-uuid '<uuid>' \
  --hub-url http://localhost:8090
```

## Watch until iteration passes (acceptance run)

```bash
python3 tools/acceptance/operate_blackbox.py \
  --project-uuid '<uuid>' \
  --watch --timeout 3600 --interval 30
```

## Pass criteria

1. Hub `/healthz` returns 200 with `"ok": true`
2. Project `current_phase` is `operate`
3. `GET /api/v2/projects/{uuid}/recovery` returns `ok: true` within 2s
4. At least one `feature_requests[]` entry is `completed` and another is
   `requested`, `in_progress`, or `backlog`
5. Recovery is not `stuck`

Wave 4 rollup: `bash tools/harness/wave4-ship-gates.sh --project-uuid '<uuid>'`

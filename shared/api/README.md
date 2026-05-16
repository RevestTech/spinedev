# Spine REST API (`shared/api/`)

Thin REST wrapper over the unified MCP server (`shared/mcp/`) + direct
Postgres reads against `spine_lifecycle` and `spine_audit`. Implements
**STORY-9.9.2** / PRD REQ-INIT-9 §9.5 FR-10. Replaces the dev-only
`shared/ui/approvals/proxy.py`. Stack: Python 3.11+, FastAPI ≥ 0.110,
Pydantic v2.

## Run

```bash
export SPINE_DB_URL='postgresql://spine:spine@localhost:33000/spine'
export SPINE_API_CORS_ORIGINS='http://localhost:8080'
uvicorn shared.api.app:create_app --factory --port 8088
# OpenAPI JSON:  http://localhost:8088/api/v2/spec
# Swagger UI:    http://localhost:8088/api/v2/docs
```

## Routes

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v2/projects` | MCP `project_create`. |
| `GET` | `/api/v2/projects` | `phase`, `status`, `owner`, `limit`, `offset`. |
| `GET` | `/api/v2/projects/{id}` | Status snapshot + total cost. |
| `PATCH` | `/api/v2/projects/{id}` | Update `status` / `metadata` (stub). |
| `POST` | `/api/v2/projects/{id}/phase-advance` | MCP `phase_advance`. |
| `POST` | `/api/v2/projects/{id}/rollback` | `transition.sh` rollback (stub). |
| `GET` | `/api/v2/approvals` | `status=pending` -> `gate.sh list-pending`. |
| `POST` | `/api/v2/approvals` | `{project_id, phase?, action, approver?, notes?}`. |
| `GET` | `/api/v2/approvals/{id}` | Single approval row. |
| `GET` | `/api/v2/audit` | `project_id` xor `correlation_id`. |
| `GET` | `/api/v2/audit/export` | `format=csv|json`, attachment. |
| `GET` | `/healthz` | DB + MCP reachability. |
| `GET` | `/readyz` | Required schemas present. |
| `GET` | `/api/v2/spec` | OpenAPI JSON. |

## Auth (v1)

No real auth — single-user local-deploy. `current_user` in
`dependencies.py` reads `X-Spine-Actor` (default `local-user`). Every
request logs identity + an `X-Request-ID` (auto-generated when absent).
JWT/OAuth slots in behind `current_user()` without touching routes.

## Architecture

- Mutations -> in-process MCP (`McpClient.call`) -> typed input model
  -> registered tool function.
- Reads -> Postgres via `DbHandle` (subprocess `psql` for v1; swap to
  `asyncpg` pool by replacing `get_db_pool`).
- Approvals -> shell out to `orchestrator/lib/gate.sh` (HMAC +
  transition coupling lives there; we don't re-implement).
- Error envelope -> `{"error_code": str, "message": str, "details"?: dict}`.

## Env vars

| Var | Default | Purpose |
|---|---|---|
| `SPINE_DB_URL` | `postgresql://spine:spine@localhost:33000/spine` | Postgres DSN. |
| `SPINE_API_CORS_ORIGINS` | `http://localhost:8080` | Comma-separated CORS list. |
| `SPINE_ROOT` | `<repo root>` | Used to locate `gate.sh`. |
| `SPINE_GATE_SH` | `$SPINE_ROOT/orchestrator/lib/gate.sh` | Override path. |

## Files

- `app.py` — factory + middleware + lifespan + health endpoints.
- `dependencies.py` — DB pool, MCP client, auth stub.
- `routes/projects.py` — `/api/v2/projects/*`.
- `routes/approvals.py` — `/api/v2/approvals/*`.
- `routes/audit.py` — `/api/v2/audit/*`.

## Future work

- Swap `DbHandle` (subprocess `psql`) for `asyncpg` pool — same surface.
- Real auth (JWT/OAuth) — wire into `current_user`.
- WebSocket subscription for dashboard live updates (STORY-9.9.4).
- Dedicated `phase_rollback` MCP tool — `PATCH` + `/rollback` currently
  return stub envelopes pending that wiring.

## Migration from dev proxy

`shared/ui/approvals/proxy.py` exposes `/api/v2/approvals` and
`/api/v2/artifacts` on port `8081`. This FastAPI app keeps the
`/api/v2/approvals` contract intact (same request/response shapes); the
`/api/v2/artifacts` artifact-fetch endpoint is intentionally **not**
ported — UI should fetch markdown directly from Git or a future
dedicated `/api/v2/artifacts` route once the artifact registry lands.

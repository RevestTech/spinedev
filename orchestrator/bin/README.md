# `spine` — orchestrator CLI

Primary user entry point. Implements **`STORY-9.9.3`** per `docs/PRD.md`
REQ-INIT-9 §9.5 FR-10. Thin bash wrapper around the orchestrator's MCP
server (`STORY-9.9.1`, `shared/mcp/tools/orchestrator.py`): mutations go
through `_mcp_call`, read-side queries hit Postgres directly.

## Install

Manual symlink (integrated install via root `install.sh` is a follow-on):

```sh
chmod +x orchestrator/bin/spine
ln -s "$(pwd)/orchestrator/bin/spine" ~/.local/bin/spine
spine doctor          # verify psql + MCP reachable
```

## Quick start (vibecoder path)

```sh
spine project new my-app --type greenfield --description "weekend hack"
# → MCP project_create; prints {"project_id":"proj_…","initial_phase":"intake"}

spine project status proj_abc123       # current phase, pending approvals
spine project approve proj_abc123 plan_approved --notes "looks good"
spine project audit  proj_abc123 --export csv > audit.csv
```

## Commands

| Group | Command | Backend |
|---|---|---|
| Lifecycle | `project new`            | MCP `project_create` |
|           | `project status [--watch]` | MCP `project_status` |
|           | `project list / show`    | SQL on `spine_lifecycle.project` (+ MCP for `show`) |
|           | `project audit`          | SQL on `spine_audit.events` |
| Gates     | `project approve`        | MCP `approval_grant` → `phase_advance` |
|           | `project reject`         | MCP `gate_reject` |
|           | `project rollback`       | MCP `phase_advance` with `rollback:true` |
| Portfolio | `status`                 | SQL rollup by phase |
|           | `doctor`                 | psql + MCP health probe |

Every command supports `--help`. `spine help [<topic>]` shows per-command
usage; `spine help` alone prints the full menu.

## Global flags

`--format json|table|brief` (default human; uses `jq` if present) ·
`--dry-run` (print would-be MCP payload, no call) · `--verbose/-v` (debug to
stderr) · `--quiet/-q` · `--help/-h`.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `SPINE_DB_URL`         | `postgresql://spine:spine@localhost:33000/spine` | psql connection |
| `SPINE_MCP_HTTP_URL`   | `http://127.0.0.1:8765` | HTTP transport fallback (when `mcp` CLI not on PATH) |
| `SPINE_DEFAULT_BUNDLE` | _(unset)_ | Org bundle id for `project new --bundle` |
| `SPINE_DEFAULT_OWNER`  | `$USER`   | Default `--owner` / `--approver` |

## Exit codes

| Code | Meaning |
|---|---|
| 0  | ok |
| 1  | generic error |
| 2  | invalid input (missing arg, bad flag, unknown project) |
| 3  | gate blocked / would exceed budget |
| 4  | MCP or Postgres unreachable |
| 64 | unknown subcommand |

## Cross-refs

- `STORY-9.9.1` MCP tools backing this CLI (`shared/mcp/tools/orchestrator.py`)
- `STORY-9.9.2` REST API (alternate surface, future)
- `orchestrator/lib/router.sh::_mcp_call` — transport pattern reused here
- `orchestrator/lib/gate.sh` (`approve` / `reject`) + `transition.sh` (`phase_advance` / `rollback`) — server-side
- `docs/PRD.md` REQ-INIT-9 §9.5 FR-10 · `docs/BACKLOG.md` STORY-9.9.3

# `shared/mcp/` — Unified Spine MCP server

> **Status:** Scaffolded 2026-05-16 (Phase 0). Tools below are stubs; real
> implementations land per the listed story IDs.

## Purpose

Single dispatch surface for the whole product. Plan, Build, Verify, and
Orchestrator all expose their primitives as MCP tools through **one** server
that lives here. Closes the survey-flagged gap against ruflo, and consolidates
TRON's existing `tron/mcp/` per `STORY-8.2.2`.

Implements `STORY-2.2.1` (server scaffolding) plus initial tool stubs from:

- `EPIC-2.2` — MCP server + `org_standards_get`
- `EPIC-6.5` / `EPIC-6.7` — KG query tools + hybrid retrieval
- `EPIC-7.2` — Build dispatch + completion
- `EPIC-8.4` / `EPIC-8.5` — Verify audit + ISO invoke
- `EPIC-9.9` — Orchestrator project lifecycle

## Architecture

```
shared/mcp/
├── __init__.py
├── README.md                  ← this file
├── server.py                  # SpineMcpServer + CLI (stdio + http transports)
├── schemas/
│   ├── __init__.py
│   └── envelopes.py           # ToolRequest, ToolResponse, ToolError, ToolStatus
├── tools/
│   ├── __init__.py            # @register_tool decorator + TOOL_REGISTRY + discover_tools
│   ├── orchestrator.py
│   ├── plan.py
│   ├── build.py
│   ├── verify.py
│   ├── kg.py
│   └── standards.py
└── tests/
    └── test_server_smoke.py
```

### Key types

- **`ToolRequest`** — wire envelope: `project_id`, `actor`, `timestamp`, `params`.
- **`ToolResponse`** — wire envelope: `status` ∈ `{ok, error, stub_implementation}`,
  `data`, optional `error`, server-generated `audit_id`.
- **`ToolError`** — `code`, `message`, `retryable`.
- **`ToolSpec`** — internal registry entry: `name`, `fn`, `input_model`,
  `module`, `story`, `description`, `tags`.

### Transports

| Transport | Use case | Wired by |
|---|---|---|
| `stdio` | AI agent harnesses (Claude Code, Codex, Cursor) | `SpineMcpServer._serve_stdio` |
| `http`  | Dashboard, REST callers, external services      | `SpineMcpServer._serve_http`  |

The underlying `mcp` SDK is imported **lazily** inside the transport methods
so lint/test stages without the SDK installed can still import the module.

### Logging

Stdlib `logging` with a JSON formatter (`server.configure_logging`). Known
secret keys (`approval_token`, `token`, `api_key`, `secret`, `password`,
`hmac_key`) are redacted from any `extra=` payload before serialization.

## Tool catalog

| Name | Module | Implementing story | Status |
|---|---|---|---|
| `project_create`    | `tools/orchestrator.py` | `STORY-9.9.1` | stub |
| `project_status`    | `tools/orchestrator.py` | `STORY-9.9.1` | stub |
| `phase_advance`     | `tools/orchestrator.py` | `STORY-9.2.1` | stub |
| `approval_grant`    | `tools/orchestrator.py` | `STORY-9.3.2` | stub |
| `plan_dispatch`     | `tools/plan.py`         | `STORY-9.4.1` | stub |
| `build_dispatch`    | `tools/build.py`        | `STORY-7.2.2` | stub |
| `build_completed`   | `tools/build.py`        | `STORY-7.2.3` | stub |
| `verify_audit`      | `tools/verify.py`       | `STORY-8.5.1` | stub |
| `iso_invoke`        | `tools/verify.py`       | `STORY-8.6.1` | stub |
| `graph_query`       | `tools/kg.py`           | `STORY-6.5.1` | stub |
| `find_callers`      | `tools/kg.py`           | `STORY-6.5.2` | stub |
| `code_neighborhood` | `tools/kg.py`           | `STORY-6.5.4` | stub |
| `impact_radius`     | `tools/kg.py`           | `STORY-6.5.5` | stub |
| `doc_for_region`    | `tools/kg.py`           | `STORY-6.5.6` | stub |
| `who_owns`          | `tools/kg.py`           | `STORY-6.5.7` | stub |
| `hybrid_search`     | `tools/kg.py`           | `STORY-6.7.3` | stub |
| `org_standards_get` | `tools/standards.py`    | `STORY-2.2.5` | stub |

**Total: 17 tools.** Smoke test (`tests/test_server_smoke.py`) asserts this
count and that every entry has a unique name + Pydantic input model.

Tools deliberately *not yet* registered (cited in PRD but waiting for the owning
epic to be ready): `trace_dependency`, `find_by_satisfies`, `directive_create`,
`report_read`, `team_status`, `cost_summary`, `sandbox_run`. Add them via a new
`@register_tool` block in the appropriate module when the implementing story is
picked up.

## Running

```bash
# stdio (default) — used by Claude Code / Codex / Cursor configs
python -m shared.mcp.server --transport stdio

# http — used by the dashboard + REST callers
python -m shared.mcp.server --transport http --port 8765
```

Both transports require the `mcp` Python SDK to be installed. The module
itself imports without it; transport boot raises a clear `RuntimeError` if
it's missing.

## How to register a new tool

1. Pick the right module under `tools/` (or add a new one). Keep one
   concern per file; modules are capped at ~200 lines.
2. Define a Pydantic v2 `BaseModel` for the input. Use `extra="forbid"` so
   bad payloads are rejected at validation, not deep inside the function.
3. Decorate the implementation with `@register_tool(...)`:

```python
from pydantic import BaseModel, ConfigDict, Field
from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool


class MyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)


@register_tool(
    name="my_tool",
    input_model=MyToolInput,
    story="STORY-X.Y.Z",
    description="One-line human description.",
    tags=("kg",),
)
def my_tool(payload: MyToolInput) -> ToolResponse:
    ...
    return ToolResponse(status="ok", data={...})
```

4. Update the catalog table above and the count constant in
   `tests/test_server_smoke.py` (`EXPECTED_TOOL_COUNT`, `EXPECTED_TOOLS_BY_MODULE`).
5. The server auto-discovers the new tool on next boot — no edits to
   `server.py` needed. `discover_tools("shared.mcp.tools")` walks the
   package and imports every non-`_`-prefixed module.

## Testing

```bash
pytest shared/mcp/tests/
```

The smoke suite does **not** require a real MCP runtime; it exercises only
the static registry, envelope shapes, and `SpineMcpServer.load_tools`.

## Future consolidation

TRON's `tron/mcp/` server folds into this one per `STORY-8.2.2` (see
`docs/PRD.md` REQ-INIT-8 FR-2 for the code mapping). Until then, TRON's
server continues to run standalone; once consolidated, every tool currently
prefixed `tron_*` will be re-registered here (renamed where the unified
naming is clearer) and TRON's `tron/mcp/` retires.

## See also

- `shared/README.md` — boundary definition for the whole `shared/` tree.
- `docs/PRD.md` — REQ-INIT-6 FR-6, REQ-INIT-7 FR-2, REQ-INIT-8 FR-4, REQ-INIT-9 FR-5.
- `docs/BACKLOG.md` — INIT-2 EPIC-2.2, INIT-6 EPIC-6.5, INIT-7 EPIC-7.2, INIT-8 EPIC-8.4, INIT-9 EPIC-9.9.
- `docs/ARCHITECTURE.md` §4 (target structure) + §5 (TRON → Spine code mapping).

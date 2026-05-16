# `sandbox.py` — TRON Docker sandbox exposed as an MCP tool

**Story:** `STORY-3.5.2`
**Spec:** `docs/PRD.md` REQ-INIT-3 EPIC-3.5

## Why this tool

Today an engineer can "ship" a directive by writing code, eyeballing it, and reporting success — without ever running it. `sandbox_run` lets the engineer (or any role) actually execute the code in a hardened ephemeral container and report the real stdout / stderr / exit / resource usage. The orchestrator, qa role, or auditor can then call the same tool to independently re-run for verification. Trust shifts from "the model said so" to "the container said so."

## Wrapper architecture

```
Spine actor (engineer-daemon, qa, auditor, orchestrator)
        │
        ▼  MCP call
shared/mcp/tools/sandbox.py::sandbox_run   ← validates + audits + caps output
        │
        ▼  lazy import
verify/tron/sandbox/sandbox_client         ← TRON's existing public API
        │
        ▼  Docker container (ephemeral, isolated)
ToolResponse(status, data=SandboxRunOutput, audit_id)
```

The wrapper does **not** modify TRON. `verify.tron.sandbox` is imported lazily so this module loads even before `verify/` is wired onto `PYTHONPATH` — returns `ToolError(code='sandbox_not_available')` instead of crashing. Docker availability is probed once at import; if missing, every call returns `ToolError(code='docker_unavailable')` with `sandbox_used=False`.

## Cost attribution rule

`cost_attribution` is a `Literal["build", "verify", "plan"]`. The audit row's `subsystem` and the cost-ledger line item both track it:

- `build` (default) — engineer-daemon's pre-seal sandbox-verify pass (see `STORY-3.5.3`). Charges Build's phase budget.
- `verify` — canonical fix-verification path inside TRON's Layer 3, or the orchestrator's own re-runs. Charges Verify's phase budget.
- `plan` — rare: architect spike to confirm a design assumption (e.g., "does this regex pattern terminate?"). Charges Plan's phase budget.

Cost is computed as `cpu_seconds × $rate + memory_mb_seconds × $rate` with v1 placeholder rates (`$0.0001/CPU-sec`, `$0.00001/MB-sec`) overridable via `SPINE_SANDBOX_CPU_USD_PER_SEC` / `SPINE_SANDBOX_MEM_USD_PER_MB_SEC`. `STORY-3.5.5` will finalize rates and route into the unified ledger.

## Threat model summary

Inherited verbatim from TRON's sandbox (see `verify/docs/security/SANDBOX_THREAT_MODEL.md` post-subtree):

- **Ephemeral container** — fresh image per call, `--rm`'d on exit
- **Read-only rootfs** — only `/tmp` is writable tmpfs (10 MB)
- **All capabilities dropped** — `cap_drop=ALL`, `no-new-privileges:true`
- **Network isolated by default** (`network='none'`); opt-in `'isolated'` or `'internet'`
- **Custom seccomp profile** — `seccomp_profile` arg overrides the bundle default
- **Resource ceilings** — wall clock (≤ 600 s), memory (≤ 4 GB), CPU (≤ 16 cores), output (64 KB stdout/stderr each, truncation indicator appended)

## Standalone TRON preserved (G-8 in REQ-INIT-8)

One-way dependency: Spine imports TRON, TRON never imports Spine. `cd verify/ && docker compose up -d` still runs TRON audit-only with its own sandbox — this wrapper is purely additive.

## Limitations in v1

- No streaming output — full stdout/stderr returned only when the container exits
- 64 KB cap per stream (truncation marker appended if exceeded)
- No GPU support — CPU-only workloads
- TRON's actual `sandbox_client.run(...)` adapter is a TODO (see `STORY-3.5.2` comment in `sandbox.py`); the envelope shape is correct so callers can integrate against the contract today

## Future hooks

- `STORY-3.5.3` — engineer daemon calls `sandbox_run` before sealing each `BuildArtifact` (when applicable)
- `STORY-3.5.4` — org-bundle seccomp customization (stricter syscall filter for sensitive orgs)
- `STORY-3.5.5` — CPU-sec / memory-sec cost rows into the unified ledger (this story is partial)

## Cross-refs

- `verify/tron/sandbox/` — TRON's sandbox bundle (lifted in `STORY-3.5.1`)
- `verify/tron/services/sandbox_client.py` — current TRON `SandboxClient` (pre-lift entry point)
- `shared/mcp/tools/iso.py` — sibling early-detect tool the wrapper style mirrors
- `shared/audit/audit_record.py` — `AuditRecord` (`from_sandbox_run` classmethod is TODO)
- `docs/PRD.md` REQ-INIT-3 EPIC-3.5 — sandbox execution verification spec
- `docs/BACKLOG.md` EPIC-3.5 — `STORY-3.5.1` … `STORY-3.5.5`

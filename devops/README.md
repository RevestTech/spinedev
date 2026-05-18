# devops/ — Operate subsystem (V3 #11)

> Status: Wave 2 scaffold. Framework + registry + audit wiring are real;
> deeper action handlers are stubs (`NotImplementedError("v1.1+")`) until
> Wave 3 squads land per-plane provider plumbing.

## What this subsystem is

The 6th corner of the Spine SDLC. Per design decision #11 in
[`docs/V3_DESIGN_DECISIONS.md`](../docs/V3_DESIGN_DECISIONS.md):

> Spine builds AND **operates** production. Every competitor stops at
> "ship the code." Spine ships INIT-10 Operate Subsystem.

The subsystem owns:

1. The customer-facing **`devops` role** (distinct from the Spine-internal
   `operator` role — conflating them is the mistake every "AI DevOps"
   startup made).
2. The **8 control planes** (W2 reframe of R7 research). Each has its own
   state, vendors, blast radius, and human-in-the-loop seam.

## The 8 control planes

ENUM values from `spine_devops.control_plane_name` (V27 schema):

| Plane (`name`)    | Module                                  | Supported actions                                                 |
|-------------------|-----------------------------------------|-------------------------------------------------------------------|
| `ci_cd`           | `devops/planes/ci_cd.py`                | `trigger_build`, `cancel_build`, `retry_build`, `status_check`    |
| `infrastructure`  | `devops/planes/infrastructure.py`       | `plan`, **`apply`**, **`destroy`**, `drift_detect`, `cost_estimate` |
| `secrets`         | `devops/planes/secrets.py`              | **`rotate`**, `audit_access`, `list_active_leases`                |
| `monitoring`      | `devops/planes/monitoring.py`           | `add_dashboard`, `query`, `alert_define`, `sli_track`             |
| `alerting`        | `devops/planes/alerting.py`             | `route`, `ack`, `escalate`, `silence`                             |
| `deployment`      | `devops/planes/deployment.py`           | **`deploy`**, **`rollback`**, **`canary`**, `feature_flag_toggle` |
| `database`        | `devops/planes/database.py`             | **`migrate`**, `backup`, **`restore_test`**, `slow_query_report`  |
| `networking`      | `devops/planes/networking.py`           | **`dns_update`**, `lb_health`, `ingress_route`, **`ssl_cert_renew`** |

**Bold** actions are **HIGH_IMPACT** (Cite-or-Refuse-required per #12).
The dispatcher refuses to execute them unless the caller passes a
non-empty `citation` list in the payload. See
`devops/planes/base.py::HIGH_IMPACT_ACTIONS`.

## Public surface

```python
from devops import DevOpsDispatcher

d = DevOpsDispatcher()
assert sorted(d.registered_planes()) == [
    "alerting", "ci_cd", "database", "deployment",
    "infrastructure", "monitoring", "networking", "secrets",
]

# Read-only
status = await d.status("ci_cd", project_id="...")
actions = d.supported_actions("ci_cd")

# Dispatch
result = await d.invoke("ci_cd", "status_check", {"run_id": "abc"})
# -> ActionResult(plane_name="ci_cd", action="status_check",
#                 status="stub_implementation", audit_chain_anchor=...)
```

## MCP tools

`devops/mcp_tools.py` registers three tools via the existing
`shared.mcp.tools.register_tool` decorator:

* `devops_invoke(plane, action, payload)` — tagged
  `requires_citation=True` per #12; the MCP middleware enforces
  citation presence on every response.
* `devops_status(plane, project_id)` — read-only.
* `devops_planes_list()` — enumerate planes + supported actions.

Auto-registration: importing `devops.mcp_tools` fires the decorators
exactly like the existing `shared/mcp/tools/*.py` modules. Until Wave 3
extends `shared.mcp.server.load_tools` to also walk `devops/`, callers
should `import devops.mcp_tools` before invoking `discover_tools`.

## Relationships

### To `shared/charters/devops.md` (Squad 1's scope)

That file is the **role charter** — the prose-form playbook authored
against industry standards (PMBOK / ITIL / NIST / SRE handbook per #7).
It's what a human reads. This subsystem (`devops/`) is the **runtime
implementation** of what the charter says the role does.

* **Squad 1** documents the role.
* **Squad 3 (this one)** implements the role.

### To `db/flyway/sql/V27__devops_role.sql` (DB layer)

Wave 0 migration that establishes:

* The `spine_devops` schema.
* The `control_plane_name` ENUM (8 canonical values).
* `spine_devops.control_plane` (one row per `(plane_name, project_id)`).
* `spine_devops.action_log` (append-only; one row per `invoke()` call;
  references the `audit_chain_anchor` from `shared.audit.audit_record`).
* `spine_devops.runbook` (versioned runbook definitions).

`devops/planes/base.py::ControlPlane.invoke()` is the only writer to
`action_log` + `control_plane.last_invoked_at` / `status` in this
subsystem.

### To `shared/audit/audit_record.py`

Every `invoke()` writes a chained `AuditRecord` via
`chain_to_previous()`. Wave 2 work-around: the `ALLOWED_SUBSYSTEMS`
enum in `audit_record.py` doesn't yet include `'devops'`, so we use
`subsystem='shared'` + `role='devops'`. **Wave 3 housekeeping item for
Squad 4:**

1. Extend `ALLOWED_SUBSYSTEMS` to include `'devops'`.
2. Add a Flyway migration to update the DB CHECK constraint on
   `spine_audit.audit_event.subsystem`.
3. Search/replace this subsystem's `subsystem="shared"` strings to
   `subsystem="devops"` in `devops/planes/base.py` and
   `devops/dispatcher.py`.

### To `shared/secrets/`

`SecretsControlPlane` (`devops/planes/secrets.py`) delegates all value
lookups to `shared.secrets` per #9. The plane only **schedules** and
**audits** rotations; it never holds secret values.

## Wave 3 follow-ups

1. **Real action implementations** per plane (each is currently a stub):
   * `ci_cd`: PyGithub / python-gitlab / jenkinsapi adapters.
   * `infrastructure`: `terraform` / `pulumi` SDK shells (with state
     locking + plan/apply gating).
   * `secrets`: rotation policy engine driving `shared.secrets`.
   * `monitoring`: Prometheus / Grafana / Datadog / New Relic.
   * `alerting`: PagerDuty REST + Slack webhooks via `shared.notify`.
   * `deployment`: Argo CD / Spinnaker / Helm + feature flag system.
   * `database`: Flyway `migrate`, `pg_basebackup`/`pg_dump`, restore
     verification harness.
   * `networking`: Route53 / Cloud DNS / cert-manager renewal.
2. **Audit subsystem extension** to add `'devops'` (see "Relationships"
   above).
3. **Server tool discovery** — extend `shared.mcp.server.load_tools` to
   walk `devops/` too (or move `devops/mcp_tools.py` into
   `shared/mcp/tools/devops.py`).
4. **Provider catalog wiring** — pick per-project provider via V30
   `spine_provider_catalog` once that schema lands.
5. **Role charter cross-link** — point `shared/charters/devops.md` at
   this subsystem once both are landed.

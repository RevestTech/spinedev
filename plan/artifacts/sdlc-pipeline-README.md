# sdlc-pipeline.yaml — Spine's SDLC manifest

Pipeline-as-data. **No** phase, role, artifact template, gate type, or cost tier is
hardcoded in Spine source. Everything lives in `sdlc-pipeline.yaml`. Each org runs
its own SDLC shape without forking Spine.

Implements `STORY-1.7.1` in `docs/BACKLOG.md` and `FR-1` in `docs/PRD.md` REQ-INIT-1.

## Files in this directory

| File | Role |
|---|---|
| `sdlc-pipeline-schema.yaml`  | Schema definition (the *shape* a manifest must take). |
| `sdlc-pipeline-default.yaml` | Default manifest shipped with Spine — 11 canonical phases. |
| `sdlc-pipeline-README.md`    | This file. |

## Top-level sections

- **`version`** — monotonic integer. Bumped on every edit. Projects lock to the version
  current at project start (FR-8 / STORY-1.7.5).
- **`org_bundle`** — id of the org policy bundle that owns this manifest (INIT-2).
- **`phases`** — ordered array. Each phase carries `ownership` (plan / build / verify /
  orchestrator), `role_lead`, optional `role_support`, optional `swarm`, target
  `artifact`, `template`, `tier_default`, and a `gate`.
- **`project_types`** — per-type swarm overrides + intake-template pointer. Built-ins:
  `web-app`, `internal-tool`, `data-pipeline`, `mobile`, `api-service`, `cli-tool`.
  Custom types (`custom-*`) added by orgs via the override layer.
- **`tier_routing`** — per-phase tier defaults, escalation rules (synthesis → high,
  chitchat → low), and budget caps (FR-6).
- **`overrides`** — `team` and `project` scope-downs.
- **`capabilities`** — which capability gates edits to which section (FR-7). Default
  uses `can_modify_sdlc_pipeline` (granted via the org bundle, not by role title).
- **`audit`** — `rationale_required: true` is a const — rationale is **never** optional.

## Canonical phases (default)

Per `STORY-9.1.3`:

```
intake → plan_in_progress → plan_approved
       → build_in_progress → build_complete
       → verify_in_progress → verify_approved
       → acceptance → released → operate → retro
```

Ownership mapping:

| Phase                | Subsystem    |
|---|---|
| intake, plan_*       | plan         |
| build_*              | build        |
| verify_*             | verify       |
| acceptance, released, operate, retro | orchestrator |

## Override hierarchy (FR-7)

Most-specific wins. Each level can only edit sections the level above authorizes
via the `capabilities` map.

```
org bundle (baseline)  ─►  team override  ─►  project override
```

Example — a regulated bank's org bundle adds a `compliance_review` phase between
`plan_in_progress` and `plan_approved`, sets `min_approvals: 2` on `verify_approved`,
and revokes the team's ability to remove either. Teams may still tweak
`tier_routing` (`scope: team`) but cannot touch `phases` (`scope: org`).

## Customization examples

**1. Startup-lite — drop verify_approved gate to auto:**

```yaml
overrides:
  project:
    fast-prototype-x:
      phases:
        - id: verify_approved
          gate: { type: auto, approvers: [system], min_approvals: 0 }
```

**2. Design-led agency — insert a UX phase between TRD and Roadmap:**

```yaml
overrides:
  team:
    creative-team:
      phases_insert_after: plan_in_progress
      phases:
        - id: ux_review
          ownership: plan
          role_lead: ux
          artifact: Findings
          template: ux-review-v1
          tier_default: medium
          gate: { type: user_approval, approvers: [user], min_approvals: 1 }
```

**3. Add a new project type (`custom-fintech`):**

```yaml
overrides:
  team:
    fintech-team:
      project_types:
        custom-fintech:
          swarm_override: [researcher, engineer, qa, operator, datawright]
          intake_template: templates/intake/custom-fintech.yaml
```

## Edit policy (FR-8)

- Manifest is git-tracked in the org bundle repo + project repo.
- Every edit = a commit with author + timestamp + **required** rationale.
- In-flight projects pin to the version current when they started.
- Locked projects migrate to a new version only by explicit user action with diff preview.
- All gate decisions and router decisions flow to the audit log (INIT-3).

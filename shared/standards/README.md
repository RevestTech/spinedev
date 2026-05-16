# Spine Org Policy Bundles

> Implements `STORY-2.1.1` (bundle schema). See `docs/BACKLOG.md` INIT-2 EPIC-2.1 and PRD REQ-INIT-1 FR-7 for the why.

## What is an org bundle?

An **org policy bundle** is a YAML manifest that packages an enterprise's coding standards, security rules, banned patterns, cost ceilings, approved libraries, deployment targets, compliance flags, capability grants, SDLC-pipeline overrides, and Verify-phase configuration. It ships to every user's local Spine install and injects itself into role prompts (so the `engineer` knows the approved lib list) and into the auditor + TRON ISO agents (so banned patterns are *enforced*, not just documented). It is the enterprise-control differentiator Spine offers that no competitor matches.

## Bundle lifecycle

1. **Author** — `shared/standards/bundle-<id>.yaml` is edited by a principal holding `can_modify_sdlc_pipeline` or `can_override_security` (gated per `capabilities.grants`).
2. **Publish** — commit; the new `bundle_version` is monotonic so downstream installs detect drift.
3. **Install** — `spine install --org-bundle <url|path>` validates and pins (`STORY-2.1.2`, implementation pending).
4. **Inject** — role prompts and auditor checks receive the bundle slice relevant to their authority (`STORY-2.1.3`, `STORY-2.1.4`).
5. **Drift-detect** — local installs warn when the org has published a newer `bundle_version` (`STORY-2.1.5`).

## Override hierarchy

Three scopes; most-specific wins; each level only edits what the level above authorized.

```
org bundle (baseline)
  └── team bundle (inherits_from: org-bundle-id)
        └── project bundle (inherits_from: team-bundle-id)
```

- A **team** bundle may narrow but never widen org grants (e.g., it can require *more* reviewers, never *fewer*).
- A **project** bundle may further narrow team grants; it may add compliance tags but never remove a pack the org mandates.
- Capability checks run at edit-time; the validator rejects any edit that exceeds the editor's grants.

## Why `rationale` is required on every edit

Per `memory/spine_flexibility_principle.md` and `EPIC-1.7.4`: Spine's pipeline is data, not code, and every edit is a git commit with **author + timestamp + rationale**. The rationale field is *required*, not optional — it is the audit anchor that lets an SOC 2 / HIPAA reviewer reconstruct *why* policy changed, not just *that* it changed. Validators reject any bundle whose `identity.rationale` is missing or shorter than 8 characters.

## Relationship to TRON's Standards Hierarchy

TRON ships a Default → Company → Project standards hierarchy in `tron/standards/` with built-in reference packs at `tron/standards/packs/{soc2,hipaa,iso27001}_reference.json`. Per `EPIC-2.4` that whole subtree lifts to `shared/standards/` (this directory). The bundle schema designed here is *the* carrier for that hierarchy:

- `security.compliance_packs` enum values map 1:1 to TRON pack ids (`SOC_2_Type_II` → `soc2_reference`, `HIPAA` → `hipaa_reference`, `ISO_27001` → `iso27001_reference`). TRON's `summarize_pack_for_prompt()` consumes them unchanged.
- `verify_overrides` drives TRON's blueprint loader per `EPIC-2.4.5` (which ISO agents fire, whether cross-LLM is required, the calibration confidence cap).
- `security.iso_agents_required` is the hard floor; `verify_overrides.iso_agents_enabled` may add more; `iso_agents_disabled` may not remove anything in `iso_agents_required` (validator enforces).

## How to author a bundle

1. Copy one of the reference bundles (`bundle-startup-saas.yaml` or `bundle-regulated-enterprise.yaml`).
2. Set `identity.bundle_id`, `org_name`, and a meaningful `rationale`.
3. Edit only the sections your capability grants allow (the validator will tell you what's out of scope).
4. Run `spine bundle validate <path>` (implementation pending per `STORY-2.1.2`).
5. Commit; bump `bundle_version`; publish.

## Files in this directory

| File | Purpose |
|---|---|
| `bundle-schema.yaml`              | Structural schema (the source of truth for what bundles look like). |
| `bundle-startup-saas.yaml`        | Reference bundle for a small SaaS startup (light controls). |
| `bundle-regulated-enterprise.yaml`| Reference bundle for a regulated healthcare/finance org (strict controls). |
| `README.md`                       | This file. |

## Example: how a regulated bundle restricts engineer library choices

The `engineer` role prompt, at directive time, receives the bundle slice:

```yaml
approved_libs:
  python: [fastapi, pydantic, sqlalchemy, pytest, httpx, cryptography, anthropic]
banned_patterns:
  - pattern: "pickle\\.loads?\\("
    severity: critical
    message: "Insecure deserialization (pickle). Use JSON or msgpack with a typed schema."
```

If the engineer's output imports `requests` (not in `approved_libs.python`) or calls `pickle.loads`, the **auditor role** — which receives the same slice — emits a finding with the bundled `message` and refuses to advance the gate. Engineer cannot self-route around it; the only escape is an explicit grant edit by a principal holding `can_override_security` (which, in the regulated reference bundle, is set to `[]` — nobody).

That is the differentiator: **the org's policy is enforced inside the model loop, not as a CI afterthought**.

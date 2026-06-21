# Documentation routing for AI agents

**Goal:** spend tokens only on files that answer the task. Use this page as a **router**, not as secondary reading material—it's short on purpose.

---

## Read first (pick one path)

| Your task | Open these only | Stop |
|-----------|-----------------|------|
| **Most code changes** (bugfix, feature in `tron/`, tests) | [`project/TRD.md`](project/TRD.md) → jump to the module/route named in the task; then read **only** the referenced paths under `tron/` | Do **not** load [`BLUEPRINT.md`](BLUEPRINT.md) end-to-end; use it as a TOC if lost |
| **Product scope / “is this Done?”** | [`project/BRD.md`](project/BRD.md) + [`project/MASTER_PROPOSAL_TODO.md`](project/MASTER_PROPOSAL_TODO.md) | Skip [`architecture/`](architecture/) unless TRD sends you there |
| **Closing or changing a requirement** | Same PR must touch [`project/BRD.md`](project/BRD.md), [`project/TRD.md`](project/TRD.md), [`project/MASTER_PROPOSAL_TODO.md`](project/MASTER_PROPOSAL_TODO.md), [`project/REQUIREMENTS_TRACEABILITY.md`](project/REQUIREMENTS_TRACEABILITY.md) — see `.cursor/rules/tron-requirements-source-of-truth.mdc` | Don’t bulk-read [`REQUIREMENTS_TRACEABILITY.md`](project/REQUIREMENTS_TRACEABILITY.md); **grep** your requirement ID or keyword |
| **REST contract / HTTP shape** | [`reference/API_REFERENCE.md`](reference/API_REFERENCE.md) **sections you need** + live OpenAPI `/api/openapi.json` via codebase grep | Skip [`website/`](website/) |
| **CLI / scripts / Makefile** | [`reference/TOOLS_REFERENCE.md`](reference/TOOLS_REFERENCE.md) **sections you need** | Skip [`implementation/`](implementation/) |
| **Bring-up / local URLs** | Root [`README.md`](../README.md) quick start + [`operations/PORT_REFERENCE.md`](operations/PORT_REFERENCE.md) | Skip [`archive/`](archive/) |
| **Sandbox isolation / Layer 3** | [`security/SANDBOX_THREAT_MODEL.md`](security/SANDBOX_THREAT_MODEL.md); integration details → [`guides/sandbox/`](guides/sandbox/) **only if wiring code** | Skip [`archive/project-journals/`](archive/project-journals/) |
| **TLS / nginx / prod hardening checklist** | [`project/HARDENING_REVIEW_TODO.md`](project/HARDENING_REVIEW_TODO.md) + targeted [`security/TLS_RUNBOOK.md`](security/TLS_RUNBOOK.md) | Skip [`architecture/DATABASE_SCHEMA.md`](architecture/DATABASE_SCHEMA.md) unless DB-related |
| **Handoff into scanned application repos** | Repo root `.cursor/rules/tron-scanned-app-handoff.mdc` + `tron/agent_handoff_templates/README.md` | Ignore **most** of `docs/` for that workflow |
| **Verification pipeline concepts** | [`architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md`](architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md) **only if** TRD or user points there | Don’t stack-read all of [`architecture/`](architecture/) |

---

## Default token budget (heuristic)

1. **`docs/project/TRD.md`** — skim headings + jump to cited §; load **one** architecture doc only if TRD explicitly names it.
2. **Code** — read the smallest `tron/` surface that implements the behavior.
3. **Governance trio** — `BRD` / `MASTER_PROPOSAL_TODO` / `REQUIREMENTS_TRACEABILITY` only when scope or traceability rows change.

---

## Do **not** open by default (high noise / historical)

| Path | Why skip |
|------|----------|
| [`archive/`](archive/) — all subfolders | Historical proposals, journals, old reviews, HTML exports—not runtime truth |
| [`website/`](website/) | Presentation HTML/CSS; not the contract stack |
| [`implementation/`](implementation/) | Long-form planning; open **only** when task explicitly mentions testing strategy, risk register, phased UI plans |
| [`operations/RUNBOOKS.md`](operations/RUNBOOKS.md) | Very long; open **only** for incident/runbook tasks |
| [`BLUEPRINT.md`](BLUEPRINT.md) | Full index—use **grep** or scroll to **one** section when you need a path |

---

## Full map when lost

[`BLUEPRINT.md`](BLUEPRINT.md) lists every bucket—treat it like an index: **navigate, don’t ingest.**

Human-oriented tree + reading order: [`README.md`](README.md).

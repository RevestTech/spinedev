# Tron documentation blueprint

**Purpose:** Canonical index for **`docs/`**.

**AI agents:** use **`docs/AGENT_NAV.md`** first so you open only task-relevant files; use **this file** as a TOC (don’t load every linked document).

Humans: **`docs/README.md`** has the physical tree and generic reading order.

**Contract stack (requirements discipline):** Closing or deferring product scope still updates **`docs/project/BRD.md`**, **`docs/project/TRD.md`**, **`docs/project/MASTER_PROPOSAL_TODO.md`**, and **`docs/project/REQUIREMENTS_TRACEABILITY.md`** in one change — see **`.cursor/rules/tron-requirements-source-of-truth.mdc`**.

---

## Documentation tree (physical layout)

```
docs/
├── AGENT_NAV.md              ← AI routing: task → minimal docs (save tokens)
├── README.md                 ← Entry: ASCII tree + suggested reading order
├── BLUEPRINT.md              ← This index (roles + pointers)
├── project/                  ← Governance + requirements traceability (§1)
├── architecture/             ← Verification pipeline & platform design (§2)
├── implementation/           ← Deep planning reference (§3)
├── operations/               ← Runbooks, ports, audits-from-ops (§4)
├── security/                 ← TLS + sandbox threat model (§5)
├── reference/                ← API companion, tools, quick start, troubleshooting (§6)
├── guides/
│   └── sandbox/              ← Sandbox developer guides (§6)
├── integrations/             ← External CI samples (e.g. GitHub Action YAML)
├── website/                  ← Static documentation site (presentation layer)
└── archive/                  ← Historical proposal, journals, reviews, exports (§7)
```

---

## 1. Governance & scope (`docs/project/`)

| Document | Role |
|----------|------|
| **[`docs/project/BRD.md`](project/BRD.md)** | Business outcomes vs **`docs/archive/PROPOSAL.md`**; limitations and deferred items. |
| **[`docs/project/TRD.md`](project/TRD.md)** | Technical pointers: modules, interfaces, backlog references. |
| **[`docs/project/REQUIREMENTS_TRACEABILITY.md`](project/REQUIREMENTS_TRACEABILITY.md)** | Done / Partial / Deferred vocabulary and **verified-deliveries evidence index**. |
| **[`docs/project/MASTER_PROPOSAL_TODO.md`](project/MASTER_PROPOSAL_TODO.md)** | **Open backlog only** vs the proposal. |
| **[`docs/project/HARDENING_REVIEW_TODO.md`](project/HARDENING_REVIEW_TODO.md)** | Production readiness (TLS, CORS prod, sandbox, CI ops, Grafana) — **not** product scope. |
| **[`docs/project/ADR-002-compliance-certified-packs.md`](project/ADR-002-compliance-certified-packs.md)** | Deferred certified vendor packs; reference packs remain in scope. |

**[`docs/project/README.md`](project/README.md)** — short pointer into this blueprint.

---

## 2. Product & verification architecture (`docs/architecture/`)

| Document | Role |
|----------|------|
| **[`architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md`](architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md)** | Layered verification pipeline. |
| **[`architecture/AI_AGENT_ARCHITECTURE.md`](architecture/AI_AGENT_ARCHITECTURE.md)** | ISO agents and supervisor patterns. |
| **[`architecture/WEBSOCKET_ARCHITECTURE.md`](architecture/WEBSOCKET_ARCHITECTURE.md)** | Real-time audit progress / Socket.IO. |
| **[`architecture/DATABASE_SCHEMA.md`](architecture/DATABASE_SCHEMA.md)** | Relational schema reference (compare with Alembic for truth). |
| **[`architecture/DATABASE_GRAPH_DESIGN.md`](architecture/DATABASE_GRAPH_DESIGN.md)** | Graph / ltree dependency model. |

Root **[`README.md`](../README.md)** — narrative and quick start; must stay aligned with **`BRD.md`** / **`TRD.md`**.

---

## 3. Implementation depth (`docs/implementation/`)

Not the scope contract — useful for testing strategy, costs, risks, phased UI notes.

| Path | Role |
|------|------|
| **`implementation/`** | `TESTING_STRATEGY.md`, `COMPLETE_P0_P1_SOLUTIONS.md`, `COST_CONTROLS.md`, `RISK_REGISTER.md`, `BUSINESS_MODEL.md`, `ADMIN_UI_PHASED.md`. |

---

## 4. Operations & runbooks (`docs/operations/`)

| Document | Role |
|----------|------|
| **[`operations/PORT_REFERENCE.md`](operations/PORT_REFERENCE.md)** | Port map (13000+). |
| **[`operations/SCALING.md`](operations/SCALING.md)** | Horizontal scaling patterns. |
| **[`operations/RUNBOOKS.md`](operations/RUNBOOKS.md)** | Incident / ops procedures. |
| **[`operations/SLIS_SLOS.md`](operations/SLIS_SLOS.md)** | SLI / SLO framing. |
| **[`operations/HOW_TO_RUN_AUDIT.md`](operations/HOW_TO_RUN_AUDIT.md)** | Audit a **GitHub** repo via API (curl examples). |
| **[`operations/SCAN_LOCAL_FOLDER.md`](operations/SCAN_LOCAL_FOLDER.md)** | Local folder scan via **`scripts/scan_local_folder.sh`**. |

---

## 5. Security (`docs/security/`)

| Document | Role |
|----------|------|
| **[`security/TLS_RUNBOOK.md`](security/TLS_RUNBOOK.md)** | TLS / nginx hardening. |
| **[`security/SANDBOX_THREAT_MODEL.md`](security/SANDBOX_THREAT_MODEL.md)** | Sandbox isolation and syscall/seccomp posture. |

---

## 6. Reference & guides

### Human-maintained companions (`docs/reference/`)

| Document | Role |
|----------|------|
| **[`reference/API_REFERENCE.md`](reference/API_REFERENCE.md)** | REST narrative; **`/api/openapi.json`** is authoritative. |
| **[`reference/TOOLS_REFERENCE.md`](reference/TOOLS_REFERENCE.md)** | CLI, scripts, Makefile. |
| **[`reference/QUICK_START.md`](reference/QUICK_START.md)** | Fast contributor path. |
| **[`reference/TROUBLESHOOTING.md`](reference/TROUBLESHOOTING.md)** | Common failures. |

### Sandbox integration (`docs/guides/sandbox/`)

| Document | Role |
|----------|------|
| **[`guides/sandbox/SANDBOX_CLIENT.md`](guides/sandbox/SANDBOX_CLIENT.md)** | Client usage. |
| **[`guides/sandbox/SANDBOX_INTEGRATION_GUIDE.md`](guides/sandbox/SANDBOX_INTEGRATION_GUIDE.md)** | Wiring verification flows. |

Scanned-repo handoff: **`tron/agent_handoff_templates/README.md`**, **`.cursor/rules/tron-scanned-app-handoff.mdc`**.

### Integrations (`docs/integrations/`)

| Content | Role |
|---------|------|
| **[`integrations/github-action-pr-gate.yml`](integrations/github-action-pr-gate.yml)** | Sample GitHub Action for diff-mode audits. |
| **`integrations/README.md`** | Folder index. |

### Static site (`docs/website/`)

| Content | Role |
|---------|------|
| **`website/index.html`** (+ assets) | Marketing / narrative site. |
| **`website/README.md`** | How to serve; points to **`BLUEPRINT.md`** for contract truth. |

---

## 7. Historical & archival (`docs/archive/`)

| Location | Contents |
|----------|----------|
| **`archive/PROPOSAL.md`** | Original product proposal. |
| **`archive/project-journals/`** | Session logs, phased plans, superseded assessments — **`README.md`** indexes files. |
| **`archive/audit-reports/`** | Legacy HTML audit exports — **not** the handoff surface for scanned apps (use **`agent_handoff_path`**). |
| **`archive/reviews/`**, **`archive/responses/`**, **`archive/summaries/`** | External reviews and narratives. |
| **`archive/legacy-sql/`** | Pre-Alembic SQL snapshots. |

Superseded week-by-week plan: **`docs/archive/project-journals/IMPLEMENTATION_BLUEPRINT.md`**. Current engineering truth: **`docs/project/TRD.md`** + **`docs/project/REQUIREMENTS_TRACEABILITY.md`**.

---

## 8. CI workflows (repository root)

| Workflow | Role |
|----------|------|
| **`.github/workflows/ci.yml`** | Import smoke, pytest, ruff, bandit. |
| **`.github/workflows/prompt-regression.yml`** | Golden suite / ISO prompt regression. |

---

*When adding a new top-level folder under **`docs/`**, update **`docs/README.md`** and this file in the same change.*

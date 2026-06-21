# Tron `docs/` — structure and reading order

This directory is the **markdown and static-doc home** for Tron.

**AI agents (save tokens):** start with **[`AGENT_NAV.md`](AGENT_NAV.md)** — task → minimal files to open; lists what to skip.

Humans: **[`BLUEPRINT.md`](BLUEPRINT.md)** is the full index; **this file** is the folder tree and a generic reading order.

---

## Physical tree

```
docs/
├── AGENT_NAV.md              ← AI agents: task → minimal docs (save tokens)
├── README.md                 ← You are here
├── BLUEPRINT.md              ← Canonical index (links + section roles)
│
├── project/                  ← Governance + requirements traceability
│   ├── README.md
│   ├── BRD.md
│   ├── TRD.md
│   ├── REQUIREMENTS_TRACEABILITY.md
│   ├── MASTER_PROPOSAL_TODO.md
│   ├── HARDENING_REVIEW_TODO.md
│   └── ADR-002-compliance-certified-packs.md
│
├── architecture/             ← Pipeline, agents, DB, WebSocket
├── implementation/           ← Testing, costs, risks, phased plans (reference)
├── operations/               ← Ports, scaling, runbooks, SLOs, audit how-tos
├── security/                 ← TLS runbook, sandbox threat model
│
├── reference/                ← API companion, tools, quick start, troubleshooting
├── guides/
│   └── sandbox/              ← Sandbox client + integration guides
├── integrations/             ← Sample GitHub Action and future integration artifacts
├── website/                  ← Static HTML/CSS/JS documentation site
│
└── archive/                  ← Historical only
    ├── PROPOSAL.md
    ├── project-journals/
    ├── audit-reports/        ← Legacy HTML exports
    ├── reviews/
    ├── responses/
    ├── summaries/
    └── legacy-sql/
```

---

## Suggested reading order

1. **[`BLUEPRINT.md`](BLUEPRINT.md)** — where everything else lives.
2. **[`project/BRD.md`](project/BRD.md)** + **[`project/TRD.md`](project/TRD.md)** — what shipped and where it lives in code.
3. **[`project/REQUIREMENTS_TRACEABILITY.md`](project/REQUIREMENTS_TRACEABILITY.md)** — evidence rows and Done/Partial/Deferred rules.
4. **[`architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md`](architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md)** — verification layers.
5. **[`operations/PORT_REFERENCE.md`](operations/PORT_REFERENCE.md)** — local URLs and ports.
6. **[`reference/QUICK_START.md`](reference/QUICK_START.md)** or root **[`../README.md`](../README.md)** — bring up the stack.

**Production hardening checklist:** [`project/HARDENING_REVIEW_TODO.md`](project/HARDENING_REVIEW_TODO.md).

**Do not use** `archive/**` as the scope contract unless you are doing historical research.

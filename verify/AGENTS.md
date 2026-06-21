# Agent context — Tron

## Documentation map

**[`docs/AGENT_NAV.md`](docs/AGENT_NAV.md)** — **read this first**: task-based routing so you don’t load `archive/`, long runbooks, or the whole blueprint unless needed.

**[`docs/README.md`](docs/README.md)** — **`docs/`** folder tree and human reading order.

**[`docs/BLUEPRINT.md`](docs/BLUEPRINT.md)** — full index (TOC only—don’t read every linked doc).

## Where we left off

1. **`docs/project/BRD.md`** — business outcomes delivered vs proposal; **`docs/project/TRD.md`** — technical design pointers.
2. **`docs/project/MASTER_PROPOSAL_TODO.md`** — **open backlog only** vs **`docs/archive/PROPOSAL.md`** (proposal-aligned backlog currently empty; deferred ADR items summarized there).
3. **`docs/project/REQUIREMENTS_TRACEABILITY.md`** — Done / Partial / Deferred vocabulary and **verified deliveries** evidence table.
4. **`docs/project/HARDENING_REVIEW_TODO.md`** — deployment / third-party review backlog (TLS, CORS prod, sandbox hardening options, scaling docs, etc.); not the same as proposal feature scope.

**Product positioning (parallel ISO swarm + layered dependency/malicious-signal assurance):** root **`README.md`** bullets 8–9; **`tron/agents/manager.py`**, **`tron/services/threat_intel.py`**.

## Deploy and verify (Docker)

- Stack: `docker compose` from this directory (`docker-compose.yml`).
- **Browser UI:** nginx on `http://localhost:13080` (static files from `frontend/dist`).
- **API (direct):** `http://127.0.0.1:13000` (behind nginx at `/api/` when using 13080).

After completing a change that affects runtime behavior, **rebuild/redeploy proactively** per `.cursor/rules/tron-docker-rebuild-redeploy.mdc` (path → command table). Quick combined refresh for SPA + API: `make prod-up`.

## Auditing *other* applications (FCNow, client repos)

Tron-specific triage does **not** live in this repo’s `docs/audit-reports/` for those apps. **Automatic:** set **`agent_handoff_path`** on the Tron project (PUT `/api/projects/{id}`) to an **absolute** path the **audit worker** can write (typically a bind-mounted checkout); when an audit **completes**, Tron refreshes only the **managed** HTML-comment regions inside `TRON_POST_SCAN.md`, `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/tron-scan-followups.mdc` there (content outside those markers is preserved). It **appends** deduplicated run lines to app-repo **`tron.md`** for **Tron activity** unless **`TRON_HANDOFF_APPEND_TRON_MD`** is false (**`tron/services/scan_handoff_export.py`**). **Manual:** `python -m tron.cli audit handoff <AUDIT_UUID> --dest /path/to/app` or **`scripts/init_tron_scan_handoff.sh`**. See **`tron/agent_handoff_templates/README.md`** and **`.cursor/rules/tron-scanned-app-handoff.mdc`**.

## Project rules

See `.cursor/rules/` — especially `tron-requirements-source-of-truth.mdc`, `tron-implementation-discipline.mdc`, `tron-docker-rebuild-redeploy.mdc`, and `tron-scanned-app-handoff.mdc`. Canonical documentation map: **`docs/BLUEPRINT.md`**.

# Agent context — Tron

## Where we left off

1. **`docs/project/MASTER_PROPOSAL_TODO.md`** — living checklist; start at **“Current snapshot (where we left off)”** for scope + evidence paths.
2. **`docs/REQUIREMENTS_TRACEABILITY.md`** — Done / Partial / Deferred vocabulary and the **verified deliveries** table.
3. **Scanned-app handoff** (other repos): **`tron/services/scan_handoff_export.py`**, **`tron/agent_handoff_templates/README.md`**, **`.cursor/rules/tron-scanned-app-handoff.mdc`**.

## Deploy and verify (Docker)

- Stack: `docker compose` from this directory (`docker-compose.yml`).
- **Browser UI:** nginx on `http://localhost:13080` (static files from `frontend/dist`).
- **API (direct):** `http://127.0.0.1:13000` (behind nginx at `/api/` when using 13080).

After completing a change that affects runtime behavior, **rebuild/redeploy proactively** per `.cursor/rules/tron-docker-rebuild-redeploy.mdc` (path → command table). Quick combined refresh for SPA + API: `make prod-up`.

## Auditing *other* applications (FCNow, client repos)

Tron-specific triage does **not** live in this repo’s `docs/audit-reports/` for those apps. **Automatic:** set **`agent_handoff_path`** on the Tron project (PUT `/api/projects/{id}`) to an **absolute** path the **audit worker** can write (typically a bind-mounted checkout); when an audit **completes**, Tron refreshes only the **managed** HTML-comment regions inside `TRON_POST_SCAN.md`, `CLAUDE.md`, `AGENTS.md`, and `.cursor/rules/tron-scan-followups.mdc` there (content outside those markers is preserved). It **appends** deduplicated run lines to app-repo **`tron.md`** for **Tron activity** unless **`TRON_HANDOFF_APPEND_TRON_MD`** is false (**`tron/services/scan_handoff_export.py`**). **Manual:** `python -m tron.cli audit handoff <AUDIT_UUID> --dest /path/to/app` or **`scripts/init_tron_scan_handoff.sh`**. See **`tron/agent_handoff_templates/README.md`** and **`.cursor/rules/tron-scanned-app-handoff.mdc`**.

## Project rules

See `.cursor/rules/` — especially `tron-requirements-source-of-truth.mdc`, `tron-implementation-discipline.mdc`, `tron-docker-rebuild-redeploy.mdc`, and `tron-scanned-app-handoff.mdc`.

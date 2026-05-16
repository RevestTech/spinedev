# Tron → scanned application: handoff files (live in **that app’s repo**)

Tron runs audits **against** another repository (FCNow, internal services, etc.). **Triage and fixes belong in that repository’s root**, so Cursor / Claude / Codex opened on the app see the same context.

## Automatic handoff (worker writes after each audit)

When an audit **finishes**, Tron refreshes a **managed** region inside each of `TRON_POST_SCAN.md`, `.cursor/rules/tron-scan-followups.mdc`, `CLAUDE.md`, and `AGENTS.md` (delimited by `<!-- TRON_HANDOFF_MANAGED_BEGIN -->` / `<!-- TRON_HANDOFF_MANAGED_END -->`). Text **outside** those markers is left unchanged. Repo-root **`tron.md`** holds **Tron activity**: Tron **appends** a short deduplicated entry after each successful handoff (set **`TRON_HANDOFF_APPEND_TRON_MD=false`** to disable). Your team can add notes there too; Tron never rewrites existing lines.

1. Run **Alembic** through **`007`** so projects have **`agent_handoff_path`**.
2. **PUT** `/api/projects/{id}` with **`agent_handoff_path`**: an **absolute** path on the **worker host** (inside Docker, that is usually a **bind-mounted** checkout).
3. Keep **`TRON_AGENT_HANDOFF`** enabled (default **true**). Set **`TRON_UI_BASE`** on **tron-worker** so generated markdown shows your Tron UI URL.

**Docker example:** mount the app repo on the worker, then set `agent_handoff_path` to that mount:

```yaml
# tron-worker volumes (example)
- /Users/you/src/FCNow:/workspace/fcnow:rw
```

Then set `agent_handoff_path` to `/workspace/fcnow` for that Tron project.

---

This folder is **only templates** (also used by the worker). You can still use the **CLI** to export into any path the API can reach:

```bash
export TRON_API_URL='http://127.0.0.1:13000'   # or your API URL
export TRON_API_KEY='…'
export TRON_UI_BASE='http://localhost:13080'   # optional; shown in breadcrumbs

./.venv312/bin/python -m tron.cli audit handoff <AUDIT_UUID> --dest /absolute/path/to/scanned-app-repo
```

Shell-only fallback (empty snapshot table — you fill `TRON_POST_SCAN.md` by hand):

```bash
export TRON_AUDIT_ID='paste-audit-uuid-from-tron'
export TRON_UI_BASE='http://localhost:13080'
./scripts/init_tron_scan_handoff.sh /absolute/path/to/scanned-app-repo "Display Name"
```

## Files created in the **application** repo

| Path | Purpose |
|------|---------|
| `TRON_POST_SCAN.md` | Human + agent snapshot: severity counts, hot files, checklist, “what Done means” (managed block only is replaced each run). |
| `.cursor/rules/tron-scan-followups.mdc` | Cursor: always load instructions to read `TRON_POST_SCAN.md` and triage findings. |
| `CLAUDE.md` | Claude Code / Claude-friendly root context. |
| `AGENTS.md` | Generic agent + Codex-style root context (many tools load this). |
| `tron.md` | **Tron activity** log (append-only entries from Tron on each handoff) + optional team notes; created on first handoff if missing. |

Commit those files **in the application repository**, not in Tron.

## Do **not** store app-specific scan dumps under Tron’s `docs/`

Tron keeps **templates** and optional HTML exports if you choose; the **action queue** for FCNow lives next to FCNow’s code.

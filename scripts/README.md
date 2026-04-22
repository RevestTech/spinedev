# Scripts

| Script | Purpose |
|--------|---------|
| `scan_local_folder.sh` | Create a project/audit from a local directory (uses shared Docker scan mount). Run from repo root. |
| Stale queued audits | **`tron-api`** startup (compose: `TRON_RECONCILE_STALE_QUEUED_ON_STARTUP`, `TRON_STALE_QUEUED_AUDIT_MINUTES`) marks long-queued rows **failed**; or `python -m tron.cli audit reconcile-stale-queued` / `POST /api/audits/reconcile-stale-queued` (master); use `--dry-run` first. |
| `scan_repository.sh` | Full workflow against a Git URL. Run from repo root. |
| `monitor_audit.py` | Watch audit progress over WebSocket. |
| `test_websocket.py`, `test_e2e_websocket.py`, `test_ws_docker.py` | Ad-hoc WebSocket checks (development). |
| `dev-start.sh`, `preflight.sh`, `backup.sh`, `restore.sh`, `vault-init.sh` | Environment and ops helpers. |

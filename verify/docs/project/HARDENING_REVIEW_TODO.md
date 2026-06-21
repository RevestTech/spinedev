# Hardening & ops — third-party review backlog

**Source:** independent deep review (architecture, security, ops, docs), April 2026.  
**Purpose:** one actionable checklist. Items below were **re-validated against this repo** (not trusted blindly — see **Validation notes**).

**Authoritative product scope** remains **`docs/project/BRD.md`**, **`docs/project/TRD.md`**, **`docs/project/MASTER_PROPOSAL_TODO.md`** (open backlog only), and **`docs/project/REQUIREMENTS_TRACEABILITY.md`**. This file is **infrastructure and safety**, not feature delivery.

---

## Validation notes (findings we confirmed or rejected)

| Review claim | Validated? | Notes |
|--------------|------------|--------|
| **C1** No TLS in `nginx` — block commented, HTTP only on `80` | **Yes** | `config/nginx/nginx.conf` (TLS and redirect blocks commented). |
| **C2** AlertManager webhooks to `localhost:9095` with no listener in compose | **Yes** | `config/alertmanager/alertmanager.yml` — all receivers use that URL. |
| **C3** WebSocket `?token=` in query string (logs, history) | **Yes** | `tron/api/routes/ws.py` — cookie path preferred, query fallback remains. |
| **C4** No CI in repo | **Addressed** | **`.github/workflows/ci.yml`** runs app import smoke, **`pytest tests/unit tests/integration`** (strict markers), **ruff**, and **bandit** on every push/PR to main/master/develop. |
| **H1** Sandbox image root + docker socket | **Plausible** | `docker/Dockerfile.sandbox` / runtime — treat as high risk for multi-tenant. |
| **H2** gVisor in `.env` vs image | **Worth checking** | Verify host `daemon.json` / runtime vs `SANDBOX_RUNTIME` in `.env.example`. |
| **H3** `allow_credentials` + `allow_headers=["*"]` | **Partly** | Browsers can reject `*` with credentials; **fixed in tree:** explicit header list + `TRON_CORS_ORIGINS` (see `tron/api/config.py` + `main.py`). |
| **H4** API key in `localStorage` | **Fixed in tree** | SPA no longer persists API keys in `localStorage`; admin session uses httpOnly cookie — see P0 **H4** row and **`tests/unit/test_frontend_no_localstorage_api_key.py`**. |
| **H5** Single uvicorn worker in image | **Yes** | `docker/Dockerfile.api` / scale-out docs. |
| **H6** Grafana provisioning vs “live” SLOs | **Partly** | Dashboards exist; need proof of end-to-end alert path (ties to C2). |
| **H7** WebSocket max connection TOCTOU | **Yes** | **Fixed in tree:** `asyncio.Lock` + auth-before-cap ( `ws.py` ). |
| **M1** `FindingOutput.severity` is string, not enum | **No (current code)** | Pydantic model uses `SeverityLevel` enum (`tron/schemas/verification.py`). Unstructured JSON paths may still need coercion — lower priority. |
| **QAISO “commented out” / 3 agents** | **No (stale doc)** | `HONEST_ASSESSMENT.md` was wrong; `audit_executor.py` registers multiple ISOs including QA. **Doc superseded** with banner. |
| **Circuit breaker dead** | **No** | `tron/infra/llm/client.py` uses breakers. |
| **Temporal unused by default** | **No** | `TEMPORAL_ENABLED` default true; `audits.py` dispatches to Temporal. |

---

## P0 — Block external exposure (before public URL)

- [x] **TLS termination** — `config/nginx/nginx.conf` rewritten: real HTTPS `:443` vhost (TLS 1.2/1.3, AEAD-only ciphers, HSTS preload, `server_tokens off`, HTTP/2), port-80 redirect with ACME `/.well-known/acme-challenge/` passthrough and `/health` bypass for container healthcheck, `X-Forwarded-Proto` forwarded to upstream. Dev cert via `make dev-cert`. Runbook at `docs/security/TLS_RUNBOOK.md`. Regression tests in `tests/unit/test_nginx_tls_config.py`.
- [x] **Secret transport** — Implicit with TLS default + HSTS + `X-Forwarded-Proto` forwarding. Admin session cookie will be marked `Secure` as long as the proto header survives (it does — verified in `test_nginx_tls_config.py::test_x_forwarded_proto_is_set`).
- [x] **C2 — Alerting path** — `tron/api/routes/alerts.py` replaces the `localhost:9095` stub with a keyvault-backed Slack webhook receiver (`_resolve_slack_webhook_url`). `config/alertmanager/alertmanager.yml` points at `http://tron-api:8000/alerts*` on the docker network. 21 tests in `tests/unit/test_alerts_route.py`.
- [x] **C3 — WebSocket token** — `frontend/src/api.ts::connectAuditWs` no longer builds `?token=` URLs; WS auth rides the httpOnly admin session cookie via `ws.py::_authenticate_ws`. Regression guard in `tests/unit/test_frontend_no_localstorage_api_key.py::test_ws_connect_does_not_embed_api_key_in_query_string`.
- [x] **H4 — API key storage** — Removed `getApiKey`/`setApiKey`/localStorage from the SPA. One-shot `purgeLegacyApiKeyStorage()` scrubs stale keys from older builds on load. Settings UI now explains the cookie flow. `X-API-Key` still accepted server-side for CLI/automation. Regression guard asserts the pattern cannot come back.

---

## P1 — Hardening & SDLC (strongly recommended)

- [x] **CI pipeline** — `.github/workflows/ci.yml` now has **four required gates, no `continue-on-error`**: app-import smoke, `pytest tests/unit tests/integration -q --strict-markers` (2696 pass), `ruff check .`, `bandit -r tron/ -ll -ii`. Ruff config in `pyproject.toml` targets F/E7/E9/W6 (real bugs, not style). Bandit clean with 3 justified `# nosec` suppressions on the hardened sandbox mounts. **Remaining (follow-ups, not blockers):** container image scan (Trivy), branch protection.
- [ ] **CORS production** — Set `TRON_CORS_ORIGINS` to real origins in prod (comma-separated). Never use `*` with credentials (handled by explicit headers in app).
- [~] **H1 / sandbox** — **`sandbox_client._hardened_run_kwargs`** applies `user="65534:65534"` (nobody), `cap_drop=ALL`, `no-new-privileges`, `read_only=True`, capped tmpfs, `pids_limit=64`, `fsize`/`nofile` ulimits, `memswap=mem`, `ipc_mode=private`, fixed hostname, hard `network_mode` allowlist (`none` or `bridge` only). When a seccomp JSON exists at **`TRON_SANDBOX_SECCOMP`** (default path **`/etc/tron/sandbox/seccomp.json`**), **`security_opt`** includes **`seccomp=`** that file (**`tron/services/sandbox_client.py`** **`_build_security_opt`**); repository profile: **`config/sandbox/seccomp.json`**. **Default `docker-compose.yml` does not mount this file into `tron-sandbox`** — without a bind mount (or image bake-in), the client logs once and falls back to Docker’s default seccomp (see tests **`test_seccomp_missing_file_warns_and_falls_back`**). Threat model: **`docs/security/SANDBOX_THREAT_MODEL.md`**. Regression tests: **`tests/unit/test_sandbox_client_hardening.py`**, **`test_sandbox_server_request_validation.py`**. **Remaining:** operators mount/bake profile in prod; tighter syscall inventory vs workload; `--userns-remap`; rootless Docker or gVisor/Firecracker for full multi-tenant isolation.
- [ ] **H2 / gVisor** — Either install `runsc` in image and wire Docker, or remove misleading `SANDBOX_RUNTIME` default until verified.
- [~] **H5** — **`docs/operations/SCALING.md`** covers replica/worker scaling patterns; **`docker-compose.yml`** documents `--scale tron-worker`. **Remaining:** optional gunicorn+uvicorn workers for `tron-api`, explicit **`WORKERS`** env alignment to replicas.
- [ ] **H6** — Import Grafana dashboards + verify Prometheus jobs scrape `tron-api` / workers; one dashboard screenshot or “SLO query works” in runbook.
- [x] **M2** `agent_handoff_path` allowlist — `TRON_AGENT_HANDOFF_ALLOWED_ROOTS` (comma-separated absolute roots) is enforced at three layers: Pydantic validator on `ProjectCreate`/`ProjectUpdate`, the write-time check inside `_maybe_write_agent_handoff_inner`, and the shared primitive in `tron/services/path_safety.py` (`parse_allowed_roots` + `resolve_under_allowlist`). Fail-closed: empty allowlist → all non-empty paths refused. Symlinks-into-root that point out, `../` escapes, and relative paths all rejected. 12 tests in `tests/unit/test_agent_handoff_allowlist.py` + 18 in `test_path_safety.py`.
- [x] **M3** Symlink / repo read — `RepoScanner._read_files` now refuses symlinks outright (`is_symlink()` check, `lstat` for sizing) and reads through `open_no_follow` (O_NOFOLLOW + O_CLOEXEC) to close the TOCTOU window. `os.readlink` logged when refusing so forensics can see what a malicious repo pointed at. 6 tests in `tests/unit/test_repo_scanner_symlink_safety.py` cover symlink-to-outside, symlink-to-inside, sibling isolation, and a static guard that blocks `abs_path.read_text(` regressions in the scanner source.
- [x] **M4** LLM budget race — `tron/infra/llm/budget_reservation.py` wraps each LLM call in an atomic Redis `INCRBY`-check-`DECRBY` on integer cents. Two callers racing the same cap only see each other's increment and only the ones that fit proceed; overshoot callers get rolled back with `LLMBudgetExceeded`. `tron_llm_budget_require_redis` flag for strict fail-closed ops mode; process-local `asyncio.Lock` fallback when Redis is missing (closes the intra-process race; cross-process race is documented as a known degradation). 16 tests in `tests/unit/test_budget_reservation.py`, including a canonical 10-parallel-$3-reservations-vs-$10-cap assertion that exactly 3 succeed.

---

## P2 — Docs & repo hygiene (reduce reviewer confusion)

- [x] **Supersede stale `HONEST_ASSESSMENT.md`** — Banner points to **`BRD.md`** / **`TRD.md`** / **`MASTER_PROPOSAL_TODO`** + this file (done in repo).
- [x] **Archive journal-style docs** — moved from **`docs/project/`** to **`docs/archive/project-journals/`** with index **`docs/archive/project-journals/README.md`**; canonical map **`docs/BLUEPRINT.md`**; governance-only **`docs/project/README.md`**.
- [x] **README “current state”** — Link block under version line in **root `README.md`** (MASTER + traceability + this file).
- [ ] **admin-ui` fate** — Deprecate with date and removal milestone, or document “supported second UI” and CI for both.

---

## P3 — Nice-to-have / structural

- [ ] **M5** Split `AuditRun` wide table into identity vs metrics vs JSON blobs (ADR + migration).
- [ ] **M7** Memory limits in `docker-compose` for stateful services (Postgres, Redis) per environment sizing doc.

---

## Quick wins already landed in the repo (reference)

- **CORS** — `TRON_CORS_ORIGINS` (comma-separated); default dev origins unchanged. Explicit CORS `allow_headers` list (not `*`) in `tron/api/main.py` when `allow_credentials` is true.
- **H7** — `tron/api/routes/ws.py` — connection cap under `asyncio.Lock`, authentication before accept+register.
- **Stale doc** — `HONEST_ASSESSMENT.md` banner.
- **Alertmanager** — File-level comment: replace `localhost:9095` (see P0).
- **CI** — `.github/workflows/ci.yml` (app import + full unit/integration pytest + ruff + bandit).
- **Merge corruption** — `tron/prompts/defaults.py` had duplicate/broken `DEFAULT_TEMPLATES` tail (import error); removed stray lines.
- **FastAPI 204** — `tron/api/routes/findings.py` returns `Response(status_code=204)` for empty bodies (FastAPI assertion fix).

*Last updated: 2026-04-24 — all four P0s landed (TLS, Alertmanager, WS token, localStorage key); CI hardened with four required gates; sandbox runtime tightened with documented threat model; file-traversal P1s (M2 agent_handoff_path allowlist, M3 symlink-safe repo reads) closed with shared `path_safety.py` primitive; M4 LLM budget race closed via atomic Redis reservation.*

#!/usr/bin/env python3
"""
Live end-to-end HTTP checks against a running Tron stack (nginx or API).

Usage:
  # Through nginx (same-origin as built frontend):
  TRON_E2E_BASE_URL=http://127.0.0.1:13080 python scripts/e2e_live_smoke.py

  # With vault master key (KMac secret ``auth/master-key``) for full API path:
  export TRON_E2E_API_KEY='<your-master-key>'
  python scripts/e2e_live_smoke.py

Exits non-zero if any required step fails.
"""

from __future__ import annotations

import os
import sys
import uuid

import httpx


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    base = os.environ.get("TRON_E2E_BASE_URL", "http://127.0.0.1:13080").rstrip("/")
    api_key = os.environ.get("TRON_E2E_API_KEY", "").strip()
    timeout = float(os.environ.get("TRON_E2E_TIMEOUT", "30"))

    print(f"Base URL: {base}")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # ── Liveness / readiness (no API key) ─────────────────────────
        r = client.get(f"{base}/health")
        if r.status_code != 200:
            _fail(f"GET /health -> {r.status_code}: {r.text[:500]}")
        body = r.json()
        if body.get("status") != "ok":
            _fail(f"GET /health unexpected JSON: {body!r}")
        print("OK  GET /health")

        r = client.get(f"{base}/ready")
        if r.status_code != 200:
            _fail(f"GET /ready -> {r.status_code}: {r.text[:500]}")
        ready = r.json()
        if ready.get("status") not in ("ok", "ready", "degraded"):
            # API returns checks dict; accept common shapes
            if not isinstance(ready, dict):
                _fail(f"GET /ready unexpected body: {ready!r}")
        print("OK  GET /ready")

        if not api_key:
            print(
                "SKIP authenticated API steps (set TRON_E2E_API_KEY to vault master key "
                "``auth/master-key`` for project CRUD smoke)."
            )
            return

        headers = {"X-API-Key": api_key}

        r = client.get(f"{base}/api/projects", headers=headers)
        if r.status_code != 200:
            _fail(f"GET /api/projects -> {r.status_code}: {r.text[:800]}")
        print("OK  GET /api/projects")

        name = f"e2e-live-{uuid.uuid4().hex[:8]}"
        r = client.post(
            f"{base}/api/projects",
            headers=headers,
            json={"name": name, "description": "e2e_live_smoke.py"},
        )
        if r.status_code != 201:
            _fail(f"POST /api/projects -> {r.status_code}: {r.text[:800]}")
        project_id = r.json().get("id")
        if not project_id:
            _fail(f"POST /api/projects missing id: {r.text[:800]}")
        print(f"OK  POST /api/projects id={project_id}")

        r = client.get(f"{base}/api/projects/{project_id}", headers=headers)
        if r.status_code != 200:
            _fail(f"GET /api/projects/{{id}} -> {r.status_code}: {r.text[:800]}")
        print("OK  GET /api/projects/{id}")

        r = client.delete(f"{base}/api/projects/{project_id}", headers=headers)
        if r.status_code != 204:
            _fail(f"DELETE /api/projects/{{id}} -> {r.status_code}: {r.text[:800]}")
        print("OK  DELETE /api/projects/{id} (cleanup)")

    print("All live checks passed.")


if __name__ == "__main__":
    main()

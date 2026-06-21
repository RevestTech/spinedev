#!/usr/bin/env python3
"""Submit a feature request to an existing Spine project and dispatch engineer."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("BASE", "http://localhost:8090").rstrip("/")


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: spine-feature-request.py <project_uuid> <feature description>",
            file=sys.stderr,
        )
        return 2

    project_uuid = sys.argv[1].strip()
    feature = " ".join(sys.argv[2:]).strip()
    ts = datetime.now(timezone.utc).isoformat()

    project = _request("GET", f"/api/v2/projects/{project_uuid}/full")
    md = project.get("metadata") or {}
    name = project.get("name") or "project"
    transcript = md.get("intake_transcript") or []

    entry = {"ts": ts, "feature": feature, "status": "requested"}
    requests = list(md.get("feature_requests") or [])
    requests.append(entry)

    _request(
        "PATCH",
        f"/api/v2/projects/{project_uuid}",
        {
            "metadata": {
                "feature_requests": requests,
                "latest_feature_request": feature,
                "pipeline_mode": "autonomous",
                "gate_policy_preset": "full_auto",
                "pipeline_paused": False,
            },
        },
    )

    message = (
        f"We are in operate phase on an existing shipped app. "
        f"New feature request from the founder:\n\n{feature}\n\n"
        f"Confirm scope in one short paragraph, then reply with "
        f"[INTAKE_COMPLETE] on its own line so engineering can start."
    )
    intake_body = {
        "message": message,
        "transcript": [
            {"role": t.get("role", "user"), "content": t.get("content", "")}
            for t in transcript
            if isinstance(t, dict)
        ],
        "project_name": name,
        "project_type": str(project.get("project_type") or "feature"),
        "greenfield": bool(md.get("greenfield")),
    }
    chat = _request("POST", f"/api/v2/projects/{project_uuid}/intake/chat", intake_body)

    try:
        recovery = _request(
            "POST",
            f"/api/v2/projects/{project_uuid}/recovery/dispatch",
            {"action": "retry_feature", "note": f"feature: {feature[:120]}"},
        )
    except urllib.error.HTTPError as exc:
        recovery = {"error": exc.code, "detail": exc.read().decode("utf-8", errors="replace")[:300]}

    print(
        json.dumps(
            {
                "project_uuid": project_uuid,
                "feature": feature,
                "intake_done": chat.get("done"),
                "intake_reply_preview": (chat.get("reply") or "")[:200],
                "recovery": recovery,
            },
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

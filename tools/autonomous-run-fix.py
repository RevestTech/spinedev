#!/usr/bin/env python3
"""Monitor an autonomous project and apply safe auto-fixes."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = os.environ.get("BASE", "http://localhost:8090").rstrip("/")
REPO = Path(__file__).resolve().parents[1]


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _get(path: str) -> dict[str, Any]:
    return _request("GET", path)


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", path, body)


def _patch_metadata(project_uuid: str, patch: dict[str, Any]) -> None:
    _request("PATCH", f"/api/v2/projects/{project_uuid}", {"metadata": patch})


def _ack(decision_id: str) -> None:
    _post(f"/api/v2/decisions/{decision_id}/ack", {})


def _backfill_prd_draft(project: dict[str, Any], project_uuid: str) -> str | None:
    md = project.get("metadata") or {}
    if md.get("prd_draft"):
        return None
    if not md.get("prd_md"):
        return None

    sys.path.insert(0, str(REPO))
    from plan.artifacts.prd_v1 import PRDv1
    from plan.runtime.intake_runner import synthesize_prd_draft
    from plan.runtime.product_runner import intake_answers_from_transcript

    transcript = md.get("intake_transcript") or []
    intake_answers = intake_answers_from_transcript(transcript)
    profile = str(md.get("golden_path_profile") or "").lower()
    template = "web-app" if profile in ("website", "jellybeans") else "cli-tool"
    text = str(intake_answers.get("transcript_text") or md.get("description") or "")
    answers = {
        "target_users": "Users described in intake transcript",
        "primary_job": text[:1200] or f"Deliver {project.get('name', 'project')}",
        "must_should_could": (
            "MUST: meet success criteria from intake transcript\n"
            "SHOULD: ship within stated constraints"
        ),
        "auth_model": "none_public",
        "data_persistence": "Minimal — per intake scope",
        "hosting_target": "undecided",
        "rendering_model": "ssr_required" if template == "web-app" else "spa_acceptable",
        "realtime_needs": "no",
        "responsive_mobile": "responsive_basic",
        "analytics_and_seo": ["marketing_seo"] if template == "web-app" else ["none"],
    }
    prd = synthesize_prd_draft(
        project_uuid=project_uuid,
        project_name=str(project.get("name") or ""),
        template_name=template,
        answers=answers,
        actor="autonomous_run_fix",
    )
    prd_dump = prd.model_dump(mode="json")
    PRDv1.model_validate(prd_dump)
    _patch_metadata(project_uuid, {"prd_draft": prd_dump})
    return "backfill_prd_draft"


def _pending_for(project_uuid: str) -> list[dict[str, Any]]:
    listed = _get("/api/v2/decisions?status=pending")
    return [
        c for c in listed.get("items") or []
        if c.get("project_id") == project_uuid
        or (c.get("metadata") or {}).get("project_uuid") == project_uuid
    ]


def run_fix_pass(project_uuid: str) -> list[str]:
    actions: list[str] = []
    try:
        project = _get(f"/api/v2/projects/{project_uuid}/full")
        recovery = _get(f"/api/v2/projects/{project_uuid}/recovery")
    except urllib.error.URLError as exc:
        return [f"hub_unreachable: {exc}"]

    md = project.get("metadata") or {}
    phase = project.get("current_phase")

    fix = _backfill_prd_draft(project, project_uuid)
    if fix:
        actions.append(fix)
        if md.get("pipeline_paused"):
            _patch_metadata(project_uuid, {
                "pipeline_paused": False,
                "pipeline_pause_reason": None,
                "pipeline_pause_kind": None,
            })
            actions.append("unpause_pipeline")

    pending = _pending_for(project_uuid)
    for card in pending:
        kind = (card.get("metadata") or {}).get("kind")
        did = card.get("decision_id")
        if not isinstance(did, str):
            continue
        if kind == "role_failure":
            retry = (card.get("metadata") or {}).get("retry_action")
            _ack(did)
            actions.append(f"ack_role_failure:{did[:8]}")
            if retry:
                try:
                    _post(
                        f"/api/v2/projects/{project_uuid}/recovery/dispatch",
                        {"action": retry, "note": "autonomous-run-fix"},
                    )
                    actions.append(f"recovery:{retry}")
                except urllib.error.HTTPError as exc:
                    actions.append(f"recovery_failed:{exc.code}")
            elif md.get("prd_draft") and phase == "verify_approved":
                try:
                    _post(
                        f"/api/v2/projects/{project_uuid}/recovery/dispatch",
                        {"action": "resume", "note": "autonomous-run-fix auditor retry"},
                    )
                    actions.append("recovery:resume")
                except urllib.error.HTTPError as exc:
                    actions.append(f"resume_failed:{exc.code}")

    if not recovery.get("dispatch_in_flight"):
        rec = recovery.get("recommended_action")
        if recovery.get("stuck") and rec and rec != "retry_qa":
            try:
                _post(
                    f"/api/v2/projects/{project_uuid}/recovery/dispatch",
                    {"action": rec, "note": "autonomous-run-fix"},
                )
                actions.append(f"recovery:{rec}")
            except urllib.error.HTTPError as exc:
                actions.append(f"recovery_failed:{rec}:{exc.code}")

        if (
            phase == "released"
            and md.get("deploy_result")
            and not md.get("operate_started_at")
        ):
            try:
                _post(
                    f"/api/v2/projects/{project_uuid}/recovery/dispatch",
                    {"action": "retry_operate", "note": "autonomous-run-fix"},
                )
                actions.append("recovery:retry_operate")
            except urllib.error.HTTPError as exc:
                actions.append(f"retry_operate_failed:{exc.code}")

    return actions or ["noop"]


def main() -> int:
    uuid = (
        os.environ.get("PROJECT_UUID", "").strip()
        or (Path(os.environ["RUN_DIR"]) / "project_uuid").read_text().strip()
        if os.environ.get("RUN_DIR")
        else ""
    )
    if not uuid and len(sys.argv) > 1:
        uuid = sys.argv[1].strip()
    if not uuid:
        print("usage: autonomous-run-fix.py <project_uuid>", file=sys.stderr)
        return 2

    actions = run_fix_pass(uuid)
    print(json.dumps({"project_uuid": uuid, "actions": actions}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

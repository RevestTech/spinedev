#!/usr/bin/env python3
"""Golden path walkthrough — create spine_on_spine project and auto-ack cards."""

from __future__ import annotations

import json
import os
import sys
import time
import http.client
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAX_ITERATIONS = 50
MAX_INTAKE_TURNS = 12
POLL_SLEEP_SEC = 3.0

_INTAKE_PROFILES: dict[str, list[str]] = {
    "cli": [
        (
            "Greenfield CLI todo app in Python. Single-file MVP with add/list/complete "
            "commands. Solo developer on laptop."
        ),
        (
            "Success: run `python todo.py add \"buy milk\"` then `list` shows it; "
            "`done 1` marks complete. Stdlib only, optional JSON persistence."
        ),
        (
            "Out of scope: accounts, cloud sync, web UI, packaging to PyPI. "
            "Ship in one session today."
        ),
        (
            "No budget/deadline beyond today. Top risk is scope creep — keep one file. "
            "You have enough context — end intake with [INTAKE_COMPLETE] on its own line."
        ),
    ],
    "website": [
        (
            "Greenfield marketing website MVP. Stack: Next.js 14 App Router, TypeScript, "
            "Tailwind CSS. Solo founder, deployable with `npm run dev` on localhost."
        ),
        (
            "Success criteria: a responsive landing page with hero headline, three feature "
            "cards, and a primary CTA button linking to a real /contact page you also build. "
            "Include package.json with a dev script. Must bind to process.env.PORT."
        ),
        (
            "Out of scope: auth, CMS, backend API, payments, database. No external APIs. "
            "Keep to 5-12 files — ship in one session today."
        ),
        (
            "No budget beyond today. Top risk is scope creep — landing + contact only. "
            "You have enough context — end intake with [INTAKE_COMPLETE] on its own line."
        ),
    ],
}


def _intake_prompts() -> list[str]:
    profile = os.environ.get("GOLDEN_PATH_PROFILE", "cli").strip().lower()
    return _INTAKE_PROFILES.get(profile, _INTAKE_PROFILES["cli"])


def _fail(msg: str) -> None:
    print(f"[golden-path-walkthrough] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _request(
    base: str,
    method: str,
    path: str,
    body: dict | None = None,
) -> dict:
    url = f"{base.rstrip('/')}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _fail(f"{method} {path} -> HTTP {exc.code}: {detail[:500]}")
    except urllib.error.URLError as exc:
        _fail(f"{method} {path} -> {exc.reason}")
    except http.client.RemoteDisconnected as exc:
        _fail(f"{method} {path} -> connection dropped ({exc})")

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        _fail(f"{method} {path} returned non-JSON: {raw[:300]}")
        raise AssertionError


def _project_uuid_from_create(resp: dict) -> str:
    data = resp.get("data") or {}
    for key in ("project_uuid", "project_id"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    top = resp.get("project_uuid") or resp.get("project_id")
    if isinstance(top, str) and top:
        return top
    _fail(f"project create missing uuid: {json.dumps(resp)[:400]}")
    raise AssertionError


def _card_belongs_to_project(card: dict, project_uuid: str) -> bool:
    meta = card.get("metadata") or {}
    if meta.get("project_uuid") == project_uuid:
        return True
    pid = card.get("project_id")
    return isinstance(pid, str) and pid == project_uuid


def _pending_for_project(items: list[dict], project_uuid: str) -> list[dict]:
    return [c for c in items if _card_belongs_to_project(c, project_uuid)]


def _hub_global_dismiss_kinds() -> frozenset[str]:
    raw = os.environ.get(
        "GOLDEN_PATH_DISMISS_GLOBAL",
        "master_daily_briefing,host_deploy_instructions",
    )
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def _dismiss_hub_global_cards(base: str, items: list[dict]) -> int:
    """Ack hub-global cards (briefings, etc.) so the queue stays usable during long runs."""
    dismissed = 0
    for kind in _hub_global_dismiss_kinds():
        for card in items:
            meta = card.get("metadata") or {}
            if meta.get("kind") != kind:
                continue
            if card.get("project_id") or meta.get("project_uuid"):
                continue
            did = card.get("decision_id")
            if not isinstance(did, str) or not did:
                continue
            print(f"[golden-path-walkthrough] dismiss global {kind} {did[:8]}…")
            _request(base, "POST", f"/api/v2/decisions/{did}/ack")
            dismissed += 1
    return dismissed


def _fetch_pending_clean(base: str) -> list[dict]:
    listed = _request(base, "GET", "/api/v2/decisions?status=pending")
    items = listed.get("items") or []
    if _dismiss_hub_global_cards(base, items):
        listed = _request(base, "GET", "/api/v2/decisions?status=pending")
        items = listed.get("items") or []
    return items


def _current_phase(base: str, project_uuid: str) -> str:
    resp = _request(base, "GET", f"/api/v2/projects/{project_uuid}")
    snap = resp.get("status_snapshot") or {}
    data = snap.get("data") or snap
    phase = data.get("current_phase")
    if isinstance(phase, str) and phase:
        return phase
    full = _request(base, "GET", f"/api/v2/projects/{project_uuid}/full")
    phase = full.get("current_phase")
    if isinstance(phase, str) and phase:
        return phase
    _fail(f"could not read current_phase for {project_uuid}")
    raise AssertionError


def _run_intake(base: str, project_uuid: str, name: str) -> None:
    """Complete intake via chat turns until product role emits [INTAKE_COMPLETE]."""
    transcript: list[dict[str, str]] = []
    prompts = _intake_prompts()

    for turn in range(1, MAX_INTAKE_TURNS + 1):
        msg = prompts[turn - 1] if turn <= len(prompts) else (
            "Confirm intake is complete. Reply with [INTAKE_COMPLETE] on its own line "
            "so the system can draft the PRD."
        )
        body = {
            "message": msg,
            "transcript": transcript,
            "project_name": name,
            "project_type": "feature",
            "greenfield": False,
        }
        print(f"[golden-path-walkthrough] intake chat turn {turn} for {project_uuid}")
        resp = _request(base, "POST", f"/api/v2/projects/{project_uuid}/intake/chat", body)
        transcript = resp.get("transcript") or transcript
        if resp.get("done"):
            print("[golden-path-walkthrough] intake complete — waiting for PRD card")
            return
        reply = (resp.get("reply") or "")[:120]
        print(f"[golden-path-walkthrough] intake turn {turn} in progress — {reply!r}")

    _fail(f"intake did not complete within {MAX_INTAKE_TURNS} turns")


def _wait_for_kind(
    base: str,
    project_uuid: str,
    kind: str,
    *,
    timeout_sec: float = 180.0,
    poll_sec: float = 3.0,
) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        items = _fetch_pending_clean(base)
        pending = _pending_for_project(items, project_uuid)
        if any((c.get("metadata") or {}).get("kind") == kind for c in pending):
            return True
        time.sleep(poll_sec)
    return False


def _hub_ok(base: str) -> bool:
    try:
        url = f"{base.rstrip('/')}/healthz"
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def _wait_for_hub(base: str, *, timeout_sec: float = 600.0, poll_sec: float = 5.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _hub_ok(base):
            print(f"[golden-path-walkthrough] Hub ready at {base}")
            return
        time.sleep(poll_sec)
    _fail(f"Hub not ready at {base} after {timeout_sec}s")


def main() -> None:
    base = os.environ.get("BASE", "http://localhost:8090").rstrip("/")
    name = os.environ.get("PROJECT_NAME", "Golden Path Walkthrough")
    profile = os.environ.get("GOLDEN_PATH_PROFILE", "cli").strip().lower()
    if profile == "website" and name == "Golden Path Walkthrough":
        name = "Sample Website"
    if os.environ.get("GOLDEN_PATH_UNIQUE", "1") not in ("0", "false", "no"):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        name = f"{name} {stamp}"
    max_iter = int(os.environ.get("MAX_ITERATIONS", str(MAX_ITERATIONS)))
    sleep_sec = float(os.environ.get("POLL_SLEEP_SEC", str(POLL_SLEEP_SEC)))

    print(f"[golden-path-walkthrough] Hub: {base} (SPINE_HUB_DEV, no auth)")
    print(f"[golden-path-walkthrough] Project: {name} (profile={profile})")

    _wait_for_hub(base)

    create_body = {
        "name": name,
        "project_type": "feature",
        "spine_on_spine": True,
        "greenfield": False,
        "description": (
            "Sample marketing website — Next.js landing + contact (golden path website profile)."
            if profile == "website"
            else "Automated golden-path walkthrough — ack cards through gates."
        ),
    }
    resume_uuid = os.environ.get("PROJECT_UUID", "").strip()
    if resume_uuid:
        project_uuid = resume_uuid
        print(f"[golden-path-walkthrough] Resuming project_uuid={project_uuid}")
    else:
        created = _request(base, "POST", "/api/v2/projects", create_body)
        if created.get("status") == "error":
            _fail(f"project create failed: {json.dumps(created)[:400]}")
        project_uuid = _project_uuid_from_create(created)
        print(f"[golden-path-walkthrough] Created project_uuid={project_uuid}")

        # Ack intake briefing (no-op for chain) then run intake to seed PRD card.
        items = _fetch_pending_clean(base)
        for card in _pending_for_project(items, project_uuid):
            kind = (card.get("metadata") or {}).get("kind")
            if kind == "intake_briefing":
                did = card.get("decision_id")
                if isinstance(did, str):
                    print(f"[golden-path-walkthrough] ack intake_briefing {did}")
                    _request(base, "POST", f"/api/v2/decisions/{did}/ack")
                break

        _run_intake(base, project_uuid, name)
        if not _wait_for_kind(base, project_uuid, "prd_approval", timeout_sec=360.0):
            print(
                "[golden-path-walkthrough] WARN: prd_approval card not seen within timeout; "
                "continuing to ack whatever is pending"
            )

    acked_total = 0
    consecutive_empty = 0
    max_empty_polls = int(os.environ.get("MAX_EMPTY_POLLS", "120"))
    max_runtime_sec = float(os.environ.get("MAX_RUNTIME_SEC", str(60 * 60)))
    deadline = time.time() + max_runtime_sec
    iteration = 0
    while time.time() < deadline and iteration < max_iter:
        iteration += 1
        items = _fetch_pending_clean(base)
        pending = _pending_for_project(items, project_uuid)
        if not pending:
            consecutive_empty += 1
            phase = _current_phase(base, project_uuid)
            if consecutive_empty >= max_empty_polls:
                print(
                    f"[golden-path-walkthrough] iteration {iteration}: "
                    f"no pending cards after {max_empty_polls} polls — stopping"
                )
                break
            if iteration == 1 or consecutive_empty % 10 == 0:
                print(
                    f"[golden-path-walkthrough] iteration {iteration}: "
                    f"waiting for cards (phase={phase}, empty_poll={consecutive_empty})"
                )
            time.sleep(sleep_sec)
            continue

        consecutive_empty = 0
        for card in pending:
            decision_id = card.get("decision_id")
            kind = (card.get("metadata") or {}).get("kind", "?")
            title = card.get("title", decision_id)
            if kind in ("orchestrator_gap", "role_failure"):
                print(f"[golden-path-walkthrough] STOP: {kind} — {title}")
                phase = _current_phase(base, project_uuid)
                print(f"[golden-path-walkthrough] project_uuid={project_uuid}")
                print(f"[golden-path-walkthrough] current_phase={phase}")
                print(f"[golden-path-walkthrough] cards_acked={acked_total}")
                sys.exit(2)
            if not isinstance(decision_id, str) or not decision_id:
                continue
            print(
                f"[golden-path-walkthrough] iteration {iteration}: "
                f"ack {decision_id} ({kind}) — {title}"
            )
            _request(base, "POST", f"/api/v2/decisions/{decision_id}/ack")
            acked_total += 1

        time.sleep(sleep_sec)
    else:
        if iteration >= max_iter:
            print(
                f"[golden-path-walkthrough] stopped after {max_iter} iterations "
                f"({acked_total} cards acked)"
            )
        else:
            print(
                f"[golden-path-walkthrough] stopped after {max_runtime_sec}s runtime "
                f"({acked_total} cards acked)"
            )

    phase = _current_phase(base, project_uuid)
    print(f"[golden-path-walkthrough] project_uuid={project_uuid}")
    print(f"[golden-path-walkthrough] current_phase={phase}")
    print(f"[golden-path-walkthrough] cards_acked={acked_total}")


if __name__ == "__main__":
    main()

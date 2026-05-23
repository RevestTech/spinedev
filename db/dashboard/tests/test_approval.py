"""Pass I-3 self-test for the dashboard approval endpoint.

The real /api/engagements/<slug>/approve handler talks to Postgres via
fetch_engagement_detail(). For an in-process unit test we want to exercise
the *side-effect* parts (append-to-plan, write-conductor-directive,
emit-outbox-event) without a live DB. We do this by:

  1. Monkeypatching fetch_engagement_detail to return a synthetic
     engagement matching what the dashboard would normally read from the
     v_engagement_detail view.
  2. Pointing PROJECT_ROOT, ENGAGEMENTS_DIR, CONDUCTOR_DIRECTIVE, and
     INSTANCE_OUTBOX at a tmpdir so writes don't touch the real repo.
  3. Calling post_approve / post_reject directly and asserting on the
     resulting files.

Run:
    python3 db/dashboard/tests/test_approval.py
Exit 0 on success, non-zero with a diagnostic on the first failure.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
DASH = HERE.parent
REPO = DASH.parent.parent


def _load_serve():
    """Import db/dashboard/serve.py as a module without going through the
    package machinery (the file has a hyphen-prefixed sibling import that
    needs the same trick)."""
    spec = importlib.util.spec_from_file_location(
        "spine_serve_under_test", DASH / "serve.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    serve = _load_serve()

    with tempfile.TemporaryDirectory(prefix="spine-approval-test-") as td:
        tmp = Path(td)
        engagements_dir = tmp / "engagements"
        engagements_dir.mkdir(parents=True)
        slug = "test-plan-2026-05-12"
        eng_id = str(uuid.uuid4())

        eng_subdir = engagements_dir / slug
        eng_subdir.mkdir()
        plan_path = eng_subdir / "plan.md"
        plan_path.write_text(
            "# Plan — test-plan-2026-05-12\n\n"
            "## Role assignments\n"
            "- engineer: build the thing\n"
        )

        # Monkeypatch the module-level paths to point at the tmp dir.
        outbox = tmp / ".instance-outbox.jsonl"
        cond_dir = tmp / "teams" / "conductor" / "directive.md"

        serve.PROJECT_ROOT = tmp
        serve.ENGAGEMENTS_DIR = engagements_dir
        serve.CONDUCTOR_DIRECTIVE = cond_dir
        serve.INSTANCE_OUTBOX = outbox

        # Stub fetch_engagement_detail with a synthetic engagement row.
        synthetic = {
            "engagement_id": eng_id,
            "slug": slug,
            "title": "Test Plan",
            "client": "tester",
            "status": "awaiting_approval",
            "requirements_uri": f"engagements/{slug}/requirements.md",
            "req_uri": f"engagements/{slug}/REQ.md",
            "plan_uri": f"engagements/{slug}/plan.md",
        }

        def fake_fetch(s):
            return 200, {
                "engagement": dict(synthetic),
                "messages": [],
                "timeline": [],
                "cost_summary": None,
            }

        serve.fetch_engagement_detail = fake_fetch

        # ---- Case 1: post_approve mutates plan + writes directive + emits event
        status, body = serve.post_approve(slug, {"approver": "khash"})
        if status != 200:
            _fail(f"approve returned {status}: {body}")

        plan_text = plan_path.read_text()
        if "## Approved by: khash" not in plan_text:
            _fail(f"plan.md missing approval line:\n{plan_text}")

        if not cond_dir.is_file():
            _fail("conductor directive.md not created")
        cond_text = cond_dir.read_text()
        if eng_id not in cond_text:
            _fail("conductor directive missing engagement_id")
        if "## Engagement-Id:" not in cond_text:
            _fail("conductor directive missing '## Engagement-Id:' line")
        if slug not in cond_text:
            _fail("conductor directive missing slug")

        if not outbox.is_file():
            _fail("outbox not written")
        events = [
            json.loads(line)
            for line in outbox.read_text().splitlines()
            if line.strip()
        ]
        status_changes = [
            e for e in events
            if e.get("event_type") == "EngagementStatusChanged"
        ]
        if not status_changes:
            _fail(f"no EngagementStatusChanged event: {events}")
        last = status_changes[-1]
        if last.get("payload", {}).get("new_status") != "executing":
            _fail(f"unexpected payload: {last}")
        if last.get("engagement_id") != eng_id:
            _fail(f"engagement_id mismatch: {last}")
        print("approve case OK")

        # ---- Case 2: post_approve on non-awaiting_approval -> 409
        synthetic2 = dict(synthetic)
        synthetic2["status"] = "planning"
        serve.fetch_engagement_detail = lambda s: (200, {
            "engagement": dict(synthetic2),
            "messages": [], "timeline": [], "cost_summary": None,
        })
        status, body = serve.post_approve(slug, {"approver": "khash"})
        if status != 409:
            _fail(f"expected 409 for planning status, got {status}: {body}")
        print("approve wrong-status case OK")

        # ---- Case 3: post_reject appends + emits cancelled
        # Reset state: clear the outbox, restore awaiting_approval.
        outbox.write_text("")
        serve.fetch_engagement_detail = fake_fetch

        status, body = serve.post_reject(slug, {"reason": "needs more detail"})
        if status != 200:
            _fail(f"reject returned {status}: {body}")
        plan_text = plan_path.read_text()
        if "## Rejected: needs more detail" not in plan_text:
            _fail(f"plan.md missing rejection line:\n{plan_text}")
        events = [
            json.loads(line)
            for line in outbox.read_text().splitlines()
            if line.strip()
        ]
        status_changes = [
            e for e in events
            if e.get("event_type") == "EngagementStatusChanged"
        ]
        if not status_changes:
            _fail("no EngagementStatusChanged for reject")
        if status_changes[-1].get("payload", {}).get("new_status") != "cancelled":
            _fail(f"reject did not emit new_status=cancelled: {status_changes[-1]}")
        print("reject case OK")

        # ---- Case 4: short reject reason -> 400
        status, body = serve.post_reject(slug, {"reason": "no"})
        if status != 400:
            _fail(f"expected 400 for short reason, got {status}: {body}")
        print("reject short-reason case OK")

    print("test_approval OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

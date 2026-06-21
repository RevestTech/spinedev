#!/usr/bin/env python3
"""Black-box operate acceptance (G5 / SPINE-ACC-01).

Read-only Hub polling — does **not** edit customer workspaces under
``~/spine-projects/``. Use a disposable ``full_auto`` project or any operate-phase
project UUID.

Pass when:
  - Hub health OK
  - Project phase is ``operate``
  - ``GET /recovery`` responds within ``--recovery-max-ms``
  - Feature queue shows iteration progress (completed + requested/in_progress)

Exit 0 on pass, 1 on fail, 2 on usage/config error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 10.0,
) -> tuple[int, dict[str, Any] | None, str, float]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), body, elapsed_ms
            except json.JSONDecodeError:
                return resp.status, None, body, elapsed_ms
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload, body, elapsed_ms
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return 0, None, str(exc.reason), elapsed_ms


def _feature_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    requests = metadata.get("feature_requests")
    if not isinstance(requests, list):
        return {
            "total": 0,
            "completed": 0,
            "requested": 0,
            "in_progress": 0,
            "backlog": 0,
            "titles": {},
        }
    counts: dict[str, int] = {}
    titles: dict[str, list[str]] = {}
    for item in requests:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown").lower()
        title = str(item.get("title") or item.get("name") or "").strip()
        counts[status] = counts.get(status, 0) + 1
        titles.setdefault(status, [])
        if title:
            titles[status].append(title)
    return {
        "total": len(requests),
        "completed": counts.get("completed", 0),
        "requested": counts.get("requested", 0),
        "in_progress": counts.get("in_progress", 0),
        "backlog": counts.get("backlog", 0),
        "titles": titles,
    }


def _iteration_ok(summary: dict[str, Any]) -> bool:
    """At least one completed feature and pipeline still has work queued/active."""
    if summary["completed"] < 1:
        return False
    return summary["requested"] >= 1 or summary["in_progress"] >= 1 or summary["backlog"] >= 1


def evaluate(
    hub_url: str,
    project_uuid: str,
    *,
    recovery_max_ms: float,
    auth_header: str | None,
) -> dict[str, Any]:
    base = hub_url.rstrip("/")
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header

    checks: list[dict[str, Any]] = []
    overall_pass = True

    health_code, health, health_raw, health_ms = _fetch_json(f"{base}/healthz", timeout_s=5.0)
    health_ok = health_code == 200 and isinstance(health, dict) and health.get("ok") is True
    checks.append(
        {
            "name": "hub_health",
            "pass": health_ok,
            "detail": f"HTTP {health_code} in {health_ms:.0f}ms",
        }
    )
    overall_pass &= health_ok

    full_code, full, full_raw, full_ms = _fetch_json(
        f"{base}/api/v2/projects/{project_uuid}/full?include_artifacts=false",
        headers=headers,
        timeout_s=10.0,
    )
    project_ok = full_code == 200 and isinstance(full, dict)
    phase = str((full or {}).get("current_phase") or "")
    metadata = (full or {}).get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    feature_summary = _feature_summary(metadata)
    checks.append(
        {
            "name": "project_full",
            "pass": project_ok,
            "detail": f"HTTP {full_code} phase={phase!r} in {full_ms:.0f}ms",
            "feature_summary": feature_summary,
        }
    )
    overall_pass &= project_ok

    phase_ok = phase == "operate"
    checks.append({"name": "operate_phase", "pass": phase_ok, "detail": f"current_phase={phase!r}"})
    overall_pass &= phase_ok

    rec_code, rec, rec_raw, rec_ms = _fetch_json(
        f"{base}/api/v2/projects/{project_uuid}/recovery",
        headers=headers,
        timeout_s=10.0,
    )
    recovery_ok = rec_code == 200 and isinstance(rec, dict) and rec.get("ok") is True
    recovery_fast = rec_ms <= recovery_max_ms
    checks.append(
        {
            "name": "recovery_api",
            "pass": recovery_ok and recovery_fast,
            "detail": f"HTTP {rec_code} ok={rec.get('ok') if rec else None} {rec_ms:.0f}ms (max {recovery_max_ms:.0f}ms)",
            "stuck": rec.get("stuck") if rec else None,
            "reasons": rec.get("reasons") if rec else None,
            "dispatch_in_flight": rec.get("dispatch_in_flight") if rec else None,
        }
    )
    overall_pass &= recovery_ok and recovery_fast

    iteration_ok = _iteration_ok(feature_summary)
    checks.append(
        {
            "name": "feature_iteration",
            "pass": iteration_ok,
            "detail": (
                f"completed={feature_summary['completed']} "
                f"requested={feature_summary['requested']} "
                f"in_progress={feature_summary['in_progress']} "
                f"backlog={feature_summary['backlog']}"
            ),
        }
    )
    overall_pass &= iteration_ok

    if rec and rec.get("stuck") is True:
        checks.append(
            {
                "name": "not_stuck",
                "pass": False,
                "detail": f"recovery reports stuck: {rec.get('reasons')}",
            }
        )
        overall_pass = False
    else:
        checks.append({"name": "not_stuck", "pass": True, "detail": "recovery not stuck"})

    return {
        "pass": overall_pass,
        "hub_url": hub_url,
        "project_uuid": project_uuid,
        "checks": checks,
        "feature_summary": feature_summary,
        "operate_serve_url": metadata.get("operate_serve_url"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G5 black-box operate acceptance (read-only)")
    parser.add_argument("--project-uuid", required=True)
    parser.add_argument("--hub-url", default="http://localhost:8090")
    parser.add_argument("--recovery-max-ms", type=float, default=2000.0)
    parser.add_argument(
        "--auth-header",
        default="",
        help="Optional Authorization header (omit when SPINE_HUB_DEV=1)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll until pass or --timeout seconds",
    )
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    args = parser.parse_args(argv)

    auth = args.auth_header.strip() or None
    deadline = time.time() + args.timeout if args.watch else time.time()

    while True:
        result = evaluate(
            args.hub_url,
            args.project_uuid,
            recovery_max_ms=args.recovery_max_ms,
            auth_header=auth,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = "PASS" if result["pass"] else "FAIL"
            print(f"[operate-blackbox] {status} project={args.project_uuid}")
            for check in result["checks"]:
                mark = "ok" if check["pass"] else "FAIL"
                print(f"  - {check['name']}: {mark} — {check['detail']}")

        if result["pass"]:
            return 0
        if not args.watch or time.time() >= deadline:
            return 1
        time.sleep(max(args.interval, 5.0))


if __name__ == "__main__":
    raise SystemExit(main())

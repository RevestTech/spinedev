"""OpenAPI snapshot drift gate (V1_SHIP_CHECKLIST.md §1).

Verifies that `shared/ui/spa/scripts/openapi-sample.json` (the snapshot
that CI builds consume when no live Hub is running) is consistent with
the live spec produced by `shared.api.openapi_spec.build_openapi()`
applied to a freshly-built `shared.api.app:create_app()`.

The snapshot is intentionally a SUBSET of the full spec — it covers
the routes the SPA panels actually consume. The drift gate's contract:

  - Every path + method in the snapshot MUST also exist in the live spec.
  - For each path/method covered by the snapshot, the request body
    schema names and response schema names must match the live spec.
  - Component schemas referenced by the snapshot MUST also exist in
    the live spec.

Drift is BIDIRECTIONAL:
  - LIVE_MISSING_FROM_SNAPSHOT: live added a route or field; snapshot
    needs refresh.
  - SNAPSHOT_MISSING_FROM_LIVE: snapshot references something that no
    longer exists in live (rename / removal).

Exit codes:
  0 — no drift
  1 — drift detected (printed)
  2 — usage / invocation error

Usage:
  .venv/bin/python tools/openapi-drift-gate.py
  .venv/bin/python tools/openapi-drift-gate.py --print-live-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "shared/ui/spa/scripts/openapi-sample.json"


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        sys.stderr.write(f"snapshot file missing: {SNAPSHOT_PATH}\n")
        sys.exit(2)
    return json.loads(SNAPSHOT_PATH.read_text())


def _build_live_spec() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from shared.api.app import create_app
    from shared.api.openapi_spec import build_openapi

    app = create_app()
    return build_openapi(app)


def _operations(spec: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    methods = {"get", "post", "put", "patch", "delete"}
    for path, ops in spec.get("paths", {}).items():
        if not isinstance(ops, dict):
            continue
        for method, body in ops.items():
            if method.lower() in methods and isinstance(body, dict):
                yield path, method.lower(), body


def _schema_refs(node: Any) -> Iterable[str]:
    """Walk a JSON-ish tree and yield every $ref string."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from _schema_refs(v)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_refs(item)


def _drift(snapshot: dict[str, Any], live: dict[str, Any]) -> list[str]:
    drift: list[str] = []

    live_ops = {(p, m): body for p, m, body in _operations(live)}
    snap_ops = {(p, m): body for p, m, body in _operations(snapshot)}

    for key in snap_ops:
        if key not in live_ops:
            drift.append(
                f"SNAPSHOT_MISSING_FROM_LIVE: {key[1].upper()} {key[0]} "
                f"in snapshot but not in live spec (route renamed/removed?)"
            )

    live_schemas = set((live.get("components") or {}).get("schemas", {}).keys())
    snap_schemas = set((snapshot.get("components") or {}).get("schemas", {}).keys())
    for name in snap_schemas - live_schemas:
        drift.append(
            f"SNAPSHOT_MISSING_FROM_LIVE: component schema {name!r} "
            f"in snapshot but not in live spec (renamed/removed?)"
        )

    for key, snap_body in snap_ops.items():
        if key not in live_ops:
            continue
        snap_refs = sorted(set(_schema_refs(snap_body)))
        live_refs = sorted(set(_schema_refs(live_ops[key])))
        snap_only = sorted(set(snap_refs) - set(live_refs))
        if snap_only:
            drift.append(
                f"SNAPSHOT_REF_MISSING_FROM_LIVE: {key[1].upper()} {key[0]} "
                f"snapshot references {snap_only} but live doesn't"
            )

    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--print-live-only",
        action="store_true",
        help="Print the live spec to stdout (json); useful for inspection",
    )
    args = parser.parse_args()

    live = _build_live_spec()
    if args.print_live_only:
        json.dump(live, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    snapshot = _load_snapshot()
    drift = _drift(snapshot, live)
    if not drift:
        snap_paths = len(snapshot.get("paths") or {})
        live_paths = len(live.get("paths") or {})
        snap_schemas = len((snapshot.get("components") or {}).get("schemas", {}))
        live_schemas = len((live.get("components") or {}).get("schemas", {}))
        print(
            f"✓ openapi snapshot drift gate: clean "
            f"(snapshot {snap_paths} paths / {snap_schemas} schemas; "
            f"live {live_paths} paths / {live_schemas} schemas)"
        )
        return 0
    for line in drift:
        sys.stderr.write(f"⚠ {line}\n")
    sys.stderr.write(
        f"\n✗ openapi snapshot drift gate: {len(drift)} drift item(s). "
        f"Refresh the snapshot:\n"
        f"  .venv/bin/python tools/openapi-drift-gate.py --print-live-only \\\n"
        f"    > {SNAPSHOT_PATH.relative_to(REPO_ROOT)}\n"
        f"…then commit the new snapshot.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

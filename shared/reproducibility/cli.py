"""Spine reproducibility CLI (STORY-3.2.2).

Subcommands:
    spine replay <manifest> [--dry-run] [--force-drift] [--override-model X]
    spine replay capture <directive_id> [--out PATH] [--directive-text STR]
    spine replay diff <manifest_a> <manifest_b>
    spine replay history <project_id>   list manifests captured for project
    spine replay validate <manifest>    drift check without dispatch

Exit codes (frozen):
    0  success
    1  replay failed
    2  drift detected (validate fail / --strict on replay)
    3  db / IO error
    64 unknown subcommand
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from shared.reproducibility.diff import diff_manifests
from shared.reproducibility.manifest import (MANIFESTS_ROOT, capture_manifest,
                                             default_manifest_path,
                                             load_manifest, save_manifest)
from shared.reproducibility.replay import (ReplayPlan, replay,
                                           validate_against_current)

EXIT_OK, EXIT_FAIL, EXIT_DRIFT, EXIT_ERROR, EXIT_UNKNOWN = 0, 1, 2, 3, 64


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, sort_keys=True))


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        m = capture_manifest(args.directive_id,
                             directive_text=args.directive_text or "",
                             db_url=args.db_url)
    except Exception as e:  # noqa: BLE001
        print(f"capture failed: {e}", file=sys.stderr); return EXIT_ERROR
    out = Path(args.out) if args.out else default_manifest_path(
        m.project_id, args.directive_id)
    save_manifest(m, out)
    _print({"manifest_uuid": str(m.manifest_uuid), "saved_to": str(out)})
    return EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    try:
        m = load_manifest(Path(args.manifest))
    except Exception as e:  # noqa: BLE001
        print(f"load failed: {e}", file=sys.stderr); return EXIT_ERROR
    result = replay(m, dry_run=args.dry_run, force_drift=args.force_drift,
                    override_model=args.override_model)
    _print(json.loads(result.model_dump_json()))
    if isinstance(result, ReplayPlan):
        return EXIT_OK
    if not result.success:
        return EXIT_FAIL
    return EXIT_DRIFT if (args.strict and result.drift_summary) else EXIT_OK


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        a, b = load_manifest(Path(args.manifest_a)), load_manifest(Path(args.manifest_b))
    except Exception as e:  # noqa: BLE001
        print(f"load failed: {e}", file=sys.stderr); return EXIT_ERROR
    d = diff_manifests(a, b)
    _print(json.loads(d.model_dump_json()))
    return EXIT_OK if d.is_reproducible else EXIT_DRIFT


def cmd_history(args: argparse.Namespace) -> int:
    project_dir = MANIFESTS_ROOT / args.project_id
    if not project_dir.is_dir():
        _print({"project_id": args.project_id, "manifests": []})
        return EXIT_OK
    rows = []
    for p in sorted(project_dir.glob("*.yaml")) + sorted(project_dir.glob("*.json")):
        try:
            m = load_manifest(p)
            rows.append({"path": str(p), "directive_id": m.directive_id,
                         "phase": m.phase, "created_at": m.created_at.isoformat(),
                         "model_id": m.runtime.model_id})
        except Exception as e:  # noqa: BLE001
            rows.append({"path": str(p), "error": str(e)})
    _print({"project_id": args.project_id, "manifests": rows})
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        m = load_manifest(Path(args.manifest))
    except Exception as e:  # noqa: BLE001
        print(f"load failed: {e}", file=sys.stderr); return EXIT_ERROR
    reproducible, drift = validate_against_current(m)
    _print({"reproducible": reproducible, "drift": drift})
    return EXIT_OK if reproducible else EXIT_DRIFT


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine replay",
                                description="Reproducible-build manifest tooling.")
    p.add_argument("--db-url", default=None,
                   help="Postgres URL (defaults to $SPINE_DB_URL).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("replay", help="Replay a captured manifest.")
    pr.add_argument("manifest")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--force-drift", action="store_true",
                    help="Proceed even if critical drift detected.")
    pr.add_argument("--override-model", default=None)
    pr.add_argument("--strict", action="store_true",
                    help="Exit 2 on ANY drift, even on success.")
    pr.set_defaults(func=cmd_replay)

    pc = sub.add_parser("capture", help="Capture a manifest for a directive.")
    pc.add_argument("directive_id")
    pc.add_argument("--out", default=None)
    pc.add_argument("--directive-text", default="")
    pc.set_defaults(func=cmd_capture)

    pd = sub.add_parser("diff", help="Diff two manifests structurally.")
    pd.add_argument("manifest_a")
    pd.add_argument("manifest_b")
    pd.set_defaults(func=cmd_diff)

    ph = sub.add_parser("history", help="List manifests for a project_uuid.")
    ph.add_argument("project_id")
    ph.set_defaults(func=cmd_history)

    pv = sub.add_parser("validate", help="Check current state vs manifest.")
    pv.add_argument("manifest")
    pv.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AttributeError:
        return EXIT_UNKNOWN


if __name__ == "__main__":
    sys.exit(main())

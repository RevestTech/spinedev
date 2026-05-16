"""cli.py — `spine pipeline {show|edit|migrate|history|lock-status|diff}`.

Implements the operator-facing surface for `EPIC-1.7` (`docs/BACKLOG.md`).
Each subcommand wraps the corresponding library entrypoint:
  - show          → manifest_loader.load_pipeline()
  - edit          → versioning.commit_pipeline_edit()  (rationale REQUIRED)
  - history       → versioning.pipeline_history()
  - lock-status   → project_lock.get_locked_pipeline() / is_pipeline_drifted()
  - migrate       → project_lock.migrate_locked_project()
  - diff          → in-process section diff between two manifest YAMLs

Style + exit-codes mirror `shared/standards/install_bundle.sh`:
  0 ok / 2 bad-args / 3 validation / 4 io / 5 capability denied.
JSON on stdout, ISO-8601 prefixed logs on stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .capability_checker import CapabilityDenied, list_grants
from .manifest_loader import PipelineManifest, load_pipeline
from .project_lock import (
    get_locked_pipeline, is_pipeline_drifted, migrate_locked_project,
)
from .versioning import commit_pipeline_edit, compute_pipeline_version, pipeline_history


def _log(level: str, msg: str) -> None:
    print(f"{datetime.utcnow().isoformat()}Z pipeline-cli {level} {msg}", file=sys.stderr)


def _ok(payload: dict[str, Any]) -> int:
    print(json.dumps({"ok": True, **payload}, default=str)); return 0


def _err(code: str, message: str, exit_code: int) -> int:
    print(json.dumps({"ok": False, "code": code, "message": message}), file=sys.stderr)
    _log("ERROR", f"{code}: {message}"); return exit_code


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        m = load_pipeline(project_id=args.project, bundle_id=args.bundle)
    except Exception as e: return _err("load_failed", str(e), 4)
    return _ok({"resolved_version": m.resolved_version, "inheritance_chain": m.inheritance_chain,
                "phases": [p.get("id") for p in m.phases], "grants": list_grants(m),
                "manifest": m.model_dump()})


def _cmd_edit(args: argparse.Namespace) -> int:
    path = Path(args.manifest_path)
    if not path.exists(): return _err("missing", f"manifest not found: {path}", 4)
    try: new_content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e: return _err("yaml_parse_error", str(e), 3)
    pipeline = load_pipeline()  # capability check against the currently active manifest
    try:
        result = commit_pipeline_edit(path, new_content, actor=args.actor,
                                      rationale=args.rationale, pipeline_for_capcheck=pipeline)
    except CapabilityDenied as e: return _err("capability_denied", str(e), 5)
    except Exception as e: return _err("commit_failed", str(e), 4)
    return _ok({"new_version": result.new_version, "commit_sha": result.commit_sha,
                "file": str(result.file_path)})


def _cmd_history(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else None
    if path is None:
        from .manifest_loader import DEFAULT_PIPELINE_PATH
        path = DEFAULT_PIPELINE_PATH
    try: edits = pipeline_history(path)
    except Exception as e: return _err("history_failed", str(e), 4)
    return _ok({"file": str(path),
                "edits": [{"commit_sha": e.commit_sha, "actor": e.actor,
                           "rationale": e.rationale, "timestamp": e.timestamp.isoformat(),
                           "subject": e.subject} for e in edits]})


def _cmd_lock_status(args: argparse.Namespace) -> int:
    if not args.project_id: return _err("bad_args", "project_id required", 2)
    try:
        locked = get_locked_pipeline(args.project_id)
        drifted = is_pipeline_drifted(args.project_id)
    except Exception as e: return _err("lookup_failed", str(e), 4)
    return _ok({"project_id": args.project_id, "locked_version": locked.resolved_version,
                "phases": [p.get("id") for p in locked.phases], "drifted": drifted})


def _cmd_migrate(args: argparse.Namespace) -> int:
    if not args.confirm: return _err("bad_args", "--confirm required (FR-8: explicit action)", 2)
    target = args.to
    new_manifest = (load_pipeline(project_id=args.project_id) if target == "latest"
                    else PipelineManifest(**yaml.safe_load(Path(target).read_text(encoding="utf-8"))))
    try:
        result = migrate_locked_project(args.project_id, new_manifest,
                                        actor=args.actor, rationale=args.rationale)
    except CapabilityDenied as e: return _err("capability_denied", str(e), 5)
    except Exception as e: return _err("migrate_failed", str(e), 4)
    return _ok({"project_id": result.project_id, "from_version": result.from_version,
                "to_version": result.to_version, "diff": result.diff})


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        a = PipelineManifest(**yaml.safe_load(Path(args.version_a).read_text(encoding="utf-8")))
        b = PipelineManifest(**yaml.safe_load(Path(args.version_b).read_text(encoding="utf-8")))
    except Exception as e: return _err("io", str(e), 4)
    from .project_lock import _diff_manifests
    return _ok({"a": compute_pipeline_version(a), "b": compute_pipeline_version(b),
                "diff": _diff_manifests(a, b)})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spine pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("--project"); s.add_argument("--bundle"); s.set_defaults(fn=_cmd_show)
    e = sub.add_parser("edit"); e.add_argument("manifest_path")
    e.add_argument("--actor", required=True); e.add_argument("--rationale", required=True); e.set_defaults(fn=_cmd_edit)
    h = sub.add_parser("history"); h.add_argument("--manifest"); h.set_defaults(fn=_cmd_history)
    ls = sub.add_parser("lock-status"); ls.add_argument("project_id", nargs="?"); ls.set_defaults(fn=_cmd_lock_status)
    m = sub.add_parser("migrate"); m.add_argument("project_id")
    m.add_argument("--to", required=True); m.add_argument("--actor", required=True)
    m.add_argument("--rationale", required=True); m.add_argument("--confirm", action="store_true"); m.set_defaults(fn=_cmd_migrate)
    d = sub.add_parser("diff"); d.add_argument("version_a"); d.add_argument("version_b"); d.set_defaults(fn=_cmd_diff)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

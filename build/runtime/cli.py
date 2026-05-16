"""CLI entry point for the ``spine kg`` daemon-side helpers (EPIC-7.3).

Subcommands
-----------
``enrich <artifact.json> [--mode fill|verify|both] [--repo <path>] [--in-place]``
    Populate ``BuildArtifact.kg_impact`` via the role's KG hook.
``find-owner <target> [--repo <path>] [--project-id <id>]``
    Operator helper: print parsed ``who_owns`` rows as JSON.
``register-output <output_path> [--source-nodes id1,id2,...]``
    Datawright helper: insert Document node + PRODUCED_BY edges.
``pre-build-check <directive.json>``
    Dry-run summary: which KG hooks *would* fire for this directive.

Invoked from ``Makefile.v2``, ``v1_report_collector.sh``, and ad-hoc shells.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from shared.schemas.build.build_artifact import BuildArtifact

from build.runtime.enrich_artifact import enrich_build_artifact
from build.runtime.kg_caller import DatawrightKGHook, OperatorKGHook


def _dpid() -> str: return os.environ.get("SPINE_PROJECT_ID", "unknown")
def _drepo() -> str: return os.environ.get("SPINE_REPO", os.getcwd())


def _cmd_enrich(args: argparse.Namespace) -> int:
    path = Path(args.artifact)
    artifact = BuildArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    artifact = enrich_build_artifact(artifact, repo=args.repo, mode=args.mode)
    out = artifact.model_dump(mode="json")
    if args.in_place:
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        sys.stderr.write(f"[ok] enriched {path} (kg_impact={len(artifact.kg_impact)})\n")
    else:
        json.dump(out, sys.stdout, indent=2); sys.stdout.write("\n")
    return 0


def _cmd_find_owner(args: argparse.Namespace) -> int:
    repo = args.repo or _drepo()
    hook = OperatorKGHook(project_id=args.project_id or _dpid())
    owners = hook.find_owner(args.target, repo=repo)
    payload: dict[str, Any] = {"target": args.target,
        "owners": [o.model_dump() for o in owners]}
    warn = hook.warn_if_no_owner(args.target, repo=repo)
    if warn:
        payload["warning"] = warn
    json.dump(payload, sys.stdout, indent=2); sys.stdout.write("\n")
    return 0 if owners else 2  # exit 2 = "no owner" so shells can branch


def _cmd_register_output(args: argparse.Namespace) -> int:
    sources = [s.strip() for s in (args.source_nodes or "").split(",") if s.strip()]
    hook = DatawrightKGHook(project_id=args.project_id or _dpid())
    node_id = hook.register_output(args.output_path, source_data_nodes=sources,
        repo=args.repo or _drepo(), commit_sha=args.commit_sha or "HEAD")
    json.dump({"ok": True, "node_id": node_id,
        "source_count": len(sources)}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


_PRE_BUILD_HINTS = {
    "engineer":   "impact_radius (per changed file, target_type=file)",
    "operator":   "who_owns (per target before mutation)",
    "datawright": "register_output (Document node + PRODUCED_BY edges)",
}


def _cmd_pre_build_check(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.directive).read_text(encoding="utf-8"))
    role = raw.get("role") or raw.get("target_role") or "unknown"
    summary: dict[str, Any] = {"role": role, "would_call": []}
    hint = _PRE_BUILD_HINTS.get(role)
    if hint:
        summary["would_call"].append(hint)
    else:
        summary["note"] = "role has no KG hook (skipping)"
    json.dump(summary, sys.stdout, indent=2); sys.stdout.write("\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine-kg", description="Daemon-side KG helpers (EPIC-7.3)")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enrich", help="Enrich a BuildArtifact's kg_impact field.")
    e.add_argument("artifact"); e.add_argument("--mode", choices=("fill", "verify", "both"), default="both")
    e.add_argument("--repo", default=None); e.add_argument("--in-place", action="store_true")
    e.set_defaults(func=_cmd_enrich)
    f = sub.add_parser("find-owner", help="Operator helper: who_owns lookup.")
    f.add_argument("target"); f.add_argument("--repo", default=None); f.add_argument("--project-id", default=None)
    f.set_defaults(func=_cmd_find_owner)
    r = sub.add_parser("register-output", help="Datawright helper: register pipeline output.")
    r.add_argument("output_path"); r.add_argument("--source-nodes", default="")
    r.add_argument("--repo", default=None); r.add_argument("--project-id", default=None)
    r.add_argument("--commit-sha", default=None); r.set_defaults(func=_cmd_register_output)
    c = sub.add_parser("pre-build-check", help="Dry-run: list KG hooks that would fire.")
    c.add_argument("directive"); c.set_defaults(func=_cmd_pre_build_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

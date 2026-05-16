"""`spine skill` CLI — list / show / test / inject / validate the registry.

Implements STORY-4.1.1 operator surface. Style mirrors `shared/eval/cli.py`.
Exit codes: 0=ok, 2=invalid input / validation failed, 3=runtime error,
64=unknown subcommand.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Optional

from shared.skills.registry import (DEFAULT_SKILLS_ROOT, discover_skills,
                                    list_skills, validate_skill_registry)
from shared.skills.trigger_engine import (DEFAULT_TOKEN_BUDGET, TriggerContext,
                                          compute_triggered_skills,
                                          inject_skill_prompts)

EXIT_OK, EXIT_INVALID, EXIT_ERROR, EXIT_UNKNOWN = 0, 2, 3, 64


def cmd_list(args: argparse.Namespace) -> int:
    reg = discover_skills(args.skills_root)
    rows = list_skills(reg, filter_role=args.role, filter_phase=args.phase)
    if args.format == "json":
        print(json.dumps([{"slug": s.slug, "name": s.name,
                           "priority": s.priority,
                           "roles": s.trigger.applies_to_roles,
                           "phases": s.trigger.applies_to_phases,
                           "max_token_overhead": s.max_token_overhead}
                          for s in rows], indent=2))
        return EXIT_OK
    if not rows: print("(no skills match)"); return EXIT_OK
    print(f"{'PRIORITY':>8}  {'SLUG':<36}  ROLES / PHASES")
    for s in rows:
        roles = ",".join(s.trigger.applies_to_roles) or "*"
        phases = ",".join(s.trigger.applies_to_phases) or "*"
        print(f"{s.priority:>8}  {s.slug:<36}  {roles} / {phases}")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    reg = discover_skills(args.skills_root)
    skill = reg.get(args.slug)
    if skill is None:
        print(f"unknown skill: {args.slug}", file=sys.stderr); return EXIT_INVALID
    payload = {"slug": skill.slug, "name": skill.name, "version": skill.version,
               "priority": skill.priority,
               "max_token_overhead": skill.max_token_overhead,
               "trigger": skill.trigger.model_dump(),
               "incompatible_with": skill.incompatible_with,
               "inherits_from": skill.inherits_from,
               "metadata": skill.metadata,
               "yaml_path": str(skill.yaml_path) if skill.yaml_path else None,
               "md_path": str(skill.md_path) if skill.md_path else None}
    print(json.dumps(payload, indent=2, default=str))
    if args.format != "json":
        print("\n--- SKILL.md ---"); print(skill.prompt_text.rstrip())
    return EXIT_OK


def _ctx(args: argparse.Namespace) -> TriggerContext:
    return TriggerContext(role=args.role, phase=args.phase,
                          directive_text=args.directive or "",
                          artifact_type=args.artifact_type,
                          project_id=args.project_id or "")


def cmd_test(args: argparse.Namespace) -> int:
    reg = discover_skills(args.skills_root)
    fired = compute_triggered_skills(_ctx(args), reg, token_budget=args.budget)
    if args.format == "json":
        print(json.dumps([s.slug for s in fired], indent=2)); return EXIT_OK
    if not fired: print("(no skills triggered)"); return EXIT_OK
    print("Skills triggered (firing order):")
    for s in fired: print(f"  {s.priority:>4}  {s.slug}")
    return EXIT_OK


def cmd_inject(args: argparse.Namespace) -> int:
    reg = discover_skills(args.skills_root)
    fired = compute_triggered_skills(_ctx(args), reg, token_budget=args.budget)
    base = ""
    if args.base_prompt:
        p = Path(args.base_prompt)
        if not p.exists():
            print(f"base prompt not found: {p}", file=sys.stderr); return EXIT_INVALID
        base = p.read_text(encoding="utf-8")
    print(inject_skill_prompts(base, fired))
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    reg = discover_skills(args.skills_root)
    issues = validate_skill_registry(reg, skills_root=args.skills_root)
    if not issues:
        print(f"registry ok ({len(reg)} skills loaded)"); return EXIT_OK
    for i in issues: print(str(i), file=sys.stderr)
    return EXIT_INVALID


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine skill", description=__doc__.splitlines()[0])
    p.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    sub = p.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("list"); lp.add_argument("--role"); lp.add_argument("--phase")
    lp.add_argument("--format", choices=["text", "json"], default="text")
    sp = sub.add_parser("show"); sp.add_argument("slug")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    for name in ("test", "inject"):
        tp = sub.add_parser(name)
        tp.add_argument("--role", required=True); tp.add_argument("--phase", required=True)
        tp.add_argument("--directive", default=""); tp.add_argument("--artifact-type", default=None)
        tp.add_argument("--project-id", default="")
        tp.add_argument("--budget", type=int, default=DEFAULT_TOKEN_BUDGET)
        tp.add_argument("--format", choices=["text", "json"], default="text")
        if name == "inject": tp.add_argument("--base-prompt", default=None)
    sub.add_parser("validate")
    return p


_DISPATCH = {"list": cmd_list, "show": cmd_show, "test": cmd_test,
             "inject": cmd_inject, "validate": cmd_validate}


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    fn = _DISPATCH.get(args.cmd)
    if fn is None:
        print(f"unknown subcommand: {args.cmd}", file=sys.stderr); return EXIT_UNKNOWN
    try: return fn(args)
    except Exception as e:  # broad — CLI must not crash hard
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr); return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

"""prompt_injector.py — inject bundle slices into Spine role-prompt files.

Implements STORY-2.1.3 (per-role prompt injection) and STORY-2.1.4 (auditor
consumption — auditor is one of the inject targets and receives the full
banned_patterns + security slice). See:
  - shared/standards/bundle-schema.yaml (which sections exist).
  - shared/standards/README.md (the "which slice goes to which role" map).
  - docs/PRD.md REQ-INIT-1 FR-7 (override hierarchy: org → team → project).

Idempotent. Re-running with the same bundle is a no-op (content matched at
marker boundaries; nothing outside the markers is touched).

CLI: `python3 prompt_injector.py inject --bundle <path>
        [--role <role>] [--project <id>] [--dry-run]`
Library: `inject_into_role(bundle: dict, role: str, prompt_path: Path) -> InjectResult`.
"""
from __future__ import annotations
import argparse, json, os, sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

# Each role gets a SLICE — only the sections relevant to its authority,
# so the prompt stays under context budget and we don't leak unrelated policy.
ROLE_SLICES: dict[str, list[str]] = {
    "product":    ["standards.documentation_requirements", "compliance_tags",
                   "capabilities.grants"],
    "architect":  ["security.compliance_packs", "deployment_targets",
                   "banned_patterns_summary", "approved_libs_summary"],
    "engineer":   ["approved_libs", "banned_patterns",
                   "standards.style_guides", "standards.naming_conventions"],
    "qa":         ["security.sast_required", "security.dependency_scanning",
                   "standards.test_coverage_threshold"],
    "operator":   ["deployment_targets", "security.secret_scanning"],
    "auditor":    ["banned_patterns", "security", "compliance_tags"],
    "datawright": ["compliance_tags.pii_data_handled", "compliance_tags.gdpr_scope",
                   "approved_libs"],
}

MARK_BEGIN_TMPL = "<!-- SPINE-BUNDLE-INJECT-BEGIN bundle_id={bid} -->"
MARK_END = "<!-- SPINE-BUNDLE-INJECT-END -->"


@dataclass
class InjectResult:
    role: str
    prompt_path: Path
    changed: bool
    bytes_written: int = 0


def _dig(d: dict, dotted: str) -> Any:
    """Drill into a dict with 'a.b.c'; return None if any hop is missing."""
    cur: Any = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur: return None
        cur = cur[k]
    return cur


def _summarize_libs(libs: dict) -> dict:
    """Counts per language — enough for architect-level awareness."""
    return {lang: f"{len(v or [])} libs" for lang, v in (libs or {}).items()}


def _summarize_banned(patterns: list) -> dict:
    """Sev-counts; full list goes to engineer + auditor."""
    out: dict[str, int] = {}
    for p in patterns or []:
        out[p.get("severity", "unknown")] = out.get(p.get("severity", "unknown"), 0) + 1
    return out


def _build_slice(bundle: dict, role: str) -> dict:
    sections = ROLE_SLICES.get(role, [])
    slice_: dict[str, Any] = {}
    for sec in sections:
        if sec == "banned_patterns_summary":
            slice_[sec] = _summarize_banned(bundle.get("banned_patterns") or [])
        elif sec == "approved_libs_summary":
            slice_[sec] = _summarize_libs(bundle.get("approved_libs") or {})
        else:
            val = _dig(bundle, sec)
            if val is not None: slice_[sec] = val
    return slice_


def _render_block(bundle: dict, role: str) -> str:
    bid = (bundle.get("identity") or {}).get("bundle_id", "unknown")
    bver = (bundle.get("identity") or {}).get("bundle_version", "?")
    slice_ = _build_slice(bundle, role)
    body = yaml.safe_dump(slice_, sort_keys=False, default_flow_style=False).rstrip()
    lines = [
        MARK_BEGIN_TMPL.format(bid=bid),
        f"## Org bundle policy ({bid} v{bver})",
        "",
        f"Authoritative policy slice injected from `~/.spine/bundles/{bid}/v{bver}/bundle.yaml`.",
        "Edits to this block are overwritten on the next `spine bundle inject`.",
        "",
        "```yaml", body, "```",
        MARK_END, "",
    ]
    return "\n".join(lines)


def _replace_block(existing: str, new_block: str) -> str:
    """Replace existing inject block, or append if no markers found."""
    begin_token = "<!-- SPINE-BUNDLE-INJECT-BEGIN"
    if begin_token in existing and MARK_END in existing:
        pre, _, rest = existing.partition(begin_token)
        _, _, post = rest.partition(MARK_END)
        # Strip exactly one trailing newline if present (we re-add via new_block).
        if post.startswith("\n"): post = post[1:]
        return pre.rstrip() + "\n\n" + new_block + post
    sep = "\n\n---\n\n" if existing.strip() else ""
    return existing.rstrip() + sep + new_block


def inject_into_role(bundle: dict, role: str, prompt_path: Path,
                     dry_run: bool = False) -> InjectResult:
    if role not in ROLE_SLICES:
        return InjectResult(role=role, prompt_path=prompt_path, changed=False)
    if not prompt_path.exists():
        return InjectResult(role=role, prompt_path=prompt_path, changed=False)
    existing = prompt_path.read_text(encoding="utf-8")
    block = _render_block(bundle, role)
    updated = _replace_block(existing, block)
    if updated == existing:
        return InjectResult(role=role, prompt_path=prompt_path, changed=False)
    if not dry_run:
        prompt_path.write_text(updated, encoding="utf-8")
    return InjectResult(role=role, prompt_path=prompt_path, changed=True,
                        bytes_written=len(updated.encode("utf-8")))


def _resolve_role_prompts_dir() -> Path:
    """Locate Spine's role-prompts dir; env override wins."""
    env = os.environ.get("SPINE_ROLE_PROMPTS_DIR")
    if env: return Path(env)
    here = Path(__file__).resolve()
    candidate = here.parent.parent.parent / "lib" / "role-prompts"
    return candidate


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="prompt_injector.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inj = sub.add_parser("inject")
    inj.add_argument("--bundle", required=True)
    inj.add_argument("--role")
    inj.add_argument("--project")
    inj.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        bundle = yaml.safe_load(open(args.bundle, "r", encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"ok": False, "code": "yaml_parse_error",
                          "message": str(e)}), file=sys.stderr)
        return 2
    prompts = _resolve_role_prompts_dir()
    roles = [args.role] if args.role else list(ROLE_SLICES.keys())
    modified: list[str] = []
    for r in roles:
        p = prompts / f"{r}.md"
        res = inject_into_role(bundle, r, p, dry_run=args.dry_run)
        if res.changed: modified.append(str(p))
    # stdout is what install_bundle.sh captures into role_prompts_modified.
    print(json.dumps(modified))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

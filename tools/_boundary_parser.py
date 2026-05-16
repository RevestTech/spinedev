#!/usr/bin/env python3
"""Spine cross-subsystem module-boundary parser.

Implements STORY-7.1.3 (Module boundary check, generalised across every
subsystem named in docs/ARCHITECTURE.md §4). Reads
``tools/boundary-rules.yaml`` and walks the repo looking for imports
that cross a subsystem boundary contrary to policy. See
``tools/check-boundaries-README.md`` for the user-facing contract.

Languages (REQ-INIT-7 §7.5 FR-1):
  * Python — ``ast``-parsed; ``import`` + ``from … import``; lazy
    in-function imports flagged as warnings rather than errors.
  * Bash   — regex-scan for ``source X`` / ``. X`` / ``bash X``.
  * JS/TS  — regex-scan for ``import``/``require``/dynamic ``import``.

CLI: ``python3 tools/_boundary_parser.py [--rules PATH] [--root PATH]
[--format json|text|junit] [--changed-only] [--explain]``. Stdlib +
PyYAML only. Exit codes: 0 clean · 1 violations · 2 warnings · 3 error.
"""

from __future__ import annotations

import argparse, ast, json, os, re, subprocess, sys, time
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover — bash wrapper reports this
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml)\n")
    sys.exit(3)

_PY_LAZY_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SH_SOURCE_RE = re.compile(r"^\s*(?:source|\.)\s+([^\s#;]+)", re.MULTILINE)
_SH_BASH_RE = re.compile(r"^\s*bash\s+([^\s#;]+)", re.MULTILINE)
_JS_IMPORT_RE = re.compile(
    r"""(?:^|\s)(?:import\s+(?:[\w*${},\s]+\s+from\s+)?|require\s*\(|import\s*\()\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_LANG_EXTS = {".py", ".sh", ".bash", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


@dataclass
class Finding:
    source: str; target: str; imported_name: str; line: int
    severity: str  # "error" | "warning"
    rule_violated: str = ""; note: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in ("", 0) or k == "line"}


@dataclass
class Rules:
    subsystems: dict = field(default_factory=dict)
    excluded_paths: list = field(default_factory=list)
    cross_rules: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)


def load_rules(path: Path) -> Rules:
    raw = yaml.safe_load(path.read_text())
    cross_raw = raw.get("allowed_cross_subsystem_paths", []) or []
    return Rules(
        subsystems=raw.get("subsystems", {}) or {},
        excluded_paths=list(raw.get("excluded_paths", []) or []),
        cross_rules=[x for x in cross_raw if isinstance(x, dict) and "rule" in x],
        exceptions=list(raw.get("exceptions", []) or []),
    )


def subsystem_of(rel_path: str, rules: Rules) -> str | None:
    for name, spec in rules.subsystems.items():
        prefix = spec.get("path", f"{name}/").rstrip("/") + "/"
        if rel_path == prefix.rstrip("/") or rel_path.startswith(prefix):
            return name
    return None


def is_excluded(rel: str, rules: Rules, owner: str | None) -> bool:
    for ex in rules.excluded_paths:
        base = ex.rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    for ex in (rules.subsystems.get(owner, {}) if owner else {}).get("excluded_paths", []) or []:
        if rel.startswith(ex.rstrip("/") + "/"):
            return True
    return False


def _resolve_rel(source: Path, target: str, root: Path) -> str | None:
    try:
        return str((source.parent / target).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return None


def _allowed(owner: str, tgt: str, rules: Rules) -> bool:
    return tgt == owner or tgt in rules.subsystems[owner].get("may_import_from", [])


def _classify(rel: str, tgt_sys: str, name: str, line: int,
              rules: Rules, lazy: bool = False) -> Finding:
    """Decide error vs warning per cross-rules + exceptions."""
    for rule in rules.cross_rules:
        pat, permitted = rule.get("source_pattern"), rule.get("permitted_target", "")
        if pat and re.search(pat, rel) and name.startswith(permitted):
            return Finding(rel, tgt_sys, name, line, "warning",
                           note=f"permitted by rule {rule.get('rule')}")
    for exc in rules.exceptions:
        if rel == exc.get("source", "") and tgt_sys == exc.get("target", "").rstrip("/"):
            return Finding(rel, tgt_sys, name, line, "warning",
                           note=f"exception: {exc.get('reason','')} (expires {exc.get('expires','?')})")
    return Finding(rel, tgt_sys, name, line, "warning" if lazy else "error",
                   rule_violated=f"{Path(rel).parts[0]} cannot import from {tgt_sys}",
                   note="lazy import" if lazy else "")


def _scan_python(path: Path, rel: str, owner: str, rules: Rules) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
    except SyntaxError:
        return []
    lazy: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, _PY_LAZY_FUNCS):
            for child in ast.walk(node):
                lazy.add(id(child))
    findings: list[Finding] = []
    for node in ast.walk(tree):
        names: list[tuple[str, int]] = []
        if isinstance(node, ast.Import):
            names = [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [(node.module, node.lineno)]
        for dotted, lineno in names:
            head = dotted.split(".", 1)[0]
            if head in rules.subsystems and not _allowed(owner, head, rules):
                findings.append(_classify(rel, head, dotted, lineno, rules,
                                          lazy=id(node) in lazy))
    return findings


def _scan_regex(path: Path, rel: str, owner: str, root: Path, rules: Rules,
                regexes: list[re.Pattern], relative_prefix: str = "") -> list[Finding]:
    """Shared regex scanner for bash + js. ``relative_prefix`` triggers path
    resolution when target starts with that char (``''`` = any non-abs)."""
    src = path.read_text(errors="replace")
    findings: list[Finding] = []
    for regex in regexes:
        for match in regex.finditer(src):
            target = match.group(1).strip("'\"")
            if "$" in target or target.startswith("-"):
                continue
            if relative_prefix and not target.startswith(relative_prefix):
                check = target.replace("/", os.sep)
            elif target.startswith("/"):
                check = target
            else:
                check = _resolve_rel(path, target, root) or target
            tgt_sys = subsystem_of(check, rules)
            if not tgt_sys or _allowed(owner, tgt_sys, rules):
                continue
            line = src[: match.start()].count("\n") + 1
            findings.append(_classify(rel, tgt_sys, target if regex is _JS_IMPORT_RE else check,
                                      line, rules))
    return findings


def iter_files(root: Path, only, rules: Rules):
    cands = ([(root / p).resolve() for p in only] if only is not None
             else [p for p in root.rglob("*") if p.is_file() and p.suffix in _LANG_EXTS])
    for path in cands:
        if not path.exists() or path.is_dir() or path.suffix not in _LANG_EXTS:
            continue
        try:
            rel = str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            continue
        owner = subsystem_of(rel, rules)
        if owner and not is_excluded(rel, rules, owner):
            yield path, rel, owner


def scan(root: Path, rules: Rules, only=None) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    for path, rel, owner in iter_files(root, only, rules):
        count += 1
        if path.suffix == ".py":
            findings.extend(_scan_python(path, rel, owner, rules))
        elif path.suffix in (".sh", ".bash"):
            findings.extend(_scan_regex(path, rel, owner, root, rules,
                                        [_SH_SOURCE_RE, _SH_BASH_RE]))
        else:
            findings.extend(_scan_regex(path, rel, owner, root, rules,
                                        [_JS_IMPORT_RE], relative_prefix="."))
    return findings, count


def changed_files(root: Path) -> list[str]:
    base = os.environ.get("SPINE_BOUNDARY_DIFF_BASE", "origin/main")
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
            stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        out = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"], text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def render_text(findings: list[Finding], count: int, duration_ms: int, explain: bool) -> str:
    errs = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warning"]
    lines: list[str] = []
    if errs:
        lines.append("VIOLATIONS:")
        for f in errs:
            lines.append(f"  [{f.severity}] {f.source}:{f.line} -> {f.target}  ({f.imported_name})")
            if explain and f.rule_violated:
                lines.append(f"      rule: {f.rule_violated}")
    if warns:
        lines.append("WARNINGS:")
        for f in warns:
            lines.append(f"  [warn] {f.source}:{f.line} -> {f.target}  ({f.imported_name})  {f.note}")
    lines.append(f"{count} files scanned, {len(errs)} violations, "
                 f"{len(warns)} warnings (took {duration_ms}ms)")
    return "\n".join(lines)


def render_junit(findings: list[Finding]) -> str:
    errs = [f for f in findings if f.severity == "error"]
    cases = [f'    <testcase classname="boundary" name="{f.source}:{f.line}">'
             f'<failure message="{f.rule_violated}">{f.imported_name} -&gt; {f.target}</failure>'
             f"</testcase>" for f in errs]
    if not cases:
        cases.append('    <testcase classname="boundary" name="all-clean"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuite name="spine.boundary" tests="{max(len(errs),1)}" failures="{len(errs)}">\n'
            + "\n".join(cases) + "\n</testsuite>\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="_boundary_parser.py")
    p.add_argument("--rules", default="tools/boundary-rules.yaml")
    p.add_argument("--root", default=".")
    p.add_argument("--format", choices=("json", "text", "junit"), default="json")
    p.add_argument("--changed-only", action="store_true")
    p.add_argument("--explain", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    rules_path = (root / args.rules).resolve() if not Path(args.rules).is_absolute() else Path(args.rules)
    if not rules_path.exists():
        sys.stderr.write(f"ERROR: rules file not found: {rules_path}\n")
        return 3
    rules = load_rules(rules_path)

    only = changed_files(root) if args.changed_only else None
    t0 = time.perf_counter()
    findings, count = scan(root, rules, only)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    errs = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warning"]
    exc_applied = sum(1 for f in warns if f.note.startswith("exception:"))

    if args.format == "json":
        print(json.dumps({"scanned_files": count,
                          "violations": [f.to_dict() for f in errs],
                          "warnings": [f.to_dict() for f in warns],
                          "exceptions_applied": exc_applied,
                          "duration_ms": duration_ms}, indent=2))
    elif args.format == "junit":
        print(render_junit(findings))
    else:
        print(render_text(findings, count, duration_ms, args.explain))

    return 1 if errs else (2 if warns else 0)


if __name__ == "__main__":
    sys.exit(main())

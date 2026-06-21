#!/usr/bin/env python3
"""Run pytest for a Harness Lite scope file (operate-loop sprint-close).

Writes a structured finding JSON under ``.spine/harness/findings/`` and prints
JSON summary on stdout. Exit 0 when pytest passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_state import harness_dir  # noqa: E402

DEFAULT_SCOPE = Path(__file__).resolve().parents[1] / "scopes" / "operate-loop.txt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_scope_paths(scope_file: Path, project_root: Path) -> tuple[list[Path], list[str]]:
    tests: list[Path] = []
    missing: list[str] = []
    for raw in scope_file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        rel = Path(line)
        full = project_root / rel
        if not full.is_file():
            missing.append(line)
            continue
        if "tests/" in line.replace("\\", "/") or rel.name.startswith("test_"):
            tests.append(full)
    return tests, missing


def resolve_python(project_root: Path) -> Path:
    venv_py = project_root / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return venv_py
    return Path(sys.executable)


def run_pytest(project_root: Path, test_paths: list[Path], timeout_s: int) -> tuple[int, str]:
    if not test_paths:
        return 2, "no test paths in scope"
    py = resolve_python(project_root)
    cmd = [str(py), "-m", "pytest", "-q", "--tb=short", *[str(p) for p in test_paths]]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return 124, f"pytest timed out after {timeout_s}s"
    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(combined.splitlines()[-40:])
    return proc.returncode, tail


def write_finding(
    project_root: Path,
    *,
    wave_id: str,
    exit_code: int,
    missing: list[str],
    test_paths: list[Path],
    tail: str,
) -> Path:
    out_dir = harness_dir(project_root) / "findings"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().replace(":", "").replace("-", "")
    path = out_dir / f"tests-scope-{ts}.json"
    if missing:
        severity = "high"
        status = "red"
        claim = "All scope paths present"
        actual = f"missing: {', '.join(missing)}"
    elif exit_code == 0:
        severity = "info"
        status = "green"
        claim = "Scoped pytest green"
        actual = f"{len(test_paths)} file(s) passed"
    else:
        severity = "critical" if exit_code != 124 else "high"
        status = "red"
        claim = "Scoped pytest green"
        actual = f"exit {exit_code}"
    payload = {
        "version": 1,
        "gate": "tests",
        "wave": "verify",
        "wave_id": wave_id,
        "scope": "operate-loop",
        "generated_at": _utc_now(),
        "proposed_status": status,
        "findings": [
            {
                "category": "tests",
                "severity": severity,
                "location": "tools/harness/scopes/operate-loop.txt",
                "claim": claim,
                "actual": actual,
                "fix": "Fix failing tests or restore missing scope files",
                "pytest_tail": tail[:4000] if tail else "",
                "test_files": [str(p.relative_to(project_root)) for p in test_paths],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness Lite scoped pytest")
    parser.add_argument("--project", default=".")
    parser.add_argument(
        "--scope-file",
        default=str(DEFAULT_SCOPE),
        help="Scope manifest (default: operate-loop.txt)",
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    project_root = Path(args.project).resolve()
    scope_file = Path(args.scope_file)
    if not scope_file.is_file():
        print(json.dumps({"error": f"scope file missing: {scope_file}"}))
        return 2

    wave_id = f"scope-pytest-{_utc_now().replace(':', '').replace('-', '')}"
    tests, missing = load_scope_paths(scope_file, project_root)
    if missing:
        finding_path = write_finding(
            project_root,
            wave_id=wave_id,
            exit_code=1,
            missing=missing,
            test_paths=tests,
            tail="",
        )
        print(
            json.dumps(
                {
                    "wave_id": wave_id,
                    "exit_code": 1,
                    "gate": "tests",
                    "status": "red",
                    "findings_file": str(finding_path),
                    "missing": missing,
                },
                indent=2,
            )
        )
        return 1

    exit_code, tail = run_pytest(project_root, tests, args.timeout)
    finding_path = write_finding(
        project_root,
        wave_id=wave_id,
        exit_code=exit_code,
        missing=[],
        test_paths=tests,
        tail=tail,
    )
    status = "green" if exit_code == 0 else "red"
    print(
        json.dumps(
            {
                "wave_id": wave_id,
                "exit_code": exit_code,
                "gate": "tests",
                "status": status,
                "findings_file": str(finding_path),
                "test_count": len(tests),
            },
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

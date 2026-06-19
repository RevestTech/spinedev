#!/usr/bin/env python3
"""Harness Lite state I/O — init, read, write, status markdown.

No Hub/Postgres required. Invoked by ``spine-harness`` and ``loop-bridge.sh``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATE_NAMES = (
    "tests",
    "requirements",
    "drift",
    "docs",
    "security",
    "compliance",
)

GATE_LABELS = {
    "tests": "Tests green",
    "requirements": "Requirements ↔ tech",
    "drift": "Drift handling",
    "docs": "Documentation",
    "security": "Security review",
    "compliance": "Compliance review",
}

VALID_MODES = frozenset(
    {"bootstrap", "feature", "sprint-close", "release-gate", "watch"}
)
VALID_WAVES = frozenset({"audit", "fix", "verify"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def harness_dir(project_root: Path) -> Path:
    return project_root / ".spine" / "harness"


def state_path(project_root: Path) -> Path:
    return harness_dir(project_root) / "state.json"


def default_state(project_root: Path | None = None) -> dict[str, Any]:
    now = _utc_now()
    return {
        "version": 1,
        "mode": None,
        "wave": None,
        "started_at": None,
        "updated_at": now,
        "gates": {g: "unknown" for g in GATE_NAMES},
        "active_loops": [],
        "last_report": None,
        "project_root": str(project_root.resolve()) if project_root else None,
    }


def read_state(project_root: Path) -> dict[str, Any]:
    path = state_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"harness not initialized: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_state(project_root: Path, state: dict[str, Any]) -> None:
    path = state_path(project_root)
    state["updated_at"] = _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def init_harness(project_root: Path) -> Path:
    root = project_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    base = harness_dir(root)
    for sub in ("findings", "reports", "loops"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    path = state_path(root)
    if not path.is_file():
        write_state(root, default_state(root))
    else:
        state = read_state(root)
        state["project_root"] = str(root)
        write_state(root, state)
    return path


def cmd_init(args: argparse.Namespace) -> int:
    path = init_harness(Path(args.project))
    print(path)
    return 0


def cmd_set_mode(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    if args.mode not in VALID_MODES:
        print(f"invalid mode: {args.mode}", file=sys.stderr)
        return 2
    state = read_state(root)
    now = _utc_now()
    state["mode"] = args.mode
    if state.get("started_at") is None:
        state["started_at"] = now
    if args.wave:
        if args.wave not in VALID_WAVES:
            print(f"invalid wave: {args.wave}", file=sys.stderr)
            return 2
        state["wave"] = args.wave
    write_state(root, state)
    print(json.dumps({"mode": args.mode, "wave": state.get("wave")}))
    return 0


def cmd_register_loop(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    state = read_state(root)
    entry = {
        "pid": int(args.pid),
        "purpose": args.purpose,
        "sentinel": args.sentinel,
        "interval_seconds": int(args.interval) if args.interval else None,
        "mode": args.mode or state.get("mode"),
        "started_at": _utc_now(),
    }
    loops = [l for l in state.get("active_loops", []) if l.get("pid") != entry["pid"]]
    loops.append(entry)
    state["active_loops"] = loops
    write_state(root, state)
    return 0


def cmd_unregister_loops(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    state = read_state(root)
    if args.all:
        state["active_loops"] = []
    else:
        pids = {int(p) for p in args.pids}
        state["active_loops"] = [
            l for l in state.get("active_loops", []) if l.get("pid") not in pids
        ]
    write_state(root, state)
    return 0


def _gate_emoji(status: str) -> str:
    return {
        "green": "ok",
        "yellow": "warn",
        "red": "fail",
        "unknown": "unknown",
    }.get(status, "unknown")


def render_status_markdown(state: dict[str, Any], project_root: Path) -> str:
    mode = state.get("mode") or "idle"
    wave = state.get("wave") or "-"
    lines = [
        "# Harness Lite status",
        "",
        f"- **Project:** `{project_root}`",
        f"- **Mode:** `{mode}`",
        f"- **Wave:** `{wave}`",
        f"- **Started:** {state.get('started_at') or '-'}",
        f"- **Updated:** {state.get('updated_at') or '-'}",
        "",
        "## QA gates (ADR-008 / QA-READINESS-STANDARD)",
        "",
        "| Gate | Status |",
        "|------|--------|",
    ]
    for gate in GATE_NAMES:
        status = state.get("gates", {}).get(gate, "unknown")
        lines.append(f"| {GATE_LABELS[gate]} | `{status}` |")
    loops = state.get("active_loops") or []
    lines.extend(["", "## Active loops", ""])
    if not loops:
        lines.append("_None_")
    else:
        lines.append("| PID | Purpose | Sentinel | Interval | Mode |")
        lines.append("|-----|---------|----------|----------|------|")
        for loop in loops:
            interval = loop.get("interval_seconds")
            interval_s = f"{interval}s" if interval else "event/dynamic"
            lines.append(
                f"| {loop.get('pid')} | {loop.get('purpose')} "
                f"| `{loop.get('sentinel')}` | {interval_s} | {loop.get('mode') or '-'} |"
            )
    report = state.get("last_report")
    if report:
        lines.extend(["", f"**Last report:** `{report}`"])
    lines.append("")
    return "\n".join(lines)


def cmd_dump_loop_pids(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    state = read_state(root)
    for loop in state.get("active_loops") or []:
        pid = loop.get("pid")
        if pid is not None:
            print(pid)
    return 0


def cmd_set_gate(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    state = read_state(root)
    if args.gate not in GATE_NAMES:
        print(f"invalid gate: {args.gate}", file=sys.stderr)
        return 2
    if args.status not in {"green", "yellow", "red", "unknown"}:
        print(f"invalid status: {args.status}", file=sys.stderr)
        return 2
    state.setdefault("gates", {})[args.gate] = args.status
    if args.report:
        state["last_report"] = args.report
    write_state(root, state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    state = read_state(root)
    if args.markdown:
        print(render_status_markdown(state, root))
    else:
        print(json.dumps(state, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness Lite state I/O")
    parser.add_argument("--project", default=".", help="Target project root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Scaffold .spine/harness/ and state.json").set_defaults(
        func=cmd_init
    )

    set_mode = sub.add_parser("set-mode", help="Record active harness mode")
    set_mode.add_argument("mode", choices=sorted(VALID_MODES))
    set_mode.add_argument("--wave", choices=sorted(VALID_WAVES))
    set_mode.set_defaults(func=cmd_set_mode)

    reg = sub.add_parser("register-loop", help="Track a background loop PID")
    reg.add_argument("--pid", required=True)
    reg.add_argument("--purpose", required=True)
    reg.add_argument("--sentinel", required=True)
    reg.add_argument("--interval", default="")
    reg.add_argument("--mode", default="")
    reg.set_defaults(func=cmd_register_loop)

    unreg = sub.add_parser("unregister-loops", help="Remove loop entries from state")
    unreg.add_argument("--pid", action="append", dest="pids", default=[])
    unreg.add_argument("--all", action="store_true")
    unreg.set_defaults(func=cmd_unregister_loops)

    dump_pids = sub.add_parser("dump-loop-pids", help="Print active loop PIDs")
    dump_pids.set_defaults(func=cmd_dump_loop_pids)

    set_gate = sub.add_parser("set-gate", help="Update a QA gate status")
    set_gate.add_argument("gate", choices=list(GATE_NAMES))
    set_gate.add_argument("status", choices=["green", "yellow", "red", "unknown"])
    set_gate.add_argument("--report", default="")
    set_gate.set_defaults(func=cmd_set_gate)

    status = sub.add_parser("status", help="Print harness state")
    status.add_argument("--markdown", action="store_true")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

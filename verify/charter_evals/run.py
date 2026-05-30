"""``python -m verify.charter_evals.run <role>`` — execute starter evals.

Wires the harness, loader, and reference callables into a one-shot
command-line entry point. Two purposes:

  * **Smoke check.** Operators can run ``python -m verify.charter_evals.run
    engineer`` to confirm the gate logic, YAML loading, and Markdown
    rendering all work end-to-end. The stub callable lets this run
    offline.
  * **Pluggable real runs.** A team running a real LLM-backed
    ``role_callable`` substitutes it via the ``--callable`` flag
    (currently only ``stub`` is wired; documented extension point).

Exits:

* ``0`` — every eval met its ``target_pass_rate`` (#7a gate green).
* ``1`` — at least one eval regressed below its target (#7a gate red).
* ``2`` — no evals found / config error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verify.charter_evals.harness import (
    CharterReport,
    evaluate_charter,
    load_evals_for_role,
)
from verify.charter_evals.role_callables import (
    fixture_role_callable_from_dir,
    stub_role_callable,
)


def render_report_markdown(report: CharterReport) -> str:
    """Render a CharterReport as a compact Markdown summary."""
    lines: list[str] = []
    lines.append(f"# Charter eval report — {report.role}\n")
    overall = "**green**" if report.overall_meets_target else "**red**"
    lines.append(f"> Overall: {overall}\n\n")
    lines.append("| Eval | Trials | Passed | Rate | Target | Meets? |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for p in report.per_eval:
        verdict = "green" if p.meets_target else "red"
        lines.append(
            f"| `{p.eval_name}` | {p.trials} | {p.passed} | "
            f"{p.pass_rate:.2f} | {p.target_pass_rate:.2f} | "
            f"**{verdict}** |\n"
        )
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spine-charter-evals",
        description=(
            "Run V3 #7a charter regression evals for a named role."
        ),
    )
    parser.add_argument(
        "role",
        help=(
            "Role to evaluate (matches a verify/charter_evals/<role>/ "
            "directory)."
        ),
    )
    parser.add_argument(
        "--callable",
        choices=("stub", "fixture"),
        default="stub",
        help=(
            "Which RoleCallable to use. 'stub' returns canned "
            "responses per eval name; 'fixture' reads response text "
            "from <root>/<eval-name>.txt files."
        ),
    )
    parser.add_argument(
        "--fixture-root",
        default=None,
        help="Directory of per-eval fixture text files (with --callable fixture).",
    )
    parser.add_argument(
        "--write",
        default=None,
        help="Also write the rendered report to PATH.",
    )
    args = parser.parse_args(argv)

    evals = load_evals_for_role(args.role)
    if not evals:
        print(
            f"no evals found for role {args.role!r} under "
            f"verify/charter_evals/{args.role}/",
            file=sys.stderr,
        )
        return 2

    if args.callable == "stub":
        role_callable = stub_role_callable
    elif args.callable == "fixture":
        if not args.fixture_root:
            print(
                "--callable fixture requires --fixture-root", file=sys.stderr,
            )
            return 2
        role_callable = fixture_role_callable_from_dir(Path(args.fixture_root))
    else:  # pragma: no cover - argparse choices restrict this
        return 2

    report = evaluate_charter(args.role, evals, role_callable)
    markdown = render_report_markdown(report)
    sys.stdout.write(markdown)

    if args.write:
        out = Path(args.write).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")

    return 0 if report.overall_meets_target else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main", "render_report_markdown"]

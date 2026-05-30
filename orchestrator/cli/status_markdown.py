"""``spine status --markdown`` handoff snapshot generator (V3 B5).

Borrowed contract source: ECC ``ecc status --markdown --write status.md``
(`affaan-m/ecc`, MIT). See ``docs/ECC_BORROWS.md`` B5.

This module turns the current Hub state into a portable Markdown document
matching the shape of ``docs/SESSION_HANDOFF.md``. The handoff serves two
purposes:

1. **Crash recovery.** If the IDE / session dies mid-work, restarting and
   reading ``SESSION_HANDOFF.md`` rebuilds context without conversation
   memory.
2. **Operator handoff.** Cron / CI can run ``spine status --markdown
   --write handoff.md --exit-code`` to fail when readiness needs
   attention (stuck dispatches, DB unreachable, ledger drift, smoke
   regression).

Inputs are read lazily and the module degrades gracefully when any
source is unavailable — DB down still produces a useful Markdown file.

Sources
-------

* **Git** — branch + working-tree summary via ``git`` shell-out. Always
  available in a repo.
* **Decision ledger** — ``shared.audit.decision_ledger`` tail of recent
  entries per project. Always available (filesystem only).
* **Spine database** — ``spine_lifecycle.project`` phase counts +
  in-flight dispatch tally. DB-optional; failures degrade to "DB
  unreachable" rows.
* **Smoke** — final ``Summary`` line from ``tools/smoke-test.sh``
  cached output, if a prior run wrote ``.spine/last-smoke.txt``.
  Optional.

Output contract
---------------

``render_markdown(state: HandoffState) -> str`` is the testable surface.
``collect_state(...)`` walks the live sources but every collector is
overridable for tests via dependency-injected callables.

Exit-code semantics (used by ``compute_exit_code(state)``):

* ``0`` — green; no warnings.
* ``1`` — warnings (e.g. ledger drift detected, pending decisions
  awaiting approval, uncommitted but non-blocking work).
* ``2`` — fail (e.g. DB unreachable, smoke fail count > 0,
  promotion-gate denials accumulating without resolution).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from shared.audit.decision_ledger import (
    DecisionLedger,
    LedgerEntry,
    default_ledger_root,
)

logger = logging.getLogger(__name__)


# ─── State model ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class GitSnapshot:
    """Working-tree summary."""

    branch: str
    is_clean: bool
    untracked_count: int
    modified_count: int
    ahead_main: int
    last_commit: str  # "<sha> <subject>"
    error: str | None = None  # set when git unreachable / not a repo

    @property
    def status_word(self) -> str:
        if self.error:
            return "error"
        if self.is_clean and self.ahead_main == 0:
            return "clean"
        return "dirty"


@dataclass(frozen=True)
class LedgerSnapshot:
    """Recent decision-ledger activity for one project.run pair."""

    project_id: str
    run_id: str
    entries_seen: int
    last_verdict: str | None
    last_tier: str | None
    last_reasons: tuple[str, ...]
    denials_in_tail: int
    chain_ok: bool
    chain_reason: str | None


@dataclass(frozen=True)
class PhaseCount:
    """One row of the phase-count distribution."""

    phase: str
    count: int


@dataclass(frozen=True)
class DbSnapshot:
    """Hub-DB-derived state. ``reachable=False`` means everything else is None."""

    reachable: bool
    error: str | None
    phase_counts: tuple[PhaseCount, ...] = ()
    dispatches_in_flight: int | None = None
    pending_decisions: int | None = None


@dataclass(frozen=True)
class SmokeSnapshot:
    """Cached output of the last smoke run."""

    available: bool
    pass_count: int | None = None
    fail_count: int | None = None
    warn_count: int | None = None
    skip_count: int | None = None
    info_count: int | None = None
    last_run_ts: str | None = None


@dataclass(frozen=True)
class HandoffState:
    """Everything render_markdown needs in one immutable bundle."""

    generated_at: datetime
    spine_home: Path
    git: GitSnapshot
    db: DbSnapshot
    ledger: tuple[LedgerSnapshot, ...] = ()
    smoke: SmokeSnapshot | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    failures: tuple[str, ...] = field(default_factory=tuple)


# ─── Collectors ──────────────────────────────────────────────────────


def collect_git(spine_home: Path) -> GitSnapshot:
    """Read git working-tree state. Never raises."""
    try:
        branch = _run_git(spine_home, ["rev-parse", "--abbrev-ref", "HEAD"])
        status = _run_git(spine_home, ["status", "--porcelain=v1"])
        try:
            ahead = int(
                _run_git(spine_home, ["rev-list", "--count", "main..HEAD"]) or "0"
            )
        except (ValueError, RuntimeError):
            ahead = 0
        last = _run_git(spine_home, ["log", "-1", "--pretty=%h %s"])

        untracked = sum(1 for line in status.splitlines() if line.startswith("??"))
        modified = sum(
            1
            for line in status.splitlines()
            if line and not line.startswith("??")
        )
        return GitSnapshot(
            branch=branch or "(detached)",
            is_clean=not status.strip(),
            untracked_count=untracked,
            modified_count=modified,
            ahead_main=ahead,
            last_commit=last or "(none)",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("collect_git failed: %s", exc)
        return GitSnapshot(
            branch="(unknown)",
            is_clean=False,
            untracked_count=0,
            modified_count=0,
            ahead_main=0,
            last_commit="(unknown)",
            error=str(exc),
        )


def _run_git(spine_home: Path, args: list[str]) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git not on PATH")
    completed = subprocess.run(
        [git, *args],
        cwd=str(spine_home),
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} rc={completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def collect_db(
    *,
    psql_runner: Callable[[str], str] | None = None,
) -> DbSnapshot:
    """Read project + dispatch counts from spine DB.

    ``psql_runner`` is the SQL execution hook. When ``None``, the
    collector returns a ``reachable=False`` snapshot — callers in the
    Python test suite typically inject a fake runner; the bash CLI
    wraps a psql subprocess.
    """
    if psql_runner is None:
        return DbSnapshot(
            reachable=False, error="no psql runner configured",
        )
    try:
        phase_text = psql_runner(
            "SELECT current_phase, COUNT(*) FROM spine_lifecycle.project "
            "WHERE deleted_at IS NULL GROUP BY current_phase "
            "ORDER BY current_phase;"
        )
        phases = tuple(_parse_phase_counts(phase_text))
        in_flight_text = psql_runner(
            "SELECT COUNT(*) FROM spine_lifecycle.project "
            "WHERE deleted_at IS NULL AND dispatch_in_flight IS NOT NULL;"
        )
        in_flight = _parse_single_int(in_flight_text)
        pending_text = psql_runner(
            "SELECT COUNT(*) FROM spine_lifecycle.approval "
            "WHERE status = 'pending';"
        )
        pending = _parse_single_int(pending_text)
        return DbSnapshot(
            reachable=True,
            error=None,
            phase_counts=phases,
            dispatches_in_flight=in_flight,
            pending_decisions=pending,
        )
    except Exception as exc:
        return DbSnapshot(reachable=False, error=str(exc))


def _parse_phase_counts(text: str) -> Iterable[PhaseCount]:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 2:
            continue
        try:
            yield PhaseCount(phase=parts[0], count=int(parts[1]))
        except ValueError:
            continue


def _parse_single_int(text: str) -> int | None:
    line = text.strip().splitlines()[0] if text.strip() else ""
    try:
        return int(line)
    except (TypeError, ValueError):
        return None


def collect_ledger(
    *,
    root: Path | None = None,
    tail: int = 5,
    max_projects: int = 10,
) -> tuple[LedgerSnapshot, ...]:
    """Walk ``<root>/<project>/<run>.jsonl`` and summarise the tail."""
    root = root or default_ledger_root()
    if not root.exists():
        return ()
    snapshots: list[LedgerSnapshot] = []
    project_dirs = sorted(p for p in root.iterdir() if p.is_dir())[:max_projects]
    for proj_dir in project_dirs:
        for run_file in sorted(proj_dir.glob("*.jsonl")):
            ledger = DecisionLedger(
                project_id=proj_dir.name,
                run_id=run_file.stem,
                root=root,
            )
            tail_entries = ledger.tail(tail)
            if not tail_entries:
                continue
            chain_ok, chain_reason = ledger.verify_chain()
            last = tail_entries[-1]
            denials = sum(
                1
                for e in tail_entries
                if e.promotion_gate.verdict == "denied"
            )
            snapshots.append(
                LedgerSnapshot(
                    project_id=proj_dir.name,
                    run_id=run_file.stem,
                    entries_seen=len(tail_entries),
                    last_verdict=last.promotion_gate.verdict,
                    last_tier=last.promotion_gate.tier,
                    last_reasons=tuple(last.promotion_gate.reasons),
                    denials_in_tail=denials,
                    chain_ok=chain_ok,
                    chain_reason=chain_reason,
                )
            )
    return tuple(snapshots)


def collect_smoke(spine_home: Path) -> SmokeSnapshot | None:
    """Read cached smoke summary from ``.spine/last-smoke.txt`` if present.

    The expected format is the final ``Summary`` block emitted by
    ``tools/smoke-test.sh``:

        PASS=99  FAIL=0  WARN=1  SKIP=0  INFO=3  (total=103)

    Anything else returns ``None``.
    """
    path = spine_home / ".spine" / "last-smoke.txt"
    if not path.exists():
        return SmokeSnapshot(available=False)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return SmokeSnapshot(available=False)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("PASS=") and "FAIL=" in line:
            counts = _parse_smoke_line(line)
            if counts is None:
                continue
            ts = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc,
            ).isoformat()
            return SmokeSnapshot(available=True, last_run_ts=ts, **counts)
    return SmokeSnapshot(available=False)


def _parse_smoke_line(line: str) -> dict[str, int] | None:
    out: dict[str, int] = {}
    for token in line.replace("(", " ").replace(")", " ").split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key not in {"PASS", "FAIL", "WARN", "SKIP", "INFO"}:
            continue
        try:
            out[f"{key.lower()}_count"] = int(value)
        except ValueError:
            return None
    if not out:
        return None
    return out


def collect_state(
    *,
    spine_home: Path,
    psql_runner: Callable[[str], str] | None = None,
    ledger_root: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> HandoffState:
    """Gather everything in one pass. Sources collected sequentially.

    All sources fail-soft: anything unavailable is reflected in the
    returned snapshot rather than raising.
    """
    now_fn = now or (lambda: datetime.now(timezone.utc))
    git = collect_git(spine_home)
    db = collect_db(psql_runner=psql_runner)
    ledger = collect_ledger(root=ledger_root)
    smoke = collect_smoke(spine_home)

    warnings: list[str] = []
    failures: list[str] = []

    if db.reachable is False:
        warnings.append(f"db: unreachable — {db.error or 'unknown'}")
    else:
        if db.pending_decisions and db.pending_decisions > 0:
            warnings.append(
                f"decisions: {db.pending_decisions} pending approval"
            )
        if db.dispatches_in_flight and db.dispatches_in_flight > 0:
            warnings.append(
                f"dispatch: {db.dispatches_in_flight} in flight"
            )

    if smoke and smoke.available and (smoke.fail_count or 0) > 0:
        failures.append(f"smoke: FAIL={smoke.fail_count}")

    for snap in ledger:
        if not snap.chain_ok:
            failures.append(
                f"ledger: {snap.project_id}/{snap.run_id} chain broken — "
                f"{snap.chain_reason}"
            )
        if snap.denials_in_tail >= 3:
            warnings.append(
                f"ledger: {snap.project_id}/{snap.run_id} "
                f"{snap.denials_in_tail} denials in tail"
            )

    if not git.is_clean and git.modified_count + git.untracked_count > 40:
        warnings.append(
            f"git: {git.modified_count + git.untracked_count} dirty files"
        )

    return HandoffState(
        generated_at=now_fn(),
        spine_home=spine_home,
        git=git,
        db=db,
        ledger=ledger,
        smoke=smoke,
        warnings=tuple(warnings),
        failures=tuple(failures),
    )


# ─── Markdown renderer ───────────────────────────────────────────────


def render_markdown(state: HandoffState) -> str:
    """Render a complete handoff document from ``state``.

    Output shape deliberately mirrors ``docs/SESSION_HANDOFF.md`` so the
    same readers can consume either an automated snapshot or a
    hand-written narrative.
    """
    parts: list[str] = []
    parts.append(f"# Spine status snapshot — {state.generated_at.date().isoformat()}\n")
    parts.append(
        f"> Auto-generated by `spine status --markdown` at "
        f"{state.generated_at.isoformat()}.\n"
        f"> Source repo: `{state.spine_home}`.\n"
    )

    parts.append("\n## Readiness\n\n")
    parts.append(_render_readiness_table(state))

    parts.append("\n## Git\n\n")
    parts.append(_render_git_section(state.git))

    parts.append("\n## Database\n\n")
    parts.append(_render_db_section(state.db))

    parts.append("\n## Decision ledger (V3 #12a)\n\n")
    parts.append(_render_ledger_section(state.ledger))

    parts.append("\n## Smoke (last cached)\n\n")
    parts.append(_render_smoke_section(state.smoke))

    parts.append("\n## Warnings / failures\n\n")
    parts.append(_render_warnings_section(state.warnings, state.failures))

    parts.append(
        "\n---\n*Use `--exit-code` to surface readiness as a process "
        "exit (0=green, 1=warnings, 2=failures).*\n"
    )
    return "".join(parts)


def _render_readiness_table(state: HandoffState) -> str:
    overall = "green"
    if state.failures:
        overall = "fail"
    elif state.warnings:
        overall = "warning"
    return (
        f"| Signal | State |\n"
        f"|---|---|\n"
        f"| Overall | **{overall}** |\n"
        f"| Git working tree | {state.git.status_word} |\n"
        f"| DB reachable | {'yes' if state.db.reachable else 'no'} |\n"
        f"| Ledger projects | {len(state.ledger)} |\n"
        f"| Smoke cached | "
        f"{'yes' if state.smoke and state.smoke.available else 'no'} |\n"
    )


def _render_git_section(git: GitSnapshot) -> str:
    if git.error:
        return f"_unavailable — {git.error}_\n"
    return (
        f"- Branch: `{git.branch}`\n"
        f"- Last commit: `{git.last_commit}`\n"
        f"- Working tree: {git.modified_count} modified, "
        f"{git.untracked_count} untracked\n"
        f"- Ahead of `main`: {git.ahead_main} commits\n"
    )


def _render_db_section(db: DbSnapshot) -> str:
    if not db.reachable:
        return f"_unreachable — {db.error or 'unknown'}_\n"
    rows = ["| Phase | Count |", "|---|---|"]
    for pc in db.phase_counts:
        rows.append(f"| {pc.phase} | {pc.count} |")
    summary = (
        f"\n- Dispatches in flight: {db.dispatches_in_flight}\n"
        f"- Pending decisions: {db.pending_decisions}\n"
    )
    return "\n".join(rows) + "\n" + summary


def _render_ledger_section(ledger: tuple[LedgerSnapshot, ...]) -> str:
    if not ledger:
        return "_no ledger entries on disk yet (see V3 #12a)_\n"
    rows = [
        "| Project | Run | Tail | Last verdict | Tier | Chain |",
        "|---|---|---|---|---|---|",
    ]
    for snap in ledger:
        chain = "ok" if snap.chain_ok else f"BROKEN ({snap.chain_reason})"
        rows.append(
            f"| `{snap.project_id}` | `{snap.run_id}` | "
            f"{snap.entries_seen} | "
            f"{snap.last_verdict or '—'} | "
            f"{snap.last_tier or '—'} | {chain} |"
        )
    return "\n".join(rows) + "\n"


def _render_smoke_section(smoke: SmokeSnapshot | None) -> str:
    if smoke is None or not smoke.available:
        return (
            "_no cached smoke summary at `.spine/last-smoke.txt` — run "
            "`bash tools/smoke-test.sh > .spine/last-smoke.txt`_\n"
        )
    return (
        f"- Last run: {smoke.last_run_ts}\n"
        f"- PASS={smoke.pass_count}  "
        f"FAIL={smoke.fail_count}  WARN={smoke.warn_count}  "
        f"SKIP={smoke.skip_count}  INFO={smoke.info_count}\n"
    )


def _render_warnings_section(
    warnings: tuple[str, ...], failures: tuple[str, ...],
) -> str:
    if not warnings and not failures:
        return "_none_\n"
    parts: list[str] = []
    if failures:
        parts.append("**Failures:**\n")
        for f in failures:
            parts.append(f"- {f}\n")
    if warnings:
        if failures:
            parts.append("\n")
        parts.append("**Warnings:**\n")
        for w in warnings:
            parts.append(f"- {w}\n")
    return "".join(parts)


# ─── Exit code + entry point ─────────────────────────────────────────


def compute_exit_code(state: HandoffState) -> int:
    """0 green / 1 warnings / 2 failures."""
    if state.failures:
        return 2
    if state.warnings:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``orchestrator/bin/spine``.

    Args (from ``argv`` or ``sys.argv``):

      ``--write PATH``  — write Markdown to ``PATH`` and stdout.
      ``--exit-code``   — return readiness as exit code.
      ``--ledger-root PATH`` — override default ledger root.

    The bash CLI invokes this as::

        .venv/bin/python -m orchestrator.cli.status_markdown \
            --write docs/SESSION_HANDOFF.md --exit-code
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="spine-status-markdown",
        description="Render a Spine status handoff as Markdown.",
    )
    parser.add_argument("--write", default=None, help="write to PATH")
    parser.add_argument(
        "--exit-code", action="store_true",
        help="surface readiness as exit code (0/1/2)",
    )
    parser.add_argument(
        "--ledger-root", default=None,
        help="override $SPINE_DECISION_LEDGER_ROOT",
    )
    args = parser.parse_args(argv)

    spine_home = Path(os.environ.get("SPINE_HOME", os.getcwd())).resolve()
    ledger_root = Path(args.ledger_root).expanduser() if args.ledger_root else None
    state = collect_state(
        spine_home=spine_home,
        psql_runner=_make_psql_runner(),
        ledger_root=ledger_root,
    )
    markdown = render_markdown(state)
    sys.stdout.write(markdown)
    if args.write:
        out_path = Path(args.write).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
    if args.exit_code:
        return compute_exit_code(state)
    return 0


def _make_psql_runner() -> Callable[[str], str] | None:
    """Build a psql shell-out runner if ``SPINE_DB_URL`` is set."""
    url = os.environ.get("SPINE_DB_URL", "").strip()
    psql = shutil.which("psql")
    if not url or not psql:
        return None

    def _run(sql: str) -> str:
        completed = subprocess.run(
            [
                psql, url, "-A", "-t", "-X", "-q",
                "-v", "ON_ERROR_STOP=1", "-c", sql,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"psql rc={completed.returncode}: {completed.stderr.strip()}"
            )
        return completed.stdout

    return _run


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())


__all__ = [
    "DbSnapshot",
    "GitSnapshot",
    "HandoffState",
    "LedgerSnapshot",
    "PhaseCount",
    "SmokeSnapshot",
    "collect_db",
    "collect_git",
    "collect_ledger",
    "collect_smoke",
    "collect_state",
    "compute_exit_code",
    "main",
    "render_markdown",
]

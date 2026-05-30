"""L07 tool_execution check for the 12-layer agent-stack audit.

Inspects the MCP tool call status mix (ok / warning / error / refusal /
stub_implementation) for the current window. The Cite-or-Refuse
middleware (V3 #12) raises refusals when a verify-class tool lacks
citations, so an elevated refusal share is the classic charter-broken
signal. Errors dominating points at a broken tool or downed dependency.
A registry full of ``stub_implementation`` masquerades as ``ok`` in some
upstream rollups, so we surface it as its own warning.
"""
from __future__ import annotations

from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding

_LAYER = "L07_tool_execution"
_ERROR_REFUSAL_REGRESSED = 0.5
_STUB_WARNING = 0.5
_REFUSAL_WARNING = 0.25
_REQUIRED_FILES = (
    Path("shared") / "mcp" / "server.py",
    Path("shared") / "mcp" / "cite_or_refuse.py",
)


def _missing_required_files(repo_root: Path) -> tuple[str, ...]:
    return tuple(
        str(rel) for rel in _REQUIRED_FILES
        if not (repo_root / rel).exists()
    )


def _coerce_count(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def check_tool_execution_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L07 — MCP tool call status mix within bounds.

    ``signals['tool_exec_stats']`` is a mapping with counts for the
    keys ``ok`` / ``warning`` / ``error`` / ``refusal`` /
    ``stub_implementation`` aggregated over a window.
    """
    missing = _missing_required_files(repo_root)
    if missing:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"{len(missing)} MCP surface file(s) missing — tool "
                "execution layer cannot run"
            ),
            severity="critical",
            evidence=missing,
        )

    stats = signals.get("tool_exec_stats")
    if stats is None:
        return LayerFinding(
            layer=_LAYER,
            status="instrumentation_pending",
            summary=(
                "no tool_exec_stats signal supplied (pipe MCP call "
                "status counts via shared.mcp.server aggregator)"
            ),
            severity="low",
        )
    if not isinstance(stats, dict):
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"tool_exec_stats signal is not a dict "
                f"(got {type(stats).__name__})"
            ),
            severity="high",
        )

    ok = _coerce_count(stats.get("ok", 0))
    warning = _coerce_count(stats.get("warning", 0))
    error = _coerce_count(stats.get("error", 0))
    refusal = _coerce_count(stats.get("refusal", 0))
    stub = _coerce_count(stats.get("stub_implementation", 0))
    total = ok + warning + error + refusal + stub

    if total == 0:
        return LayerFinding(
            layer=_LAYER,
            status="instrumentation_pending",
            summary="tool_exec_stats window is empty (0 calls observed)",
            severity="low",
        )

    error_refusal_rate = (error + refusal) / total
    stub_rate = stub / total
    refusal_rate = refusal / total

    if error_refusal_rate > _ERROR_REFUSAL_REGRESSED:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"{error + refusal}/{total} "
                f"({error_refusal_rate:.0%}) MCP calls failing "
                "(error+refusal) — investigate broken tool, downed "
                "dependency, or charter producing un-cited output"
            ),
            severity="high",
            evidence=(
                f"ok={ok}",
                f"warning={warning}",
                f"error={error}",
                f"refusal={refusal}",
                f"stub_implementation={stub}",
            ),
            next_actions=(
                "tail MCP server logs for the offending tool",
                "check cite_or_refuse refusal evidence in audit ledger",
            ),
        )

    if stub_rate > _STUB_WARNING:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                f"{stub}/{total} ({stub_rate:.0%}) MCP calls returning "
                "stub_implementation — too many un-wired tools"
            ),
            severity="medium",
            evidence=(f"stub_implementation={stub}", f"total={total}"),
            next_actions=(
                "wire stub tools to real implementations or remove from "
                "registry to avoid masking as ok",
            ),
        )

    if refusal_rate > _REFUSAL_WARNING:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                f"{refusal}/{total} ({refusal_rate:.0%}) MCP calls "
                "refused — elevated refusal rate suggests charter "
                "producing un-cited output"
            ),
            severity="medium",
            evidence=(f"refusal={refusal}", f"total={total}"),
            next_actions=(
                "review cite_or_refuse refusal evidence for charter "
                "that needs citation discipline",
            ),
        )

    return LayerFinding(
        layer=_LAYER,
        status="clean",
        summary=(
            f"{total} MCP call(s) — ok={ok} warning={warning} "
            f"error={error} refusal={refusal} stub={stub}"
        ),
        severity="low",
    )


__all__ = ["check_tool_execution_layer"]

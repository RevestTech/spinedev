"""L08 tool_interpretation — bounded-retrieval need parsing health.

Verifies ``shared/runtime/bounded_retrieval.py`` still ships the V3 B4
need-parsing channel and inspects ``signals['next_actions_stats']`` for
roles emitting malformed need lines or never engaging the channel.
"""
from __future__ import annotations

from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding


_BR_RELPATH = Path("shared") / "runtime" / "bounded_retrieval.py"
_MALFORMED_RATE_WARN_THRESHOLD = 0.25
_MIN_ACTIONS_FOR_UNDERUSE = 10


def check_tool_interpretation_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L08 — next_actions parsing rate within bound."""
    br_path = repo_root / _BR_RELPATH
    if not br_path.exists():
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="regressed",
            summary="shared/runtime/bounded_retrieval.py missing",
            severity="critical",
            evidence=(str(_BR_RELPATH),),
        )

    stats = signals.get("next_actions_stats")
    if stats is None:
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="instrumentation_pending",
            summary=(
                "no next_actions_stats signal (pipe in total_next_actions / "
                "parsed_needs / malformed_need_attempts from dispatcher)"
            ),
            severity="low",
        )
    if not isinstance(stats, dict):
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="regressed",
            summary=(
                f"next_actions_stats signal is not a dict "
                f"(got {type(stats).__name__})"
            ),
            severity="high",
        )

    total = int(stats.get("total_next_actions", 0) or 0)
    parsed = int(stats.get("parsed_needs", 0) or 0)
    malformed = int(stats.get("malformed_need_attempts", 0) or 0)

    if total == 0:
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="instrumentation_pending",
            summary="next_actions_stats total_next_actions is 0",
            severity="low",
        )

    malformed_rate = malformed / total
    if malformed_rate > _MALFORMED_RATE_WARN_THRESHOLD:
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="warning",
            summary=(
                f"malformed need rate {malformed_rate:.0%} "
                f"({malformed}/{total}) — roles emitting un-parseable "
                f"need: lines"
            ),
            severity="medium",
            evidence=(
                f"malformed_need_attempts={malformed}",
                f"total_next_actions={total}",
            ),
        )

    if parsed == 0 and total >= _MIN_ACTIONS_FOR_UNDERUSE:
        return LayerFinding(
            layer="L08_tool_interpretation",
            status="warning",
            summary=(
                f"zero parsed needs across {total} next_actions — "
                f"bounded retrieval channel underused"
            ),
            severity="medium",
            evidence=(
                f"parsed_needs={parsed}",
                f"total_next_actions={total}",
            ),
        )

    return LayerFinding(
        layer="L08_tool_interpretation",
        status="clean",
        summary=(
            f"{parsed}/{total} next_actions parsed as needs; "
            f"{malformed} malformed"
        ),
    )


__all__ = ["check_tool_interpretation_layer"]

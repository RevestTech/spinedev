"""L05 active_recall — KG retrieval middleware health.

Verifies the hybrid_search formatter still exists on disk and still
caps result rows so the KG context block cannot bloat into the role
prompt. Live retrieval health (hit rate, avg results per hit) comes in
through ``signals['kg_retrieval_stats']`` when the runtime aggregator
populates it.
"""
from __future__ import annotations

from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding


_KG_RELPATH = Path("shared") / "runtime" / "kg_role_context.py"
_CAP_MARKER = "results[:15]"
_MIN_QUERIES_FOR_HIT_RATE = 10
_HIT_RATE_WARN_THRESHOLD = 0.5
_AVG_RESULTS_WARN_THRESHOLD = 30


def check_active_recall_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L05 — KG retrieval middleware healthy + hit-rate within bound."""
    kg_path = repo_root / _KG_RELPATH
    if not kg_path.exists():
        return LayerFinding(
            layer="L05_active_recall",
            status="regressed",
            summary="shared/runtime/kg_role_context.py missing",
            severity="high",
            evidence=(str(_KG_RELPATH),),
        )

    text = kg_path.read_text(encoding="utf-8")
    if _CAP_MARKER not in text:
        return LayerFinding(
            layer="L05_active_recall",
            status="regressed",
            summary=(
                "format_hybrid_search_block no longer caps result rows — "
                "KG block may bloat role context"
            ),
            severity="high",
            evidence=("missing 15-row cap",),
        )

    stats = signals.get("kg_retrieval_stats")
    if stats is None:
        return LayerFinding(
            layer="L05_active_recall",
            status="instrumentation_pending",
            summary=(
                "no kg_retrieval_stats signal (pipe in recent_queries / "
                "recent_hits / avg_results_per_hit from runtime aggregator)"
            ),
            severity="low",
        )
    if not isinstance(stats, dict):
        return LayerFinding(
            layer="L05_active_recall",
            status="regressed",
            summary=(
                f"kg_retrieval_stats signal is not a dict "
                f"(got {type(stats).__name__})"
            ),
            severity="high",
        )

    recent_queries = int(stats.get("recent_queries", 0) or 0)
    recent_hits = int(stats.get("recent_hits", 0) or 0)
    avg_results = float(stats.get("avg_results_per_hit", 0.0) or 0.0)

    if recent_queries >= _MIN_QUERIES_FOR_HIT_RATE:
        hit_rate = recent_hits / recent_queries if recent_queries else 0.0
        if hit_rate < _HIT_RATE_WARN_THRESHOLD:
            return LayerFinding(
                layer="L05_active_recall",
                status="warning",
                summary=(
                    f"KG retrieval hit rate {hit_rate:.0%} "
                    f"({recent_hits}/{recent_queries}) — roles flying blind"
                ),
                severity="medium",
                evidence=(
                    f"recent_queries={recent_queries}",
                    f"recent_hits={recent_hits}",
                ),
            )

    if avg_results > _AVG_RESULTS_WARN_THRESHOLD:
        return LayerFinding(
            layer="L05_active_recall",
            status="warning",
            summary=(
                f"KG avg results per hit {avg_results:.1f} exceeds "
                f"{_AVG_RESULTS_WARN_THRESHOLD} — block may bloat role prompt"
            ),
            severity="medium",
            evidence=(f"avg_results_per_hit={avg_results:.1f}",),
        )

    return LayerFinding(
        layer="L05_active_recall",
        status="clean",
        summary=(
            f"KG retrieval middleware intact; "
            f"{recent_hits}/{recent_queries} recent hits, "
            f"avg {avg_results:.1f} results per hit"
        ),
    )


__all__ = ["check_active_recall_layer"]

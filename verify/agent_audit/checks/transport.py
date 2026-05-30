"""L10 — transport mutation surfaces (SPA / API / federation).

Transport failure mode in Spine: the V3 #30a envelope additions
(``summary``, ``next_actions``, ``artifacts``) are emitted by the MCP
server but get stripped or ignored between server emission and the
user-facing render. Three surfaces can do this:

  * API serialization in ``shared/api/`` that flattens responses.
  * SPA components in ``shared/ui/spa/src/lib/components/`` that bind
    only to ``data`` and never surface ``summary`` / ``next_actions``.
  * Federation downstream Hubs re-shaping outputs.

This check is intentionally static: it verifies the envelope contract
on disk and counts how many ``ToolResponse`` consumer files reference
the new ``summary`` field. Live drop counts can be supplied via
``signals['transport_drops']``.
"""
from __future__ import annotations

from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding

_LAYER = "L10_transport"
_ENVELOPES_RELPATH = Path("shared") / "mcp" / "schemas" / "envelopes.py"
_API_DIR = Path("shared") / "api"
_SPA_COMPONENTS_DIR = (
    Path("shared") / "ui" / "spa" / "src" / "lib" / "components"
)
_REQUIRED_ENVELOPE_FIELDS: tuple[str, ...] = (
    "summary",
    "next_actions",
    "artifacts",
)
_SUMMARY_REFERENCE_MIN_RATIO = 0.5


def _count_consumer_files(root: Path, glob: str) -> tuple[int, int]:
    """Return ``(consumer_count, with_summary_count)`` for ``glob``.

    A consumer is any file under the search root mentioning
    ``ToolResponse``. ``with_summary_count`` is the subset that also
    references the ``summary`` field, used as the V3 #30a uptake proxy.
    """
    if not root.is_dir():
        return (0, 0)
    consumers = 0
    with_summary = 0
    for path in sorted(root.rglob(glob)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "ToolResponse" not in text:
            continue
        consumers += 1
        if "summary" in text:
            with_summary += 1
    return (consumers, with_summary)


def check_transport_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L10 — transport envelope-field preservation."""
    api_dir = repo_root / _API_DIR
    envelopes_path = repo_root / _ENVELOPES_RELPATH

    missing_paths: list[str] = []
    if not api_dir.is_dir():
        missing_paths.append(str(_API_DIR))
    if not envelopes_path.is_file():
        missing_paths.append(str(_ENVELOPES_RELPATH))
    if missing_paths:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                f"{len(missing_paths)} transport-surface path(s) missing "
                "— envelope contract cannot be validated"
            ),
            severity="critical",
            evidence=tuple(missing_paths),
        )

    text = envelopes_path.read_text(encoding="utf-8")
    missing_fields = tuple(
        f for f in _REQUIRED_ENVELOPE_FIELDS if f not in text
    )
    if missing_fields:
        return LayerFinding(
            layer=_LAYER,
            status="regressed",
            summary=(
                "ToolResponse envelope missing V3 #30a field(s) — "
                "transport will strip role context"
            ),
            severity="high",
            evidence=missing_fields,
            next_actions=(
                "restore the missing field(s) on ToolResponse in "
                "shared/mcp/schemas/envelopes.py",
            ),
        )

    api_consumers, api_with_summary = _count_consumer_files(
        repo_root / _API_DIR, "*.py"
    )
    spa_consumers, spa_with_summary = _count_consumer_files(
        repo_root / _SPA_COMPONENTS_DIR, "*.svelte"
    )
    total_consumers = api_consumers + spa_consumers
    total_with_summary = api_with_summary + spa_with_summary

    drops = signals.get("transport_drops")
    if isinstance(drops, int) and drops > 0:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                f"{drops} transport envelope-field drop(s) observed "
                "— role context truncated en route to user"
            ),
            severity="medium",
            evidence=(f"transport_drops={drops}",),
            next_actions=(
                "trace which serializer / component dropped the "
                "summary / next_actions / artifacts fields",
            ),
        )

    if total_consumers == 0:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                "no ToolResponse consumers found across API + SPA — "
                "envelope likely never reaches the user surface"
            ),
            severity="medium",
            evidence=(
                f"api_consumers={api_consumers}",
                f"spa_consumers={spa_consumers}",
            ),
        )

    ratio = total_with_summary / total_consumers
    if ratio < _SUMMARY_REFERENCE_MIN_RATIO:
        return LayerFinding(
            layer=_LAYER,
            status="warning",
            summary=(
                f"only {total_with_summary}/{total_consumers} "
                f"ToolResponse consumer(s) reference summary "
                f"({ratio:.0%}) — roles' summaries not reaching user"
            ),
            severity="medium",
            evidence=(
                f"api_with_summary={api_with_summary}/{api_consumers}",
                f"spa_with_summary={spa_with_summary}/{spa_consumers}",
            ),
            next_actions=(
                "bind summary / next_actions / artifacts in the SPA "
                "components that render ToolResponse",
            ),
        )

    return LayerFinding(
        layer=_LAYER,
        status="clean",
        summary=(
            f"envelope contract intact; "
            f"{total_with_summary}/{total_consumers} consumer(s) "
            f"reference summary ({ratio:.0%})"
        ),
    )


__all__ = ["check_transport_layer"]

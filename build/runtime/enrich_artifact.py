"""Post-process a ``BuildArtifact`` to populate ``kg_impact`` automatically.

STORY-7.3.{1,3} fallback path: the role daemon may have skipped the KG call,
but we still need ``kg_impact`` populated before the artifact can be sealed
(the engineer refuse-to-seal rule in ``build_artifact.py`` blocks otherwise).

Used by:
  * ``build/bridge/report_parser.py`` — auto-enrich v1-bridge artifacts before
    they hit ``build_completed`` / the auditor (STORY-7.4.3).
  * CI gate in ``build/runtime/cli.py kg enrich``.
  * Manual debugging from the shell.

Modes
-----
``fill``    — only compute ``kg_impact`` when the artifact's list is empty.
``verify``  — when ``kg_impact`` is non-empty, recompute and log a warning on
              mismatch (the auditor still has authoritative say).
``both``    — fill if empty, otherwise verify.
"""

from __future__ import annotations

import logging
from typing import Literal

from shared.schemas.build.build_artifact import BuildArtifact, KGImpactNode

from build.runtime.kg_caller import DatawrightKGHook, EngineerKGHook

logger = logging.getLogger(__name__)

Mode = Literal["fill", "verify", "both"]


def _resolve_repo(artifact: BuildArtifact, repo: str | None) -> str | None:
    """Prefer caller-supplied repo, then metadata extras (v1-bridge stashes it)."""
    if repo:
        return repo
    extras = getattr(artifact.metadata, "extras", None) or {}
    if isinstance(extras, dict):
        for k in ("repo", "v1_repo", "repository"):
            v = extras.get(k)
            if isinstance(v, str) and v:
                return v
    # ``ArtifactMetadata`` may also expose ``repo`` directly on some versions.
    return getattr(artifact.metadata, "repo", None)


def _enrich_engineer(artifact: BuildArtifact, repo: str, mode: Mode) -> BuildArtifact:
    """Fill or verify ``kg_impact`` for an engineer artifact."""
    if not artifact.code_changes:
        return artifact
    hook = EngineerKGHook(project_id=artifact.project_id)
    if mode in ("fill", "both") and not artifact.kg_impact:
        computed = hook.compute_kg_impact(artifact.code_changes, repo=repo)
        if computed:
            artifact.kg_impact = computed
            logger.info("enrich_artifact_filled", extra={
                "directive_id": artifact.directive_id, "count": len(computed)})
        return artifact
    if mode in ("verify", "both") and artifact.kg_impact:
        computed = hook.compute_kg_impact(artifact.code_changes, repo=repo)
        claimed = {n.node_id for n in artifact.kg_impact}
        actual = {n.node_id for n in computed}
        missing = actual - claimed
        extra = claimed - actual
        if missing or extra:
            logger.warning("enrich_artifact_mismatch", extra={
                "directive_id": artifact.directive_id,
                "missing_count": len(missing), "extra_count": len(extra)})
    return artifact


def _enrich_datawright(artifact: BuildArtifact, repo: str, mode: Mode) -> BuildArtifact:
    """Register each created/modified pipeline output as a Document node."""
    if mode not in ("fill", "both"):
        return artifact
    outputs = [c for c in artifact.code_changes if c.change_type in ("create", "modify")]
    if not outputs:
        return artifact
    hook = DatawrightKGHook(project_id=artifact.project_id)
    seen = {n.node_id for n in artifact.kg_impact}
    for change in outputs:
        # No explicit source-data linkage available from the v1 report;
        # callers using the cli/MCP path can pass --source-nodes for richer
        # edges. Here we still create the Document node so the KG sees it.
        node_id = hook.register_output(change.path, source_data_nodes=[], repo=repo)
        if node_id and node_id not in seen:
            try:
                artifact.kg_impact.append(KGImpactNode(
                    node_id=node_id, node_type="Document", impact_distance=0))
                seen.add(node_id)
            except Exception:
                continue
    return artifact


def enrich_build_artifact(artifact: BuildArtifact, *,
                          repo: str | None = None,
                          mode: Mode = "both") -> BuildArtifact:
    """Populate / verify ``kg_impact`` based on the artifact's role.

    * ``engineer``     → call ``EngineerKGHook.compute_kg_impact``.
    * ``operator``     → no-op (operator has no ``code_changes``; ownership
      check is a *pre-action* hook, not part of the BuildArtifact contract).
    * ``datawright``   → register each pipeline output as a Document node
      via ``DatawrightKGHook.register_output``.

    Failures are logged but never raised: the auditor (STORY-7.4.3) will flag
    any leftover ``kg_impact_missing`` so we degrade gracefully on KG outage.
    """
    resolved_repo = _resolve_repo(artifact, repo)
    if not resolved_repo:
        logger.warning("enrich_artifact_no_repo",
                       extra={"directive_id": artifact.directive_id})
        return artifact
    try:
        if artifact.role == "engineer":
            return _enrich_engineer(artifact, resolved_repo, mode)
        if artifact.role == "datawright":
            return _enrich_datawright(artifact, resolved_repo, mode)
        return artifact  # operator: nothing to do at artifact time
    except Exception as exc:  # noqa: BLE001 — graceful degradation
        logger.warning("enrich_artifact_failed", extra={
            "directive_id": artifact.directive_id, "err": str(exc)})
        return artifact


__all__ = ["enrich_build_artifact"]

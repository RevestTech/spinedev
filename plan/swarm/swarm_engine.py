"""
Technical Review Swarm engine (LangGraph subgraph).

Implements `STORY-1.2.1` (swarm orchestration primitive) from
`docs/BACKLOG.md` and REQ-INIT-1 FR-3 (`docs/PRD.md`).

Hosted inside the architect daemon. From the outside the daemon still takes
a markdown directive and writes a markdown TRD; LangGraph is an
implementation detail that gives us typed state + checkpoint/resume.

Graph:
    start → compose_swarm → dispatch_scouts → wait_for_scouts
          → synthesize → validate_trd → end
                              ↑               │
                              └──── retry ────┘  (validation_errors)

LangGraph is OPTIONAL (lazy import); when absent the engine runs the same
node functions in a linear Python loop (test-friendly).

CLI:
    python -m plan.swarm.swarm_engine --prd <prd.json> --project-type web_app
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

from plan.artifacts.prd_v1 import PRDv1
from plan.artifacts.trd_v1 import TRDv1

from .composition_rules import get_swarm_for
from .scout_contribution import (
    DEFAULT_LENS_FOR_ROLE, Finding, FindingKind,
    ScoutContribution, ScoutRole, Severity,
)
from .synthesis import SynthesisError, synthesize_trd

log = logging.getLogger("spine.swarm")


class SwarmState(TypedDict, total=False):
    run_id: str
    prd_payload: dict[str, Any]
    project_type: str
    pipeline_version: str
    roster: list[str]
    directives: dict[str, str]
    contributions: list[dict[str, Any]]
    unrun: list[str]
    synthesis_attempts: int
    trd_payload: Optional[dict[str, Any]]
    validation_errors: list[str]
    last_node: str


# Adapter — default writes a directive under teams/<role>/directive.md
# (existing Spine daemon contract). Tests inject a fake; production wires
# this to router.sh / MCP `plan_dispatch`.
ScoutDispatcher = Callable[[ScoutRole, str, dict[str, Any]], ScoutContribution]


@dataclass
class FileDispatcher:
    """Default dispatcher: writes a directive; returns a stub contribution."""

    teams_root: Path = field(default_factory=lambda: Path("teams"))
    stub_only: bool = True

    def __call__(self, role: ScoutRole, scope: str, prd: dict[str, Any]) -> ScoutContribution:
        role_dir = self.teams_root / role.value
        role_dir.mkdir(parents=True, exist_ok=True)
        (role_dir / "directive.md").write_text(
            f"# Swarm directive — {role.value}\n\n## Scope\n{scope}\n\n"
            f"## PRD\n```json\n{json.dumps(prd, default=str, indent=2)}\n```\n",
            encoding="utf-8",
        )
        if not self.stub_only:
            raise NotImplementedError("Real scout adapter not wired.")
        return ScoutContribution(
            scout_role=role, lens=DEFAULT_LENS_FOR_ROLE[role], scope_received=scope,
            findings=[Finding(
                severity=Severity.LOW, kind=FindingKind.RECOMMENDATION,
                file_or_section=f"{role.value}-stub",
                description=f"Stub finding from {role.value} scout.",
                recommendation=f"Stub recommendation from {role.value}.")],
            model_used="stub")


# ── Node implementations — plain functions; LangGraph wraps them. ────────────


def node_compose_swarm(state: SwarmState) -> SwarmState:
    roster = [r.value for r in get_swarm_for(state.get("project_type", "custom"))]
    return {**state, "roster": roster, "last_node": "compose_swarm"}


def node_dispatch_scouts(state: SwarmState, dispatcher: ScoutDispatcher) -> SwarmState:
    contribs: list[dict[str, Any]] = list(state.get("contributions") or [])
    unrun: list[str] = list(state.get("unrun") or [])
    directives: dict[str, str] = dict(state.get("directives") or {})
    scope = (state.get("prd_payload", {}).get("problem_statement")
             or "Assess the PRD against your lens.")
    for role_name in state.get("roster", []):
        try:
            role = ScoutRole(role_name)
        except ValueError:
            unrun.append(role_name)
            continue
        try:
            contribs.append(
                dispatcher(role, scope, state.get("prd_payload", {})).model_dump(mode="json")
            )
            directives[role.value] = f"teams/{role.value}/directive.md"
        except Exception as e:  # noqa: BLE001 — swarm-level resilience
            log.warning("scout %s failed: %s", role_name, e)
            unrun.append(role_name)
    return {**state, "contributions": contribs, "unrun": unrun,
            "directives": directives, "last_node": "dispatch_scouts"}


def node_wait_for_scouts(state: SwarmState) -> SwarmState:
    """No-op for synchronous FileDispatcher. Async adapters poll here."""
    return {**state, "last_node": "wait_for_scouts"}


def _push_err(state: SwarmState, msg: str, node: str) -> SwarmState:
    errs = list(state.get("validation_errors", [])) + [msg]
    return {**state, "validation_errors": errs, "last_node": node}


def node_synthesize(state: SwarmState) -> SwarmState:
    attempts = state.get("synthesis_attempts", 0) + 1
    contribs = [ScoutContribution.model_validate(c) for c in state.get("contributions", [])]
    prd = PRDv1.model_validate(state["prd_payload"])
    try:
        trd = synthesize_trd(prd, contribs)
    except SynthesisError as e:
        log.error("synthesis attempt %d failed: %s", attempts, e)
        return {**_push_err(state, str(e), "synthesize"), "synthesis_attempts": attempts}
    return {**state, "synthesis_attempts": attempts,
            "trd_payload": trd.model_dump(mode="json"),
            "validation_errors": [], "last_node": "synthesize"}


def node_validate_trd(state: SwarmState) -> SwarmState:
    payload = state.get("trd_payload")
    if payload is None:
        return _push_err(state, "no TRD produced", "validate_trd")
    try:
        TRDv1.model_validate(payload)
    except Exception as e:  # noqa: BLE001
        return _push_err(state, str(e), "validate_trd")
    return {**state, "validation_errors": [], "last_node": "validate_trd"}


# ── Graph builder (lazy LangGraph) + linear fallback. ────────────────────────


def _make_checkpointer() -> Any:
    """Pick the best LangGraph checkpointer available; None if neither installed."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]
        return SqliteSaver.from_conn_string(":memory:")
    except Exception:
        try:
            from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import-not-found]
            return MemorySaver()
        except Exception:
            return None


def _build_langgraph(dispatcher: ScoutDispatcher) -> Optional[Any]:
    """Return a compiled LangGraph app, or None if LangGraph isn't installed."""
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    except Exception:
        return None
    g: Any = StateGraph(SwarmState)
    g.add_node("compose_swarm", node_compose_swarm)
    g.add_node("dispatch_scouts", lambda s: node_dispatch_scouts(s, dispatcher))
    g.add_node("wait_for_scouts", node_wait_for_scouts)
    g.add_node("synthesize", node_synthesize)
    g.add_node("validate_trd", node_validate_trd)
    g.set_entry_point("compose_swarm")
    for src, dst in [("compose_swarm", "dispatch_scouts"),
                     ("dispatch_scouts", "wait_for_scouts"),
                     ("wait_for_scouts", "synthesize"),
                     ("synthesize", "validate_trd")]:
        g.add_edge(src, dst)

    def _post_validate(s: SwarmState) -> str:
        errs = s.get("validation_errors") or []
        return "synthesize" if errs and s.get("synthesis_attempts", 0) < 2 else END

    g.add_conditional_edges("validate_trd", _post_validate)
    cp = _make_checkpointer()
    return g.compile(checkpointer=cp) if cp else g.compile()


def _run_linear(initial: SwarmState, dispatcher: ScoutDispatcher) -> SwarmState:
    """LangGraph-free fallback that runs the same nodes in order."""
    state = node_compose_swarm(initial)
    state = node_dispatch_scouts(state, dispatcher)
    state = node_wait_for_scouts(state)
    for _ in range(2):
        state = node_synthesize(state)
        state = node_validate_trd(state)
        if not state.get("validation_errors"):
            break
    return state


def run_swarm(
    prd: PRDv1, project_type: str, *,
    pipeline_version: str = "spine-default@1",
    dispatcher: Optional[ScoutDispatcher] = None,
    resume_run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run the swarm end-to-end. Returns the final state dict.

    Failure handling (FR-3): scout failures land in `state['unrun']` and
    synthesis proceeds with remaining lenses (degraded TRD). Synthesis
    failures retry once; second failure populates `validation_errors` for
    the caller to escalate.
    """
    dispatcher = dispatcher or FileDispatcher()
    initial: SwarmState = {
        "run_id": resume_run_id or str(uuid.uuid4()),
        "prd_payload": prd.model_dump(mode="json"),
        "project_type": project_type, "pipeline_version": pipeline_version,
        "contributions": [], "unrun": [], "synthesis_attempts": 0,
        "validation_errors": [], "last_node": "start",
    }
    app = _build_langgraph(dispatcher)
    started = time.time()
    if app is None:
        log.info("LangGraph unavailable; using linear fallback")
        final = _run_linear(initial, dispatcher)
    else:
        cfg = {"configurable": {"thread_id": initial["run_id"]}}
        final = app.invoke(initial, config=cfg)  # type: ignore[assignment]
    final["wall_time_s"] = round(time.time() - started, 3)
    return dict(final)


def _cli() -> int:
    p = argparse.ArgumentParser(prog="spine-swarm")
    p.add_argument("--prd", required=True, help="Path to a PRD JSON file")
    p.add_argument("--project-type", required=True)
    p.add_argument("--resume", default=None, help="Existing run_id to resume")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    prd_path = Path(args.prd)
    if not prd_path.exists():
        print(f"PRD file not found: {prd_path}", file=sys.stderr)
        return 2
    prd = PRDv1.model_validate_json(prd_path.read_text(encoding="utf-8"))
    state = run_swarm(prd, args.project_type, resume_run_id=args.resume)
    print(json.dumps(state, indent=2, default=str))
    return 0 if not state.get("validation_errors") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())


__all__ = [
    "FileDispatcher", "ScoutDispatcher", "SwarmState",
    "node_compose_swarm", "node_dispatch_scouts", "node_synthesize",
    "node_validate_trd", "node_wait_for_scouts", "run_swarm",
]

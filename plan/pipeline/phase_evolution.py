"""phase_evolution.py — runtime handling of pipeline-manifest evolution.

`STORY-9.1.4` (`docs/BACKLOG.md`): phase set is editable via `sdlc-pipeline.yaml`
with explicit runtime semantics for the awkward edges — phase renamed /
removed / reordered / gate or rollback changed. Backs PRD REQ-INIT-9 FR-2
(canonical phase set, pipeline-as-data) + REQ-INIT-1 FR-7/FR-8 (override
hierarchy + required rationale) (`docs/PRD.md`).

Layering: `manifest_loader.py` owns the resolved-manifest shape + hash;
`project_lock.py` owns the lock + migration writer; THIS module owns the
*detection*, *classification*, and *planning* of evolution events. It
delegates the actual write to `project_lock.migrate_locked_project`.

DB I/O via `psql` subprocess (matches `project_lock.py`).
"""
from __future__ import annotations

import json, os, subprocess
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .manifest_loader import PipelineManifest
from .project_lock import MigrationResult, get_locked_pipeline, migrate_locked_project
from .versioning import compute_pipeline_version

EvolutionType = Literal["phase_added", "phase_removed", "phase_renamed",
                        "phase_reordered", "gate_changed", "rollback_changed"]


class PhaseEvolutionEvent(BaseModel):
    """One meaningful change between two pipeline manifest versions."""
    model_config = ConfigDict(extra="forbid")
    event_type: EvolutionType
    pipeline_version_old: str
    pipeline_version_new: str
    phase_id: str
    # Populated by `affected_projects()`; empty in pure-diff mode so
    # `detect_evolution_events` stays DB-free.
    affected_projects: list[str] = Field(default_factory=list)
    auto_migratable: bool = False
    rationale: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class MigrationPlan(BaseModel):
    """Concrete steps to migrate one project across one evolution event."""
    model_config = ConfigDict(extra="forbid")
    project_id: str
    event: PhaseEvolutionEvent
    steps: list[str]
    requires_user_action: bool
    blockers: list[str] = Field(default_factory=list)


def _psql(sql: str) -> str:
    """Mirrors `project_lock._psql` so the package behaves uniformly."""
    url = os.environ.get("SPINE_DB_URL")
    if not url: raise RuntimeError("SPINE_DB_URL not set — phase_evolution needs a database")
    r = subprocess.run(["psql", url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def _phase_map(m: PipelineManifest) -> dict[str, dict[str, Any]]:
    return {p.get("id"): p for p in (m.phases or []) if p.get("id")}


def _phase_order(m: PipelineManifest) -> list[str]:
    return [p.get("id") for p in (m.phases or []) if p.get("id")]


def _signature(p: dict[str, Any]) -> tuple[str, str, str]:
    """Rename heuristic identity: label + subsystem + artifact."""
    return (str(p.get("label") or ""), str(p.get("subsystem") or ""), str(p.get("artifact") or ""))


def _detect_renames(adds: list[dict], rems: list[dict]
                    ) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Pair add/remove with matching signatures; return (renames, leftovers)."""
    renames: list[tuple[dict, dict]] = []; rems_left = list(rems); adds_left: list[dict] = []
    for a in adds:
        m = next((r for r in rems_left if _signature(r) == _signature(a)), None)
        if m: renames.append((m, a)); rems_left.remove(m)
        else: adds_left.append(a)
    return renames, adds_left, rems_left


def _mk(t: str, vo: str, vn: str, pid: str, **kw) -> PhaseEvolutionEvent:
    return PhaseEvolutionEvent(event_type=t, pipeline_version_old=vo,
                               pipeline_version_new=vn, phase_id=pid, **kw)


def can_auto_migrate(event: PhaseEvolutionEvent) -> bool:
    """Closed-by-default policy. Yes: phase_added, phase_reordered. No: rename,
    remove, gate_changed, rollback_changed (each could surprise an operator
    managing an in-flight project; require explicit review)."""
    return event.event_type in ("phase_added", "phase_reordered")


def detect_evolution_events(old: PipelineManifest,
                            new: PipelineManifest) -> list[PhaseEvolutionEvent]:
    """Compare two pipeline manifests; emit one event per meaningful change.

    Identity is `phase.id`. A rename surfaces as removed+added unless the
    `label/subsystem/artifact` triple matches — `_detect_renames` then
    merges them into a single `phase_renamed` event.
    """
    v_old, v_new = compute_pipeline_version(old), compute_pipeline_version(new)
    if v_old == v_new: return []
    o_map, n_map = _phase_map(old), _phase_map(new)
    out: list[PhaseEvolutionEvent] = []
    added   = [p for pid, p in n_map.items() if pid not in o_map]
    removed = [p for pid, p in o_map.items() if pid not in n_map]
    renames, adds_left, rems_left = _detect_renames(added, removed)

    for old_p, new_p in renames:
        out.append(_mk("phase_renamed", v_old, v_new, new_p["id"],
            detail={"from": old_p["id"], "to": new_p["id"]},
            rationale="phase id changed; label/subsystem/artifact unchanged"))
    for p in adds_left:
        out.append(_mk("phase_added", v_old, v_new, p["id"], rationale=f"new phase {p['id']!r}"))
    for p in rems_left:
        out.append(_mk("phase_removed", v_old, v_new, p["id"], rationale=f"phase {p['id']!r} removed"))

    # Reorder: only when the order of phases present in BOTH manifests changes.
    o_order = [pid for pid in _phase_order(old) if pid in n_map]
    n_order = [pid for pid in _phase_order(new) if pid in o_map]
    if o_order != n_order and o_order and n_order:
        for i, pid in enumerate(n_order):
            if i >= len(o_order) or o_order[i] != pid:
                out.append(_mk("phase_reordered", v_old, v_new, pid,
                    detail={"old_order": o_order, "new_order": n_order},
                    rationale=f"phase order changed at {pid!r}"))
                break

    # Gate / rollback changes per phase still present in both.
    for pid in (set(o_map) & set(n_map)):
        og, ng = o_map[pid].get("gate"), n_map[pid].get("gate")
        if og != ng:
            out.append(_mk("gate_changed", v_old, v_new, pid,
                detail={"old_gate": og, "new_gate": ng},
                rationale=f"gate on {pid!r} changed"))
        orb, nrb = o_map[pid].get("rollback_to"), n_map[pid].get("rollback_to")
        if orb != nrb:
            out.append(_mk("rollback_changed", v_old, v_new, pid,
                detail={"old_rollback_to": orb, "new_rollback_to": nrb},
                rationale=f"rollback_to on {pid!r} changed"))
    for ev in out: ev.auto_migratable = can_auto_migrate(ev)
    return out


def affected_projects(event: PhaseEvolutionEvent, db_url: Optional[str] = None) -> list[str]:
    """In-flight projects locked to `event.pipeline_version_old` that this touches."""
    if db_url: os.environ["SPINE_DB_URL"] = db_url
    rows = _psql(
        f"SELECT COALESCE(project_uuid::text, id::text) FROM spine_lifecycle.project "
        f"WHERE pipeline_version = '{event.pipeline_version_old}' "
        f"AND status IN ('active','paused');")
    return [r for r in rows.splitlines() if r.strip()]


def _current_phase_of(project_id: str) -> str:
    raw = _psql(f"SELECT current_phase FROM spine_lifecycle.project "
                f"WHERE project_uuid::text = '{project_id}' OR id::text = '{project_id}' LIMIT 1;")
    return (raw or "").strip()


def migration_plan(event: PhaseEvolutionEvent, project_id: str) -> MigrationPlan:
    """Per-project step list. Identifies blockers up-front so the UI can
    refuse to offer the action when there is no safe path."""
    cur = _current_phase_of(project_id)
    steps = ["capability_check actor (require can_modify_sdlc_pipeline)",
             f"diff lock vs target version {event.pipeline_version_new}"]
    blockers: list[str] = []
    requires_user = not event.auto_migratable

    if event.event_type == "phase_removed" and cur == event.phase_id:
        blockers.append(f"project is currently in '{event.phase_id}', which the new manifest removes")
    if event.event_type == "phase_renamed":
        old_id, new_id = event.detail.get("from"), event.detail.get("to")
        if cur == old_id:
            steps.append(f"rewrite project.current_phase: {old_id} -> {new_id}")
            steps.append("rewrite phase_history.phase rows for this project (same swap)")
        requires_user = True
    if event.event_type == "gate_changed":
        steps.append(f"surface gate change for {event.phase_id!r} to operator")
        requires_user = True

    steps.append("project_lock.migrate_locked_project(...) writes lock + audit")
    return MigrationPlan(project_id=project_id, event=event, steps=steps,
                         requires_user_action=requires_user, blockers=blockers)


def execute_migration(plan: MigrationPlan, actor: str, rationale: str, *,
                      dry_run: bool = False) -> MigrationResult | dict[str, Any]:
    """Apply the migration. Raises on blockers; respects `dry_run`. Reconstitutes
    the target manifest via the currently resolved pipeline — callers wanting
    a non-current target should call `migrate_locked_project` directly."""
    if plan.blockers: raise RuntimeError(f"cannot execute migration: blockers={plan.blockers}")
    if dry_run: return {"dry_run": True, "project_id": plan.project_id,
                        "event_type": plan.event.event_type, "steps": plan.steps}
    from .manifest_loader import load_pipeline
    return migrate_locked_project(plan.project_id, load_pipeline(project_id=plan.project_id),
                                  actor, rationale)


def evolution_report(old: str, new: str, db_url: Optional[str] = None) -> dict[str, Any]:
    """Human-readable summary for the UI. Reconstitutes manifests via locks."""
    if db_url: os.environ["SPINE_DB_URL"] = db_url
    q = ("SELECT COALESCE(project_uuid::text, id::text) FROM spine_lifecycle.project "
         "WHERE pipeline_version = '{}' LIMIT 1;")
    a, b = _psql(q.format(old)).strip(), _psql(q.format(new)).strip()
    if not a or not b:
        return {"ok": False, "reason": "no projects locked to one of the provided versions"}
    events = detect_evolution_events(get_locked_pipeline(a), get_locked_pipeline(b))
    for ev in events: ev.affected_projects = affected_projects(ev)
    return {"ok": True, "from": old, "to": new, "event_count": len(events),
            "auto_migratable_count": sum(1 for e in events if e.auto_migratable),
            "manual_review_count":   sum(1 for e in events if not e.auto_migratable),
            "events": [e.model_dump() for e in events]}


__all__ = ["EvolutionType", "MigrationPlan", "PhaseEvolutionEvent", "affected_projects",
           "can_auto_migrate", "detect_evolution_events", "evolution_report",
           "execute_migration", "migration_plan"]


# CLI — exit codes per spec: 0=ok, 2=manual review needed, 3=db error, 64=usage.
def _cli(argv: list[str]) -> int:
    import sys
    if not argv:
        print("usage: phase_evolution.py detect|affected|report <args>", file=sys.stderr); return 64
    cmd, *r = argv
    try:
        if cmd == "detect" and len(r) >= 2:
            with open(r[0]) as fa, open(r[1]) as fb:
                old, new = PipelineManifest(**json.load(fa)), PipelineManifest(**json.load(fb))
            events = detect_evolution_events(old, new)
            print(json.dumps([e.model_dump() for e in events], indent=2, default=str))
            return 0 if all(e.auto_migratable for e in events) else 2
        if cmd == "affected" and len(r) >= 3:
            ev = PhaseEvolutionEvent(event_type=r[0], pipeline_version_old=r[1],
                pipeline_version_new=r[2], phase_id=r[3] if len(r) > 3 else "")
            print(json.dumps(affected_projects(ev), indent=2)); return 0
        if cmd == "report" and len(r) >= 2:
            print(json.dumps(evolution_report(r[0], r[1]), indent=2, default=str)); return 0
        print(f"bad usage for {cmd!r}", file=sys.stderr); return 64
    except subprocess.CalledProcessError as e:
        print(f"db_error: {e.stderr}", file=sys.stderr); return 3


if __name__ == "__main__":
    import sys; sys.exit(_cli(sys.argv[1:]))

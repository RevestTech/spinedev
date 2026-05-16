"""versioning.py — sha256 versions, git-committed edits, history walk.

Implements `STORY-1.7.4` (every pipeline edit = git commit with author +
timestamp + REQUIRED rationale) from `docs/BACKLOG.md`. Backs PRD REQ-INIT-1
FR-8 in `docs/PRD.md`: "rationale is a required field on the edit action,
not optional". Refusing to accept an empty rationale is the whole point of
this module — it's the audit anchor for `EPIC-1.7`.

Git is invoked via the `git` subprocess (no GitPython dep, per constraints).
Commits use a structured trailer ("Actor: …\\nRationale: …") that
`pipeline_history()` parses on the way back out.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from .capability_checker import assert_rationale, require_capability
from .manifest_loader import PipelineManifest


@dataclass
class CommitResult:
    """Outcome of `commit_pipeline_edit`."""

    new_version: str
    commit_sha: str
    file_path: Path


@dataclass
class PipelineEdit:
    """One historical edit row, parsed from `git log <manifest>`."""

    commit_sha: str
    actor: str
    rationale: str
    timestamp: datetime
    subject: str


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_pipeline_version(manifest: PipelineManifest) -> str:
    """sha256 of canonical JSON of the manifest body (transport hash).

    Excludes derived/cosmetic fields (`resolved_version`, `inheritance_chain`)
    so the version is content-addressable and stable across loads.
    """
    body = manifest.model_dump(exclude={"resolved_version", "inheritance_chain"})
    return "sha256:" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git subcommand with structured failure surfacing."""
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _git_root(path: Path) -> Path:
    """Locate the git repo root for `path`; raises if not in a repo."""
    r = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                       check=True, capture_output=True, text=True)
    return Path(r.stdout.strip())


def _first_line_summary(new_content: dict, prev_content: dict) -> str:
    """Short, deterministic subject line. Mentions phases-added if obvious."""
    if not prev_content:
        return "pipeline: initial commit"
    new_phases = {p.get("id") for p in (new_content.get("phases") or [])}
    old_phases = {p.get("id") for p in (prev_content.get("phases") or [])}
    added = sorted(new_phases - old_phases)
    removed = sorted(old_phases - new_phases)
    if added and not removed: return f"pipeline: add phase(s) {','.join(added)}"
    if removed and not added: return f"pipeline: remove phase(s) {','.join(removed)}"
    if added or removed: return f"pipeline: +{','.join(added)} / -{','.join(removed)}"
    nv = new_content.get("version"); ov = prev_content.get("version")
    if nv != ov: return f"pipeline: version {ov} → {nv}"
    return "pipeline: edit"


def commit_pipeline_edit(manifest_path: Path, new_content: dict, actor: str,
                         rationale: str,
                         pipeline_for_capcheck: Optional[PipelineManifest] = None
                         ) -> CommitResult:
    """Write `new_content` to `manifest_path` and commit it.

    Order: (1) rationale required (FR-8 — refused empty); (2) capability check;
    (3) write file; (4) `git add`; (5) `git commit` with the structured trailer;
    (6) compute new sha; (7) return `CommitResult`.

    `pipeline_for_capcheck` should be the *currently active* pipeline so the
    grant lookup is meaningful. If omitted, the capability check is skipped —
    callers should only do this for system-level bootstrap (e.g. shipping
    `sdlc-pipeline-default.yaml`).
    """
    rationale = assert_rationale(actor, "can_modify_sdlc_pipeline", rationale)
    if pipeline_for_capcheck is not None:
        require_capability(actor, "can_modify_sdlc_pipeline", pipeline_for_capcheck)
    manifest_path = manifest_path.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    prev_content: dict = {}
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as fh:
            prev_content = yaml.safe_load(fh) or {}
    with manifest_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(new_content, fh, sort_keys=False, default_flow_style=False)
    repo_root = _git_root(manifest_path)
    rel = manifest_path.relative_to(repo_root)
    _run_git(["add", str(rel)], cwd=repo_root)
    subject = _first_line_summary(new_content, prev_content)
    body = f"{subject}\n\nActor: {actor}\nRationale: {rationale}\n"
    _run_git(["commit", "-m", body], cwd=repo_root)
    sha = _run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    new_version = "sha256:" + hashlib.sha256(_canonical(new_content).encode("utf-8")).hexdigest()
    return CommitResult(new_version=new_version, commit_sha=sha, file_path=manifest_path)


def pipeline_history(manifest_path: Path) -> list[PipelineEdit]:
    """Walk `git log <manifest>` and parse Actor/Rationale trailers.

    Each commit becomes a `PipelineEdit`. Commits without an `Actor:` line are
    surfaced with actor="<unknown>" — the caller can use that to flag pre-FR-8
    history that should not occur in a freshly-shipped Spine install.
    """
    manifest_path = manifest_path.resolve()
    if not manifest_path.exists():
        return []
    repo_root = _git_root(manifest_path)
    rel = manifest_path.relative_to(repo_root)
    fmt = "%H%x00%aI%x00%s%x00%b%x1e"
    r = _run_git(["log", f"--pretty=format:{fmt}", "--", str(rel)], cwd=repo_root)
    out: list[PipelineEdit] = []
    for raw in r.stdout.split("\x1e"):
        raw = raw.strip("\n\r ")
        if not raw: continue
        parts = raw.split("\x00")
        if len(parts) < 4: continue
        sha, iso, subject, body = parts[0], parts[1], parts[2], "\x00".join(parts[3:])
        actor = "<unknown>"; rationale = ""
        for line in body.splitlines():
            if line.startswith("Actor:"): actor = line.split(":", 1)[1].strip()
            elif line.startswith("Rationale:"): rationale = line.split(":", 1)[1].strip()
        try: ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError: ts = datetime.utcnow()
        out.append(PipelineEdit(commit_sha=sha, actor=actor, rationale=rationale,
                                timestamp=ts, subject=subject))
    return out


__all__ = [
    "CommitResult",
    "PipelineEdit",
    "commit_pipeline_edit",
    "compute_pipeline_version",
    "pipeline_history",
]

"""Manifest + output diff (STORY-3.2.3).

Two questions the SDLC asks constantly:
    Q1. "What changed between yesterday's run and today's run?"
        → diff_manifests: structural field-by-field comparison.
    Q2. "Did model X produce the same output as model Y on the same
        directive?" → diff_outputs: compare hashes from the audit log.

Drift is categorised so callers can render critical changes in red and
noise (timestamps, uuids) in grey.

Stack: stdlib + Pydantic v2.
"""
from __future__ import annotations
import os
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.reproducibility.manifest import (DEFAULT_DB_URL, RunManifest, _esc,
                                             _psql)

_PYD = ConfigDict(extra="forbid", protected_namespaces=())

# Fields whose change implies the new run is NOT reproducing the old one.
CRITICAL_FIELDS = frozenset({
    "role.role_prompt_sha256", "pipeline.pipeline_version",
    "pipeline.pipeline_sha256", "runtime.model_id",
    "inputs.directive_sha256", "inputs.prd_sha256",
    "inputs.trd_sha256", "inputs.org_bundle_sha256"})

# Fields that may differ harmlessly between two valid replays.
MINOR_FIELDS = frozenset({
    "runtime.temperature", "runtime.max_tokens",
    "dependencies.python_packages_lockfile_sha",
    "dependencies.node_packages_lockfile_sha",
    "git_state.dirty", "git_state.dirty_files"})

# Fields that ALWAYS differ between captures — never report.
IGNORED_FIELDS = frozenset({"manifest_uuid", "created_at", "metadata"})


class FieldDiff(BaseModel):
    """One field-level diff entry."""
    model_config = _PYD
    field_path: str
    severity: str  # "critical" | "minor" | "informational"
    old_value: Any
    new_value: Any

class ManifestDiff(BaseModel):
    """Result of `diff_manifests`. `is_reproducible` iff no critical diffs."""
    model_config = _PYD
    manifest_a_uuid: str
    manifest_b_uuid: str
    diffs: list[FieldDiff] = Field(default_factory=list)
    critical_count: int = 0
    minor_count: int = 0
    informational_count: int = 0
    is_reproducible: bool = True

class OutputDiff(BaseModel):
    """Result of `diff_outputs`. `outputs_match` iff hashes are equal."""
    model_config = _PYD
    directive_a: str
    directive_b: str
    output_hash_a: Optional[str] = None
    output_hash_b: Optional[str] = None
    outputs_match: bool = False
    diff_summary: list[str] = Field(default_factory=list)


def _flatten(prefix: str, obj: Any, out: dict[str, Any]) -> None:
    """Flatten a nested dict to dotted keys; non-dicts copied verbatim."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out[prefix] = obj

def _classify(path: str) -> str:
    """Map a dotted field path to a severity tier."""
    if path in CRITICAL_FIELDS: return "critical"
    if path in MINOR_FIELDS: return "minor"
    return "informational"


def diff_manifests(a: RunManifest, b: RunManifest) -> ManifestDiff:
    """Structural diff. Walks every field; classifies each change by severity."""
    flat_a: dict[str, Any] = {}; flat_b: dict[str, Any] = {}
    _flatten("", a.model_dump(mode="json"), flat_a)
    _flatten("", b.model_dump(mode="json"), flat_b)
    diffs: list[FieldDiff] = []
    counts = {"critical": 0, "minor": 0, "informational": 0}
    for path in sorted(set(flat_a) | set(flat_b)):
        if path.split(".", 1)[0] in IGNORED_FIELDS: continue
        va, vb = flat_a.get(path), flat_b.get(path)
        if va == vb: continue
        sev = _classify(path)
        counts[sev] += 1
        diffs.append(FieldDiff(field_path=path, severity=sev,
                               old_value=va, new_value=vb))
    return ManifestDiff(
        manifest_a_uuid=str(a.manifest_uuid),
        manifest_b_uuid=str(b.manifest_uuid), diffs=diffs,
        critical_count=counts["critical"], minor_count=counts["minor"],
        informational_count=counts["informational"],
        is_reproducible=(counts["critical"] == 0))


def _fetch_output_hash(directive_id: str, db_url: Optional[str]) -> Optional[str]:
    """output_hash from the most recent audit_event for directive_id."""
    return _psql("SELECT output_hash FROM spine_audit.audit_event "
                 f"WHERE subject_id = '{_esc(directive_id)}' "
                 "AND output_hash IS NOT NULL ORDER BY ts DESC LIMIT 1;", db_url)


def diff_outputs(manifest_a: RunManifest, manifest_b: RunManifest, *,
                 db_url: Optional[str] = None) -> OutputDiff:
    """Compare the actual outputs of two captured runs (via audit log)."""
    url = db_url or os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    hash_a = _fetch_output_hash(manifest_a.directive_id, url)
    hash_b = _fetch_output_hash(manifest_b.directive_id, url)
    summary: list[str] = []
    match = bool(hash_a and hash_b and hash_a == hash_b)
    if not hash_a:
        summary.append(f"no output captured for directive {manifest_a.directive_id}")
    if not hash_b:
        summary.append(f"no output captured for directive {manifest_b.directive_id}")
    if hash_a and hash_b:
        summary.append("outputs identical" if match
                       else f"output hashes differ: {hash_a[:12]} != {hash_b[:12]}")
    if manifest_a.runtime.model_id != manifest_b.runtime.model_id:
        summary.append(f"different models: {manifest_a.runtime.model_id} "
                       f"vs {manifest_b.runtime.model_id}")
    if manifest_a.role.role_prompt_sha256 != manifest_b.role.role_prompt_sha256:
        summary.append("role prompt differs between runs")
    return OutputDiff(directive_a=manifest_a.directive_id,
                      directive_b=manifest_b.directive_id,
                      output_hash_a=hash_a, output_hash_b=hash_b,
                      outputs_match=match, diff_summary=summary)


__all__ = ["FieldDiff", "ManifestDiff", "OutputDiff",
           "diff_manifests", "diff_outputs",
           "CRITICAL_FIELDS", "MINOR_FIELDS", "IGNORED_FIELDS"]

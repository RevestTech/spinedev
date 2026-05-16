"""Parse v1 markdown reports into BuildArtifact-shaped JSON.

Implements part of STORY-7.5.1 / REQ-INIT-7 FR-5. v1 daemons produce
free-form markdown reports (PROTOCOL §3b §15c); this module best-effort
extracts the typed fields a v2 ``BuildArtifact`` needs. ``kg_impact`` is
populated post-hoc by ``build/runtime/enrich_artifact.enrich_build_artifact``
(STORY-7.3.{1,3}) — v1 daemons never call ``impact_radius`` themselves, so
the bridge fills the field before the auditor (STORY-7.4.3) sees it. Set
``SPINE_AUTO_ENRICH_KG=false`` to disable and ship empty ``kg_impact``.

CLI: ``python3 report_parser.py parse <file> --role <r> --project-id <p>
--directive-id <d> --pipeline-version <v>``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Header detection — v1 reports always start with "# Report" (PROTOCOL §3b).
# Failure variants embed FAILED / STOPPED / TIMEOUT in the title.
_REPORT_HEADER_RE = re.compile(r"^#\s*Report\b", re.IGNORECASE)

# v1 conventional section headings (PROTOCOL §15c + role-prompts/*.md).
# We accept ## and ### levels and case-insensitive matches.
_SECTION_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")

# "Files touched" bullet shape:
#   - path/to/file.ts (created — adds new route)
#   - `path/to/file.ts` modified
_FILE_BULLET_RE = re.compile(
    r"""^\s*[-*]\s+`?(?P<path>[^\s`(]+)`?\s*
        (?:\((?P<type>created|modified|deleted|new|updated|removed)\b[^)]*\))?
        (?:\s+(?P<type2>created|modified|deleted))?""",
    re.IGNORECASE | re.VERBOSE,
)

# Heuristic for skipping the "(none)" placeholder bullet.
_NONE_BULLET = re.compile(r"^\s*[-*]\s*\(?\s*none\s*\)?\s*$", re.IGNORECASE)


def _classify_section(heading: str) -> str:
    """Map a section heading to a canonical bucket name."""
    h = heading.strip().lower().rstrip(":")
    if h.startswith("tl;dr") or h == "tldr" or h.startswith("summary"):
        return "tldr"
    if "file" in h and ("touched" in h or "changed" in h or "modified" in h):
        return "files"
    if h.startswith("tests added") or h == "added tests":
        return "tests_added"
    if h.startswith("tests run") or h.startswith("tests executed"):
        return "tests_run"
    if h == "tests":
        return "tests_run"
    if h.startswith("rationale") or h.startswith("why") or h.startswith("what i did"):
        return "rationale"
    if h.startswith("lessons") or "memory" in h:
        return "lessons"
    if h.startswith("cost") or h.startswith("usage"):
        return "cost"
    return "other"


def _split_sections(text: str) -> dict[str, list[str]]:
    """Split markdown into {bucket: [lines...]} keyed by classified heading."""
    buckets: dict[str, list[str]] = {}
    current = "preamble"
    buckets[current] = []
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            current = _classify_section(m.group(1))
            buckets.setdefault(current, [])
            continue
        buckets.setdefault(current, []).append(line)
    return buckets


def _normalise_change_type(raw: str | None) -> str:
    """Map v1 free-form change words to BuildArtifact ``change_type`` enum."""
    if not raw:
        return "modify"
    r = raw.lower()
    if r in {"created", "new"}:
        return "create"
    if r in {"deleted", "removed"}:
        return "delete"
    return "modify"


def _extract_files(lines: list[str]) -> list[dict[str, Any]]:
    """Pull (path, change_type) tuples out of a "Files touched" section."""
    out: list[dict[str, Any]] = []
    for raw in lines:
        if not raw.strip() or _NONE_BULLET.match(raw):
            continue
        m = _FILE_BULLET_RE.match(raw)
        if not m:
            continue
        path = m.group("path")
        ctype = _normalise_change_type(m.group("type") or m.group("type2"))
        diff_hash = hashlib.sha256(f"{path}|{ctype}|{raw.strip()}".encode()).hexdigest()
        # lines_added/_removed: v1 reports rarely include +/- counts; zero
        # is honest and the auditor (STORY-7.4.3) will flag if needed.
        out.append({"path": path, "change_type": ctype, "diff_hash": diff_hash,
                    "lines_added": 0, "lines_removed": 0, "language": None})
    return out


def _extract_tests(lines: list[str], default_status: str) -> list[dict[str, Any]]:
    """Pull TestRecord-shaped dicts from a "Tests" bullet list (best-effort)."""
    out: list[dict[str, Any]] = []
    for raw in lines:
        if not raw.strip() or _NONE_BULLET.match(raw):
            continue
        m = re.match(r"^\s*[-*]\s+`?(?P<path>[^\s`(]+)`?(?:\s+(?P<rest>.*))?$", raw)
        if not m:
            continue
        path = m.group("path")
        rest = (m.group("rest") or "").lower()
        status = next((s for s in ("passed", "failed", "skipped", "errored")
                       if s in rest), default_status)
        out.append({"test_id": path, "path": path, "status": status,
                    "duration_ms": 0, "failure_message": None})
    return out


def _extract_tldr(buckets: dict[str, list[str]]) -> str:
    """Compose ``rationale`` from TL;DR + rationale sections, ≤500 chars."""
    parts: list[str] = []
    for key in ("tldr", "rationale"):
        block = "\n".join(buckets.get(key, [])).strip()
        if block:
            parts.append(block)
    text = "\n\n".join(parts).strip()
    if not text:
        # Fall back to the report header so sealing isn't blocked by the
        # rationale-required validator.
        text = "v1 bridge: report had no TL;DR / rationale section"
    return text[:500]


def _sealed_status(report_text: str) -> str:
    """Classify the report header. STOPPED/FAILED/TIMEOUT → rejected, else sealed."""
    first = (report_text.splitlines() or [""])[0]
    if not _REPORT_HEADER_RE.search(first):
        return "draft"
    upper = first.upper()
    if any(k in upper for k in ("FAILED", "STOPPED", "TIMEOUT")):
        return "rejected"
    return "sealed"


def parse_v1_report(
    report_text: str,
    *,
    role: str,
    project_id: str,
    directive_id: str,
    pipeline_version: str,
) -> dict[str, Any]:
    """Return a BuildArtifact-shaped dict (NOT validated against the Pydantic
    model — the v2 ``build_completed`` tool will do that)."""
    buckets = _split_sections(report_text)
    code_changes = _extract_files(buckets.get("files", []))
    tests_added = _extract_tests(buckets.get("tests_added", []), default_status="added")
    tests_run = _extract_tests(buckets.get("tests_run", []), default_status="passed")
    rationale = _extract_tldr(buckets)
    status = _sealed_status(report_text)
    now = datetime.now(timezone.utc).isoformat()

    # v1 daemons never call MCP impact_radius — start with empty kg_impact,
    # then post-enrich via build/runtime/enrich_artifact below (STORY-7.3.{1,3}).
    # v2 BuildArtifact restricts role to engineer/operator/datawright; map
    # other v1 roles to "engineer" and stash the original in metadata.
    v2_role = role if role in ("engineer", "operator", "datawright") else "engineer"
    artifact: dict[str, Any] = {
        "version": "build-artifact-v1", "directive_id": directive_id,
        "project_id": str(project_id), "phase": "build_in_progress",
        "role": v2_role, "pipeline_version": pipeline_version,
        "code_changes": code_changes, "tests_added": tests_added,
        "tests_run": tests_run, "kg_impact": [],
        "cost": {"tokens_input": 0, "tokens_output": 0,
                 "model": "v1-bridge-unknown", "cost_usd": "0", "tier": "medium"},
        "runtime": {"started_at": now, "completed_at": now,
                    "duration_seconds": 0, "worker_id": None},
        "rationale": rationale, "status": status, "auditor_verdict": "pending",
        "metadata": {"created_by": f"v1_bridge:{role}",
                     "created_at": now, "last_modified": now,
                     "v1_role": role, "v1_bridge": True},
    }

    # STORY-7.3.{1,3}: auto-enrich kg_impact via build/runtime/enrich_artifact
    # so the v1 bridge stops shipping empty kg_impact to the auditor. Opt-out
    # with SPINE_AUTO_ENRICH_KG=false (e.g. when debugging the KG schema).
    if os.environ.get("SPINE_AUTO_ENRICH_KG", "true").lower() != "false":
        try:
            from build.runtime.enrich_artifact import enrich_build_artifact
            from shared.schemas.build.build_artifact import BuildArtifact
            validated = BuildArtifact.model_validate(artifact)
            enriched = enrich_build_artifact(validated, mode="fill")
            artifact = enriched.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            sys.stderr.write(f"[warn] kg enrichment failed: {exc}\n")
    return artifact


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="report_parser.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    parse = sub.add_parser("parse", help="Parse a v1 markdown report file.")
    parse.add_argument("report_file", type=Path)
    parse.add_argument("--role", required=True)
    parse.add_argument("--project-id", required=True)
    parse.add_argument("--directive-id", required=True)
    parse.add_argument("--pipeline-version", required=True)
    args = p.parse_args(argv)

    if args.cmd == "parse":
        text = args.report_file.read_text(encoding="utf-8", errors="replace")
        artifact = parse_v1_report(
            text,
            role=args.role,
            project_id=args.project_id,
            directive_id=args.directive_id,
            pipeline_version=args.pipeline_version,
        )
        json.dump(artifact, sys.stdout)
        sys.stdout.write("\n")
        return 0
    return 64


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

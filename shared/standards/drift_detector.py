#!/usr/bin/env python3
"""Drift detection for installed Spine org bundles (STORY-2.1.5).

Compares each installed bundle in ``~/.spine/bundles/<id>/v<n>/`` against
its recorded source URL. Transports mirror install_bundle.sh: http(s) via
``urllib.request``; ``git+<repo>`` via shallow git clone; ``file://`` /
bare path via ``Path.read_bytes()``. Drift kinds: none | out_of_date |
source_modified | source_unreachable | unknown.

CLI: ``drift_detector.py status [<bundle_id>] [--format text|json]``.
Exit 0 = no drift, 2 = drift detected, 3 = error. Stdlib only; identity
fields regex-parsed (no PyYAML on the drift hot-path). Python 3.11+, Pydantic v2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
BUNDLES_DIR = SPINE_HOME / "bundles"
HTTP_TIMEOUT_SECS = 15

DriftKind = Literal["none", "out_of_date", "source_unreachable",
                    "source_modified", "unknown"]


class DriftStatus(BaseModel):
    """Drift snapshot for a single installed bundle."""
    bundle_id: str
    installed_version: int
    installed_sha256: str
    source_url: str | None = None
    source_version: int | None = None
    source_sha256: str | None = None
    is_drifted: bool
    drift_kind: DriftKind
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rationale: str


_IDENTITY_RE = re.compile(r"^identity:\s*$\n((?:[ \t]+.*\n)+)", re.MULTILINE)
_BV_RE = re.compile(r"^\s*bundle_version:\s*(\d+)", re.MULTILINE)
_BID_RE = re.compile(r"^\s*bundle_id:\s*([A-Za-z0-9_\-]+)", re.MULTILINE)


def _parse_identity(text: str) -> tuple[str | None, int | None]:
    """Cheap regex parse of identity.{bundle_id, bundle_version}."""
    m = _IDENTITY_RE.search(text); block = m.group(1) if m else text
    bid_m = _BID_RE.search(block); bv_m = _BV_RE.search(block)
    return (bid_m.group(1) if bid_m else None,
            int(bv_m.group(1)) if bv_m else None)


def _latest_version_dir(bundle_dir: Path) -> Path | None:
    if not bundle_dir.is_dir():
        return None
    vs = sorted((p for p in bundle_dir.iterdir()
                 if p.is_dir() and p.name.startswith("v")),
                key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else -1)
    return vs[-1] if vs else None


def _fetch_source(source_url: str) -> bytes:
    if source_url.startswith(("http://", "https://")):
        req = urllib.request.Request(
            source_url, headers={"User-Agent": "spine-drift/1"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECS) as resp:
            return resp.read()
    if source_url.startswith("git+"):
        repo = source_url[len("git+"):]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                subprocess.run(["git", "clone", "--depth", "1", repo, tmp],
                               capture_output=True, check=True, timeout=60)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    FileNotFoundError) as e:
                raise OSError(f"git clone {repo} failed: {e}") from e
            found = next(Path(tmp).rglob("bundle*.yaml"), None)
            if found is None:
                raise OSError(f"no bundle*.yaml in {repo}")
            return found.read_bytes()
    path = (source_url[len("file://"):]
            if source_url.startswith("file://") else source_url)
    return Path(path).read_bytes()


def _read_or(path: Path, default: str = "") -> str:
    return path.read_text().strip() if path.exists() else default


def detect_drift(bundle_id: str, *,
                 bundle_dir: Path | None = None) -> DriftStatus:
    """Compare one installed bundle against its source URL."""
    root = bundle_dir or (BUNDLES_DIR / bundle_id)
    vdir = _latest_version_dir(root)
    base = dict(bundle_id=bundle_id, installed_version=0, installed_sha256="")
    if vdir is None:
        return DriftStatus(**base, is_drifted=False, drift_kind="unknown",
            rationale=f"no installed version found under {root}")
    base.update(installed_sha256=_read_or(vdir / "sha256"),
        installed_version=int(vdir.name[1:]) if vdir.name[1:].isdigit() else 0)
    source_url = _read_or(vdir / "source_url") or None
    if not source_url:
        return DriftStatus(**base, source_url=None, is_drifted=False,
            drift_kind="unknown",
            rationale="source_url not recorded; cannot compare")
    try:
        raw = _fetch_source(source_url)
    except (OSError, urllib.error.URLError) as e:
        return DriftStatus(**base, source_url=source_url, is_drifted=True,
            drift_kind="source_unreachable", rationale=f"fetch failed: {e}")
    source_sha = hashlib.sha256(raw).hexdigest()
    _bid, source_ver = _parse_identity(raw.decode("utf-8", errors="replace"))
    iv = base["installed_version"]
    if source_sha == base["installed_sha256"]:
        kind, drifted, rat = "none", False, "installed sha256 matches source"
    elif source_ver is not None and source_ver > iv:
        kind, drifted = "out_of_date", True
        rat = f"source v{source_ver} > installed v{iv}; upgrade available"
    elif source_ver is not None and source_ver == iv:
        kind, drifted = "source_modified", True
        rat = ("source bundle_version unchanged but sha256 differs; "
               "monotonic-version invariant violated upstream")
    else:
        kind, drifted = "out_of_date", True
        rat = f"source sha256 differs (source_ver={source_ver}, installed_ver={iv})"
    return DriftStatus(**base, source_url=source_url,
        source_version=source_ver, source_sha256=source_sha,
        is_drifted=drifted, drift_kind=kind, rationale=rat)


def detect_drift_all() -> list[DriftStatus]:
    """Check every installed bundle. [] if BUNDLES_DIR is missing."""
    if not BUNDLES_DIR.is_dir():
        return []
    return [detect_drift(p.name) for p in sorted(BUNDLES_DIR.iterdir())
            if p.is_dir()]


def render_drift_report(statuses: list[DriftStatus],
                        fmt: Literal["text", "json"]) -> str:
    if fmt == "json":
        return json.dumps({"ok": True, "checked_at": datetime.now(
            timezone.utc).isoformat(),
            "bundles": [s.model_dump(mode="json") for s in statuses]}, indent=2)
    if not statuses:
        return "(no installed bundles)"
    lines: list[str] = []
    for s in statuses:
        marker = "DRIFT" if s.is_drifted else "ok   "
        sv = s.source_version if s.source_version is not None else "?"
        lines.append(f"[{marker}] {s.bundle_id:30s}  installed=v"
                     f"{s.installed_version}  source=v{sv}  kind={s.drift_kind}")
        lines.append(f"          {s.rationale}")
    return "\n".join(lines)


def _cmd_status(args: argparse.Namespace) -> int:
    statuses = ([detect_drift(args.bundle_id)] if args.bundle_id
                else detect_drift_all())
    sys.stdout.write(render_drift_report(statuses, args.format) + "\n")
    return 2 if any(s.is_drifted for s in statuses) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="drift_detector.py",
        description="Detect drift between installed Spine bundles and sources.")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="show drift status (all bundles or one)")
    st.add_argument("bundle_id", nargs="?", default=None)
    st.add_argument("--format", choices=("text", "json"), default="text")
    st.set_defaults(func=_cmd_status)
    try:
        a = p.parse_args(argv); return int(a.func(a))
    except Exception as e:  # last-resort guard; CLI must never traceback
        sys.stderr.write(json.dumps(
            {"ok": False, "code": "unexpected", "error": str(e)}) + "\n")
        return 3


if __name__ == "__main__":
    sys.exit(main())

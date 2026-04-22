"""Write Tron audit handoff files into a scanned application repository (breadcrumbs for local agents)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# HTML comments survive Markdown / .mdc; only the region between these markers is replaced on refresh.
TRON_HANDOFF_MANAGED_BEGIN = "<!-- TRON_HANDOFF_MANAGED_BEGIN -->"
TRON_HANDOFF_MANAGED_END = "<!-- TRON_HANDOFF_MANAGED_END -->"


class UnmarkedExistingStrategy(str, Enum):
    """When a target file exists but has no managed markers yet."""

    REPLACE = "replace"  # drop prior content (used for TRON_POST_SCAN.md snapshot)
    PREPEND = "prepend"  # keep prior file body after the managed block (CLAUDE.md / AGENTS.md / rules)


def tron_repo_root() -> Path:
    """Repository root (parent of ``tron/`` package)."""
    return Path(__file__).resolve().parent.parent.parent


def handoff_templates_dir() -> Path:
    """Templates shipped under ``tron/agent_handoff_templates`` (Docker COPY tron/ only)."""
    embedded = Path(__file__).resolve().parent.parent / "agent_handoff_templates"
    if embedded.is_dir():
        return embedded
    legacy = tron_repo_root() / "docs/templates/scanned-app-tron-handoff"
    if legacy.is_dir():
        return legacy
    raise FileNotFoundError(
        f"Handoff templates missing (tried {embedded} and {legacy})"
    )


def substitute_template(text: str, *, app_name: str, audit_id: str, tron_ui_base: str) -> str:
    return (
        text.replace("{{APP_NAME}}", app_name)
        .replace("{{TRON_AUDIT_ID}}", str(audit_id))
        .replace("{{TRON_UI_BASE}}", tron_ui_base.rstrip("/"))
    )


def wrap_managed_handoff_inner(managed_inner: str) -> str:
    """Return ``managed_inner`` wrapped in begin/end markers (single write / merge unit)."""
    body = managed_inner.strip()
    return f"{TRON_HANDOFF_MANAGED_BEGIN}\n{body}\n{TRON_HANDOFF_MANAGED_END}"


def merge_or_write_managed_file(
    path: Path,
    managed_inner: str,
    *,
    unmarked_existing: UnmarkedExistingStrategy,
) -> None:
    """Write ``managed_inner`` inside markers; preserve text before/after the marker block.

    If the file already contains a managed block, only that block is replaced. Otherwise
    behavior depends on ``unmarked_existing`` (see :class:`UnmarkedExistingStrategy`).
    """
    inner = managed_inner.strip()
    new_block = wrap_managed_handoff_inner(inner)
    if not path.exists():
        path.write_text(new_block + "\n", encoding="utf-8")
        return

    old = path.read_text(encoding="utf-8")
    b, e = TRON_HANDOFF_MANAGED_BEGIN, TRON_HANDOFF_MANAGED_END
    if b in old and e in old:
        i0 = old.index(b)
        i1 = old.index(e, i0 + len(b))
        before = old[:i0]
        after = old[i1 + len(e) :]
        path.write_text(before + new_block + after, encoding="utf-8")
        return

    if unmarked_existing is UnmarkedExistingStrategy.PREPEND:
        sep = "\n\n" if old.strip() else ""
        path.write_text(new_block + sep + old, encoding="utf-8")
        return

    path.write_text(new_block + "\n", encoding="utf-8")


def tron_handoff_audit_marker(audit_id: str) -> str:
    return f"<!-- tron-handoff:{audit_id.strip()} -->"


def append_tron_md_activity_log(
    dest: Path,
    *,
    app_name: str,
    audit_id: str,
    tron_ui_base: str,
    audit: dict[str, Any],
) -> Path | None:
    """Append a deduplicated audit summary to ``dest/tron.md`` (append-only; never edits earlier lines).

    Local agents are steered here from ``AGENTS.md`` / ``CLAUDE.md`` / Cursor rules to see **what Tron did**
    on this repo (folder or GitHub checkout) without re-reading the whole ``TRON_POST_SCAN.md`` table.

    Returns ``None`` if this ``audit_id`` was already logged (idempotent re-handoff).
    """
    dest = dest.expanduser().resolve()
    path = dest / "tron.md"
    marker = tron_handoff_audit_marker(audit_id)
    crit = int(audit.get("findings_critical") or 0)
    high = int(audit.get("findings_high") or 0)
    med = int(audit.get("findings_medium") or 0)
    low = int(audit.get("findings_low") or 0)
    total = int(audit.get("findings_total") or 0)
    completed = audit.get("completed_at") or "—"
    base = tron_ui_base.rstrip("/")

    block = (
        f"\n{marker}\n"
        f"### Tron activity — audit `{audit_id}`\n\n"
        f"- **Scanned as:** {app_name}\n"
        f"- **Completed:** {completed}\n"
        f"- **Findings (total / C / H / M / L):** {total} / {crit} / {high} / {med} / {low}\n"
        f"- **Tron UI:** {base}\n"
        f"- **Details & top issues:** `TRON_POST_SCAN.md` (Tron-managed block)\n"
    )

    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if marker in existing:
            return None
        path.write_text(existing.rstrip() + block + "\n", encoding="utf-8")
        return path

    intro = (
        "# Tron in this repository\n\n"
        "Tron audits this codebase (from a **folder path** or a **Git clone** configured in Tron, often backed by **GitHub**). "
        "After each audit, Tron writes handoff files in **this repo root** so your local IDE agent sees what happened.\n\n"
        "**What your agent should read:**\n\n"
        "1. The usual repo context — **`AGENTS.md`**, **`CLAUDE.md`**, and **`.cursor/rules/`** (Cursor loads these automatically).\n"
        "2. **`TRON_POST_SCAN.md`** — latest finding counts, top paths, triage checklist.\n"
        "3. **This file (`tron.md`)** — **Tron activity**: append-only log entries after each handoff; add human notes below or between runs.\n\n"
    )
    path.write_text(intro + block.lstrip("\n") + "\n", encoding="utf-8")
    return path


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _duration_line(audit: dict[str, Any]) -> str:
    a = _parse_ts(audit.get("started_at"))
    b = _parse_ts(audit.get("completed_at"))
    if not a or not b:
        return ""
    sec = max(0, int((b - a).total_seconds()))
    return f"{sec}s"


def _severity_rank(sev: str) -> int:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get((sev or "").strip().lower(), 99)


def build_tron_post_scan_markdown(
    *,
    app_name: str,
    audit_id: str,
    tron_ui_base: str,
    audit: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    """Markdown for ``TRON_POST_SCAN.md`` (Agent Directives + Snapshot)."""
    crit = int(audit.get("findings_critical") or 0)
    high = int(audit.get("findings_high") or 0)
    total = int(audit.get("findings_total") or len(findings))
    
    tdir = handoff_templates_dir()
    template_path = tdir / "TRON_POST_SCAN.md.template"
    if not template_path.is_file():
        # Fallback to the legacy build logic if template missing
        return f"# Audit {audit_id} - {app_name}\n\nTotal findings: {total}"

    raw_template = template_path.read_text(encoding="utf-8")
    
    # Sort findings: Critical first, then High
    sorted_f = sorted(findings, key=lambda f: (_severity_rank(f.get("severity", "")), f.get("file_path", "")))
    
    directive_lines = []
    for f in sorted_f:
        sev = (f.get("severity") or "low").upper()
        if sev not in ("CRITICAL", "HIGH", "MEDIUM"): # Include medium too for coverage
            continue
            
        fp = f.get("file_path", "unknown")
        line = f.get("line_start") or f.get("line_number") or "?"
        title = f.get("title") or "Unnamed Finding"
        desc = f.get("description") or "No description provided."
        fix = f.get("fix_suggestion") or f.get("suggested_fix") or "No specific fix suggested. Investigate root cause."
        
        directive_lines.append(f"### 🔴 {sev}: {title}")
        directive_lines.append(f"- **Location:** `{fp}:{line}`")
        directive_lines.append(f"- **Issue:** {desc}")
        directive_lines.append(f"- **Directive:** {fix}")
        directive_lines.append("")

    details = "\n".join(directive_lines) if directive_lines else "_No Critical or High severity findings detected._"

    return (
        raw_template.replace("{{APP_NAME}}", app_name)
        .replace("{{TRON_AUDIT_ID}}", audit_id)
        .replace("{{TRON_UI_BASE}}", tron_ui_base.rstrip("/"))
        .replace("{{CRIT_COUNT}}", str(crit))
        .replace("{{HIGH_COUNT}}", str(high))
        .replace("{{TOTAL_COUNT}}", str(total))
        .replace("{{FINDING_DETAILS}}", details)
    )


def write_audit_handoff_bundle(
    dest: Path,
    *,
    app_name: str,
    audit_id: str,
    tron_ui_base: str,
    audit: dict[str, Any],
    findings: list[dict[str, Any]],
    append_tron_md_activity: bool | None = None,
) -> list[Path]:
    """Write ``TRON_POST_SCAN.md``, ``.cursor/rules/tron-scan-followups.mdc``, ``CLAUDE.md``, ``AGENTS.md`` under ``dest``.

    When ``append_tron_md_activity`` is true (default: ``TRON_HANDOFF_APPEND_TRON_MD`` env), also appends to ``tron.md``.
    """
    dest = dest.expanduser().resolve()
    rules_dir = dest / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    tdir = handoff_templates_dir()
    written: list[Path] = []

    post = build_tron_post_scan_markdown(
        app_name=app_name,
        audit_id=audit_id,
        tron_ui_base=tron_ui_base,
        audit=audit,
        findings=findings,
    )
    p1 = dest / "TRON_POST_SCAN.md"
    merge_or_write_managed_file(
        p1,
        post,
        unmarked_existing=UnmarkedExistingStrategy.REPLACE,
    )
    written.append(p1)

    for tmpl, out_rel in (
        ("tron-scan-followups.mdc.template", dest / ".cursor" / "rules" / "tron-scan-followups.mdc"),
        ("CLAUDE.md.template", dest / "CLAUDE.md"),
        ("AGENTS.md.template", dest / "AGENTS.md"),
    ):
        raw = (tdir / tmpl).read_text(encoding="utf-8")
        body = substitute_template(
            raw,
            app_name=app_name,
            audit_id=str(audit_id),
            tron_ui_base=tron_ui_base,
        )
        merge_or_write_managed_file(
            out_rel,
            body,
            unmarked_existing=UnmarkedExistingStrategy.PREPEND,
        )
        written.append(out_rel)

    if append_tron_md_activity is None:
        from tron.api.config import settings as _settings

        append_tron_md_activity = _settings.tron_handoff_append_tron_md
    if append_tron_md_activity:
        tmd = append_tron_md_activity_log(
            dest,
            app_name=app_name,
            audit_id=str(audit_id),
            tron_ui_base=tron_ui_base,
            audit=audit,
        )
        if tmd is not None:
            written.append(tmd)

    return written


def paginate_audit_findings(
    fetch_json: Callable[..., Any],
    audit_id: str,
    *,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Collect all findings for an audit using paginated GET ``/audits/{id}/findings``."""
    page = 1
    out: list[dict[str, Any]] = []
    while True:
        data = fetch_json(
            "GET",
            f"/audits/{audit_id}/findings",
            params={"page": page, "page_size": page_size},
        )
        items = data.get("items") or []
        out.extend(items)
        total = int(data.get("total") or 0)
        if not items or len(out) >= total:
            break
        page += 1
    return out

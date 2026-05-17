"""Spine plan-phase intake runner.

Replaces the `plan_dispatch` stub for the first user-facing slice: when a
project enters `plan_in_progress`, run the intake template's question loop
against stdin/stdout, persist the answers to `project.metadata.intake`, and
synthesize a draft PRD into `project.metadata.prd_draft`.

Replacement path: this module's `run_intake()` is the deterministic v1. A
future LLM-driven runner will live alongside it (likely
`plan.runtime.intake_runner_llm`) and read/write the same JSON shape; the
caller (orchestrator MCP, `spine intake` CLI) flips between them via a
project setting.

Boundaries:
- Reads templates from `plan/templates/intake/<template>.yaml`.
- Reads / writes only `spine_lifecycle.project.metadata` (jsonb merge).
- Audits via `shared.audit.audit_record.write_via_psql` — one row per
  consequential step (`intake_started`, per-question, `intake_completed`,
  `prd_draft_persisted`).
- Validates the PRD it builds via `plan.artifacts.prd_v1.PRDv1`.

Non-tty callers (e.g. the MCP server) get a friendly `IntakeNotInteractive`
exception so they can surface "run `spine intake <id>` instead" instead of
blocking on `input()` forever.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from plan.artifacts._base import (
    AcceptanceCriterion,
    ArtifactMetadata,
    Goal,
    OpenQuestion,
    ProjectType as PRDProjectType,
)
from plan.artifacts.prd_v1 import Goals, PRDv1, Stakeholder

# ── Constants & paths ──────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(os.environ.get(
    "SPINE_INTAKE_TEMPLATE_DIR", _REPO_ROOT / "plan/templates/intake"
))

# Map the orchestrator `project_type` lifecycle flags to the intake template
# we default to when the user did not pass --template. `greenfield` projects
# have no inherent product archetype, so we fall back to the CLI tool template
# (matches the dogfood case). Bundles can extend this via the metadata field.
_DEFAULT_TEMPLATE_BY_PROJECT_TYPE: dict[str, str] = {
    "greenfield": "cli-tool",
    "evolve": "cli-tool",
}

# project_type strings used by the intake YAMLs do not match the PRD's
# `ProjectType` enum 1:1 (the YAML uses dashes; the enum uses underscores).
_PRD_PROJECT_TYPE_BY_TEMPLATE: dict[str, PRDProjectType] = {
    "cli-tool": PRDProjectType.CLI_TOOL,
    "web-app": PRDProjectType.WEB_APP,
    "internal-tool": PRDProjectType.INTERNAL_TOOL,
    "data-pipeline": PRDProjectType.DATA_PIPELINE,
    "mobile": PRDProjectType.MOBILE,
    "api-service": PRDProjectType.API_SERVICE,
}


class IntakeNotInteractive(RuntimeError):
    """Raised when `run_intake()` is called without a tty on stdin.

    The MCP `plan_dispatch` tool catches this and returns a structured
    error so the user runs `spine intake <id>` in a real shell instead.
    """


class IntakeTemplateNotFound(FileNotFoundError):
    """The template file for the requested project type is missing."""


# ── Data classes ───────────────────────────────────────────────────────


@dataclass
class IntakeResult:
    """What `run_intake()` produced. Mirrors the shape of metadata.intake."""

    template: str
    template_version: str
    started_at: str
    completed_at: str
    answers: dict[str, Any] = field(default_factory=dict)
    prd_valid: bool = False
    prd_fields_populated: int = 0
    audit_event_count: int = 0

    def to_metadata_entry(self) -> dict[str, Any]:
        """Shape that gets merged into `project.metadata.intake`."""
        return {
            "template": self.template,
            "template_version": self.template_version,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "answers": self.answers,
        }


# ── DB helpers (psql shell-outs; matches the pattern in orchestrator.py) ─


def _db_url() -> str:
    url = os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set; intake runner requires a DB URL")
    return url


def _psql(sql: str, *, timeout: int = 15) -> str:
    cmd = ["psql", _db_url(), "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _esc(value: str) -> str:
    return value.replace("'", "''")


# ── Project lookup ─────────────────────────────────────────────────────


def _load_project(project_id: int | str) -> dict[str, Any]:
    """Resolve `project_id` (BIGINT id or name) to the row we need."""
    if isinstance(project_id, int) or (isinstance(project_id, str) and project_id.isdigit()):
        where = f"id = {int(project_id)}"
    else:
        where = f"name = '{_esc(str(project_id))}'"
    sql = (
        "SELECT id::text || '|' || project_uuid::text || '|' || name || '|' || "
        "project_type || '|' || current_phase || '|' || COALESCE(metadata::text,'{}') "
        f"FROM spine_lifecycle.project WHERE {where} AND status='active' LIMIT 1;"
    )
    out = _psql(sql)
    if not out:
        raise RuntimeError(f"no active project for id/name={project_id!r}")
    parts = out.split("|", 5)
    return {
        "id": int(parts[0]), "project_uuid": parts[1], "name": parts[2],
        "project_type": parts[3], "current_phase": parts[4],
        "metadata": json.loads(parts[5] or "{}"),
    }


def _merge_metadata(pid: int, patch: dict[str, Any]) -> None:
    """Jsonb merge of `patch` into project.metadata (top-level keys, shallow)."""
    payload = json.dumps(patch).replace("'", "''")
    sql = (
        "UPDATE spine_lifecycle.project "
        f"SET metadata = metadata || '{payload}'::jsonb "
        f"WHERE id = {pid};"
    )
    _psql(sql)


# ── Template loading ───────────────────────────────────────────────────


def _resolve_template_name(
    explicit: str | None,
    project_metadata: dict[str, Any],
    project_type: str,
) -> str:
    """Pick the intake template per priority: --template > metadata > default."""
    if explicit:
        return explicit
    via_meta = (project_metadata.get("intake_template") or "").strip()
    if via_meta:
        return via_meta
    fallback = _DEFAULT_TEMPLATE_BY_PROJECT_TYPE.get(project_type)
    if fallback:
        return fallback
    # If the project_type happens to BE a template name (e.g. "cli-tool"
    # in an org bundle), accept it.
    if (TEMPLATES_DIR / f"{project_type}.yaml").exists():
        return project_type
    raise IntakeTemplateNotFound(
        f"no template resolvable for project_type={project_type!r}; "
        f"pass --template, set metadata.intake_template, or extend "
        f"_DEFAULT_TEMPLATE_BY_PROJECT_TYPE"
    )


def load_template(template_name: str) -> tuple[dict[str, Any], str]:
    """Return (parsed_template, version_token) for `<TEMPLATES_DIR>/<name>.yaml`."""
    path = TEMPLATES_DIR / f"{template_name}.yaml"
    if not path.exists():
        raise IntakeTemplateNotFound(f"intake template missing: {path}")
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    # Use mtime + size as a cheap version token. A real content hash is the
    # future option but mtime is enough to detect "template changed since
    # this project last ran intake".
    version = f"mtime={int(path.stat().st_mtime)};size={path.stat().st_size}"
    return parsed, version


# ── Audit helper (best-effort; mirrors orchestrator.py) ────────────────


def _write_audit(*, action: str, project_id: int, actor: str,
                 metadata: dict[str, Any], rationale: str | None = None,
                 subject_id: str | None = None,
                 subject_type: str = "intake") -> bool:
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
    except Exception:
        return False
    try:
        try:
            tip = _psql("SELECT content_hash FROM spine_audit.audit_event "
                        "ORDER BY event_id DESC LIMIT 1;")
        except Exception:
            tip = ""
        rec = AuditRecord(
            project_id=project_id, phase="plan_in_progress",
            role="product", subsystem="plan", action=action, actor=actor,
            subject_type=subject_type,
            subject_id=subject_id or f"intake:{project_id}",
            rationale=rationale, metadata=metadata,
        )
        rec = chain_to_previous(rec, tip or None)
        write_via_psql(rec)
        return True
    except Exception:
        # Audit-write failure must not kill the intake run; the project
        # metadata IS the source of truth.
        return False


# ── Interactive prompt loop ────────────────────────────────────────────


def _banner(out, text: str) -> None:
    bar = "─" * max(len(text) + 4, 40)
    print(f"\n{bar}", file=out)
    print(f"  {text}", file=out)
    print(bar, file=out)


def _ask_one(question: dict[str, Any], *, in_, out) -> Any:
    """Print one question, read + normalize one answer. Loops on bad input."""
    qtype = question.get("type", "open")
    prompt = question.get("prompt", question["id"])
    why = question.get("why_asked")
    required = bool(question.get("required", False))
    examples = question.get("examples") or []
    options: list[str] = question.get("options") or []

    while True:
        print(f"\nQ: {prompt}", file=out)
        if why:
            print(f"   (why: {why})", file=out)
        if examples:
            print("   examples:", file=out)
            for ex in examples:
                print(f"     - {ex}", file=out)
        if qtype in ("single_choice", "multi_choice"):
            for idx, opt in enumerate(options, 1):
                print(f"     {idx}. {opt}", file=out)
            hint = ("pick one (number)" if qtype == "single_choice"
                    else "pick one or more (comma-separated numbers)")
            print(f"   {hint}: ", end="", file=out, flush=True)
        elif qtype == "yes_no":
            print("   y/n: ", end="", file=out, flush=True)
        else:
            print("   > ", end="", file=out, flush=True)

        raw = in_.readline()
        if raw == "":  # EOF
            if required:
                raise IntakeNotInteractive(
                    f"EOF on question {question['id']!r} but it's required"
                )
            return None
        answer = raw.strip()
        normalized = _normalize(qtype, answer, options)
        if normalized is None or (required and _is_empty(normalized)):
            print("   (required — please answer)", file=out)
            continue
        return normalized


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _normalize(qtype: str, raw: str, options: list[str]) -> Any:
    if qtype == "single_choice":
        if not raw:
            return None
        try:
            idx = int(raw)
        except ValueError:
            return None
        if 1 <= idx <= len(options):
            return options[idx - 1]
        return None
    if qtype == "multi_choice":
        if not raw:
            return None
        picked: list[str] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                idx = int(token)
            except ValueError:
                return None
            if not (1 <= idx <= len(options)):
                return None
            if options[idx - 1] not in picked:
                picked.append(options[idx - 1])
        return picked
    if qtype == "yes_no":
        low = raw.lower()
        if low in {"y", "yes", "true", "1"}:
            return True
        if low in {"n", "no", "false", "0"}:
            return False
        return None
    # open
    return raw


# ── PRD synthesis ──────────────────────────────────────────────────────


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    # Split on newline first; if single line, try semicolons then commas.
    for sep in ("\n", ";", ","):
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    return [text]


def _parse_must_should_could(raw: str | None) -> tuple[list[str], list[str], list[str]]:
    """Parse a free-form 'MUST: a / SHOULD: b / COULD: c' answer into three lists.

    Designed to be forgiving: each tier can appear once, on its own line, or
    inline separated by ` / `. Items within a tier split on `,`.
    """
    must: list[str] = []
    should: list[str] = []
    could: list[str] = []
    if not raw:
        return must, should, could
    text = raw.replace(" / ", "\n").replace("/", "\n")
    current: list[str] | None = None
    for line in text.splitlines():
        line = line.strip(" -*")
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("MUST"):
            current = must
            line = line.split(":", 1)[1].strip() if ":" in line else ""
        elif upper.startswith("SHOULD"):
            current = should
            line = line.split(":", 1)[1].strip() if ":" in line else ""
        elif upper.startswith("COULD") or upper.startswith("WONT") or upper.startswith("WON'T"):
            current = could
            line = line.split(":", 1)[1].strip() if ":" in line else ""
        if current is None or not line:
            continue
        for item in line.split(","):
            item = item.strip()
            if item:
                current.append(item)
    return must, should, could


def synthesize_prd_draft(
    *,
    project_uuid: str,
    project_name: str,
    template_name: str,
    answers: dict[str, Any],
    actor: str,
) -> PRDv1:
    """Build a draft PRDv1 from the collected intake answers.

    Draft (not approved) — so we can leave open questions where the user
    didn't fill in something the PRD would normally need, and the
    refuse-to-advance gate stays satisfied.
    """
    prd_pt = _PRD_PROJECT_TYPE_BY_TEMPLATE.get(template_name, PRDProjectType.CUSTOM)

    primary_job = (answers.get("primary_job") or "").strip()
    audience = answers.get("audience") or answers.get("consumers") or ""

    problem = (
        primary_job
        if primary_job
        else f"Deliver {template_name} for {audience or 'the target audience'}."
    )

    stakeholders: list[Stakeholder] = []
    if audience:
        stakeholders.append(Stakeholder(
            name=str(audience),
            needs=(f"Reliable {template_name} that supports their primary job: "
                   f"{primary_job or 'TBD'}").strip(),
        ))

    must_raw = answers.get("must_should_could") or answers.get("must_should_could_features")
    must_list, should_list, could_list = _parse_must_should_could(
        must_raw if isinstance(must_raw, str) else None
    )

    goals = Goals(
        must=[Goal(id=f"G-M-{i+1}", statement=stmt) for i, stmt in enumerate(must_list)],
        should=[Goal(id=f"G-S-{i+1}", statement=stmt) for i, stmt in enumerate(should_list)],
        could=[Goal(id=f"G-C-{i+1}", statement=stmt) for i, stmt in enumerate(could_list)],
    )

    in_scope: list[str] = []
    if primary_job:
        in_scope.append(f"Primary command/job: {primary_job}")
    for key in ("install_method", "output_formats", "cross_platform"):
        vals = answers.get(key)
        if isinstance(vals, list) and vals:
            in_scope.append(f"{key.replace('_', ' ')}: {', '.join(vals)}")
        elif isinstance(vals, str) and vals.strip():
            in_scope.append(f"{key.replace('_', ' ')}: {vals.strip()}")
    in_scope.extend(_as_list(answers.get("in_scope")))

    out_of_scope = _as_list(answers.get("out_of_scope"))

    # Derive a couple of acceptance criteria from the answers when present.
    acceptance: list[AcceptanceCriterion] = []
    if primary_job:
        acceptance.append(AcceptanceCriterion(
            id="AC-1",
            given=f"a {audience or 'target user'} on a supported platform",
            when="they run the primary command described in intake",
            then="the command completes successfully and produces the expected output",
        ))
    for ms in must_list[:3]:
        acceptance.append(AcceptanceCriterion(
            id=f"AC-MUST-{len(acceptance)}",
            then=f"MUST item delivered: {ms}",
        ))

    # Anything the user dodged becomes an open question rather than blocking
    # the draft.
    open_qs: list[OpenQuestion] = []
    for k in ("dependencies_runtime", "config_file", "subcommand_depth"):
        if k not in answers or _is_empty(answers.get(k)):
            open_qs.append(OpenQuestion(
                id=f"OQ-{len(open_qs)+1}",
                question=f"intake skipped {k!r}; product role to confirm.",
            ))

    return PRDv1(
        project_id=project_uuid,
        project_name=project_name,
        project_type=prd_pt,
        problem_statement=problem,
        users_stakeholders=stakeholders,
        goals=goals,
        in_scope=in_scope or ["TBD-intake-incomplete"][:0],  # never insert TBD
        out_of_scope=out_of_scope,
        acceptance_criteria=acceptance,
        open_questions=open_qs,
        metadata=ArtifactMetadata(
            created_by=actor or "product",
            status="draft",  # draft only — sealing happens after review phase.
        ),
    )


# ── Public entry point ────────────────────────────────────────────────


def run_intake(
    project_id: int | str,
    *,
    template: str | None = None,
    actor: str = "product",
    in_=None,
    out=None,
) -> IntakeResult:
    """Drive the intake loop end-to-end. See module docstring.

    Raises:
        IntakeNotInteractive: stdin has no tty (MCP / pipe-from-no-input).
        IntakeTemplateNotFound: template file missing.
        RuntimeError: project lookup or DB write failed.
    """
    in_ = in_ if in_ is not None else sys.stdin
    out = out if out is not None else sys.stdout

    if not in_.isatty() and not os.environ.get("SPINE_INTAKE_ALLOW_NONTTY"):
        raise IntakeNotInteractive(
            "intake requires interactive tty — run `spine intake <id>` instead"
        )

    proj = _load_project(project_id)
    template_name = _resolve_template_name(
        template, proj["metadata"], proj["project_type"]
    )
    parsed, template_version = load_template(template_name)
    questions: list[dict[str, Any]] = parsed.get("questions") or []
    if not questions:
        raise RuntimeError(f"template {template_name!r} has no questions")

    started_at = datetime.now(timezone.utc).isoformat()
    audit_count = 0
    audit_count += int(_write_audit(
        action="intake_started", project_id=proj["id"], actor=actor,
        metadata={"template": template_name, "template_version": template_version,
                  "question_count": len(questions)},
        subject_id=f"intake:{proj['id']}:{template_name}",
    ))

    _banner(out, f"Spine intake — {proj['name']} (template: {template_name})")
    print(f"Description: {parsed.get('description', '').strip()}", file=out)
    print(f"Questions  : {len(questions)} (Ctrl-C to abort)", file=out)

    answers: dict[str, Any] = {}
    current_section: str | None = None
    for q in questions:
        section = q.get("section")
        if section and section != current_section:
            _banner(out, f"Section: {section}")
            current_section = section
        answer = _ask_one(q, in_=in_, out=out)
        answers[q["id"]] = answer
        audit_count += int(_write_audit(
            action="intake_question_answered", project_id=proj["id"], actor=actor,
            metadata={"question_id": q["id"], "type": q.get("type"),
                      "answer_preview": _preview(answer)},
            subject_id=f"intake:{proj['id']}:{q['id']}",
        ))

    completed_at = datetime.now(timezone.utc).isoformat()
    result = IntakeResult(
        template=template_name, template_version=template_version,
        started_at=started_at, completed_at=completed_at, answers=answers,
    )

    # Persist intake answers BEFORE we attempt PRD synthesis — if the PRD
    # validate step trips a Pydantic guard the user keeps their answers.
    _merge_metadata(proj["id"], {"intake": result.to_metadata_entry()})
    audit_count += int(_write_audit(
        action="intake_completed", project_id=proj["id"], actor=actor,
        metadata={"template": template_name, "answer_count": len(answers),
                  "started_at": started_at, "completed_at": completed_at},
        subject_id=f"intake:{proj['id']}:{template_name}",
    ))

    # Synthesize PRD; tolerate validation failure by surfacing the issue but
    # still leaving the intake answers in place.
    prd_dump: dict[str, Any] = {}
    prd_valid = False
    try:
        prd = synthesize_prd_draft(
            project_uuid=proj["project_uuid"], project_name=proj["name"],
            template_name=template_name, answers=answers, actor=actor,
        )
        prd_dump = prd.model_dump(mode="json")
        # Round-trip to prove model_validate accepts what we just dumped.
        PRDv1.model_validate(prd_dump)
        prd_valid = True
    except Exception as exc:  # noqa: BLE001 — surface to caller via result
        prd_dump = {"_error": f"prd_synthesis_failed: {exc.__class__.__name__}: {exc}"}

    _merge_metadata(proj["id"], {"prd_draft": prd_dump})
    audit_count += int(_write_audit(
        action="prd_draft_persisted", project_id=proj["id"], actor=actor,
        metadata={"valid": prd_valid, "fields_populated": _count_populated(prd_dump),
                  "template": template_name},
        subject_id=f"prd_draft:{proj['id']}",
    ))

    result.prd_valid = prd_valid
    result.prd_fields_populated = _count_populated(prd_dump)
    result.audit_event_count = audit_count

    print("", file=out)
    print(f"Intake complete: {len(answers)} answers, PRD draft "
          f"{'valid' if prd_valid else 'INVALID — see metadata.prd_draft._error'}.",
          file=out)
    print(f"Stored in project.metadata.intake and project.metadata.prd_draft.", file=out)
    return result


# ── Small utility ──────────────────────────────────────────────────────


def _preview(answer: Any, max_len: int = 120) -> str:
    if isinstance(answer, list):
        text = ", ".join(str(x) for x in answer)
    elif answer is None:
        text = ""
    else:
        text = str(answer)
    text = text.replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _count_populated(prd_dump: dict[str, Any]) -> int:
    """Crude "how rich is this PRD" count — used in dispatch response."""
    count = 0
    for key in ("project_id", "project_name", "project_type", "problem_statement"):
        if prd_dump.get(key):
            count += 1
    for key in ("users_stakeholders", "in_scope", "out_of_scope",
                "acceptance_criteria", "open_questions"):
        if prd_dump.get(key):
            count += 1
    goals = prd_dump.get("goals") or {}
    for tier in ("must", "should", "could"):
        if goals.get(tier):
            count += 1
    return count


__all__ = [
    "IntakeNotInteractive",
    "IntakeTemplateNotFound",
    "IntakeResult",
    "load_template",
    "run_intake",
    "synthesize_prd_draft",
]

"""12-layer agent-stack audit (V3 B10 borrow).

The audit enumerates every layer of the agent stack that can corrupt
role output and runs a Spine-native check against each. Native checks
inspect: charters on disk, the MCP tool registry, the decision
ledger, MCP envelope conventions, and the charter-eval suite.

Some layers (e.g. transport/rendering, distillation) require runtime
telemetry that is not yet plumbed into shared state — those return
``status='instrumentation_pending'`` so the report explicitly
distinguishes "checked and clean" from "no instrumentation". This
prevents the gate from going green just because nothing reported.

Severity codes follow the convention in
``~/.claude/rules/ecc/common/code-review.md``:

* ``critical`` — gate-blocking; a regression has been observed.
* ``high``     — risk worth investigating before promotion.
* ``medium``   — maintainability concern, not gate-blocking.
* ``low``      — informational.

The audit is read-only; it computes findings, never mutates state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

LayerId = Literal[
    "L01_system_prompt",
    "L02_session_history",
    "L03_long_term_memory",
    "L04_distillation",
    "L05_active_recall",
    "L06_tool_selection",
    "L07_tool_execution",
    "L08_tool_interpretation",
    "L09_answer_shaping",
    "L10_transport",
    "L11_evals",
    "L12_promotion_gate",
]
"""Twelve named layers per the ECC agent-architecture-audit catalog,
specialised to Spine surfaces:

  * L01 system_prompt        — `shared/charters/<role>.md` identity
  * L02 session_history      — `.spine/work/<run_id>/` workspace state
  * L03 long_term_memory     — Smart Spine instincts + lessons (#27)
  * L04 distillation         — audit-ledger compression / summary
  * L05 active_recall        — KG retrieval middleware (kg_role_context)
  * L06 tool_selection       — MCP `TOOL_REGISTRY` size + duplicates
  * L07 tool_execution       — tool call success vs error vs refusal mix
  * L08 tool_interpretation  — next_actions parsing rate
  * L09 answer_shaping       — V3 #30a envelope conformance (B2)
  * L10 transport            — SPA / API / federation mutations
  * L11 evals                — charter_evals pass@k (B6 / V3 #7a)
  * L12 promotion_gate       — decision-ledger denial rate (B1 / #12a)
"""


LayerSeverity = Literal["critical", "high", "medium", "low"]
LayerStatus = Literal["clean", "warning", "regressed", "instrumentation_pending"]


class LayerFinding(BaseModel):
    """One layer's audit row in :class:`AgentAuditReport`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: LayerId
    status: LayerStatus
    summary: str
    severity: LayerSeverity = "low"
    evidence: tuple[str, ...] = Field(default_factory=tuple)
    next_actions: tuple[str, ...] = Field(default_factory=tuple)


@dataclass(frozen=True)
class AgentAuditReport:
    """Aggregate result of one :func:`scan_agent_stack` run."""

    findings: tuple[LayerFinding, ...]

    @property
    def regressed_layers(self) -> tuple[LayerFinding, ...]:
        return tuple(f for f in self.findings if f.status == "regressed")

    @property
    def overall_status(self) -> LayerStatus:
        if any(f.status == "regressed" for f in self.findings):
            return "regressed"
        if any(f.status == "warning" for f in self.findings):
            return "warning"
        if all(
            f.status == "instrumentation_pending" for f in self.findings
        ):
            return "instrumentation_pending"
        return "clean"


# ─── Layer-check callable surface ────────────────────────────────────


@dataclass(frozen=True)
class LayerCheck:
    """One layer's native check, packaged for dependency injection.

    A check is a callable ``(repo_root, signals) -> LayerFinding``.
    Tests pass a fake ``signals`` dict; production callers populate it
    from the live runtime so the same check function works in both
    modes (no DB / process state captured at module scope).
    """

    layer: LayerId
    fn: Callable[[Path, dict], LayerFinding]


def _pending(layer: LayerId, why: str) -> LayerFinding:
    return LayerFinding(
        layer=layer,
        status="instrumentation_pending",
        summary=why,
        severity="low",
    )


# ─── Native checks ───────────────────────────────────────────────────


def check_system_prompt_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L01 — charters readable + non-empty.

    Pass condition: every file under ``shared/charters/*.md`` parses
    and exceeds a minimum body length (catches blanked-out charters).
    """
    charter_dir = repo_root / "shared" / "charters"
    if not charter_dir.is_dir():
        return LayerFinding(
            layer="L01_system_prompt",
            status="regressed",
            summary="shared/charters/ directory not present",
            severity="critical",
        )
    too_short: list[str] = []
    count = 0
    for path in sorted(charter_dir.glob("*.md")):
        count += 1
        if len(path.read_text(encoding="utf-8")) < 500:
            too_short.append(path.name)
    if too_short:
        return LayerFinding(
            layer="L01_system_prompt",
            status="warning",
            summary=f"{len(too_short)} charter(s) under 500 chars",
            severity="medium",
            evidence=tuple(too_short),
            next_actions=(
                "review whether the short charter was truncated by an "
                "edit or is intentionally minimal",
            ),
        )
    return LayerFinding(
        layer="L01_system_prompt",
        status="clean",
        summary=f"{count} charter(s) load and exceed minimum body length",
        severity="low",
    )


def check_long_term_memory_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L03 — Smart Spine instinct + lesson surfaces wired.

    Pass: ``learning/`` package importable + ``instinct.py`` present.
    """
    learning_pkg = repo_root / "learning" / "__init__.py"
    instinct_mod = repo_root / "learning" / "instinct.py"
    contribute_mod = repo_root / "learning" / "contribute.py"
    missing = [
        str(p.relative_to(repo_root)) for p in
        (learning_pkg, instinct_mod, contribute_mod)
        if not p.exists()
    ]
    if missing:
        return LayerFinding(
            layer="L03_long_term_memory",
            status="regressed",
            summary=f"{len(missing)} long-term-memory module(s) missing",
            severity="high",
            evidence=tuple(missing),
        )
    return LayerFinding(
        layer="L03_long_term_memory",
        status="clean",
        summary="learning/ instinct + contribute modules present",
    )


def check_tool_selection_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L06 — MCP tool registry healthy.

    ``signals['tool_registry']`` is the live ``TOOL_REGISTRY`` dict
    when running in-process. Falls back to ``instrumentation_pending``
    when absent (e.g. a tests-only environment).
    """
    registry = signals.get("tool_registry")
    if registry is None:
        return _pending(
            "L06_tool_selection",
            "no tool_registry signal supplied (pass live TOOL_REGISTRY "
            "in signals for production checks)",
        )
    if not isinstance(registry, dict):
        return LayerFinding(
            layer="L06_tool_selection",
            status="regressed",
            summary=f"tool_registry signal is not a dict (got {type(registry).__name__})",
            severity="critical",
        )
    if not registry:
        return LayerFinding(
            layer="L06_tool_selection",
            status="regressed",
            summary="tool_registry is empty",
            severity="critical",
        )
    return LayerFinding(
        layer="L06_tool_selection",
        status="clean",
        summary=f"{len(registry)} tool(s) registered",
    )


def check_answer_shaping_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L09 — V3 #30a envelope module shipped + extra fields present.

    Verifies ``shared/mcp/schemas/envelopes.py`` carries ``summary``,
    ``next_actions``, and ``artifacts`` — the B2 contract additions.
    Missing fields indicate the envelope rolled back to pre-B2 shape.
    """
    envelopes_path = repo_root / "shared" / "mcp" / "schemas" / "envelopes.py"
    if not envelopes_path.exists():
        return LayerFinding(
            layer="L09_answer_shaping",
            status="regressed",
            summary="shared/mcp/schemas/envelopes.py missing",
            severity="critical",
        )
    text = envelopes_path.read_text(encoding="utf-8")
    missing = [
        f for f in ("summary", "next_actions", "artifacts")
        if f not in text
    ]
    if missing:
        return LayerFinding(
            layer="L09_answer_shaping",
            status="regressed",
            summary=(
                "B2 envelope additions missing — answer shape regressed "
                "to pre-V3 #30a contract"
            ),
            severity="critical",
            evidence=tuple(missing),
        )
    return LayerFinding(
        layer="L09_answer_shaping",
        status="clean",
        summary="V3 #30a envelope fields present in shared envelope schema",
    )


def check_evals_layer(repo_root: Path, signals: dict) -> LayerFinding:
    """L11 — charter eval suite present + ≥ 3 starter evals per role.

    Pass: ``verify/charter_evals/engineer/`` and ``architect/`` exist
    and each contains ≥ 3 ``.yaml`` files. The threshold matches the
    one the loader test enforces — a charter cannot pass #7a's gate
    on fewer than 3 evals.
    """
    base = repo_root / "verify" / "charter_evals"
    if not base.is_dir():
        return LayerFinding(
            layer="L11_evals",
            status="regressed",
            summary="verify/charter_evals/ missing — #7a gate cannot fire",
            severity="critical",
        )
    issues: list[str] = []
    for role in ("engineer", "architect"):
        role_dir = base / role
        if not role_dir.is_dir():
            issues.append(f"{role}/: missing")
            continue
        yamls = sorted(role_dir.glob("*.yaml"))
        if len(yamls) < 3:
            issues.append(f"{role}/: {len(yamls)} eval(s) (< 3)")
    if issues:
        return LayerFinding(
            layer="L11_evals",
            status="warning",
            summary="charter eval count below #7a enforcement threshold",
            severity="medium",
            evidence=tuple(issues),
            next_actions=(
                "land additional capability evals or wait for the "
                "starter pack to fill in",
            ),
        )
    return LayerFinding(
        layer="L11_evals",
        status="clean",
        summary="engineer + architect each carry ≥ 3 capability evals",
    )


def check_promotion_gate_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L12 — V3 #12a decision-ledger denial rate within bound.

    ``signals['ledger_summary']`` is expected to be a mapping with
    ``denials_in_window`` / ``window_size`` keys when the orchestrator
    or ``spine status --markdown`` aggregator populates it. Absent ⇒
    ``instrumentation_pending``.
    """
    summary = signals.get("ledger_summary")
    if summary is None:
        return _pending(
            "L12_promotion_gate",
            "no ledger_summary signal (pipe in via "
            "shared.audit.decision_ledger aggregation)",
        )
    if not isinstance(summary, dict):
        return LayerFinding(
            layer="L12_promotion_gate",
            status="regressed",
            summary=f"ledger_summary signal is not a dict (got {type(summary).__name__})",
            severity="high",
        )
    denials = int(summary.get("denials_in_window", 0))
    window = int(summary.get("window_size", 0) or 0)
    if window == 0:
        return _pending(
            "L12_promotion_gate",
            "ledger_summary window_size is 0",
        )
    denial_rate = denials / window
    if denial_rate >= 0.5:
        return LayerFinding(
            layer="L12_promotion_gate",
            status="regressed",
            summary=(
                f"promotion gate denying {denials}/{window} "
                f"({denial_rate:.0%}) — investigate freshness / replay"
            ),
            severity="high",
            evidence=(f"denials={denials}", f"window={window}"),
        )
    if denial_rate >= 0.25:
        return LayerFinding(
            layer="L12_promotion_gate",
            status="warning",
            summary=(
                f"promotion gate denying {denials}/{window} "
                f"({denial_rate:.0%}) — elevated denial rate"
            ),
            severity="medium",
            evidence=(f"denials={denials}", f"window={window}"),
        )
    return LayerFinding(
        layer="L12_promotion_gate",
        status="clean",
        summary=f"promotion gate denial rate {denial_rate:.0%} within bound",
    )


# ─── Layers without native checks (yet) ──────────────────────────────


def _pending_check(layer: LayerId, why: str) -> Callable[[Path, dict], LayerFinding]:
    def _check(repo_root: Path, signals: dict) -> LayerFinding:
        return _pending(layer, why)
    return _check


DEFAULT_CHECKS: tuple[LayerCheck, ...] = (
    LayerCheck("L01_system_prompt", check_system_prompt_layer),
    LayerCheck(
        "L02_session_history",
        _pending_check(
            "L02_session_history",
            "no instrumentation — would inspect .spine/work/<run_id>/ "
            "directives for stale-context bleed across cycles",
        ),
    ),
    LayerCheck("L03_long_term_memory", check_long_term_memory_layer),
    LayerCheck(
        "L04_distillation",
        _pending_check(
            "L04_distillation",
            "no instrumentation — audit-ledger compression / summary "
            "ratios not yet captured",
        ),
    ),
    LayerCheck(
        "L05_active_recall",
        _pending_check(
            "L05_active_recall",
            "no instrumentation — KG retrieval hit-rate and result-set "
            "size not yet captured by shared.runtime.kg_role_context",
        ),
    ),
    LayerCheck("L06_tool_selection", check_tool_selection_layer),
    LayerCheck(
        "L07_tool_execution",
        _pending_check(
            "L07_tool_execution",
            "no instrumentation — tool call status mix (ok / error / "
            "refusal) not yet aggregated",
        ),
    ),
    LayerCheck(
        "L08_tool_interpretation",
        _pending_check(
            "L08_tool_interpretation",
            "no instrumentation — next_actions parsing success rate "
            "not yet captured",
        ),
    ),
    LayerCheck("L09_answer_shaping", check_answer_shaping_layer),
    LayerCheck(
        "L10_transport",
        _pending_check(
            "L10_transport",
            "no instrumentation — SPA / API / federation transport "
            "mutation surfaces not yet captured",
        ),
    ),
    LayerCheck("L11_evals", check_evals_layer),
    LayerCheck("L12_promotion_gate", check_promotion_gate_layer),
)


def scan_agent_stack(
    *,
    repo_root: Path,
    signals: dict | None = None,
    checks: Sequence[LayerCheck] | None = None,
) -> AgentAuditReport:
    """Run every layer check against ``repo_root`` and return a report.

    ``signals`` carries live-runtime state that the on-disk checks
    cannot derive themselves (tool registry, ledger denial counts).
    Tests pass synthetic signals; production callers pipe in the
    output of ``spine status --markdown`` collectors.
    """
    signals = dict(signals or {})
    checks = tuple(checks) if checks is not None else DEFAULT_CHECKS
    findings = tuple(c.fn(repo_root, signals) for c in checks)
    return AgentAuditReport(findings=findings)


__all__ = [
    "AgentAuditReport",
    "DEFAULT_CHECKS",
    "LayerCheck",
    "LayerFinding",
    "LayerId",
    "LayerSeverity",
    "LayerStatus",
    "check_answer_shaping_layer",
    "check_evals_layer",
    "check_long_term_memory_layer",
    "check_promotion_gate_layer",
    "check_system_prompt_layer",
    "check_tool_selection_layer",
    "scan_agent_stack",
]

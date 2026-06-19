"""Reference ``role_callable`` implementations for charter evals.

The harness in :mod:`verify.charter_evals.harness` is provider-agnostic
— it never calls an LLM. Callers supply a :data:`RoleCallable` at run
time. This module ships:

* :func:`stub_role_callable` — returns canned output keyed on the
  eval ``name``. Lets operators see the gate fire green / red without
  any LLM cost. Useful for CI smoke checks of the harness itself.
* :func:`fixture_role_callable_from_dir` — reads ``<dir>/<eval-name>``
  text files and returns the contents as the role output. Lets a team
  capture a known-good run, commit the fixture, and gate regressions
  against it without re-running the model.

A real LLM-backed callable (Claude Code / Cursor / charter daemon)
plugs in by satisfying the same :data:`RoleCallable` shape — see
:func:`make_anthropic_role_callable` in the docstring for the contract.
"""
from __future__ import annotations

from pathlib import Path

from verify.charter_evals.harness import CapabilityEval, RoleCallable


# ─── Stub: canned responses by eval name ─────────────────────────────


# Each entry is keyed on the eval's ``name`` field. Pass / fail is
# determined by whether the canned output trips the eval's criteria.
# Canned outputs are crafted to pass every shipped eval criterion so
# offline stub runs exercise the green gate path (CI smoke + operators).
_STUB_RESPONSES: dict[str, str] = {
    # ── Engineer evals ──────────────────────────────────────────────
    "engineer-cites-req-id-in-report": (
        "Implementation report for REQ-AUTH-7 (rotate session keys "
        "every 24h). Touched shared/auth/session.py and added a "
        "scheduled job. Lint + tests pass."
    ),
    "engineer-declares-implementer-kind": (
        "Report metadata: implementer_kind: claude_code, "
        "autonomy_tier: autonomous, agent_version: 4.7-1m."
    ),
    "engineer-honours-search-first-contract": (
        "Pre-implementation note: searched npm + MCP catalog; "
        "evaluated jose vs jsonwebtoken; adopt jose (active "
        "maintenance, smaller surface). Recorded chosen path in "
        "decision ledger before any Write/Edit."
    ),
    # ── Architect evals ─────────────────────────────────────────────
    "architect-cites-kg-node-id": (
        "ADR-0042: introduce decision-ledger boundary. "
        "kg_citations: [node-decision-ledger-design, "
        "node-spine-audit-chain]. Reversibility: two_way_door."
    ),
    "architect-declares-reversibility": (
        "ADR-0043: top-level subsystem 'forecast'. "
        "reversibility: one_way_door. rationale: data shape "
        "commitment crosses federation."
    ),
    "architect-anchors-in-recognised-methodology": (
        "TRD section: auth subsystem characteristics classified per "
        "TOGAF Architecture Capability Framework. Non-functional "
        "requirements mapped to ISO 25010 quality attributes."
    ),
}


def stub_role_callable(eval_: CapabilityEval, trial_index: int) -> str:
    """Return a canned response keyed on ``eval_.name``.

    Falls back to an empty string for unknown eval names — that fails
    every criterion, making the missing-canned-data case visible.
    """
    return _STUB_RESPONSES.get(eval_.name, "")


# ─── Fixture: per-eval text files ─────────────────────────────────────


def fixture_role_callable_from_dir(root: Path) -> RoleCallable:
    """Build a callable that reads ``<root>/<eval-name>.txt`` per call.

    Useful when a team wants to commit a known-good model response
    once and gate regressions against the fixture without re-running
    the LLM. Missing files yield an empty string (which fails every
    criterion).
    """
    root = Path(root)

    def _read(eval_: CapabilityEval, trial_index: int) -> str:
        path = root / f"{eval_.name}.txt"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    return _read


# ─── Anthropic-backed callable (documented contract; no implementation) ───
#
# An LLM-backed callable plugs into the harness by satisfying the
# RoleCallable shape::
#
#     def make_anthropic_role_callable(
#         *,
#         api_key: str,
#         model: str = "claude-sonnet-4-6",
#         charter_path: Path,
#     ) -> RoleCallable:
#         from anthropic import Anthropic
#         client = Anthropic(api_key=api_key)
#         system_prompt = charter_path.read_text(encoding="utf-8")
#
#         def _call(eval_: CapabilityEval, trial_index: int) -> str:
#             resp = client.messages.create(
#                 model=model,
#                 system=system_prompt,
#                 max_tokens=1024,
#                 messages=[{"role": "user", "content": eval_.task}],
#             )
#             return resp.content[0].text
#
#         return _call
#
# Not implemented here to keep the harness importable without an SDK
# dependency. Drop the snippet in a project-local module when wiring
# up a real charter eval run.


__all__ = [
    "fixture_role_callable_from_dir",
    "stub_role_callable",
]

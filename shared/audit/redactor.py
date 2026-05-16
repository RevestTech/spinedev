"""PII / secret redaction for AuditRecord rows — STORY-3.1.4.

Implements REQ-INIT-3 EPIC-3.1 NFR-3 ("audit log MUST NOT persist
secrets or PII in cleartext"). The redactor walks each
``AuditRecord`` field (string-typed + the ``metadata`` JSON tree) and
substitutes regex-matched secrets with a fixed sentinel before the row
is shipped to ``spine_audit.audit_event``.

Design choices
--------------
* **Stateless.** ``redact()`` returns a NEW record; the input is never
  mutated, so callers can safely retain the pre-redaction object for
  internal-only logging (off the persisted audit chain).
* **Severity tiers.** ``always`` always applies, ``default`` applies
  unless explicitly disabled, ``opt_in`` (e.g. ``email``) is off by
  default because the false-positive rate is too high for a hash-chain
  that must not silently rewrite "user@org.io" inside legitimate
  rationale text. Org bundles can promote tiers.
* **Hashes are kept.** ``prompt_hash`` and ``output_hash`` are SHA-256
  digests already — redacting them would destroy the only useful
  field for de-duplication while gaining no privacy (hashes are
  one-way).
* **Compiled once.** Pattern regexes are compiled at module load and
  re-used across rows. Per-row cost ~µs for the default rule set.

See also: ``redactor_README.md``, V15 schema, ``audit_record.py``.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Iterable, Literal, Optional

from pydantic import BaseModel, Field

from .audit_record import AuditRecord

Severity = Literal["always", "default", "opt_in"]
_REDACTED = "[REDACTED]"

# Fields on AuditRecord that may contain free-form user content. The
# ``metadata`` field is a dict and walked recursively.
_STRING_FIELDS: tuple[str, ...] = (
    "rationale",
    "error_message",
    "subject_id",
    "actor",
)
_DICT_FIELDS: tuple[str, ...] = ("metadata",)


class RedactionRule(BaseModel):
    """One regex-based redaction rule, applied to a set of record fields."""

    name: str
    pattern: str
    replacement: str = _REDACTED
    fields: list[str] = Field(default_factory=lambda: list(_STRING_FIELDS + _DICT_FIELDS))
    severity: Severity = "default"
    flags: int = 0  # re.DOTALL etc. as an int so the model stays JSON-safe.

    _compiled: ClassVar[dict[str, re.Pattern[str]]] = {}

    def compiled(self) -> re.Pattern[str]:
        """Return the lazily-compiled regex for this rule (process-wide cache)."""
        key = f"{self.name}::{self.flags}::{self.pattern}"
        cache = type(self)._compiled
        rx = cache.get(key)
        if rx is None:
            rx = re.compile(self.pattern, self.flags)
            cache[key] = rx
        return rx


class RedactionResult(BaseModel):
    """Summary of what the redactor touched on one record."""

    redactions_applied: int = 0
    rules_matched: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Default rule set. Order matters only for human inspection — every
# rule scans every applicable field, no early-exit.
# ─────────────────────────────────────────────────────────────────────
DEFAULT_RULES: list[RedactionRule] = [
    RedactionRule(name="aws_access_key",
                  pattern=r"AKIA[0-9A-Z]{16}"),
    RedactionRule(name="aws_secret_key",
                  pattern=r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),
    RedactionRule(name="jwt",
                  pattern=r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    RedactionRule(name="github_pat",
                  pattern=r"gh[pousr]_[A-Za-z0-9]{36,}"),
    RedactionRule(name="anthropic_key",
                  pattern=r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    RedactionRule(name="openai_key",
                  pattern=r"sk-[A-Za-z0-9]{32,}"),
    RedactionRule(name="bearer_token",
                  pattern=r"Bearer\s+[A-Za-z0-9_.\-]{16,}"),
    RedactionRule(name="credit_card",
                  pattern=r"\b(?:\d[ -]*?){13,16}\b"),
    RedactionRule(name="private_key_pem",
                  pattern=r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
                  flags=re.DOTALL),
    # opt_in rules — high false-positive risk; promoted by org bundles.
    RedactionRule(name="email",
                  pattern=r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
                  severity="opt_in"),
    RedactionRule(name="us_ssn",
                  pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                  severity="opt_in"),
    RedactionRule(name="us_phone",
                  pattern=r"\b\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b",
                  severity="opt_in"),
]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

_SEVERITY_RANK: dict[Severity, int] = {"opt_in": 0, "default": 1, "always": 2}


def _passes_floor(rule: RedactionRule, floor: Severity) -> bool:
    """True if ``rule.severity`` is at least as strong as ``floor``."""
    if rule.severity == "always":
        return True
    return _SEVERITY_RANK[rule.severity] >= _SEVERITY_RANK[floor]


def _redact_str(s: str, rules: Iterable[RedactionRule], result: RedactionResult,
                field: str) -> str:
    """Apply each rule to ``s``, accumulating stats into ``result``."""
    out = s
    for rule in rules:
        new, n = rule.compiled().subn(rule.replacement, out)
        if n:
            result.redactions_applied += n
            if rule.name not in result.rules_matched:
                result.rules_matched.append(rule.name)
            if field not in result.redacted_fields:
                result.redacted_fields.append(field)
            out = new
    return out


def _redact_value(value: Any, rules: list[RedactionRule], result: RedactionResult,
                  field: str) -> Any:
    """Recurse into dict/list/str leaves and redact strings in-place by copy."""
    if isinstance(value, str):
        return _redact_str(value, rules, result, field)
    if isinstance(value, dict):
        return {k: _redact_value(v, rules, result, f"{field}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, rules, result, f"{field}[]") for v in value]
    return value


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def redact(record: AuditRecord, *,
           rules: Optional[list[RedactionRule]] = None,
           severity_floor: Severity = "default") -> tuple[AuditRecord, RedactionResult]:
    """Return ``(redacted_record, summary)``; the input ``record`` is not mutated.

    ``severity_floor`` filters the active rule set. ``"opt_in"`` enables
    everything (including email/SSN/phone). ``"default"`` is the
    production default. ``"always"`` is the most conservative: only
    rules explicitly marked ``always`` run.
    """
    active = [r for r in (rules or DEFAULT_RULES) if _passes_floor(r, severity_floor)]
    result = RedactionResult()
    updates: dict[str, Any] = {}

    for fname in _STRING_FIELDS:
        current = getattr(record, fname, None)
        if isinstance(current, str) and current:
            applicable = [r for r in active if fname in r.fields or not r.fields]
            new = _redact_str(current, applicable, result, fname)
            if new != current:
                updates[fname] = new

    for fname in _DICT_FIELDS:
        current = getattr(record, fname, None)
        if isinstance(current, dict) and current:
            applicable = [r for r in active if fname in r.fields or not r.fields]
            new_dict = _redact_value(current, applicable, result, fname)
            if new_dict != current:
                updates[fname] = new_dict

    if not updates:
        return record, result
    # content_hash must be recomputed downstream (chain_to_previous);
    # clear it here so a stale hash can't slip through.
    updates["content_hash"] = None
    return record.model_copy(update=updates), result


def load_org_rules(bundle_id: str) -> list[RedactionRule]:
    """Load org-bundle ``security.redaction_rules`` and merge with defaults.

    The bundle file is expected at
    ``$SPINE_HOME/bundles/<bundle_id>/redaction_rules.json`` as a JSON
    array of ``RedactionRule`` objects. Missing file -> defaults only.
    """
    import json
    import os

    path = os.path.join(
        os.environ.get("SPINE_HOME", os.path.expanduser("~/.spine")),
        "bundles", bundle_id, "redaction_rules.json",
    )
    if not os.path.exists(path):
        return list(DEFAULT_RULES)
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    custom = [RedactionRule.model_validate(item) for item in raw]
    # Custom rules override defaults of the same name.
    by_name = {r.name: r for r in DEFAULT_RULES}
    for r in custom:
        by_name[r.name] = r
    return list(by_name.values())


def redact_text(text: str, *, rules: Optional[list[RedactionRule]] = None,
                severity_floor: Severity = "default") -> tuple[str, RedactionResult]:
    """Dry-run helper: redact a raw string (used by ``spine audit redaction test``)."""
    active = [r for r in (rules or DEFAULT_RULES) if _passes_floor(r, severity_floor)]
    result = RedactionResult()
    return _redact_str(text, active, result, "<input>"), result

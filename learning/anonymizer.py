"""Tier 2 anonymization pipeline — Wave 4 Squad D / V3 #27.

Per #27, Tier 2 (cross-org) telemetry is **anonymized + aggregated
only; no raw customer data leaves**. This module is the single place
that decides whether a pattern aggregate is releasable.

Method choice — k-anonymity (k>=5) by default
---------------------------------------------

We default to **k-anonymity** with k=5 because:

  1. **Sufficient for aggregate counters.** Tier 2 only exports
     pattern *counts* (e.g. ``{pattern_class='late_qa_gate', count=17,
     period='2026-05'}``). k-anonymity guarantees any individual
     customer's contribution to a count is indistinguishable among at
     least k=5 contributors.
  2. **Auditable + explainable.** Differential privacy adds calibrated
     noise that is mathematically rigorous but harder to explain to a
     customer admin reading an audit row ("why does the count differ
     from my dashboard?"). k-anonymity returns a deterministic
     suppress-or-pass decision the admin can verify by inspection.
  3. **Tunable per-bundle.** Enterprise bundles can raise k to 10 or
     15 by passing a stricter :class:`KAnonymityMethod`; vendor's
     internal Tier 3 deployment can drop k=1 (no anonymization) for
     self-improvement loops since it's the vendor's own data.
  4. **DP available as opt-in.** :class:`DifferentialPrivacyMethod`
     is provided as a stub that adds Laplace noise scaled by 1/epsilon;
     bundles that prefer DP (e.g. for SOC2 / FedRAMP customers) can
     swap it in via ``anonymize_for_cross_org(..., method=dp_method)``.

Output contract
---------------

Every :class:`AnonymizationResult` carries:
  * ``release_ok`` — bool; False means the aggregate failed the policy.
  * ``anonymization_method`` — string in the V29 ``telemetry_anonymized
    .anonymization_method`` format ("k_anonymity_N" / "differential_
    privacy_epsX" / "synthetic").
  * ``redacted_fields`` — list of fields scrubbed.
  * ``report`` — :class:`AnonymizationReport` with the per-step decisions
    so the audit chain can replay the privacy decision.

No raw lesson_text is ever included in the result; callers must produce
their own ``pattern_class`` summary BEFORE calling this module.
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_K = 5
DEFAULT_EPSILON = 1.0  # diff-priv stub default; not used unless method picked.


# Field denylist — never released into Tier 2 telemetry regardless of method.
_ALWAYS_REDACT = (
    "user_email", "user_id", "actor", "actor_id", "project_id", "project_name",
    "hub_id", "hub_name", "repo", "repo_url", "commit_sha", "file_path",
    "rationale", "lesson_text", "source_audit_record_id", "ip_address",
)

# Patterns that look like raw data slipped into a pattern_class string.
_PII_RE = re.compile(
    r"(?i)([\w.+-]+@[\w-]+\.[\w.-]+)|(\b\d{3}-\d{2}-\d{4}\b)|"
    r"(\b[A-F0-9]{32,}\b)|"  # long hex strings (hashes / tokens)
    r"(\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b)"  # ipv4
)


class AnonymizationMethodKind(str, Enum):
    K_ANONYMITY = "k_anonymity"
    DIFFERENTIAL_PRIVACY = "differential_privacy"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class AnonymizationMethod:
    """Abstract method descriptor.

    Subclasses set ``kind`` + ``label`` and parameterize ``k`` or
    ``epsilon``. ``label`` MUST match the V29 column format
    (``k_anonymity_5`` / ``differential_privacy_eps1`` / ``synthetic``).
    """
    kind: AnonymizationMethodKind
    label: str
    k: Optional[int] = None
    epsilon: Optional[float] = None


def k_anonymity_method(k: int = DEFAULT_K) -> AnonymizationMethod:
    if k < 1:
        raise ValueError("k must be >= 1")
    return AnonymizationMethod(
        kind=AnonymizationMethodKind.K_ANONYMITY,
        label=f"k_anonymity_{k}",
        k=k,
    )


def differential_privacy_method(epsilon: float = DEFAULT_EPSILON) -> AnonymizationMethod:
    if epsilon <= 0:
        raise ValueError("epsilon must be > 0")
    # V29 column expects integer eps suffix per spec ("differential_privacy_epsX").
    eps_label = int(epsilon) if float(epsilon).is_integer() else epsilon
    return AnonymizationMethod(
        kind=AnonymizationMethodKind.DIFFERENTIAL_PRIVACY,
        label=f"differential_privacy_eps{eps_label}",
        epsilon=epsilon,
    )


def synthetic_method() -> AnonymizationMethod:
    return AnonymizationMethod(
        kind=AnonymizationMethodKind.SYNTHETIC,
        label="synthetic",
    )


def available_methods() -> tuple[str, ...]:
    """Labels Hub UI can list as anonymization options."""
    return ("k_anonymity_5", "k_anonymity_10", "differential_privacy_eps1", "synthetic")


@dataclass
class AnonymizationReport:
    """Audit-trail of the privacy decisions for one aggregate."""
    pattern_class: str
    method_label: str
    k: Optional[int] = None
    epsilon: Optional[float] = None
    contributor_count: int = 0
    redacted_fields: list[str] = field(default_factory=list)
    pii_hits: list[str] = field(default_factory=list)
    suppressed_reason: Optional[str] = None
    noise_added: Optional[float] = None


@dataclass
class AnonymizationResult:
    """Output of :func:`anonymize_for_cross_org`."""
    release_ok: bool
    pattern_class: str
    count: int
    period: str
    anonymization_method: str
    report: AnonymizationReport
    redacted_fields: list[str] = field(default_factory=list)
    aggregate_hash: str = ""


# ─── Internals ──────────────────────────────────────────────────────


def _scrub_fields(extra: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    redacted: list[str] = []
    clean: dict[str, Any] = {}
    for k, v in extra.items():
        if k in _ALWAYS_REDACT:
            redacted.append(k)
            continue
        # Recursive scrub for nested mappings.
        if isinstance(v, dict):
            inner, inner_red = _scrub_fields(v)
            if inner_red:
                redacted.extend(f"{k}.{r}" for r in inner_red)
            clean[k] = inner
        elif isinstance(v, str) and _PII_RE.search(v):
            redacted.append(k)
        else:
            clean[k] = v
    return clean, redacted


def _scan_pattern_class_for_pii(pattern_class: str) -> list[str]:
    hits = [m.group(0) for m in _PII_RE.finditer(pattern_class)]
    return hits


def _hash_aggregate(pattern_class: str, count: int, period: str, label: str) -> str:
    h = hashlib.sha256()
    h.update(pattern_class.encode("utf-8"))
    h.update(str(count).encode("utf-8"))
    h.update(period.encode("utf-8"))
    h.update(label.encode("utf-8"))
    return h.hexdigest()


def _laplace_noise(scale: float, *, seed: Optional[int] = None) -> float:
    """Sample Laplace(0, scale). Deterministic when ``seed`` is given (tests)."""
    rng = random.Random(seed) if seed is not None else random
    u = rng.random() - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))


# ─── Public entry ───────────────────────────────────────────────────


def anonymize_for_cross_org(
    *,
    pattern_class: str,
    count: int,
    period: str,
    contributor_ids: Iterable[str],
    extra_fields: Optional[dict[str, Any]] = None,
    method: Optional[AnonymizationMethod] = None,
    deterministic_noise_seed: Optional[int] = None,
) -> AnonymizationResult:
    """Run an aggregate through the Tier 2 anonymization pipeline.

    Steps:
      1. Validate count + pattern_class (refuse if PII detected in name).
      2. Scrub denylisted + PII-matching fields from ``extra_fields``.
      3. Apply the chosen method:
         * k-anonymity: require len(set(contributor_ids)) >= k.
         * differential privacy: add Laplace noise; allow always.
         * synthetic: return a single placeholder count.
      4. Emit a fully-populated :class:`AnonymizationReport`.

    The function NEVER raises on policy failure — it returns
    ``release_ok=False`` with a populated ``suppressed_reason`` so the
    caller can audit the suppression.
    """
    method = method or k_anonymity_method(DEFAULT_K)
    pii_hits = _scan_pattern_class_for_pii(pattern_class)
    extras_clean, redacted = _scrub_fields(dict(extra_fields or {}))
    distinct_contribs = {str(c) for c in contributor_ids if c is not None}
    contributor_count = len(distinct_contribs)

    report = AnonymizationReport(
        pattern_class=pattern_class,
        method_label=method.label,
        k=method.k,
        epsilon=method.epsilon,
        contributor_count=contributor_count,
        redacted_fields=list(redacted),
        pii_hits=pii_hits,
    )

    # Hard refusal if pattern_class itself leaks PII — caller must
    # construct a generalized class first.
    if pii_hits:
        report.suppressed_reason = "pii_in_pattern_class"
        return AnonymizationResult(
            release_ok=False,
            pattern_class=pattern_class,
            count=0,
            period=period,
            anonymization_method=method.label,
            report=report,
            redacted_fields=list(redacted),
        )

    released_count = count
    noise_added: Optional[float] = None

    if method.kind == AnonymizationMethodKind.K_ANONYMITY:
        k = method.k or DEFAULT_K
        if contributor_count < k:
            report.suppressed_reason = (
                f"k_anonymity_violation: contributors={contributor_count} < k={k}"
            )
            return AnonymizationResult(
                release_ok=False,
                pattern_class=pattern_class,
                count=0,
                period=period,
                anonymization_method=method.label,
                report=report,
                redacted_fields=list(redacted),
            )
    elif method.kind == AnonymizationMethodKind.DIFFERENTIAL_PRIVACY:
        eps = method.epsilon or DEFAULT_EPSILON
        scale = 1.0 / eps  # sensitivity=1 for counting queries
        noise_added = _laplace_noise(scale, seed=deterministic_noise_seed)
        released_count = max(0, int(round(count + noise_added)))
        report.noise_added = noise_added
    elif method.kind == AnonymizationMethodKind.SYNTHETIC:
        # Synthetic: report only that the pattern was observed (count
        # collapsed to 1 if non-zero). Never leak true magnitude.
        released_count = 1 if count > 0 else 0

    digest = _hash_aggregate(pattern_class, released_count, period, method.label)
    return AnonymizationResult(
        release_ok=True,
        pattern_class=pattern_class,
        count=released_count,
        period=period,
        anonymization_method=method.label,
        report=report,
        redacted_fields=list(redacted),
        aggregate_hash=digest,
    )


__all__ = [
    "AnonymizationMethod",
    "AnonymizationMethodKind",
    "AnonymizationReport",
    "AnonymizationResult",
    "anonymize_for_cross_org",
    "available_methods",
    "differential_privacy_method",
    "k_anonymity_method",
    "synthetic_method",
]

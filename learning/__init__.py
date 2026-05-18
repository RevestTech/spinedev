"""Spine v3 ``learning/`` — Smart Spine 3-tier learning loop.

Per design decision **#27** in ``docs/V3_DESIGN_DECISIONS.md`` and the
Wave 4 Squad D spec in ``docs/V3_BUILD_SEQUENCE.md``, this subsystem
implements the three learning tiers + the vendor-self-improvement loop
(Tier 3):

    Tier 1a — per-project           always on
    Tier 1b — within-Hub federation default ON  (admin-disable per bundle)
    Tier 2  — cross-org / vendor    default OFF (explicit, granular opt-in)
    Tier 3  — vendor self-improvement always on for vendor's own deployment

The public surface is intentionally narrow — most callers use:

    from learning import (
        resolve_scope, contribute_lesson, grant_cross_org_consent,
        revoke_cross_org_consent, anonymize_for_cross_org,
        vendor_self_improvement_record,
    )

Implementation notes
--------------------
* Lessons originate in ``spine_memory.lesson`` (Wave 1 ``writer_hooks``).
  This subsystem READS those and WRITES tier-scoped copies into
  ``spine_learning.lesson`` after gating through ``scope.resolve`` +
  ``contribute.gate``.
* Tier 2 export pipeline goes through :mod:`learning.anonymizer` which
  is privacy-review-blocking — no Tier 2 export bypasses it.
* All secret access (Vault tokens for vendor self-improvement push)
  routes through :mod:`shared.secrets` per V3 #9.
* MCP tools live in :mod:`shared.mcp.tools.learning`; the consent grant
  tool is tagged ``requires_citation=True`` per V3 #12 because granting
  cross-org learning is a high-stakes data-sharing decision.
"""
from __future__ import annotations

from .anonymizer import (
    AnonymizationMethod,
    AnonymizationReport,
    AnonymizationResult,
    anonymize_for_cross_org,
    available_methods,
)
from .consent import (
    ConsentDecision,
    ConsentRecord,
    grant_cross_org_consent,
    list_cross_org_consents,
    revoke_cross_org_consent,
)
from .contribute import (
    ContributionDecision,
    ContributionOutcome,
    contribute_lesson,
    gate,
)
from .scope import (
    LearningScope,
    ScopeContext,
    ScopePolicy,
    resolve_scope,
)
from .vendor_self_improvement import (
    VendorSelfImprovementEvent,
    is_vendor_deployment,
    vendor_self_improvement_record,
)

__all__ = [
    # scope.py
    "LearningScope",
    "ScopeContext",
    "ScopePolicy",
    "resolve_scope",
    # contribute.py
    "ContributionDecision",
    "ContributionOutcome",
    "contribute_lesson",
    "gate",
    # consent.py
    "ConsentDecision",
    "ConsentRecord",
    "grant_cross_org_consent",
    "list_cross_org_consents",
    "revoke_cross_org_consent",
    # anonymizer.py
    "AnonymizationMethod",
    "AnonymizationReport",
    "AnonymizationResult",
    "anonymize_for_cross_org",
    "available_methods",
    # vendor_self_improvement.py
    "VendorSelfImprovementEvent",
    "is_vendor_deployment",
    "vendor_self_improvement_record",
]

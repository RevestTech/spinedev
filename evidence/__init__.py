"""evidence/ — Spine v3 Evidence Store + GRC-vendor push.

Implements V3 design decision #24 (Vanta + Drata + Secureframe first-class
Day 1; Tugboat / Strike Graph / Thoropass v1.1+) on top of the
``spine_evidence`` schema (db/flyway/sql/V25__evidence_store.sql).

Public surface
==============

Collectors (``evidence.collectors``) translate Spine audit/devops events
into ``EvidencePayload`` objects pointed at a ``spine_evidence.control``::

    from evidence.collectors.audit_chain   import collect_audit_chain
    from evidence.collectors.role_decision import collect_role_decisions
    from evidence.collectors.vault_access  import collect_vault_access
    from evidence.collectors.deploy        import collect_deploys
    from evidence.collectors.approval      import collect_approvals

Exporters (``evidence.exporters``) push a batch of evidence to a GRC
vendor over HTTP. All exporter credentials route through
``shared.secrets.get_secret`` (decision #9 — vault-only). Vanta, Drata,
and Secureframe are real Day-1 implementations. Tugboat Logic, Strike
Graph, and Thoropass are stubbed in v1.1+ form (raise NotImplementedError
on ``send()``) with config + auth wired so v1.1 promotion is a one-file
swap-in.

Two-party attestation
=====================

``evidence.two_party_attestation`` produces and verifies the
``spine_evidence.evidence_record.two_party_attestation_hash`` per V25
schema. Hash input order is FIXED::

    SHA-256(payload_canonical_json || attestor_A_signature ||
            attestor_B_signature)

See ``two_party_attestation.py`` for canonicalisation rules and the
verification flow (regenerate -> compare bytes).

MCP surface
===========

The four user-facing MCP tools live in ``shared/mcp/tools/evidence.py``:

  * ``evidence_collect`` (requires_citation=True per #12)
  * ``evidence_export``  (requires_citation=True per #12)
  * ``evidence_status``  (read-only; no citation requirement)
  * ``evidence_attestation_verify`` (read-only verification)

Notes
=====

* No collector or exporter holds raw credentials in process state — every
  fetch is awaited through ``shared.secrets`` and the value is dropped as
  soon as the HTTP request returns (per #9).
* Every export call appends a row to ``spine_evidence.export_log``
  whether it succeeds or fails — the log is the auditor's first
  corroboration point for the two-party attestation flow.
"""

from __future__ import annotations

__all__: list[str] = [
    "EvidencePayload",
    "ExportBatch",
    "ExportResult",
]


# Re-export the core dataclasses so callers can do
#   from evidence import EvidencePayload
# without reaching into a submodule.
from evidence._types import EvidencePayload, ExportBatch, ExportResult

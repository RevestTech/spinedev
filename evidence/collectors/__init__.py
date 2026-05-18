"""Evidence collectors — translate Spine events into ``EvidencePayload``.

One module per source:

  * ``audit_chain``   — generic pull from ``spine_audit.audit_event``
                        filtered by framework + control_id (the default
                        collector; every audit row is potential evidence
                        per #24).
  * ``role_decision`` — captures role decision events
                        (action ∈ approval_granted, gate_check, ...).
  * ``vault_access``  — captures vault read/write events.
  * ``deploy``        — captures deploy events from
                        ``spine_devops.action_log``.
  * ``approval``      — captures approval grants.

Each collector exposes one top-level function
(``collect_*(framework, control_id, ...) -> list[EvidencePayload]``)
and a default mapping table tying its Spine actions to V25
``evidence_type`` values.
"""
from __future__ import annotations

__all__: list[str] = []

"""12-layer agent architecture audit for Spine (V3 B10 borrow).

Borrowed contract source: ECC ``agent-architecture-audit`` skill
(``affaan-m/ecc``, MIT). See ``docs/ECC_BORROWS.md`` (B10 added
2026-05-29). Implemented natively against Spine's own surfaces —
charters, MCP tool registry, decision ledger, envelope conventions,
charter evals — rather than as a port.

Where this fits
---------------

Charter evals (B6 / V3 #7a) tell you *that* a role regressed. The
12-layer audit tells you *where* in the agent stack the regression
lives so you can fix the right layer instead of guessing.

The audit is read-only: it inspects state, computes findings, and
returns a typed report. No fixes are applied — that is the role's
job per the relevant charter contract.
"""

from verify.agent_audit.introspection import (
    IntrospectionTrace,
    build_introspection_trace,
)
from verify.agent_audit.twelve_layer import (
    AgentAuditReport,
    LayerCheck,
    LayerFinding,
    LayerId,
    LayerSeverity,
    LayerStatus,
    scan_agent_stack,
)

__all__ = [
    "AgentAuditReport",
    "IntrospectionTrace",
    "LayerCheck",
    "LayerFinding",
    "LayerId",
    "LayerSeverity",
    "LayerStatus",
    "build_introspection_trace",
    "scan_agent_stack",
]

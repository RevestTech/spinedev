"""
federation
==========

Spine v3 Federation subsystem (Wave 4 Squad A).

Implements the fractal-Hub federation per `docs/V3_DESIGN_DECISIONS.md`:

* **#4 — Hub-to-Hub topology** (control plane / data plane split). Project
  Spines register with a parent Hub; aggregated reads pull up; bundle
  distribution pushes policy down.
* **#10 — Fractal Hub federation** ("a Hub is a Hub is a Hub"). Same
  container at every tier; consent-leaning trust model — peer-consent
  by default, bounded mandatory upward flows declared in bundle for
  compliance (e.g. corporate Hub can mandate security-incident reporting).
* **#16 — Update distribution via federation tree.** Vendor publishes
  signed bundles → parent Hub approves → cascades to child Hubs with their
  own approval gate. Auto-push is never an option. Audit chain captures
  every decision.

Public surface (locked for Wave 4):

    bootstrap_hub_id()        — read hub/_state/hub_id.txt; insert into
                                 spine_federation.hub if first start
    HubRegistry               — async CRUD over spine_federation.hub
    UpstreamClient            — mTLS + bearer client to parent Hub
    DownstreamRouter          — route delegated tools to child Hubs
    UpdateCascade             — vendor → parent → child distribution
                                 with per-tier approval gate
    ConsentEngine             — peer-consent default; bounded mandatory
                                 upward flows from bundle policy

All modules are async (asyncpg + httpx). All secrets (mTLS cert/key,
bearer tokens, parent-hub URLs that are sensitive) route through
`shared.secrets` per #9.

Cross-subsystem contracts honored:

* `hub_id` flows from `hub/_state/hub_id.txt` (written by the Day-0
  wizard) → `federation.hub_registry.bootstrap_hub_id()` on first Hub
  start → INSERT into `spine_federation.hub` if not present.
* mTLS material is vault-fetched: `federation/mtls/<role>/cert`,
  `federation/mtls/<role>/key`.
* The MCP tools in `shared/mcp/tools/federation.py` are tagged
  `requires_citation=True` for high-impact actions (#12).

Scope boundary: this package only touches `federation/*`,
`shared/schemas/federation/*`, and `shared/mcp/tools/federation.py`.
"""

from __future__ import annotations

from .consent import (
    ConsentClass,
    ConsentDecision,
    ConsentEngine,
    MandatoryFlowDenied,
)
from .downstream_router import DownstreamRouter, RoutingError
from .hub_registry import (
    HubRecord,
    HubRegistry,
    bootstrap_hub_id,
    read_hub_id_file,
)
from .update_cascade import (
    ApprovalRequired,
    CascadeOutcome,
    RolloutStatus,
    UpdateCascade,
    UpdateRecord,
)
from .upstream_client import UpstreamClient, UpstreamCallError

__all__ = [
    # hub_registry
    "HubRecord",
    "HubRegistry",
    "bootstrap_hub_id",
    "read_hub_id_file",
    # upstream
    "UpstreamClient",
    "UpstreamCallError",
    # downstream
    "DownstreamRouter",
    "RoutingError",
    # cascade
    "UpdateCascade",
    "UpdateRecord",
    "CascadeOutcome",
    "RolloutStatus",
    "ApprovalRequired",
    # consent
    "ConsentEngine",
    "ConsentClass",
    "ConsentDecision",
    "MandatoryFlowDenied",
]

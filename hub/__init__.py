"""
hub — Spine v3 containerized product (Wave 3 Squad B).

Per `docs/V3_DESIGN_DECISIONS.md` decision #3, the Hub is THE primary
management surface of Spine — not a template, not a CLI, not a library.
This package is the thin subsystem skeleton that:

    * Boots a FastAPI app via the shared.api.create_app factory
      (extended with Hub routes by Wave 3 Squad C).
    * Owns the Day-0 bootstrap wizard (`hub.wizard`) that runs once per
      deployment to wire the operator's choice of vault adapter +
      Keycloak deployment + LLM provider + initial admin + hub_id into
      a coherent runtime configuration.
    * Ships the container `Dockerfile`, `docker-compose.yml`,
      `entrypoint.sh`, and `healthcheck.sh` artifacts that distinguish
      the four deployment shapes (#17): laptop / BYOC / customer-cloud /
      on-prem.

The Python surface is intentionally small — most behavior lives in
`shared/*` packages so that the hub container, the CLI, and federated
Spines all share the same code paths.
"""

from __future__ import annotations

from hub.main import app, create_app  # re-export the ASGI app + factory

__all__: list[str] = ["app", "create_app"]
__version__: str = "0.1.0"  # synchronised with hub/Dockerfile spine.wave="3" label

"""hub.main — ASGI entry point for the Spine v3 Hub container.

This module exists solely so external runners (uvicorn, gunicorn, k8s
liveness probes, smoke tests) have a stable import path:

    uvicorn hub.main:app          # default ASGI app
    uvicorn hub.main:create_app --factory   # equivalent factory form

The actual FastAPI app is built by `shared.api.app.create_app()` per
decision #3 + the build-sequence note that "Hub uses the shared FastAPI
factory; Wave 3 Squad C extends `shared/api/` with new routes."

Keeping this file tiny is deliberate:

    * The Hub container reuses shared/api/ wholesale — there is no
      separate Hub-specific FastAPI factory to keep in sync.
    * Wave 3 Squad C may add Hub-specific middleware / routes via
      `shared/api/`; those automatically light up here without changes
      to `hub/main.py`.
    * The entrypoint.sh bootstrap (vault adapter install) runs BEFORE
      uvicorn imports this module, so `create_app()` finds a wired-up
      secrets backend already in place.
"""

from __future__ import annotations

from shared.api.app import create_app as _shared_create_app


def create_app():
    """Build and return the Hub's FastAPI app.

    Thin wrapper over :func:`shared.api.app.create_app` so callers that
    want explicit dependency on the Hub subsystem can target
    ``hub.main:create_app`` instead of reaching into ``shared.api`` —
    useful for tests that want to assert "the Hub uses the shared
    factory" without dual-imports.
    """
    return _shared_create_app()


# Eager construction so `uvicorn hub.main:app` (the most common entry
# form, no --factory flag needed) works out of the box. The shared
# factory is cheap to call at import time; lifespan handles the slow
# parts (DB ping, MCP discovery) after the worker accepts connections.
app = create_app()


__all__: list[str] = ["app", "create_app"]

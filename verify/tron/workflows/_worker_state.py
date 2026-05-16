"""
Worker-level state shared across Temporal activities.

Secrets are loaded once at worker startup and stored here so that
individual activities (which run in the same process) can access
them without repeated keyvault calls.

This is *not* a global singleton in the traditional sense — it's
scoped to the Temporal worker process. Each worker loads its own
secrets on boot via `init_worker_state()`.
"""

from __future__ import annotations

from typing import Dict, Optional

_secrets: Optional[Dict[str, str]] = None


def init_worker_state(secrets: Dict[str, str]) -> None:
    """Store secrets for the lifetime of this worker process.

    Called once from worker.py during startup.
    """
    global _secrets
    _secrets = dict(secrets)  # defensive copy


def get_worker_secrets() -> Dict[str, str]:
    """Retrieve secrets loaded at worker startup.

    Raises RuntimeError if called before init_worker_state().
    """
    if _secrets is None:
        raise RuntimeError(
            "Worker state not initialized. "
            "Call init_worker_state() during worker startup."
        )
    return _secrets

"""Pytest config for mobile-route smoke tests.

We reuse the OIDC + DB fixtures from ``shared/api/tests/conftest.py``
rather than duplicating them — the mobile API is a thin wrapper over
the existing Hub routes so the same Keycloak mock applies.

The sys.path hygiene (un-shadow stdlib ``secrets``) is done in
``shared/api/tests/conftest.py`` already; loading that as the plugin
inherits the same fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make repo root importable when pytest is invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytest_plugins = ("shared.api.tests.conftest",)

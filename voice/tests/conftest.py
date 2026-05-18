"""Pytest config for voice scaffold tests — reuses the shared OIDC fixture."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytest_plugins = ("shared.api.tests.conftest",)

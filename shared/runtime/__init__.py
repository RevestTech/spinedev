"""shared.runtime — cross-cutting runtime substrate (Wave 1, v3).

Per ``docs/V3_BUILD_SEQUENCE.md`` Part 1.1 (resolved layout):

    shared/runtime/   NEW   — substrate moved from lib/ (vitals,
                              heartbeat, watchdog, notify, executor,
                              usage-parsers, file-lock, updater,
                              db-outbox, AND #34 workspace hygiene).

Wave 1 (Squad B) seeds this package with the workspace-hygiene library
(``hygiene.py``). The remainder of the legacy ``lib/*.sh`` substrate
moves here in Wave 3 (Hub product) per the build-sequence plan; this
``__init__`` exports the API surface as packages land.
"""
from __future__ import annotations

from .hygiene import (
    HygieneSweep,
    Workspace,
    project_is_clean,
    workspace,
)

__all__ = [
    "HygieneSweep",
    "Workspace",
    "project_is_clean",
    "workspace",
]

"""shared.runtime — cross-cutting runtime substrate (Wave 1+3, v3).

Per ``docs/V3_BUILD_SEQUENCE.md`` Part 1.1 (resolved layout):

    shared/runtime/   NEW   — substrate moved from lib/ (vitals,
                              heartbeat, watchdog, notify, executor,
                              usage-parsers, file-lock, updater,
                              db-outbox, AND #34 workspace hygiene).

Wave 1 (Squad B) seeded this package with the workspace-hygiene library
(``hygiene.py``).

Wave 3 (Squad A) migrated the nine legacy ``lib/*.sh`` substrate
scripts here:

    vitals.sh         heartbeat.sh    watchdog.sh
    notify.sh         executor.sh     usage-parsers.sh
    file-lock.sh      updater.sh      db-outbox.sh

These are bash scripts, not Python — they are invoked via ``bash`` and
do not appear in this module's exported API. Python callers continue
to import only the workspace-hygiene helpers; shell callers should
source from ``$REPO/shared/runtime/<name>.sh``. Wave 6 retires the
``lib/`` directory entirely once remaining lib/ callers are rebuilt.
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

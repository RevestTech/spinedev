"""Repo-root pytest conftest.

Sole purpose: undo the ``shared/secrets/`` package shadowing of Python's
stdlib ``secrets`` module that pytest's rootdir discovery introduces.

Pytest walks up from each test file collecting directories until it
finds one without ``__init__.py``. ``shared/`` has no ``__init__.py``
(it's a namespace package), so pytest inserts ``shared/`` on
``sys.path``. That makes ``shared.secrets`` resolve as ``secrets`` and
breaks ``from secrets import token_hex`` (Starlette / FastAPI rely on
the stdlib ``secrets`` module).

Loading this fix at repo-root conftest level — pytest auto-discovers
and runs ALL conftests up the directory tree — guarantees every test
suite inherits the fix without each `shared/*/tests/conftest.py`
duplicating the block.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_SHARED_DIR = str(_Path(__file__).resolve().parent / "shared")

# Remove ``shared/`` from sys.path if pytest inserted it. We never need
# ``import secrets`` to resolve to ``shared/secrets/``; that package is
# only ever consumed via its fully-qualified name ``shared.secrets``.
while _SHARED_DIR in _sys.path:
    _sys.path.remove(_SHARED_DIR)

# Evict any already-imported ``secrets`` module that resolved to our
# package during early conftest collection so the next ``import secrets``
# re-resolves to stdlib.
_pre = _sys.modules.get("secrets")
if _pre is not None and getattr(_pre, "__file__", "").startswith(_SHARED_DIR):
    del _sys.modules["secrets"]

"""Runtime gating for Spine hooks / phases (V3 B7 borrow).

Borrowed contract source: ECC ``ECC_HOOK_PROFILE`` /
``ECC_DISABLED_HOOKS`` environment variables. See
``docs/ECC_BORROWS.md`` B7.

Why
---

Spine's smoke harness, hygiene gate, and MCP dispatcher pre-checks are
all-or-nothing today. Operators want to switch between fast local checks
and strict CI without editing scripts.

Two env vars control everything:

* ``SPINE_HOOK_PROFILE`` — ``minimal`` | ``standard`` | ``strict``
  (default ``standard``).
* ``SPINE_DISABLED_HOOKS`` — comma-separated list of hook ids that are
  always skipped (regardless of profile).

Each named hook declares a *minimum profile* at which it runs.
``is_hook_active(name)`` returns True iff the active profile is at or
above the hook's minimum AND the hook is not in the disabled list.

Profile levels (ordered, lowest first):

  1. ``minimal``  — bootstrap + bash core sanity only. Fast feedback.
  2. ``standard`` — default; current 99-PASS smoke contract.
  3. ``strict``   — adds extended LLM-bridge audits + KG drift checks.

A hook with minimum ``standard`` runs in ``standard`` AND ``strict``
but not ``minimal``. A hook with minimum ``minimal`` runs everywhere
(unless explicitly disabled).

The bash counterpart lives in ``tools/_hook_profile.sh`` — both surfaces
read the same env vars and follow the same precedence rules.
"""
from __future__ import annotations

import os
from typing import Literal

HookProfile = Literal["minimal", "standard", "strict"]

PROFILE_ENV = "SPINE_HOOK_PROFILE"
"""Env var that sets the active profile."""

DISABLED_ENV = "SPINE_DISABLED_HOOKS"
"""Env var that lists hooks to always skip (csv)."""

DEFAULT_PROFILE: HookProfile = "standard"
"""Profile used when ``SPINE_HOOK_PROFILE`` is unset or invalid."""


_PROFILE_LEVEL: dict[HookProfile, int] = {
    "minimal": 1,
    "standard": 2,
    "strict": 3,
}


def active_profile() -> HookProfile:
    """Read ``SPINE_HOOK_PROFILE`` and return the validated profile.

    Returns :data:`DEFAULT_PROFILE` for unset, empty, or unrecognised
    values. Values are case-insensitive.
    """
    raw = os.environ.get(PROFILE_ENV, "").strip().lower()
    if raw in _PROFILE_LEVEL:
        return raw  # type: ignore[return-value]
    return DEFAULT_PROFILE


def disabled_hooks() -> frozenset[str]:
    """Parse ``SPINE_DISABLED_HOOKS`` into a normalised set."""
    raw = os.environ.get(DISABLED_ENV, "")
    return frozenset(
        token.strip()
        for token in raw.split(",")
        if token.strip()
    )


def is_hook_active(
    hook_name: str,
    *,
    minimum_profile: HookProfile = "standard",
) -> bool:
    """Return True iff ``hook_name`` should run under the active profile.

    A hook is active when BOTH:

      * ``active_profile()`` level is ≥ ``minimum_profile`` level.
      * ``hook_name`` is not present in :func:`disabled_hooks`.

    Empty or whitespace-only ``hook_name`` always returns False.
    """
    if not hook_name or not hook_name.strip():
        return False
    if hook_name in disabled_hooks():
        return False
    if minimum_profile not in _PROFILE_LEVEL:
        return False
    return _PROFILE_LEVEL[active_profile()] >= _PROFILE_LEVEL[minimum_profile]


def explain(hook_name: str, *, minimum_profile: HookProfile = "standard") -> str:
    """Return a one-line explanation suitable for log surfaces.

    Useful when a script wants to print *why* a check was skipped.
    """
    if not hook_name or not hook_name.strip():
        return "hook_name empty"
    if hook_name in disabled_hooks():
        return f"hook {hook_name!r} disabled via {DISABLED_ENV}"
    profile = active_profile()
    if _PROFILE_LEVEL[profile] < _PROFILE_LEVEL[minimum_profile]:
        return (
            f"hook {hook_name!r} skipped — minimum profile "
            f"{minimum_profile!r}, active {profile!r}"
        )
    return f"hook {hook_name!r} active (profile={profile!r})"


__all__ = [
    "DEFAULT_PROFILE",
    "DISABLED_ENV",
    "HookProfile",
    "PROFILE_ENV",
    "active_profile",
    "disabled_hooks",
    "explain",
    "is_hook_active",
]

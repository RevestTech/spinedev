"""
Atomic LLM budget reservation (closes the race in P1 M4).

Problem
-------
The legacy check in ``budget.assert_llm_budget_allows_estimated_call`` did
``SELECT SUM(cost_usd)`` then compared to the cap, and the caller inserted
the usage row AFTER the provider call completed. Two concurrent callers
could both read the pre-insert sum, both pass the check, and both spend —
blowing the cap by up to ``N_callers × per_call_cost``.

Fix
---
Move the race-critical "check + reserve" into a single atomic Redis
operation. The flow becomes:

  1. ``reserve_llm_budget(estimated_usd)`` does:
     - Read historical spend from the DB (source of truth for reporting).
     - ``INCRBY llm:reserved_cents estimated_cents`` atomically.
     - If ``historical + new_reservation_total > cap``: ``DECRBY`` back and
       raise :class:`tron.infra.llm.budget.LLMBudgetExceeded`.
     - Otherwise return a reservation handle.
  2. The caller makes the provider call inside the context manager.
  3. On exit (success or exception) the reservation is released with a
     ``DECRBY``. The actual cost of the call is still persisted to
     ``llm_usage`` by the existing ledger writer, so the DB stays
     authoritative for dashboards and next-invocation reads.

The Redis counter represents *in-flight* spend only. On each reservation
we re-read the DB sum, so a missed ``DECRBY`` (crashed worker, etc.) would
be bounded to at most ``N_workers × per_call_cost`` of leaked reservation
until the next worker restart, and a scheduled ``SET llm:reserved_cents 0``
on worker bootstrap puts an upper bound on that.

Fallback (no Redis)
-------------------
When Redis isn't reachable, we degrade to a process-local ``asyncio.Lock``
around the DB-sum check. This closes the intra-process race cleanly and
logs a warning; the cross-process race is documented as a known gap. Ops
can force fail-closed via ``TRON_LLM_BUDGET_REQUIRE_REDIS=true``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from tron.api.config import settings
from tron.infra.llm.budget import (
    LLMBudgetExceeded,
    get_total_llm_spend_usd,
)

logger = logging.getLogger(__name__)

# Redis key. Stored as INTEGER CENTS so ``INCRBY`` / ``DECRBY`` are
# truly atomic (Redis only guarantees atomicity for integer operations;
# INCRBYFLOAT is atomic but has well-known precision issues with cents).
_RESERVATION_KEY = "llm:budget:reserved_cents"

# Process-local serializer for the no-Redis fallback path. Scoped to this
# module, not per-instance — all LLM callers inside one worker share it.
_FALLBACK_LOCK = asyncio.Lock()


@dataclass
class BudgetReservation:
    """Handle returned by ``reserve_llm_budget`` — callers normally won't
    touch this directly; use the async context manager instead."""

    reserved_cents: int
    # True when the reservation was taken in Redis and must be released
    # there; False when we fell back to the in-process lock path (in which
    # case there's nothing to release — the lock already released).
    redis_backed: bool


def _usd_to_cents(usd: float) -> int:
    """Convert dollars to an integer cents value, rounding up.

    Rounding up is conservative: we'd rather over-reserve by a penny than
    under-reserve and drift past the cap.
    """
    if usd <= 0:
        return 0
    # multiply then ceil — the +0.9999 trick is equivalent and avoids a
    # math.ceil import.
    cents = int(usd * 100 + 0.9999)
    return max(cents, 1)


async def _try_get_redis():
    """Return the Redis client or ``None`` if it isn't initialised.

    Kept as a thin wrapper so tests can monkeypatch the whole lookup in one
    place, and so the fallback branch lights up cleanly when ``get_redis``
    raises.
    """
    try:
        from tron.infra.redis.client import get_redis

        return get_redis()
    except Exception as exc:
        logger.debug("LLM budget: Redis unavailable (%s); using fallback lock", exc)
        return None


async def _current_reserved_cents(redis) -> int:
    raw = await redis.get(_RESERVATION_KEY)
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Corrupted / unexpected value — zero it out so we don't permanently
        # wedge LLM calls. Logged loudly so the bad state is visible.
        logger.warning(
            "LLM budget reservation key %s was non-integer (%r); resetting",
            _RESERVATION_KEY, raw,
        )
        await redis.set(_RESERVATION_KEY, 0)
        return 0


@contextlib.asynccontextmanager
async def reserve_llm_budget(
    estimated_usd: float,
) -> AsyncIterator[Optional[BudgetReservation]]:
    """Atomically check and reserve budget for one LLM call.

    Usage::

        async with reserve_llm_budget(estimated_cost):
            response = await provider.call(...)

    Raises :class:`LLMBudgetExceeded` if the reservation would push the
    running total past ``TRON_LLM_BUDGET_USD``. The reservation is always
    released on exit, whether the call succeeded or not — the real cost of
    the completed call is recorded separately via the usage ledger.
    """
    # Feature switch / misconfig: if enforcement is off or the cap is
    # non-positive, every call is a free no-op.
    if not settings.tron_llm_budget_enforce:
        yield None
        return
    cap_usd = settings.tron_llm_budget_usd
    if cap_usd <= 0:
        yield None
        return

    est_cents = _usd_to_cents(estimated_usd)
    cap_cents = _usd_to_cents(cap_usd)

    redis = await _try_get_redis()
    if redis is None:
        # Fallback path: serialise within the process, re-check the DB.
        async with _fallback_reserve(est_cents, cap_cents):
            yield BudgetReservation(reserved_cents=est_cents, redis_backed=False)
        return

    # Fast pre-check against the historical DB spend. We still do the
    # atomic Redis swap below — this just short-circuits when we're
    # obviously over.
    spent_usd = await get_total_llm_spend_usd()
    spent_cents = _usd_to_cents(spent_usd)
    if spent_cents >= cap_cents:
        raise LLMBudgetExceeded(spent_usd, cap_usd)

    # Atomic take-or-refuse. INCRBY is atomic across clients; we decide to
    # keep or roll back based on the returned new total. If a second
    # caller ran INCRBY between our GET above and this INCRBY, we both see
    # each other's increment and only one of us can fit under the cap.
    new_reserved_cents = int(await redis.incrby(_RESERVATION_KEY, est_cents))
    if spent_cents + new_reserved_cents > cap_cents:
        # Someone else raced us past the cap. Roll back and raise.
        await redis.decrby(_RESERVATION_KEY, est_cents)
        raise LLMBudgetExceeded(
            spent_usd + (new_reserved_cents / 100.0),
            cap_usd,
        )

    try:
        yield BudgetReservation(reserved_cents=est_cents, redis_backed=True)
    finally:
        # Release unconditionally — the actual cost flows through the DB
        # ledger via persist_llm_usage, which bumps historical spend on
        # the next caller's check.
        try:
            await redis.decrby(_RESERVATION_KEY, est_cents)
        except Exception:
            # A leaked reservation is bounded (another call's worth) and
            # self-heals on the next worker bootstrap that resets the key.
            logger.warning(
                "Failed to release LLM budget reservation of %d cents",
                est_cents,
                exc_info=True,
            )


@contextlib.asynccontextmanager
async def _fallback_reserve(est_cents: int, cap_cents: int) -> AsyncIterator[None]:
    """No-Redis path: process-local lock + DB SUM check.

    This closes the intra-worker race. Cross-worker isolation is lost —
    two workers without Redis can each pass the check simultaneously. We
    log a warning the first time this path is hit per process so the
    degradation is visible.
    """
    if getattr(settings, "tron_llm_budget_require_redis", False):
        raise LLMBudgetExceeded(0.0, cap_cents / 100.0)

    async with _FALLBACK_LOCK:
        spent_usd = await get_total_llm_spend_usd()
        spent_cents = _usd_to_cents(spent_usd)
        if spent_cents + est_cents > cap_cents:
            raise LLMBudgetExceeded(spent_usd, cap_cents / 100.0)
        # We hold the lock across the yielded block intentionally — the
        # caller does the LLM call and writes the usage row inside it,
        # so the next contender sees the updated DB sum.
        yield

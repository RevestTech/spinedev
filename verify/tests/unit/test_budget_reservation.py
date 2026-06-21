"""
Regression tests for the LLM budget reservation (P1 M4).

The old check-then-spend flow let two concurrent callers both pass the cap
check and both spend. These tests fire many concurrent reservations
against a tight cap and assert that only the budget's worth succeed — the
rest raise :class:`LLMBudgetExceeded`.

We cover both the Redis-backed path and the process-local fallback.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tron.infra.llm.budget import LLMBudgetExceeded
from tron.infra.llm import budget_reservation as bres_mod
from tron.infra.llm.budget_reservation import (
    _usd_to_cents,
    reserve_llm_budget,
)


# ── _usd_to_cents rounds up ──────────────────────────────────────────────


class TestUsdToCents:
    def test_zero(self):
        assert _usd_to_cents(0) == 0

    def test_negative_clamps_to_zero(self):
        assert _usd_to_cents(-1) == 0

    def test_whole_dollars(self):
        assert _usd_to_cents(5.0) == 500

    def test_fractional_rounds_up(self):
        # 0.0049 cents is still "above 0" → at least 1 cent reserved.
        assert _usd_to_cents(0.00001) == 1

    def test_half_cent_rounds_up(self):
        # 12.345 → 1234.5 → 1235 (ceil)
        assert _usd_to_cents(12.345) == 1235


# ── Shared fake Redis for the concurrency tests ───────────────────────────


class _FakeRedis:
    """In-memory stand-in with async INCRBY/DECRBY/GET/SET.

    Backed by an asyncio.Lock so ``INCRBY`` is atomic across cooperating
    coroutines exactly like the real Redis — without that, the test would
    just validate asyncio.Lock rather than the reservation logic.
    """

    def __init__(self):
        self._store: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            v = self._store.get(key)
            return str(v) if v is not None else None

    async def set(self, key: str, value):
        async with self._lock:
            self._store[key] = int(value)

    async def incrby(self, key: str, amount: int) -> int:
        async with self._lock:
            self._store[key] = self._store.get(key, 0) + int(amount)
            return self._store[key]

    async def decrby(self, key: str, amount: int) -> int:
        async with self._lock:
            self._store[key] = self._store.get(key, 0) - int(amount)
            return self._store[key]


def _patch_settings(monkeypatch, cap_usd: float, *, enforce: bool = True, require_redis: bool = False):
    stand_in = SimpleNamespace(
        tron_llm_budget_enforce=enforce,
        tron_llm_budget_usd=cap_usd,
        tron_llm_soft_cap_pct=0.85,
        tron_llm_budget_require_redis=require_redis,
    )
    monkeypatch.setattr(bres_mod, "settings", stand_in)


@pytest.fixture
def fake_redis(monkeypatch):
    redis = _FakeRedis()

    async def _stub():
        return redis

    monkeypatch.setattr(bres_mod, "_try_get_redis", _stub)
    return redis


@pytest.fixture
def zero_db_spend(monkeypatch):
    """Pretend the DB ledger is empty. Tests opt out with their own stub."""
    monkeypatch.setattr(
        bres_mod, "get_total_llm_spend_usd", AsyncMock(return_value=0.0)
    )


# ── Single-caller paths ───────────────────────────────────────────────────


class TestSingleCaller:

    @pytest.mark.asyncio
    async def test_enforce_off_is_noop(self, monkeypatch, fake_redis):
        _patch_settings(monkeypatch, cap_usd=10.0, enforce=False)
        async with reserve_llm_budget(1000.0) as r:
            # Giant estimate, enforcement off → sails through.
            assert r is None

    @pytest.mark.asyncio
    async def test_zero_cap_is_noop(self, monkeypatch, fake_redis):
        _patch_settings(monkeypatch, cap_usd=0)
        async with reserve_llm_budget(5.0) as r:
            assert r is None

    @pytest.mark.asyncio
    async def test_happy_path_reserves_and_releases(self, monkeypatch, fake_redis, zero_db_spend):
        _patch_settings(monkeypatch, cap_usd=10.0)

        async with reserve_llm_budget(3.0) as r:
            assert r is not None
            assert r.redis_backed is True
            # During the block, the reservation is reflected in Redis.
            assert int(await fake_redis.get("llm:budget:reserved_cents")) == 300

        # After exit, reservation is released.
        assert int(await fake_redis.get("llm:budget:reserved_cents")) == 0

    @pytest.mark.asyncio
    async def test_release_runs_on_exception(self, monkeypatch, fake_redis, zero_db_spend):
        _patch_settings(monkeypatch, cap_usd=10.0)

        with pytest.raises(RuntimeError, match="boom"):
            async with reserve_llm_budget(2.0):
                raise RuntimeError("boom")

        assert int(await fake_redis.get("llm:budget:reserved_cents")) == 0

    @pytest.mark.asyncio
    async def test_historical_spend_already_over_cap_raises(self, monkeypatch, fake_redis):
        _patch_settings(monkeypatch, cap_usd=10.0)
        monkeypatch.setattr(
            bres_mod, "get_total_llm_spend_usd", AsyncMock(return_value=10.50)
        )

        with pytest.raises(LLMBudgetExceeded):
            async with reserve_llm_budget(0.01):
                pass

    @pytest.mark.asyncio
    async def test_single_reservation_that_would_exceed_rolls_back(
        self, monkeypatch, fake_redis
    ):
        _patch_settings(monkeypatch, cap_usd=10.0)
        monkeypatch.setattr(
            bres_mod, "get_total_llm_spend_usd", AsyncMock(return_value=9.50)
        )

        # Estimate $1.00 → would reach $10.50 → refused.
        with pytest.raises(LLMBudgetExceeded):
            async with reserve_llm_budget(1.00):
                pass

        # Roll-back path: reserved counter returns to zero.
        assert int(await fake_redis.get("llm:budget:reserved_cents")) == 0


# ── Concurrency: the actual race fix ──────────────────────────────────────


@pytest.mark.asyncio
async def test_many_concurrent_reservations_respect_the_cap(
    monkeypatch, fake_redis, zero_db_spend
):
    """THE test. 10 concurrent callers, $10 cap, $3 each. Only 3 succeed.

    The pre-fix code would let all 10 pass (each reads SUM=0 and thinks the
    cap is safe). Under the fix, INCRBY serialises check-and-reserve — four
    and later callers blow past the cap on their atomic increment and get
    rolled back.
    """
    _patch_settings(monkeypatch, cap_usd=10.0)

    successes = 0
    failures = 0

    async def one_call():
        nonlocal successes, failures
        try:
            async with reserve_llm_budget(3.00):
                # Hold the reservation briefly so all callers overlap.
                await asyncio.sleep(0.01)
            successes += 1
        except LLMBudgetExceeded:
            failures += 1

    await asyncio.gather(*[one_call() for _ in range(10)])

    # 10 attempts × $3 = $30 would be 3× the cap. At most floor(10/3)=3 fit.
    assert successes == 3, (
        f"expected exactly 3 concurrent reservations under a $10 cap at "
        f"$3 each, got {successes} successes / {failures} failures — the "
        f"race is back."
    )
    assert failures == 7

    # All reservations released — counter is zero.
    assert int(await fake_redis.get("llm:budget:reserved_cents")) == 0


@pytest.mark.asyncio
async def test_exact_cap_allows_exact_fill(monkeypatch, fake_redis, zero_db_spend):
    """Reservations that sum exactly to the cap must all succeed."""
    _patch_settings(monkeypatch, cap_usd=10.0)

    successes = 0

    async def one_call():
        nonlocal successes
        try:
            async with reserve_llm_budget(2.00):
                await asyncio.sleep(0.005)
            successes += 1
        except LLMBudgetExceeded:
            pass

    await asyncio.gather(*[one_call() for _ in range(5)])
    assert successes == 5  # 5 × $2 == $10 cap exactly


# ── Fallback (no Redis) path ──────────────────────────────────────────────


class TestFallbackPath:

    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        async def _stub():
            return None

        monkeypatch.setattr(bres_mod, "_try_get_redis", _stub)

    @pytest.mark.asyncio
    async def test_fallback_succeeds_under_cap(self, monkeypatch, zero_db_spend):
        _patch_settings(monkeypatch, cap_usd=10.0, require_redis=False)

        async with reserve_llm_budget(3.0) as r:
            assert r is not None
            assert r.redis_backed is False

    @pytest.mark.asyncio
    async def test_fallback_refuses_over_cap(self, monkeypatch):
        _patch_settings(monkeypatch, cap_usd=10.0, require_redis=False)
        monkeypatch.setattr(
            bres_mod, "get_total_llm_spend_usd", AsyncMock(return_value=9.50)
        )

        with pytest.raises(LLMBudgetExceeded):
            async with reserve_llm_budget(1.00):
                pass

    @pytest.mark.asyncio
    async def test_require_redis_fails_closed(self, monkeypatch, zero_db_spend):
        # Ops flag: when Redis is the only path and it's down, refuse calls.
        _patch_settings(monkeypatch, cap_usd=10.0, require_redis=True)

        with pytest.raises(LLMBudgetExceeded):
            async with reserve_llm_budget(1.00):
                pass

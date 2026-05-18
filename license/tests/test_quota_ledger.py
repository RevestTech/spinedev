"""Tests for ``license.quota_ledger``."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from license.quota_ledger import (
    GENESIS_ANCHOR_HEX,
    _anchor,
    _default_period,
    record_usage,
    verify_chain,
)


def _now() -> datetime:
    return datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def test_default_period_is_calendar_month() -> None:
    start, end = _default_period(_now())
    assert start == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_default_period_handles_december_rollover() -> None:
    start, end = _default_period(datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_anchor_is_deterministic() -> None:
    a = _anchor(prev_anchor_hex="0" * 64, flag_name="x",
                period_start=_now(), period_end=_now(), used_value=5)
    b = _anchor(prev_anchor_hex="0" * 64, flag_name="x",
                period_start=_now(), period_end=_now(), used_value=5)
    assert a == b
    assert len(a) == 32


def test_record_usage_first_row_chains_to_genesis(mock_pool) -> None:
    # 1st fetchrow (FOR UPDATE existing) -> None ⇒ new row path
    mock_pool.script_row(None)
    # 2nd fetchrow (prior-period anchor) -> None ⇒ genesis bootstrap
    mock_pool.script_row(None)

    async def _run():
        return await record_usage(
            pool=mock_pool, flag_name="role_devops", increment=5, now=_now(),
        )

    result = asyncio.run(_run())
    assert result["used_value"] == 5
    assert result["created_row"] is True
    # The anchor should be sha256 of (genesis || flag || start || end || 5).
    period_start, period_end = _default_period(_now())
    expected = _anchor(
        prev_anchor_hex=GENESIS_ANCHOR_HEX,
        flag_name="role_devops", period_start=period_start,
        period_end=period_end, used_value=5,
    ).hex()
    assert result["ledger_anchor_hex"] == expected


def test_record_usage_increments_existing(mock_pool) -> None:
    period_start, period_end = _default_period(_now())
    prev_anchor = _anchor(
        prev_anchor_hex=GENESIS_ANCHOR_HEX,
        flag_name="role_devops", period_start=period_start,
        period_end=period_end, used_value=10,
    )
    # 1st fetchrow returns the existing row.
    mock_pool.script_row({"used_value": 10, "ledger_anchor": prev_anchor})

    async def _run():
        return await record_usage(
            pool=mock_pool, flag_name="role_devops", increment=3, now=_now(),
        )

    result = asyncio.run(_run())
    assert result["used_value"] == 13
    assert result["created_row"] is False
    expected = _anchor(
        prev_anchor_hex=prev_anchor.hex(),
        flag_name="role_devops", period_start=period_start,
        period_end=period_end, used_value=13,
    ).hex()
    assert result["ledger_anchor_hex"] == expected


def test_record_usage_negative_increment_raises(mock_pool) -> None:
    with pytest.raises(ValueError):
        asyncio.run(record_usage(
            pool=mock_pool, flag_name="x", increment=-1, now=_now(),
        ))


def test_verify_chain_detects_tampered_row(mock_pool) -> None:
    period_start, period_end = _default_period(_now())
    # Correct anchor for row 1
    good_anchor_1 = _anchor(
        prev_anchor_hex=GENESIS_ANCHOR_HEX,
        flag_name="role_devops", period_start=period_start,
        period_end=period_end, used_value=10,
    )
    # Tampered anchor for row 1 (wrong bytes)
    bad_anchor = bytes(32)  # all zeros — almost certainly wrong
    mock_pool.script_rows([
        {"period_start": period_start, "period_end": period_end,
         "used_value": 10, "ledger_anchor": bad_anchor},
    ])
    result = asyncio.run(verify_chain(pool=mock_pool, flag_name="role_devops"))
    assert result["ok"] is False
    assert result["rows_checked"] == 1
    assert result["first_bad_row"]["flag_name"] == "role_devops"


def test_verify_chain_passes_on_clean_chain(mock_pool) -> None:
    period_start, period_end = _default_period(_now())
    anchor_1 = _anchor(
        prev_anchor_hex=GENESIS_ANCHOR_HEX,
        flag_name="role_devops", period_start=period_start,
        period_end=period_end, used_value=10,
    )
    mock_pool.script_rows([
        {"period_start": period_start, "period_end": period_end,
         "used_value": 10, "ledger_anchor": anchor_1},
    ])
    result = asyncio.run(verify_chain(pool=mock_pool, flag_name="role_devops"))
    assert result["ok"] is True
    assert result["first_bad_row"] is None

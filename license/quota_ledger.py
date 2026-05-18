"""Hash-chained quota usage writer.

Writes per-feature usage increments to ``spine_license.quota_usage``
(V22 schema) and chains each row's ``ledger_anchor`` to the SHA-256 of
the prior row so tampering with historical usage is detectable.

The chain anchor is computed as::

    anchor_i = sha256(
        prev_anchor_hex || "\\n" ||
        flag_name        || "\\n" ||
        period_start_iso || "\\n" ||
        period_end_iso   || "\\n" ||
        used_value_after_increment
    )

Bootstrap: the very first row in the table has ``prev_anchor_hex = "0" * 64``.
The chain is per-(flag_name, period_start) — concurrent writers to
different flags don't have to coordinate; only consecutive writes to the
SAME (flag, period) need to read+update under a SERIALIZABLE-isolation
``UPDATE`` (single SQL statement; Postgres serialises the row lock).

The ledger is *append-by-merge*: each call to :func:`record_usage` does
an UPSERT — if a row for the (flag, period_start, period_end) tuple
already exists, the increment is added; otherwise a new row is created.
Either way we recompute the anchor.

Why hash-chain quotas? Per #24 the audit chain is SOC2 evidence. Per #23
quota usage is the data needed to set rational pricing. Tampering with
quota data (either to underreport usage and underpay, or to overreport
and inflate vendor metrics) is therefore a compliance event — making the
ledger tamper-evident is cheap insurance.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("spine.license.quota_ledger")

#: Bootstrap anchor — what the first row's "prev" hash is.
GENESIS_ANCHOR_HEX: str = "0" * 64


def _anchor(
    *,
    prev_anchor_hex: str,
    flag_name: str,
    period_start: datetime,
    period_end: datetime,
    used_value: int,
) -> bytes:
    """Compute the SHA-256 anchor binding the new row to the chain.

    Returns the raw 32-byte digest (the column is ``bytea``).
    """
    payload = (
        f"{prev_anchor_hex}\n"
        f"{flag_name}\n"
        f"{period_start.astimezone(timezone.utc).isoformat()}\n"
        f"{period_end.astimezone(timezone.utc).isoformat()}\n"
        f"{used_value}"
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _default_period(now: datetime) -> tuple[datetime, datetime]:
    """Return the calendar-month period containing ``now`` (UTC).

    ``period_start`` = first day of the UTC month at 00:00:00.
    ``period_end``   = first day of the next UTC month at 00:00:00.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0,
                        tzinfo=timezone.utc)
    # Next month: roll over via day-overflow trick.
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def record_usage(
    *,
    pool: Any,
    flag_name: str,
    increment: int,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Append ``increment`` units of usage for ``flag_name`` to the ledger.

    Args:
        pool: asyncpg pool (or duck-typed equivalent — tests use a mock).
        flag_name: Feature identifier; must match ``KNOWN_FEATURE_FLAGS``.
        increment: Units to add (must be >= 0; the V22 CHECK enforces
            ``used_value >= 0`` so the post-increment value can't go
            negative either).
        period_start / period_end: Override the billing window
            (default = the current UTC calendar month).
        now: Wall-clock override for tests.

    Returns:
        ``{"flag_name", "period_start", "period_end", "used_value",
        "ledger_anchor_hex", "created_row"}``.

    Raises:
        ValueError: increment < 0 OR period_end <= period_start.
    """
    if increment < 0:
        raise ValueError(f"increment must be >= 0, got {increment}")
    when = now or datetime.now(timezone.utc)
    if period_start is None or period_end is None:
        period_start, period_end = _default_period(when)
    if period_end <= period_start:
        raise ValueError("period_end must be strictly after period_start")

    # Step 1: get the *previous* anchor for this (flag, period).
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT used_value, ledger_anchor "
            "FROM spine_license.quota_usage "
            "WHERE flag_name = $1 AND period_start = $2 AND period_end = $3 "
            "FOR UPDATE;",
            flag_name, period_start, period_end,
        )
        if existing is not None:
            old_used = int(existing["used_value"])
            prev_anchor_bytes = existing["ledger_anchor"]
            prev_anchor_hex = (
                prev_anchor_bytes.hex() if prev_anchor_bytes else GENESIS_ANCHOR_HEX
            )
            new_used = old_used + increment
            new_anchor = _anchor(
                prev_anchor_hex=prev_anchor_hex,
                flag_name=flag_name, period_start=period_start,
                period_end=period_end, used_value=new_used,
            )
            await conn.execute(
                "UPDATE spine_license.quota_usage "
                "SET used_value = $1, ledger_anchor = $2 "
                "WHERE flag_name = $3 AND period_start = $4 AND period_end = $5;",
                new_used, new_anchor, flag_name, period_start, period_end,
            )
            created = False
        else:
            # New row — chain to the most recent prior period for this flag,
            # or to genesis if this is the very first row.
            prev_row = await conn.fetchrow(
                "SELECT ledger_anchor FROM spine_license.quota_usage "
                "WHERE flag_name = $1 AND period_end <= $2 "
                "ORDER BY period_end DESC LIMIT 1;",
                flag_name, period_start,
            )
            if prev_row is not None and prev_row["ledger_anchor"]:
                prev_anchor_hex = prev_row["ledger_anchor"].hex()
            else:
                prev_anchor_hex = GENESIS_ANCHOR_HEX
            new_used = increment
            new_anchor = _anchor(
                prev_anchor_hex=prev_anchor_hex,
                flag_name=flag_name, period_start=period_start,
                period_end=period_end, used_value=new_used,
            )
            await conn.execute(
                "INSERT INTO spine_license.quota_usage "
                "(flag_name, period_start, period_end, used_value, ledger_anchor) "
                "VALUES ($1, $2, $3, $4, $5);",
                flag_name, period_start, period_end, new_used, new_anchor,
            )
            created = True
    logger.info(
        "quota_usage_recorded",
        extra={
            "flag": flag_name, "increment": increment,
            "used_value": new_used, "created_row": created,
        },
    )
    # Drop the feature_flags cache so the next quota_remaining() reads fresh.
    try:
        from license.feature_flags import invalidate_cache as _inv
        _inv()
    except Exception:  # pragma: no cover — cache invalidation is best-effort
        pass
    return {
        "flag_name": flag_name,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "used_value": new_used,
        "ledger_anchor_hex": new_anchor.hex(),
        "created_row": created,
    }


async def verify_chain(
    *,
    pool: Any,
    flag_name: str,
) -> dict[str, Any]:
    """Replay the chain for ``flag_name`` and return the verification report.

    Returns ``{"ok": bool, "rows_checked": int, "first_bad_row": dict | None}``.
    Used by MCP tool ``license_verify_bundle`` to surface tampering.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT period_start, period_end, used_value, ledger_anchor "
            "FROM spine_license.quota_usage "
            "WHERE flag_name = $1 ORDER BY period_start ASC;",
            flag_name,
        )
    prev_anchor_hex = GENESIS_ANCHOR_HEX
    for idx, row in enumerate(rows):
        expected = _anchor(
            prev_anchor_hex=prev_anchor_hex,
            flag_name=flag_name,
            period_start=row["period_start"],
            period_end=row["period_end"],
            used_value=int(row["used_value"]),
        )
        actual = row["ledger_anchor"]
        if actual is None or bytes(actual) != expected:
            return {
                "ok": False, "rows_checked": idx + 1,
                "first_bad_row": {
                    "flag_name": flag_name,
                    "period_start": row["period_start"].isoformat(),
                    "expected_anchor_hex": expected.hex(),
                    "actual_anchor_hex": (actual.hex() if actual else None),
                },
            }
        prev_anchor_hex = expected.hex()
    return {"ok": True, "rows_checked": len(rows), "first_bad_row": None}


__all__ = [
    "GENESIS_ANCHOR_HEX",
    "record_usage",
    "verify_chain",
]

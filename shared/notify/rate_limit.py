"""Persistent rate-limit ledger for shared.notify.

Per V3 design decision #6 ("communication preferences — fully flexible
per-user, per-decision-class, per-medium") the in-memory rate-limit
counter in ``Notifier._rate_log`` is insufficient: federation needs
rate-limit awareness across multiple Hub processes (and surviving
restarts) so identical events don't fan out twice.

Storage choice (per task spec): reuse the pre-existing
``spine_license.quota_usage`` table (V22). No new schema, no V33
migration. Each rate-limit key is encoded as a ``flag_name`` of the
form ``notify.<channel>.<event_type>`` (e.g. ``notify.slack.verify_failed``)
and the rate-limit window becomes the row's
``[period_start, period_end)``.

API (sync, mockable for unit tests):

    check(channel, event_type, key, window_seconds) -> bool
        # True iff this (channel, event_type, key) was already notified
        # within the current window — caller should suppress.

    mark(channel, event_type, key, window_seconds) -> None
        # Records a successful notification within the current window
        # so subsequent ``check`` calls within the same window return
        # True.

Both functions are best-effort: if the database is unreachable, the
helpers log + return permissive defaults (``check`` → False, ``mark``
→ no-op) so notification never blocks on the ledger. Federation
correctness degrades to per-process behavior in that case — exactly
the legacy posture.

Implementation note: DB I/O uses the same psql-bound pattern as
``plan/pipeline/project_lock.py`` (parameter-binding via ``\\set``)
so untrusted ``key`` values from per-user prefs cannot be SQL-injected.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

_log = logging.getLogger("spine.notify.rate_limit")


# ──────────────────────────────────────────────────────────────────────
# Helpers — psql parameter binding (mirrors project_lock._psql_bound)
# ──────────────────────────────────────────────────────────────────────


def _psql_bound(sql_with_binds: str, binds: dict[str, str]) -> str:
    """Run psql with safely-bound parameters. Returns stripped stdout.

    See ``plan/pipeline/project_lock.py:_psql_bound`` for the security
    rationale. Mirrored here to avoid a cross-package import from
    ``shared`` -> ``plan``.
    """
    url = os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set — notify.rate_limit needs DB")
    lines: list[str] = [r"\set ON_ERROR_STOP 1"]
    for name, value in binds.items():
        if not name.replace("_", "").isalnum():
            raise ValueError(f"unsafe bind name: {name!r}")
        safe = value.replace("'", "''")
        lines.append(f"\\set {name} '{safe}'")
    lines.append(sql_with_binds)
    script = "\n".join(lines) + "\n"
    proc = subprocess.run(
        ["psql", url, "-At", "-X", "-q"],
        input=script,
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


# ──────────────────────────────────────────────────────────────────────
# Key + period helpers
# ──────────────────────────────────────────────────────────────────────


def _flag_name(channel: str, event_type: str) -> str:
    """Compose the ``spine_license.quota_usage.flag_name`` for this key.

    Format: ``notify.<channel>.<event_type>``. ``channel`` and ``event_type``
    are constrained at the caller (Pydantic Literal in
    ``shared.notify.notifier``), so the hash-based escape is unnecessary;
    we still validate shape defensively.
    """
    if not channel or not event_type:
        raise ValueError("channel and event_type must be non-empty")
    return f"notify.{channel}.{event_type}"


def _period_for(now: datetime, window_seconds: int) -> tuple[datetime, datetime]:
    """Bucket ``now`` into a discrete window of ``window_seconds`` length.

    Buckets align to epoch — same input always yields the same bucket
    across processes / hosts (the federation correctness property).
    """
    epoch = int(now.timestamp())
    bucket = epoch - (epoch % max(int(window_seconds), 1))
    start = datetime.fromtimestamp(bucket, tz=timezone.utc)
    end = start + timedelta(seconds=int(window_seconds))
    return start, end


def _recipient_hash(key: str) -> str:
    """Stable short hash for the (channel, event_type) tuple's
    per-recipient discriminator. The recipient string may contain
    arbitrary user input (email addresses, channel ids) so we hash
    it to keep the SQL bind value bounded and free of secrets."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def check(channel: str, event_type: str, key: str, window_seconds: int,
          *, now: datetime | None = None) -> bool:
    """Has (channel, event_type, key) already been notified in this window?

    Returns True if a quota_usage row exists for the matching flag_name
    + period AND ledger_anchor matches the recipient hash. False on
    miss OR on any DB failure (fail-open to preserve notification
    delivery).
    """
    flag = _flag_name(channel, event_type)
    period_start, period_end = _period_for(now or datetime.now(timezone.utc),
                                           window_seconds)
    recipient = _recipient_hash(key)
    try:
        rows = _psql_bound(
            "SELECT 1 FROM spine_license.quota_usage "
            "WHERE flag_name = :'flag' "
            "AND period_start = :'pstart'::timestamptz "
            "AND period_end = :'pend'::timestamptz "
            "AND encode(ledger_anchor, 'hex') = :'rcp' "
            "LIMIT 1;",
            {"flag": flag,
             "pstart": period_start.isoformat(),
             "pend": period_end.isoformat(),
             "rcp": recipient},
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("rate_limit.check failed (%s); allowing send", exc)
        return False
    return bool(rows.strip())


def mark(channel: str, event_type: str, key: str, window_seconds: int,
         *, now: datetime | None = None) -> None:
    """Record that (channel, event_type, key) was notified in this window.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` semantics indirectly by
    re-issuing as an upsert. The ``ledger_anchor`` column stores the
    short recipient hash so the row uniquely identifies the (flag,
    period, recipient) triple.
    """
    flag = _flag_name(channel, event_type)
    period_start, period_end = _period_for(now or datetime.now(timezone.utc),
                                           window_seconds)
    recipient = _recipient_hash(key)
    try:
        _psql_bound(
            "INSERT INTO spine_license.quota_usage "
            "(flag_name, period_start, period_end, used_value, ledger_anchor) "
            "VALUES (:'flag', :'pstart'::timestamptz, :'pend'::timestamptz, "
            "1, decode(:'rcp', 'hex')) "
            "ON CONFLICT DO NOTHING;",
            {"flag": flag,
             "pstart": period_start.isoformat(),
             "pend": period_end.isoformat(),
             "rcp": recipient},
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("rate_limit.mark failed (%s); continuing", exc)


__all__ = ["check", "mark"]

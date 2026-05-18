"""
shared.secrets.cli
==================

Command-line wrapper around the async `shared.secrets` public surface so
bash scripts can read/write vault-backed secrets without embedding Python.

Per design decision #9, every Spine code path (including bash) must route
secret reads through this package. This CLI is the bash on-ramp.

Usage (callable as `python3 -m shared.secrets.cli ...`):

    python3 -m shared.secrets.cli get <path>
    python3 -m shared.secrets.cli put <path> <value>       # value from stdin if "-"
    python3 -m shared.secrets.cli delete <path>
    python3 -m shared.secrets.cli list [<prefix>]
    python3 -m shared.secrets.cli adapter                   # print configured adapter name

The CLI requires the default adapter to be configured via the Day-0 vault
wizard. If no adapter is configured, exits non-zero with a clear message.

Exit codes:
    0   success
    1   secret not found
    2   access denied / unauthorized
    3   backend error (network, vault sealed, etc.)
    4   misuse (bad args)
    5   no adapter configured

`get` prints the secret value to stdout WITHOUT a trailing newline so
bash callers can use `VALUE=$(python3 -m shared.secrets.cli get path)`
without manual stripping. All errors and diagnostics go to stderr.
"""

from __future__ import annotations

import asyncio
import os
import sys

from . import (
    SecretAccessDenied,
    SecretBackendError,
    SecretNotFound,
    delete_secret,
    get_default_adapter,
    get_secret,
    list_secrets,
    put_secret,
)


def _die(code: int, msg: str) -> None:
    print(f"shared.secrets.cli: {msg}", file=sys.stderr)
    sys.exit(code)


async def _amain(argv: list[str]) -> int:
    if not argv:
        _die(4, "usage: get|put|delete|list|adapter [args]")

    cmd, *rest = argv

    try:
        get_default_adapter()
    except Exception as e:
        if cmd != "adapter":
            _die(5, f"no adapter configured: {e}. Run the Day-0 vault wizard first.")

    if cmd == "get":
        if len(rest) != 1:
            _die(4, "usage: get <path>")
        try:
            value = await get_secret(rest[0])
        except SecretNotFound:
            _die(1, f"not found: {rest[0]}")
        except SecretAccessDenied as e:
            _die(2, f"access denied: {e}")
        except SecretBackendError as e:
            _die(3, f"backend error: {e}")
        sys.stdout.write(value)
        sys.stdout.flush()
        return 0

    if cmd == "put":
        if len(rest) != 2:
            _die(4, "usage: put <path> <value | -for-stdin>")
        path, value = rest
        if value == "-":
            value = sys.stdin.read()
        try:
            await put_secret(path, value)
        except SecretAccessDenied as e:
            _die(2, f"access denied: {e}")
        except SecretBackendError as e:
            _die(3, f"backend error: {e}")
        return 0

    if cmd == "delete":
        if len(rest) != 1:
            _die(4, "usage: delete <path>")
        try:
            await delete_secret(rest[0])
        except SecretNotFound:
            return 0  # idempotent
        except SecretAccessDenied as e:
            _die(2, f"access denied: {e}")
        except SecretBackendError as e:
            _die(3, f"backend error: {e}")
        return 0

    if cmd == "list":
        prefix = rest[0] if rest else ""
        try:
            keys = await list_secrets(prefix)
        except SecretAccessDenied as e:
            _die(2, f"access denied: {e}")
        except SecretBackendError as e:
            _die(3, f"backend error: {e}")
        for k in keys:
            print(k)
        return 0

    if cmd == "adapter":
        try:
            a = get_default_adapter()
            print(getattr(a, "name", a.__class__.__name__))
            return 0
        except Exception as e:
            _die(5, f"no adapter configured: {e}")

    _die(4, f"unknown command: {cmd}")
    return 4  # unreachable


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        return asyncio.run(_amain(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

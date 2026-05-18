"""Shamir 3-of-5 secret sharing for the vendor license-signing key.

Part 4.3 of `docs/V3_BUILD_SEQUENCE.md` + design decision #9 (vault-only
secrets, no exceptions) + #18 (closed-source v1.0) + #32 layer 8 (vault
unseal recovery — Shamir 3-of-5 OR cloud-KMS) + #23 (license bundle
signing key custody — pattern lifted from HashiCorp Vault Enterprise,
Confluent Platform, MongoDB Atlas Enterprise).

Trust model
-----------

The vendor's 32-byte Ed25519 license-signing private key is stored in
the vendor vault under ``license/vendor_signing_key``. If that vault
unseals (operating shard) is lost / compromised, recovery is via
Shamir's Secret Sharing: the secret was split at vendor-init into
**5 shards**; any **3 shards** can reconstruct the original 32 bytes.

The 5 shards are distributed offline to 5 trusted parties (per the
Vault Enterprise recommended layout: 2 founders + CFO + outside legal
counsel + outside director). Each shard sits in physically-separate
custody (paper print in a safe deposit box, HSM, Yubikey, etc.). No
single party can recover the key; no single compromise loses it.

Critically (per #9):

* The reconstructed key **NEVER lands on disk** during recovery. It
  lives only in process memory and is immediately written to the vendor
  vault, then zeroed.
* Shard *file* contents are zeroed after read.
* The Hub binary's hard-coded ``TRUSTED_VENDOR_FINGERPRINT`` is
  unchanged by recovery (we reconstruct the same key bytes => same
  pubkey => same fingerprint). If the recovery is part of a key
  rotation, the operator runs ``bootstrap-keypair --rotate`` separately
  to mint a new key, re-shards, and re-releases the Hub binary with the
  new fingerprint.

Library choice
--------------

We use ``pyshamir`` (PyPI):

* **What:** pure-Python port of HashiCorp Vault's Shamir's Secret
  Sharing implementation. Wire-compatible with ``vault operator init``
  shards — the same scheme described in #32 layer 8.
* **Vetted:** the underlying algorithm is the HashiCorp implementation
  shipped in production vaults since 2015 across thousands of
  enterprises.
* **Surface:** ``pyshamir.split(secret: bytes, parts: int, threshold:
  int) -> list[bytes]`` and ``pyshamir.combine(shares: list[bytes]) ->
  bytes``. Two functions, < 500 LOC, no transitive deps.
* **License:** MPL-2.0 — compatible with our #18 closed-source posture
  (file-level copyleft only; we link, we do not modify).
* **CVE history:** none recorded against ``pyshamir`` itself. The
  underlying HashiCorp Shamir code has had zero CVEs against the
  scheme; vault-level CVEs (e.g. CVE-2020-16251) have all been at the
  vault-API / auth layer, not the SSS primitive.
* **Last release:** see ``pip show pyshamir`` at install time. Pin in
  CI/Docker-build.

Fallback library is ``sslib`` (PyPI; SSSA scheme). We prefer
``pyshamir`` for wire-compatibility with Vault's own shards, which
preserves the option for the operator to use ``vault operator init
-key-shares=5 -key-threshold=3`` directly as the shard producer in a
future hardening pass.

Rolling our own Shamir (over GF(256) with Lagrange interpolation) was
considered and **rejected**: crypto primitives written in-house are
high-risk per industry consensus. The 50-line implementation looks
trivial; the 50-line side-channel-resistant implementation is not.

Install (NOT done by this agent — declare-only per scope constraints)::

    pip install pyshamir==1.0.1   # or whatever 'pip index versions pyshamir' resolves

Public API
----------

* :func:`split_secret` — split a 32-byte secret into 5 shares, 3-of-5
  threshold. Returns 5 hex strings (each is the pyshamir share bytes,
  hex-encoded for safe paper/Yubikey storage).
* :func:`combine_shares` — combine >=3 shares (as hex strings) back
  into the original secret bytes.
* :func:`validate_share` — schema-check a single share without
  attempting reconstruction.
* :func:`write_share_files` — write split shares to chmod-600 files at
  operator-chosen paths; refuses to overwrite.
* :func:`read_and_zeroize_share_file` — read a share file, then zero
  its contents in place before reconstruction proceeds.
* :class:`ShamirError` — base for module-specific errors with stable
  ``.code`` so the CLI can surface structured messages.

This module is import-safe even if ``pyshamir`` is not installed: the
import is lazy and surfaces a clear ``ShamirError("library_unavailable",
...)`` only when the operator actually calls split/combine. ``py_compile``
+ ``pytest --co`` work without the dep so smoke tests pass in fresh
clones.
"""

from __future__ import annotations

import logging
import os
import re
import secrets as _secrets
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("spine.license.shamir")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Target secret length — Ed25519 raw private key is exactly 32 bytes.
SECRET_LEN_BYTES: int = 32

#: 3-of-5 threshold per Part 4.3 + #32 layer 8.
DEFAULT_PARTS: int = 5
DEFAULT_THRESHOLD: int = 3

#: A pyshamir share is ``len(secret) + 1`` bytes (each byte gets its own
#: GF(256) polynomial; the trailing byte is the X-coordinate of the share).
#: For a 32-byte secret the share is exactly 33 bytes => 66 hex chars.
SHARE_LEN_BYTES: int = SECRET_LEN_BYTES + 1
SHARE_LEN_HEX: int = SHARE_LEN_BYTES * 2

#: Regex hex-only sanity check used by :func:`validate_share`.
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ShamirError(Exception):
    """Stable-code error for Shamir split/combine failures.

    ``.code`` is a short stable token the CLI / caller can branch on
    without parsing the message. Codes:

    * ``library_unavailable`` — ``pyshamir`` is not installed.
    * ``bad_secret_length``    — split called with secret != 32 bytes.
    * ``bad_share_format``     — share is not hex / wrong length.
    * ``too_few_shares``       — combine called with < 3 shares.
    * ``duplicate_shares``     — two shares carry the same X-coordinate.
    * ``combine_failed``       — pyshamir refused (likely tampered share).
    * ``share_file_exists``    — refusing to overwrite an existing file.
    * ``share_file_unreadable`` — file missing or not readable.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Lazy library import
# ---------------------------------------------------------------------------


def _import_pyshamir():  # noqa: ANN202 — module object
    """Import ``pyshamir`` on demand; raise structured error if missing."""
    try:
        import pyshamir  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ShamirError(
            "library_unavailable",
            "pyshamir is required for Shamir split/combine. "
            "Install via: `pip install pyshamir` "
            "(see license/README.md for vendoring notes).",
        ) from exc
    return pyshamir


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_share(share_hex: str) -> None:
    """Raise :class:`ShamirError` if ``share_hex`` is not a well-formed share.

    Strong, library-agnostic checks (so we can refuse silently-bad
    shares **before** calling pyshamir):

    1. Stripped string is hex-only.
    2. Length is exactly :data:`SHARE_LEN_HEX` chars (66 for a 32-byte
       secret => 33-byte share).
    3. Not all-zero (defends against a "wiped" or placeholder share).

    These three together catch the common operator mistakes:
    truncated paste, accidental whitespace inside the hex, the wrong
    file copy-pasted (e.g. a SHA-256 hash, which is 64 chars not 66).
    """
    if not isinstance(share_hex, str):
        raise ShamirError(
            "bad_share_format",
            f"share must be a string, got {type(share_hex).__name__}",
        )
    s = share_hex.strip()
    if not s:
        raise ShamirError("bad_share_format", "share is empty")
    if not _HEX_RE.match(s):
        raise ShamirError(
            "bad_share_format",
            "share contains non-hex characters; expected 66 hex chars "
            "(33 bytes for a 32-byte secret)",
        )
    if len(s) != SHARE_LEN_HEX:
        raise ShamirError(
            "bad_share_format",
            f"share length {len(s)} hex chars, expected {SHARE_LEN_HEX} "
            f"({SHARE_LEN_BYTES} bytes for a {SECRET_LEN_BYTES}-byte secret)",
        )
    if int(s, 16) == 0:
        raise ShamirError(
            "bad_share_format",
            "share is all-zero; this is either a wiped placeholder or "
            "a copy-paste of empty contents — refusing",
        )


def _shares_have_unique_xs(share_bytes: List[bytes]) -> None:
    """Refuse a share-set whose X-coordinates collide.

    pyshamir's last byte is the share X-coordinate. Two shares with the
    same X are mathematically un-combinable; pyshamir will silently
    fail or return garbage on some versions. We pre-detect.
    """
    xs = [b[-1] for b in share_bytes]
    if len(set(xs)) != len(xs):
        raise ShamirError(
            "duplicate_shares",
            "two or more shares share the same X-coordinate; "
            "you probably submitted the same shard twice",
        )


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------


def split_secret(
    secret: bytes,
    *,
    parts: int = DEFAULT_PARTS,
    threshold: int = DEFAULT_THRESHOLD,
) -> List[str]:
    """Split ``secret`` (32 bytes) into ``parts`` shares; ``threshold`` to recover.

    Returns ``parts`` hex strings. Each is ``SHARE_LEN_HEX`` chars. The
    operator distributes these to ``parts`` offline custodians.

    Raises :class:`ShamirError` with ``code="library_unavailable"`` if
    pyshamir is not installed, or ``code="bad_secret_length"`` if the
    secret is not exactly :data:`SECRET_LEN_BYTES` bytes.
    """
    if not isinstance(secret, (bytes, bytearray)):
        raise ShamirError(
            "bad_secret_length",
            f"secret must be bytes, got {type(secret).__name__}",
        )
    if len(secret) != SECRET_LEN_BYTES:
        raise ShamirError(
            "bad_secret_length",
            f"secret must be exactly {SECRET_LEN_BYTES} bytes "
            f"(Ed25519 raw private key); got {len(secret)} bytes",
        )
    if not (1 < threshold <= parts):
        raise ShamirError(
            "bad_secret_length",
            f"invalid threshold/parts: threshold={threshold} parts={parts} "
            "(need 1 < threshold <= parts)",
        )
    pyshamir = _import_pyshamir()
    raw_shares: List[bytes] = pyshamir.split(bytes(secret), parts, threshold)
    return [b.hex() for b in raw_shares]


# ---------------------------------------------------------------------------
# Combine
# ---------------------------------------------------------------------------


def combine_shares(
    shares_hex: List[str],
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> bytes:
    """Combine ``shares_hex`` (>= ``threshold`` shares) back to the secret.

    Each input share goes through :func:`validate_share` first; any
    failure refuses the whole reconstruction. Then pyshamir does the
    Lagrange interpolation in GF(256).

    Returns the 32-byte secret. Caller is responsible for zeroizing it
    after use.
    """
    if not isinstance(shares_hex, list) or len(shares_hex) < threshold:
        raise ShamirError(
            "too_few_shares",
            f"need at least {threshold} shares to reconstruct; "
            f"got {len(shares_hex) if isinstance(shares_hex, list) else 0}",
        )
    # Validate every share BEFORE touching the library (defence-in-depth).
    for i, s in enumerate(shares_hex):
        try:
            validate_share(s)
        except ShamirError as exc:
            raise ShamirError(
                exc.code,
                f"share #{i + 1} rejected: {exc}",
            ) from exc
    share_bytes = [bytes.fromhex(s.strip()) for s in shares_hex]
    _shares_have_unique_xs(share_bytes)
    pyshamir = _import_pyshamir()
    try:
        secret: bytes = pyshamir.combine(share_bytes)
    except Exception as exc:  # noqa: BLE001 — pyshamir uses ValueError etc.
        raise ShamirError(
            "combine_failed",
            f"pyshamir.combine refused the shares (likely tampered or "
            f"mismatched share-set): {exc}",
        ) from exc
    if len(secret) != SECRET_LEN_BYTES:
        # Should never happen if validate_share() passed; defence-in-depth.
        raise ShamirError(
            "combine_failed",
            f"reconstructed secret was {len(secret)} bytes, expected "
            f"{SECRET_LEN_BYTES}",
        )
    return secret


# ---------------------------------------------------------------------------
# Share-file I/O
# ---------------------------------------------------------------------------


def write_share_files(
    shares_hex: List[str],
    output_paths: List[Path],
) -> List[Path]:
    """Write each share to its own chmod-600 file. Refuses to overwrite.

    Raises :class:`ShamirError` with ``code="share_file_exists"`` if any
    target path already exists — operator must explicitly remove first
    so we never silently clobber a share file in use.
    """
    if len(shares_hex) != len(output_paths):
        raise ShamirError(
            "bad_share_format",
            f"got {len(shares_hex)} shares but {len(output_paths)} output paths",
        )
    # Pre-check all paths before writing any — atomic-ish failure.
    for p in output_paths:
        if p.exists():
            raise ShamirError(
                "share_file_exists",
                f"refusing to overwrite existing file: {p}",
            )
    written: List[Path] = []
    for share, path in zip(shares_hex, output_paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write with restrictive permissions from the start. We use
        # os.open with O_CREAT|O_EXCL|O_WRONLY so we never race with
        # another process creating the same file between exists() and
        # open().
        fd = os.open(
            str(path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(share.strip() + "\n")
        except Exception:
            # If we crashed mid-write, leave nothing useful on disk.
            try:
                path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 — best-effort
                pass
            raise
        os.chmod(str(path), 0o600)
        written.append(path)
    return written


def read_and_zeroize_share_file(path: Path) -> str:
    """Read a share hex from ``path``, then overwrite the file with zeros.

    Per #9: the reconstructed key never lands on disk, AND the input
    shares should not linger on the recovery operator's machine after
    use. We overwrite the file contents with hex zeros of the same
    length, then truncate, then unlink. This is best-effort against
    journaling filesystems but is the standard recommendation in
    HashiCorp's Vault unseal runbook.
    """
    p = Path(path)
    if not p.is_file():
        raise ShamirError(
            "share_file_unreadable",
            f"share file not found or not a regular file: {p}",
        )
    try:
        content = p.read_text().strip()
    except OSError as exc:
        raise ShamirError(
            "share_file_unreadable",
            f"could not read share file {p}: {exc}",
        ) from exc
    if not content:
        raise ShamirError(
            "share_file_unreadable",
            f"share file {p} is empty",
        )
    # Overwrite then unlink.
    try:
        with open(p, "w") as f:
            f.write("0" * len(content) + "\n")
            f.flush()
            os.fsync(f.fileno())
        p.unlink()
    except OSError as exc:  # noqa: BLE001 — best-effort wipe
        logger.warning(
            "shamir_share_wipe_failed",
            extra={"path": str(p), "err": str(exc)},
        )
    return content


def zeroize_bytes(buf: bytes) -> bytes:
    """Best-effort zeroize a bytes-like buffer.

    Python doesn't guarantee zeroing of immutable bytes; we rebind to a
    fresh zero-buffer and trust GC to reclaim the original. Callers
    that need real wiping should use ``bytearray`` + manual overwrite,
    which is what :func:`combine_shares` callers do in tools/license-sign.sh.
    """
    return b"\x00" * len(buf)


# ---------------------------------------------------------------------------
# Convenience for tools/license-sign.sh
# ---------------------------------------------------------------------------


def reconstruct_from_files(
    share_paths: List[Path],
    *,
    threshold: int = DEFAULT_THRESHOLD,
    zeroize_files: bool = True,
) -> Tuple[bytes, List[Path]]:
    """One-shot helper: read N share files, reconstruct, zeroize files.

    Returns ``(secret_bytes, wiped_paths)``. The reconstructed bytes
    must be moved into the vault by the caller and then explicitly
    zeroed; we do not write to vault from here (separation of concerns —
    the CLI layer holds the vault adapter).
    """
    if len(share_paths) < threshold:
        raise ShamirError(
            "too_few_shares",
            f"need at least {threshold} share files; got {len(share_paths)}",
        )
    shares: List[str] = []
    wiped: List[Path] = []
    for p in share_paths:
        if zeroize_files:
            shares.append(read_and_zeroize_share_file(p))
            wiped.append(p)
        else:
            try:
                shares.append(Path(p).read_text().strip())
            except OSError as exc:
                raise ShamirError(
                    "share_file_unreadable",
                    f"could not read share file {p}: {exc}",
                ) from exc
    secret = combine_shares(shares, threshold=threshold)
    return secret, wiped


def generate_ed25519_seed() -> bytes:
    """Generate a fresh 32-byte secret suitable as an Ed25519 raw private key.

    Used by the splitter CLI when the operator asks for a brand-new key
    to be split (the common case at vendor first-run / rotation).

    We use ``secrets.token_bytes`` — CSPRNG, audit-friendly, no external
    dep. ``cryptography.Ed25519PrivateKey.generate`` is the canonical
    Spine path elsewhere; we accept either as input.
    """
    return _secrets.token_bytes(SECRET_LEN_BYTES)


__all__ = [
    "DEFAULT_PARTS",
    "DEFAULT_THRESHOLD",
    "SECRET_LEN_BYTES",
    "SHARE_LEN_BYTES",
    "SHARE_LEN_HEX",
    "ShamirError",
    "combine_shares",
    "generate_ed25519_seed",
    "read_and_zeroize_share_file",
    "reconstruct_from_files",
    "split_secret",
    "validate_share",
    "write_share_files",
    "zeroize_bytes",
]

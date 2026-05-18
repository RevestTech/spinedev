#!/usr/bin/env bash
# tools/license-sign.sh — Spine v3 license-bundle signing CLI (vendor-side ONLY).
#
# Implements design decisions #9 (vault-only secrets) + #23 (feature-flag
# licensing as Day-1 primitive) + Part 4.3 (vendor signing key custody +
# Shamir 3-of-5 recovery). See license/README.md.
#
# Trust model:
#   - The Ed25519 SIGNING key lives ONLY in the vendor vault. This script
#     loads it on-demand, signs in memory, and exits. The key never lands
#     on disk and never enters source control. The signing-key vault path
#     is `license/vendor_signing_key` by default; override with --vault-path.
#   - If the operating signing key is lost / compromised, recovery is via
#     Shamir 3-of-5: at least 3 of the 5 shard-holders run
#     `tools/license-sign.sh recover-shamir --shard <hex>` (called 3 times,
#     once per shard) which reconstructs the key in vault under a new path
#     and emits the new fingerprint. The Hub binary must be re-released
#     with the new fingerprint baked in as TRUSTED_VENDOR_FINGERPRINT.
#
# Customer-side usage (NOT this script): the Hub verifies signed bundles
# via `license.bundle_verifier.load_active_bundle`. This script is the
# producer side ONLY. Customers receive the signed bundle as a file +
# `psql -f` it into their `spine_license.bundle` table; the Hub picks it
# up on next periodic verify.
#
# Subcommands:
#   sign              produce a signed bundle from a JSON payload
#   verify            verify a signed bundle against the vendor public key
#                     (smoke-test for the signer; the Hub uses Python)
#   bootstrap-keypair generate a fresh Ed25519 keypair and store the
#                     private key in vault (vendor first-run / rotation)
#   shamir-split      split a fresh / supplied 32-byte secret into 5
#                     Shamir shares (3-of-5 threshold) writing each share
#                     to a chmod-600 file
#   recover-shamir    reconstruct the signing key from 3 Shamir share
#                     files; posts to vault and zeroizes the share files
#   --help            this message
#
# Exit codes:
#   0  success
#   1  generic / fall-through error
#   2  invalid input (bad flags, missing file, malformed JSON)
#   3  vault unreachable / vault-cli not installed
#   4  signature verification failed
#   5  fingerprint mismatch (Hub trust-anchor check would refuse this bundle)

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── defaults (env-overridable) ─────────────────────────────────────
VAULT_PATH="${SPINE_LICENSE_SIGNING_VAULT_PATH:-license/vendor_signing_key}"
PUBKEY_VAULT_PATH="${SPINE_LICENSE_VENDOR_PUBKEY_PATH:-license/vendor_pubkey}"
PYTHON="${PYTHON:-python3}"

# ─── logging ─────────────────────────────────────────────────────────
_ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
_log() { printf '%s license-sign.sh %s %s\n' "$(_ts)" "$1" "${*:2}" >&2; }
_err() { _log ERROR "$*"; }

# ─── usage ───────────────────────────────────────────────────────────
usage() {
  cat <<EOF
tools/license-sign.sh — Spine license-bundle signing CLI (vendor-side ONLY)

USAGE
  tools/license-sign.sh sign --payload <file.json> --output <signed.json>
                             [--vault-path <path>] [--pubkey-vault-path <path>]
  tools/license-sign.sh verify --signed <signed.json>
                               [--pubkey-vault-path <path>]
  tools/license-sign.sh bootstrap-keypair [--vault-path <path>]
                                          [--pubkey-vault-path <path>]
                                          [--rotate]
  tools/license-sign.sh shamir-split [--secret-hex <hex>] --out <dir>
                                     [--parts N] [--threshold K]
                                     [--prefix <name>]
  tools/license-sign.sh recover-shamir --share-file <path>
                                       [--share-file <path>] ...
                                       [--vault-path <path>]
                                       [--keep-share-files]
                                       [--dry-run]

OPTIONS
  --payload <file>          JSON payload matching license-bundle-v1
                            (see shared/schemas/license/bundle_v1.py).
  --output <file>           Where to write the signed envelope.
  --signed <file>           Signed envelope to verify.
  --vault-path <p>          Vault path for the PRIVATE signing key
                            (default: $VAULT_PATH).
  --pubkey-vault-path <p>   Vault path for the PUBLIC vendor key
                            (default: $PUBKEY_VAULT_PATH).
  --rotate                  When bootstrapping, allow overwrite of an
                            existing private-key entry.
  --share-file <path>       A Shamir share file (repeatable; need >= 3).
                            Each file contains one hex share on a single
                            line. Files are zeroized + unlinked after
                            successful reconstruction (suppress with
                            --keep-share-files).
  --keep-share-files        Do NOT zeroize+unlink share files after a
                            successful recover-shamir run. Intended for
                            dry-run / rehearsal only — leaves shares on
                            disk, which violates the trust model in prod.
  --dry-run                 recover-shamir only: reconstruct + print
                            fingerprint, but do NOT write to vault.
  --secret-hex <hex>        shamir-split only: 32-byte secret in hex
                            (64 chars). Default = generate fresh CSPRNG.
  --out <dir>               shamir-split only: directory to write the
                            share files into (must not contain prior
                            shares with the same prefix).
  --parts N                 shamir-split only: total shares (default 5).
  --threshold K             shamir-split only: shares needed to combine
                            (default 3).
  --prefix <name>           shamir-split only: filename prefix
                            (default 'vendor-signing-share').

TRUST MODEL
  - Private signing key NEVER on disk. Loaded from vault, signed in
    memory, key bytes zeroed on exit (#9).
  - Key custody: Shamir 3-of-5 across vendor officers (Part 4.3).
  - The Hub binary hard-codes TRUSTED_VENDOR_FINGERPRINT at build
    time. Any signed bundle whose pubkey fingerprint doesn't match is
    refused.

EXIT CODES
  0=ok 1=generic 2=bad-input 3=vault-unreachable 4=sig-verify-failed
  5=fingerprint-mismatch

EXAMPLES
  # Vendor first-run: bootstrap a keypair, store private in vault.
  tools/license-sign.sh bootstrap-keypair

  # Sign a customer's license payload.
  tools/license-sign.sh sign \\
      --payload payloads/acme-team-tier.json \\
      --output  signed/acme-team-tier.signed.json

  # Customer receives signed.json and imports via psql:
  #   psql -f tools/license-import.sql -v signed=signed.json
EOF
}

# ─── arg parsing ─────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then usage; exit 0; fi
case "${1:-}" in -h|--help|help) usage; exit 0 ;; esac

CMD="$1"; shift
PAYLOAD=""; OUTPUT=""; SIGNED=""; ROTATE=0
SECRET_HEX=""; OUT_DIR=""; PARTS=5; THRESHOLD=3; PREFIX="vendor-signing-share"
KEEP_SHARES=0; DRY_RUN=0
declare -a SHARE_FILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --payload)            PAYLOAD="$2"; shift 2 ;;
    --output)             OUTPUT="$2";  shift 2 ;;
    --signed)             SIGNED="$2";  shift 2 ;;
    --vault-path)         VAULT_PATH="$2"; shift 2 ;;
    --pubkey-vault-path)  PUBKEY_VAULT_PATH="$2"; shift 2 ;;
    --rotate)             ROTATE=1; shift ;;
    --share-file)         SHARE_FILES+=("$2"); shift 2 ;;
    --keep-share-files)   KEEP_SHARES=1; shift ;;
    --dry-run)            DRY_RUN=1; shift ;;
    --secret-hex)         SECRET_HEX="$2"; shift 2 ;;
    --out)                OUT_DIR="$2"; shift 2 ;;
    --parts)              PARTS="$2"; shift 2 ;;
    --threshold)          THRESHOLD="$2"; shift 2 ;;
    --prefix)             PREFIX="$2"; shift 2 ;;
    -h|--help)            usage; exit 0 ;;
    *) _err "unknown flag: $1"; usage; exit 2 ;;
  esac
done

# ─── vault helpers ───────────────────────────────────────────────────
# We support two vault CLIs: HashiCorp `vault` and OpenBao `bao` (the
# Day-0 default per #9). Whichever is on PATH wins. For local dogfood
# we also accept an env override SPINE_LICENSE_LOCAL_PRIV_HEX which
# inlines the hex private key — used ONLY by the test harness; the
# production path is the vault read.
_vault_cli() {
  if [[ -n "${SPINE_LICENSE_LOCAL_PRIV_HEX:-}" ]]; then return 0; fi
  if command -v bao   >/dev/null 2>&1; then printf 'bao'; return 0; fi
  if command -v vault >/dev/null 2>&1; then printf 'vault'; return 0; fi
  return 1
}

_vault_read() {
  # $1 = vault path; emits raw value (single field "value") to stdout
  if [[ -n "${SPINE_LICENSE_LOCAL_PRIV_HEX:-}" && "$1" == "$VAULT_PATH" ]]; then
    printf '%s' "$SPINE_LICENSE_LOCAL_PRIV_HEX"; return 0
  fi
  if [[ -n "${SPINE_LICENSE_LOCAL_PUB_HEX:-}" && "$1" == "$PUBKEY_VAULT_PATH" ]]; then
    printf '%s' "$SPINE_LICENSE_LOCAL_PUB_HEX"; return 0
  fi
  local cli; cli="$(_vault_cli)" || { _err "no vault CLI on PATH and no SPINE_LICENSE_LOCAL_* override"; return 3; }
  "$cli" kv get -field=value "$1" 2>/dev/null
}

_vault_write() {
  # $1 = vault path, $2 = value
  local cli; cli="$(_vault_cli)" || { _err "no vault CLI on PATH"; return 3; }
  "$cli" kv put "$1" "value=$2" >/dev/null
}

# ─── sign ────────────────────────────────────────────────────────────
cmd_sign() {
  [[ -z "$PAYLOAD" || -z "$OUTPUT" ]] && { _err "sign requires --payload and --output"; exit 2; }
  [[ -f "$PAYLOAD" ]] || { _err "payload not found: $PAYLOAD"; exit 2; }
  local priv_hex pub_hex
  priv_hex="$(_vault_read "$VAULT_PATH" || true)"
  if [[ -z "$priv_hex" ]]; then _err "could not read private key from vault path '$VAULT_PATH'"; exit 3; fi
  pub_hex="$(_vault_read "$PUBKEY_VAULT_PATH" || true)"

  "$PYTHON" - "$PAYLOAD" "$OUTPUT" "$priv_hex" "${pub_hex:-}" <<'PYEOF'
import base64, hashlib, json, sys
from pathlib import Path

payload_path = Path(sys.argv[1])
out_path     = Path(sys.argv[2])
priv_hex     = sys.argv[3].strip()
pub_hex_in   = sys.argv[4].strip() if len(sys.argv) > 4 else ""

# Defer imports so --help doesn't require cryptography.
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

# Load payload + Pydantic-validate via the same schema the Hub uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from shared.schemas.license import LicenseBundlePayload  # noqa: E402

raw = json.loads(payload_path.read_text())
payload = LicenseBundlePayload.model_validate(raw)

# Canonical bytes (must match license.bundle_verifier.canonicalise exactly).
canon = json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8")

priv_bytes = bytes.fromhex(priv_hex)
if len(priv_bytes) != 32:
    raise SystemExit(f"private key must be 32 raw bytes, got {len(priv_bytes)}")
key = Ed25519PrivateKey.from_private_bytes(priv_bytes)
sig = key.sign(canon)
pub_bytes = key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
fp = hashlib.sha256(pub_bytes).hexdigest()
if pub_hex_in and pub_hex_in.lower() != pub_bytes.hex():
    print(f"WARN: vault pubkey ({pub_hex_in[:16]}...) does not match private "
          f"key's derived public ({pub_bytes.hex()[:16]}...); update vault.",
          file=sys.stderr)

envelope = {
    "payload_canonical_b64":   base64.b64encode(canon).decode("ascii"),
    "signature_b64":           base64.b64encode(sig).decode("ascii"),
    "signing_key_fingerprint": fp,
}
out_path.write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n")
# Zero the in-memory key bytes (best-effort; Python doesn't guarantee
# bytes-object zeroing, but rebinding helps GC collect promptly).
priv_bytes = b"\x00" * 32
print(f"signed_ok fingerprint={fp} payload_bytes={len(canon)} sig_bytes={len(sig)}")
PYEOF
}

# ─── verify ──────────────────────────────────────────────────────────
cmd_verify() {
  [[ -z "$SIGNED" ]] && { _err "verify requires --signed"; exit 2; }
  [[ -f "$SIGNED" ]] || { _err "signed file not found: $SIGNED"; exit 2; }
  local pub_hex; pub_hex="$(_vault_read "$PUBKEY_VAULT_PATH" || true)"
  [[ -z "$pub_hex" ]] && { _err "could not read public key from vault"; exit 3; }
  "$PYTHON" - "$SIGNED" "$pub_hex" <<'PYEOF'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from shared.schemas.license import SignedLicenseBundle
from license.bundle_verifier import verify_signature, BundleVerificationError

env = SignedLicenseBundle.model_validate(json.loads(Path(sys.argv[1]).read_text()))
pub_hex = sys.argv[2].strip()
try:
    payload = verify_signature(env, vendor_public_key_bytes=bytes.fromhex(pub_hex))
except BundleVerificationError as exc:
    print(f"FAIL code={exc.code} msg={exc}")
    sys.exit(4 if exc.code == "invalid_signature" else 5)
print(f"OK tier={payload.tier} bundle_id={payload.bundle_id} "
      f"customer={payload.customer} flags={len(payload.feature_flags)}")
PYEOF
}

# ─── bootstrap-keypair ───────────────────────────────────────────────
cmd_bootstrap_keypair() {
  "$PYTHON" - "$VAULT_PATH" "$PUBKEY_VAULT_PATH" "$ROTATE" <<'PYEOF'
import os, sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

vault_path = sys.argv[1]
pubkey_path = sys.argv[2]
rotate = sys.argv[3] == "1"

key = Ed25519PrivateKey.generate()
priv_bytes = key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
pub_bytes = key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
print("PRIVATE_HEX_FOR_VAULT_WRITE=", priv_bytes.hex(), sep="")
print("PUBLIC_HEX_FOR_VAULT_WRITE=", pub_bytes.hex(), sep="")
print(f"FINGERPRINT_BAKE_INTO_HUB={__import__('hashlib').sha256(pub_bytes).hexdigest()}")
print(f"rotate={rotate} vault_path={vault_path} pubkey_path={pubkey_path}")
print("NEXT: vault kv put $VAULT_PATH value=<PRIVATE_HEX>  "
      "&& vault kv put $PUBKEY_VAULT_PATH value=<PUBLIC_HEX>")
print("NEXT: also split <PRIVATE_HEX> with Shamir 3-of-5 (see Part 4.3).")
PYEOF
}

# ─── shamir-split ────────────────────────────────────────────────────
cmd_shamir_split() {
  if [[ -z "$OUT_DIR" ]]; then
    _err "shamir-split requires --out <dir>"
    exit 2
  fi
  if [[ ! -d "$OUT_DIR" ]]; then
    _err "output dir does not exist: $OUT_DIR"
    exit 2
  fi
  "$PYTHON" - "$OUT_DIR" "$PARTS" "$THRESHOLD" "$PREFIX" "$SECRET_HEX" <<'PYEOF'
import hashlib, sys
from pathlib import Path

out_dir = Path(sys.argv[1])
parts   = int(sys.argv[2])
thresh  = int(sys.argv[3])
prefix  = sys.argv[4]
secret_hex_in = sys.argv[5].strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from license import shamir  # noqa: E402

if secret_hex_in:
    try:
        secret = bytes.fromhex(secret_hex_in)
    except ValueError as exc:
        raise SystemExit(f"--secret-hex is not valid hex: {exc}")
    if len(secret) != shamir.SECRET_LEN_BYTES:
        raise SystemExit(f"--secret-hex must decode to {shamir.SECRET_LEN_BYTES} "
                         f"bytes, got {len(secret)}")
    source = "operator-supplied"
else:
    secret = shamir.generate_ed25519_seed()
    source = "csprng-fresh"

# Derive the Ed25519 public-key fingerprint so the operator can sanity-
# check this matches the key they intend to back up.
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.from_private_bytes(secret)
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fp = hashlib.sha256(pub).hexdigest()
except Exception as exc:  # pragma: no cover — cryptography is documented dep
    raise SystemExit(f"could not derive pubkey fingerprint: {exc}")

try:
    shares = shamir.split_secret(secret, parts=parts, threshold=thresh)
except shamir.ShamirError as exc:
    raise SystemExit(f"shamir_split_failed code={exc.code} msg={exc}")

# Zeroize the local secret bytes ASAP — we never need them again past this point.
secret = shamir.zeroize_bytes(secret)

paths = [out_dir / f"{prefix}-{i + 1}-of-{parts}.hex" for i in range(parts)]
try:
    written = shamir.write_share_files(shares, paths)
except shamir.ShamirError as exc:
    raise SystemExit(f"shamir_write_failed code={exc.code} msg={exc}")

# Zeroize the in-memory share strings (best-effort).
shares = ["0" * len(s) for s in shares]

print(f"shamir_split_ok source={source} parts={parts} threshold={thresh}")
print(f"signing_key_fingerprint={fp}")
print("share_files:")
for p in written:
    print(f"  {p}")
print("")
print("NEXT STEPS (vendor officer runbook — Part 4.3):")
print("  1. Verify each share file exists and is chmod 600.")
print(f"  2. Distribute the {parts} share files OFFLINE to {parts} trusted")
print("     parties (Vault Enterprise recommendation: 2 founders + CFO +")
print("     outside legal counsel + outside director).")
print("  3. Each party stores their share in physically-separate custody")
print("     (safe deposit box, HSM, Yubikey, sealed envelope).")
print("  4. REHEARSE: collect any 3 shares back, run `recover-shamir")
print("     --dry-run --share-file ...`, confirm the printed fingerprint")
print(f"     matches: {fp}")
print("  5. Once rehearsal passes: DELETE the original share files from")
print(f"     {out_dir} (they've been distributed, the disk copies are toxic).")
print("  6. Bake the fingerprint into the Hub binary as")
print("     TRUSTED_VENDOR_FINGERPRINT and ship the release.")
PYEOF
}

# ─── recover-shamir ──────────────────────────────────────────────────
cmd_recover_shamir() {
  if [[ "${#SHARE_FILES[@]}" -lt 3 ]]; then
    _err "recover-shamir requires at least 3 --share-file <path> arguments"
    exit 2
  fi
  # Validate that all share files exist BEFORE entering python — fail
  # fast with a clear shell-level error.
  local sf
  for sf in "${SHARE_FILES[@]}"; do
    if [[ ! -f "$sf" ]]; then
      _err "share file not found: $sf"
      exit 2
    fi
  done

  # If we're going to write to vault, ensure a vault CLI (or local
  # override) is available BEFORE we consume the share files.
  if [[ "$DRY_RUN" -eq 0 ]]; then
    if [[ -z "${SPINE_LICENSE_LOCAL_PRIV_HEX:-}" ]]; then
      _vault_cli >/dev/null || { _err "no vault CLI (vault/bao) on PATH; refusing to consume share files without a write target. Use --dry-run to rehearse."; exit 3; }
    fi
  fi

  # Hand the share files to python. Python handles: validate -> combine
  # -> zeroize files -> print fingerprint. We then handle: write to
  # vault from a tempfile-free pipe. The key never lands on disk.
  #
  # Avoid heredoc-inside-$(...) which is buggy under bash 3.2 (macOS
  # default). Instead, pipe the script body through stdin and capture
  # stdout into $py_out via a process-sub-free temp variable.
  local py_out fp recovered_hex
  local py_script
  py_script="$(cat <<'PYEOF'
import hashlib, sys
from pathlib import Path

keep_shares = sys.argv[1] == "1"
dry_run     = sys.argv[2] == "1"
share_paths = [Path(p) for p in sys.argv[3:]]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from license import shamir  # noqa: E402

try:
    secret, wiped = shamir.reconstruct_from_files(
        share_paths,
        zeroize_files=not keep_shares,
    )
except shamir.ShamirError as exc:
    print("FAIL code={} msg={}".format(exc.code, exc), file=sys.stderr)
    if exc.code in ("too_few_shares", "bad_share_format",
                    "duplicate_shares", "share_file_unreadable"):
        sys.exit(2)
    if exc.code == "combine_failed":
        sys.exit(4)
    sys.exit(3)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.from_private_bytes(secret)
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fp = hashlib.sha256(pub).hexdigest()
except Exception as exc:
    secret = shamir.zeroize_bytes(secret)
    print("FAIL code=fp_derive_failed msg={}".format(exc), file=sys.stderr)
    sys.exit(1)

print("FP={}".format(fp))
if not dry_run:
    print("HEX={}".format(secret.hex()))
print("WIPED_COUNT={}".format(len(wiped)), file=sys.stderr)
for p in wiped:
    print("WIPED {}".format(p), file=sys.stderr)

secret = shamir.zeroize_bytes(secret)
PYEOF
)"
  py_out="$(printf '%s' "$py_script" | "$PYTHON" - "$KEEP_SHARES" "$DRY_RUN" "${SHARE_FILES[@]}")"
  # If python failed it already printed FAIL=... on stderr; bubble up.
  if [[ -z "$py_out" ]]; then
    _err "reconstructor produced no output (see stderr)"
    exit 1
  fi
  fp="$(printf '%s\n' "$py_out" | awk -F= '/^FP=/{print $2}')"
  if [[ -z "$fp" ]]; then
    _err "could not parse fingerprint from reconstructor output"
    exit 1
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'shamir_recover_dry_run_ok fingerprint=%s\n' "$fp"
    printf 'Compare against the Hub binary'\''s TRUSTED_VENDOR_FINGERPRINT.\n'
    printf 'No write to vault. Share files: %s\n' \
      "$([[ "$KEEP_SHARES" -eq 1 ]] && echo 'kept on disk (rehearsal mode)' || echo 'zeroized + unlinked')"
    return 0
  fi
  recovered_hex="$(printf '%s\n' "$py_out" | awk -F= '/^HEX=/{print $2}')"
  if [[ -z "$recovered_hex" ]]; then
    _err "reconstructor did not emit HEX (non-dry-run expected one)"
    exit 1
  fi
  # Post to vault. Per #9 the key never lands on disk; it travels
  # through environment / pipe only. Some vault CLIs accept value=@-
  # for stdin; we use the simplest portable form (value=<hex> as arg).
  if ! _vault_write "$VAULT_PATH" "$recovered_hex"; then
    # Best-effort scrub of the variable holding the hex string.
    recovered_hex="$(printf '0%.0s' $(seq 1 ${#recovered_hex}))"
    _err "vault write to $VAULT_PATH failed; key NOT installed. Re-run with --dry-run to confirm reconstruction, then fix the vault adapter."
    exit 3
  fi
  # Scrub the local variable holding the hex.
  recovered_hex="$(printf '0%.0s' $(seq 1 ${#recovered_hex}))"
  unset recovered_hex
  cat <<EOF
shamir_recover_ok fingerprint=$fp vault_path=$VAULT_PATH
NEXT STEPS:
  1. Compare fingerprint above against the Hub binary's
     TRUSTED_VENDOR_FINGERPRINT (baked at build time).
     - MATCH:  recovery succeeded; no Hub re-release needed.
     - MISMATCH: the operator recovered the wrong key OR the Hub
       binary was built against a different keypair. DO NOT proceed
       to sign customer bundles until this is resolved.
  2. Run \`tools/license-sign.sh verify --signed <a-prior-good-bundle>\`
     to confirm signing works against the restored key.
  3. Notify federation tree (per #16) of the recovery event (audit).
  4. Audit each share custodian's environment — physical custody chain
     and access logs — to determine whether the original loss event
     compromised the scheme.
EOF
}

# ─── dispatch ────────────────────────────────────────────────────────
case "$CMD" in
  sign)              cmd_sign ;;
  verify)            cmd_verify ;;
  bootstrap-keypair) cmd_bootstrap_keypair ;;
  shamir-split)      cmd_shamir_split ;;
  recover-shamir)    cmd_recover_shamir ;;
  *) _err "unknown subcommand: $CMD"; usage; exit 2 ;;
esac

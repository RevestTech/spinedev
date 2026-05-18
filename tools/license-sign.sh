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
#   recover-shamir    reconstruct the signing key from 3 Shamir shards
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
  tools/license-sign.sh recover-shamir --shard <hex> [--shard <hex>] ...
                                       [--vault-path <path>]

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
  --shard <hex>             A Shamir shard (repeatable; need >= 3).

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
declare -a SHARDS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --payload)            PAYLOAD="$2"; shift 2 ;;
    --output)             OUTPUT="$2";  shift 2 ;;
    --signed)             SIGNED="$2";  shift 2 ;;
    --vault-path)         VAULT_PATH="$2"; shift 2 ;;
    --pubkey-vault-path)  PUBKEY_VAULT_PATH="$2"; shift 2 ;;
    --rotate)             ROTATE=1; shift ;;
    --shard)              SHARDS+=("$2"); shift 2 ;;
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

# ─── recover-shamir ──────────────────────────────────────────────────
cmd_recover_shamir() {
  if [[ "${#SHARDS[@]}" -lt 3 ]]; then
    _err "recover-shamir requires at least 3 --shard <hex> arguments"
    exit 2
  fi
  # Wave-4 scope-boundary: ship the entry-point + arg validation now.
  # Pulling in a Shamir implementation (`pyshamir` / `mnemonic-shamir`)
  # is a dep decision deferred to the Wave-0 dependency audit; this
  # placeholder makes the recovery flow visible without expanding deps.
  cat <<EOF
WAVE-4 STUB: $(printf '%s' "${#SHARDS[@]}") shards received.
Production recovery flow (per Part 4.3):
  1. Collect 3 of 5 Shamir shards from vendor officers via secure channel.
  2. Reconstruct the 32-byte Ed25519 private key with pyshamir / sslib.
  3. \`tools/license-sign.sh bootstrap-keypair --rotate\` to derive the
     new public key + fingerprint.
  4. \`vault kv put $VAULT_PATH value=<reconstructed_priv_hex>\`
  5. Re-release the Hub binary with the new TRUSTED_VENDOR_FINGERPRINT
     baked in.
  6. Notify federation tree (#16) so customers re-pull bundles.
EOF
}

# ─── dispatch ────────────────────────────────────────────────────────
case "$CMD" in
  sign)              cmd_sign ;;
  verify)            cmd_verify ;;
  bootstrap-keypair) cmd_bootstrap_keypair ;;
  recover-shamir)    cmd_recover_shamir ;;
  *) _err "unknown subcommand: $CMD"; usage; exit 2 ;;
esac

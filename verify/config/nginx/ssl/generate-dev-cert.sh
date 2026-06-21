#!/usr/bin/env bash
# Generate a self-signed TLS certificate for LOCAL DEVELOPMENT ONLY.
#
# Output lives next to this script:
#   ./cert.pem   — self-signed certificate, 397-day validity
#   ./key.pem    — 2048-bit RSA private key, mode 0600
#
# The cert covers: localhost, 127.0.0.1, ::1, tron-nginx (the docker service
# name), and whatever hostname you pass as $TRON_DEV_CERT_HOSTNAME. Browsers
# will still throw a warning (self-signed by nature) but the stack will serve
# HTTPS correctly.
#
# DO NOT ship this output to production. Production uses real CA-issued certs;
# see docs/security/TLS_RUNBOOK.md for how to rotate those in.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT="${SCRIPT_DIR}/cert.pem"
KEY="${SCRIPT_DIR}/key.pem"
CN="${TRON_DEV_CERT_CN:-tron-dev}"
EXTRA_HOST="${TRON_DEV_CERT_HOSTNAME:-}"

if ! command -v openssl >/dev/null 2>&1; then
    echo "error: openssl is required but not on PATH" >&2
    exit 1
fi

if [[ -f "$CERT" && -f "$KEY" ]]; then
    # Don't silently overwrite an existing cert — a human may have dropped a
    # real one in here for a private test domain.
    if [[ "${TRON_DEV_CERT_FORCE:-0}" != "1" ]]; then
        echo "cert.pem and key.pem already exist; refusing to overwrite." >&2
        echo "Set TRON_DEV_CERT_FORCE=1 to regenerate." >&2
        exit 2
    fi
fi

# Build the SAN list.
SAN="DNS:localhost,DNS:tron-nginx,IP:127.0.0.1,IP:::1"
if [[ -n "$EXTRA_HOST" ]]; then
    SAN="${SAN},DNS:${EXTRA_HOST}"
fi

TMP_CFG="$(mktemp)"
trap 'rm -f "$TMP_CFG"' EXIT

cat > "$TMP_CFG" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = ${CN}

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SAN}
basicConstraints = critical, CA:FALSE
EOF

openssl req \
    -x509 -nodes \
    -newkey rsa:2048 \
    -days 397 \
    -keyout "$KEY" \
    -out "$CERT" \
    -config "$TMP_CFG"

chmod 600 "$KEY"
chmod 644 "$CERT"

echo "Generated self-signed dev cert:"
echo "  $CERT"
echo "  $KEY"
echo
echo "SANs: $SAN"
echo
echo "Reminder: this is a DEV cert. Do not use in production."

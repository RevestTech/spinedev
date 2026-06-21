"""
Regression tests for the shape of config/nginx/nginx.conf.

We cannot actually run nginx from a unit test — that would need a container
runtime. What we CAN do is make sure the static config keeps enforcing the
TLS posture documented in docs/security/TLS_RUNBOOK.md. If someone
comments out HSTS or re-enables TLSv1.0, these tests fire.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "config" / "nginx" / "nginx.conf"


@pytest.fixture(scope="module")
def conf() -> str:
    assert NGINX_CONF.exists(), f"missing {NGINX_CONF}"
    return NGINX_CONF.read_text(encoding="utf-8")


# ── TLS listener is present and hardened ─────────────────────────────────


def test_listens_on_443_with_ssl(conf: str) -> None:
    # Must be a real TLS listener, not a commented-out stub.
    assert re.search(r"^\s*listen\s+443\s+ssl", conf, re.MULTILINE), (
        "Expected an uncommented ``listen 443 ssl`` directive — TLS must be "
        "the default listener per docs/security/TLS_RUNBOOK.md."
    )


def test_http2_is_enabled(conf: str) -> None:
    assert re.search(r"^\s*http2\s+on\s*;", conf, re.MULTILINE), (
        "http2 must be explicitly enabled on the TLS vhost."
    )


def test_tls_protocols_are_12_and_13_only(conf: str) -> None:
    m = re.search(r"ssl_protocols\s+([^;]+);", conf)
    assert m, "ssl_protocols directive is required"
    protos = set(m.group(1).split())
    assert protos == {"TLSv1.2", "TLSv1.3"}, (
        f"ssl_protocols must be exactly TLSv1.2 + TLSv1.3, got {protos!r}. "
        "TLS 1.0/1.1 are broken; SSLv3 is worse."
    )


def test_cipher_suite_is_aead_only(conf: str) -> None:
    m = re.search(r"ssl_ciphers\s+'([^']+)'", conf)
    assert m, "ssl_ciphers directive is required"
    ciphers = m.group(1)
    # Every cipher in the list must be AEAD (GCM or CHACHA20-POLY1305) —
    # no CBC-MAC, no RC4, no 3DES.
    for entry in ciphers.split(":"):
        assert "GCM" in entry or "CHACHA20-POLY1305" in entry, (
            f"ssl_ciphers contains a non-AEAD entry: {entry!r}. AEAD-only "
            "is required."
        )


def test_session_tickets_disabled(conf: str) -> None:
    # TLS session tickets pin forward secrecy to the ticket key. Disabled.
    assert re.search(r"ssl_session_tickets\s+off", conf), (
        "ssl_session_tickets must be off to preserve forward secrecy."
    )


# ── HTTP redirect and ACME passthrough ────────────────────────────────────


def test_http_redirects_to_https(conf: str) -> None:
    # The port-80 vhost must have a 301 redirect for general traffic.
    assert re.search(r"return\s+301\s+https://", conf), (
        "Port-80 block must 301 to HTTPS (docs/security/TLS_RUNBOOK.md)."
    )


def test_acme_challenge_path_is_preserved(conf: str) -> None:
    # Certbot renewal requires plaintext HTTP on /.well-known/acme-challenge/.
    assert "/.well-known/acme-challenge/" in conf, (
        "Port-80 block must keep the ACME HTTP-01 challenge path reachable."
    )


def test_healthcheck_path_bypasses_https_redirect(conf: str) -> None:
    # Docker's built-in HEALTHCHECK hits /health over HTTP; if the redirect
    # catches it, the container flaps to unhealthy. We slice from the
    # ``listen 80`` directive up to the start of the TLS vhost and look for
    # a /health location there. A single nested closing brace would fool a
    # non-ASCII-balancing regex, so we anchor on the start of the next
    # ``listen 443`` block instead.
    start = conf.find("listen 80 default_server")
    assert start != -1, "could not locate the port-80 server block"
    end = conf.find("listen 443 ssl", start)
    assert end != -1, "could not locate the TLS vhost"
    port_80_block = conf[start:end]
    assert "/health" in port_80_block, (
        "The port-80 vhost must still serve /health so the docker healthcheck "
        "works. Either keep the proxy_pass exception or update the compose "
        "healthcheck to hit HTTPS with -k."
    )


# ── Security headers on TLS vhost ─────────────────────────────────────────


def test_hsts_is_set(conf: str) -> None:
    m = re.search(
        r"Strict-Transport-Security\s+\"max-age=(\d+)", conf
    )
    assert m, "HSTS header must be set on the TLS vhost."
    max_age = int(m.group(1))
    # Minimum one year; the Chrome preload list requires this.
    assert max_age >= 31_536_000, (
        f"HSTS max-age={max_age} is too short — Chrome preload list needs "
        "at least one year (31536000s)."
    )


def test_x_content_type_options_is_nosniff(conf: str) -> None:
    assert 'X-Content-Type-Options "nosniff"' in conf


def test_frame_ancestors_are_constrained(conf: str) -> None:
    # Either X-Frame-Options or CSP frame-ancestors (or both) must restrict
    # framing. Belt-and-braces is fine.
    assert "X-Frame-Options" in conf
    assert "frame-ancestors" in conf


def test_csp_allows_wss_connections(conf: str) -> None:
    # CSP must permit wss: on connect-src or the admin WS break post-TLS.
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', conf)
    assert m, "CSP header missing"
    csp = m.group(1)
    assert "connect-src" in csp
    # Either explicit wss: or a self-scheme fallback with upgrade-insecure-requests.
    assert "wss:" in csp or "upgrade-insecure-requests" in csp


# ── Proxy forwarding preserves HTTPS awareness upstream ───────────────────


def test_x_forwarded_proto_is_set(conf: str) -> None:
    # Without this, the FastAPI app thinks every request is plaintext and
    # won't mark session cookies Secure.
    matches = re.findall(r"proxy_set_header\s+X-Forwarded-Proto\s+\$scheme", conf)
    assert len(matches) >= 3, (
        f"Expected X-Forwarded-Proto on /api, /socket.io, and /ws (and "
        f"possibly /temporal). Found {len(matches)} instances."
    )


def test_server_tokens_hidden(conf: str) -> None:
    assert re.search(r"server_tokens\s+off", conf), (
        "server_tokens off hides nginx version in error pages / headers."
    )


# ── Cert paths match the runbook ─────────────────────────────────────────


def test_ssl_cert_paths_match_mounted_volume(conf: str) -> None:
    # docker-compose.yml mounts ./config/nginx/ssl at /etc/nginx/ssl. The
    # paths in nginx.conf must match or the container fails to start.
    assert "/etc/nginx/ssl/cert.pem" in conf
    assert "/etc/nginx/ssl/key.pem" in conf


# ── Dev cert script is executable and documented ─────────────────────────


def test_dev_cert_script_exists_and_is_executable() -> None:
    script = REPO_ROOT / "config" / "nginx" / "ssl" / "generate-dev-cert.sh"
    assert script.exists(), (
        "config/nginx/ssl/generate-dev-cert.sh is required — new developers "
        "can't bring nginx up without a cert."
    )
    import os
    # Owner-executable is enough; the script runs on the host, not in the
    # nginx container.
    assert os.access(script, os.X_OK), "dev-cert script must be executable"


def test_makefile_has_dev_cert_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^dev-cert:", makefile, re.MULTILINE), (
        "Makefile must expose ``make dev-cert`` for discoverability."
    )

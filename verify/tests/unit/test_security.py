"""
Unit tests for Week 8 security hardening:
  - SecurityHeadersMiddleware
  - FieldEncryptor / encryption utilities
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from tron.api.middleware.security import SecurityHeadersMiddleware
from tron.infra.encryption import FieldEncryptor, get_encryptor, reset_encryptor

# Ensure submodule is registered on the parent package so @patch paths work
import tron.infra.secrets  # noqa: F401
import tron.infra.secrets.kmac_client  # noqa: F401


# ── SecurityHeadersMiddleware ──


class TestSecurityHeadersMiddleware:

    @pytest.fixture
    def app(self):
        """Fake ASGI app that returns a 200 with no headers."""
        async def _app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await send({"type": "http.response.body", "body": b"ok"})
        return _app

    async def test_adds_security_headers(self, app):
        mw = SecurityHeadersMiddleware(app)
        captured = {}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["headers"] = dict(message.get("headers", []))

        await mw({"type": "http", "scheme": "http"}, AsyncMock(), send)

        headers = captured["headers"]
        assert headers[b"x-content-type-options"] == b"nosniff"
        assert headers[b"x-frame-options"] == b"DENY"
        assert headers[b"x-xss-protection"] == b"1; mode=block"
        assert b"strict-transport-security" not in headers
        assert headers[b"referrer-policy"] == b"strict-origin-when-cross-origin"
        assert headers[b"permissions-policy"] == b"camera=(), microphone=(), geolocation=()"
        assert headers[b"cache-control"] == b"no-store"
        assert headers[b"content-security-policy"] == b"default-src 'self'; frame-ancestors 'none'"

    async def test_adds_hsts_on_https(self, app):
        mw = SecurityHeadersMiddleware(app)
        captured = {}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["headers"] = dict(message.get("headers", []))

        await mw({"type": "http", "scheme": "https"}, AsyncMock(), send)

        assert captured["headers"][b"strict-transport-security"] == (
            b"max-age=31536000; includeSubDomains"
        )

    async def test_skips_non_http(self, app):
        mw = SecurityHeadersMiddleware(app)
        inner_called = False

        async def fake_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        mw_ws = SecurityHeadersMiddleware(fake_app)
        await mw_ws({"type": "websocket"}, AsyncMock(), AsyncMock())
        assert inner_called

    async def test_preserves_existing_headers(self):
        async def _app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"x-custom", b"value")],
            })
            await send({"type": "http.response.body", "body": b""})

        mw = SecurityHeadersMiddleware(_app)
        captured = {}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["headers"] = message.get("headers", [])

        await mw({"type": "http"}, AsyncMock(), send)

        header_names = [h[0] for h in captured["headers"]]
        assert b"x-custom" in header_names
        assert b"x-frame-options" in header_names


# ── FieldEncryptor ──


class TestFieldEncryptor:

    @pytest.fixture
    def key(self):
        return Fernet.generate_key()

    @pytest.fixture
    def encryptor(self, key):
        return FieldEncryptor(key)

    def test_encrypt_decrypt_roundtrip(self, encryptor):
        plaintext = "sensitive data here"
        encrypted = encryptor.encrypt(plaintext)
        assert encrypted != plaintext
        assert encryptor.decrypt(encrypted) == plaintext

    def test_encrypt_empty_string(self, encryptor):
        assert encryptor.encrypt("") == ""

    def test_decrypt_empty_string(self, encryptor):
        assert encryptor.decrypt("") == ""

    def test_decrypt_invalid_token(self, encryptor):
        with pytest.raises(ValueError, match="Decryption failed"):
            encryptor.decrypt(base64.b64encode(b"garbage").decode())

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError, match="Invalid encryption key"):
            FieldEncryptor(b"not-a-valid-fernet-key")

    def test_unicode_roundtrip(self, encryptor):
        text = "Hello World!"
        assert encryptor.decrypt(encryptor.encrypt(text)) == text

    def test_rotate_key(self, key, encryptor):
        new_key = Fernet.generate_key()
        encrypted = encryptor.encrypt("rotate me")

        rotated = encryptor.rotate_key(key, new_key, encrypted)
        assert rotated != encrypted

        # Decrypt with new key
        new_enc = FieldEncryptor(new_key)
        assert new_enc.decrypt(rotated) == "rotate me"

    def test_rotate_key_invalid_old_key(self, encryptor):
        new_key = Fernet.generate_key()
        wrong_key = Fernet.generate_key()
        encrypted = encryptor.encrypt("data")

        with pytest.raises(ValueError, match="Key rotation failed"):
            encryptor.rotate_key(wrong_key, new_key, encrypted)


# ── get_encryptor ──


class TestGetEncryptor:

    def setup_method(self):
        reset_encryptor()
        # Ensure tron.infra.secrets is properly imported so patch targets resolve
        import tron.infra.secrets  # noqa: F401

    def teardown_method(self):
        reset_encryptor()

    async def test_get_encryptor_caches(self):
        key = Fernet.generate_key()
        m = AsyncMock(return_value=key.decode())
        # Patch on the module that get_encryptor imports from at call time
        import sys
        secrets_mod = sys.modules["tron.infra.secrets"]
        orig = secrets_mod.get_secret
        secrets_mod.get_secret = m
        try:
            enc1 = await get_encryptor()
            enc2 = await get_encryptor()
            assert enc1 is enc2
            m.assert_called_once()
        finally:
            secrets_mod.get_secret = orig

    async def test_get_encryptor_no_key_raises(self):
        m = AsyncMock(return_value=None)
        import sys
        secrets_mod = sys.modules["tron.infra.secrets"]
        orig = secrets_mod.get_secret
        secrets_mod.get_secret = m
        try:
            with pytest.raises(RuntimeError, match="Encryption initialization failed"):
                await get_encryptor()
        finally:
            secrets_mod.get_secret = orig

    async def test_reset_clears_cache(self):
        key = Fernet.generate_key()
        m = AsyncMock(return_value=key.decode())
        import sys
        secrets_mod = sys.modules["tron.infra.secrets"]
        orig = secrets_mod.get_secret
        secrets_mod.get_secret = m
        try:
            await get_encryptor()
            reset_encryptor()
            await get_encryptor()
            assert m.call_count == 2
        finally:
            secrets_mod.get_secret = orig

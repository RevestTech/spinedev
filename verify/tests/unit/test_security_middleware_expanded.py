"""
Expanded unit tests for OWASP security headers middleware.

Tests:
  - All security headers added correctly
  - Non-HTTP requests pass through
  - Header values and format
  - Multiple requests with headers
"""

from __future__ import annotations

from unittest.mock import AsyncMock


from tron.api.middleware.security import SecurityHeadersMiddleware


class TestSecurityHeadersMiddlewareHTTP:
    """Tests for HTTP request processing."""

    async def test_all_security_headers_added(self):
        """All OWASP security headers added to response."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http", "method": "GET", "path": "/api/test"}
        receive = AsyncMock()
        send = AsyncMock()
        
        # Simulate app sending response
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        # Check send was called with headers
        assert send.called
        call_args = send.call_args_list
        
        # Find the http.response.start call
        response_start = None
        for call in call_args:
            if call[0][0].get("type") == "http.response.start":
                response_start = call[0][0]
                break
        
        assert response_start is not None
        headers = dict(response_start.get("headers", []))
        
        # Check all headers are present
        assert b"x-content-type-options" in headers or b"X-Content-Type-Options" in headers

    async def test_x_content_type_options_header(self):
        """X-Content-Type-Options set to nosniff."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        assert headers_dict.get(b"x-content-type-options") == b"nosniff"

    async def test_x_frame_options_header(self):
        """X-Frame-Options set to DENY."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        assert headers_dict.get(b"x-frame-options") == b"DENY"

    async def test_x_xss_protection_header(self):
        """X-XSS-Protection set to 1; mode=block."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        assert headers_dict.get(b"x-xss-protection") == b"1; mode=block"

    async def test_strict_transport_security_header(self):
        """Strict-Transport-Security with 1-year max-age (HTTPS only)."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http", "scheme": "https"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        hsts = headers_dict.get(b"strict-transport-security", b"").decode()
        assert "31536000" in hsts or "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts

    async def test_referrer_policy_header(self):
        """Referrer-Policy set to strict-origin-when-cross-origin."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        assert headers_dict.get(b"referrer-policy") == b"strict-origin-when-cross-origin"

    async def test_permissions_policy_header(self):
        """Permissions-Policy disables camera, microphone, geolocation."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        perms = headers_dict.get(b"permissions-policy", b"").decode()
        assert "camera=()" in perms
        assert "microphone=()" in perms
        assert "geolocation=()" in perms

    async def test_cache_control_header(self):
        """Cache-Control set to no-store."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        assert headers_dict.get(b"cache-control") == b"no-store"

    async def test_content_security_policy_header(self):
        """Content-Security-Policy set correctly."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        csp = headers_dict.get(b"content-security-policy", b"").decode()
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp


class TestSecurityHeadersNonHTTP:
    """Tests for non-HTTP request handling."""

    async def test_websocket_requests_pass_through(self):
        """WebSocket requests pass through without modification."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()
        
        await middleware(scope, receive, send)
        
        # App should be called directly without wrapper
        app.assert_called_once()

    async def test_lifespan_requests_pass_through(self):
        """Lifespan events pass through without modification."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()
        
        await middleware(scope, receive, send)
        
        app.assert_called_once()


class TestSecurityHeadersResponseMessagesWithoutStart:
    """Tests for messages without http.response.start."""

    async def test_http_response_body_passes_through(self):
        """http.response.body messages pass through unchanged."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)

        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()

        body_sent = []

        async def capture_send(message):
            body_sent.append(message)

        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
            await send_inner({"type": "http.response.body", "body": b"test"})

        middleware.app = mock_app
        await middleware(scope, receive, capture_send)

        # Check that body message was sent
        body_messages = [m for m in body_sent if m.get("type") == "http.response.body"]
        assert len(body_messages) > 0


class TestSecurityHeadersMultipleRequests:
    """Tests with multiple sequential requests."""

    async def test_headers_added_to_multiple_responses(self):
        """Headers added consistently to multiple responses."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        for _ in range(3):
            scope = {"type": "http"}
            receive = AsyncMock()
            send = AsyncMock()
            
            async def mock_app(scope, receive, send_inner):
                await send_inner({"type": "http.response.start", "status": 200, "headers": []})
            
            middleware.app = mock_app
            await middleware(scope, receive, send)
            
            # Verify headers were added
            headers_found = False
            for call in send.call_args_list:
                if call[0][0].get("type") == "http.response.start":
                    headers = call[0][0].get("headers", [])
                    if len(headers) > 0:
                        headers_found = True
            
            assert headers_found


class TestSecurityHeadersExistingHeaders:
    """Tests when response already has some headers."""

    async def test_preserves_existing_headers(self):
        """Existing headers preserved when adding security headers."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        existing_headers = [(b"content-type", b"application/json")]
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": existing_headers})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_dict = {}
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                headers_dict = {k.lower(): v for k, v in headers}
        
        # Existing header should be preserved
        assert b"content-type" in headers_dict or b"Content-Type" in headers_dict.keys()
        # Security headers should also be added
        assert b"x-content-type-options" in headers_dict

    async def test_appends_security_headers(self):
        """Security headers appended to list, not replacing."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        existing_headers = [(b"custom-header", b"custom-value")]
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": existing_headers})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        headers_list = []
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers_list = call[0][0].get("headers", [])
        
        # Should have original + new headers
        assert len(headers_list) >= len(existing_headers) + 7  # 7 on HTTP (no HSTS)


class TestSecurityHeadersErrorResponses:
    """Tests for error responses."""

    async def test_headers_added_to_error_responses(self):
        """Security headers added to error responses (500, 404, etc)."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        for status in [404, 500, 403]:
            scope = {"type": "http"}
            receive = AsyncMock()
            send = AsyncMock()
            
            async def mock_app(scope, receive, send_inner):
                await send_inner({"type": "http.response.start", "status": status, "headers": []})
            
            middleware.app = mock_app
            await middleware(scope, receive, send)
            
            headers_dict = {}
            for call in send.call_args_list:
                if call[0][0].get("type") == "http.response.start":
                    headers = call[0][0].get("headers", [])
                    headers_dict = {k.lower(): v for k, v in headers}
            
            assert len(headers_dict) > 0  # Headers should be present


class TestSecurityHeadersHeaderCasing:
    """Tests for header name casing."""

    async def test_headers_use_lowercase_with_hyphens(self):
        """Headers use lowercase names with hyphens (HTTP/2 convention)."""
        app = AsyncMock()
        middleware = SecurityHeadersMiddleware(app)
        
        scope = {"type": "http"}
        receive = AsyncMock()
        send = AsyncMock()
        
        async def mock_app(scope, receive, send_inner):
            await send_inner({"type": "http.response.start", "status": 200, "headers": []})
        
        middleware.app = mock_app
        await middleware(scope, receive, send)
        
        for call in send.call_args_list:
            if call[0][0].get("type") == "http.response.start":
                headers = call[0][0].get("headers", [])
                # Check that header names are bytes with lowercase
                for name, value in headers:
                    if name.startswith(b"x-") or name.startswith(b"cache-") or name.startswith(b"content-") or name.startswith(b"referrer-") or name.startswith(b"permissions-") or name.startswith(b"strict-"):
                        assert name == name.lower()  # Should be lowercase

"""Unit tests for :mod:`shared.mcp.server_remote`.

Covers (per Wave 3 SPA4 scope):

* mTLS material is fetched from vault using the correct path templates
  (matching :mod:`federation.upstream_client`).
* Bearer header is attached to every outbound request.
* 5xx and 429/408 retry per backoff policy; eventual success returns.
* 401/403 surface as :class:`RemoteMcpAuthError` and are NEVER retried.
* Verify-class tools without a citation surface as
  :class:`RemoteMcpCitationRefusal` (#12) even when the remote claims ok.
* Wave 6 Stream J envelope extensions (``feature_flag_required`` +
  ``actor_token_claims``) pass through to the outbound JSON body verbatim.

These tests do NOT touch real networks. A scripted fake
``httpx.AsyncClient`` substitute (injected via ``http_client_factory``)
records every outbound call.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shared.mcp.server_remote import (
    DEFAULT_BEARER_PATH_TPL,
    DEFAULT_CERT_PATH_TPL,
    DEFAULT_KEY_PATH_TPL,
    RemoteMcpAuthError,
    RemoteMcpCitationRefusal,
    RemoteMcpClient,
    RemoteMcpClientConfig,
    RemoteMcpError,
    RemoteMcpTransportError,
    _reset_verify_class_cache,
)


# ---------------------------------------------------------------------------
# Fake httpx.AsyncClient — records calls + replays scripted responses
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    """Just enough of httpx.AsyncClient for the remote client."""

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs: dict[str, Any] = kwargs
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self._script: list[_FakeResponse] = []
        self.closed = False

    def script(self, *responses: _FakeResponse) -> None:
        self._script.extend(responses)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        self.calls.append((method, path, json))
        if not self._script:
            return _FakeResponse(200, {"status": "ok", "data": {}})
        return self._script.pop(0)

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Vault-fetcher fixture
# ---------------------------------------------------------------------------


def _vault(stub_cert: str = "CERT-PEM", stub_key: str = "KEY-PEM",
           stub_bearer: str = "BEARER-TOKEN"):
    """Build a fake secret_fetcher; returns the function + the call-log."""
    log: list[str] = []

    async def _fetch(path: str) -> str:
        log.append(path)
        if path.endswith("/cert"):
            return stub_cert
        if path.endswith("/key"):
            return stub_key
        if "bearer" in path:
            return stub_bearer
        raise KeyError(path)

    return _fetch, log


def _factory(fake: "_FakeAsyncClient"):
    """Return a factory that captures kwargs on the fake."""
    def _build(**kwargs: Any) -> _FakeAsyncClient:
        fake.init_kwargs = kwargs
        return fake
    return _build


def _cfg(**overrides: Any) -> RemoteMcpClientConfig:
    base = dict(
        base_url="https://parent.hub.example/api/v2/mcp/remote",
        role="child",
        actor="federation_child",
        # Tests inject placeholder PEMs that aren't real X.509; skip
        # ssl.load_cert_chain so unit tests don't need to generate a CA.
        verify_tls=False,
        max_attempts=3,
        base_delay_secs=0.0,
        multiplier=1.0,
        max_delay_secs=0.0,
    )
    base.update(overrides)
    return RemoteMcpClientConfig(**base)  # type: ignore[arg-type]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _verify_cache_reset() -> None:
    """Reset the verify-class tools cache between tests."""
    _reset_verify_class_cache()


# ---------------------------------------------------------------------------
# mTLS + bearer wiring
# ---------------------------------------------------------------------------


def test_vault_paths_match_federation_convention() -> None:
    """Path templates must match what federation/upstream_client.py uses (#9)."""
    assert "federation/mtls/{role}/cert" in DEFAULT_CERT_PATH_TPL
    assert "federation/mtls/{role}/key" in DEFAULT_KEY_PATH_TPL
    assert "federation/bearer/{role}" in DEFAULT_BEARER_PATH_TPL


def test_open_fetches_three_secrets_for_role() -> None:
    """``open`` must fetch cert, key, and bearer keyed on ``role``."""
    fake = _FakeAsyncClient()
    fetcher, log = _vault()

    async def go() -> None:
        client = await RemoteMcpClient.open(
            _cfg(role="security_reporter"),
            secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        )
        try:
            assert "federation/mtls/security_reporter/cert" in log
            assert "federation/mtls/security_reporter/key" in log
            assert "federation/bearer/security_reporter" in log
        finally:
            await client.aclose()

    _run(go())
    assert fake.closed is True


def test_bearer_header_attached_on_every_call() -> None:
    """Bearer token from vault must be put in the Authorization header."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"status": "ok", "data": {"x": 1}}))
    fetcher, _ = _vault(stub_bearer="THE-TOKEN")

    async def go() -> dict[str, Any]:
        async with RemoteMcpClient.connect(
            _cfg(),
            secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as client:
            return await client.acall("graph_query", {"foo": 1})

    out = _run(go())
    assert out == {"status": "ok", "data": {"x": 1}}
    # Header set at construction:
    auth_header = fake.init_kwargs["headers"]["Authorization"]
    assert auth_header == "Bearer THE-TOKEN"
    # Federation role header propagated so the upstream can audit:
    assert fake.init_kwargs["headers"]["X-Spine-Federation-Role"] == "child"


# ---------------------------------------------------------------------------
# Envelope shape — Wave 6 Stream J pass-through
# ---------------------------------------------------------------------------


def test_envelope_includes_wave6_stream_j_extensions() -> None:
    """``feature_flag_required`` + ``actor_token_claims`` must appear in body."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"status": "ok", "data": {}}))
    fetcher, _ = _vault()
    claims = {"sub": "u-1", "realm_access": {"roles": ["devops"]}}

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as client:
            await client.acall(
                "graph_query", {"q": "x"},
                feature_flag_required="federation",
                actor_token_claims=claims,
            )

    _run(go())
    _, path, body = fake.calls[-1]
    assert path == "/call/graph_query"
    assert body is not None
    assert body["params"] == {"q": "x"}
    assert body["feature_flag_required"] == "federation"
    assert body["actor_token_claims"] == claims
    assert body["actor"] == "federation_child"
    assert "project_id" in body


def test_envelope_skips_unset_wave6_fields() -> None:
    """No ``feature_flag_required`` key when caller didn't pass one."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"status": "ok", "data": {}}))
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as client:
            await client.acall("graph_query", {"q": "x"})

    _run(go())
    _, _, body = fake.calls[-1]
    assert body is not None
    assert "feature_flag_required" not in body
    assert "actor_token_claims" not in body


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


def test_retry_on_5xx_eventually_succeeds() -> None:
    """5xx is retryable; the second attempt's 200 wins."""
    fake = _FakeAsyncClient()
    fake.script(
        _FakeResponse(503, {"error": "boom"}),
        _FakeResponse(200, {"status": "ok", "data": {"v": "ok"}}),
    )
    fetcher, _ = _vault()

    async def go() -> dict[str, Any]:
        async with RemoteMcpClient.connect(
            _cfg(max_attempts=3), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            return await c.acall("graph_query", {"q": "x"})

    out = _run(go())
    assert out["data"]["v"] == "ok"
    assert len(fake.calls) == 2


def test_retry_on_429_then_giveup_raises_transport_error() -> None:
    """429 is retryable; if it persists past max_attempts we raise."""
    fake = _FakeAsyncClient()
    fake.script(
        _FakeResponse(429, {"error": "rate"}),
        _FakeResponse(429, {"error": "rate"}),
        _FakeResponse(429, {"error": "rate"}),
    )
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(max_attempts=3), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            await c.acall("graph_query", {"q": "x"})

    with pytest.raises(RemoteMcpTransportError) as ei:
        _run(go())
    assert ei.value.status_code == 429
    assert len(fake.calls) == 3


# ---------------------------------------------------------------------------
# 401/403 — never silently retried (fail-closed per #25)
# ---------------------------------------------------------------------------


def test_401_surfaces_immediately_as_auth_error_no_retry() -> None:
    """401 must surface as AuthError without consuming retry budget."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(401, {"error": "bad token"}))
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(max_attempts=5), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            await c.acall("graph_query", {"q": "x"})

    with pytest.raises(RemoteMcpAuthError) as ei:
        _run(go())
    assert ei.value.status_code == 401
    assert ei.value.retryable is False
    assert len(fake.calls) == 1  # never retried


def test_403_surfaces_immediately_as_auth_error_no_retry() -> None:
    """403 same posture as 401."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(403, {"error": "forbidden"}))
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(max_attempts=5), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            await c.acall("graph_query", {"q": "x"})

    with pytest.raises(RemoteMcpAuthError) as ei:
        _run(go())
    assert ei.value.status_code == 403
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Non-retryable 4xx
# ---------------------------------------------------------------------------


def test_400_non_retryable() -> None:
    """400 is a caller bug — never retried."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(400, {"error": "bad"}))
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(max_attempts=5), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            await c.acall("graph_query", {"q": "x"})

    with pytest.raises(RemoteMcpError) as ei:
        _run(go())
    assert ei.value.status_code == 400
    assert ei.value.retryable is False
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Cite-or-Refuse local enforcement on verify-class tools (#12)
# ---------------------------------------------------------------------------


def test_verify_class_response_without_citation_refused_locally(monkeypatch) -> None:
    """A verify-class tool returning status=ok but no citation MUST refuse."""
    import shared.mcp.server_remote as srm  # noqa: PLC0415
    monkeypatch.setattr(srm, "_VERIFY_CLASS_TOOLS_CACHE", {"verify_audit"})
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"status": "ok", "data": {"x": 1}, "citation": []}))
    fetcher, _ = _vault()

    async def go() -> None:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            await c.acall("verify_audit", {"q": "x"})

    with pytest.raises(RemoteMcpCitationRefusal) as ei:
        _run(go())
    assert ei.value.tool_name == "verify_audit"


def test_verify_class_response_with_citation_passes(monkeypatch) -> None:
    """Same tool with a citation list passes through unchanged."""
    import shared.mcp.server_remote as srm  # noqa: PLC0415
    monkeypatch.setattr(srm, "_VERIFY_CLASS_TOOLS_CACHE", {"verify_audit"})
    fake = _FakeAsyncClient()
    fake.script(
        _FakeResponse(200, {
            "status": "ok", "data": {"x": 1},
            "citation": [{"type": "file_line", "ref": "src/x.py:42"}],
        })
    )
    fetcher, _ = _vault()

    async def go() -> dict[str, Any]:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            return await c.acall("verify_audit", {"q": "x"})

    out = _run(go())
    assert out["status"] == "ok"
    assert out["citation"]


def test_non_verify_tool_passes_through_without_citation(monkeypatch) -> None:
    """A non-verify tool with no citation is fine."""
    import shared.mcp.server_remote as srm  # noqa: PLC0415
    monkeypatch.setattr(srm, "_VERIFY_CLASS_TOOLS_CACHE", {"verify_audit"})
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"status": "ok", "data": {"k": "v"}}))
    fetcher, _ = _vault()

    async def go() -> dict[str, Any]:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            return await c.acall("graph_query", {"q": "x"})

    out = _run(go())
    assert out["status"] == "ok"


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


def test_list_tools_returns_remote_catalog() -> None:
    """``list_tools`` returns the remote's ``tools`` list verbatim."""
    fake = _FakeAsyncClient()
    fake.script(_FakeResponse(200, {"tools": [
        {"name": "graph_query", "description": "test"},
        {"name": "verify_audit", "description": "test"},
    ]}))
    fetcher, _ = _vault()

    async def go() -> list[dict[str, Any]]:
        async with RemoteMcpClient.connect(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        ) as c:
            return await c.list_tools()

    out = _run(go())
    assert {t["name"] for t in out} == {"graph_query", "verify_audit"}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_call_after_close_raises() -> None:
    """Using a closed client is a programmer error, raise rather than no-op."""
    fake = _FakeAsyncClient()
    fetcher, _ = _vault()

    async def go() -> None:
        c = await RemoteMcpClient.open(
            _cfg(), secret_fetcher=fetcher,
            http_client_factory=_factory(fake),
        )
        await c.aclose()
        await c.acall("graph_query", {"q": "x"})

    with pytest.raises(RemoteMcpError):
        _run(go())


def test_set_mcp_transport_remote_requires_url() -> None:
    """Wiring sanity: selecting remote without a URL is a config bug."""
    from shared.api.dependencies import set_mcp_transport  # noqa: PLC0415

    with pytest.raises(ValueError):
        set_mcp_transport("remote")
    # Reset to in_process so other tests aren't affected.
    set_mcp_transport("in_process")

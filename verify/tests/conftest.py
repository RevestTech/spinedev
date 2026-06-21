"""
Root conftest — shared fixtures for all tests.

Provides:
  - Fake secrets dict (no keyvault needed)
  - Mock LLM client and responses
  - Mock Redis
  - Async SQLite database (in-memory)
  - FastAPI test client
  - Sample domain objects (Project, AuditRun, Finding)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


# ── Environment cleanup (remove proxy vars that break httpx in sandbox) ──


@pytest.fixture(autouse=True, scope="session")
def _clear_proxy_env():
    """Remove proxy env vars that cause SOCKS/SSL errors in sandbox."""
    proxy_vars = [
        "ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy",
        "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy",
    ]
    saved = {}
    for var in proxy_vars:
        if var in os.environ:
            saved[var] = os.environ.pop(var)
    yield
    os.environ.update(saved)


# ── Secrets ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_secrets() -> Dict[str, str]:
    """Keyvault secrets for testing — no real keys."""
    return {
        "db/password": "test-db-password",
        "redis/password": "test-redis-password",
        "auth/master-key": "tron_test_key_001",
        "auth/jwt-secret": "test-jwt-secret",
        "auth/secret-key": "test-secret-key",
        "llm/openai-key": "sk-test-openai-key",
        "llm/anthropic-key": "sk-ant-test-key",
    }


# ── LLM Mocks ────────────────────────────────────────────────────────


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "test-model"
    provider: str = "test"
    input_tokens: int = 100
    output_tokens: int = 200
    cost_usd: float = 0.001
    latency_ms: int = 50
    finish_reason: str = "stop"
    raw: Optional[Dict[str, Any]] = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


SAMPLE_SECURITY_FINDINGS_JSON = json.dumps([
    {
        "vulnerability_type": "sql_injection",
        "severity": "critical",
        "confidence": 0.95,
        "file_path": "app.py",
        "line_number": 12,
        "code_snippet": 'cursor.execute("SELECT * FROM users WHERE name = \'" + query + "\'")',
        "description": "SQL injection via string concatenation in query parameter",
        "fix_suggestion": "Use parameterized queries",
        "finding_fingerprint": "abc123def456",
        "deterministic_tool_confirmed": True,
    },
    {
        "vulnerability_type": "hardcoded_secrets",
        "severity": "high",
        "confidence": 0.9,
        "file_path": "app.py",
        "line_number": 5,
        "code_snippet": 'DATABASE_PASSWORD = "super_secret_password_123"',
        "description": "Hardcoded database password",
        "fix_suggestion": "Use environment variables or a secrets manager",
        "finding_fingerprint": "def456ghi789",
        "deterministic_tool_confirmed": False,
    },
])

SAMPLE_BUILDER_FINDINGS_JSON = json.dumps([
    {
        "vulnerability_type": "dependency_vulnerability",
        "severity": "medium",
        "confidence": 0.85,
        "file_path": "requirements.txt",
        "line_number": 3,
        "code_snippet": "flask==1.0.0",
        "description": "Outdated Flask version with known CVEs",
        "fix_suggestion": "Upgrade to flask>=2.3.0",
        "finding_fingerprint": "build001",
        "deterministic_tool_confirmed": True,
    },
])

SAMPLE_PERFORMANCE_FINDINGS_JSON = json.dumps([
    {
        "vulnerability_type": "other",
        "severity": "medium",
        "confidence": 0.80,
        "file_path": "app.py",
        "line_number": 12,
        "code_snippet": "cursor.execute(...) inside loop",
        "description": "N+1 query: SQL execution inside loop",
        "fix_suggestion": "Batch the query outside the loop",
        "finding_fingerprint": "perf001",
        "deterministic_tool_confirmed": False,
    },
])


@pytest.fixture
def mock_llm_security_response():
    """LLM response returning security findings JSON."""
    return FakeLLMResponse(content=SAMPLE_SECURITY_FINDINGS_JSON)


@pytest.fixture
def mock_llm_builder_response():
    """LLM response returning builder findings JSON."""
    return FakeLLMResponse(content=SAMPLE_BUILDER_FINDINGS_JSON)


@pytest.fixture
def mock_llm_performance_response():
    """LLM response returning performance findings JSON."""
    return FakeLLMResponse(content=SAMPLE_PERFORMANCE_FINDINGS_JSON)


@pytest.fixture
def mock_llm_empty_response():
    """LLM response with no findings."""
    return FakeLLMResponse(content="[]")


@pytest.fixture
def mock_llm_client(mock_llm_security_response):
    """Mock LLMClient that returns security findings by default."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value=mock_llm_security_response)
    client.close = AsyncMock()
    client.total_cost_usd = 0.0
    return client


# ── Redis Mock ────────────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    """Mock Redis client for pub/sub and caching tests."""
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.ping = AsyncMock(return_value=True)
    return redis


# ── Sample Data ───────────────────────────────────────────────────────


@pytest.fixture
def sample_project_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def sample_audit_run_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def sample_file_contents() -> Dict[str, str]:
    """Minimal source files for agent testing."""
    return {
        "app.py": '''\
import os, subprocess, sqlite3, pickle
from flask import Flask, request, render_template_string

app = Flask(__name__)
DATABASE_PASSWORD = "super_secret_password_123"

@app.route("/search")
def search():
    query = request.args.get("q", "")
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name = '" + query + "'")
    return str(cursor.fetchall())

@app.route("/run")
def run_command():
    cmd = request.args.get("cmd", "ls")
    output = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    return output.stdout.read()
''',
        "Dockerfile": '''\
FROM python:3.11
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "app.py"]
''',
        "requirements.txt": "flask==1.0.0\nrequests==2.20.0\n",
    }


@pytest.fixture
def sample_languages() -> List[str]:
    return ["python"]


# ── ISO Agent Fixtures ────────────────────────────────────────────────


@pytest.fixture
def iso_config_security():
    """ISOConfig for SecurityISO testing."""
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    return ISOConfig(
        specialization=ISOSpecialization.SECURITY,
        agent_id="security-iso-test",
        model_provider=LLMProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=("bandit", "semgrep"),
        prompt_template_id="security-v1",
    )


@pytest.fixture
def iso_config_builder():
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    return ISOConfig(
        specialization=ISOSpecialization.BUILDER,
        agent_id="builder-iso-test",
        model_provider=LLMProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=(),
        prompt_template_id="builder-v1",
    )


@pytest.fixture
def iso_config_performance():
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    return ISOConfig(
        specialization=ISOSpecialization.PERFORMANCE,
        agent_id="performance-iso-test",
        model_provider=LLMProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=(),
        prompt_template_id="performance-v1",
    )


@pytest.fixture
def sample_blueprint():
    """A default Blueprint for testing."""
    from tron.schemas.verification import (
        Blueprint, BlueprintScope, VerificationMethod, VulnerabilityType,
    )
    return Blueprint(
        id="test-blueprint-001",
        name="Test Security Analysis",
        description="Test blueprint",
        scope=BlueprintScope(
            file_patterns=["*.*"],
            check_types=list(VulnerabilityType),
            languages=["python"],
        ),
        tools_required=["bandit", "semgrep"],
        max_tokens=4000,
        max_duration_seconds=300,
        temperature=0.1,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


# ── FastAPI Test Client ──────────────────────────────────────────────


@pytest.fixture
async def test_app(fake_secrets):
    """FastAPI app wired for testing (no real DB, auth bypassed).

    Creates a *fresh* app via create_app() each time so that singleton
    state (middleware stack, dependency overrides, OpenTelemetry tracing)
    accumulated by earlier tests cannot leak across test boundaries.
    """
    from tron.api.main import create_app

    app = create_app()
    app.state.secrets = fake_secrets

    yield app

    app.dependency_overrides.clear()


@pytest.fixture
async def api_client(test_app):
    """Async HTTP client for API testing."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_headers(fake_secrets) -> Dict[str, str]:
    """Headers with a valid API key."""
    return {"X-API-Key": fake_secrets["auth/master-key"]}

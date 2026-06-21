"""
Application configuration.

Non-secret config comes from environment variables.
All secrets come from the container keyvault at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable application settings — non-secret values only."""

    # Database (non-secret)
    db_host: str = os.getenv("DB_HOST", "pgbouncer")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "tron")
    db_user: str = os.getenv("DB_USER", "tron")
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "10"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "5"))

    # Redis (non-secret)
    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_pool_size: int = int(os.getenv("REDIS_POOL_SIZE", "50"))

    # MinIO (non-secret)
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
    minio_secure: bool = os.getenv("MINIO_SECURE", "true").lower() == "true"
    minio_bucket: str = os.getenv("MINIO_BUCKET", "tron-artifacts")

    # Temporal
    temporal_host: str = os.getenv("TEMPORAL_HOST", "temporal:7233")
    temporal_task_queue: str = os.getenv("TEMPORAL_TASK_QUEUE", "tron-tasks")
    temporal_enabled: bool = os.getenv("TEMPORAL_ENABLED", "true").lower() == "true"

    # Stale queued audit reconciliation (POST /api/audits/reconcile-stale-queued default age)
    stale_queued_audit_minutes_default: int = int(
        os.getenv("TRON_STALE_QUEUED_AUDIT_MINUTES", "120")
    )
    # Mark long-stuck queued rows failed once at API startup (Docker-friendly cleanup for Live UI)
    reconcile_stale_queued_on_startup: bool = os.getenv(
        "TRON_RECONCILE_STALE_QUEUED_ON_STARTUP", "true"
    ).lower() in ("1", "true", "yes")

    # Auth (non-secret)
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expiration_minutes: int = int(os.getenv("JWT_EXPIRATION_MINUTES", "60"))
    # Browser admin UI session (JWT cookie from POST /api/admin/login)
    admin_session_hours: float = float(os.getenv("TRON_ADMIN_SESSION_HOURS", "8"))

    # Rate limiting
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    rate_limit_per_hour: int = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

    # App
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    workers: int = int(os.getenv("WORKERS", "1"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # After each completed audit, write TRON_POST_SCAN.md + Cursor/Claude/Codex files
    # into ``projects.agent_handoff_path`` when that column is set (worker must see the path).
    tron_agent_handoff: bool = os.getenv("TRON_AGENT_HANDOFF", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # Shown inside generated handoff markdown (browser URL for Tron admin UI).
    tron_ui_base: str = os.getenv("TRON_UI_BASE", "http://localhost:13080").rstrip("/")
    # Append a deduplicated run entry to repo-root ``tron.md`` on each handoff (never rewrites that file).
    tron_handoff_append_tron_md: bool = os.getenv(
        "TRON_HANDOFF_APPEND_TRON_MD", "true"
    ).lower() in ("1", "true", "yes")
    # Comma-separated list of absolute paths under which a project's
    # ``agent_handoff_path`` is allowed to live. EMPTY by default — with no
    # allowlist configured, the handoff writer refuses ALL paths (fail-closed).
    # Operators opt in by setting the env var to the concrete mount prefix(es)
    # the worker can safely write to, e.g.:
    #     TRON_AGENT_HANDOFF_ALLOWED_ROOTS=/var/tron/handoffs,/mnt/repos
    # See tron/services/path_safety.py for the resolution semantics.
    tron_agent_handoff_allowed_roots: str = os.getenv(
        "TRON_AGENT_HANDOFF_ALLOWED_ROOTS", ""
    )

    # WebSocket
    ws_require_auth: bool = os.getenv("WS_REQUIRE_AUTH", "true").lower() == "true"
    ws_max_connections: int = int(os.getenv("WS_MAX_CONNECTIONS", "100"))

    # LLM Circuit Breaker
    llm_circuit_breaker_threshold: int = int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "5"))
    llm_circuit_breaker_timeout: int = int(os.getenv("LLM_CIRCUIT_BREAKER_TIMEOUT", "60"))
    llm_request_timeout: int = int(os.getenv("LLM_REQUEST_TIMEOUT", "30"))
    llm_bulkhead_max_concurrent: int = int(os.getenv("LLM_BULKHEAD_MAX_CONCURRENT", "10"))

    # LLM cost dashboard + enforcement (global sum of llm_usage.cost_usd)
    tron_llm_budget_usd: float = float(os.getenv("TRON_LLM_BUDGET_USD", "500"))
    tron_llm_budget_enforce: bool = os.getenv(
        "TRON_LLM_BUDGET_ENFORCE", "true"
    ).lower() in ("1", "true", "yes")
    tron_llm_soft_cap_pct: float = float(os.getenv("TRON_LLM_SOFT_CAP_PCT", "0.85"))
    # Strict mode: if true, LLM calls FAIL when Redis is unreachable (the
    # only path that gives cross-worker race-free enforcement). Default
    # false — the process-local fallback is good enough for single-worker
    # dev and keeps the system running in degraded state in prod.
    tron_llm_budget_require_redis: bool = os.getenv(
        "TRON_LLM_BUDGET_REQUIRE_REDIS", "false"
    ).lower() in ("1", "true", "yes")

    # Observability
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    otel_enabled: bool = os.getenv("OTEL_ENABLED", "true").lower() == "true"
    otel_trace_sample_rate: float = float(os.getenv("OTEL_TRACE_SAMPLE_RATE", "1.0"))
    service_name: str = os.getenv("OTEL_SERVICE_NAME", "tron-api")

    # SEC-5: optional second sandbox pass + follow_up_recommended for top-N critical/high still unverified after Layer 3 (0=off).
    tron_deep_verify_top_n: int = int(os.getenv("TRON_DEEP_VERIFY_TOP_N", "0"))

    def cors_allowed_origins(self) -> list[str]:
        """Browser CORS allowlist. Comma-separated TRON_CORS_ORIGINS, else local dev defaults."""
        raw = os.getenv("TRON_CORS_ORIGINS", "").strip()
        if raw:
            return [x.strip() for x in raw.split(",") if x.strip()]
        return [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:13001",
            "http://localhost:13080",
            "http://127.0.0.1:13080",
            "http://127.0.0.1:13001",
        ]

    def database_url(self, password: str) -> str:
        """Build async database URL with password from keyvault."""
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    def database_url_sync(self, password: str) -> str:
        """Build sync database URL (for Alembic migrations)."""
        return f"postgresql://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    def redis_url(self, password: str) -> str:
        """Build Redis URL with password from keyvault."""
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"


# Singleton
settings = Settings()

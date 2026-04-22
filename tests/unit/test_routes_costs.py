"""
Unit tests for cost dashboard route schemas and response models.

Pure Pydantic validation — no FastAPI TestClient or database required.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from tron.api.routes.costs import (
    CostSummary,
    CostByProvider,
    CostByProject,
    DailyCost,
    CostDashboardResponse,
)


# ── CostSummary ──


class TestCostSummary:

    def test_creation_with_defaults(self):
        s = CostSummary(
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-31T23:59:59",
        )
        assert s.total_cost_usd == 0.0
        assert s.total_tokens == 0
        assert s.total_audits == 0
        assert s.avg_cost_per_audit == 0.0

    def test_creation_with_values(self):
        s = CostSummary(
            total_cost_usd=150.75,
            total_tokens=500000,
            total_audits=25,
            avg_cost_per_audit=6.03,
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-31T23:59:59",
        )
        assert s.total_cost_usd == 150.75
        assert s.total_tokens == 500000
        assert s.total_audits == 25
        assert s.avg_cost_per_audit == 6.03

    def test_period_dates_stored(self):
        s = CostSummary(
            period_start="2025-06-01T00:00:00",
            period_end="2025-06-30T23:59:59",
        )
        assert "2025-06-01" in s.period_start
        assert "2025-06-30" in s.period_end

    def test_zero_cost(self):
        s = CostSummary(
            total_cost_usd=0.0,
            period_start="2025-01-01",
            period_end="2025-01-02",
        )
        assert s.total_cost_usd == 0.0

    def test_large_token_count(self):
        s = CostSummary(
            total_tokens=10_000_000,
            period_start="2025-01-01",
            period_end="2025-01-02",
        )
        assert s.total_tokens == 10_000_000

    def test_serialization_roundtrip(self):
        s = CostSummary(
            total_cost_usd=99.99,
            total_tokens=12345,
            total_audits=5,
            avg_cost_per_audit=20.0,
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
        d = s.dict()
        s2 = CostSummary(**d)
        assert s2.total_cost_usd == s.total_cost_usd
        assert s2.total_tokens == s.total_tokens


# ── CostByProvider ──


class TestCostByProvider:

    def test_creation(self):
        c = CostByProvider(
            provider="openai",
            model="gpt-4",
            cost_usd=50.0,
            tokens=100000,
            requests=200,
        )
        assert c.provider == "openai"
        assert c.model == "gpt-4"
        assert c.cost_usd == 50.0

    def test_defaults(self):
        c = CostByProvider(provider="anthropic", model="claude-3")
        assert c.cost_usd == 0.0
        assert c.tokens == 0
        assert c.requests == 0

    def test_multiple_providers(self):
        providers = [
            CostByProvider(provider="openai", model="gpt-4", cost_usd=50.0),
            CostByProvider(provider="anthropic", model="claude-3", cost_usd=30.0),
            CostByProvider(provider="openai", model="gpt-3.5", cost_usd=5.0),
        ]
        assert len(providers) == 3
        total = sum(p.cost_usd for p in providers)
        assert total == 85.0

    def test_serialization(self):
        c = CostByProvider(
            provider="openai", model="gpt-4", cost_usd=10.5, tokens=5000, requests=10
        )
        d = c.dict()
        assert d["provider"] == "openai"
        assert d["model"] == "gpt-4"
        assert d["cost_usd"] == 10.5


# ── CostByProject ──


class TestCostByProject:

    def test_creation(self):
        c = CostByProject(
            project_id="proj-123",
            project_name="My Project",
            cost_usd=25.50,
            audit_count=10,
        )
        assert c.project_id == "proj-123"
        assert c.project_name == "My Project"
        assert c.cost_usd == 25.50
        assert c.audit_count == 10

    def test_defaults(self):
        c = CostByProject(project_id="p1", project_name="Test")
        assert c.cost_usd == 0.0
        assert c.audit_count == 0

    def test_sorting_by_cost(self):
        projects = [
            CostByProject(project_id="a", project_name="A", cost_usd=10),
            CostByProject(project_id="b", project_name="B", cost_usd=50),
            CostByProject(project_id="c", project_name="C", cost_usd=25),
        ]
        sorted_projects = sorted(projects, key=lambda p: p.cost_usd, reverse=True)
        assert sorted_projects[0].project_name == "B"
        assert sorted_projects[1].project_name == "C"
        assert sorted_projects[2].project_name == "A"

    def test_serialization(self):
        c = CostByProject(project_id="p1", project_name="Test", cost_usd=5.0)
        d = c.dict()
        assert d["project_id"] == "p1"
        assert d["project_name"] == "Test"


# ── DailyCost ──


class TestDailyCost:

    def test_creation(self):
        d = DailyCost(date="2025-01-15", cost_usd=12.50, tokens=25000, audits=3)
        assert d.date == "2025-01-15"
        assert d.cost_usd == 12.50
        assert d.tokens == 25000
        assert d.audits == 3

    def test_defaults(self):
        d = DailyCost(date="2025-01-15")
        assert d.cost_usd == 0.0
        assert d.tokens == 0
        assert d.audits == 0

    def test_weekly_trend(self):
        trend = [
            DailyCost(date=f"2025-01-{i:02d}", cost_usd=float(i))
            for i in range(1, 8)
        ]
        assert len(trend) == 7
        assert trend[0].cost_usd == 1.0
        assert trend[6].cost_usd == 7.0

    def test_serialization(self):
        d = DailyCost(date="2025-01-15", cost_usd=10.0)
        data = d.dict()
        d2 = DailyCost(**data)
        assert d2.date == d.date
        assert d2.cost_usd == d.cost_usd


# ── CostDashboardResponse ──


class TestCostDashboardResponse:

    def test_creation_minimal(self):
        summary = CostSummary(period_start="2025-01-01", period_end="2025-01-31")
        r = CostDashboardResponse(summary=summary)
        assert r.summary.total_cost_usd == 0.0
        assert r.by_provider == []
        assert r.by_project == []
        assert r.daily_trend == []
        assert r.budget_limit_usd == 500.0
        assert r.budget_used_pct == 0.0

    def test_creation_full(self):
        summary = CostSummary(
            total_cost_usd=200.0,
            total_tokens=1000000,
            total_audits=50,
            avg_cost_per_audit=4.0,
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
        r = CostDashboardResponse(
            summary=summary,
            by_provider=[
                CostByProvider(provider="openai", model="gpt-4", cost_usd=150.0),
                CostByProvider(provider="anthropic", model="claude-3", cost_usd=50.0),
            ],
            by_project=[
                CostByProject(project_id="p1", project_name="App", cost_usd=120.0),
            ],
            daily_trend=[
                DailyCost(date="2025-01-01", cost_usd=10.0),
            ],
            budget_limit_usd=1000.0,
            budget_used_pct=20.0,
        )
        assert len(r.by_provider) == 2
        assert len(r.by_project) == 1
        assert len(r.daily_trend) == 1
        assert r.budget_limit_usd == 1000.0
        assert r.budget_used_pct == 20.0

    def test_budget_pct_calculation(self):
        summary = CostSummary(
            total_cost_usd=250.0,
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
        r = CostDashboardResponse(
            summary=summary,
            budget_limit_usd=500.0,
            budget_used_pct=50.0,
        )
        assert r.budget_used_pct == 50.0

    def test_serialization_roundtrip(self):
        summary = CostSummary(
            total_cost_usd=100.0,
            period_start="2025-01-01",
            period_end="2025-01-31",
        )
        r = CostDashboardResponse(
            summary=summary,
            by_provider=[CostByProvider(provider="openai", model="gpt-4", cost_usd=100.0)],
        )
        d = r.dict()
        r2 = CostDashboardResponse(**d)
        assert r2.summary.total_cost_usd == 100.0
        assert len(r2.by_provider) == 1
        assert r2.by_provider[0].provider == "openai"

    def test_empty_lists_serialization(self):
        summary = CostSummary(period_start="2025-01-01", period_end="2025-01-31")
        r = CostDashboardResponse(summary=summary)
        d = r.dict()
        assert d["by_provider"] == []
        assert d["by_project"] == []
        assert d["daily_trend"] == []

    def test_json_serialization(self):
        summary = CostSummary(period_start="2025-01-01", period_end="2025-01-31")
        r = CostDashboardResponse(summary=summary)
        json_str = r.json()
        assert "total_cost_usd" in json_str
        assert "budget_limit_usd" in json_str

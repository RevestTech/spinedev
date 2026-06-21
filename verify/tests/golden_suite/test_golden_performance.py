"""
Golden Test Suite for PerformanceISO Agent

This module contains regression tests that verify PerformanceISO correctly
detects performance anti-patterns in code. Tests use mock LLM responses to
ensure determinism — no real LLM calls.

Performance issues tested:
- N+1 queries (ORM calls inside loops)
- Blocking I/O in async contexts
- Resource leaks (unclosed connections/files)
- Unbounded queries (SELECT * without LIMIT)
- Missing caching for expensive operations
- Inefficient algorithms
- Memory issues

Each test:
1. Constructs a mock LLM response representing correct analysis
2. Calls PerformanceISO._parse_llm_response()
3. Asserts the correct vulnerability type, severity, and description
"""

import pytest
import json
from unittest.mock import Mock

from tron.agents.performance_iso import PerformanceISO
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    VulnerabilityType,
    SeverityLevel,
)


# Fixtures

@pytest.fixture
def mock_llm_client():
    """Mock LLM client that doesn't make real API calls"""
    return Mock()


@pytest.fixture
def performance_iso(mock_llm_client):
    """Create PerformanceISO agent with mocked LLM"""
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider

    config = ISOConfig(
        specialization=ISOSpecialization.PERFORMANCE,
        agent_id="test-performance-iso",
        model_provider=LLMProvider.ANTHROPIC,
        model_name="claude-haiku-4-5-20251001",
    )

    iso = PerformanceISO(
        config=config,
        secrets={"llm/anthropic-key": "test-key"},
        llm_client=mock_llm_client,
    )
    return iso


@pytest.fixture
def test_blueprint():
    """Create a test blueprint for performance analysis"""
    return Blueprint(
        id="golden-test-perf-blueprint",
        name="Golden Suite Performance Test",
        description="Test blueprint for golden suite performance issues",
        scope=BlueprintScope(
            file_patterns=["*.py"],
            check_types=[VulnerabilityType.OTHER],
            languages=["python"],
        ),
    )


# ============================================================================
# N+1 Query Tests
# ============================================================================

class TestGoldenN1Queries:
    """Golden tests for N+1 query detection"""

    def test_n1_orm_query_in_loop(self, performance_iso, test_blueprint):
        """MUST detect ORM query inside for loop"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "models.py",
                "line_number": 12,
                "code_snippet": "for user in users:\n    orders = db.session.query(Order).filter_by(user_id=user.id).all()",
                "description": "N+1 query: executing separate database query for each user in loop",
                "fix_suggestion": "Use eager loading: User.query.options(joinedload(User.orders)).all()",
                "estimated_impact": "100x fewer database queries",
                "confidence": 0.92,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.OTHER
        assert findings[0].severity == SeverityLevel.HIGH
        assert "n_plus_one" in findings[0].description.lower()

    def test_n1_api_call_in_loop(self, performance_iso, test_blueprint):
        """MUST detect API call inside loop"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "services.py",
                "line_number": 24,
                "code_snippet": "for item in items:\n    details = requests.get(f'https://api.example.com/items/{item.id}').json()",
                "description": "N+1 API calls: making separate HTTP request for each item",
                "fix_suggestion": "Batch request: requests.post('https://api.example.com/items/batch', json={'ids': [i.id for i in items]})",
                "estimated_impact": "50x reduction in network calls",
                "confidence": 0.89,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH

    def test_n1_cache_miss_in_loop(self, performance_iso, test_blueprint):
        """MUST detect cache lookups that could be batched"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "medium",
                "file_path": "cache_service.py",
                "line_number": 35,
                "code_snippet": "for key in keys:\n    value = cache.get(key)\n    if not value:\n        value = expensive_operation(key)\n        cache.set(key, value)",
                "description": "Repeated cache operations in loop — could use mget() for bulk retrieval",
                "fix_suggestion": "Use cache.mget(keys) to fetch all keys at once",
                "estimated_impact": "10x fewer cache round-trips",
                "confidence": 0.85,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.MEDIUM


# ============================================================================
# Blocking I/O in Async Tests
# ============================================================================

class TestGoldenBlockingIO:
    """Golden tests for blocking I/O in async contexts"""

    def test_sync_http_in_async(self, performance_iso, test_blueprint):
        """MUST detect synchronous HTTP call in async function"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "handlers.py",
                "line_number": 18,
                "code_snippet": "async def fetch_data():\n    response = requests.get('https://api.example.com/data')\n    return response.json()",
                "description": "Blocking I/O: synchronous requests.get() will block entire event loop",
                "fix_suggestion": "Use async library: async with aiohttp.ClientSession() as session: response = await session.get(...)",
                "estimated_impact": "Event loop unblocked for other tasks",
                "confidence": 0.95,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH
        assert "blocking" in findings[0].description.lower()

    def test_file_io_in_async(self, performance_iso, test_blueprint):
        """MUST detect file I/O in async function"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "data.py",
                "line_number": 42,
                "code_snippet": "async def read_config():\n    with open('config.json', 'r') as f:\n        return json.load(f)",
                "description": "Blocking file I/O in async function blocks event loop",
                "fix_suggestion": "Use aiofiles: async with aiofiles.open('config.json') as f: data = json.loads(await f.read())",
                "estimated_impact": "Event loop remains responsive",
                "confidence": 0.93,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_sleep_without_async_await(self, performance_iso, test_blueprint):
        """MUST detect time.sleep() instead of asyncio.sleep()"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "retry.py",
                "line_number": 56,
                "code_snippet": "async def retry_operation():\n    time.sleep(5)  # Blocks entire loop!\n    return await operation()",
                "description": "Using time.sleep() in async function blocks event loop for 5 seconds",
                "fix_suggestion": "Use await asyncio.sleep(5) instead",
                "estimated_impact": "Event loop unblocked during sleep",
                "confidence": 0.99,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) >= 1


# ============================================================================
# Resource Leak Tests
# ============================================================================

class TestGoldenResourceLeaks:
    """Golden tests for resource leak detection"""

    def test_unclosed_database_connection(self, performance_iso, test_blueprint):
        """MUST detect unclosed database connection"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "resource_leak",
                "severity": "critical",
                "file_path": "db.py",
                "line_number": 14,
                "code_snippet": "conn = sqlite3.connect('app.db')\ndata = conn.execute('SELECT * FROM users').fetchall()\nreturn data",
                "description": "Database connection never closed — will accumulate open file handles",
                "fix_suggestion": "Use context manager: with sqlite3.connect('app.db') as conn: data = conn.execute(...).fetchall()",
                "estimated_impact": "Prevents connection exhaustion and file descriptor leaks",
                "confidence": 0.96,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL

    def test_unclosed_file_handle(self, performance_iso, test_blueprint):
        """MUST detect unclosed file handle"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "resource_leak",
                "severity": "high",
                "file_path": "logs.py",
                "line_number": 28,
                "code_snippet": "f = open('error.log', 'a')\nf.write('error occurred')",
                "description": "File handle not closed — will leak file descriptors",
                "fix_suggestion": "Use context manager: with open('error.log', 'a') as f: f.write('error occurred')",
                "estimated_impact": "Prevents file descriptor exhaustion",
                "confidence": 0.95,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_unclosed_http_session(self, performance_iso, test_blueprint):
        """MUST detect unclosed HTTP session"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "resource_leak",
                "severity": "high",
                "file_path": "client.py",
                "line_number": 41,
                "code_snippet": "session = aiohttp.ClientSession()\nresponse = await session.get('https://api.example.com/data')",
                "description": "aiohttp.ClientSession never closed — will leak TCP connections",
                "fix_suggestion": "Use context manager: async with aiohttp.ClientSession() as session: response = await session.get(...)",
                "estimated_impact": "Prevents connection pool exhaustion",
                "confidence": 0.94,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Unbounded Query Tests
# ============================================================================

class TestGoldenUnboundedQueries:
    """Golden tests for unbounded query detection"""

    def test_select_all_without_limit(self, performance_iso, test_blueprint):
        """MUST detect SELECT * without LIMIT"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "unbounded_query",
                "severity": "high",
                "file_path": "reports.py",
                "line_number": 67,
                "code_snippet": "results = db.session.query(User).all()  # Could be 1M+ rows",
                "description": "Unbounded query: SELECT * without LIMIT can load entire table into memory",
                "fix_suggestion": "Add LIMIT or paginate: db.session.query(User).limit(1000).all()",
                "estimated_impact": "Prevents OOM and query timeouts",
                "confidence": 0.88,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH

    def test_unbounded_list_growth(self, performance_iso, test_blueprint):
        """MUST detect unbounded list accumulation"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "unbounded_query",
                "severity": "medium",
                "file_path": "aggregator.py",
                "line_number": 79,
                "code_snippet": "all_items = []\nfor page in range(1, 10000):\n    all_items.extend(fetch_page(page))",
                "description": "Unbounded list accumulation with no upper bound on pages",
                "fix_suggestion": "Add a maximum page limit or use pagination instead of accumulation",
                "estimated_impact": "Prevents memory exhaustion",
                "confidence": 0.82,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Missing Cache Tests
# ============================================================================

class TestGoldenMissingCache:
    """Golden tests for missing cache detection"""

    def test_repeated_expensive_computation(self, performance_iso, test_blueprint):
        """MUST detect repeated expensive computation"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "missing_cache",
                "severity": "medium",
                "file_path": "algorithms.py",
                "line_number": 92,
                "code_snippet": "def get_user_profile(user_id):\n    user = db.query(User).get(user_id)\n    stats = compute_stats(user)  # Called every request for same user\n    return stats",
                "description": "Expensive computation repeated for same input without caching",
                "fix_suggestion": "Add caching: @cache.cached(timeout=300) or use functools.lru_cache",
                "estimated_impact": "50x faster response times",
                "confidence": 0.85,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_missing_http_cache_headers(self, performance_iso, test_blueprint):
        """MUST detect missing cache headers on HTTP responses"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "missing_cache",
                "severity": "low",
                "file_path": "views.py",
                "line_number": 103,
                "code_snippet": "@app.route('/static-content')\ndef static_content():\n    return render_template('content.html')",
                "description": "Static content served without Cache-Control headers — clients re-fetch unnecessarily",
                "fix_suggestion": "Add caching headers: response.headers['Cache-Control'] = 'public, max-age=3600'",
                "estimated_impact": "Reduces bandwidth and server load",
                "confidence": 0.80,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Inefficient Algorithm Tests
# ============================================================================

class TestGoldenInefficiencies:
    """Golden tests for inefficient algorithm detection"""

    def test_nested_loop_O_n_squared(self, performance_iso, test_blueprint):
        """MUST detect O(n²) nested loop"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "inefficient_algorithm",
                "severity": "medium",
                "file_path": "search.py",
                "line_number": 115,
                "code_snippet": "for item1 in large_list:\n    for item2 in large_list:\n        if item1.id == item2.id:\n            process(item1, item2)",
                "description": "O(n²) nested loop comparing each item with all others",
                "fix_suggestion": "Use hash lookup: item_map = {i.id: i for i in large_list}; for item1 in large_list: item2 = item_map.get(item1.id)",
                "estimated_impact": "1000x faster for large lists",
                "confidence": 0.91,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_sort_in_loop(self, performance_iso, test_blueprint):
        """MUST detect repeated sorting in loop"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "inefficient_algorithm",
                "severity": "medium",
                "file_path": "processing.py",
                "line_number": 128,
                "code_snippet": "for round_num in range(100):\n    data.sort()  # Re-sorting the same data 100 times\n    process(data[0])",
                "description": "Sorting same list repeatedly instead of once",
                "fix_suggestion": "Sort once before loop: sorted_data = sorted(data); for round_num in range(100): process(sorted_data[0])",
                "estimated_impact": "100x reduction in sorting overhead",
                "confidence": 0.93,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Memory Issue Tests
# ============================================================================

class TestGoldenMemoryIssues:
    """Golden tests for memory issue detection"""

    def test_unbounded_list_accumulation(self, performance_iso, test_blueprint):
        """MUST detect unbounded list growth"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "memory_leak",
                "severity": "critical",
                "file_path": "cache.py",
                "line_number": 141,
                "code_snippet": "cache = {}\ndef cache_result(key, value):\n    cache[key] = value  # No eviction, grows forever",
                "description": "Cache with no eviction policy grows unbounded until OOM",
                "fix_suggestion": "Use bounded cache: from functools import lru_cache or implement max-size with eviction",
                "estimated_impact": "Prevents OOM crashes",
                "confidence": 0.97,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_circular_reference_leak(self, performance_iso, test_blueprint):
        """MUST detect potential circular reference issues"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "memory_leak",
                "severity": "high",
                "file_path": "models.py",
                "line_number": 154,
                "code_snippet": "class Node:\n    def __init__(self, parent=None):\n        self.parent = parent\n        if parent:\n            parent.children.append(self)  # Circular reference if parent retains child",
                "description": "Circular parent-child references can prevent garbage collection",
                "fix_suggestion": "Use weak references: import weakref; self.parent = weakref.ref(parent)",
                "estimated_impact": "Prevents reference cycle memory leaks",
                "confidence": 0.87,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Clean Code Tests
# ============================================================================

class TestGoldenCleanPerformance:
    """Golden tests for clean code with no performance issues"""

    def test_clean_code_with_eager_loading(self, performance_iso, test_blueprint):
        """Clean code: proper eager loading returns no findings"""
        mock_response = json.dumps([])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 0

    def test_clean_async_code(self, performance_iso, test_blueprint):
        """Clean code: proper async I/O returns no findings"""
        mock_response = json.dumps([])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 0

    def test_clean_resource_management(self, performance_iso, test_blueprint):
        """Clean code: proper context managers return no findings"""
        mock_response = json.dumps([])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestGoldenPerformanceIntegration:
    """Integration tests with multiple performance issues"""

    def test_multiple_performance_issues(self, performance_iso, test_blueprint):
        """MUST handle multiple performance issues in same response"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "app.py",
                "line_number": 10,
                "code_snippet": "for user in users: orders = db.query(Order).filter_by(user_id=user.id).all()",
                "confidence": 0.92,
            },
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "app.py",
                "line_number": 20,
                "code_snippet": "async def fetch(): response = requests.get('...')",
                "confidence": 0.95,
            },
            {
                "vulnerability_type": "other",
                "performance_category": "resource_leak",
                "severity": "critical",
                "file_path": "app.py",
                "line_number": 30,
                "code_snippet": "conn = db.connect()",
                "confidence": 0.96,
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 3
        severities = [f.severity for f in findings]
        assert SeverityLevel.CRITICAL in severities
        assert severities.count(SeverityLevel.HIGH) == 2

    def test_performance_findings_capped_at_0_7(self, performance_iso, test_blueprint):
        """Performance findings must be capped at 0.7 confidence (LLM-only, no tool confirmation)"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "app.py",
                "line_number": 10,
                "code_snippet": "query in loop",
                "confidence": 0.99,  # Try to exceed cap
            }
        ])

        findings = performance_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].confidence <= 0.7

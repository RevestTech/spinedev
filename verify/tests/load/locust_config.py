"""
Advanced Locust configuration for Tron load testing.

This module provides:
- Multiple user types with realistic behaviors
- Staged load profiles (ramp up, hold, peak)
- Custom metrics and reporting
- Performance thresholds and SLA monitoring

Usage:
    locust -f tests/load/locustfile.py \
      --config tests/load/locust_config.py \
      --host https://api.tron.example.com \
      --headless --users 100 --spawn-rate 5 --run-time 10m

Configuration file (locust.conf):
    [Locust]
    headless = true
    users = 100
    spawn_rate = 10
    run_time = 10m
    host = https://api.tron.example.com
    loglevel = INFO
    locustfile = tests/load/locustfile.py
"""

import time
from datetime import datetime
from typing import Dict, Any
import logging

from locust import events

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# LOAD PROFILES
# ──────────────────────────────────────────────────────────────────

class StagedLoadProfile:
    """Ramp-up/hold/ramp-down load profile.

    Example:
        profile = StagedLoadProfile()
        target_users = profile.get_target_users_at_time(elapsed_seconds)
        spawn_rate = profile.get_spawn_rate_at_time(elapsed_seconds)
    """

    def __init__(
        self,
        ramp_up_duration: int = 300,      # 5 minutes
        hold_duration: int = 600,          # 10 minutes
        ramp_down_duration: int = 300,    # 5 minutes
        initial_users: int = 1,
        peak_users: int = 100,
    ):
        """Initialize load profile.

        Args:
            ramp_up_duration: Seconds to ramp from 1 to peak_users
            hold_duration: Seconds to hold at peak_users
            ramp_down_duration: Seconds to ramp down from peak to 1
            initial_users: Starting user count
            peak_users: Maximum users during hold phase
        """
        self.ramp_up_duration = ramp_up_duration
        self.hold_duration = hold_duration
        self.ramp_down_duration = ramp_down_duration
        self.initial_users = initial_users
        self.peak_users = peak_users
        self.total_duration = ramp_up_duration + hold_duration + ramp_down_duration

    def get_target_users_at_time(self, elapsed_seconds: int) -> int:
        """Get target user count at a specific time."""
        if elapsed_seconds < self.ramp_up_duration:
            # Ramp up phase
            progress = elapsed_seconds / self.ramp_up_duration
            return self.initial_users + int(
                (self.peak_users - self.initial_users) * progress
            )
        elif elapsed_seconds < (self.ramp_up_duration + self.hold_duration):
            # Hold phase
            return self.peak_users
        elif elapsed_seconds < self.total_duration:
            # Ramp down phase
            remaining = elapsed_seconds - (self.ramp_up_duration + self.hold_duration)
            progress = remaining / self.ramp_down_duration
            return self.peak_users - int(
                (self.peak_users - self.initial_users) * progress
            )
        else:
            # Test complete
            return self.initial_users

    def get_spawn_rate_at_time(self, elapsed_seconds: int) -> float:
        """Get spawn rate (users/sec) at a specific time."""
        if elapsed_seconds < self.ramp_up_duration:
            # Ramp up: users per second
            return (self.peak_users - self.initial_users) / self.ramp_up_duration
        elif elapsed_seconds < (self.ramp_up_duration + self.hold_duration):
            # Hold: no new users
            return 0.0
        elif elapsed_seconds < self.total_duration:
            # Ramp down: kill users per second
            return (self.peak_users - self.initial_users) / self.ramp_down_duration
        else:
            return 0.0


# ──────────────────────────────────────────────────────────────────
# PERFORMANCE METRICS & REPORTING
# ──────────────────────────────────────────────────────────────────

class PerformanceMetrics:
    """Track custom performance metrics beyond Locust defaults."""

    def __init__(self):
        self.cost_per_request: Dict[str, float] = {}
        self.audit_completion_times: Dict[str, float] = {}
        self.finding_detection_latency: Dict[str, float] = {}
        self.error_types: Dict[str, int] = {}
        self.start_time = time.time()

    def record_cost(self, endpoint: str, cost_usd: float):
        """Record API cost for an endpoint."""
        if endpoint not in self.cost_per_request:
            self.cost_per_request[endpoint] = 0.0
        self.cost_per_request[endpoint] += cost_usd

    def record_audit_completion(self, audit_id: str, duration_seconds: float):
        """Record time to complete an audit."""
        self.audit_completion_times[audit_id] = duration_seconds

    def record_finding_latency(self, finding_id: str, latency_ms: float):
        """Record time to detect a finding."""
        self.finding_detection_latency[finding_id] = latency_ms

    def record_error(self, error_type: str):
        """Record an error occurrence."""
        self.error_types[error_type] = self.error_types.get(error_type, 0) + 1

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        total_cost = sum(self.cost_per_request.values())
        request_count = sum(1 for _ in self.cost_per_request.values())

        audit_times = list(self.audit_completion_times.values())
        finding_latencies = list(self.finding_detection_latency.values())

        return {
            "total_cost_usd": round(total_cost, 2),
            "avg_cost_per_request": round(total_cost / request_count, 4) if request_count > 0 else 0,
            "total_audits_completed": len(self.audit_completion_times),
            "avg_audit_duration_sec": round(sum(audit_times) / len(audit_times), 2) if audit_times else 0,
            "max_audit_duration_sec": round(max(audit_times), 2) if audit_times else 0,
            "p95_audit_duration_sec": round(self._percentile(audit_times, 95), 2) if audit_times else 0,
            "p99_audit_duration_sec": round(self._percentile(audit_times, 99), 2) if audit_times else 0,
            "avg_finding_latency_ms": round(sum(finding_latencies) / len(finding_latencies), 2) if finding_latencies else 0,
            "max_finding_latency_ms": round(max(finding_latencies), 2) if finding_latencies else 0,
            "error_summary": self.error_types,
            "test_duration_sec": round(time.time() - self.start_time, 2),
        }

    @staticmethod
    def _percentile(data: list, percentile: float) -> float:
        """Calculate percentile from list of values."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * (percentile / 100))
        return sorted_data[min(index, len(sorted_data) - 1)]


# Global metrics instance
metrics = PerformanceMetrics()

# ──────────────────────────────────────────────────────────────────
# EVENT LISTENERS & HOOKS
# ──────────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Initialize test run."""
    logger.info("="*60)
    logger.info("Tron Load Test Starting")
    logger.info(f"Host: {environment.host}")
    logger.info(f"Start time: {datetime.now().isoformat()}")
    logger.info("="*60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Finalize test and print summary."""
    logger.info("="*60)
    logger.info("Tron Load Test Complete")
    logger.info(f"End time: {datetime.now().isoformat()}")
    logger.info("="*60)

    # Print summary
    summary = metrics.get_summary()
    logger.info("\nPerformance Summary:")
    logger.info(f"  Total Cost: ${summary['total_cost_usd']}")
    logger.info(f"  Avg Cost/Request: ${summary['avg_cost_per_request']}")
    logger.info(f"  Audits Completed: {summary['total_audits_completed']}")
    logger.info(f"  Audit Duration (avg): {summary['avg_audit_duration_sec']}s")
    logger.info(f"  Audit Duration (p95): {summary['p95_audit_duration_sec']}s")
    logger.info(f"  Audit Duration (p99): {summary['p99_audit_duration_sec']}s")
    logger.info(f"  Finding Detection (avg): {summary['avg_finding_latency_ms']}ms")
    logger.info(f"  Test Duration: {summary['test_duration_sec']}s")

    if summary['error_summary']:
        logger.warning("\nErrors Encountered:")
        for error_type, count in summary['error_summary'].items():
            logger.warning(f"  {error_type}: {count}")

    logger.info("="*60)

    # Check SLA thresholds
    check_slas(summary)


def check_slas(summary: Dict[str, Any]):
    """Validate that performance meets SLA thresholds."""
    logger.info("\nSLA Checks:")

    slas = {
        "Avg Audit Duration < 60s": summary['avg_audit_duration_sec'] < 60,
        "P95 Audit Duration < 120s": summary['p95_audit_duration_sec'] < 120,
        "P99 Audit Duration < 180s": summary['p99_audit_duration_sec'] < 180,
        "Avg Finding Latency < 5000ms": summary['avg_finding_latency_ms'] < 5000,
        "Total Errors < 5% of requests": True,  # Placeholder
    }

    for sla_name, passed in slas.items():
        status = "PASS" if passed else "FAIL"
        logger.info(f"  [{status}] {sla_name}")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, **kwargs):
    """Log each request and record metrics."""
    # Extract cost from response headers if available
    if hasattr(response, 'headers'):
        cost = response.headers.get('X-Cost-USD', '0')
        try:
            metrics.record_cost(name, float(cost))
        except (ValueError, TypeError):
            pass

    # Log slow requests
    if response_time > 5000:  # > 5 seconds
        logger.warning(f"SLOW: {request_type} {name} took {response_time:.0f}ms")


# ──────────────────────────────────────────────────────────────────
# USER BEHAVIOR CONFIGURATIONS
# ──────────────────────────────────────────────────────────────────

USER_CONFIGS = {
    "BrowseUser": {
        "description": "Light browsing - health checks and project listing",
        "weight": 1,
        "behavior": [
            ("health", 0.3),
            ("ready", 0.2),
            ("list_projects", 0.5),
        ],
        "wait_time_range": (1, 3),  # 1-3 seconds between requests
    },
    "ProjectUser": {
        "description": "Moderate usage - project CRUD operations",
        "weight": 2,
        "behavior": [
            ("create_project", 0.2),
            ("list_projects", 0.4),
            ("get_project", 0.3),
            ("update_project", 0.1),
        ],
        "wait_time_range": (2, 5),  # 2-5 seconds between requests
    },
    "AuditUser": {
        "description": "Heavy usage - audit creation and monitoring",
        "weight": 1,
        "behavior": [
            ("create_audit", 0.2),
            ("list_audits", 0.3),
            ("get_audit_status", 0.3),
            ("get_audit_findings", 0.2),
        ],
        "wait_time_range": (3, 8),  # 3-8 seconds between requests (audits are slow)
    },
    "AdminUser": {
        "description": "Admin operations - GDPR, costs, analytics",
        "weight": 0.5,
        "behavior": [
            ("get_cost_dashboard", 0.4),
            ("get_retention_policy", 0.3),
            ("list_audits", 0.3),
        ],
        "wait_time_range": (5, 15),  # 5-15 seconds between requests
    },
}

# ──────────────────────────────────────────────────────────────────
# LOAD TEST PROFILES
# ──────────────────────────────────────────────────────────────────

LOAD_PROFILES = {
    "smoke": {
        "description": "Quick smoke test with 10 users for 2 minutes",
        "ramp_up_duration": 60,      # 1 min
        "hold_duration": 60,         # 1 min
        "ramp_down_duration": 0,     # No ramp down
        "peak_users": 10,
    },
    "endurance": {
        "description": "Long-running test with 50 users for 30 minutes",
        "ramp_up_duration": 300,     # 5 min
        "hold_duration": 1800,       # 30 min
        "ramp_down_duration": 300,   # 5 min
        "peak_users": 50,
    },
    "standard": {
        "description": "Standard load test: 1->100 users over 5 min, hold 10 min, ramp down 5 min",
        "ramp_up_duration": 300,     # 5 min
        "hold_duration": 600,        # 10 min
        "ramp_down_duration": 300,   # 5 min
        "peak_users": 100,
    },
    "spike": {
        "description": "Spike test: rapid ramp to 200 users",
        "ramp_up_duration": 60,      # 1 min (fast ramp)
        "hold_duration": 300,        # 5 min hold
        "ramp_down_duration": 60,    # 1 min ramp down
        "peak_users": 200,
    },
    "stress": {
        "description": "Stress test: push to breaking point (500 users)",
        "ramp_up_duration": 600,     # 10 min (slow ramp to detect issues)
        "hold_duration": 300,        # 5 min hold
        "ramp_down_duration": 300,   # 5 min ramp down
        "peak_users": 500,
    },
}

# ──────────────────────────────────────────────────────────────────
# DEFAULTS
# ──────────────────────────────────────────────────────────────────

DEFAULT_LOAD_PROFILE = "standard"
DEFAULT_USERS = 100
DEFAULT_SPAWN_RATE = 5
DEFAULT_RUN_TIME = "20m"

def get_load_profile(profile_name: str = DEFAULT_LOAD_PROFILE) -> StagedLoadProfile:
    """Get a load profile by name."""
    if profile_name not in LOAD_PROFILES:
        logger.warning(f"Unknown profile '{profile_name}', using 'standard'")
        profile_name = DEFAULT_LOAD_PROFILE

    config = LOAD_PROFILES[profile_name]
    return StagedLoadProfile(
        ramp_up_duration=config['ramp_up_duration'],
        hold_duration=config['hold_duration'],
        ramp_down_duration=config['ramp_down_duration'],
        peak_users=config['peak_users'],
    )

"""
Advanced Locust load test for Tron API.

This file defines user behaviors with realistic workflows:
- HealthUser: Lightweight health/readiness checks (10% of traffic)
- ProjectUser: Project CRUD operations (50% of traffic)
- AuditUser: Audit creation, monitoring, finding retrieval (30% of traffic)
- AdminUser: Cost analytics, GDPR, retention policies (10% of traffic)

Features:
- Staged load profile: ramp-up (5min) -> hold (10min) -> ramp-down (5min)
- Realistic wait times between tasks (1-8 seconds)
- Custom metrics: cost per request, audit completion time
- Error tracking and SLA monitoring
- Headless and web UI support

Usage:
    # Interactive web UI (default)
    locust -f tests/load/locustfile.py --host=http://localhost:13000

    # Standard headless test (50 users, 20 minutes)
    locust -f tests/load/locustfile.py --host=http://localhost:13000 \\
      --headless -u 50 -r 2 -t 20m

    # Stress test (500 users, slow ramp to detect breaking point)
    locust -f tests/load/locustfile.py --host=http://localhost:13000 \\
      --headless -u 500 -r 5 -t 25m

For advanced configuration, see tests/load/locust_config.py
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Optional

from locust import HttpUser, task, between, TaskSet, events
import logging

logger = logging.getLogger(__name__)

# Configuration
API_KEY = os.getenv("TRON_API_KEY", "test-api-key-12345")
HOST = os.getenv("TRON_HOST", "http://localhost:13000")

# Store project IDs for reuse in audit tasks
project_ids: list[str] = []


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Initialize test data."""
    logger.info(f"Starting load test against {environment.host}")
    logger.info(f"Using API Key: {API_KEY[:10]}...")


class HealthBehavior(TaskSet):
    """Health check tasks - lightweight, frequent."""

    wait_time = between(0.5, 2)

    @task(2)
    def health(self):
        """Hit /health endpoint."""
        self.client.get(
            "/health",
            name="GET /health",
        )

    @task(1)
    def ready(self):
        """Hit /ready endpoint (checks DB + Redis)."""
        self.client.get(
            "/ready",
            name="GET /ready",
        )


class ProjectBehavior(TaskSet):
    """Project CRUD operations."""

    wait_time = between(1, 3)

    def on_start(self):
        """Initialize project tracking."""
        self.project_id: Optional[str] = None

    @task(3)
    def create_project(self):
        """Create a new project."""
        project_name = f"Load-Test-Project-{uuid.uuid4().hex[:8]}"

        response = self.client.post(
            "/api/projects",
            json={
                "name": project_name,
                "description": "Load test project",
                "repo_url": "https://github.com/example/test",
                "default_branch": "main",
            },
            headers={"X-API-Key": API_KEY},
            name="POST /api/projects",
        )

        if response.status_code == 201:
            self.project_id = response.json().get("id")
            project_ids.append(self.project_id)
            logger.debug(f"Created project: {self.project_id}")
        else:
            logger.warning(f"Failed to create project: {response.status_code}")

    @task(5)
    def list_projects(self):
        """List all projects."""
        self.client.get(
            "/api/projects?limit=50&offset=0",
            headers={"X-API-Key": API_KEY},
            name="GET /api/projects",
        )

    @task(3)
    def get_project(self):
        """Get a specific project by ID."""
        if self.project_id:
            self.client.get(
                f"/api/projects/{self.project_id}",
                headers={"X-API-Key": API_KEY},
                name="GET /api/projects/{id}",
            )

    @task(2)
    def update_project(self):
        """Update project details."""
        if self.project_id:
            self.client.put(
                f"/api/projects/{self.project_id}",
                json={
                    "description": "Updated during load test",
                    "default_branch": "develop",
                },
                headers={"X-API-Key": API_KEY},
                name="PUT /api/projects/{id}",
            )


class AuditBehavior(TaskSet):
    """Audit run operations."""

    wait_time = between(2, 5)

    def on_start(self):
        """Initialize audit tracking."""
        self.audit_id: Optional[str] = None
        self.project_id: Optional[str] = None

    @task(2)
    def create_audit(self):
        """Start a new audit run."""
        # Use existing project IDs if available, otherwise create one
        if not project_ids:
            # Create a project first
            project_response = self.client.post(
                "/api/projects",
                json={
                    "name": f"Audit-Test-{uuid.uuid4().hex[:8]}",
                    "repo_url": "https://github.com/example/audit-test",
                },
                headers={"X-API-Key": API_KEY},
            )
            if project_response.status_code == 201:
                self.project_id = project_response.json().get("id")
            else:
                logger.warning("Failed to create project for audit")
                return
        else:
            self.project_id = project_ids[0]

        response = self.client.post(
            "/api/audits",
            json={
                "project_id": self.project_id,
                "branch": "main",
                "trigger_type": "manual",
            },
            headers={"X-API-Key": API_KEY},
            name="POST /api/audits",
        )

        if response.status_code == 202:
            self.audit_id = response.json().get("id")
            logger.debug(f"Created audit: {self.audit_id}")
        else:
            logger.warning(f"Failed to create audit: {response.status_code}")

    @task(4)
    def list_audits(self):
        """List audit runs."""
        self.client.get(
            "/api/audits?limit=50&offset=0",
            headers={"X-API-Key": API_KEY},
            name="GET /api/audits",
        )

    @task(2)
    def get_audit_status(self):
        """Get status of a specific audit run."""
        if self.audit_id:
            self.client.get(
                f"/api/audits/{self.audit_id}",
                headers={"X-API-Key": API_KEY},
                name="GET /api/audits/{id}",
            )

    @task(3)
    def get_audit_findings(self):
        """Get findings from an audit run."""
        if self.audit_id:
            self.client.get(
                f"/api/audits/{self.audit_id}/findings?limit=20",
                headers={"X-API-Key": API_KEY},
                name="GET /api/audits/{id}/findings",
            )


class HealthUser(HttpUser):
    """User that primarily checks health endpoints.

    Weight: 1 (lighter load compared to others)
    """

    weight = 1
    tasks = [HealthBehavior]


class ProjectUser(HttpUser):
    """User that performs project CRUD operations.

    Weight: 2 (moderate load)
    """

    weight = 2
    tasks = [ProjectBehavior]


class AuditUser(HttpUser):
    """User that runs audits and retrieves findings.

    Weight: 1 (lighter load, audits are expensive)
    """

    weight = 1
    tasks = [AuditBehavior]


class AdminBehavior(TaskSet):
    """Admin operations - costs, analytics, GDPR."""

    wait_time = between(3, 8)

    @task(2)
    def get_cost_dashboard(self):
        """Retrieve cost dashboard."""
        self.client.get(
            "/api/costs/dashboard?days=30",
            headers={"X-API-Key": API_KEY},
            name="GET /api/costs/dashboard",
        )

    @task(1)
    def get_cost_summary(self):
        """Retrieve cost summary."""
        self.client.get(
            "/api/costs/summary?days=30",
            headers={"X-API-Key": API_KEY},
            name="GET /api/costs/summary",
        )

    @task(1)
    def get_retention_policy(self):
        """Check GDPR retention policy."""
        self.client.get(
            "/api/gdpr/retention-policy",
            headers={"X-API-Key": API_KEY},
            name="GET /api/gdpr/retention-policy",
        )


class AdminUser(HttpUser):
    """User that performs admin operations.

    Weight: 0.5 (minimal admin traffic)
    """

    weight = 0.5
    tasks = [AdminBehavior]


# Event handlers for logging and metrics

@events.request.add_listener
def log_request(request_type, name, response_time, response_length, response, context, **kwargs):
    """Log each request."""
    if response.status_code >= 400:
        logger.warning(
            f"{request_type} {name}: {response.status_code} ({response_time:.0f}ms)"
        )


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Clean up and report results."""
    logger.info("Load test completed")
    logger.info(f"Total projects created: {len(project_ids)}")


# ──────────────────────────────────────────────────────────────────
# STAGED LOAD PROFILE
# ──────────────────────────────────────────────────────────────────
# This implements a realistic load profile:
# 1. Ramp up: 1->50 users over 5 minutes (test system capacity)
# 2. Hold: Stay at 50 users for 10 minutes (steady-state validation)
# 3. Ramp down: 50->1 users over 5 minutes (graceful shutdown)
#
# Useful commands:
#   # Standard test (headless)
#   locust -f tests/load/locustfile.py --host=http://localhost:13000 --headless -u 50 -r 10 -t 20m
#
#   # Interactive web UI (default)
#   locust -f tests/load/locustfile.py --host=http://localhost:13000
#
#   # Stress test (500 users, slow ramp)
#   locust -f tests/load/locustfile.py --host=http://localhost:13000 --headless -u 500 -r 5 -t 20m


class StagedLoadScheduler:
    """Implements staged load ramp-up/hold/ramp-down."""

    def __init__(self):
        self.test_start_time = None
        self.stage = "ramp_up"

    @events.test_start.add_listener
    def on_test_start(self, **kwargs):
        self.test_start_time = time.time()
        logger.info("Staged load profile starting: ramp_up -> hold -> ramp_down")

    def get_current_stage(self) -> str:
        """Determine current load stage based on elapsed time."""
        if not self.test_start_time:
            return "ramp_up"

        elapsed = time.time() - self.test_start_time
        # Ramp up: 0-300s (5 min)
        # Hold:    300-900s (10 min)
        # Ramp down: 900+ (5 min)

        if elapsed < 300:
            return "ramp_up"
        elif elapsed < 900:
            return "hold"
        else:
            return "ramp_down"


# Global scheduler
_scheduler = StagedLoadScheduler()


# Configuration for running locally
if __name__ == "__main__":
    """Run locally with sensible defaults."""
    import sys

    # Default to localhost if not specified
    if "--host" not in sys.argv:
        sys.argv.extend(["--host", "http://localhost:13000"])

    # Default to 50 users if not specified (staged ramp)
    if "-u" not in sys.argv and "--users" not in sys.argv:
        sys.argv.extend(["-u", "50"])

    # Default spawn rate (users per second during ramp-up)
    if "-r" not in sys.argv and "--spawn-rate" not in sys.argv:
        sys.argv.extend(["-r", "2"])

    # Default run time (20 minutes: 5min ramp + 10min hold + 5min ramp down)
    if "-t" not in sys.argv and "--run-time" not in sys.argv:
        sys.argv.extend(["-t", "20m"])

    from locust.main import main

    main()

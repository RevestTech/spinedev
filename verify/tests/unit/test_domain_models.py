"""
Expanded unit tests for SQLAlchemy ORM models.

Tests:
  - Model instantiation with default values
  - Field validation (constraints)
  - Relationships
  - Timestamp handling
  - UUID generation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tron.domain.models import (
    Project, AuditRun, Finding, LLMUsage, LLMCostHourly, LLMCostDaily,
    ProjectCostLimit, CostEvent, CodeFile, FileDependency,
    FindingRelationship, Standard, _utcnow, _gen_uuid
)


def new_project(**kwargs) -> Project:
    """Helper to create a Project with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "status": "active",
        "default_branch": "main",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return Project(**defaults)


def new_audit_run(**kwargs) -> AuditRun:
    """Helper to create an AuditRun with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "project_id": _gen_uuid(),
        "workflow_id": "wf-default",
        "workflow_run_id": "run-default",
        "status": "running",
        "progress": 0,
        "findings_total": 0,
        "findings_critical": 0,
        "findings_high": 0,
        "findings_medium": 0,
        "findings_low": 0,
        "started_at": _utcnow(),
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return AuditRun(**defaults)


def new_finding(**kwargs) -> Finding:
    """Helper to create a Finding with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "audit_run_id": _gen_uuid(),
        "project_id": _gen_uuid(),
        "fingerprint": "fp-default",
        "rule_id": "rule-default",
        "file_path": "file.py",
        "severity": "medium",
        "title": "Finding",
        "description": "Description",
        "status": "open",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return Finding(**defaults)


def new_llm_usage(**kwargs) -> LLMUsage:
    """Helper to create LLMUsage with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "project_id": _gen_uuid(),
        "provider": "openai",
        "model": "gpt-4",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost_usd": Decimal("0.001"),
        "duration_ms": 500,
        "cached": False,
        "created_at": _utcnow(),
    }
    defaults.update(kwargs)
    return LLMUsage(**defaults)


def new_cost_limit(**kwargs) -> ProjectCostLimit:
    """Helper to create ProjectCostLimit with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "project_id": _gen_uuid(),
        "daily_limit_usd": Decimal("10.00"),
        "monthly_limit_usd": Decimal("100.00"),
        "action_on_limit": "warn",
        "enabled": True,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return ProjectCostLimit(**defaults)


def new_code_file(**kwargs) -> CodeFile:
    """Helper to create CodeFile with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "project_id": _gen_uuid(),
        "file_path": "file.py",
        "file_hash": "hash123",
        "first_seen_at": _utcnow(),
        "last_seen_at": _utcnow(),
    }
    defaults.update(kwargs)
    return CodeFile(**defaults)


def new_file_dependency(**kwargs) -> FileDependency:
    """Helper to create FileDependency with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "source_file_id": _gen_uuid(),
        "target_file_id": _gen_uuid(),
        "dependency_type": "import",
        "is_external": False,
        "is_circular": False,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return FileDependency(**defaults)


def new_finding_relationship(**kwargs) -> FindingRelationship:
    """Helper to create FindingRelationship with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "finding_id": _gen_uuid(),
        "related_finding_id": _gen_uuid(),
        "relationship_type": "related",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return FindingRelationship(**defaults)


def new_standard(**kwargs) -> Standard:
    """Helper to create Standard with defaults for non-persisted testing."""
    defaults = {
        "id": _gen_uuid(),
        "hierarchy_path": "path.default",
        "name": "Standard",
        "rules": {},
        "is_active": True,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    defaults.update(kwargs)
    return Standard(**defaults)


class TestProjectModel:
    """Tests for Project model."""

    def test_project_creation_with_defaults(self):
        """Project created with default values."""
        project = new_project(name="Test Project")

        assert project.id is not None
        assert project.name == "Test Project"
        assert project.status == "active"
        assert project.default_branch == "main"
        assert isinstance(project.created_at, datetime)
        assert isinstance(project.updated_at, datetime)

    def test_project_uuid_generation(self):
        """Project ID is generated UUID."""
        project1 = new_project(name="Project 1")
        project2 = new_project(name="Project 2")

        assert isinstance(project1.id, uuid.UUID)
        assert isinstance(project2.id, uuid.UUID)
        assert project1.id != project2.id

    def test_project_timestamps_in_utc(self):
        """Project timestamps are in UTC."""
        project = new_project(name="Test")

        assert project.created_at.tzinfo == timezone.utc
        assert project.updated_at.tzinfo == timezone.utc

    def test_project_description_optional(self):
        """Project description is optional."""
        project = Project(name="Test", description=None)
        assert project.description is None
        
        project2 = Project(name="Test", description="Some description")
        assert project2.description == "Some description"

    def test_project_repo_url_optional(self):
        """Project repo_url is optional."""
        project = Project(name="Test", repo_url=None)
        assert project.repo_url is None

    def test_project_created_by_optional(self):
        """Project created_by is optional UUID."""
        user_id = uuid.uuid4()
        project = Project(name="Test", created_by=user_id)
        assert project.created_by == user_id

    def test_project_deleted_at_soft_delete(self):
        """Project supports soft delete via deleted_at."""
        project = Project(name="Test", deleted_at=None)
        assert project.deleted_at is None
        
        now = datetime.now(timezone.utc)
        project.deleted_at = now
        assert project.deleted_at == now


class TestAuditRunModel:
    """Tests for AuditRun model."""

    def test_audit_run_creation(self):
        """AuditRun created with required fields."""
        project_id = uuid.uuid4()
        audit = new_audit_run(
            project_id=project_id,
            workflow_id="wf-123",
            workflow_run_id="run-456",
        )

        assert audit.id is not None
        assert audit.project_id == project_id
        assert audit.workflow_id == "wf-123"
        assert audit.status == "running"
        assert audit.progress == 0
        assert audit.findings_total == 0

    def test_audit_run_severity_counters_default_zero(self):
        """Severity counters initialized to zero."""
        audit = new_audit_run()

        assert audit.findings_critical == 0
        assert audit.findings_high == 0
        assert audit.findings_medium == 0
        assert audit.findings_low == 0

    def test_audit_run_progress_bounds(self):
        """Progress field expected to be 0-100."""
        audit = new_audit_run(progress=50)

        assert audit.progress == 50

    def test_audit_run_quality_score_decimal(self):
        """Quality score is Decimal type."""
        audit = new_audit_run(quality_score=Decimal("87.50"))

        assert audit.quality_score == Decimal("87.50")

    def test_audit_run_completed_at_optional(self):
        """Completed_at is optional, set when done."""
        audit = new_audit_run()
        assert audit.completed_at is None

        now = datetime.now(timezone.utc)
        audit.completed_at = now
        assert audit.completed_at == now

    def test_audit_run_error_fields_optional(self):
        """Error message and stack trace are optional."""
        audit = new_audit_run(error_message=None, error_stack=None)

        assert audit.error_message is None
        assert audit.error_stack is None


class TestFindingModel:
    """Tests for Finding model."""

    def test_finding_creation(self):
        """Finding created with required fields."""
        project_id = uuid.uuid4()
        audit_id = uuid.uuid4()

        finding = new_finding(
            audit_run_id=audit_id,
            project_id=project_id,
            fingerprint="fp-abc123",
            rule_id="rule-001",
            file_path="src/app.py",
            severity="critical",
            title="SQL Injection",
            description="SQL injection vulnerability found",
        )

        assert finding.id is not None
        assert finding.fingerprint == "fp-abc123"
        assert finding.rule_id == "rule-001"
        assert finding.status == "open"

    def test_finding_line_numbers_optional(self):
        """Line start/end are optional."""
        finding = new_finding(
            line_start=None,
            line_end=None,
        )

        assert finding.line_start is None
        assert finding.line_end is None

    def test_finding_code_snippet_optional(self):
        """Code snippet is optional."""
        finding = new_finding(code_snippet=None)

        assert finding.code_snippet is None

    def test_finding_resolution_tracking(self):
        """Finding tracks resolution status and details."""
        resolved_user_id = uuid.uuid4()
        finding = new_finding(
            status="resolved",
            resolution="fixed",
            resolved_by=resolved_user_id,
        )

        assert finding.status == "resolved"
        assert finding.resolution == "fixed"
        assert finding.resolved_by == resolved_user_id


class TestLLMUsageModel:
    """Tests for LLM usage tracking model."""

    def test_llm_usage_creation(self):
        """LLM usage record created."""
        usage = new_llm_usage(
            provider="openai",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=200,
            cost_usd=Decimal("0.0050"),
            duration_ms=1500,
        )

        assert usage.id is not None
        assert usage.provider == "openai"
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 200
        assert usage.cached is False

    def test_llm_usage_cache_tracking(self):
        """LLM usage tracks cache hits."""
        usage = new_llm_usage(
            provider="anthropic",
            model="claude-opus",
            prompt_tokens=500,
            completion_tokens=100,
            cost_usd=Decimal("0.0010"),
            duration_ms=800,
            cached=True,
            cache_key="key-hash-abc",
        )

        assert usage.cached is True
        assert usage.cache_key == "key-hash-abc"

    def test_llm_usage_optional_fields(self):
        """LLM usage fields like temperature, max_tokens optional."""
        usage = new_llm_usage(
            provider="openai",
            model="gpt-3.5",
            prompt_tokens=50,
            completion_tokens=50,
            cost_usd=Decimal("0.0001"),
            duration_ms=500,
            temperature=None,
            max_tokens=None,
        )

        assert usage.temperature is None
        assert usage.max_tokens is None


class TestProjectCostLimitModel:
    """Tests for project cost limits."""

    def test_cost_limit_creation(self):
        """Cost limit created with defaults."""
        project_id = uuid.uuid4()
        limit = new_cost_limit(
            project_id=project_id,
            daily_limit_usd=Decimal("10.00"),
            monthly_limit_usd=Decimal("100.00"),
        )

        assert limit.id is not None
        assert limit.project_id == project_id
        assert limit.action_on_limit == "warn"
        assert limit.enabled is True

    def test_cost_limit_thresholds(self):
        """Cost limit has warning and throttle thresholds."""
        limit = new_cost_limit(
            warning_threshold=Decimal("0.80"),
            throttle_threshold=Decimal("0.90"),
        )

        assert limit.warning_threshold == Decimal("0.80")
        assert limit.throttle_threshold == Decimal("0.90")

    def test_cost_limit_notifications(self):
        """Cost limit has optional notification config."""
        emails = ["admin@example.com", "ops@example.com"]
        limit = new_cost_limit(
            notify_email=emails,
            notify_webhook="https://example.com/webhook",
        )

        assert limit.notify_email == emails
        assert limit.notify_webhook == "https://example.com/webhook"


class TestCodeFileModel:
    """Tests for code file tracking."""

    def test_code_file_creation(self):
        """Code file record created."""
        file = new_code_file(
            file_path="src/main.py",
            file_hash="sha256-abc123",
            language="python",
        )

        assert file.id is not None
        assert file.file_path == "src/main.py"
        assert file.file_hash == "sha256-abc123"

    def test_code_file_metrics(self):
        """Code file tracks complexity and LOC."""
        file = new_code_file(
            file_path="util.py",
            file_hash="hash-1",
            lines_of_code=250,
            complexity_score=42,
        )

        assert file.lines_of_code == 250
        assert file.complexity_score == 42

    def test_code_file_dependency_counts(self):
        """Code file tracks incoming/outgoing dependencies."""
        file = new_code_file(
            file_path="api.py",
            file_hash="hash-2",
            dependency_count=5,
            dependent_count=8,
        )

        assert file.dependency_count == 5
        assert file.dependent_count == 8


class TestFileDependencyModel:
    """Tests for file dependency relationships."""

    def test_file_dependency_creation(self):
        """File dependency created."""
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()

        dep = new_file_dependency(
            source_file_id=source_id,
            target_file_id=target_id,
            dependency_type="import",
        )

        assert dep.id is not None
        assert dep.source_file_id == source_id
        assert dep.target_file_id == target_id
        assert dep.is_external is False
        assert dep.is_circular is False

    def test_file_dependency_external_flag(self):
        """File dependency marks external dependencies."""
        dep = new_file_dependency(
            dependency_type="external",
            is_external=True,
        )

        assert dep.is_external is True

    def test_file_dependency_circular_detection(self):
        """File dependency tracks circular references."""
        dep = new_file_dependency(is_circular=True)

        assert dep.is_circular is True

    def test_file_dependency_usage_count(self):
        """File dependency tracks usage frequency."""
        dep = new_file_dependency(usage_count=3)

        assert dep.usage_count == 3


class TestFindingRelationshipModel:
    """Tests for finding relationships."""

    def test_finding_relationship_creation(self):
        """Finding relationship created."""
        finding_id = uuid.uuid4()
        related_id = uuid.uuid4()

        rel = new_finding_relationship(
            finding_id=finding_id,
            related_finding_id=related_id,
            relationship_type="root_cause",
        )

        assert rel.id is not None
        assert rel.finding_id == finding_id
        assert rel.related_finding_id == related_id

    def test_finding_relationship_confidence(self):
        """Finding relationship has confidence score 0-1."""
        rel = new_finding_relationship(
            relationship_type="related",
            confidence=Decimal("0.85"),
        )

        assert rel.confidence == Decimal("0.85")

    def test_finding_relationship_metadata(self):
        """Finding relationship stores JSON metadata."""
        rel = new_finding_relationship(
            relationship_type="duplicate",
            metadata_json={"reason": "exact match", "similarity": 0.95},
        )

        assert rel.metadata_json["reason"] == "exact match"


class TestStandardModel:
    """Tests for security standards hierarchy."""

    def test_standard_creation(self):
        """Standard created with required fields."""
        standard = new_standard(
            hierarchy_path="owasp.top10.a01_injection",
            name="Injection Flaws",
            rules={"rule1": "value"},
        )

        assert standard.id is not None
        assert standard.hierarchy_path == "owasp.top10.a01_injection"
        assert standard.is_active is True

    def test_standard_hierarchy_parent(self):
        """Standard can have parent in hierarchy."""
        parent_id = uuid.uuid4()
        standard = new_standard(
            hierarchy_path="owasp.top10.a01",
            name="Level 1",
            rules={},
            parent_id=parent_id,
        )

        assert standard.parent_id == parent_id

    def test_standard_project_scope(self):
        """Standard can be project-specific."""
        project_id = uuid.uuid4()
        standard = new_standard(
            hierarchy_path="custom.rules",
            name="Custom Rules",
            rules={},
            project_id=project_id,
        )

        assert standard.project_id == project_id


class TestUtilityFunctions:
    """Tests for model utility functions."""

    def test_utcnow_returns_utc_datetime(self):
        """_utcnow returns UTC datetime."""
        now = _utcnow()
        
        assert isinstance(now, datetime)
        assert now.tzinfo == timezone.utc

    def test_gen_uuid_returns_uuid(self):
        """_gen_uuid returns new UUID."""
        id1 = _gen_uuid()
        id2 = _gen_uuid()
        
        assert isinstance(id1, uuid.UUID)
        assert isinstance(id2, uuid.UUID)
        assert id1 != id2

    def test_gen_uuid_unique_each_call(self):
        """_gen_uuid generates unique IDs."""
        ids = [_gen_uuid() for _ in range(100)]
        
        assert len(set(ids)) == 100  # All unique

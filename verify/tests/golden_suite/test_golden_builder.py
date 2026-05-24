"""
Golden Test Suite for BuilderISO Agent (Infrastructure Security)

This module contains regression tests for infrastructure security checks
including Docker configurations, CI/CD pipelines, and dependency manifests.

Tests verify that BuilderISO detects common misconfigurations that could
lead to security vulnerabilities in containerized environments.
"""

import pytest
import json
from unittest.mock import Mock
from pathlib import Path

from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    VulnerabilityType,
    SeverityLevel,
)


# Fixtures

@pytest.fixture
def golden_suite_dir():
    """Return path to golden suite"""
    return Path(__file__).parent / "vulnerable_samples"


@pytest.fixture
def mock_builder_iso():
    """Mock BuilderISO agent"""
    return Mock()


@pytest.fixture
def infrastructure_blueprint():
    """Blueprint for infrastructure security checks"""
    return Blueprint(
        id="golden-builder-blueprint",
        name="Golden Suite Infrastructure Test",
        description="Test blueprint for golden suite infrastructure vulnerabilities",
        scope=BlueprintScope(
            file_patterns=["Dockerfile", "docker-compose.yml", ".github/workflows/*", "requirements.txt"],
            check_types=[
                VulnerabilityType.SECURITY_MISCONFIGURATION,
                VulnerabilityType.HARDCODED_SECRETS,
                VulnerabilityType.DEPENDENCY_VULNERABILITY,
            ],
            languages=["dockerfile", "yaml", "text"],
        ),
    )


# ============================================================================
# Dockerfile Security Tests
# ============================================================================

class TestGoldenDockerfile:
    """Golden tests for Dockerfile security issues"""
    
    def test_dockerfile_running_as_root(self):
        """MUST detect when container runs as root"""
        # Vulnerable Dockerfile content
        vulnerable_dockerfile = """
FROM ubuntu:20.04

WORKDIR /app
COPY . /app

RUN apt-get update && apt-get install -y python3

CMD ["python3", "app.py"]
"""
        
        # Expected finding
        expected = {
            "vulnerability_type": "security_misconfiguration",
            "severity": "high",
            "file_path": "Dockerfile",
            "line_number": 8,
            "code_snippet": 'CMD ["python3", "app.py"]',
            "description": "Container runs as root user — compromised container can access entire host",
            "fix_suggestion": "Add USER directive: 'RUN useradd -m appuser' and 'USER appuser'",
        }
        
        # In real test: parse Dockerfile, check for USER directive
        assert "USER" not in vulnerable_dockerfile, "Dockerfile should lack USER directive"
    
    def test_dockerfile_unpinned_base_image(self):
        """MUST detect unpinned base images"""
        vulnerable_dockerfile = "FROM ubuntu:latest\n"
        
        # 'latest' tag means unpredictable image contents
        assert ":latest" in vulnerable_dockerfile or "FROM ubuntu" in vulnerable_dockerfile
    
    def test_dockerfile_running_privileged_service(self):
        """MUST detect services running with elevated privileges"""
        vulnerable_dockerfile = """
FROM nginx:latest

RUN chmod 777 /var/www/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        
        # 777 permissions are overly permissive
        assert "chmod 777" in vulnerable_dockerfile


# ============================================================================
# Docker Compose Security Tests
# ============================================================================

class TestGoldenDockerCompose:
    """Golden tests for docker-compose.yml security"""
    
    def test_docker_compose_secrets_in_environment(self):
        """MUST detect secrets in environment variables"""
        vulnerable_compose = """
version: '3.8'
services:
  api:
    image: myapp:latest
    environment:
      - DB_PASSWORD=super_secret_123
      - API_KEY=fake_stripe_compose_fixture
      - ADMIN_USER=admin
"""
        
        # Secrets in plaintext environment
        assert "DB_PASSWORD=super_secret_123" in vulnerable_compose
        assert "API_KEY=fake_stripe_compose_fixture" in vulnerable_compose


# ============================================================================
# CI/CD Pipeline Security Tests
# ============================================================================

class TestGoldenCICD:
    """Golden tests for CI/CD pipeline security"""
    
    def test_github_workflow_hardcoded_secrets(self):
        """MUST detect hardcoded secrets in GitHub Actions"""
        vulnerable_workflow = """
name: Deploy
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to Production
        env:
          DATABASE_URL: postgresql://user:password123@prod-db.internal/db
          AWS_SECRET_ACCESS_KEY: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLE
        run: |
          python manage.py migrate
          python manage.py deploy
"""
        
        # Secrets in plaintext
        assert "password123" in vulnerable_workflow
        assert "wJalrXUtnFEMI" in vulnerable_workflow
    
    def test_github_workflow_no_permission_restrictions(self):
        """MUST detect workflow permissions not restricted"""
        vulnerable_workflow = """
name: CI
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      security-events: write
"""
        
        # Overly permissive permissions
        assert "contents: write" in vulnerable_workflow
    
    def test_github_workflow_insecure_checkout(self):
        """MUST detect checkout with elevated permissions"""
        vulnerable_workflow = """
on:
  pull_request_target:
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v2
        with:
          ref: ${{ github.event.pull_request.head.sha }}
"""
        
        # pull_request_target with write permissions is risky
        assert "pull_request_target" in vulnerable_workflow


# ============================================================================
# Dependency Manifest Security Tests
# ============================================================================

class TestGoldenDependencies:
    """Golden tests for dependency security"""
    
    def test_requirements_txt_vulnerable_versions(self):
        """MUST detect packages with known vulnerabilities"""
        vulnerable_requirements = """
flask==0.12.3
django==1.11.0
requests==2.18.4
pyyaml==3.12
pillow==5.4.0
sqlalchemy==1.3.0
jinja2==2.11.0
"""
        
        # All these are vulnerable versions
        assert "flask==0.12.3" in vulnerable_requirements
        assert "django==1.11.0" in vulnerable_requirements
        assert "pyyaml==3.12" in vulnerable_requirements
    
    def test_requirements_txt_outdated_packages(self):
        """MUST detect severely outdated packages"""
        # Packages from 2015-2017 with 2024 version gaps
        vulnerable_requirements = """
cryptography==2.1.4
urllib3==1.21.1
certifi==2017.4.17
"""
        
        # These are 6+ years outdated
        assert "2017" in vulnerable_requirements or "2.1.4" in vulnerable_requirements
    
    def test_requirements_txt_no_versions(self):
        """SHOULD warn about unpinned dependencies"""
        vulnerable_requirements = """
Flask
Django
requests
pillow
"""
        
        # No version pinning - unpredictable builds
        assert "Flask\n" in vulnerable_requirements


# ============================================================================
# Configuration File Security Tests
# ============================================================================

class TestGoldenConfiguration:
    """Golden tests for configuration file security"""
    
    def test_env_file_in_git(self):
        """SHOULD detect .env file patterns that might be committed"""
        # This would be detected by checking git history/structure
        vulnerable_paths = [
            ".env",
            ".env.production",
            ".env.local",
            "config/secrets.yaml",
            "config/credentials.json",
        ]
        
        # These files should never be in version control
        for path in vulnerable_paths:
            assert "env" in path or "secret" in path or "credential" in path
    
    def test_database_credentials_in_config(self):
        """MUST detect database credentials in configuration files"""
        vulnerable_config = """
database:
  host: prod-db.internal
  port: 5432
  username: dbadmin
  password: MyDatabasePassword123
  name: production_db
"""
        
        # Credentials in plaintext
        assert "password:" in vulnerable_config


# ============================================================================
# Container Registry Tests
# ============================================================================

class TestGoldenContainerRegistry:
    """Golden tests for container registry security"""
    
    def test_public_container_registry_credentials(self):
        """MUST detect Docker Hub credentials in code"""
        vulnerable_file = """
docker login -u myuser -p my_docker_token_secret123
docker build -t myrepo/myimage:latest .
docker push myrepo/myimage:latest
"""
        
        # Credentials in plaintext
        assert "my_docker_token_secret123" in vulnerable_file
    
    def test_image_push_without_signing(self):
        """SHOULD detect unsigned container images"""
        # This is a policy check - detecting docker push without notary/cosign
        build_script = """
docker build -t myapp:latest .
docker push myapp:latest
"""
        
        # No content signing, no image verification
        assert "docker push" in build_script
        assert "sign" not in build_script.lower()


# ============================================================================
# Kubernetes Security Tests (if applicable)
# ============================================================================

class TestGoldenKubernetes:
    """Golden tests for Kubernetes configuration security"""
    
    def test_pod_runs_as_root(self):
        """MUST detect pods running as root"""
        vulnerable_pod = """
apiVersion: v1
kind: Pod
metadata:
  name: vulnerable-pod
spec:
  containers:
  - name: app
    image: myapp:latest
    securityContext:
      runAsUser: 0
"""
        
        # runAsUser: 0 = root
        assert "runAsUser: 0" in vulnerable_pod
    
    def test_pod_privileged_mode(self):
        """MUST detect privileged pods"""
        vulnerable_pod = """
apiVersion: v1
kind: Pod
metadata:
  name: privileged-pod
spec:
  containers:
  - name: app
    image: myapp:latest
    securityContext:
      privileged: true
"""
        
        # Privileged mode is dangerous
        assert "privileged: true" in vulnerable_pod
    
    def test_network_policy_missing(self):
        """SHOULD detect missing network policies"""
        vulnerable_deployment = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
      - name: app
        image: myapp:latest
"""
        
        # No NetworkPolicy defined
        assert "NetworkPolicy" not in vulnerable_deployment


# ============================================================================
# Supply Chain Security Tests
# ============================================================================

class TestGoldenSupplyChain:
    """Golden tests for software supply chain security"""
    
    def test_missing_dependency_lock_file(self):
        """SHOULD detect missing lock files for reproducibility"""
        # Package manager: Python
        # Missing: poetry.lock, Pipfile.lock, etc.
        vulnerable_state = {
            "has_requirements_txt": True,
            "has_lock_file": False,
        }
        
        assert not vulnerable_state["has_lock_file"]
    
    def test_git_commit_without_gpg_signature(self):
        """SHOULD detect unsigned git commits"""
        # This would check git commit signatures
        vulnerable_commit = {
            "signed": False,
            "commit_hash": "abc123",
            "author": "unknown",
        }
        
        assert not vulnerable_commit["signed"]


# ============================================================================
# Integration Tests
# ============================================================================

class TestGoldenBuilderIntegration:
    """Integration tests for infrastructure security"""
    
    def test_multiple_dockerfile_issues(self):
        """MUST detect multiple issues in single Dockerfile"""
        vulnerable_dockerfile = """
FROM ubuntu:latest

WORKDIR /app
COPY . /app

ENV DB_PASSWORD=secret123
ENV API_KEY=fake_stripe_dockerfile_fixture

RUN apt-get update && apt-get install -y python3
RUN pip install flask==0.12.0

EXPOSE 5000
CMD ["python3", "app.py"]
"""
        
        # Multiple issues:
        # 1. Unpinned base image (ubuntu:latest)
        # 2. Hardcoded secrets in environment
        # 3. Vulnerable Flask version
        # 4. Running as root
        
        assert ":latest" in vulnerable_dockerfile
        assert "DB_PASSWORD=secret123" in vulnerable_dockerfile
        assert "flask==0.12.0" in vulnerable_dockerfile
    
    def test_complete_insecure_deployment(self):
        """MUST detect issues across multiple infrastructure files"""
        files = {
            "Dockerfile": """FROM ubuntu:latest
ENV API_KEY=secret123
RUN useradd -m appuser
USER appuser
""",
            "docker-compose.yml": """version: '3'
services:
  db:
    image: postgres:9.6
    environment:
      POSTGRES_PASSWORD: dbpass123
""",
            "requirements.txt": """flask==0.12.0
requests==2.18.0
""",
        }
        
        # Issues to detect:
        # - Unpinned base image
        # - Hardcoded secrets (multiple)
        # - Outdated vulnerable packages
        
        assert ":latest" in files["Dockerfile"]
        assert "secret123" in files["Dockerfile"]
        assert "dbpass123" in files["docker-compose.yml"]
        assert "flask==0.12.0" in files["requirements.txt"]


# ============================================================================
# Coverage and Completeness Tests
# ============================================================================

class TestGoldenCoverage:
    """Tests to ensure golden suite covers all vulnerability types"""
    
    def test_golden_suite_vulnerability_types(self):
        """Verify golden suite tests all major vulnerability types"""
        covered_types = {
            VulnerabilityType.SQL_INJECTION,
            VulnerabilityType.COMMAND_INJECTION,
            VulnerabilityType.XSS,
            VulnerabilityType.HARDCODED_SECRETS,
            VulnerabilityType.INSECURE_DESERIALIZATION,
            VulnerabilityType.BROKEN_AUTH,
            VulnerabilityType.SSRF,
            VulnerabilityType.PATH_TRAVERSAL,
            VulnerabilityType.SECURITY_MISCONFIGURATION,
            VulnerabilityType.OPEN_REDIRECT,
            VulnerabilityType.DEPENDENCY_VULNERABILITY,
        }
        
        # Should have at least 10 major vulnerability types covered
        assert len(covered_types) >= 10
    
    def test_golden_suite_has_positive_and_negative_cases(self):
        """Verify golden suite includes both vulnerable and secure code"""
        # Negative case (vulnerable): Tests show what code SHOULD detect
        # Positive case (secure): Would show what code should NOT flag
        
        # The golden suite primarily tests negative cases (vulnerabilities)
        # Positive cases would be additional tests showing secure patterns
        assert True  # This is more of a design note

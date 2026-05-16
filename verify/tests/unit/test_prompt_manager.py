"""
Unit tests for the Prompt Management system.

Tests:
  - PromptManager in-memory mode (no DB)
  - Template registration and versioning
  - Template retrieval (latest and specific version)
  - Template rendering with variable substitution
  - Load defaults
  - Hash computation and drift detection
  - Variable validation
  - Error handling
"""

from __future__ import annotations

import hashlib

import pytest

from tron.prompts.defaults import DEFAULT_TEMPLATES
from tron.prompts.manager import PromptManager, RenderedPrompt
from tron.prompts.models import PromptVersion


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def pm() -> PromptManager:
    """In-memory PromptManager (no DB session)."""
    return PromptManager(session=None, cache_ttl_seconds=60)


@pytest.fixture
def pm_with_defaults() -> PromptManager:
    """In-memory PromptManager with default templates loaded."""
    mgr = PromptManager(session=None)
    mgr.load_defaults()
    return mgr


# ── Registration Tests ────────────────────────────────────────────────


class TestRegisterTemplate:

    async def test_register_basic(self, pm):
        """Register a simple template in memory."""
        version = await pm.register_template(
            template_id="test-v1",
            name="Test Template",
            system_prompt="You are a test agent.",
            user_prompt_template="Analyze: $code",
            variables=["code"],
            agent_type="test",
        )

        assert isinstance(version, PromptVersion)
        assert version.version == 1
        assert version.system_prompt == "You are a test agent."
        assert version.user_prompt_template == "Analyze: $code"
        assert version.variables == ["code"]
        assert version.content_hash  # non-empty

    async def test_register_creates_new_version(self, pm):
        """Second register with same template_id bumps version."""
        await pm.register_template(
            template_id="bump-v1",
            name="Bump Template",
            system_prompt="System v1",
            user_prompt_template="User: $input",
            variables=["input"],
            agent_type="test",
        )
        v2 = await pm.register_template(
            template_id="bump-v1",
            name="Bump Template v2",
            system_prompt="System v2",
            user_prompt_template="User: $input",
            variables=["input"],
            agent_type="test",
        )

        assert v2.version == 2
        assert v2.system_prompt == "System v2"

    async def test_register_invalid_template_id(self, pm):
        """Invalid template_id raises ValueError."""
        with pytest.raises(ValueError, match="Invalid template_id"):
            await pm.register_template(
                template_id="bad id!",
                name="Bad",
                system_prompt="sys",
                user_prompt_template="$x",
                variables=["x"],
                agent_type="test",
            )

    async def test_register_variable_mismatch(self, pm):
        """Declared variables not matching template raises ValueError."""
        with pytest.raises(ValueError, match="Variable mismatch"):
            await pm.register_template(
                template_id="mismatch-v1",
                name="Mismatch",
                system_prompt="sys",
                user_prompt_template="Analyze $code",
                variables=["code", "unused_var"],
                agent_type="test",
            )

    async def test_register_extra_used_variable(self, pm):
        """Template using undeclared variables raises ValueError."""
        with pytest.raises(ValueError, match="Variable mismatch"):
            await pm.register_template(
                template_id="extra-v1",
                name="Extra",
                system_prompt="sys",
                user_prompt_template="Analyze $code and $extra",
                variables=["code"],
                agent_type="test",
            )


# ── Retrieval Tests ──────────────────────────────────────────────────


class TestGetTemplate:

    async def test_get_latest(self, pm):
        """get_template returns latest version by default."""
        await pm.register_template(
            template_id="get-test",
            name="Get Test",
            system_prompt="v1",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )
        await pm.register_template(
            template_id="get-test",
            name="Get Test v2",
            system_prompt="v2",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )

        result = await pm.get_template("get-test")
        assert result is not None
        assert result.version == 2
        assert result.system_prompt == "v2"

    async def test_get_specific_version(self, pm):
        """get_template with version returns that specific version."""
        await pm.register_template(
            template_id="versioned",
            name="Versioned",
            system_prompt="v1-sys",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )
        await pm.register_template(
            template_id="versioned",
            name="Versioned",
            system_prompt="v2-sys",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )

        v1 = await pm.get_template("versioned", version=1)
        assert v1 is not None
        assert v1.system_prompt == "v1-sys"

    async def test_get_nonexistent(self, pm):
        """get_template for unknown template returns None."""
        result = await pm.get_template("nonexistent")
        assert result is None

    async def test_get_nonexistent_version(self, pm):
        """get_template for unknown version returns None."""
        await pm.register_template(
            template_id="one-version",
            name="One",
            system_prompt="sys",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )
        result = await pm.get_template("one-version", version=999)
        assert result is None


# ── Rendering Tests ──────────────────────────────────────────────────


class TestRender:

    async def test_render_basic(self, pm):
        """Render substitutes variables correctly."""
        await pm.register_template(
            template_id="render-test",
            name="Render Test",
            system_prompt="System",
            user_prompt_template="Code: $code\nLang: $language",
            variables=["code", "language"],
            agent_type="test",
        )

        result = await pm.render(
            "render-test",
            {"code": "print('hello')", "language": "python"},
        )

        assert isinstance(result, RenderedPrompt)
        assert result.template_id == "render-test"
        assert result.version == 1
        assert result.system_prompt == "System"
        assert "print('hello')" in result.user_prompt
        assert "python" in result.user_prompt
        assert result.content_hash  # non-empty

    async def test_render_missing_variable(self, pm):
        """Render with missing variable raises KeyError."""
        await pm.register_template(
            template_id="missing-var",
            name="Missing Var",
            system_prompt="sys",
            user_prompt_template="$required_var",
            variables=["required_var"],
            agent_type="test",
        )

        with pytest.raises(KeyError):
            await pm.render("missing-var", {})

    async def test_render_nonexistent_template(self, pm):
        """Render on unknown template returns None."""
        result = await pm.render("no-such-template", {"x": "1"})
        assert result is None

    async def test_render_extra_variables_ignored(self, pm):
        """Extra variables in the dict are safely ignored."""
        await pm.register_template(
            template_id="extra-ok",
            name="Extra OK",
            system_prompt="sys",
            user_prompt_template="$x",
            variables=["x"],
            agent_type="test",
        )

        result = await pm.render("extra-ok", {"x": "val", "y": "ignored"})
        assert result is not None
        assert result.user_prompt == "val"


# ── Listing Tests ────────────────────────────────────────────────────


class TestListTemplates:

    async def test_list_empty(self, pm):
        """List with no templates returns empty list."""
        result = await pm.list_templates()
        assert result == []

    async def test_list_all(self, pm):
        """List returns all registered templates."""
        await pm.register_template(
            template_id="a-v1", name="A", system_prompt="s",
            user_prompt_template="$x", variables=["x"], agent_type="security",
        )
        await pm.register_template(
            template_id="b-v1", name="B", system_prompt="s",
            user_prompt_template="$x", variables=["x"], agent_type="builder",
        )

        result = await pm.list_templates()
        assert len(result) == 2

    async def test_list_filtered_by_agent_type(self, pm):
        """List filtered by agent_type returns only matching."""
        await pm.register_template(
            template_id="sec-v1", name="Sec", system_prompt="s",
            user_prompt_template="$x", variables=["x"], agent_type="security",
        )
        await pm.register_template(
            template_id="build-v1", name="Build", system_prompt="s",
            user_prompt_template="$x", variables=["x"], agent_type="builder",
        )

        result = await pm.list_templates(agent_type="security")
        assert len(result) == 1
        assert result[0]["template_id"] == "sec-v1"


# ── Hashing Tests ────────────────────────────────────────────────────


class TestHashing:

    async def test_hash_deterministic(self, pm):
        """Same content produces same hash."""
        await pm.register_template(
            template_id="hash-v1", name="Hash", system_prompt="sys",
            user_prompt_template="$x", variables=["x"], agent_type="test",
        )

        hash1 = await pm.get_hash("hash-v1")
        hash2 = await pm.get_hash("hash-v1")
        assert hash1 == hash2

    async def test_hash_changes_with_content(self, pm):
        """Different content produces different hashes."""
        await pm.register_template(
            template_id="hash-a", name="A", system_prompt="system A",
            user_prompt_template="$x", variables=["x"], agent_type="test",
        )
        await pm.register_template(
            template_id="hash-b", name="B", system_prompt="system B",
            user_prompt_template="$x", variables=["x"], agent_type="test",
        )

        hash_a = await pm.get_hash("hash-a")
        hash_b = await pm.get_hash("hash-b")
        assert hash_a != hash_b

    async def test_hash_matches_sha256(self, pm):
        """Hash matches manual SHA256 computation."""
        sys_prompt = "system"
        user_template = "$x"

        await pm.register_template(
            template_id="manual-hash", name="Manual",
            system_prompt=sys_prompt,
            user_prompt_template=user_template,
            variables=["x"], agent_type="test",
        )

        expected = hashlib.sha256(
            f"{sys_prompt}\n\n{user_template}".encode("utf-8")
        ).hexdigest()

        actual = await pm.get_hash("manual-hash")
        assert actual == expected

    async def test_hash_nonexistent(self, pm):
        """get_hash for unknown template returns None."""
        result = await pm.get_hash("nope")
        assert result is None


# ── Defaults Tests ───────────────────────────────────────────────────


class TestLoadDefaults:

    def test_load_defaults(self, pm_with_defaults):
        """load_defaults populates all DEFAULT_TEMPLATES."""
        assert len(pm_with_defaults._in_memory_templates) == len(DEFAULT_TEMPLATES)

    async def test_default_templates_renderable(self, pm_with_defaults):
        """All default templates can be retrieved."""
        for template_id in DEFAULT_TEMPLATES:
            result = await pm_with_defaults.get_template(template_id)
            assert result is not None, f"Template {template_id} not found"
            assert result.version == 1

    async def test_security_iso_template_has_variables(self, pm_with_defaults):
        """SecurityISO template has expected variables."""
        tmpl = await pm_with_defaults.get_template("security-iso-v1")
        assert tmpl is not None
        assert "blueprint_name" in tmpl.variables
        assert "source_code" in tmpl.variables

    async def test_builder_iso_template_has_variables(self, pm_with_defaults):
        """BuilderISO template has expected variables."""
        tmpl = await pm_with_defaults.get_template("builder-iso-v1")
        assert tmpl is not None
        assert "build_files" in tmpl.variables

    async def test_performance_iso_template_has_variables(self, pm_with_defaults):
        """PerformanceISO template has expected variables."""
        tmpl = await pm_with_defaults.get_template("performance-iso-v1")
        assert tmpl is not None
        assert "source_code" in tmpl.variables


# ── CachedTemplate Tests ────────────────────────────────────────────


class TestCachedTemplate:

    def test_is_expired(self):
        """CachedTemplate.is_expired works with TTL."""
        import time
        from tron.prompts.manager import CachedTemplate

        ct = CachedTemplate(
            system_prompt="s",
            user_prompt_template="$x",
            variables=["x"],
            content_hash="abc",
            cached_at=time.time() - 100,
        )

        assert ct.is_expired(ttl_seconds=50)
        assert not ct.is_expired(ttl_seconds=200)

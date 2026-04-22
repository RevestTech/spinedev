"""
Prompt Management System for Tron.

Provides versioned prompt template storage, retrieval, and rendering with
support for both in-memory and database backends. Enables prompt drift
detection and version management.

Architecture:
- Templates are identified by unique template_id slugs (e.g., "security-iso-v1")
- Each template update creates a new immutable version
- Variables use Python string.Template style ($variable substitution)
- Optional in-memory cache with TTL for hot templates
- SHA256 hashing of template content for drift detection
"""

from __future__ import annotations

import hashlib
import logging
import string
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.prompts.defaults import DEFAULT_TEMPLATES
from tron.prompts.models import PromptTemplate, PromptVersion

logger = logging.getLogger(__name__)


# ── Type Definitions ───────────────────────────────────────────────────


@dataclass
class RenderedPrompt:
    """Result of rendering a template with variables."""

    template_id: str
    version: int
    system_prompt: str
    user_prompt: str
    content_hash: str


@dataclass
class CachedTemplate:
    """In-memory cache entry with TTL."""

    system_prompt: str
    user_prompt_template: str
    variables: List[str]
    content_hash: str
    cached_at: float

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry has expired."""
        return (time.time() - self.cached_at) > ttl_seconds


# ── Prompt Manager ────────────────────────────────────────────────────


class PromptManager:
    """Central system for managing versioned prompt templates.

    Features:
    - Register/update templates with automatic version management
    - Retrieve templates (latest or specific version)
    - Render templates with variable substitution
    - SHA256 hashing for drift detection
    - In-memory caching with configurable TTL
    - Support for in-memory-only (testing) or database-backed operation

    Usage:
        # In-memory mode (testing)
        pm = PromptManager()
        pm.load_defaults()
        rendered = pm.render("security-iso-v1", {"blueprint_name": "Test"})

        # Database-backed mode (production)
        pm = PromptManager(session=db_session)
        await pm.register_template(
            template_id="security-iso-v2",
            name="SecurityISO v2",
            system_prompt="...",
            user_prompt_template="...",
            variables=["var1", "var2"],
            agent_type="security"
        )
    """

    def __init__(
        self,
        session: Optional[AsyncSession] = None,
        cache_ttl_seconds: int = 3600,
    ):
        """Initialize the Prompt Manager.

        Args:
            session: Optional AsyncSession for database operations. If None,
                    operates in in-memory only mode.
            cache_ttl_seconds: TTL for in-memory template cache (default: 1 hour).
        """
        self.session = session
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, CachedTemplate] = {}
        self._in_memory_templates: Dict[str, Dict[str, Any]] = {}

    # ── Template Registration ──────────────────────────────────────────

    async def register_template(
        self,
        template_id: str,
        name: str,
        system_prompt: str,
        user_prompt_template: str,
        variables: List[str],
        agent_type: str,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> PromptVersion:
        """Register or update a prompt template.

        Creates a new version if the template already exists. Old versions
        are retained for drift detection and audit trails.

        Args:
            template_id: Unique slug identifier (e.g., "security-iso-v1")
            name: Human-readable name
            system_prompt: System-level prompt (agent persona/rules)
            user_prompt_template: User prompt template with $variables
            variables: List of variable names used in user_prompt_template
            agent_type: Agent specialization (security, builder, performance, etc.)
            description: Optional description
            created_by: Optional identifier of who created this version

        Returns:
            PromptVersion: The newly created version record

        Raises:
            ValueError: If the template_id is invalid or variables don't match
        """
        if not template_id or not template_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid template_id: {template_id}")

        # Validate variables are referenced in the template
        self._validate_variables(user_prompt_template, variables)

        content_hash = self._compute_hash(system_prompt, user_prompt_template)

        # In-memory mode: store in dict
        if self.session is None:
            return self._register_in_memory(
                template_id=template_id,
                name=name,
                description=description,
                agent_type=agent_type,
                system_prompt=system_prompt,
                user_prompt_template=user_prompt_template,
                variables=variables,
                content_hash=content_hash,
                created_by=created_by,
            )

        # Database mode: use SQLAlchemy ORM
        return await self._register_in_db(
            template_id=template_id,
            name=name,
            description=description,
            agent_type=agent_type,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            variables=variables,
            content_hash=content_hash,
            created_by=created_by,
        )

    def _register_in_memory(
        self,
        template_id: str,
        name: str,
        description: Optional[str],
        agent_type: str,
        system_prompt: str,
        user_prompt_template: str,
        variables: List[str],
        content_hash: str,
        created_by: Optional[str],
    ) -> PromptVersion:
        """Register a template in in-memory storage."""
        # Get current version or initialize
        current_version = 1
        if template_id in self._in_memory_templates:
            current_version = self._in_memory_templates[template_id].get("current_version", 0) + 1
            self._in_memory_templates[template_id]["current_version"] = current_version
        else:
            self._in_memory_templates[template_id] = {
                "name": name,
                "description": description,
                "agent_type": agent_type,
                "current_version": current_version,
                "versions": [],
            }

        version_record = PromptVersion(
            template_id=None,  # In-memory only
            version=current_version,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            variables=variables,
            content_hash=content_hash,
            created_by=created_by,
        )

        self._in_memory_templates[template_id]["versions"].append(version_record)

        logger.info(
            "Registered template %s version %d (hash: %s)",
            template_id, current_version, content_hash[:8]
        )

        return version_record

    async def _register_in_db(
        self,
        template_id: str,
        name: str,
        description: Optional[str],
        agent_type: str,
        system_prompt: str,
        user_prompt_template: str,
        variables: List[str],
        content_hash: str,
        created_by: Optional[str],
    ) -> PromptVersion:
        """Register a template in the database."""
        # Find or create the template record
        stmt = select(PromptTemplate).where(
            PromptTemplate.template_id == template_id
        )
        result = await self.session.execute(stmt)
        template = result.scalars().first()

        if template is None:
            template = PromptTemplate(
                template_id=template_id,
                name=name,
                description=description,
                agent_type=agent_type,
                current_version=1,
            )
            self.session.add(template)
            await self.session.flush()
            current_version = 1
        else:
            current_version = template.current_version + 1
            template.current_version = current_version
            template.name = name
            if description:
                template.description = description

        # Create the new version record
        version = PromptVersion(
            template_id=template.id,
            version=current_version,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            variables=variables,
            content_hash=content_hash,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.commit()

        # Clear cache for this template
        self._cache.pop(f"{template_id}:latest", None)
        self._cache.pop(f"{template_id}:{current_version}", None)

        logger.info(
            "Registered template %s version %d in DB (hash: %s)",
            template_id, current_version, content_hash[:8]
        )

        return version

    # ── Template Retrieval ────────────────────────────────────────────

    async def get_template(
        self,
        template_id: str,
        version: Optional[int] = None,
    ) -> Optional[PromptVersion]:
        """Retrieve a template (latest or specific version).

        Args:
            template_id: Template identifier
            version: Specific version to retrieve. If None, returns latest.

        Returns:
            PromptVersion if found, None otherwise
        """
        if self.session is None:
            return self._get_in_memory(template_id, version)
        return await self._get_from_db(template_id, version)

    def _get_in_memory(
        self,
        template_id: str,
        version: Optional[int],
    ) -> Optional[PromptVersion]:
        """Retrieve an in-memory template."""
        if template_id not in self._in_memory_templates:
            return None

        template_data = self._in_memory_templates[template_id]
        versions = template_data.get("versions", [])

        if not versions:
            return None

        if version is None:
            return versions[-1]  # Latest

        for v in versions:
            if v.version == version:
                return v

        return None

    async def _get_from_db(
        self,
        template_id: str,
        version: Optional[int],
    ) -> Optional[PromptVersion]:
        """Retrieve a template from the database."""
        # Query for the template record first
        stmt = select(PromptTemplate).where(
            PromptTemplate.template_id == template_id
        )
        result = await self.session.execute(stmt)
        template = result.scalars().first()

        if template is None:
            return None

        # Query for the version
        if version is None:
            version = template.current_version

        version_stmt = select(PromptVersion).where(
            (PromptVersion.template_id == template.id) &
            (PromptVersion.version == version)
        )
        version_result = await self.session.execute(version_stmt)
        return version_result.scalars().first()

    # ── Template Rendering ────────────────────────────────────────────

    async def render(
        self,
        template_id: str,
        variables: Dict[str, str],
        version: Optional[int] = None,
    ) -> Optional[RenderedPrompt]:
        """Render a template with variables.

        Uses Python string.Template for safe, simple variable substitution.
        Missing variables raise an exception; extra variables are ignored.

        Args:
            template_id: Template identifier
            variables: Dict of variable values
            version: Specific version to render. If None, uses latest.

        Returns:
            RenderedPrompt with rendered system and user prompts, or None if
            template not found

        Raises:
            KeyError: If a required variable is missing
        """
        template = await self.get_template(template_id, version)
        if template is None:
            logger.warning("Template not found: %s", template_id)
            return None

        try:
            tmpl = string.Template(template.user_prompt_template)
            rendered_user = tmpl.substitute(variables)
        except KeyError as e:
            logger.error("Missing variable in template %s: %s", template_id, e)
            raise

        return RenderedPrompt(
            template_id=template_id,
            version=template.version,
            system_prompt=template.system_prompt,
            user_prompt=rendered_user,
            content_hash=template.content_hash,
        )

    # ── Template Listing ───────────────────────────────────────────────

    async def list_templates(
        self,
        agent_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available templates, optionally filtered by agent type.

        Args:
            agent_type: If provided, only return templates for this agent type

        Returns:
            List of template metadata dicts
        """
        if self.session is None:
            return self._list_in_memory(agent_type)
        return await self._list_from_db(agent_type)

    def _list_in_memory(self, agent_type: Optional[str]) -> List[Dict[str, Any]]:
        """List in-memory templates."""
        result = []
        for template_id, data in self._in_memory_templates.items():
            if agent_type and data.get("agent_type") != agent_type:
                continue

            result.append({
                "template_id": template_id,
                "name": data.get("name"),
                "description": data.get("description"),
                "agent_type": data.get("agent_type"),
                "current_version": data.get("current_version"),
            })

        return result

    async def _list_from_db(self, agent_type: Optional[str]) -> List[Dict[str, Any]]:
        """List templates from the database."""
        stmt = select(PromptTemplate)
        if agent_type:
            stmt = stmt.where(PromptTemplate.agent_type == agent_type)

        result = await self.session.execute(stmt)
        templates = result.scalars().all()

        return [
            {
                "template_id": t.template_id,
                "name": t.name,
                "description": t.description,
                "agent_type": t.agent_type,
                "current_version": t.current_version,
            }
            for t in templates
        ]

    # ── Hash Management ────────────────────────────────────────────────

    async def get_hash(
        self,
        template_id: str,
        version: Optional[int] = None,
    ) -> Optional[str]:
        """Get SHA256 hash of a template's content.

        Useful for drift detection — comparing stored hash with computed
        hash of current SYSTEM_PROMPT to detect manual changes.

        Args:
            template_id: Template identifier
            version: Specific version. If None, uses latest.

        Returns:
            SHA256 hash (hex string) or None if template not found
        """
        template = await self.get_template(template_id, version)
        if template is None:
            return None
        return template.content_hash

    @staticmethod
    def _compute_hash(system_prompt: str, user_prompt_template: str) -> str:
        """Compute SHA256 hash of template content."""
        content = f"{system_prompt}\n\n{user_prompt_template}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # ── Utilities ──────────────────────────────────────────────────────

    def load_defaults(self) -> None:
        """Load default templates into in-memory storage.

        Useful for testing and bootstrapping. In production, use
        register_template or a migration script to seed the database.
        """
        if self.session is not None:
            logger.warning(
                "load_defaults() is intended for in-memory mode only. "
                "In database mode, use a migration script or explicit registration."
            )

        for template_id, template_data in DEFAULT_TEMPLATES.items():
            self._register_in_memory(
                template_id=template_id,
                name=template_data["name"],
                description=template_data.get("description"),
                agent_type=template_data["agent_type"],
                system_prompt=template_data["system_prompt"],
                user_prompt_template=template_data["user_prompt_template"],
                variables=template_data["variables"],
                content_hash=self._compute_hash(
                    template_data["system_prompt"],
                    template_data["user_prompt_template"],
                ),
                created_by=None,
            )

        logger.info(
            "Loaded %d default templates into in-memory storage",
            len(DEFAULT_TEMPLATES)
        )

    @staticmethod
    def _validate_variables(
        user_prompt_template: str,
        variables: List[str],
    ) -> None:
        """Validate that all declared variables are used in the template.

        Args:
            user_prompt_template: Template string with $variables
            variables: List of variable names

        Raises:
            ValueError: If there's a mismatch
        """
        # Extract variable names using the Template pattern regex.
        # get_identifiers() is only available in Python 3.11+, so we use
        # the pattern attribute directly for 3.10 compatibility.
        tmpl = string.Template(user_prompt_template)
        used_vars: set[str] = set()
        for match in tmpl.pattern.finditer(user_prompt_template):
            # Template pattern groups: escaped, named, braced, invalid
            name = match.group("named") or match.group("braced")
            if name is not None:
                used_vars.add(name)
        declared_vars = set(variables)

        if used_vars != declared_vars:
            missing = declared_vars - used_vars
            extra = used_vars - declared_vars

            msg_parts = []
            if missing:
                msg_parts.append(f"declared but not used: {missing}")
            if extra:
                msg_parts.append(f"used but not declared: {extra}")

            raise ValueError(
                f"Variable mismatch in template: {'; '.join(msg_parts)}"
            )

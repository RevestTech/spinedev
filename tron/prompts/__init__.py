"""
Tron Prompt Management System.

Provides versioned prompt template storage, retrieval, and rendering with
support for drift detection and audit trails.

Public API:
- PromptManager: Core system for managing templates
- PromptTemplate: SQLAlchemy ORM model for template registry
- PromptVersion: SQLAlchemy ORM model for version snapshots
- RenderedPrompt: Result of rendering a template with variables
- DEFAULT_TEMPLATES: Default templates for the three ISO agents
"""

from __future__ import annotations

from tron.prompts.defaults import DEFAULT_TEMPLATES
from tron.prompts.manager import PromptManager, RenderedPrompt
from tron.prompts.models import PromptTemplate, PromptVersion

__all__ = [
    "PromptManager",
    "PromptTemplate",
    "PromptVersion",
    "RenderedPrompt",
    "DEFAULT_TEMPLATES",
]

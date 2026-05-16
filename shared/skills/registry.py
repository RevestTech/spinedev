"""Skill registry — discover, validate, and list SKILL.yaml + SKILL.md pairs.

Implements STORY-4.1.1 (skill auto-trigger mechanism). Each skill lives in
`shared/skills/skills/<slug>/` as a pair of files:

    SKILL.yaml  — trigger config + metadata (this module's source of truth)
    SKILL.md    — the prompt body the role daemon injects when fired

Pattern source: `obra/superpowers`. The trigger evaluation runtime lives in
`trigger_engine.py`; this module only deals with loading + validating.

Stack: Pydantic v2 + PyYAML + stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
DEFAULT_TOKEN_BUDGET = 2000
# Skills carry runtime path refs (yaml_path / md_path) — allow `Path` values.
_STRIP = ConfigDict(str_strip_whitespace=True, extra="forbid",
                    arbitrary_types_allowed=True)


class SkillTrigger(BaseModel):
    """`trigger:` block of SKILL.yaml. AND semantics across all filters."""
    model_config = _STRIP
    applies_to_roles: list[str] = Field(default_factory=list)
    applies_to_phases: list[str] = Field(default_factory=list)
    applies_to_directive_keywords: list[str] = Field(default_factory=list)
    applies_when: list[dict[str, Any]] = Field(default_factory=list)
    applies_when_or: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("applies_to_roles", "applies_to_phases",
                     "applies_to_directive_keywords")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


class Skill(BaseModel):
    """A single skill loaded from SKILL.yaml + SKILL.md."""
    model_config = _STRIP
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    version: int = 1
    trigger: SkillTrigger = Field(default_factory=SkillTrigger)
    priority: int = 100
    max_token_overhead: int = 500
    incompatible_with: list[str] = Field(default_factory=list)
    inherits_from: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Lazy file refs — not part of the YAML payload (set after model_validate).
    yaml_path: Optional[Path] = None
    md_path: Optional[Path] = None
    _prompt_cache: Optional[str] = PrivateAttr(default=None)

    @property
    def prompt_text(self) -> str:
        """Read SKILL.md once; cache thereafter. Empty string if missing."""
        if self._prompt_cache is not None:
            return self._prompt_cache
        if self.md_path is None or not self.md_path.exists():
            self._prompt_cache = ""
        else:
            self._prompt_cache = self.md_path.read_text(encoding="utf-8")
        return self._prompt_cache


@dataclass
class ValidationError:
    """One issue found during registry validation."""
    slug: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.slug}: {self.message}"


def _load_one(yaml_path: Path) -> Skill:
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{yaml_path}: top-level YAML must be a mapping")
    # Backwards-tolerant: if `trigger:` is absent but flat `applies_to_*` keys
    # exist at the root (older convention), fold them into a synthetic trigger.
    if "trigger" not in raw:
        flat_keys = {"applies_to_roles", "applies_to_phases",
                     "applies_to_directive_keywords", "applies_when",
                     "applies_when_or"}
        flat = {k: raw.pop(k) for k in list(raw) if k in flat_keys}
        if flat:
            raw["trigger"] = flat
    skill = Skill.model_validate(raw)
    skill.yaml_path = yaml_path
    skill.md_path = yaml_path.with_name("SKILL.md")
    return skill


def discover_skills(skills_root: Path = DEFAULT_SKILLS_ROOT
                    ) -> dict[str, Skill]:
    """Walk `skills_root` for SKILL.yaml files and return a slug-keyed map.

    Duplicate slugs are kept on first-write-wins; `validate_skill_registry`
    flags collisions separately so the load itself never crashes.
    """
    registry: dict[str, Skill] = {}
    if not skills_root.exists():
        return registry
    for yaml_path in sorted(skills_root.rglob("SKILL.yaml")):
        try:
            skill = _load_one(yaml_path)
        except Exception:  # noqa: BLE001 — validation surfaces issues, not load.
            continue
        registry.setdefault(skill.slug, skill)
    return registry


def list_skills(registry: Optional[dict[str, Skill]] = None,
                filter_role: Optional[str] = None,
                filter_phase: Optional[str] = None) -> list[Skill]:
    """Filter + sort skills by priority (desc). Pass `registry` to reuse a load."""
    reg = registry if registry is not None else discover_skills()
    out: list[Skill] = []
    for skill in reg.values():
        if filter_role and skill.trigger.applies_to_roles \
                and filter_role not in skill.trigger.applies_to_roles:
            continue
        if filter_phase and skill.trigger.applies_to_phases \
                and filter_phase not in skill.trigger.applies_to_phases:
            continue
        out.append(skill)
    out.sort(key=lambda s: (-s.priority, s.slug))
    return out


def validate_skill_registry(registry: Optional[dict[str, Skill]] = None,
                            skills_root: Path = DEFAULT_SKILLS_ROOT
                            ) -> list[ValidationError]:
    """Return all issues: slug collisions, broken refs, missing SKILL.md."""
    issues: list[ValidationError] = []
    # Detect slug collisions by re-walking the tree (discover_skills hides them).
    seen: dict[str, Path] = {}
    if skills_root.exists():
        for yaml_path in sorted(skills_root.rglob("SKILL.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            except Exception as e:  # noqa: BLE001
                issues.append(ValidationError(
                    slug=yaml_path.parent.name, code="yaml_parse_error",
                    message=f"{yaml_path}: {e}"))
                continue
            slug = (raw or {}).get("slug") or yaml_path.parent.name
            if slug in seen:
                issues.append(ValidationError(
                    slug=slug, code="slug_collision",
                    message=f"also defined at {seen[slug]}"))
            else:
                seen[slug] = yaml_path
    reg = registry if registry is not None else discover_skills(skills_root)
    slugs = set(reg.keys())
    for slug, skill in reg.items():
        for ref in skill.incompatible_with:
            if ref not in slugs:
                issues.append(ValidationError(
                    slug=slug, code="incompatible_ref_missing",
                    message=f"incompatible_with `{ref}` not in registry"))
        for ref in skill.inherits_from:
            if ref not in slugs:
                issues.append(ValidationError(
                    slug=slug, code="inherits_ref_missing",
                    message=f"inherits_from `{ref}` not in registry"))
        if skill.md_path is None or not skill.md_path.exists():
            issues.append(ValidationError(
                slug=slug, code="prompt_missing",
                message=f"SKILL.md not found alongside {skill.yaml_path}"))
        if skill.max_token_overhead <= 0:
            issues.append(ValidationError(
                slug=slug, code="bad_overhead",
                message="max_token_overhead must be positive"))
    return issues

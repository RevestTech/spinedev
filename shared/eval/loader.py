"""Spine eval dataset + rubric loader (STORY-3.4.2).

Reads dataset YAMLs (per `_dataset_schema.yaml`) and rubric YAMLs (per
`_rubric_schema.yaml`), validates with Pydantic v2, resolves `rubric_ref`,
computes baseline-prompt SHA-256 for drift detection. Pure I/O + validation;
no DB, no LLM. Consumed by runner.py.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CheckType = Literal["regex", "structured_field", "llm_judge", "deterministic"]
Severity = Literal["critical", "high", "medium", "low"]
ScoringMethod = Literal["strict_must", "weighted_average", "composite"]
_STRIP = ConfigDict(str_strip_whitespace=True, extra="forbid")


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes (hex)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Trait(BaseModel):
    model_config = _STRIP
    trait_id: str = Field(min_length=1)
    description: str
    check_type: CheckType
    check_payload: dict[str, Any]

class ExpectedTraits(BaseModel):
    model_config = _STRIP
    must: list[Trait] = Field(default_factory=list)
    should: list[Trait] = Field(default_factory=list)
    must_not: list[Trait] = Field(default_factory=list)

class CaseInputs(BaseModel):
    model_config = _STRIP
    files: list[str] = Field(default_factory=list)
    kg_queries: list[str] = Field(default_factory=list)
    prior_reports: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

class Case(BaseModel):
    model_config = _STRIP
    case_id: str = Field(min_length=1)
    directive: str = Field(min_length=1)
    inputs: CaseInputs = Field(default_factory=CaseInputs)
    expected_traits: ExpectedTraits = Field(default_factory=ExpectedTraits)
    rubric_ref: str
    severity: Severity
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    @model_validator(mode="after")
    def _must_or_low(self) -> "Case":
        """Rule 4: ≥1 must trait OR severity=low."""
        if not self.expected_traits.must and self.severity != "low":
            raise ValueError(f"case {self.case_id!r}: needs a 'must' trait or severity=low")
        return self

class Baseline(BaseModel):
    model_config = _STRIP
    prompt_path: str
    prompt_sha: str = Field(min_length=64, max_length=64)
    model: str
    recorded_scores: dict[str, float] = Field(default_factory=dict)

class EvalDataset(BaseModel):
    model_config = _STRIP
    dataset_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    description: str = ""
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    baseline: Baseline
    cases: list[Case] = Field(min_length=1)
    @model_validator(mode="after")
    def _unique_case_ids(self) -> "EvalDataset":
        ids = [c.case_id for c in self.cases]
        if dupes := sorted({x for x in ids if ids.count(x) > 1}):
            raise ValueError(f"duplicate case_id(s): {dupes}")
        return self

class RubricCheck(BaseModel):
    model_config = _STRIP
    check_id: str = Field(min_length=1)
    description: str = ""
    check_type: CheckType
    must_pass: bool = False
    weight: float = Field(ge=0.0, le=1.0, default=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)

class EvalRubric(BaseModel):
    model_config = _STRIP
    rubric_id: str = Field(min_length=1)
    description: str = ""
    scoring_method: ScoringMethod
    checks: list[RubricCheck] = Field(min_length=1)
    @model_validator(mode="after")
    def _scoring_rules(self) -> "EvalRubric":
        if self.scoring_method == "strict_must" and not all(c.must_pass for c in self.checks):
            raise ValueError("strict_must requires every check.must_pass=true")
        if self.scoring_method == "weighted_average":
            total = sum(c.weight for c in self.checks)
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"weighted_average weights must sum ~1.0 (got {total:.3f})")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"yaml not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping, got {type(data).__name__}")
    return data

def load_dataset(path: Path, *, repo_root: Optional[Path] = None,
                 verify_baseline: bool = False) -> EvalDataset:
    """Validate dataset YAML; optionally check baseline.prompt_path exists."""
    dataset = EvalDataset.model_validate(_read_yaml(path))
    if verify_baseline:
        bp = (repo_root or Path.cwd()) / dataset.baseline.prompt_path
        if not bp.is_file():
            raise FileNotFoundError(f"baseline.prompt_path not found: {bp}")
    return dataset

def load_rubric(path: Path) -> EvalRubric:
    return EvalRubric.model_validate(_read_yaml(path))

def resolve_rubric(dataset_path: Path, case: Case) -> Path:
    """rubric_ref is relative to the dataset dir."""
    return (dataset_path.parent / case.rubric_ref).resolve()

def load_dataset_with_rubrics(path: Path, *, repo_root: Optional[Path] = None,
                              verify_baseline: bool = False
                              ) -> tuple[EvalDataset, dict[str, EvalRubric]]:
    """Load dataset + every distinct rubric it references."""
    dataset = load_dataset(path, repo_root=repo_root, verify_baseline=verify_baseline)
    rubrics: dict[str, EvalRubric] = {}
    for case in dataset.cases:
        key = str(rp := resolve_rubric(path, case))
        if key in rubrics:
            continue
        if not rp.is_file():
            raise FileNotFoundError(f"case {case.case_id!r}: rubric missing: {rp}")
        rubrics[key] = load_rubric(rp)
    return dataset, rubrics


__all__ = ["CheckType", "Severity", "ScoringMethod", "Trait", "ExpectedTraits",
           "CaseInputs", "Case", "Baseline", "EvalDataset", "RubricCheck",
           "EvalRubric", "load_dataset", "load_rubric",
           "load_dataset_with_rubrics", "resolve_rubric", "sha256_file"]

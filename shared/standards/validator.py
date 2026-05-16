"""validator.py — Spine org-policy-bundle schema validator.

Implements STORY-2.1.2 (bundle validation). Mirrors
shared/standards/bundle-schema.yaml as Pydantic v2 models so a bundle that
parses here is guaranteed to satisfy the published schema. Cross-section
invariants (HIPAA scope ⇒ HIPAA pack, capability principals well-formed,
inherits_from resolves to an installed parent, rationale ≥8 chars) are
checked in @model_validator hooks. See:
  - shared/standards/bundle-schema.yaml (source of truth).
  - shared/standards/README.md (lifecycle + override hierarchy).
  - docs/PRD.md REQ-INIT-1 FR-7 (customization authority), FR-8 (rationale).
  - docs/BACKLOG.md INIT-2 EPIC-2.1 (STORY-2.1.2 + 2.1.5 drift detection).

CLI: `python3 validator.py validate <path>` — exit 0 valid; non-zero with a
structured-JSON error on stderr otherwise.
Library: `validate_bundle(path) -> ValidationResult{valid, errors, warnings}`.
"""
from __future__ import annotations
import json, os, re, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# Compliance packs we recognize today; bundles may declare extras (warning,
# not hard fail — EPIC-2.4.5 may register new TRON packs over time).
KNOWN_PACKS = {"OWASP_Top_10", "SOC_2_Type_II", "ISO_27001", "HIPAA",
               "PCI_DSS", "NIST_CSF", "GDPR", "FedRAMP"}
KNOWN_SEVERITIES = {"critical", "high", "medium", "low"}
KNOWN_SCOPES = {"org", "team", "project"}
PRINCIPAL_RE = re.compile(r"^(role|user|group):[A-Za-z0-9_\-\*]+$")


class PRReviewRequirements(BaseModel):
    min_reviewers: int = 1
    required_checks: list[str] = []
    required_labels: list[str] = []


class DocRequirements(BaseModel):
    readme_required: bool = True
    adr_required_for: list[str] = []


class Standards(BaseModel):
    naming_conventions: dict[str, Any] = {}
    style_guides: list[str] = []
    commit_message_format: Optional[str] = None
    pr_review_requirements: PRReviewRequirements = Field(default_factory=PRReviewRequirements)
    test_coverage_threshold: Optional[int] = None
    documentation_requirements: DocRequirements = Field(default_factory=DocRequirements)


class Security(BaseModel):
    compliance_packs: list[str] = []
    secret_scanning: dict[str, Any] = {}
    dependency_scanning: dict[str, Any] = {}
    sast_required: bool = False
    iso_agents_required: list[str] = []
    sandbox_seccomp_profile: Optional[str] = None


class Cost(BaseModel):
    daily_cap_usd: Optional[float] = None
    weekly_cap_usd: Optional[float] = None
    monthly_cap_usd: Optional[float] = None
    per_project_cap_usd: Optional[float] = None
    per_phase_caps: dict[str, float] = {}
    model_menu: dict[str, list[str]] = {}

    @field_validator("daily_cap_usd", "weekly_cap_usd", "monthly_cap_usd", "per_project_cap_usd")
    @classmethod
    def _nonneg(cls, v):
        if v is not None and v < 0:
            raise ValueError("cost cap must be >= 0")
        return v


class BannedPattern(BaseModel):
    pattern: str
    language: str
    severity: str
    message: str
    source: Optional[str] = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v):
        if v not in KNOWN_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(KNOWN_SEVERITIES)}")
        return v

    @field_validator("pattern")
    @classmethod
    def _regex_compiles(cls, v):
        try: re.compile(v)
        except re.error as e: raise ValueError(f"invalid regex: {e}")
        return v


class DeploymentTargets(BaseModel):
    allowed_environments: list[str] = []
    cloud_providers: list[str] = []
    infra_as_code: dict[str, Any] = {}
    requires_change_approval: bool = False


class ComplianceTags(BaseModel):
    pii_data_handled: bool = False
    pci_dss_scope: bool = False
    hipaa_scope: bool = False
    gdpr_scope: bool = False
    regulated_industry: str = "none"


class Capabilities(BaseModel):
    grants: dict[str, list[str]] = {}
    revokes: list[str] = []


class Identity(BaseModel):
    bundle_version: int
    bundle_id: str
    display_name: str
    org_name: str
    inherits_from: Optional[str] = None
    scope: str
    created_at: str
    last_updated_at: str
    last_updated_by: str
    rationale: str

    @field_validator("bundle_version")
    @classmethod
    def _ver(cls, v):
        if v < 1: raise ValueError("bundle_version must be a positive integer")
        return v

    @field_validator("scope")
    @classmethod
    def _scope(cls, v):
        if v not in KNOWN_SCOPES: raise ValueError(f"scope must be one of {sorted(KNOWN_SCOPES)}")
        return v

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, v):
        if not v or len(v.strip()) < 8:
            raise ValueError("rationale required, min_length=8 (audit anchor per EPIC-1.7.4)")
        return v


class Bundle(BaseModel):
    identity: Identity
    standards: Standards = Field(default_factory=Standards)
    security: Security = Field(default_factory=Security)
    cost: Cost = Field(default_factory=Cost)
    approved_libs: dict[str, list[str]] = {}
    banned_patterns: list[BannedPattern] = []
    deployment_targets: DeploymentTargets = Field(default_factory=DeploymentTargets)
    compliance_tags: ComplianceTags = Field(default_factory=ComplianceTags)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    pipeline_overrides: dict[str, Any] = {}
    verify_overrides: dict[str, Any] = {}


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _check_principals(caps: Capabilities, warnings: list[str]) -> list[str]:
    bad = []
    for cap_name, principals in (caps.grants or {}).items():
        for p in principals or []:
            if not PRINCIPAL_RE.match(p):
                bad.append(f"capabilities.grants.{cap_name}: invalid principal {p!r} "
                           f"(expected role:<n>, user:<id>, group:<id>)")
    for p in caps.revokes or []:
        if not PRINCIPAL_RE.match(p):
            warnings.append(f"capabilities.revokes: non-standard principal {p!r}")
    return bad


def _check_phase_appends(po: dict, errors: list[str]) -> None:
    """Loose check of pipeline_overrides.phases.append items vs sdlc-pipeline-schema.yaml phase shape."""
    phases = ((po or {}).get("phases") or {}).get("append") or []
    required = {"id", "ownership", "role_lead", "artifact", "tier_default", "gate"}
    for i, ph in enumerate(phases):
        if not isinstance(ph, dict):
            errors.append(f"pipeline_overrides.phases.append[{i}]: not a mapping"); continue
        missing = required - set(ph.keys())
        if missing:
            errors.append(f"pipeline_overrides.phases.append[{i}] missing keys: {sorted(missing)}")


def _check_cross_section(b: Bundle, errors: list[str], warnings: list[str]) -> None:
    # HIPAA scope ⇒ HIPAA pack (warning per spec — operator may have a documented override).
    if b.compliance_tags.hipaa_scope and "HIPAA" not in b.security.compliance_packs:
        warnings.append("compliance_tags.hipaa_scope=true but HIPAA not in security.compliance_packs")
    # PCI scope ⇒ PCI_DSS pack (mirror policy).
    if b.compliance_tags.pci_dss_scope and "PCI_DSS" not in b.security.compliance_packs:
        warnings.append("compliance_tags.pci_dss_scope=true but PCI_DSS not in security.compliance_packs")
    # Unknown packs → warn (extensibility hook, not hard fail).
    for pack in b.security.compliance_packs:
        if pack not in KNOWN_PACKS:
            warnings.append(f"security.compliance_packs: unknown pack {pack!r}")
    # inherits_from must resolve to an installed parent (warn if absent locally).
    if b.identity.inherits_from:
        bundles_dir = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine"))) / "bundles"
        if not (bundles_dir / b.identity.inherits_from).exists():
            warnings.append(f"identity.inherits_from={b.identity.inherits_from!r} not installed locally")
    # Capability principals.
    errors.extend(_check_principals(b.capabilities, warnings))
    # pipeline_overrides phase shape.
    _check_phase_appends(b.pipeline_overrides, errors)


def validate_bundle(path: Path) -> ValidationResult:
    """Validate a bundle YAML; structured ValidationResult never raises."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as e:
        return ValidationResult(valid=False, errors=[f"yaml_parse_error: {e}"])
    if not isinstance(raw, dict):
        return ValidationResult(valid=False, errors=["bundle root must be a mapping"])
    try:
        bundle = Bundle.model_validate(raw)
    except ValidationError as e:
        return ValidationResult(valid=False,
                                errors=[f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
                                        for err in e.errors()])
    errors: list[str] = []; warnings: list[str] = []
    _check_cross_section(bundle, errors, warnings)
    return ValidationResult(valid=(not errors), errors=errors, warnings=warnings)


def _cli() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "validate":
        print(json.dumps({"ok": False, "code": "bad_args",
                          "message": "usage: validator.py validate <path>"}), file=sys.stderr)
        return 2
    result = validate_bundle(Path(sys.argv[2]))
    payload = {"ok": result.valid, "errors": result.errors, "warnings": result.warnings}
    print(json.dumps(payload))
    if not result.valid:
        print(json.dumps({"ok": False, "code": "validation_failed",
                          "errors": result.errors}), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

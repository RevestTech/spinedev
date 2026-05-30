"""Tests for ``verify.agent_audit.checks.transport`` (L10)."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.checks.transport import check_transport_layer


REPO_ROOT = Path(__file__).resolve().parents[4]

_ENVELOPE_WITH_ALL_FIELDS = (
    "class ToolResponse:\n"
    "    summary: str | None\n"
    "    next_actions: list[str]\n"
    "    artifacts: list\n"
)

_ENVELOPE_MISSING_FIELDS = (
    "class ToolResponse:\n"
    "    data: dict\n"
)


def _stub_envelopes(root: Path, body: str) -> Path:
    envelopes = root / "shared" / "mcp" / "schemas" / "envelopes.py"
    envelopes.parent.mkdir(parents=True, exist_ok=True)
    envelopes.write_text(body, encoding="utf-8")
    return envelopes


def _stub_api_dir(root: Path, files: dict[str, str] | None = None) -> Path:
    api_dir = root / "shared" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (files or {}).items():
        (api_dir / name).write_text(body, encoding="utf-8")
    return api_dir


def _stub_spa_components(
    root: Path, files: dict[str, str] | None = None,
) -> Path:
    comp_dir = root / "shared" / "ui" / "spa" / "src" / "lib" / "components"
    comp_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (files or {}).items():
        (comp_dir / name).write_text(body, encoding="utf-8")
    return comp_dir


def _stub_full_repo(
    root: Path,
    *,
    envelope_body: str = _ENVELOPE_WITH_ALL_FIELDS,
    api_files: dict[str, str] | None = None,
    spa_files: dict[str, str] | None = None,
) -> None:
    _stub_envelopes(root, envelope_body)
    _stub_api_dir(root, api_files or {})
    _stub_spa_components(root, spa_files or {})


def test_regressed_when_envelopes_file_missing(tmp_path: Path) -> None:
    _stub_api_dir(tmp_path)
    finding = check_transport_layer(tmp_path, {})
    assert finding.layer == "L10_transport"
    assert finding.status == "regressed"
    assert finding.severity == "critical"
    assert any("envelopes.py" in ev for ev in finding.evidence)


def test_regressed_when_api_dir_missing(tmp_path: Path) -> None:
    _stub_envelopes(tmp_path, _ENVELOPE_WITH_ALL_FIELDS)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "critical"
    assert any("api" in ev for ev in finding.evidence)


def test_regressed_when_envelope_missing_fields(tmp_path: Path) -> None:
    _stub_full_repo(tmp_path, envelope_body=_ENVELOPE_MISSING_FIELDS)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert set(finding.evidence) == {"summary", "next_actions", "artifacts"}


def test_regressed_lists_only_missing_fields(tmp_path: Path) -> None:
    partial = (
        "class ToolResponse:\n"
        "    summary: str | None\n"
        "    artifacts: list\n"
    )
    _stub_full_repo(tmp_path, envelope_body=partial)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.evidence == ("next_actions",)


def test_warning_when_no_consumers_found(tmp_path: Path) -> None:
    _stub_full_repo(tmp_path)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "no ToolResponse consumers" in finding.summary


def test_warning_when_summary_ratio_below_threshold(tmp_path: Path) -> None:
    api_files = {
        "a.py": "uses ToolResponse only",
        "b.py": "uses ToolResponse only",
        "c.py": "uses ToolResponse and summary",
    }
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "1/3" in finding.summary


def test_clean_when_summary_ratio_at_threshold(tmp_path: Path) -> None:
    api_files = {
        "a.py": "ToolResponse summary present",
        "b.py": "ToolResponse summary present",
    }
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "clean"
    assert finding.severity == "low"


def test_clean_mixed_api_and_spa_consumers(tmp_path: Path) -> None:
    api_files = {
        "route.py": "ToolResponse summary lives here",
    }
    spa_files = {
        "Panel.svelte": "<script>ToolResponse summary</script>",
        "Other.svelte": "no envelope reference",
    }
    _stub_full_repo(tmp_path, api_files=api_files, spa_files=spa_files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "clean"


def test_warning_when_transport_drops_positive(tmp_path: Path) -> None:
    api_files = {"a.py": "ToolResponse summary present"}
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {"transport_drops": 7})
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "7 transport envelope-field drop" in finding.summary
    assert "transport_drops=7" in finding.evidence


def test_transport_drops_zero_does_not_trigger_warning(tmp_path: Path) -> None:
    api_files = {"a.py": "ToolResponse summary present"}
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {"transport_drops": 0})
    assert finding.status == "clean"


def test_transport_drops_non_int_ignored(tmp_path: Path) -> None:
    api_files = {"a.py": "ToolResponse summary present"}
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {"transport_drops": "lots"})
    assert finding.status == "clean"


def test_missing_signal_does_not_go_pending(tmp_path: Path) -> None:
    api_files = {"a.py": "ToolResponse summary present"}
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status != "instrumentation_pending"


def test_real_repo_does_not_go_pending() -> None:
    finding = check_transport_layer(REPO_ROOT, {})
    assert finding.layer == "L10_transport"
    assert finding.status != "instrumentation_pending"


def test_consumer_count_ignores_non_matching_files(tmp_path: Path) -> None:
    api_files = {
        "noise.py": "nothing relevant here",
        "a.py": "ToolResponse summary present",
    }
    _stub_full_repo(tmp_path, api_files=api_files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == "clean"
    assert "1/1" in finding.summary


@pytest.mark.parametrize(
    "with_summary,total,expected",
    [
        (1, 2, "clean"),
        (1, 3, "warning"),
        (2, 4, "clean"),
        (0, 1, "warning"),
    ],
)
def test_summary_ratio_boundary(
    tmp_path: Path, with_summary: int, total: int, expected: str,
) -> None:
    files: dict[str, str] = {}
    for i in range(with_summary):
        files[f"with_{i}.py"] = "ToolResponse summary present"
    for i in range(total - with_summary):
        files[f"without_{i}.py"] = "ToolResponse only"
    _stub_full_repo(tmp_path, api_files=files)
    finding = check_transport_layer(tmp_path, {})
    assert finding.status == expected

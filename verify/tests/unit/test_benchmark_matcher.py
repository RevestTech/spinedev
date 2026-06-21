"""Synthetic-CVE benchmark harness — matcher tests (#9).

The matcher decides which findings count as true positives against the
labeled injections. It's the most fragile piece of the harness — small
mismatches in field names or line tolerance wreck the precision/recall
numbers. These tests pin the contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The benchmark runner lives outside the package — import it by path.
_HARNESS_DIR = (
    Path(__file__).resolve().parents[2] / "scripts" / "benchmark"
)
sys.path.insert(0, str(_HARNESS_DIR))

from synthetic_cve_runner import (  # type: ignore  # noqa: E402
    FixtureSpec,
    Injection,
    _translate_snyk_findings,
    match_findings,
    score,
)


def _spec(*injections: Injection, line_tolerance: int = 2) -> FixtureSpec:
    return FixtureSpec(
        fixture_name="t",
        description="",
        source_repo_url=None,
        source_commit=None,
        line_tolerance=line_tolerance,
        injections=list(injections),
    )


def _inj(file: str, vuln: str, line: int) -> Injection:
    inj = Injection(
        file=file,
        payload="...",
        expected_vulnerability_type=vuln,
        expected_severity="high",
    )
    inj.expected_line = line
    return inj


def _f(file: str, vuln: str, line: int) -> dict:
    return {"file_path": file, "vulnerability_type": vuln, "line_number": line}


# ── Matching ────────────────────────────────────────────────────────────


class TestMatching:
    def test_exact_match_is_a_tp(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10))
        finds = [_f("app/x.py", "sql_injection", 10)]
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 1
        assert len(fps) == 0
        assert len(fns) == 0

    def test_within_line_tolerance_is_a_tp(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10), line_tolerance=2)
        finds = [_f("app/x.py", "sql_injection", 12)]  # off by 2
        tps, _, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 1
        assert not fns

    def test_outside_line_tolerance_is_not_a_tp(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10), line_tolerance=2)
        finds = [_f("app/x.py", "sql_injection", 15)]
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 0
        assert len(fps) == 1
        assert len(fns) == 1

    def test_wrong_vuln_type_is_a_fp_and_fn(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10))
        finds = [_f("app/x.py", "xss", 10)]  # wrong type
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 0
        assert len(fps) == 1
        assert len(fns) == 1

    def test_wrong_file_is_a_fp_and_fn(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10))
        finds = [_f("app/y.py", "sql_injection", 10)]
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 0
        assert len(fps) == 1
        assert len(fns) == 1

    def test_extra_findings_count_as_fps(self):
        spec = _spec(_inj("app/x.py", "sql_injection", 10))
        finds = [
            _f("app/x.py", "sql_injection", 10),  # TP
            _f("app/y.py", "xss", 5),             # FP
            _f("app/z.py", "command_injection", 3),  # FP
        ]
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 1
        assert len(fps) == 2
        assert len(fns) == 0

    def test_finding_only_credits_one_injection(self):
        # Two injections of the same vuln_type in the same file at
        # different lines — a single finding should match exactly one,
        # not double-count.
        spec = _spec(
            _inj("app/x.py", "sql_injection", 10),
            _inj("app/x.py", "sql_injection", 20),
        )
        finds = [_f("app/x.py", "sql_injection", 10)]  # only matches the first
        tps, fps, fns = match_findings(findings=finds, spec=spec)
        assert len(tps) == 1
        assert len(fps) == 0
        assert len(fns) == 1
        # And it's the right one (line 20).
        assert fns[0].expected_line == 20


# ── Scoring ─────────────────────────────────────────────────────────────


class TestScore:
    def test_perfect_recall_and_precision(self):
        s = score(tp=10, fp=0, fn=0)
        assert s == {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    def test_zero_findings_at_all(self):
        s = score(tp=0, fp=0, fn=5)
        assert s["precision"] == 0.0
        assert s["recall"] == 0.0
        assert s["f1"] == 0.0

    def test_balanced_case(self):
        # 5 TP, 5 FP → precision 0.5
        # 5 TP, 5 FN → recall 0.5
        # F1 = 2*0.5*0.5 / 1.0 = 0.5
        s = score(tp=5, fp=5, fn=5)
        assert s["precision"] == pytest.approx(0.5)
        assert s["recall"] == pytest.approx(0.5)
        assert s["f1"] == pytest.approx(0.5)


# ── Snyk JSON adapter ────────────────────────────────────────────────────


class TestSnykAdapter:
    """Snyk Code emits SARIF-shaped JSON. The adapter translates to
    Tron-shape so the same matcher can score Snyk against the labeled
    fixture. Tests pin the schema mapping and the path-prefix stripping
    that aligns Snyk's absolute paths with the spec's repo-relative ones."""

    def test_modern_sarif_runs_results_shape(self):
        raw = {
            "runs": [
                {
                    "results": [
                        {
                            "ruleId": "javascript/Sqli",
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "/tmp/dirty/src/app.js"},
                                        "region": {"startLine": 12},
                                    }
                                }
                            ],
                        },
                        {
                            "ruleId": "python/HardcodedSecret",
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "/tmp/dirty/auth.py"},
                                        "region": {"startLine": 3},
                                    }
                                }
                            ],
                        },
                    ]
                }
            ]
        }
        out = _translate_snyk_findings(raw, dirty_repo=Path("/tmp/dirty"))
        assert out == [
            {"file_path": "src/app.js", "vulnerability_type": "sql_injection", "line_number": 12},
            {"file_path": "auth.py", "vulnerability_type": "hardcoded_secrets", "line_number": 3},
        ]

    def test_unknown_rule_id_falls_back_to_other(self):
        raw = {
            "runs": [{"results": [{
                "ruleId": "javascript/SomeNewRuleSnykAddedYesterday",
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": "/tmp/dirty/x.js"},
                    "region": {"startLine": 5},
                }}],
            }]}]
        }
        out = _translate_snyk_findings(raw, dirty_repo=Path("/tmp/dirty"))
        # Unknown rule → ``other``. Still appears so line-tolerant
        # matching against the spec is possible.
        assert out == [{"file_path": "x.js", "vulnerability_type": "other", "line_number": 5}]

    def test_legacy_vulnerabilities_list_shape(self):
        # Older Snyk Open Source style: bare list with ``filePath`` / ``ruleId``.
        raw = {
            "vulnerabilities": [
                {
                    "filePath": "/tmp/dirty/server.js",
                    "ruleId": "javascript/Xss",
                    "line": 22,
                },
            ]
        }
        out = _translate_snyk_findings(raw, dirty_repo=Path("/tmp/dirty"))
        assert out == [{"file_path": "server.js", "vulnerability_type": "xss", "line_number": 22}]

    def test_empty_results_returns_empty_list(self):
        out = _translate_snyk_findings({"runs": [{"results": []}]}, dirty_repo=Path("/tmp/dirty"))
        assert out == []

    def test_unknown_shape_returns_empty(self):
        # Anything we don't recognise should produce ``[]``, not crash —
        # benchmark continues, Snyk just contributes 0/0.
        out = _translate_snyk_findings("not a dict", dirty_repo=Path("/tmp/dirty"))
        assert out == []
        out = _translate_snyk_findings({"unknown": "shape"}, dirty_repo=Path("/tmp/dirty"))
        assert out == []

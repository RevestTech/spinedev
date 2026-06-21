import json
from pathlib import Path

from tron.services.sarif_import import _fingerprint, parse_sarif_to_rows

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "minimal.sarif.json"


def test_parse_sarif_fixture() -> None:
    data = json.loads(FIXTURE.read_text())
    rows = parse_sarif_to_rows(
        data, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    )
    assert len(rows) == 1
    r0 = rows[0]
    assert r0["file_path"] == "src/app.py"
    assert r0["line_start"] == 10
    assert r0["evidence_source"] == "sarif"
    assert r0["rule_id"] == "test/rule-1"
    assert r0["fingerprint"] == _fingerprint("test/rule-1", "src/app.py", 10)


def test_fingerprint_stable() -> None:
    a = _fingerprint("r", "f.py", 1)
    b = _fingerprint("r", "f.py", 1)
    assert a == b
    assert _fingerprint("r2", "f.py", 1) != a

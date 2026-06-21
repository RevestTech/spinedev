
from tron.services.audit_path_filters import (
    classify_path_role,
    filter_file_contents,
    path_matches_any,
    path_matches_glob,
)


def test_path_matches_glob_star() -> None:
    assert path_matches_glob("src/foo.py", "*.py")
    assert not path_matches_glob("x", "*.js")


def test_path_matches_doublestar() -> None:
    assert path_matches_glob("node_modules/lodash/x.js", "**/node_modules/**")
    assert not path_matches_glob("src/x.js", "**/node_modules/**")


def test_filter_excludes() -> None:
    d = {"a.py": "x", "b.min.js": "y", "c.py": "z"}
    out = filter_file_contents(d, ["*.min.js"])
    assert "b.min.js" not in out
    assert len(out) == 2


def test_test_path_classify() -> None:
    assert classify_path_role("tests/test_x.py", ["**/test/**", "**/tests/**"]) == "test"
    assert classify_path_role("src/lib.py", ["**/test/**"]) is None


def test_path_matches_any_empty() -> None:
    assert path_matches_any("a", None) is False
    assert path_matches_any("a", []) is False

"""directory_path ltree encoding for code_files / GiST index."""

from tron.services.graph_sync import _directory_path_as_ltree


def test_root_file_no_directory():
    assert _directory_path_as_ltree("Makefile") is None
    assert _directory_path_as_ltree("README.md") is None


def test_nested_unix_path_becomes_dots():
    assert _directory_path_as_ltree("tron/api/routes/graph.py") == "tron.api.routes"


def test_special_chars_sanitized_in_labels():
    assert _directory_path_as_ltree(".github/workflows/ci.yml") == "_github.workflows"
    assert _directory_path_as_ltree("pkg-name/src/lib.rs") == "pkg_name.src"


def test_skips_empty_segments_from_double_slash():
    assert _directory_path_as_ltree("a//b/c.py") == "a.b"

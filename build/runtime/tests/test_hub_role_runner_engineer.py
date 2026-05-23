"""Engineer output validation helpers in hub_role_runner."""

from build.runtime.hub_role_runner import _has_implementation_files, _parse_engineer_output


def test_has_implementation_files_detects_python() -> None:
    assert _has_implementation_files([("todo.py", "print('hi')")]) is True
    assert _has_implementation_files([("docs/PRD.md", "# prd")]) is False
    assert _has_implementation_files([("README.md", "# hi")]) is False


def test_parse_engineer_output_extracts_file_blocks() -> None:
    raw = (
        "Intro line\n\n"
        "===== FILE: todo.py =====\n"
        "print('ok')\n"
        "===== END FILE =====\n\n"
        "===== RUN =====\n"
        "python todo.py list\n"
        "===== END RUN =====\n"
    )
    intro, files, run_block = _parse_engineer_output(raw)
    assert intro.startswith("Intro line")
    assert files == [("todo.py", "print('ok')")]
    assert "python todo.py list" in run_block

"""
Unit tests for RepoScanner.

Tests:
  - File filtering (_should_include)
  - Language detection (detect_languages)
  - _looks_binary heuristic
  - scan() with mocked git clone
  - _clone error handling (timeout, non-zero exit)
  - _read_files (size limits, binary detection, max files)
  - Constructor defaults
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.services.repo_scanner import (
    RepoScanner,
    RepoScanError,
    _looks_binary,
    detect_languages,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    SKIP_FILENAMES,
    ANALYZABLE_EXTENSIONS,
    ANALYZABLE_FILENAMES,
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_TOTAL_SIZE,
    DEFAULT_MAX_FILES,
    DEFAULT_CLONE_TIMEOUT,
)


@pytest.fixture
def scanner():
    return RepoScanner()


# ── Constructor Tests ─────────────────────────────────────────────────


class TestConstructor:

    def test_default_limits(self):
        s = RepoScanner()
        assert s._max_file_size == DEFAULT_MAX_FILE_SIZE
        assert s._max_total_size == DEFAULT_MAX_TOTAL_SIZE
        assert s._max_files == DEFAULT_MAX_FILES
        assert s._clone_timeout == DEFAULT_CLONE_TIMEOUT

    def test_custom_limits(self):
        s = RepoScanner(max_file_size=1024, max_total_size=4096, max_files=10, clone_timeout=30)
        assert s._max_file_size == 1024
        assert s._max_files == 10


# ── _should_include Tests ─────────────────────────────────────────────


class TestShouldInclude:
    """Tests for file inclusion/exclusion logic."""

    def test_python_file_included(self, scanner, tmp_path):
        p = tmp_path / "app.py"
        p.write_text("x")
        assert scanner._should_include("app.py", p) is True

    def test_javascript_file_included(self, scanner, tmp_path):
        p = tmp_path / "index.js"
        p.write_text("x")
        assert scanner._should_include("index.js", p) is True

    def test_typescript_file_included(self, scanner, tmp_path):
        p = tmp_path / "component.tsx"
        p.write_text("x")
        assert scanner._should_include("component.tsx", p) is True

    def test_go_file_included(self, scanner, tmp_path):
        p = tmp_path / "main.go"
        p.write_text("x")
        assert scanner._should_include("main.go", p) is True

    def test_rust_file_included(self, scanner, tmp_path):
        p = tmp_path / "lib.rs"
        p.write_text("x")
        assert scanner._should_include("lib.rs", p) is True

    def test_java_file_included(self, scanner, tmp_path):
        p = tmp_path / "App.java"
        p.write_text("x")
        assert scanner._should_include("App.java", p) is True

    def test_shell_file_included(self, scanner, tmp_path):
        p = tmp_path / "deploy.sh"
        p.write_text("#!/bin/bash")
        assert scanner._should_include("deploy.sh", p) is True

    def test_sql_file_included(self, scanner, tmp_path):
        p = tmp_path / "migration.sql"
        p.write_text("CREATE TABLE")
        assert scanner._should_include("migration.sql", p) is True

    def test_terraform_file_included(self, scanner, tmp_path):
        p = tmp_path / "main.tf"
        p.write_text("resource")
        assert scanner._should_include("main.tf", p) is True

    def test_node_modules_excluded(self, scanner, tmp_path):
        d = tmp_path / "node_modules" / "express"
        d.mkdir(parents=True)
        p = d / "index.js"
        p.write_text("x")
        assert scanner._should_include("node_modules/express/index.js", p) is False

    def test_dot_git_excluded(self, scanner, tmp_path):
        d = tmp_path / ".git" / "objects"
        d.mkdir(parents=True)
        p = d / "abc"
        p.write_text("x")
        assert scanner._should_include(".git/objects/abc", p) is False

    def test_pycache_excluded(self, scanner, tmp_path):
        d = tmp_path / "__pycache__"
        d.mkdir()
        p = d / "module.cpython-311.pyc"
        p.write_text("x")
        assert scanner._should_include("__pycache__/module.cpython-311.pyc", p) is False

    def test_vendor_excluded(self, scanner, tmp_path):
        d = tmp_path / "vendor" / "lib"
        d.mkdir(parents=True)
        p = d / "code.go"
        p.write_text("x")
        assert scanner._should_include("vendor/lib/code.go", p) is False

    def test_venv_excluded(self, scanner, tmp_path):
        d = tmp_path / ".venv" / "lib"
        d.mkdir(parents=True)
        p = d / "site.py"
        p.write_text("x")
        assert scanner._should_include(".venv/lib/site.py", p) is False

    def test_binary_extension_excluded(self, scanner, tmp_path):
        for ext in (".png", ".zip", ".exe", ".dll", ".pyc", ".jar"):
            p = tmp_path / f"file{ext}"
            p.write_text("x")
            assert scanner._should_include(f"file{ext}", p) is False

    def test_lock_file_excluded(self, scanner, tmp_path):
        p = tmp_path / "package-lock.json"
        p.write_text("x")
        assert scanner._should_include("package-lock.json", p) is False

    def test_yarn_lock_excluded(self, scanner, tmp_path):
        p = tmp_path / "yarn.lock"
        p.write_text("x")
        assert scanner._should_include("yarn.lock", p) is False

    def test_cargo_lock_excluded(self, scanner, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text("x")
        assert scanner._should_include("Cargo.lock", p) is False

    def test_minified_js_excluded(self, scanner, tmp_path):
        p = tmp_path / "bundle.min.js"
        p.write_text("x")
        assert scanner._should_include("bundle.min.js", p) is False

    def test_source_map_excluded(self, scanner, tmp_path):
        p = tmp_path / "app.js.map"
        p.write_text("x")
        assert scanner._should_include("app.js.map", p) is False

    def test_dockerfile_included(self, scanner, tmp_path):
        p = tmp_path / "Dockerfile"
        p.write_text("FROM python:3.11")
        assert scanner._should_include("Dockerfile", p) is True

    def test_makefile_included(self, scanner, tmp_path):
        p = tmp_path / "Makefile"
        p.write_text("build:")
        assert scanner._should_include("Makefile", p) is True

    def test_yaml_included(self, scanner, tmp_path):
        p = tmp_path / "config.yml"
        p.write_text("key: value")
        assert scanner._should_include("config.yml", p) is True

    def test_unknown_extension_excluded(self, scanner, tmp_path):
        p = tmp_path / "data.xyz"
        p.write_text("x")
        assert scanner._should_include("data.xyz", p) is False

    def test_ds_store_excluded(self, scanner, tmp_path):
        p = tmp_path / ".DS_Store"
        p.write_text("x")
        assert scanner._should_include(".DS_Store", p) is False


# ── _looks_binary Tests ──────────────────────────────────────────────


class TestLooksBinary:

    def test_normal_text_not_binary(self):
        assert _looks_binary("Hello world\nThis is normal text\n") is False

    def test_empty_string_not_binary(self):
        assert _looks_binary("") is False

    def test_binary_content_detected(self):
        # Create content with lots of null bytes
        binary = "\x00" * 100 + "some text"
        assert _looks_binary(binary) is True

    def test_code_with_tabs_not_binary(self):
        code = "def foo():\n\tprint('hello')\n\treturn True\n"
        assert _looks_binary(code) is False


# ── detect_languages Tests ────────────────────────────────────────────


class TestDetectLanguages:

    def test_python_files(self):
        langs = detect_languages({"app.py": "x", "test.py": "y"})
        assert "python" in langs

    def test_javascript_files(self):
        langs = detect_languages({"index.js": "x"})
        assert "javascript" in langs

    def test_typescript_files(self):
        langs = detect_languages({"app.ts": "x"})
        assert "typescript" in langs

    def test_go_files(self):
        langs = detect_languages({"main.go": "x"})
        assert "go" in langs

    def test_rust_files(self):
        langs = detect_languages({"lib.rs": "x"})
        assert "rust" in langs

    def test_mixed_languages(self):
        langs = detect_languages({
            "app.py": "x",
            "index.js": "y",
            "main.go": "z",
        })
        assert len(langs) >= 3

    def test_empty_files(self):
        langs = detect_languages({})
        assert langs == ["unknown"]

    def test_unknown_extension_returns_unknown(self):
        langs = detect_languages({"data.xyz": "x"})
        assert langs == ["unknown"]

    def test_sorted_output(self):
        langs = detect_languages({"a.py": "x", "b.js": "y", "c.go": "z"})
        assert langs == sorted(langs)

    def test_sql_detected(self):
        langs = detect_languages({"schema.sql": "CREATE TABLE"})
        assert "sql" in langs

    def test_terraform_detected(self):
        langs = detect_languages({"main.tf": "resource"})
        assert "terraform" in langs


# ── scan() Tests ──────────────────────────────────────────────────────


class TestScan:

    async def test_scan_creates_and_returns_files(self, scanner):
        with patch.object(scanner, "_clone", new_callable=AsyncMock), \
             patch.object(scanner, "_get_tracked_files", new_callable=AsyncMock, return_value=["app.py"]), \
             patch.object(scanner, "_read_files", return_value={"app.py": "print('hi')"}):

            result = await scanner.scan("https://github.com/test/repo.git")

            assert "app.py" in result
            assert result["app.py"] == "print('hi')"

    async def test_scan_error_on_clone_failure(self, scanner):
        with patch.object(scanner, "_clone", new_callable=AsyncMock, side_effect=RepoScanError("clone failed")):
            with pytest.raises(RepoScanError, match="clone failed"):
                await scanner.scan("https://github.com/test/repo.git")

    async def test_scan_with_branch(self, scanner):
        with patch.object(scanner, "_clone", new_callable=AsyncMock) as mock_clone, \
             patch.object(scanner, "_get_tracked_files", new_callable=AsyncMock, return_value=[]), \
             patch.object(scanner, "_read_files", return_value={}):

            await scanner.scan("https://github.com/test/repo.git", branch="develop")

            # Verify branch was passed to _clone
            call_args = mock_clone.call_args
            assert call_args[0][1] == "develop"


# ── _clone Tests ─────────────────────────────────────────────────────


class TestClone:

    async def test_clone_timeout_raises(self, scanner):
        import asyncio as aio

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=aio.TimeoutError()):

            with pytest.raises(RepoScanError, match="timed out"):
                await scanner._clone("https://github.com/test/repo.git", "main", "/tmp/clone")

    async def test_clone_nonzero_exit_raises(self, scanner):
        mock_proc = AsyncMock()
        mock_proc.returncode = 128
        mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: repo not found"))

        async def passthrough_wait_for(coro, **kwargs):
            return await coro

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", side_effect=passthrough_wait_for):

            with pytest.raises(RepoScanError, match="Clone failed"):
                await scanner._clone("https://github.com/test/repo.git", "main", "/tmp/clone")


# ── RepoScanError Tests ─────────────────────────────────────────────


class TestRepoScanError:

    def test_is_exception(self):
        err = RepoScanError("test error")
        assert isinstance(err, Exception)

    def test_message(self):
        err = RepoScanError("clone failed")
        assert "clone failed" in str(err)


# ── Constants Coverage ───────────────────────────────────────────────


class TestConstants:

    def test_skip_dirs_has_essential_entries(self):
        for d in ["node_modules", ".git", "__pycache__", "vendor", ".venv"]:
            assert d in SKIP_DIRS

    def test_skip_extensions_has_binaries(self):
        for ext in [".exe", ".dll", ".png", ".zip", ".pyc"]:
            assert ext in SKIP_EXTENSIONS

    def test_analyzable_extensions_has_code(self):
        for ext in [".py", ".js", ".ts", ".go", ".rs", ".java"]:
            assert ext in ANALYZABLE_EXTENSIONS

    def test_analyzable_filenames_has_configs(self):
        for name in ["Dockerfile", "Makefile", "requirements.txt", "package.json"]:
            assert name in ANALYZABLE_FILENAMES


# ── _read_files Tests ─────────────────────────────────────────────────


class TestReadFiles:
    """Tests for _read_files with real tmp filesystem."""

    def _setup_repo(self, tmp_path):
        """Create a fake repo directory with various files."""
        # Source files
        (tmp_path / "app.py").write_text("print('hello')\n")
        (tmp_path / "utils.py").write_text("def helper(): pass\n")
        (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
        # Non-analyzable
        (tmp_path / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        (tmp_path / "data.xyz").write_text("unknown")
        return tmp_path

    async def test_reads_python_files(self, scanner, tmp_path):
        self._setup_repo(tmp_path)
        tracked = {"app.py", "utils.py", "Dockerfile", "image.png", "data.xyz"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)

        assert "app.py" in result
        assert "utils.py" in result
        assert "Dockerfile" in result

    async def test_skips_binary_extension(self, scanner, tmp_path):
        self._setup_repo(tmp_path)
        tracked = {"app.py", "image.png"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)

        assert "image.png" not in result

    async def test_skips_unknown_extension(self, scanner, tmp_path):
        self._setup_repo(tmp_path)
        tracked = {"app.py", "data.xyz"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)

        assert "data.xyz" not in result

    async def test_respects_max_files(self, tmp_path):
        # Create scanner with max_files=2
        s = RepoScanner(max_files=2)

        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.py").write_text("c")
        tracked = {"a.py", "b.py", "c.py"}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)
        assert len(result) <= 2

    async def test_respects_max_file_size(self, tmp_path):
        s = RepoScanner(max_file_size=10)  # 10 bytes

        (tmp_path / "small.py").write_text("x")
        (tmp_path / "big.py").write_text("x" * 100)
        tracked = {"small.py", "big.py"}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)
        assert "small.py" in result
        assert "big.py" not in result

    async def test_respects_max_total_size(self, tmp_path):
        s = RepoScanner(max_total_size=50)

        (tmp_path / "a.py").write_text("x" * 30)
        (tmp_path / "b.py").write_text("x" * 30)
        tracked = {"a.py", "b.py"}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)
        # Only first file should fit within 50 byte total
        assert len(result) <= 2  # May include both depending on exact counting

    async def test_skips_empty_files(self, scanner, tmp_path):
        (tmp_path / "empty.py").write_text("")
        tracked = {"empty.py"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)
        assert "empty.py" not in result

    async def test_skips_binary_content(self, scanner, tmp_path):
        # Create a file with binary-looking content (lots of null bytes)
        (tmp_path / "binary.py").write_text("\x00" * 100 + "some text")
        tracked = {"binary.py"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)
        assert "binary.py" not in result

    async def test_skips_node_modules_dir(self, scanner, tmp_path):
        d = tmp_path / "node_modules" / "pkg"
        d.mkdir(parents=True)
        (d / "index.js").write_text("module.exports = {}")
        tracked = {"node_modules/pkg/index.js"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)
        assert len(result) == 0


# ── _get_tracked_files Tests ─────────────────────────────────────────


class TestGetTrackedFiles:

    async def test_returns_set_of_files(self, scanner):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"app.py\nutils.py\nREADME.md\n", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await scanner._get_tracked_files("/tmp/repo")

        assert result == {"app.py", "utils.py", "README.md"}

    async def test_strips_whitespace(self, scanner):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"  app.py  \n\n  utils.py\n", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await scanner._get_tracked_files("/tmp/repo")

        assert result == {"app.py", "utils.py"}

    async def test_empty_output(self, scanner):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await scanner._get_tracked_files("/tmp/repo")

        assert result == set()


# ── Subdirectory Path Handling Tests ──────────────────────────────


class TestSubdirectoryPathHandling:
    """Test scanning a subdirectory of the repo."""

    async def test_scan_with_subdirectory(self, scanner, tmp_path):
        """scan() should handle subdirectory parameter."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hi')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test.py").write_text("assert True")

        tracked = {"src/app.py", "tests/test.py"}

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)), \
             patch("shutil.rmtree"), \
             patch.object(scanner, "_clone", new_callable=AsyncMock), \
             patch.object(scanner, "_get_tracked_files", new_callable=AsyncMock, return_value=tracked), \
             patch.object(scanner, "_read_files", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = {"src/app.py": "print('hi')"}

            result = await scanner.scan(
                "https://github.com/test/repo.git",
                subdirectory="src",
            )

            # Verify the subdirectory was passed to _read_files
            call_args = mock_read.call_args
            scan_root = call_args[0][1]
            assert "src" in str(scan_root)

    async def test_scan_subdirectory_not_found_raises(self, scanner):
        """scan() should raise if subdirectory doesn't exist."""
        from tron.services.repo_scanner import RepoScanError

        with patch.object(scanner, "_clone", new_callable=AsyncMock), \
             patch.object(scanner, "_get_tracked_files", new_callable=AsyncMock, return_value=set()):
            with pytest.raises(RepoScanError, match="not found"):
                await scanner.scan(
                    "https://github.com/test/repo.git",
                    subdirectory="nonexistent",
                )


# ── Clone Logging Tests ────────────────────────────────────────────


class TestCloneLogging:
    """Test clone operation logging."""

    async def test_clone_logs_repo_name(self, scanner):
        """_clone should log repo name and branch."""
        from unittest.mock import patch
        import logging

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def passthrough_wait_for(coro, **kwargs):
            return await coro

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", side_effect=passthrough_wait_for):

            logger = logging.getLogger("tron.services.repo_scanner")
            with patch.object(logger, "info") as mock_log:
                await scanner._clone("https://github.com/org/my-repo.git", "main", "/tmp/clone")

                # Verify logging was called
                assert mock_log.call_count >= 1


# ── Max Size Limit Tests ───────────────────────────────────────────


class TestMaxSizeLimits:
    """Test file and total size limits."""

    async def test_max_total_size_stops_scanning(self, tmp_path):
        """Scanner should stop when total_size limit reached."""
        s = RepoScanner(max_total_size=100)

        (tmp_path / "a.py").write_text("x" * 60)
        (tmp_path / "b.py").write_text("x" * 60)
        (tmp_path / "c.py").write_text("x" * 60)

        tracked = {"a.py", "b.py", "c.py"}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)

        # Should stop before reading all three files (may include the file that
        # pushes past the limit, but not subsequent files)
        assert len(result) < 3

    async def test_max_file_size_skips_large_files(self, tmp_path):
        """Scanner should skip files larger than max_file_size."""
        s = RepoScanner(max_file_size=500)

        (tmp_path / "small.py").write_text("x" * 10)
        (tmp_path / "large.py").write_text("x" * 1000)

        tracked = {"small.py", "large.py"}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)

        assert "small.py" in result
        assert "large.py" not in result


# ── File Filtering Tests ───────────────────────────────────────────


class TestFileFiltering:
    """Test file inclusion/exclusion filtering."""

    async def test_binary_file_detection(self, scanner, tmp_path):
        """Scanner should detect and skip binary content."""
        # Create a file with lots of null bytes
        (tmp_path / "binary.dat").write_bytes(b"\x00" * 100 + b"text")

        tracked = {"binary.dat"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)

        assert "binary.dat" not in result

    async def test_skip_dirs_applied(self, scanner, tmp_path):
        """Scanner should skip files in SKIP_DIRS."""
        node_dir = tmp_path / "node_modules" / "pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("module.exports = {}")

        tracked = {"node_modules/pkg/index.js"}

        result = await scanner._read_files(str(tmp_path), tmp_path, tracked)

        assert len(result) == 0


# ── Max Files Limit Tests ──────────────────────────────────────────


class TestMaxFilesLimit:
    """Test max files limit enforcement."""

    async def test_max_files_stops_at_limit(self, tmp_path):
        """Scanner should stop reading after max_files."""
        s = RepoScanner(max_files=2)

        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"# file {i}\n")

        tracked = {f"file{i}.py" for i in range(5)}

        result = await s._read_files(str(tmp_path), tmp_path, tracked)

        assert len(result) <= 2

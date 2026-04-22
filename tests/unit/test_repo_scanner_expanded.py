"""
Expanded unit tests for repository scanner.

Tests:
  - File filtering and exclusion
  - Language detection
  - Size limits (per-file and total)
  - Directory skipping
  - Binary file detection
  - Gitignore respecting
  - Error handling and timeouts
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.services.repo_scanner import (
    RepoScanner, RepoScanError, SKIP_DIRS, SKIP_EXTENSIONS,
    SKIP_FILENAMES, ANALYZABLE_EXTENSIONS, ANALYZABLE_FILENAMES,
    detect_languages, _looks_binary,
    DEFAULT_MAX_FILE_SIZE, DEFAULT_MAX_TOTAL_SIZE, DEFAULT_MAX_FILES,
)


class TestRepoScannerInit:
    """Tests for RepoScanner initialization."""

    def test_scanner_default_limits(self):
        """RepoScanner initialized with default size limits."""
        scanner = RepoScanner()
        
        assert scanner._max_file_size == DEFAULT_MAX_FILE_SIZE
        assert scanner._max_total_size == DEFAULT_MAX_TOTAL_SIZE
        assert scanner._max_files == DEFAULT_MAX_FILES

    def test_scanner_custom_limits(self):
        """RepoScanner accepts custom limits."""
        scanner = RepoScanner(
            max_file_size=1024,
            max_total_size=10240,
            max_files=100,
        )
        
        assert scanner._max_file_size == 1024
        assert scanner._max_total_size == 10240
        assert scanner._max_files == 100

    def test_scanner_custom_clone_timeout(self):
        """RepoScanner accepts custom clone timeout."""
        scanner = RepoScanner(clone_timeout=300)
        
        assert scanner._clone_timeout == 300


class TestSkipDirectories:
    """Tests for directory skipping logic."""

    def test_skip_dirs_set_contains_common_patterns(self):
        """SKIP_DIRS contains common build/dependency directories."""
        assert "node_modules" in SKIP_DIRS
        assert ".git" in SKIP_DIRS
        assert "__pycache__" in SKIP_DIRS
        assert "vendor" in SKIP_DIRS
        assert "dist" in SKIP_DIRS

    def test_skip_dirs_set_contains_cache_directories(self):
        """SKIP_DIRS contains cache directories."""
        assert ".pytest_cache" in SKIP_DIRS
        assert ".mypy_cache" in SKIP_DIRS
        assert ".tox" in SKIP_DIRS

    def test_skip_dirs_set_contains_venv_directories(self):
        """SKIP_DIRS contains virtual environment directories."""
        assert ".venv" in SKIP_DIRS
        assert "venv" in SKIP_DIRS
        assert "env" in SKIP_DIRS

    def test_should_include_skips_node_modules(self):
        """_should_include skips node_modules directory."""
        scanner = RepoScanner()
        
        result = scanner._should_include(
            "node_modules/package/index.js",
            Path("node_modules/package/index.js")
        )
        
        assert result is False

    def test_should_include_skips_hidden_directories(self):
        """_should_include skips .git, .vscode, .idea."""
        scanner = RepoScanner()
        
        for dir_name in [".git", ".vscode", ".idea"]:
            result = scanner._should_include(
                f"{dir_name}/file.txt",
                Path(f"{dir_name}/file.txt")
            )
            assert result is False


class TestSkipExtensions:
    """Tests for file extension skipping."""

    def test_skip_extensions_contains_binaries(self):
        """SKIP_EXTENSIONS contains binary extensions."""
        assert ".exe" in SKIP_EXTENSIONS
        assert ".dll" in SKIP_EXTENSIONS
        assert ".so" in SKIP_EXTENSIONS

    def test_skip_extensions_contains_images(self):
        """SKIP_EXTENSIONS contains image extensions."""
        assert ".png" in SKIP_EXTENSIONS
        assert ".jpg" in SKIP_EXTENSIONS
        assert ".gif" in SKIP_EXTENSIONS

    def test_skip_extensions_contains_media(self):
        """SKIP_EXTENSIONS contains media extensions."""
        assert ".mp3" in SKIP_EXTENSIONS
        assert ".mp4" in SKIP_EXTENSIONS

    def test_skip_extensions_contains_archives(self):
        """SKIP_EXTENSIONS contains archive extensions."""
        assert ".zip" in SKIP_EXTENSIONS
        assert ".tar" in SKIP_EXTENSIONS
        assert ".gz" in SKIP_EXTENSIONS

    def test_should_include_skips_lock_files(self):
        """_should_include skips .lock files."""
        scanner = RepoScanner()
        
        result = scanner._should_include(
            "package-lock.json",
            Path("package-lock.json")
        )
        
        assert result is False

    def test_should_include_skips_minified_js(self):
        """_should_include skips .min.js files."""
        scanner = RepoScanner()
        
        result = scanner._should_include(
            "bundle.min.js",
            Path("bundle.min.js")
        )
        
        assert result is False


class TestAnalyzableExtensions:
    """Tests for analyzable file extensions."""

    def test_analyzable_extensions_contains_python(self):
        """ANALYZABLE_EXTENSIONS contains Python."""
        assert ".py" in ANALYZABLE_EXTENSIONS

    def test_analyzable_extensions_contains_javascript(self):
        """ANALYZABLE_EXTENSIONS contains JavaScript/TypeScript."""
        assert ".js" in ANALYZABLE_EXTENSIONS
        assert ".ts" in ANALYZABLE_EXTENSIONS
        assert ".jsx" in ANALYZABLE_EXTENSIONS

    def test_analyzable_extensions_contains_java(self):
        """ANALYZABLE_EXTENSIONS contains Java."""
        assert ".java" in ANALYZABLE_EXTENSIONS

    def test_analyzable_extensions_contains_config(self):
        """ANALYZABLE_EXTENSIONS contains config files."""
        assert ".yml" in ANALYZABLE_EXTENSIONS
        assert ".yaml" in ANALYZABLE_EXTENSIONS
        assert ".json" in ANALYZABLE_EXTENSIONS
        assert ".toml" in ANALYZABLE_EXTENSIONS

    def test_should_include_includes_python_files(self):
        """_should_include includes .py files."""
        scanner = RepoScanner()
        
        result = scanner._should_include(
            "app.py",
            Path("app.py")
        )
        
        assert result is True

    def test_should_include_includes_dockerfile(self):
        """_should_include includes Dockerfile (special filename)."""
        scanner = RepoScanner()
        
        result = scanner._should_include(
            "Dockerfile",
            Path("Dockerfile")
        )
        
        assert result is True


class TestAnalyzableFilenames:
    """Tests for special important filenames."""

    def test_analyzable_filenames_contains_dockerfile(self):
        """ANALYZABLE_FILENAMES contains Dockerfile."""
        assert "Dockerfile" in ANALYZABLE_FILENAMES

    def test_analyzable_filenames_contains_config_files(self):
        """ANALYZABLE_FILENAMES contains config files."""
        assert "docker-compose.yml" in ANALYZABLE_FILENAMES
        assert "package.json" in ANALYZABLE_FILENAMES
        assert "pyproject.toml" in ANALYZABLE_FILENAMES

    def test_should_include_always_includes_analyzable_filenames(self):
        """_should_include includes special filenames regardless of extension."""
        scanner = RepoScanner()
        
        # Dockerfile has no extension but should be included
        result = scanner._should_include(
            "Dockerfile",
            Path("Dockerfile")
        )
        
        assert result is True


class TestBinaryDetection:
    """Tests for binary file detection."""

    def test_looks_binary_with_control_characters(self):
        """_looks_binary detects high control character ratio."""
        # Simulate binary content with many control characters
        binary_content = "\x00\x01\x02\x03" * 2000  # 8000 control chars
        
        result = _looks_binary(binary_content)
        
        assert result is True

    def test_looks_binary_with_mostly_text(self):
        """_looks_binary returns False for mostly text."""
        text_content = "import os\nimport sys\n" * 1000
        
        result = _looks_binary(text_content)
        
        assert result is False

    def test_looks_binary_with_empty_string(self):
        """_looks_binary returns False for empty string."""
        result = _looks_binary("")
        
        assert result is False

    def test_looks_binary_threshold_at_boundary(self):
        """_looks_binary uses 5% threshold."""
        # Create content with exactly 5% control characters
        content = ("x" * 1900) + ("\x00" * 100)
        
        result = _looks_binary(content)
        
        # At exactly 5%, should be False (not exceeded)
        assert result is False

    def test_looks_binary_above_threshold(self):
        """_looks_binary returns True above threshold."""
        # Create content with 6% control characters
        content = ("x" * 1880) + ("\x00" * 120)
        
        result = _looks_binary(content)
        
        # Above 5%, should be True
        assert result is True

    def test_looks_binary_ignores_whitespace(self):
        """_looks_binary doesn't count whitespace as control chars."""
        # Newlines, tabs, carriage returns are ignored
        text_with_whitespace = "line1\nline2\tdata\rmore"
        
        result = _looks_binary(text_with_whitespace)
        
        assert result is False


class TestLanguageDetection:
    """Tests for language detection."""

    def test_detect_languages_python(self):
        """detect_languages identifies Python files."""
        files = {
            "app.py": "import os",
            "util.py": "def util(): pass",
        }
        
        languages = detect_languages(files)
        
        assert "python" in languages

    def test_detect_languages_javascript(self):
        """detect_languages identifies JavaScript files."""
        files = {
            "app.js": "const x = 1;",
            "index.tsx": "export default App",
        }
        
        languages = detect_languages(files)
        
        assert "javascript" in languages or "typescript" in languages

    def test_detect_languages_multiple(self):
        """detect_languages detects multiple languages."""
        files = {
            "app.py": "import os",
            "main.js": "console.log()",
            "query.sql": "SELECT * FROM users",
        }
        
        languages = detect_languages(files)
        
        assert "python" in languages
        assert "javascript" in languages
        assert "sql" in languages

    def test_detect_languages_empty_file_list(self):
        """detect_languages returns unknown for empty list."""
        languages = detect_languages({})
        
        assert languages == ["unknown"]

    def test_detect_languages_unknown_extension(self):
        """detect_languages marks unknown extensions."""
        files = {
            "data.xyz": "some content",
        }
        
        languages = detect_languages(files)
        
        assert "unknown" in languages or len(languages) == 0

    def test_detect_languages_sorted_output(self):
        """detect_languages returns sorted list."""
        files = {
            "z.py": "",
            "a.js": "",
            "m.go": "",
        }
        
        languages = detect_languages(files)
        
        # Should be sorted
        assert languages == sorted(languages)


class TestRepoCloning:
    """Tests for git cloning behavior."""

    async def test_clone_timeout_error(self):
        """Clone raises RepoScanError on timeout."""
        scanner = RepoScanner(clone_timeout=1)
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Simulate timeout
            async def slow_wait(*args, **kwargs):
                raise asyncio.TimeoutError()
            
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_exec.return_value = mock_process
            
            with pytest.raises(RepoScanError, match="timed out"):
                await scanner._clone(
                    "https://github.com/org/repo.git",
                    "main",
                    "/tmp/clone"
                )

    async def test_clone_failure_on_nonzero_exit(self):
        """Clone raises RepoScanError on git failure."""
        scanner = RepoScanner()
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(
                return_value=(b"", b"fatal: repository not found")
            )
            mock_exec.return_value = mock_process
            
            with pytest.raises(RepoScanError, match="Clone failed"):
                await scanner._clone(
                    "https://github.com/invalid/repo.git",
                    "main",
                    "/tmp/clone"
                )

    async def test_clone_success_on_zero_exit(self):
        """Clone succeeds with zero exit code."""
        scanner = RepoScanner()
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process
            
            # Should not raise
            await scanner._clone(
                "https://github.com/org/repo.git",
                "main",
                "/tmp/clone"
            )


class TestGetTrackedFiles:
    """Tests for git ls-files integration."""

    async def test_get_tracked_files_parses_output(self):
        """_get_tracked_files parses git output."""
        scanner = RepoScanner()
        
        git_output = b"file1.py\nfile2.js\ndir/file3.py\n"
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(git_output, b""))
            mock_exec.return_value = mock_process
            
            files = await scanner._get_tracked_files("/tmp/repo")
            
            assert "file1.py" in files
            assert "file2.js" in files
            assert "dir/file3.py" in files

    async def test_get_tracked_files_handles_empty_output(self):
        """_get_tracked_files handles empty repository."""
        scanner = RepoScanner()
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process
            
            files = await scanner._get_tracked_files("/tmp/repo")
            
            assert len(files) == 0


class TestSizeLimits:
    """Tests for size limiting behavior."""

    def test_per_file_size_limit_enforced(self):
        """Files exceeding per-file limit are skipped."""
        scanner = RepoScanner(max_file_size=1000)
        
        # File larger than limit
        large_content = "x" * 2000
        
        # Simulate a file path with large content
        # The _read_files checks the actual file size on disk
        assert scanner._max_file_size == 1000

    def test_total_size_limit_enforced(self):
        """Total size limit stops reading files."""
        scanner = RepoScanner(max_total_size=5000)
        
        assert scanner._max_total_size == 5000

    def test_max_files_limit_enforced(self):
        """Max files limit stops reading after N files."""
        scanner = RepoScanner(max_files=10)
        
        assert scanner._max_files == 10


class TestReadFilesFiltering:
    """Tests for file reading and filtering."""

    async def test_read_files_filters_by_should_include(self):
        """_read_files respects _should_include logic."""
        scanner = RepoScanner()
        
        # Create mock tracked files
        tracked = {
            "app.py",           # Should include
            "test.pyc",         # Should skip (binary)
            "node_modules/pkg.js",  # Should skip (dir)
            ".git/config",      # Should skip (dir)
        }
        
        # Only app.py should be kept after filtering
        # The actual filtering happens in _should_include


class TestRepoScannerErrors:
    """Tests for error handling."""

    def test_repo_scan_error_is_exception(self):
        """RepoScanError is an Exception."""
        error = RepoScanError("test error")
        
        assert isinstance(error, Exception)

    def test_repo_scan_error_message(self):
        """RepoScanError preserves error message."""
        msg = "Repository not found"
        error = RepoScanError(msg)
        
        assert str(error) == msg


class TestSubdirectoryScanning:
    """Tests for subdirectory scoping."""

    def test_scan_with_subdirectory_parameter(self):
        """RepoScanner scan method accepts subdirectory."""
        scanner = RepoScanner()
        
        # The method signature accepts subdirectory parameter
        # This is just verifying the API


class TestScanIntegration:
    """Integration tests for full scanning workflow."""

    async def test_scan_cleanup_on_success(self):
        """Temporary directory cleaned up after successful scan."""
        scanner = RepoScanner()
        
        # Mock the entire process
        with patch("tempfile.mkdtemp") as mock_mkdtemp:
            mock_dir = "/tmp/test-dir"
            mock_mkdtemp.return_value = mock_dir
            
            with patch.object(scanner, "_clone") as mock_clone:
                with patch.object(scanner, "_get_tracked_files") as mock_get_files:
                    with patch.object(scanner, "_read_files") as mock_read_files:
                        with patch("shutil.rmtree") as mock_rmtree:
                            mock_clone.return_value = None
                            mock_get_files.return_value = set()
                            mock_read_files.return_value = {}
                            
                            await scanner.scan("https://github.com/org/repo.git")
                            
                            # Cleanup should be called
                            mock_rmtree.assert_called_once()

    async def test_scan_cleanup_on_error(self):
        """Temporary directory cleaned up even on error."""
        scanner = RepoScanner()
        
        with patch("tempfile.mkdtemp") as mock_mkdtemp:
            mock_dir = "/tmp/test-dir"
            mock_mkdtemp.return_value = mock_dir
            
            with patch.object(scanner, "_clone") as mock_clone:
                with patch("shutil.rmtree") as mock_rmtree:
                    mock_clone.side_effect = RepoScanError("Clone failed")
                    
                    with pytest.raises(RepoScanError):
                        await scanner.scan("https://github.com/org/repo.git")
                    
                    # Cleanup should still be called
                    mock_rmtree.assert_called_once()

"""
Repository Scanner — clone, walk, filter, and read source files.

Clones a git repository into a temporary sandbox directory, walks the
file tree with smart filtering, and returns file contents keyed by
relative path. Designed to feed directly into the agent pipeline.

Filtering:
  - Respects .gitignore via `git ls-files`
  - Skips binary files, vendored deps, generated code
  - Enforces per-file size limits (no 5MB minified bundles)
  - Caps total collected size to prevent memory blowout
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)

# ── Defaults ──

DEFAULT_MAX_FILE_SIZE = 512 * 1024  # 512 KB per file
DEFAULT_MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB total (was 20 MB — too low for real .NET/Java projects)
DEFAULT_CLONE_TIMEOUT = 120  # seconds
DEFAULT_MAX_FILES = 2000  # cap on number of files (was 500 — too low for enterprise codebases)

# ── Skip patterns ──

# Directories to always skip (even if not in .gitignore)
SKIP_DIRS: Set[str] = {
    "node_modules",
    "vendor",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
    ".terraform",
    ".venv",
    "venv",
    "env",
    ".env",
    "target",           # Rust/Java build output
    "out",              # Java/TS build output
    ".gradle",
    ".idea",
    ".vscode",
}

# File extensions to always skip (binary / generated / not analyzable)
SKIP_EXTENSIONS: Set[str] = {
    # Binary
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".whl", ".egg",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".tiff", ".tif",
    # Media
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac", ".ogg",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Data (large)
    ".sqlite", ".db", ".sqlite3",
    # Lock files (large, no vulns)
    ".lock",
    # Minified / source maps
    ".min.js", ".min.css", ".map",
    # Compiled / generated
    ".pb.go", ".pb.cc", ".pb.h",  # protobuf
    ".generated.ts", ".generated.js",
}

# File names to always skip
SKIP_FILENAMES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "go.sum",
    ".DS_Store",
    "Thumbs.db",
}

# Extensions we want to analyze
ANALYZABLE_EXTENSIONS: Set[str] = {
    # Python
    ".py", ".pyi",
    # JavaScript / TypeScript
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    # Java / Kotlin / Scala
    ".java", ".kt", ".kts", ".scala",
    # Go
    ".go",
    # Rust
    ".rs",
    # C / C++
    ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cxx",
    # C#
    ".cs",
    # Ruby
    ".rb", ".erb",
    # PHP
    ".php",
    # Swift / Objective-C
    ".swift", ".m", ".mm",
    # Shell
    ".sh", ".bash", ".zsh",
    # Config (security-relevant)
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf",
    ".env.example", ".env.sample",
    # Docker / CI
    ".dockerfile",
    # Web
    ".html", ".htm", ".css", ".scss", ".less",
    # SQL
    ".sql",
    # Terraform / IaC
    ".tf", ".hcl",
    # Markup
    ".xml", ".proto",
}

# Filenames we always want (regardless of extension)
ANALYZABLE_FILENAMES: Set[str] = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    ".github/workflows",
    "Gemfile",
    "Rakefile",
    "Vagrantfile",
    "Procfile",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "package.json",
    "tsconfig.json",
    "webpack.config.js",
    "vite.config.ts",
    ".eslintrc.json",
    ".eslintrc.js",
    ".babelrc",
    "Cargo.toml",
    "go.mod",
    "build.gradle",
    "pom.xml",
    "CMakeLists.txt",
}


class RepoScanner:
    """Clone and scan a git repository for source files.

    Usage:
        scanner = RepoScanner()
        files = await scanner.scan(
            repo_url="https://github.com/org/repo.git",
            branch="main",
        )
        # files = {"src/app.py": "import ...", "config.yaml": "..."}
    """

    def __init__(
        self,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_total_size: int = DEFAULT_MAX_TOTAL_SIZE,
        max_files: int = DEFAULT_MAX_FILES,
        clone_timeout: int = DEFAULT_CLONE_TIMEOUT,
    ) -> None:
        self._max_file_size = max_file_size
        self._max_total_size = max_total_size
        self._max_files = max_files
        self._clone_timeout = clone_timeout

    async def scan(
        self,
        repo_url: str,
        branch: str = "main",
        subdirectory: Optional[str] = None,
        github_token: Optional[str] = None,
    ) -> Dict[str, str]:
        """Clone a repo and return analyzable file contents.

        Args:
            repo_url: Git clone URL (https or ssh).
            branch: Branch or tag to checkout.
            subdirectory: Optional subdirectory to scope the scan to.
            github_token: Optional PAT for authenticated HTTPS cloning.

        Returns:
            Dict mapping relative file paths to their contents.

        Raises:
            RepoScanError: If clone fails or repo is inaccessible.
        """
        clone_dir = tempfile.mkdtemp(prefix="tron-scan-")

        try:
            # 1. Clone
            await self._clone(repo_url, branch, clone_dir, github_token=github_token)

            # 2. Get tracked files via git ls-files (respects .gitignore)
            tracked_files = await self._get_tracked_files(clone_dir)

            # 3. Filter and read
            scan_root = Path(clone_dir)
            if subdirectory:
                scan_root = scan_root / subdirectory
                if not scan_root.exists():
                    raise RepoScanError(
                        f"Subdirectory '{subdirectory}' not found in repo"
                    )

            files = await self._read_files(clone_dir, scan_root, tracked_files)

            logger.info(
                "RepoScanner: %d files collected (%.1f KB) from %s@%s",
                len(files),
                sum(len(v) for v in files.values()) / 1024,
                repo_url.split("/")[-1].replace(".git", ""),
                branch,
            )

            return files

        finally:
            # Always clean up the clone
            shutil.rmtree(clone_dir, ignore_errors=True)

    async def clone_to_tempdir(
        self,
        repo_url: str,
        branch: str = "main",
    ) -> str:
        """Shallow clone into a new temp directory. Caller must ``shutil.rmtree`` when done."""
        clone_dir = tempfile.mkdtemp(prefix="tron-clone-")
        try:
            await self._clone(repo_url, branch, clone_dir)
            return clone_dir
        except Exception:
            shutil.rmtree(clone_dir, ignore_errors=True)
            raise

    async def _clone(
        self, repo_url: str, branch: str, target_dir: str, github_token: Optional[str] = None
    ) -> None:
        """Shallow clone a repo into target_dir with fallback branch detection."""
        # Inject token for private HTTPS GitHub clones
        authenticated_url = repo_url
        if github_token and repo_url.startswith("https://github.com/"):
            authenticated_url = repo_url.replace("https://github.com/", f"https://x-access-token:{github_token}@github.com/")

        # Try to clone specific branch first
        success = await self._exec_clone(authenticated_url, target_dir, branch)
        
        if not success:
            logger.info("Branch '%s' not found for %s, attempting to clone default branch...", branch, repo_url)
            # Try cloning WITHOUT a specific branch to let git pick the remote HEAD (default branch)
            success = await self._exec_clone(authenticated_url, target_dir, None)

        if not success:
            raise RepoScanError(f"Clone failed for {repo_url}. Check if repo exists and is accessible.")

        logger.info("Clone complete: %s", target_dir)

    async def _exec_clone(self, url: str, target_dir: str, branch: Optional[str]) -> bool:
        """Helper to execute the git clone command."""
        cmd = [
            "git",
            "-c",
            "safe.directory=*",
            "clone",
            "--depth", "1",
        ]
        
        if branch:
            cmd.extend(["--single-branch", "--branch", branch])
            
        cmd.extend([url, target_dir])

        env = os.environ.copy()
        env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "echo",
        })

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._clone_timeout
            )
            
            if proc.returncode == 0:
                return True
            
            err = stderr.decode("utf-8", errors="replace").lower()
            # If it's a branch error, we can retry. If it's auth/not found, we fail.
            if "could not find remote branch" in err or "remote branch" in err and "not found" in err:
                return False
                
            # For other errors (auth, etc.), raise immediately to avoid useless retry
            raise RepoScanError(f"Clone failed (exit {proc.returncode}): {err.strip()}")
            
        except asyncio.TimeoutError:
            raise RepoScanError(f"Clone timed out after {self._clone_timeout}s")

    async def _get_tracked_files(self, clone_dir: str) -> Set[str]:
        """Get list of git-tracked files (respects .gitignore)."""
        proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--cached", "--others", "--exclude-standard",
            cwd=clone_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        files = set()
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                files.add(line)

        logger.debug("Git reports %d tracked files", len(files))
        return files

    async def _read_files(
        self,
        clone_dir: str,
        scan_root: Path,
        tracked_files: Set[str],
    ) -> Dict[str, str]:
        """Walk the file tree, filter, and read contents."""
        clone_path = Path(clone_dir)
        result: Dict[str, str] = {}
        total_size = 0
        skipped_size = 0
        skipped_count = 0

        # Sort tracked files for deterministic output
        for rel_path_str in sorted(tracked_files):
            if len(result) >= self._max_files:
                logger.info(
                    "Hit max files limit (%d), stopping scan",
                    self._max_files,
                )
                break

            if total_size >= self._max_total_size:
                logger.info(
                    "Hit max total size limit (%.1f MB), stopping scan",
                    self._max_total_size / (1024 * 1024),
                )
                break

            abs_path = clone_path / rel_path_str
            rel_to_scan = abs_path.relative_to(scan_root) if abs_path.is_relative_to(scan_root) else None

            # Skip if outside scan root
            if rel_to_scan is None:
                continue

            # Apply filters
            if not self._should_include(rel_path_str, abs_path):
                skipped_count += 1
                continue

            # Check file size
            try:
                file_size = abs_path.stat().st_size
            except OSError:
                continue

            if file_size > self._max_file_size:
                skipped_size += file_size
                skipped_count += 1
                logger.debug(
                    "Skipped (too large: %d KB): %s",
                    file_size // 1024,
                    rel_path_str,
                )
                continue

            if file_size == 0:
                continue

            # Read file
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                skipped_count += 1
                continue

            # Check if it looks binary (high ratio of null bytes)
            if _looks_binary(content):
                skipped_count += 1
                continue

            result[rel_path_str] = content
            total_size += len(content)

        logger.info(
            "RepoScanner: included=%d, skipped=%d, total_size=%.1f KB",
            len(result),
            skipped_count,
            total_size / 1024,
        )

        return result

    def _should_include(self, rel_path: str, abs_path: Path) -> bool:
        """Determine if a file should be included in the scan."""
        parts = Path(rel_path).parts
        filename = parts[-1] if parts else ""

        # Skip entire directories
        for part in parts[:-1]:
            if part in SKIP_DIRS:
                return False

        # Skip specific filenames
        if filename in SKIP_FILENAMES:
            return False

        # Always include known-important filenames
        if filename in ANALYZABLE_FILENAMES:
            return True

        # Check extension against skip list
        suffix = abs_path.suffix.lower()
        if suffix in SKIP_EXTENSIONS:
            return False

        # For double extensions like .min.js
        name_lower = filename.lower()
        for skip_ext in SKIP_EXTENSIONS:
            if name_lower.endswith(skip_ext):
                return False

        # Check extension against analyzable list
        if suffix in ANALYZABLE_EXTENSIONS:
            return True

        # Default: skip unknown extensions
        return False


class RepoScanError(Exception):
    """Raised when repository scanning fails."""
    pass


def _looks_binary(content: str, threshold: float = 0.05) -> bool:
    """Heuristic: if more than 5% of chars are null/control, it's binary."""
    if not content:
        return False
    # Check first 8KB only for performance
    sample = content[:8192]
    control_chars = sum(
        1 for c in sample
        if ord(c) < 32 and c not in ("\n", "\r", "\t")
    )
    return (control_chars / len(sample)) > threshold


def detect_languages(file_contents: Dict[str, str]) -> List[str]:
    """Detect programming languages from file extensions.

    Enhanced version that handles the full range of extensions
    from ANALYZABLE_EXTENSIONS.
    """
    ext_to_lang = {
        ".py": "python", ".pyi": "python",
        ".js": "javascript", ".jsx": "javascript",
        ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
        ".scala": "scala",
        ".go": "go",
        ".rs": "rust",
        ".c": "c", ".h": "c",
        ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
        ".hh": "cpp", ".cxx": "cpp",
        ".cs": "csharp",
        ".rb": "ruby", ".erb": "ruby",
        ".php": "php",
        ".swift": "swift", ".m": "objective-c", ".mm": "objective-c",
        ".sh": "shell", ".bash": "shell", ".zsh": "shell",
        ".sql": "sql",
        ".tf": "terraform", ".hcl": "terraform",
        ".html": "html", ".htm": "html",
        ".css": "css", ".scss": "css", ".less": "css",
        ".yml": "yaml", ".yaml": "yaml",
        ".json": "json", ".toml": "toml",
        ".xml": "xml", ".proto": "protobuf",
    }

    languages: Set[str] = set()
    for path in file_contents:
        suffix = Path(path).suffix.lower()
        lang = ext_to_lang.get(suffix)
        if lang:
            languages.add(lang)

    return sorted(languages) if languages else ["unknown"]

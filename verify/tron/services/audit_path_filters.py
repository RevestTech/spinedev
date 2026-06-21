"""Project-level path filters for scans (SEC-3): exclude globs and test-path tagging."""
from __future__ import annotations

import fnmatch
import re
from typing import Dict, List, Optional, Sequence


def _normalize_path(p: str) -> str:
    return p.replace("\\", "/").lstrip("/")


def _pattern_variants(pat: str) -> List[str]:
    s = {pat}
    if pat.startswith("**/"):
        s.add(pat[3:])
    return list(s)


def _path_matches_glob_one(path: str, pat: str) -> bool:
    """One glob variant: `**` = any path segment chain; `*` = within a segment (no /)."""
    if "**" not in pat:
        return fnmatch.fnmatch(path, pat)
    ph = "@@@DS@@@"
    p = pat.replace("**", ph)
    p = re.escape(p)
    p = p.replace(ph, ".*")
    p = p.replace(r"\*", "[^/]*")
    return re.match("^" + p + "$", path) is not None


def path_matches_glob(path: str, pattern: str) -> bool:
    """Match a repo-relative *path* against a glob (* and ** allowed)."""
    path = _normalize_path(path)
    for pat in _pattern_variants(_normalize_path(pattern)):
        if _path_matches_glob_one(path, pat):
            return True
    return False


def path_matches_any(path: str, patterns: Optional[Sequence[str]]) -> bool:
    if not patterns:
        return False
    for p in patterns:
        if p and str(p).strip() and path_matches_glob(path, str(p).strip()):
            return True
    return False


def filter_file_contents(
    file_contents: Dict[str, str], exclude_globs: Optional[Sequence[str]]
) -> Dict[str, str]:
    if not exclude_globs:
        return file_contents
    return {k: v for k, v in file_contents.items() if not path_matches_any(k, exclude_globs)}


def classify_path_role(path: str, test_globs: Optional[Sequence[str]]) -> Optional[str]:
    if test_globs and path_matches_any(path, test_globs):
        return "test"
    return None

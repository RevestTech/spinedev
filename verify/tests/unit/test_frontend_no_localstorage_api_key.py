"""
Regression guard: the browser SPA must not store API keys in localStorage.

P0 security fix — the previous ``frontend/src/api.ts`` kept the master key in
``localStorage['tron-api-key']`` and attached it as ``X-API-Key`` on every
request. Any script that ran in the page (XSS, hostile dependency, extension)
could pull the key straight back out. Auth now rides the httpOnly admin session
cookie instead, and this test makes sure nobody accidentally brings the
localStorage path back.

We scan the frontend source trees for banned patterns. The one-shot migration
helper in ``frontend/src/api.ts`` (``localStorage.removeItem('tron-api-key')``)
is explicitly allowed — it exists to scrub stale keys from older builds.
Non-secret client-side state (the PlanWizard plan-draft autosave) is also
allowed via an explicit per-file allowlist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOTS = [
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "admin-ui" / "src",
]
SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".html"}

# Patterns that indicate API-key material being persisted to browser storage.
# Anything matching these must stay out of the SPA code.
FORBIDDEN_KEY_STORAGE = (
    "tron-api-key",  # legacy storage key
    "tron_api_key",
)

# Files allowed to mention the banned strings (comments, migration scrubs,
# this test itself). Anything new that needs to land here should come with a
# justification in the diff.
COMMENT_OR_MIGRATION_ALLOWLIST = {
    # One-shot scrubber + explanatory doc comment:
    REPO_ROOT / "frontend" / "src" / "api.ts",
}

# Non-secret client-side state allowlist — files here may call localStorage
# but must not be storing API keys or other secrets.
NON_SECRET_LOCALSTORAGE_ALLOWLIST = {
    # PlanWizard autosaves the questionnaire form as a debounce-draft; it is
    # not sensitive and is keyed per project.
    REPO_ROOT / "frontend" / "src" / "pages" / "PlanWizard.tsx",
    # Migration helper in api.ts only calls removeItem.
    REPO_ROOT / "frontend" / "src" / "api.ts",
}


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root in FRONTEND_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in SOURCE_EXTS:
                # Skip node_modules/dist if they somehow leak under src.
                if any(part in {"node_modules", "dist", "build"} for part in p.parts):
                    continue
                files.append(p)
    return files


def test_frontend_has_no_api_key_in_localstorage() -> None:
    """No SPA file may persist an API key to browser storage."""
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for needle in FORBIDDEN_KEY_STORAGE:
                if needle in line and path not in COMMENT_OR_MIGRATION_ALLOWLIST:
                    offenders.append((path.relative_to(REPO_ROOT), lineno, line.strip()))

    assert not offenders, (
        "API-key-like identifiers found in the SPA. Auth must ride the httpOnly "
        "admin session cookie, never localStorage. Offenders:\n"
        + "\n".join(f"  {p}:{lineno}  {snippet}" for p, lineno, snippet in offenders)
    )


def test_frontend_setItem_not_used_for_api_keys() -> None:
    """No setItem call may mention key-ish identifiers outside the allowlist."""
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_source_files():
        if path in NON_SECRET_LOCALSTORAGE_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if (".setitem(" in low or "sessionstorage.setitem(" in low) and (
                "key" in low or "token" in low or "secret" in low or "auth" in low
            ):
                offenders.append((path.relative_to(REPO_ROOT), lineno, line.strip()))

    assert not offenders, (
        "Suspicious browser-storage writes touching an auth-like identifier. "
        "If this is non-secret state, add the file to "
        "NON_SECRET_LOCALSTORAGE_ALLOWLIST with a comment explaining why. "
        "Offenders:\n"
        + "\n".join(f"  {p}:{lineno}  {snippet}" for p, lineno, snippet in offenders)
    )


def test_ws_connect_does_not_embed_api_key_in_query_string() -> None:
    """WS URLs must not carry the API key as ?token= — it leaks to logs."""
    ws_file = REPO_ROOT / "frontend" / "src" / "api.ts"
    if not ws_file.exists():  # pragma: no cover - only hit in partial checkouts
        pytest.skip("frontend/src/api.ts not present in this checkout")
    text = ws_file.read_text(encoding="utf-8")
    # Flag the specific leak shape: ``?token=${...apiKey...}`` or equivalent.
    for needle in ("?token=${encodeURIComponent(", "?token=${key", "?token=${getApiKey"):
        assert needle not in text, (
            f"frontend/src/api.ts still builds a WS URL with {needle!r}. The WS "
            "upgrade carries the session cookie; do not attach the API key in "
            "the query string (query-string secrets leak into proxy logs and "
            "browser history)."
        )

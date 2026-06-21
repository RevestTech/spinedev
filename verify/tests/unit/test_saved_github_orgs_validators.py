"""Pydantic + regex validation for the saved-github-orgs payload.

We do NOT exercise the route here — the route's GitHub-existence check
talks to a real httpx client and is covered by an integration test.
This file pins the *input contract* the route depends on so that
adversarial inputs (path traversal, oversized strings, leading
whitespace, double slashes) get rejected before the GitHub call ever
fires.
"""

from __future__ import annotations

import pytest

from tron.api.routes.integrations import (
    SavedGithubOrgCreate,
    _GITHUB_LOGIN_RE,
)


# ── Login regex ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "login",
    [
        "anthropic",
        "Anthropic",
        "khash-anthropic",
        "a",                     # single-char allowed by GitHub
        "github1",
        "AB-CD-EF",
    ],
)
def test_login_regex_accepts_valid(login: str) -> None:
    assert _GITHUB_LOGIN_RE.match(login)


@pytest.mark.parametrize(
    "login",
    [
        "",
        "-leading",
        "trailing-",
        "with space",
        "slash/in/middle",
        "dotted.login",
        "a" * 40,                # > 39 chars
        "you@github",
    ],
)
def test_login_regex_rejects_invalid(login: str) -> None:
    """The regex's purpose is to prevent URL-path injection, not to mirror
    every GitHub signup rule — consecutive hyphens, for example, do show
    up in some legacy accounts. Keep this list focused on shapes that
    would actually break /orgs/{login}/repos."""
    assert not _GITHUB_LOGIN_RE.match(login)


# ── SavedGithubOrgCreate validator ───────────────────────────────────

def test_create_normalises_login_to_lowercase() -> None:
    """The unique-login index in the DB is on ``lower(login)``; the
    Pydantic validator MUST normalise so the index actually enforces."""
    body = SavedGithubOrgCreate(login="Anthropic")
    assert body.login == "anthropic"


def test_create_strips_surrounding_slashes_and_whitespace() -> None:
    """Users sometimes paste the URL fragment ``/anthropic/`` from a
    browser address bar — accept that gracefully."""
    body = SavedGithubOrgCreate(login="  /anthropic/  ")
    assert body.login == "anthropic"


def test_create_rejects_path_traversal() -> None:
    """A login containing a slash would smuggle an extra path segment
    into ``/orgs/{login}/repos`` — must be rejected before persisting."""
    with pytest.raises(Exception):  # pydantic.ValidationError
        SavedGithubOrgCreate(login="anthropic/../admin")


def test_create_rejects_empty() -> None:
    with pytest.raises(Exception):
        SavedGithubOrgCreate(login="")


def test_create_strips_blank_display_name_to_none() -> None:
    """Empty / whitespace-only display_name should become None so the
    UI's ``display_name || login`` fallback works."""
    body = SavedGithubOrgCreate(login="anthropic", display_name="   ")
    assert body.display_name is None


def test_create_preserves_real_display_name() -> None:
    body = SavedGithubOrgCreate(login="anthropic", display_name="  Anthropic, Inc.  ")
    assert body.display_name == "Anthropic, Inc."


def test_create_pinned_defaults_false() -> None:
    body = SavedGithubOrgCreate(login="anthropic")
    assert body.pinned is False


def test_create_login_too_long_rejected() -> None:
    """Field max_length=100 protects the DB column; the regex enforces
    GitHub's stricter 39-char limit. Both belt and braces."""
    with pytest.raises(Exception):
        SavedGithubOrgCreate(login="a" * 101)

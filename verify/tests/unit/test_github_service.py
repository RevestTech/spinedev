"""GitHubService helpers."""

from tron.services.github_service import normalize_github_pat


def test_normalize_github_pat_strips_bearer_prefix():
    assert normalize_github_pat("Bearer ghp_abc123") == "ghp_abc123"
    assert normalize_github_pat("bearer ghp_x") == "ghp_x"


def test_normalize_github_pat_strips_quotes_and_space():
    assert normalize_github_pat('  "ghp_x"  ') == "ghp_x"
    assert normalize_github_pat(None) is None
    assert normalize_github_pat("   ") is None

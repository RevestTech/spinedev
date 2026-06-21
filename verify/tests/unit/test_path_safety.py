"""
Unit tests for ``tron.services.path_safety``.

These are the primitives used to sanity-check user-supplied filesystem
paths (agent handoff destinations, repo-scanner reads). If any of these
behaviours regress, the two higher-level consumers (M2 + M3) regress too.
"""

from __future__ import annotations

import os

import pytest

from tron.services.path_safety import (
    UnsafePathError,
    open_no_follow,
    parse_allowed_roots,
    resolve_under_allowlist,
)


# ── parse_allowed_roots ───────────────────────────────────────────────────


class TestParseAllowedRoots:
    def test_empty_string_returns_empty_tuple(self):
        assert parse_allowed_roots("") == ()

    def test_none_returns_empty_tuple(self):
        assert parse_allowed_roots(None) == ()

    def test_single_absolute_path_is_canonicalised(self, tmp_path):
        roots = parse_allowed_roots(str(tmp_path))
        assert roots == (tmp_path.resolve(),)

    def test_multiple_comma_separated_paths(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        roots = parse_allowed_roots(f"{a}, {b}")
        assert set(roots) == {a.resolve(), b.resolve()}

    def test_whitespace_and_empty_entries_ignored(self, tmp_path):
        roots = parse_allowed_roots(f" , ,,  {tmp_path}  ,,  ")
        assert roots == (tmp_path.resolve(),)

    def test_relative_path_rejected_loudly(self):
        # Operator typo — not a silent downgrade to CWD-relative.
        with pytest.raises(UnsafePathError, match="not an absolute path"):
            parse_allowed_roots("not/absolute")


# ── resolve_under_allowlist ───────────────────────────────────────────────


class TestResolveUnderAllowlist:
    def test_empty_allowlist_refuses_everything(self, tmp_path):
        # Fail-closed default — the handoff setting is OFF unless an operator
        # explicitly opts in.
        with pytest.raises(UnsafePathError, match="no allowlist roots"):
            resolve_under_allowlist(str(tmp_path), ())

    def test_happy_path_absolute_under_root(self, tmp_path):
        sub = tmp_path / "handoffs" / "proj-a"
        sub.mkdir(parents=True)
        resolved = resolve_under_allowlist(str(sub), [tmp_path])
        assert resolved == sub.resolve()

    def test_relative_path_refused(self, tmp_path):
        with pytest.raises(UnsafePathError, match="not absolute"):
            resolve_under_allowlist("etc/passwd", [tmp_path])

    def test_empty_path_refused(self, tmp_path):
        with pytest.raises(UnsafePathError, match="empty"):
            resolve_under_allowlist("   ", [tmp_path])

    def test_parent_escape_is_rejected(self, tmp_path):
        # Classic ``../../etc/passwd`` dance.
        roots = [tmp_path / "handoffs"]
        (tmp_path / "handoffs").mkdir()
        escape = tmp_path / "handoffs" / ".." / ".." / "etc" / "passwd"
        with pytest.raises(UnsafePathError, match="not under any configured"):
            resolve_under_allowlist(str(escape), roots)

    def test_symlink_into_root_that_points_outside_is_rejected(self, tmp_path):
        # Operator allows /allowed-root. Attacker (or buggy caller) places a
        # symlink inside that root pointing at /tmp outside the root. The
        # resolved target must not still be considered safe.
        allowed = tmp_path / "allowed-root"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        malicious_link = allowed / "shortcut"
        malicious_link.symlink_to(outside)

        with pytest.raises(UnsafePathError, match="not under any configured"):
            resolve_under_allowlist(str(malicious_link), [allowed])

    def test_symlink_fully_inside_root_is_allowed(self, tmp_path):
        # Positive control: a symlink that stays within the root should work.
        allowed = tmp_path / "root"
        allowed.mkdir()
        target = allowed / "real"
        target.mkdir()
        link = allowed / "link"
        link.symlink_to(target)

        resolved = resolve_under_allowlist(str(link), [allowed])
        assert resolved == target.resolve()

    def test_non_existent_leaf_is_allowed(self, tmp_path):
        # The handoff writer creates files — the leaf path may not exist
        # yet. This is fine; what matters is the parent chain resolves under
        # the root.
        leaf = tmp_path / "handoffs" / "proj-a" / "not-yet.md"
        # only the first-level dir exists
        (tmp_path / "handoffs").mkdir()
        resolved = resolve_under_allowlist(str(leaf), [tmp_path])
        assert resolved == leaf.resolve()

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        # ~ should expand to $HOME before the absolute check.
        monkeypatch.setenv("HOME", str(tmp_path))
        resolved = resolve_under_allowlist("~/sub", [tmp_path])
        assert resolved == (tmp_path / "sub").resolve()

    def test_multiple_roots_any_match_passes(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        target = b / "file"
        resolved = resolve_under_allowlist(str(target), [a, b])
        assert resolved == target.resolve()


# ── open_no_follow ────────────────────────────────────────────────────────


class TestOpenNoFollow:
    def test_opens_regular_file(self, tmp_path):
        p = tmp_path / "hello.txt"
        p.write_text("hi")
        fd = open_no_follow(p)
        try:
            with os.fdopen(fd, "r", closefd=True) as fh:
                assert fh.read() == "hi"
        except Exception:
            os.close(fd)
            raise

    def test_refuses_symlink_at_leaf(self, tmp_path):
        real = tmp_path / "real.txt"
        real.write_text("secret")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        # O_NOFOLLOW makes os.open raise ELOOP (Linux) / EMLINK (macOS) on
        # a symlink target. We don't care which — just that it raises.
        with pytest.raises(OSError):
            open_no_follow(link)

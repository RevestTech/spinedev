"""
Regression tests for the RepoScanner symlink-safety fix (P1 M3).

Attack shape: a repo under scan commits a symlink whose target is outside
the clone root. ``git ls-files`` reports the symlink as tracked and
``Path.is_relative_to(scan_root)`` passes (the link sits inside the scan
root). The old code then did ``abs_path.read_text()`` which follows the
symlink and returns the contents of the attacker's target — a classic
arbitrary-file-read.

These tests plant such symlinks in temporary "repos" and assert the
scanner refuses to read them.
"""

from __future__ import annotations

import platform

import pytest

from tron.services.repo_scanner import RepoScanner


pytestmark = pytest.mark.skipif(
    platform.system() == "Windows",
    reason="symlink creation on Windows requires developer mode; feature only "
    "matters on Linux/macOS which is what the scanner runs on",
)


@pytest.fixture
def scanner():
    return RepoScanner()


# ── Exfiltration via symlink ─────────────────────────────────────────────


async def test_tracked_symlink_to_outside_file_is_refused(scanner, tmp_path):
    """A symlink inside the repo pointing outside must NOT be read."""
    clone = tmp_path / "clone"
    clone.mkdir()
    # Payload that an attacker would want to exfiltrate.
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SECRETS_THE_SCANNER_SHOULD_NEVER_SEE")
    # The malicious tracked file.
    malicious = clone / "README.md"
    malicious.symlink_to(outside)

    # git would report this as a tracked file.
    tracked = {"README.md"}

    result = await scanner._read_files(str(clone), clone, tracked)

    assert "README.md" not in result, (
        "RepoScanner read a symlinked tracked file — this would leak the "
        "content of the symlink target (anywhere on disk)."
    )
    # And critically — the secret MUST NOT appear anywhere in the result.
    for path, content in result.items():
        assert "SECRETS_THE_SCANNER_SHOULD_NEVER_SEE" not in content, (
            f"Symlink target contents leaked through {path}"
        )


async def test_tracked_symlink_to_inside_file_is_also_refused(scanner, tmp_path):
    """Even symlinks that stay inside the clone are refused — simpler rule.

    We could special-case "symlink stays inside the root" as allowed, but
    the scanner's purpose is to read source files, not follow links. A
    conservative refuse-all policy is easier to audit and matches what
    most security linters do.
    """
    clone = tmp_path / "clone"
    clone.mkdir()
    real = clone / "real.py"
    real.write_text("print('real')")
    link = clone / "link.py"
    link.symlink_to(real)

    tracked = {"real.py", "link.py"}
    result = await scanner._read_files(str(clone), clone, tracked)

    assert "real.py" in result, "regular files must still be read"
    assert "link.py" not in result, "symlinks must not be followed"


async def test_non_symlink_sibling_of_symlink_still_scanned(scanner, tmp_path):
    """One bad symlink must not take down the rest of the scan."""
    clone = tmp_path / "clone"
    clone.mkdir()

    outside = tmp_path / "target"
    outside.write_text("EVIL")
    (clone / "evil.py").symlink_to(outside)
    (clone / "good.py").write_text("print('ok')")
    (clone / "also_good.py").write_text("import os")

    tracked = {"evil.py", "good.py", "also_good.py"}
    result = await scanner._read_files(str(clone), clone, tracked)

    assert "good.py" in result
    assert "also_good.py" in result
    assert "evil.py" not in result
    # And no bleed-through:
    assert all("EVIL" not in c for c in result.values())


async def test_symlink_to_sensitive_absolute_target_refused(scanner, tmp_path):
    """Classic ``./foo.py -> /etc/passwd`` scenario.

    We can't actually point at /etc/passwd from a unit test (may not exist,
    reads may be blocked), so we fabricate a representative-enough
    equivalent under tmp_path and check the same defensive path runs.
    """
    clone = tmp_path / "clone"
    clone.mkdir()
    # Fake "/etc/passwd" — any path outside the clone is equivalent from
    # the scanner's point of view.
    target = tmp_path / "etc-passwd"
    target.write_text("root:x:0:0:...")
    (clone / "login.py").symlink_to(target)

    tracked = {"login.py"}
    result = await scanner._read_files(str(clone), clone, tracked)

    assert result == {}


# ── O_NOFOLLOW defends against TOCTOU swap ───────────────────────────────


async def test_open_no_follow_is_used_for_reads(scanner, tmp_path, monkeypatch):
    """The read site must go through ``open_no_follow`` — verified by
    monkeypatching the symbol and asserting it gets called."""
    from tron.services import repo_scanner as mod

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "ok.py").write_text("x = 1")

    observed = {"calls": 0}
    real_open_no_follow = mod.open_no_follow

    def spy(*args, **kwargs):
        observed["calls"] += 1
        return real_open_no_follow(*args, **kwargs)

    monkeypatch.setattr(mod, "open_no_follow", spy)

    result = await scanner._read_files(str(clone), clone, {"ok.py"})
    assert "ok.py" in result
    assert observed["calls"] >= 1, (
        "open_no_follow must be used for file reads in the scanner — "
        "reverting to Path.read_text reintroduces the TOCTOU window."
    )


# ── Path.read_text must NOT appear in the read loop ──────────────────────


def test_repo_scanner_source_does_not_call_read_text_for_scanned_files():
    """Static guard: if somebody re-introduces ``abs_path.read_text(``
    in the read loop, this test fires. The safe pattern is
    ``open_no_follow`` + ``os.fdopen``.

    We check the whole file, but allow ``read_text`` elsewhere (comments,
    unrelated helpers). The specific banned shape is the one the scanner
    used to have: ``abs_path.read_text(``.
    """
    from pathlib import Path as _Path

    src = (
        _Path(__file__).resolve().parents[2]
        / "tron" / "services" / "repo_scanner.py"
    ).read_text(encoding="utf-8")
    assert "abs_path.read_text(" not in src, (
        "repo_scanner.py must not use ``abs_path.read_text(...)`` — that "
        "follows symlinks. Use the open_no_follow + os.fdopen pattern "
        "already in place."
    )

"""Pre-PR diff-mode audit (#5) — request validation tests.

The route handler itself is integration-tested separately. These are the
edge-validator tests on ``AuditDiffCreate`` — they fire at the request
boundary, before any DB or workflow plumbing runs, and prove the
contract for the GitHub Action sample to depend on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from tron.api.routes.audits import AuditDiffCreate


def _valid_body(**overrides):
    body = {
        "project_id": uuid4(),
        "changed_files": ["src/app.py", "src/lib/utils.ts"],
        "base_ref": "main",
        "head_ref": "feature/x",
    }
    body.update(overrides)
    return body


class TestAuditDiffCreate:
    def test_happy_path_accepts_valid_body(self):
        body = AuditDiffCreate(**_valid_body())
        assert body.changed_files == ["src/app.py", "src/lib/utils.ts"]
        assert body.trigger_type == "pr"  # default
        assert body.branch == "main"  # default

    def test_empty_changed_files_rejected(self):
        with pytest.raises(ValidationError):
            AuditDiffCreate(**_valid_body(changed_files=[]))

    def test_empty_string_in_changed_files_rejected(self):
        with pytest.raises(ValidationError, match="empty"):
            AuditDiffCreate(**_valid_body(changed_files=["src/x.py", ""]))

    def test_traversal_in_changed_files_rejected(self):
        # ``../`` escape attempts must die at the edge — the diff scope is
        # repo-relative only, and the executor's path filter would silently
        # drop these anyway. Loud rejection is better.
        for evil in [
            "../etc/passwd",
            "src/../../etc/passwd",
            "..",
            "../",
        ]:
            with pytest.raises(ValidationError, match="traversal"):
                AuditDiffCreate(**_valid_body(changed_files=["ok.py", evil]))

    def test_absolute_paths_rejected(self):
        with pytest.raises(ValidationError, match="repo-relative"):
            AuditDiffCreate(**_valid_body(
                changed_files=["src/x.py", "/etc/passwd"]
            ))

    def test_max_files_cap_enforced(self):
        # 2001 entries exceeds the max — defensive against DoS-by-huge-PR.
        files = [f"src/{i}.py" for i in range(2001)]
        with pytest.raises(ValidationError):
            AuditDiffCreate(**_valid_body(changed_files=files))

    def test_max_files_cap_boundary_accepted(self):
        # Exactly at the limit (2000) is fine.
        files = [f"src/{i}.py" for i in range(2000)]
        body = AuditDiffCreate(**_valid_body(changed_files=files))
        assert len(body.changed_files) == 2000

    def test_optional_refs(self):
        # Refs are nice-to-have informational fields; the executor
        # functions without them.
        body = AuditDiffCreate(**_valid_body(base_ref=None, head_ref=None))
        assert body.base_ref is None
        assert body.head_ref is None

    def test_trigger_type_overridable(self):
        # Some teams want to distinguish diff-on-merge-queue vs diff-on-PR.
        body = AuditDiffCreate(**_valid_body(trigger_type="merge_queue"))
        assert body.trigger_type == "merge_queue"

    def test_relative_path_with_dots_in_name_is_ok(self):
        # ``..`` is only a traversal when it's a path segment; ``foo..bar.py``
        # as a filename is benign.
        body = AuditDiffCreate(**_valid_body(
            changed_files=["src/foo..bar.py", "src/normal.py"],
        ))
        assert len(body.changed_files) == 2

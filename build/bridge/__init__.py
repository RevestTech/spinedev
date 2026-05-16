"""Spine v1 → v2 bridge package (STORY-7.5.1, REQ-INIT-7 FR-5).

Lets the v2 orchestrator dispatch directives to the legacy bash daemons
in ``lib/`` via the file-bus contract documented in ``PROTOCOL.md``, while
collecting v1 markdown reports back into typed ``BuildArtifact`` payloads.

This package is **additive**: the legacy v1 daemons remain untouched and
keep running. The bridge will be retired once every role daemon emits a
native ``BuildArtifact`` (see ``bridge_README.md`` — Phase C).
"""

from __future__ import annotations

__all__: list[str] = []

"""Build-subsystem runtime hooks that the v1/v2 daemons invoke around sealing.

Daemon-side enforcement layer for STORY-7.3.{1,2,3} (BACKLOG EPIC-7.3) and
PRD §FR-4 (REQ-INIT-7). The role prompts in ``lib/role-prompts/*.md`` already
ask the LLM agent to call the KG MCP tools; this package is what the daemon
runs *itself* so the BuildArtifact's ``kg_impact`` is populated even when the
agent forgets. See ``runtime_README.md`` for the flow + cross-refs.
"""

from __future__ import annotations

__all__: list[str] = []

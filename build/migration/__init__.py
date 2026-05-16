"""build/migration — daemon migration toolkit (lib/ → build/daemons/).

Implements STORY-7.5.1 (move team-agent-daemon), STORY-7.5.2 (move
role-prompts), STORY-7.5.3 (retire lib/ as drained) per REQ-INIT-7 §7.5
FR-5 and docs/ARCHITECTURE.md §6 Phase 4 (incremental drain).

Scripts live alongside this marker; the toolkit is bash-first. See
migration_README.md for the operational runbook.
"""

__all__: list[str] = []

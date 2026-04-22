"""Agent Memory System — semantic learning and context management for ISO agents.

The Agent Memory System enables ISO agents to:
- Learn from past findings, patterns, and human feedback
- Retrieve relevant context via semantic similarity search
- Consolidate and decay memories over time
- Share learned knowledge across projects

Five memory types:
1. FINDING: Learned vulnerability patterns and false positive markers
2. PATTERN: Recognized code patterns and anti-patterns
3. CONTEXT: Project-specific context (tech stack, conventions)
4. DECISION: Past decisions and their outcomes
5. FEEDBACK: Human feedback on agent accuracy

Core components:
- AgentMemory: SQLAlchemy model with pgvector embeddings
- MemoryStore: Main API for storing, recalling, and consolidating memories
- MemoryType: Enum of the 5 memory types
"""

from __future__ import annotations

from tron.memory.models import AgentMemory
from tron.memory.store import MemoryResult, MemoryStore
from tron.memory.types import MEMORY_TYPE_DESCRIPTIONS, MemoryType

__all__ = [
    "AgentMemory",
    "MemoryStore",
    "MemoryResult",
    "MemoryType",
    "MEMORY_TYPE_DESCRIPTIONS",
]

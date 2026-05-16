"""Memory type constants and enumerations for the Agent Memory System."""

from __future__ import annotations

from enum import Enum


class MemoryType(str, Enum):
    """The 5 memory types for agent learning and context.
    
    Each type captures a different aspect of agent knowledge that can be
    retrieved and applied to future tasks.
    """

    FINDING = "finding"
    """Learned vulnerability patterns and false positive markers.
    
    Examples:
    - "XPath injection in dynamic queries is rare; check template safety instead"
    - "False positive: @deprecated decorators in Java cause low-confidence warnings"
    """

    PATTERN = "pattern"
    """Recognized code patterns and anti-patterns.
    
    Examples:
    - "Observable.of().flatMap() pattern indicates RxJava reactive code"
    - "try-with-resources ensures AutoCloseable cleanup"
    """

    CONTEXT = "context"
    """Project-specific context: tech stack, conventions, architecture.
    
    Examples:
    - "Uses Nest.js for backend; middleware in src/common/middleware/"
    - "API versioning via /api/v1, /api/v2 routes"
    """

    DECISION = "decision"
    """Past decisions and their outcomes.
    
    Examples:
    - "Decided NOT to flag console.log in test files: too noisy"
    - "Applied stricter rules in legacy auth module vs new token-based auth"
    """

    FEEDBACK = "feedback"
    """Human feedback on agent accuracy and rule tuning.
    
    Examples:
    - "Marked 3 SQL injection findings as false positives; tighten regex"
    - "User confirmed all buffer overflow findings in C code; increase sensitivity"
    """


# Friendly descriptions for each memory type
MEMORY_TYPE_DESCRIPTIONS: dict[MemoryType, str] = {
    MemoryType.FINDING: "Learned vulnerability patterns and false positive markers",
    MemoryType.PATTERN: "Recognized code patterns and anti-patterns",
    MemoryType.CONTEXT: "Project-specific context (tech stack, conventions)",
    MemoryType.DECISION: "Past decisions and their outcomes",
    MemoryType.FEEDBACK: "Human feedback on agent accuracy",
}

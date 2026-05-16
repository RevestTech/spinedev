"""
Base parser class and data structures for code analysis.

Provides the abstract BaseParser interface and dataclasses for representing
parsed code structures (functions, classes, imports). All language-specific
parsers inherit from BaseParser and implement the parse() method.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── Data Structures ────────────────────────────────────────────────────


@dataclass
class ImportInfo:
    """Information about a module import or require statement.

    Attributes:
        module: The imported module name (e.g., "os", "react")
        names: List of imported names (e.g., ["join", "sep"] for "from os import...")
        is_from: Whether this is a "from X import Y" style import
        alias: Aliased name if imported as something else (e.g., "import pandas as pd")
        line_number: Line where the import appears (1-indexed)
    """

    module: str
    names: List[str] = field(default_factory=list)
    is_from: bool = False
    alias: Optional[str] = None
    line_number: int = 0


@dataclass
class FunctionInfo:
    """Information about a function or method.

    Attributes:
        name: Function name
        start_line: Line where function starts (1-indexed)
        end_line: Line where function ends (1-indexed)
        args: List of parameter names
        decorators: List of decorator names (e.g., ["property", "staticmethod"])
        is_async: Whether the function is async/coroutine
        docstring: Docstring if present
    """

    name: str
    start_line: int
    end_line: int
    args: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    is_async: bool = False
    docstring: Optional[str] = None


@dataclass
class ClassInfo:
    """Information about a class definition.

    Attributes:
        name: Class name
        start_line: Line where class starts (1-indexed)
        end_line: Line where class ends (1-indexed)
        methods: List of methods defined in this class
        bases: List of base class names (e.g., ["Exception"] for class MyError(Exception))
        decorators: List of decorator names
    """

    name: str
    start_line: int
    end_line: int
    methods: List[FunctionInfo] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)


@dataclass
class ParseResult:
    """Complete result from parsing a source file.

    Attributes:
        functions: Top-level functions (and module-level ones)
        classes: All class definitions
        imports: All imports/requires
        top_level_statements: Count of top-level statements (for complexity)
        line_count: Total lines in the file
        complexity_score: Estimated McCabe-style cyclomatic complexity
    """

    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    top_level_statements: int = 0
    line_count: int = 0
    complexity_score: float = 0.0

    def __repr__(self) -> str:
        return (
            f"<ParseResult "
            f"functions={len(self.functions)} "
            f"classes={len(self.classes)} "
            f"imports={len(self.imports)} "
            f"complexity={self.complexity_score:.1f}>"
        )


# ── Abstract Base Parser ──────────────────────────────────────────────


class BaseParser(ABC):
    """Abstract base class for language-specific code parsers.

    All parsers (Python, JavaScript, TypeScript) inherit from this and
    implement the parse() method to extract structural information from
    source code.

    The parsers are used by ISO agents to understand code context without
    needing a full build environment or language runtime.
    """

    def __init__(self) -> None:
        """Initialize the parser."""
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def parse(self, source: str, file_path: str = "") -> ParseResult:
        """Parse source code and extract structural information.

        Args:
            source: The source code as a string
            file_path: Optional file path (used for context/logging)

        Returns:
            ParseResult containing functions, classes, imports, and metrics

        Raises:
            SyntaxError: If the source code has severe syntax issues
        """
        ...

    def _estimate_complexity(self, result: ParseResult) -> float:
        """Estimate cyclomatic complexity based on parsed structure.

        A simple heuristic: base complexity of 1, plus 1 for each:
        - Function definition
        - Class definition
        - If/else statement equivalent

        This is a rough estimate and may be overridden by subclasses
        for more accurate language-specific complexity calculation.

        Args:
            result: The ParseResult to analyze

        Returns:
            Estimated complexity score
        """
        complexity = 1.0  # Base
        complexity += len(result.functions) * 0.5
        complexity += len(result.classes) * 0.3
        complexity += sum(len(c.methods) for c in result.classes) * 0.5
        return min(complexity, 50.0)  # Cap at 50 (prevent overflow)

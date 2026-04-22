"""
Code parsers module for Tron — extracts structural information from source code.

This module provides language-specific parsers (Python, JavaScript, TypeScript)
that extract functions, classes, imports, and complexity metrics from source code.

The parsers are used by ISO agents to understand code context without needing
a full build environment or language runtime.

Public API:
    - get_parser(language: str) -> BaseParser
    - BaseParser, FunctionInfo, ClassInfo, ImportInfo, ParseResult (data classes)

Example:
    from tron.parsers import get_parser

    parser = get_parser("python")
    result = parser.parse(source_code, file_path="example.py")

    print(f"Functions: {len(result.functions)}")
    print(f"Classes: {len(result.classes)}")
    print(f"Complexity: {result.complexity_score}")

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1
"""

from __future__ import annotations

import logging
from typing import Optional

from tron.parsers.base import (
    BaseParser,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
)
from tron.parsers.javascript import JavaScriptParser
from tron.parsers.python import PythonParser
from tron.parsers.typescript import TypeScriptParser

logger = logging.getLogger(__name__)

__all__ = [
    "get_parser",
    "BaseParser",
    "PythonParser",
    "JavaScriptParser",
    "TypeScriptParser",
    "ParseResult",
    "FunctionInfo",
    "ClassInfo",
    "ImportInfo",
]


def get_parser(language: str) -> BaseParser:
    """Get a parser instance for the specified language.

    Args:
        language: Language name. Supported: "python", "javascript", "typescript",
                 "js", "ts" (case-insensitive, aliases supported)

    Returns:
        An initialized parser instance for the language

    Raises:
        ValueError: If language is not supported
    """
    language_lower = language.lower().strip()

    # Normalize aliases
    language_map = {
        "python": PythonParser,
        "python3": PythonParser,
        "py": PythonParser,
        "javascript": JavaScriptParser,
        "js": JavaScriptParser,
        "node": JavaScriptParser,
        "typescript": TypeScriptParser,
        "ts": TypeScriptParser,
    }

    if language_lower not in language_map:
        supported = ", ".join(sorted(language_map.keys()))
        raise ValueError(
            f"Unsupported language: '{language}'. "
            f"Supported languages: {supported}"
        )

    parser_class = language_map[language_lower]
    logger.debug("Creating parser for language '%s': %s", language, parser_class.__name__)

    return parser_class()

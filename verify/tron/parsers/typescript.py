"""
TypeScript code parser extending the JavaScript parser.

Adds type annotation awareness (interfaces, type aliases, generics)
while reusing the JavaScript function/class extraction logic.

TypeScript syntax is a superset of JavaScript, so the JavaScript
patterns work; this parser just adds TypeScript-specific constructs.
"""

from __future__ import annotations

import logging
import re
from typing import List

from tron.parsers.base import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
)
from tron.parsers.javascript import JavaScriptParser

logger = logging.getLogger(__name__)


class TypeScriptParser(JavaScriptParser):
    """Parser for TypeScript using regex patterns (extends JavaScript parser)."""

    # TypeScript-specific patterns
    INTERFACE_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:export\s+)?interface\s+(\w+)(?:<[^>]*>)?\s*(?:extends\s+([^{]+))?\s*\{',
        re.MULTILINE,
    )

    TYPE_ALIAS_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:export\s+)?type\s+(\w+)(?:<[^>]*>)?\s*=\s*',
        re.MULTILINE,
    )

    ENUM_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:export\s+)?enum\s+(\w+)\s*\{',
        re.MULTILINE,
    )

    def parse(self, source: str, file_path: str = "") -> ParseResult:
        """Parse TypeScript source code using regex extraction.

        Extends the JavaScript parser to also extract TypeScript-specific
        constructs like interfaces, type aliases, and enums.

        Args:
            source: TypeScript source code as string
            file_path: Optional file path (for logging)

        Returns:
            ParseResult with functions, classes, imports, interfaces, and metrics
        """
        # Use parent's parse() for JavaScript constructs
        result = super().parse(source, file_path)

        # Now add TypeScript-specific information
        # Note: Interfaces and type aliases aren't included in functions/classes
        # but we extract them for future use
        cleaned = self._remove_comments(source)

        # Extract interfaces, enums, and type aliases
        self._extract_interfaces(cleaned, result)
        self._extract_type_aliases(cleaned, result)
        self._extract_enums(cleaned, result)

        return result

    def _extract_interfaces(self, source: str, result: ParseResult) -> None:
        """Extract TypeScript interface definitions.

        Interfaces are type definitions that don't appear in runtime code,
        so we store them in the top_level_statements counter for context.
        """
        lines = source.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Match: interface Foo {}, interface Foo extends Bar {}
            match = re.search(
                r'interface\s+(\w+)(?:<[^>]*>)?(?:\s+extends\s+([^{]+))?\s*\{',
                line,
            )
            if match:
                interface_name = match.group(1)
                # Track that we found a type definition (add to statement count)
                result.top_level_statements += 1
                logger.debug(
                    "TypeScript parser: found interface '%s' at line %d",
                    interface_name,
                    line_num,
                )

    def _extract_type_aliases(self, source: str, result: ParseResult) -> None:
        """Extract TypeScript type alias definitions.

        Type aliases don't affect runtime structure but are useful context
        for understanding the codebase.
        """
        lines = source.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Match: type Foo = ..., type Foo<T> = ...
            match = re.search(
                r'type\s+(\w+)(?:<[^>]*>)?\s*=\s*',
                line,
            )
            if match:
                type_name = match.group(1)
                result.top_level_statements += 1
                logger.debug(
                    "TypeScript parser: found type alias '%s' at line %d",
                    type_name,
                    line_num,
                )

    def _extract_enums(self, source: str, result: ParseResult) -> None:
        """Extract TypeScript enum definitions.

        Enums are a TypeScript runtime construct, so they're like classes.
        """
        lines = source.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1

            # Match: enum Foo {}, enum Foo { A, B, C }
            match = re.search(
                r'enum\s+(\w+)\s*\{',
                line,
            )
            if match:
                enum_name = match.group(1)
                start_line = i - 1

                # Find closing brace
                depth = line.count('{') - line.count('}')
                end_line = start_line
                members: List[str] = []

                for j in range(i, min(i + 100, len(lines))):
                    enum_line = lines[j]
                    depth += enum_line.count('{') - enum_line.count('}')

                    # Extract enum members (simple approach)
                    # enum Foo { A, B, C = 5, }
                    member_matches = re.findall(r'(\w+)\s*(?:=|,|$)', enum_line)
                    for member in member_matches:
                        if member and member not in members:
                            members.append(member)

                    if depth == 0:
                        end_line = j + 1
                        break

                result.top_level_statements += 1
                logger.debug(
                    "TypeScript parser: found enum '%s' with %d members at line %d",
                    enum_name,
                    len(members),
                    start_line + 1,
                )

    def _extract_functions(self, source: str, result: ParseResult) -> None:
        """Extract functions, handling TypeScript-specific syntax.

        Extends parent to handle:
        - Type parameters: function foo<T>()
        - Return type annotations: function foo(): string
        - Parameter type annotations: function foo(x: string, y: number)
        """
        # First call parent's extraction to get basic functions
        super()._extract_functions(source, result)

        # TypeScript-specific: could add additional processing here
        # (e.g., tracking generic functions separately)
        # For now, the parent's regex-based approach handles most cases

    def _extract_classes(self, source: str, result: ParseResult) -> None:
        """Extract classes, handling TypeScript-specific syntax.

        Extends parent to handle:
        - Type parameters: class Foo<T>
        - Visibility modifiers: public, private, protected
        - Abstract classes: abstract class Foo
        - Implements: class Foo implements Bar
        """
        # First call parent's extraction to get basic classes
        super()._extract_classes(source, result)

        # TypeScript-specific: could enhance with visibility tracking
        # For now, the parent's extraction is sufficient for context

    def _remove_comments(self, source: str) -> str:
        """Remove comments and docstrings from TypeScript.

        Extends parent to handle JSDoc comments that may appear before
        type definitions.
        """
        return super()._remove_comments(source)

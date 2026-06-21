"""
JavaScript/TypeScript code parser using regex-based extraction.

Since we can't rely on Node.js AST parsers being available, this parser
uses carefully crafted regex patterns to extract structural information
from JavaScript and TypeScript source code.

This is a best-effort parser — it won't handle every edge case but
captures the major code structures needed for context extraction.

Limitations:
- JSX/TSX support is basic (regex, not full AST)
- Complex nested structures may be missed
- Comments and string contents are roughly stripped before analysis
"""

from __future__ import annotations

import logging
import re
from typing import List

from tron.parsers.base import (
    BaseParser,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
)

logger = logging.getLogger(__name__)


class JavaScriptParser(BaseParser):
    """Parser for JavaScript/TypeScript using regex patterns."""

    # Regex patterns for various constructs
    # Note: These are pragmatic patterns; they won't handle every edge case

    # Import statements: import foo from "bar", require("foo"), etc.
    IMPORT_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:import|const|let|var)\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+(?:from\s+)?["\']([^"\']+)["\']',
        re.MULTILINE,
    )

    # require() pattern
    REQUIRE_PATTERN = re.compile(
        r'(?:const|let|var|import)\s+(?:\{[^}]*\}|[\w\s,]+)\s*=\s*require\(["\']([^"\']+)["\']\)',
        re.MULTILINE,
    )

    # Function declarations: function foo() {}, const foo = () => {}
    FUNCTION_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:async\s+)?(?:function|const|let|var)\s+(\w+)\s*(?:=.*?)?\([^)]*\)\s*(?::|=>)?\s*\{',
        re.MULTILINE,
    )

    # Class declarations: class Foo {}, class Foo extends Bar {}
    CLASS_PATTERN = re.compile(
        r'(?:^|\n)\s*(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?\s*\{',
        re.MULTILINE,
    )

    # Method declarations inside classes: method() {}, async method() {}
    METHOD_PATTERN = re.compile(
        r'^\s*(?:async\s+)?(?:get|set)?(?:static\s+)?(\w+)\s*\([^)]*\)\s*(?::|=>)?\s*\{',
        re.MULTILINE,
    )

    def parse(self, source: str, file_path: str = "") -> ParseResult:
        """Parse JavaScript/TypeScript source code using regex extraction.

        Args:
            source: JavaScript/TypeScript source code as string
            file_path: Optional file path (for logging)

        Returns:
            ParseResult with functions, classes, imports, and metrics
        """
        result = ParseResult(
            line_count=len(source.splitlines()),
        )

        # Remove comments to avoid false matches (rough approach)
        cleaned = self._remove_comments(source)

        # Extract imports
        self._extract_imports(cleaned, result)

        # Extract classes
        self._extract_classes(cleaned, result)

        # Extract functions
        self._extract_functions(cleaned, result)

        # Estimate complexity
        result.complexity_score = self._estimate_complexity(result)

        return result

    def _remove_comments(self, source: str) -> str:
        """Remove single-line and multi-line comments from JavaScript.

        Note: This is a rough implementation and may not handle all cases
        of strings containing comment-like patterns.
        """
        # Remove single-line comments // ...
        source = re.sub(r'//.*?$', '', source, flags=re.MULTILINE)

        # Remove multi-line comments /* ... */
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)

        return source

    def _extract_imports(self, source: str, result: ParseResult) -> None:
        """Extract import statements from source."""
        lines = source.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('//'):
                continue

            # Check for import statement: import foo from "bar"
            match = re.search(
                r'import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|[\w\s,]+)\s+from\s+["\']([^"\']+)["\']',
                line,
            )
            if match:
                module = match.group(1)
                # Extract imported names from curly braces
                names_match = re.search(r'\{([^}]*)\}', line)
                names = []
                if names_match:
                    names_str = names_match.group(1)
                    names = [n.strip().split(' as ')[0] for n in names_str.split(',')]
                else:
                    # Default import: import foo from "bar"
                    default_match = re.search(r'import\s+(\w+)', line)
                    if default_match:
                        names = [default_match.group(1)]

                result.imports.append(
                    ImportInfo(
                        module=module,
                        names=names,
                        is_from=True,
                        line_number=line_num,
                    )
                )

            # Check for require: const foo = require("bar")
            match = re.search(
                r'(?:const|let|var)\s+(?:\{[^}]*\}|(\w+))\s*=\s*require\(["\']([^"\']+)["\']\)',
                line,
            )
            if match:
                var_name = match.group(1) or ""
                module = match.group(2)
                names = [var_name] if var_name else []

                result.imports.append(
                    ImportInfo(
                        module=module,
                        names=names,
                        is_from=False,
                        line_number=line_num,
                    )
                )

    def _extract_functions(self, source: str, result: ParseResult) -> None:
        """Extract function declarations from source."""
        lines = source.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1

            # Skip if inside a class (rough heuristic: check for preceding class)
            # For now, extract all functions at any level

            # Match: function foo() {}, const foo = () => {}, async function foo() {}
            match = re.search(
                r'(?:async\s+)?(?:function\s+)?(\w+)\s*=?\s*(?:function)?\s*\(([^)]*)\)',
                line,
            )
            if match:
                name = match.group(1)
                args_str = match.group(2)
                args = self._parse_args(args_str)
                is_async = 'async' in line

                # Find closing brace to estimate end line (simplified)
                start_line = i - 1
                depth = line.count('{') - line.count('}')
                end_line = start_line

                for j in range(i, min(i + 200, len(lines))):
                    depth += lines[j].count('{') - lines[j].count('}')
                    if depth == 0:
                        end_line = j + 1
                        break

                func = FunctionInfo(
                    name=name,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                    args=args,
                    is_async=is_async,
                )
                result.functions.append(func)

    def _extract_classes(self, source: str, result: ParseResult) -> None:
        """Extract class declarations from source."""
        lines = source.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1

            # Match: class Foo {}, class Foo extends Bar {}, class Foo<T> {}
            match = re.search(
                r'class\s+(\w+)(?:<[^>]*>)?(?:\s+extends\s+(\w+)(?:<[^>]*>)?)?\s*(?:implements\s+[\w<>,\s]+)?\s*\{',
                line,
            )
            if match:
                name = match.group(1)
                base = match.group(2)
                start_line = i - 1

                # Find class body closing brace
                depth = line.count('{') - line.count('}')
                end_line = start_line
                methods: List[FunctionInfo] = []

                for j in range(i, min(i + 500, len(lines))):
                    class_line = lines[j]
                    depth += class_line.count('{') - class_line.count('}')

                    # Look for method declarations inside class
                    method_match = re.search(
                        r'^\s*(?:async\s+)?(?:static\s+)?(\w+)\s*\(([^)]*)\)',
                        class_line,
                    )
                    if method_match and depth > 0:
                        method_name = method_match.group(1)
                        args_str = method_match.group(2)
                        args = self._parse_args(args_str)
                        is_async = 'async' in class_line

                        method = FunctionInfo(
                            name=method_name,
                            start_line=j + 1,
                            end_line=j + 1,  # Simplified
                            args=args,
                            is_async=is_async,
                        )
                        methods.append(method)

                    if depth == 0:
                        end_line = j + 1
                        break

                klass = ClassInfo(
                    name=name,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                    methods=methods,
                    bases=[base] if base else [],
                )
                result.classes.append(klass)

    @staticmethod
    def _parse_args(args_str: str) -> List[str]:
        """Parse parameter list from function arguments string.

        Handles: foo, bar, ...rest, {a, b}, etc.
        """
        if not args_str.strip():
            return []

        args = []
        for arg in args_str.split(','):
            arg = arg.strip()
            # Skip empty args and type annotations
            if arg and arg not in ('=', ''):
                # Remove default values: foo = 'bar' -> foo
                arg_name = arg.split('=')[0].strip()
                # Remove type annotations: foo: string -> foo
                arg_name = arg_name.split(':')[0].strip()
                # Handle destructuring: {a, b} -> use as single param
                if arg_name.startswith('{') and arg_name.endswith('}'):
                    arg_name = '<destructured>'
                if arg_name:
                    args.append(arg_name)

        return args

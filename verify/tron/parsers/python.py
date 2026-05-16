"""
Python code parser using the ast module from the standard library.

Extracts function signatures, class definitions, imports, and complexity
metrics from Python source code without requiring external dependencies.

Uses the built-in ast.parse() to safely analyze Python syntax and extract
structural information.
"""

from __future__ import annotations

import ast
import logging
from typing import List, Optional

from tron.parsers.base import (
    BaseParser,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParseResult,
)

logger = logging.getLogger(__name__)


class PythonParser(BaseParser):
    """Parser for Python source code using ast module."""

    def parse(self, source: str, file_path: str = "") -> ParseResult:
        """Parse Python source code and extract structural information.

        Args:
            source: Python source code as string
            file_path: Optional file path (for logging)

        Returns:
            ParseResult with functions, classes, imports, and metrics

        Raises:
            SyntaxError: If source has syntax errors
        """
        result = ParseResult(
            line_count=len(source.splitlines()),
        )

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning(
                "Python parser: syntax error in %s at line %d: %s",
                file_path or "<unknown>",
                exc.lineno or 0,
                exc.msg,
            )
            raise

        # Extract imports, functions, and classes at module level
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._extract_import(node, result)

        # Extract module-level functions and classes (not in ast.walk, order matters)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                result.functions.append(
                    self._extract_function(node, is_async=False)
                )
            elif isinstance(node, ast.AsyncFunctionDef):
                result.functions.append(
                    self._extract_function(node, is_async=True)
                )
            elif isinstance(node, ast.ClassDef):
                result.classes.append(self._extract_class(node))

            # Count top-level statements for complexity
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.If,
                    ast.While,
                    ast.For,
                    ast.With,
                    ast.Try,
                ),
            ):
                result.top_level_statements += 1

        # Calculate complexity based on structure
        result.complexity_score = self._estimate_complexity(result)

        return result

    def _extract_import(self, node: ast.stmt, result: ParseResult) -> None:
        """Extract import information from Import or ImportFrom node."""
        if isinstance(node, ast.Import):
            # import foo, import foo as bar
            for alias in node.names:
                import_info = ImportInfo(
                    module=alias.name,
                    names=[alias.name],
                    is_from=False,
                    alias=alias.asname,
                    line_number=node.lineno,
                )
                result.imports.append(import_info)

        elif isinstance(node, ast.ImportFrom):
            # from foo import bar, baz
            module = node.module or ""
            names = []
            for alias in node.names:
                names.append(alias.name)

            import_info = ImportInfo(
                module=module,
                names=names,
                is_from=True,
                line_number=node.lineno,
            )
            result.imports.append(import_info)

    def _extract_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool = False
    ) -> FunctionInfo:
        """Extract function information from FunctionDef or AsyncFunctionDef."""
        # Extract parameter names
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        # Include *args if present
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        # Include **kwargs if present
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")

        # Extract decorators
        decorators = [
            self._get_decorator_name(dec) for dec in node.decorator_list
        ]

        # Extract docstring
        docstring = ast.get_docstring(node)

        # Determine end line (last statement in function)
        end_line = node.end_lineno or node.lineno

        return FunctionInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=end_line,
            args=args,
            decorators=decorators,
            is_async=is_async,
            docstring=docstring,
        )

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        """Extract class information from ClassDef node."""
        # Extract base class names
        bases = [self._get_node_name(base) for base in node.bases]

        # Extract decorators
        decorators = [
            self._get_decorator_name(dec) for dec in node.decorator_list
        ]

        # Extract methods
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                methods.append(self._extract_function(item, is_async=False))
            elif isinstance(item, ast.AsyncFunctionDef):
                methods.append(self._extract_function(item, is_async=True))

        # Determine end line
        end_line = node.end_lineno or node.lineno

        return ClassInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=end_line,
            methods=methods,
            bases=bases,
            decorators=decorators,
        )

    @staticmethod
    def _get_decorator_name(node: ast.expr) -> str:
        """Extract decorator name from decorator node.

        Handles simple decorators like @property, @staticmethod,
        and call decorators like @functools.wraps(func).
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            # @decorator() or @functools.wraps()
            if isinstance(node.func, ast.Name):
                return node.func.id
            elif isinstance(node.func, ast.Attribute):
                return node.func.attr
        return "<unknown>"

    @staticmethod
    def _get_node_name(node: ast.expr) -> str:
        """Extract a simple name from an AST node.

        Handles Name nodes (e.g., "int", "BaseClass") and
        Attribute nodes (e.g., "collections.abc.Iterator").
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # Recursively build qualified name like "foo.bar.baz"
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return "<unknown>"

    def _estimate_complexity(self, result: ParseResult) -> float:
        """Estimate McCabe-style cyclomatic complexity for Python code.

        Counts:
        - Each if/elif/else adds 1
        - Each for/while adds 1
        - Each except clause adds 1
        - Functions and classes add structure but not direct complexity

        Returns a score from 1.0 (simple) to infinity (very complex).
        """
        # This is a simplified estimate; a full implementation would
        # walk the AST and count decision points. For now, use the
        # base implementation from BaseParser.
        return super()._estimate_complexity(result)

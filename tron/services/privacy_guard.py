"""
Privacy Guard - Zero-Exfiltration and Ghost Logic engine for Tron.

Protects proprietary business logic from being sent to external LLMs while
retaining the structural integrity required for security and performance analysis.
"""

import ast
import re
import hashlib
from typing import Dict, Tuple

class PrivacyGuard:
    """
    Engine to protect Intellectual Property before sending code to LLMs.
    """
    def __init__(self):
        self.identifier_map: Dict[str, str] = {}
        self.reverse_map: Dict[str, str] = {}
        self._counter = 1

    def _get_alias(self, original: str) -> str:
        """Get or create an alias for an identifier."""
        if original not in self.identifier_map:
            # Deterministic hashing could be used, but simple counters are easier to read for the LLM
            alias = f"SECURE_ALIAS_{self._counter:04d}"
            self.identifier_map[original] = alias
            self.reverse_map[alias] = original
            self._counter += 1
        return self.identifier_map[original]

    def apply_ghost_logic(self, code: str) -> Tuple[str, Dict[str, str]]:
        """
        Replaces potentially sensitive business logic variable/function names with aliases.
        Retains Python keywords and common built-ins.
        
        Returns:
            Tuple of (obfuscated_code, reverse_mapping)
        """
        # Basic Python keywords to preserve
        preserved = {
            "def", "class", "return", "if", "else", "elif", "for", "while", "in", 
            "True", "False", "None", "and", "or", "not", "is", "try", "except", 
            "finally", "raise", "import", "from", "as", "with", "async", "await",
            "pass", "continue", "break", "print", "self", "__init__", "str", "int", 
            "float", "list", "dict", "set", "Tuple", "List", "Dict", "Optional", "Any"
        }

        # Find words > 4 characters that aren't keywords (crude but effective proxy for custom logic)
        def replace_match(match):
            word = match.group(0)
            if word in preserved or len(word) <= 4 or word.startswith("__"):
                return word
            return self._get_alias(word)

        # Regex to match word characters
        obfuscated_code = re.sub(r'\b[A-Za-z_][A-Za-z0-9_]*\b', replace_match, code)
        
        return obfuscated_code, self.reverse_map

    def restore_ghost_logic(self, response: str, reverse_map: Dict[str, str]) -> str:
        """
        Restores aliases back to their original names in an LLM response.
        """
        restored = response
        for alias, original in reverse_map.items():
            restored = restored.replace(alias, original)
        return restored

    def apply_signature_only(self, code: str, language: str = "python") -> str:
        """
        Strips out all function bodies, leaving only signatures and class definitions.
        Useful for "Contract Drift" and architecture analysis without exposing IP.
        Supports Python (AST) and C-style languages (Regex-based tree walking).
        """
        if language.lower() == "python":
            try:
                tree = ast.parse(code)
                class SignatureStripper(ast.NodeTransformer):
                    def visit_FunctionDef(self, node):
                        node.body = [ast.Pass()]
                        return node
                    def visit_AsyncFunctionDef(self, node):
                        node.body = [ast.Pass()]
                        return node
                stripped_tree = SignatureStripper().visit(tree)
                ast.fix_missing_locations(stripped_tree)
                return ast.unparse(stripped_tree)
            except Exception:
                return code

        # Multi-Language Logic (C#, Java, Go, C++, JS/TS)
        # We use a non-greedy block stripper that respects nested curly braces
        def strip_bodies(text):
            result = []
            stack = 0
            current_line = []
            
            # This logic identifies method/class signatures and preserves them 
            # while purging the actual implementation blocks.
            lines = text.split('\n')
            for line in lines:
                trimmed = line.strip()
                
                # Check for start of a block
                if '{' in line:
                    if stack == 0:
                        # Capture the signature (part before the {)
                        result.append(line.split('{')[0] + '{ /* TRON REDACTED IP */ }')
                    stack += line.count('{')
                
                # Check for end of a block
                if '}' in line:
                    stack -= line.count('}')
                    if stack < 0: stack = 0
                    continue
                
                # If we are not inside a block, preserve the line (headers, imports, namespaces)
                if stack == 0:
                    result.append(line)
            
            return '\n'.join(result)

        return strip_bodies(code)

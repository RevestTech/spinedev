```markdown
# spinedev Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `spinedev` Python repository. It covers file organization, code style, commit message formatting, and testing patterns. By following these guidelines, contributors can ensure consistency and maintainability across the codebase.

## Coding Conventions

### File Naming
- Use **snake_case** for all Python files.
  - Example: `data_processor.py`, `utils/helpers.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import helper_function
    from ..models import DataModel
    ```

### Export Style
- Use **named exports** by defining `__all__` in modules.
  - Example:
    ```python
    __all__ = ['MyClass', 'my_function']
    ```

### Commit Messages
- Follow **conventional commit** style.
- Use the `docs` prefix for documentation-related commits.
- Keep commit messages concise (average ~45 characters).
  - Example:
    ```
    docs: update README with installation steps
    ```

## Workflows

### Documentation Update
**Trigger:** When updating or improving documentation.
**Command:** `/update-docs`

1. Make changes to documentation files (e.g., `README.md`, `docs/`).
2. Stage your changes:  
   `git add README.md`
3. Commit using the conventional commit format:  
   `git commit -m "docs: clarify setup instructions"`
4. Push your changes:  
   `git push origin <branch-name>`

## Testing Patterns

- **Framework:** Not explicitly detected; ensure to use a consistent testing approach.
- **Test File Pattern:** Use `*.test.ts` for test files (suggests some TypeScript usage for testing).
  - Example: `my_module.test.ts`
- Place test files alongside the modules they test or in a dedicated `tests/` directory.

## Commands
| Command        | Purpose                                    |
|----------------|--------------------------------------------|
| /update-docs   | Standardize documentation update workflow  |
```
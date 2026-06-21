"""
Path-safety helpers for user-supplied filesystem paths.

Two classes of caller:

  * **Admin API input** — e.g. ``Project.agent_handoff_path``. The client
    supplies a string, we want to ensure it canonicalises to something under
    an operator-configured root before we write to it.
  * **Repo scanner** — reads files out of a cloned repo; a payload inside
    the repo (a symlink, a ``../`` dance) must not be able to trick us
    into reading something outside the clone root.

Both are served by the primitives here. Callers stay in charge of what
"outside the root" means — we just do the canonicalisation and the
relative-to check.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class UnsafePathError(ValueError):
    """Raised when a caller-supplied path fails the safety check.

    Subclasses ``ValueError`` so FastAPI converts it to a 422 when raised
    inside a Pydantic validator, but callers in the worker can catch it
    explicitly.
    """


def parse_allowed_roots(raw: str | None) -> tuple[Path, ...]:
    """Parse a comma-separated env-var value into canonical absolute paths.

    Entries are ``strip()``'d, empty ones dropped, ``~`` is expanded, and
    each result is ``.resolve(strict=False)``'d so any symlinks along the
    way are collapsed. We accept non-existent roots here — operators may
    configure a root that only materialises at runtime (mounted volume,
    etc.); the per-call check catches that later.
    """
    if not raw:
        return ()
    roots: list[Path] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        p = Path(entry).expanduser()
        if not p.is_absolute():
            # An allowlist root that isn't absolute is almost certainly an
            # operator typo. Loud failure > silent "everything under CWD".
            raise UnsafePathError(
                f"allowlist root {entry!r} is not an absolute path; "
                "use absolute paths in TRON_AGENT_HANDOFF_ALLOWED_ROOTS "
                "and friends"
            )
        roots.append(p.resolve(strict=False))
    return tuple(roots)


def resolve_under_allowlist(
    raw_path: str,
    allowed_roots: Iterable[Path],
) -> Path:
    """Canonicalise ``raw_path`` and ensure it is under one of ``allowed_roots``.

    Returns the resolved path on success. Raises :class:`UnsafePathError`
    if:

      * the allowlist is empty (treating this as "feature disabled" is the
        caller's job — we default to refusing);
      * the path is not absolute;
      * the path, after ``.resolve()``, is not under any allowed root;
      * any symlink along the way points outside the root.

    The check uses ``Path.resolve(strict=False)``: non-existent leaf paths
    are fine (the caller may be about to create the file), but every
    symlink that DOES exist is followed, so a malicious ``resolves/..``
    dance or a symlink redirect is caught.
    """
    roots = tuple(allowed_roots)
    if not roots:
        raise UnsafePathError(
            "no allowlist roots configured — refusing to accept user-supplied "
            "filesystem path. Set the appropriate TRON_*_ALLOWED_ROOTS env var "
            "in the worker/API environment."
        )

    if not raw_path or not raw_path.strip():
        raise UnsafePathError("path is empty")

    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        raise UnsafePathError(
            f"path {raw_path!r} is not absolute; relative paths are refused "
            "because their meaning depends on the process CWD"
        )

    resolved = p.resolve(strict=False)

    # Under Python 3.9+, Path.is_relative_to exists; we expect 3.12 but use
    # a manual check so this module stays import-safe even in test envs
    # where ``is_relative_to`` isn't yet available.
    def _is_under(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
        except ValueError:
            return False
        return True

    for root in roots:
        if _is_under(resolved, root):
            return resolved

    raise UnsafePathError(
        f"path {raw_path!r} (resolved to {resolved!s}) is not under any "
        f"configured allowlist root ({', '.join(str(r) for r in roots)})"
    )


def open_no_follow(path: Path, *, mode: int = os.O_RDONLY) -> int:
    """``os.open`` with ``O_NOFOLLOW`` — raises ``OSError`` on symlink traversal.

    Use this when you need a file descriptor and want symlinks to be
    rejected at the leaf, not just somewhere along the way. For "read a
    file that I've already verified is under the clone root", this is the
    right primitive — it closes the TOCTOU window between
    ``resolve_under_allowlist`` and the actual read.

    The returned FD is the caller's to close (use ``os.fdopen(fd, ...)``
    or ``open(fd, closefd=True, ...)``).
    """
    flags = mode | os.O_NOFOLLOW
    # O_CLOEXEC when available prevents FD leaks across exec; it's a no-op
    # on platforms that don't support it (Windows), which we don't target
    # for the scanner anyway.
    flags |= getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags)

"""Workspace selection and path confinement."""
from __future__ import annotations

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


class PathEscapeError(WorkspaceError):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def validate(path_str: str) -> "Workspace":
        if not path_str or not path_str.strip():
            raise WorkspaceError("no directory given")
        real = Path(os.path.realpath(os.path.expanduser(path_str.strip())))
        if not real.exists():
            raise WorkspaceError(f"directory does not exist: {path_str}")
        if not real.is_dir():
            raise WorkspaceError(f"not a directory: {path_str}")
        return Workspace(real)

    def resolve(self, rel: str) -> Path:
        """Return the real path inside the root, or raise PathEscapeError. Does no I/O besides realpath."""
        if not isinstance(rel, str) or not rel or "\0" in rel:
            raise PathEscapeError(f"path escapes workspace: {rel!r}")
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        real = Path(os.path.realpath(candidate))
        if real == self.root or self.root in real.parents:
            return real
        raise PathEscapeError(f"path escapes workspace: {rel}")

    def rel(self, p: Path) -> str:
        real = Path(os.path.realpath(p))
        if real == self.root:
            return "."
        return real.relative_to(self.root).as_posix()

    def top_entries(self, limit: int = 30) -> list[str]:
        skip = {".git", ".agent", ".venv", "node_modules", "__pycache__"}
        try:
            children = sorted(self.root.iterdir(), key=lambda c: c.name)
        except OSError:
            return []
        names = [c.name + ("/" if c.is_dir() else "") for c in children if c.name not in skip]
        return names[:limit]

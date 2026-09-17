from __future__ import annotations

import os
from pathlib import Path


class SecurityError(Exception):
    pass


class PathTraversalError(SecurityError):
    pass


class PathGuard:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def resolve_safe_path(self, relative_path: str, allow_root: bool = False) -> Path:
        clean_path = (relative_path or "").strip()
        if "\x00" in clean_path:
            raise PathTraversalError("Karakter null byte terdeteksi dalam path.")

        # Menolak path Windows UNC atau drive letter di luar root jika mutlak
        target_path = Path(clean_path)
        if target_path.is_absolute():
            resolved = target_path.resolve()
        else:
            resolved = (self.workspace_root / clean_path).resolve()

        if resolved == self.workspace_root:
            if allow_root:
                return resolved
            return resolved

        # Memastikan path berada di dalam direktori workspace
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PathTraversalError(
                f"Akses ditolak: path '{clean_path}' berada di luar direktori workspace."
            ) from exc

        return resolved

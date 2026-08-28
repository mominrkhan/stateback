"""Safe project discovery and exclusive local-file creation."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class ProjectFileError(RuntimeError):
    """A project path is unsafe or cannot be created."""


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "stateback.toml").exists():
            return candidate
    raise ProjectFileError(
        "No stateback.toml was found. Run `stateback init` in your project first."
    )


def ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ProjectFileError(f"refusing unsafe project directory: {path}")
        return
    path.mkdir(mode=0o700)


def create_file(path: Path, content: bytes, *, mode: int) -> bool:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ProjectFileError(f"refusing unsafe project file: {path}")
        return False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError:
        return False
    except OSError as exc:
        raise ProjectFileError(f"could not create project file: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    actual_mode = stat.S_IMODE(path.stat().st_mode)
    if actual_mode & ~mode:
        path.chmod(mode)
    return True

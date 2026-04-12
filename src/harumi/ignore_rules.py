from __future__ import annotations

from pathlib import Path


IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    ".cache",
    "__pycache__",
    "dist",
    "build",
}

IGNORED_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
}


def is_ignored_directory(path: Path) -> bool:
    return path.name in IGNORED_DIR_NAMES


def is_ignored_file(path: Path) -> bool:
    return path.name in IGNORED_FILE_NAMES
